#!/usr/bin/env python3
"""Pure check evaluators for Andy. ZERO IO, by design and by test.

WHY THIS FILE HAS NO IO
-----------------------
Every comparison Andy makes is a numeric or set predicate with a tolerance that
`invariants/orbit.md` already states exactly. Those tolerances were prose, so
nothing enforced them and the model was the runtime. Here they are code.

No network, no database, no filesystem, no clock. Everything arrives as a plain
dict. That is what makes the golden-fixture regression suite possible: a
tolerance change that silently un-breaks a check fails a test instead of
shipping. `tests/test_checks.py` asserts the no-IO property directly.

CONTRACT
--------
    evaluate(check, fact) -> Outcome(status, finding)

`status` is one of pass | fail | skip | error, and those four words mean exactly
what the envelope says they mean:

  pass   the predicate held
  fail   the predicate did not hold; `finding` is populated
  skip   the check does not apply, and `finding.detail` carries a reason from
         the CLOSED list in the registry. An unexplained skip is a verification
         failure, never a pass.
  error  the check could not be evaluated. NOT a pass. A non-zero error count
         forces the whole run to BROKEN-INFRA. "Skipped is not a pass" is the
         rule that stops a dead credential from reading as a clean audit.

Severity is read from the registry, never decided here, except where the
registry declares an explicit `severity_split`.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field, asdict
from typing import Any, Callable

SKIP_REASONS = {
    "not_applicable_client_type",
    "no_data_in_window",
    "bootstrap_missing_env",
    "endpoint_unreachable",
    "disabled_in_registry",
}


@dataclass
class Finding:
    """One finding. Mirrors the _winning-library Finding shape deliberately, so
    anyone who has read meta_creative_qa.py already knows this structure."""
    check: str
    severity: str                      # red | yellow | info
    client: str | None = None
    subject: str | None = None         # contact:<id>, appt:<id>, file:<path>#<sym>
    detail: str = ""
    observed: str = ""
    expected: str = ""
    tolerance: str = ""
    source: str = ""
    owner: str = ""
    needs_judgment: bool = False
    judgment_kind: str | None = None
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Outcome:
    status: str                        # pass | fail | skip | error
    finding: Finding | None = None
    observed: Any = None
    expected: Any = None
    delta: float | None = None


# --------------------------------------------------------------------------
# numeric helpers
# --------------------------------------------------------------------------

def _num(v: Any) -> float:
    """Coerce to float, raising a message that names the offender.

    Solve, do not defer: Meta returns spend as a STRING, Neon returns Decimal,
    and the API returns JSON numbers. Every one of those must compare equal.
    """
    if v is None:
        raise ValueError("value is None")
    if isinstance(v, bool):
        raise ValueError(f"refusing to treat bool {v!r} as a number")
    try:
        f = float(v)
    except (TypeError, ValueError) as e:
        raise ValueError(f"not numeric: {v!r}") from e
    if math.isnan(f) or math.isinf(f):
        raise ValueError(f"not finite: {v!r}")
    return f


def relative_delta(truth: float, app: float) -> float:
    """|truth - app| / |truth|, with 0-vs-0 treated as agreement.

    Guarding the zero denominator matters: a client with no spend in window is
    the COMMON case, not an edge case, and dividing by it would turn every quiet
    client into a spurious blocker.
    """
    if truth == 0 and app == 0:
        return 0.0
    if truth == 0:
        return float("inf")
    return abs(truth - app) / abs(truth)


# --------------------------------------------------------------------------
# comparators. each returns (ok: bool, observed, expected, delta, note)
# --------------------------------------------------------------------------

def _cmp_relative_pct(fact, check):
    truth, app = _num(fact["truth"]), _num(fact["app"])
    tol = check.get("tolerance", 0.05)
    override = check.get("tolerance_override") or {}
    note = ""
    if fact.get("is_most_recent_day") and "most_recent_day_in_window" in override:
        tol = override["most_recent_day_in_window"]
        note = "loosened for the most recent day (Meta still aggregating)"
    d = relative_delta(truth, app)
    return d <= tol, app, truth, d, note


def _cmp_absolute_pp(fact, check):
    truth, app = _num(fact["truth"]), _num(fact["app"])
    tol = check.get("tolerance", 0.001)
    d = abs(truth - app)
    return d <= tol, app, truth, d, ""


def _cmp_exact(fact, check):
    truth, app = fact["truth"], fact["app"]
    try:
        t, a = _num(truth), _num(app)
        return t == a, a, t, abs(t - a), ""
    except ValueError:
        return truth == app, app, truth, None, ""


def _cmp_per_field(fact, check):
    """Several sub-metrics, each with its own comparator and tolerance.

    Exists because ORBIT-A4 bundles CPC/CPM (relative) with CTR (absolute pp).
    Collapsing them to one tolerance is the bug this shape prevents.
    """
    spec = check.get("per_field") or {}
    truth, app = fact["truth"], fact["app"]
    if not isinstance(truth, dict) or not isinstance(app, dict):
        raise ValueError("per_field expects dict truth/app")
    bad = []
    for name, sub in spec.items():
        if name not in truth or name not in app:
            continue
        sub_fact = {"truth": truth[name], "app": app[name],
                    "is_most_recent_day": fact.get("is_most_recent_day")}
        ok, o, e, d, _ = COMPARATORS[sub["comparator"]](sub_fact, sub)
        if not ok:
            unit = "pp" if sub["comparator"] == "absolute_pp" else ""
            bad.append(f"{name}: got {o}, expected {e} (delta {d:.4f}{unit}, tol {sub['tolerance']})")
    return (not bad), app, truth, None, "; ".join(bad)


def _cmp_freshness(fact, check):
    """Age of a timestamp against a threshold. `now` is supplied, never read."""
    ts, now = fact.get("timestamp"), fact.get("now")
    if ts is None:
        return False, None, "a timestamp", None, "no timestamp recorded at all"
    ts, now = _as_dt(ts), _as_dt(now)
    hours = check.get("threshold_hours")
    if hours is None and check.get("threshold_days") is not None:
        hours = check["threshold_days"] * 24
    if hours is None:
        raise ValueError(f"{check['id']}: freshness check has no threshold")
    age_h = (now - ts).total_seconds() / 3600.0
    # threshold_days means "must be this far in the FUTURE" (token expiry).
    if check.get("threshold_days") is not None:
        return -age_h >= hours, ts.isoformat(), f">{hours/24:.0f}d in the future", -age_h / 24, ""
    return age_h <= hours, ts.isoformat(), f"within {hours}h", age_h, ""


def _cmp_latency_ms(fact, check):
    got = _num(fact["observed_ms"])
    tol = _num(check["tolerance"])
    return got <= tol, got, tol, got - tol, ""


def _cmp_timestamp_equal(fact, check):
    a, b = _as_dt(fact["truth"]), _as_dt(fact["app"])
    tol = float(check.get("tolerance_seconds", 1))
    d = abs((a - b).total_seconds())
    return d <= tol, b.isoformat(), a.isoformat(), d, ""


def _cmp_count_equals(fact, check):
    got = int(_num(fact["observed"]))
    exp = int(check["expected"])
    return got == exp, got, exp, got - exp, ""


def _cmp_grep_absent(fact, check):
    hits = fact.get("hits") or []
    return len(hits) == 0, len(hits), 0, len(hits), "; ".join(map(str, hits[:5]))


def _cmp_subset(fact, check):
    sub, sup = set(fact.get("subset") or []), set(fact.get("superset") or [])
    missing = sub - sup
    return not missing, f"{len(missing)} missing", "0 missing", len(missing), \
        ", ".join(sorted(map(str, missing))[:10])


def _cmp_set_membership(fact, check):
    seen, known = set(fact.get("seen") or []), set(fact.get("known") or [])
    skipped = set(fact.get("explicitly_skipped") or [])
    unknown = seen - known - skipped
    return not unknown, f"{len(unknown)} uncatalogued", "0 uncatalogued", len(unknown), \
        ", ".join(sorted(map(str, unknown))[:10])


def _cmp_set_diff(fact, check):
    before, after = set(fact.get("before") or []), set(fact.get("after") or [])
    added, removed = after - before, before - after
    note = f"+{len(added)} / -{len(removed)}"
    return not (added or removed), note, "no change", len(added) + len(removed), note


def _cmp_hash(fact, check):
    exp, got = fact.get("baseline_sha"), fact.get("current_sha")
    if not exp or not got:
        raise ValueError("hash check needs baseline_sha and current_sha")
    return exp == got, got[:12], exp[:12], None, ""


def _cmp_count(fact, check):
    return True, fact.get("observed"), None, None, ""       # INFO-only reporter


def _cmp_note(fact, check):
    return True, fact.get("observed"), None, None, ""       # INFO-only reporter


def _cmp_custom(fact, check):
    """The check computed its own verdict upstream (B5, B6, I1, I2, I3, J4).

    The evaluator still owns the PASS/FAIL word so that every check, however
    specialised, funnels through one place and cannot invent a fifth status.
    """
    if "ok" not in fact:
        raise ValueError(f"{check['id']}: custom check produced no `ok` verdict")
    return bool(fact["ok"]), fact.get("observed"), fact.get("expected"), \
        fact.get("delta"), fact.get("note", "")


COMPARATORS: dict[str, Callable] = {
    "relative_pct": _cmp_relative_pct,
    "absolute_pp": _cmp_absolute_pp,
    "exact": _cmp_exact,
    "per_field": _cmp_per_field,
    "freshness": _cmp_freshness,
    "latency_ms": _cmp_latency_ms,
    "timestamp_equal": _cmp_timestamp_equal,
    "count_equals": _cmp_count_equals,
    "grep_absent": _cmp_grep_absent,
    "subset": _cmp_subset,
    "set_membership": _cmp_set_membership,
    "set_diff": _cmp_set_diff,
    "hash": _cmp_hash,
    "count": _cmp_count,
    "note": _cmp_note,
    "custom": _cmp_custom,
}


def _as_dt(v: Any) -> dt.datetime:
    if isinstance(v, dt.datetime):
        return v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)
    if isinstance(v, str):
        s = v.replace("Z", "+00:00")
        d = dt.datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    raise ValueError(f"not a timestamp: {v!r}")


def _severity_for(check: dict, fact: dict) -> str:
    """Registry severity, unless the registry declares an explicit split."""
    split = check.get("severity_split")
    if split:
        key = fact.get("severity_key")
        if key and key in split:
            return split[key]
        if "otherwise" in split:
            return split["otherwise"]
    return check["severity"]


def evaluate(check: dict, fact: dict) -> Outcome:
    """Evaluate one check against one fact bundle. Never raises."""
    cid = check.get("id", "<unknown>")

    skip = fact.get("skip_reason")
    if skip:
        if skip not in SKIP_REASONS:
            return Outcome("error", Finding(
                check=cid, severity="red", client=fact.get("client"),
                detail=f"illegal skip reason {skip!r}; must be one of {sorted(SKIP_REASONS)}",
                source="andy_checks.evaluate"))
        return Outcome("skip", Finding(
            check=cid, severity="info", client=fact.get("client"),
            detail=skip, source="registry"))

    comparator = check.get("comparator")
    fn = COMPARATORS.get(comparator)
    if fn is None:
        return Outcome("error", Finding(
            check=cid, severity="red", client=fact.get("client"),
            detail=f"no comparator registered for {comparator!r}",
            source="andy_checks.evaluate"))

    try:
        ok, observed, expected, delta, note = fn(fact, check)
    except Exception as e:
        # An evaluation that blew up is an infra failure, never a quiet pass.
        return Outcome("error", Finding(
            check=cid, severity="red", client=fact.get("client"),
            subject=fact.get("subject"),
            detail=f"could not evaluate: {type(e).__name__}: {e}",
            source="andy_checks.evaluate"))

    if ok:
        return Outcome("pass", None, observed, expected, delta)

    tol_desc = ""
    if check.get("tolerance") is not None:
        tol_desc = (f"+/-{check['tolerance']}pp" if comparator == "absolute_pp"
                    else f"+/-{check['tolerance']}")
        if comparator == "relative_pct":
            tol_desc = f"+/-{check['tolerance'] * 100:g}%"
        elif comparator == "exact":
            tol_desc = "exact (0)"

    return Outcome("fail", Finding(
        check=cid,
        severity=_severity_for(check, fact),
        client=fact.get("client"),
        subject=fact.get("subject"),
        detail=note or check.get("title", ""),
        observed=str(observed),
        expected=str(expected),
        tolerance=tol_desc,
        source=check.get("app_source", ""),
        owner=check.get("owner", ""),
        needs_judgment=bool(check.get("judgment")),
        judgment_kind=check.get("judgment_kind"),
        evidence=fact.get("evidence", {}),
    ), observed, expected, delta)


def applies(check: dict, client: dict | None) -> bool:
    """Does this check apply to this client? Capability-derived, never by name."""
    scope = check.get("applies_to", "all")
    if scope == "global":
        return client is None
    if client is None:
        return False
    if scope == "all":
        return True
    caps = client.get("capabilities") or {}
    return bool(caps.get(scope))


def expected_check_count(registry: dict, roster: list[dict]) -> int:
    """How many (check, client) evaluations this run OWES.

    Recomputed independently by andy_verify.py and compared against what the
    engine actually reported. Two derivations, one truth -- the ORBIT-I3
    doctrine applied to Andy himself.
    """
    n = 0
    for chk in registry["checks"]:
        if chk.get("applies_to") == "global":
            n += 1
        else:
            n += sum(1 for c in roster if applies(chk, c))
    return n
