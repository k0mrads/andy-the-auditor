#!/usr/bin/env python3
"""Safety properties for ledger rotation.

Rotation MOVES entries between files. It must never lose one, invent one,
change one's status, or bury an unresolved finding. A FROZEN snapshot of the
2026-09-27 pre-rotation ledger is the fixture, because the real distribution
(381 entries: 219 closed, 135 J4/B6 candidates, 27 defects) is the thing that
has to survive. It is frozen rather than read live for the obvious reason: the
first apply changed the live file, and a test whose fixture is its own subject
stops testing anything the moment it passes once.

The property that matters most is the LAST one: rotation plus the seen-index
must leave every fingerprint still recognisable, because an entry that
disappears from the ledger comes back as NEW on the next run, and 135 findings
escalating at once is an alert storm -- indistinguishable from silence.

Run: python3 tests/test_ledger.py
"""
import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import andy_ledger as L  # noqa: E402

failures = []


def check(label, got, want):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"        expected {want!r}, got {got!r}")
        failures.append(label)


FIXTURE = ROOT / "tests" / "fixtures" / "ledger-2026-09-27-pre-rotate.json"
SRC = json.loads(FIXTURE.read_text())
F = SRC["findings"]
BEFORE = copy.deepcopy(F)

groups = {"findings": {}, "triage": {}, "archive": {}}
for fp, f in F.items():
    groups[L.classify(fp, f)][fp] = f

print("--- the fixture is the pre-rotation ledger, unchanged ---")
check("fixture has all 381 original entries", len(F), 381)
check("fixture still contains closed entries",
      sum(1 for f in F.values() if f.get("status") == "closed"), 219)

print("\n--- conservation: nothing lost, nothing invented ---")
check("every entry lands in exactly one group",
      sum(len(g) for g in groups.values()), len(F))
check("no fingerprint appears in two groups",
      len(set(groups["findings"]) & set(groups["triage"]) |
          set(groups["findings"]) & set(groups["archive"]) |
          set(groups["triage"]) & set(groups["archive"])), 0)
check("the union is exactly the original key set",
      set(groups["findings"]) | set(groups["triage"]) | set(groups["archive"]), set(F))

print("\n--- rotation must not MUTATE anything ---")
check("no entry body was modified during classification", F, BEFORE)
check("no status was rewritten",
      {fp: f.get("status") for fp, f in F.items()},
      {fp: f.get("status") for fp, f in BEFORE.items()})

print("\n--- only finished work may be archived ---")
bad = [fp for fp, f in groups["archive"].items() if f.get("status") not in L.ARCHIVED_STATUSES]
check("archive contains only closed entries", bad, [])
check("no OPEN finding was archived",
      [fp for fp, f in groups["archive"].items()
       if f.get("status") in ("new", "known", "snoozed_until",
                              "aged_out_of_detector_window")], [])

print("\n--- the aged-out B6 entries must NOT be buried ---")
aged = [fp for fp, f in F.items() if f.get("status") == "aged_out_of_detector_window"]
check("aged_out entries exist in this fixture", len(aged) > 0, True)
check("none of them were archived",
      [fp for fp in aged if fp in groups["archive"]], [])
check("all of them are in the triage queue, still visible",
      all(fp in groups["triage"] for fp in aged), True)

print("\n--- the triage queue holds review candidates, not defects ---")
check("triage holds only J4/B6",
      sorted({f.get("check") for f in groups["triage"].values()}),
      sorted(L.TRIAGE_CHECKS))
check("no J4/B6 remains in the defect ledger",
      [fp for fp, f in groups["findings"].items() if f.get("check") in L.TRIAGE_CHECKS], [])

print("\n--- classify() is pure: same entry, same answer, no side effects ---")
sample = list(F.items())[:40]
check("classify is deterministic across repeated calls",
      [L.classify(fp, f) for fp, f in sample],
      [L.classify(fp, f) for fp, f in sample])
snapshot = copy.deepcopy(dict(sample))
for fp, f in sample:
    L.classify(fp, f)
check("classify does not mutate its input", dict(sample), snapshot)

print("\n--- the seen-index is what stops an alert storm ---")
seen = L.build_seen_index(groups)
check("seen-index covers EVERY fingerprint", len(seen), len(F))
check("seen-index misses nothing", sorted(seen), sorted(F))
check("every row has the documented field count",
      {len(v) for v in seen.values()}, {len(L.SEEN_FIELDS)})
wrong = [fp for fp, row in seen.items()
         if row[L.SEEN_FIELDS.index("status")] != F[fp].get("status")]
check("seen-index status matches the source entry", wrong, [])
where_i = L.SEEN_FIELDS.index("where")
mis = [fp for fp, row in seen.items() if fp not in groups[row[where_i]]]
check("every row's `where` points at the group that actually holds it", mis, [])

print("\n--- the index is small enough to load unconditionally ---")
size = len(json.dumps(seen))
check("seen-index is under 40KB", size < 40_000, True)
print(f"        (actual: {size:,} bytes for {len(seen)} fingerprints)")


print("\n--- rotation must be IDEMPOTENT (regression: 2026-09-27) ---")
# The first implementation rebuilt triage-queue.json from findings.json alone,
# so a SECOND run wrote a queue holding only the J4/B6 entries still in
# findings.json -- after the first run, none. It clobbered 135 entries. Git had
# them, so nothing was lost, but an operation whose second invocation destroys
# data cannot be scheduled, and rotation is meant to be routine.
import json as _json, shutil as _shutil, tempfile as _tempfile, importlib as _importlib

_tmp = pathlib.Path(_tempfile.mkdtemp())
(_tmp / "ledger").mkdir()
_shutil.copy2(FIXTURE, _tmp / "ledger" / "findings.json")

_orig_paths = (L.LEDGER, L.FINDINGS, L.TRIAGE, L.SEEN, L.ARCHIVE_DIR)
L.LEDGER = _tmp / "ledger"
L.FINDINGS = L.LEDGER / "findings.json"
L.TRIAGE = L.LEDGER / "triage-queue.json"
L.SEEN = L.LEDGER / "seen-index.json"
L.ARCHIVE_DIR = L.LEDGER / "archive"

import io as _io, contextlib as _ctx
def _rotate_quiet():
    with _ctx.redirect_stdout(_io.StringIO()):
        L.rotate(apply=True)

def _counts():
    f = len(_json.loads(L.FINDINGS.read_text())["findings"])
    t = len(_json.loads(L.TRIAGE.read_text())["findings"]) if L.TRIAGE.exists() else 0
    a = 0
    if L.ARCHIVE_DIR.exists():
        a = sum(1 for p_ in L.ARCHIVE_DIR.glob("*.jsonl") for ln in p_.open() if ln.strip())
    return f, t, a

_rotate_quiet()
first = _counts()
_rotate_quiet()
_rotate_quiet()
third = _counts()

check("first rotate conserves all 381", sum(first), 381)
check("a second and third rotate change nothing", third, first)
check("the triage queue is not clobbered by re-running", third[1], first[1])
check("the archive gains no duplicate rows", third[2], first[2])
print(f"        (stable at {first[0]} defects / {first[1]} triage / {first[2]} archived)")

L.LEDGER, L.FINDINGS, L.TRIAGE, L.SEEN, L.ARCHIVE_DIR = _orig_paths
_shutil.rmtree(_tmp, ignore_errors=True)

total = len(failures)

# --- the vague-action gate (added 2026-09-28) -------------------------------
# The README has required a real unblocking_action since the split, and nothing
# enforced it: 73 of 147 live entries (49.7%) opened with investigate / monitor /
# review on 2026-09-28. A test that only asserted "lint passes" would stay green
# if the regex matched nothing, so both directions are pinned here.
print("\n--- unblocking_action must name an action ---")
from andy_ledger import VAGUE_ACTION  # noqa: E402

for bad in ("Investigate whether the GHL walker window is off",
            "Monitor for a few more runs",
            "Review in GHL or accept",
            "Decide: count_as_separate or not",
            "TBD",
            "None (ledger-once). Benign paid-social re-opt-in"):
    check(f"rejects {bad[:34]!r}", bool(VAGUE_ACTION.match(bad)), True)

for good in ("Orbit PR (batch 08-17): give sweep/force_full a bookings pass",
             "DECISION OWED (grouped, 5 clients, one bug): raise the best-ads cap",
             "RESOLVED 2026-09-28 on evidence, not aged out."):
    check(f"accepts {good[:34]!r}", bool(VAGUE_ACTION.match(good)), False)

# Run the real CLI against the real ledger: earlier tests reload the module
# against a temp dir, so calling lint() in-process could lint the wrong tree.
import subprocess as _sp  # noqa: E402
_r = _sp.run([sys.executable, str(ROOT / "scripts/andy_ledger.py"), "lint"],
             capture_output=True, text=True)
check("the live ledger has no vague actions", _r.returncode, 0)

print(f"\n{'ALL PASS' if total == 0 else str(total) + ' FAILURE(S)'}")
sys.exit(1 if total else 0)
