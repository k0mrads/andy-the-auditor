#!/usr/bin/env python3
"""Golden regression suite for Andy's deterministic evaluators.

Convention follows ~/.claude/hooks/tests/: pure stdlib, a table of cases, one
PASS/FAIL line each, exit 1 if anything fails. No pytest.

The point of this suite is stated plainly: a tolerance change that silently
un-breaks a check must FAIL A TEST rather than ship. Andy's tolerances lived in
prose for months and nothing enforced them.

Run: python3 tests/test_checks.py
"""
import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import andy_checks as ac  # noqa: E402

REGISTRY = json.loads((ROOT / "checks" / "registry.json").read_text())
BY_ID = {c["id"]: c for c in REGISTRY["checks"]}

failures: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"        expected {want!r}, got {got!r}")
        failures.append(label)


def status_of(check_id, fact):
    return ac.evaluate(BY_ID[check_id], fact).status


# ---------------------------------------------------------------------------
print("\n--- relative tolerance: spend, +/-5%, +/-10% on the most recent day ---")
check("A1 exact match passes",
      status_of("ORBIT-A1", {"client": "obb", "truth": 408.10, "app": 408.10}), "pass")
check("A1 4.9% drift passes (inside 5%)",
      status_of("ORBIT-A1", {"client": "obb", "truth": 1000.0, "app": 951.0}), "pass")
check("A1 exactly 5.0% drift passes (boundary is inclusive)",
      status_of("ORBIT-A1", {"client": "obb", "truth": 1000.0, "app": 950.0}), "pass")
check("A1 5.1% drift FAILS",
      status_of("ORBIT-A1", {"client": "obb", "truth": 1000.0, "app": 949.0}), "fail")
check("A1 8% drift passes ONLY on the most recent day",
      status_of("ORBIT-A1", {"client": "obb", "truth": 1000.0, "app": 920.0,
                             "is_most_recent_day": True}), "pass")
check("A1 8% drift on a settled day still FAILS",
      status_of("ORBIT-A1", {"client": "obb", "truth": 1000.0, "app": 920.0,
                             "is_most_recent_day": False}), "fail")
check("A1 11% drift fails even on the most recent day",
      status_of("ORBIT-A1", {"client": "obb", "truth": 1000.0, "app": 890.0,
                             "is_most_recent_day": True}), "fail")

print("\n--- the quiet-client trap: 0 vs 0 must not divide by zero ---")
check("A1 no spend on either side passes",
      status_of("ORBIT-A1", {"client": "revlab", "truth": 0, "app": 0}), "pass")
check("A1 Neon shows spend where Meta shows none FAILS (not a crash)",
      status_of("ORBIT-A1", {"client": "revlab", "truth": 0, "app": 42.0}), "fail")

print("\n--- type coercion: Meta returns strings, Neon returns Decimal ---")
check("A1 string '408.10' equals float 408.10",
      status_of("ORBIT-A1", {"client": "obb", "truth": "408.10", "app": 408.10}), "pass")
check("A1 a None value is an ERROR, never a pass",
      status_of("ORBIT-A1", {"client": "obb", "truth": None, "app": 408.10}), "error")
check("A1 a non-numeric value is an ERROR, never a pass",
      status_of("ORBIT-A1", {"client": "obb", "truth": "n/a", "app": 408.10}), "error")

print("\n--- CTR is absolute pp, NOT relative. this is a real bug class ---")
# 1.20% vs 1.25% = 0.05pp apart (passes) but 4.2% relative -- the two rules disagree.
check("A4 CTR 0.05pp apart passes",
      status_of("ORBIT-A4", {"client": "obb",
                             "truth": {"cpc": 1.0, "cpm": 10.0, "ctr": 0.0120},
                             "app":   {"cpc": 1.0, "cpm": 10.0, "ctr": 0.0125}}), "pass")
check("A4 CTR 0.15pp apart FAILS despite being a small relative move",
      status_of("ORBIT-A4", {"client": "obb",
                             "truth": {"cpc": 1.0, "cpm": 10.0, "ctr": 0.0120},
                             "app":   {"cpc": 1.0, "cpm": 10.0, "ctr": 0.0135}}), "fail")
check("A4 CPC 6% off FAILS even when CTR is fine",
      status_of("ORBIT-A4", {"client": "obb",
                             "truth": {"cpc": 1.00, "cpm": 10.0, "ctr": 0.012},
                             "app":   {"cpc": 1.06, "cpm": 10.0, "ctr": 0.012}}), "fail")

print("\n--- counts are EXACT. one lead of drift is a blocker ---")
check("B1 equal counts pass",
      status_of("ORBIT-B1", {"client": "builderpro", "truth": 37, "app": 37}), "pass")
check("B1 off by one FAILS",
      status_of("ORBIT-B1", {"client": "builderpro", "truth": 37, "app": 36}), "fail")
o = ac.evaluate(BY_ID["ORBIT-B1"], {"client": "builderpro", "truth": 37, "app": 36})
check("B1 failure is severity red", o.finding.severity, "red")
check("B1 failure names the owning code",
      o.finding.owner, "api/ads/_ghl-direct.ts#fetchGhlGroundTruthCounts")

print("\n--- CPL is +/-0.5%, CPBC is +/-5%. they must not share a tolerance ---")
check("E3 CPL 0.4% off passes",
      status_of("ORBIT-E3", {"client": "obb", "truth": {"cpl": 100.0, "cpbc": 500.0},
                             "app": {"cpl": 100.4, "cpbc": 500.0}}), "pass")
check("E3 CPL 1% off FAILS (would have passed under a 5% rule)",
      status_of("ORBIT-E3", {"client": "obb", "truth": {"cpl": 100.0, "cpbc": 500.0},
                             "app": {"cpl": 101.0, "cpbc": 500.0}}), "fail")
check("E3 CPBC 4% off passes",
      status_of("ORBIT-E3", {"client": "obb", "truth": {"cpl": 100.0, "cpbc": 500.0},
                             "app": {"cpl": 100.0, "cpbc": 520.0}}), "pass")

print("\n--- freshness and token expiry ---")
NOW = dt.datetime(2026, 9, 27, 12, 0, tzinfo=dt.timezone.utc)
check("G1 synced 3h ago passes",
      status_of("ORBIT-G1", {"client": "obb", "now": NOW,
                             "timestamp": NOW - dt.timedelta(hours=3)}), "pass")
check("G1 synced 30h ago FAILS",
      status_of("ORBIT-G1", {"client": "obb", "now": NOW,
                             "timestamp": NOW - dt.timedelta(hours=30)}), "fail")
check("G1 never synced at all FAILS (not a skip)",
      status_of("ORBIT-G1", {"client": "obb", "now": NOW, "timestamp": None}), "fail")
check("G3 token expiring in 40 days passes",
      status_of("ORBIT-G3", {"client": "obb", "now": NOW,
                             "timestamp": NOW + dt.timedelta(days=40)}), "pass")
check("G3 token expiring in 5 days FAILS",
      status_of("ORBIT-G3", {"client": "obb", "now": NOW,
                             "timestamp": NOW + dt.timedelta(days=5)}), "fail")

print("\n--- writer truth: +/-1s against the stored raw payload ---")
check("LEADFORM-1 stamps 0.4s apart pass",
      status_of("LEADFORM-1", {"client": "mustache-painting",
                               "truth": "2026-09-26T14:00:00.000Z",
                               "app": "2026-09-26T14:00:00.400Z"}), "pass")
check("LEADFORM-1 stamps 3s apart FAIL",
      status_of("LEADFORM-1", {"client": "mustache-painting",
                               "truth": "2026-09-26T14:00:00Z",
                               "app": "2026-09-26T14:00:03Z"}), "fail")

print("\n--- latency ---")
check("G7 an endpoint at 59s passes the 60s ceiling",
      status_of("ORBIT-G7", {"observed_ms": 59000}), "pass")
check("G7 an endpoint at 61s FAILS",
      status_of("ORBIT-G7", {"observed_ms": 61000}), "fail")

print("\n--- skip discipline: the 3-of-9-clients hole ---")
check("a legal skip reason is recorded as a skip",
      status_of("ORBIT-B1", {"client": "peach-paint-co",
                             "skip_reason": "not_applicable_client_type"}), "skip")
check("an INVENTED skip reason is an ERROR, not a skip",
      status_of("ORBIT-B1", {"client": "peach-paint-co",
                             "skip_reason": "didn't feel like it"}), "error")
check("the retired `aged_out_of_detector_window` is NOT a legal skip",
      status_of("ORBIT-B6", {"client": "obb",
                             "skip_reason": "aged_out_of_detector_window"}), "error")

print("\n--- skipped is not a pass: a blown-up evaluator is an error ---")
check("custom check with no verdict is an ERROR",
      status_of("ORBIT-I1", {"client": "obb"}), "error")
check("custom check with an explicit false verdict FAILS",
      status_of("ORBIT-I1", {"client": "obb", "ok": False}), "fail")
check("custom check with an explicit true verdict passes",
      status_of("ORBIT-I1", {"client": "obb", "ok": True}), "pass")

print("\n--- severity_split (B5 is red on a different day, yellow same-day) ---")
o = ac.evaluate(BY_ID["ORBIT-B5"], {"client": "cg", "ok": False,
                                    "severity_key": "different_ny_day"})
check("B5 different-day is red", o.finding.severity, "red")
o = ac.evaluate(BY_ID["ORBIT-B5"], {"client": "cg", "ok": False,
                                    "severity_key": "same_day_over_1h"})
check("B5 same-day-over-1h is yellow", o.finding.severity, "yellow")

print("\n--- judgment routing ---")
o = ac.evaluate(BY_ID["ORBIT-J4"], {"client": "obb", "ok": False, "subject": "appt:abc"})
check("J4 failure is flagged for judgment", o.finding.needs_judgment, True)
check("J4 judgment kind is triage_candidate", o.finding.judgment_kind, "triage_candidate")
o = ac.evaluate(BY_ID["ORBIT-A1"], {"client": "obb", "truth": 100.0, "app": 50.0})
check("A1 failure is NOT flagged for judgment", o.finding.needs_judgment, False)

print("\n--- capability routing, never a hardcoded client list ---")
ghl = {"client_id": "builderpro", "capabilities": {"has_ghl_walk": True}}
lf = {"client_id": "peach-paint-co", "capabilities": {"has_leadform_source": True}}
check("B1 applies to a GHL-walker client", ac.applies(BY_ID["ORBIT-B1"], ghl), True)
check("B1 does NOT apply to a leadform client", ac.applies(BY_ID["ORBIT-B1"], lf), False)
check("LEADFORM-1 applies to a leadform client", ac.applies(BY_ID["LEADFORM-1"], lf), True)
check("A1 applies to every client", ac.applies(BY_ID["ORBIT-A1"], lf), True)
check("a global check does not apply per-client", ac.applies(BY_ID["ORBIT-E4"], ghl), False)
check("a global check applies once, globally", ac.applies(BY_ID["ORBIT-E4"], None), True)

print("\n--- expected_check_count: the number andy_verify re-derives ---")
roster = [ghl, lf]
n = ac.expected_check_count(REGISTRY, roster)
check("expected count is a positive int", isinstance(n, int) and n > 0, True)
manual = sum(1 for c in REGISTRY["checks"] if c.get("applies_to") == "global") + \
    sum(1 for c in REGISTRY["checks"] if c.get("applies_to") != "global"
        for cl in roster if ac.applies(c, cl))
check("expected count matches an independent derivation", n, manual)

print("\n--- registry integrity ---")
check("every comparator in the registry exists in code",
      sorted({c["comparator"] for c in REGISTRY["checks"]} - set(ac.COMPARATORS)), [])
check("every severity is legal",
      sorted({c["severity"] for c in REGISTRY["checks"]} - {"red", "yellow", "info"}), [])
check("every declared skip reason is legal",
      sorted(set(REGISTRY["_skip_reasons"]) - ac.SKIP_REASONS), [])
check("no duplicate check ids",
      len(BY_ID), len(REGISTRY["checks"]))
check("every judgment check declares a judgment_kind",
      [c["id"] for c in REGISTRY["checks"] if c.get("judgment") and not c.get("judgment_kind")], [])
check("every red/yellow check names an owner or is code-static/global",
      [c["id"] for c in REGISTRY["checks"]
       if c["severity"] == "red" and not c.get("owner")
       and c.get("applies_to") != "global" and c.get("comparator") != "custom"], [])

print("\n--- the no-IO property (what makes this suite possible at all) ---")
src = (ROOT / "scripts" / "andy_checks.py").read_text()
banned = ["import socket", "import requests", "import psycopg2", "import urllib",
          "urlopen(", "open(", "subprocess", "os.environ"]
present = [b for b in banned if b in src]
check("andy_checks.py performs no IO", present, [])

print("\n--- the evaluator must never raise, whatever it is handed ---")
raised = None
for junk in [{}, {"truth": object()}, {"truth": [1], "app": {"a": 1}},
             {"skip_reason": None}, {"truth": float("nan"), "app": 1}]:
    for cid in list(BY_ID)[:12]:
        try:
            ac.evaluate(BY_ID[cid], junk)
        except Exception as e:      # noqa: BLE001
            raised = f"{cid} on {junk!r}: {type(e).__name__}: {e}"
            break
    if raised:
        break
check("evaluate() survives arbitrary junk input", raised, None)

total = len(failures)
print(f"\n{'ALL PASS' if total == 0 else str(total) + ' FAILURE(S)'}")
sys.exit(1 if total else 0)
