#!/usr/bin/env python3
"""Andy's ledger: rotation, archival, and the always-loaded seen-index.

THE PROBLEM THIS SOLVES
-----------------------
ledger/findings.json was 337KB / ~84K tokens and SKILL.md Step 0.5 said to read
it WHOLE before the first query. Measured on 2026-09-27, 381 entries:

    closed                       219   144KB   49%   already resolved, dead weight
    snoozed_until                 88    96KB   32%
    aged_out_of_detector_window   60    45KB   15%   all ORBIT-B6
    new                           12     7KB    2%
    known                          2     1KB    0%

and by check, 333 of 381 (87%) were ORBIT-J4 (222) or ORBIT-B6 (111).

So the file was two different things wearing one name: a DEFECT ledger, and a
human REVIEW QUEUE of individual bookings and opt-in stamps. Conflating them is
why the context load was enormous, why status was ACTION on 22 of the last 25
runs, and why the queue never drained.

THE SPLIT
---------
  findings.json      open DEFECTS in Orbit. Small. Read every run.
  triage-queue.json  ORBIT-J4 / ORBIT-B6 candidates. Read for triage work.
  seen-index.json    EVERY known fingerprint, minimal fields. Always read.
  archive/*.jsonl    resolved history. NEVER read by the agent; grep-able.

seen-index.json is the load-bearing piece. Without it, moving entries out of
findings.json would make the next run re-report all of them as NEW -- an
alert storm, which is indistinguishable from silence. The index answers
"have we seen this fingerprint before, and where does its body live?" in a
file small enough to read unconditionally.

Nothing here decides a finding's fate. Rotation moves CLOSED entries to the
archive and CLASSIFIES J4/B6 into the triage queue. Statuses are preserved
byte-for-byte. Open findings are never touched, closed, aged, or re-dated.

Usage:
    andy_ledger.py status                  # what is in the ledger now
    andy_ledger.py rotate                  # DRY RUN, prints the plan
    andy_ledger.py rotate --apply          # write it
    andy_ledger.py reindex --apply         # rebuild seen-index after any write
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LEDGER = ROOT / "ledger"
FINDINGS = LEDGER / "findings.json"
TRIAGE = LEDGER / "triage-queue.json"
SEEN = LEDGER / "seen-index.json"
ARCHIVE_DIR = LEDGER / "archive"

# Checks that are a human review queue, not defects in Orbit.
TRIAGE_CHECKS = {"ORBIT-J4", "ORBIT-B6"}

# Statuses whose entries are finished and belong in the archive.
ARCHIVED_STATUSES = {"closed"}


def load() -> dict:
    return json.loads(FINDINGS.read_text())


def quarter_of(iso: str) -> str:
    try:
        d = dt.date.fromisoformat(str(iso)[:10])
    except Exception:
        return "unknown"
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def classify(fp: str, f: dict) -> str:
    """Where does this entry belong? Pure function of its own fields."""
    if f.get("status") in ARCHIVED_STATUSES:
        return "archive"
    if f.get("check") in TRIAGE_CHECKS:
        return "triage"
    return "findings"


SEEN_FIELDS = ["check", "client", "status", "last_seen", "where"]


def build_seen_index(groups: dict[str, dict]) -> dict:
    """Minimal always-loadable index over EVERY fingerprint we have ever seen.

    Excludes note / unblocking_action / title, which together were 76% of the
    ledger's bytes. Rows are ARRAYS, not objects, keyed by SEEN_FIELDS: at 381
    entries the repeated JSON key names cost more than the data does (51KB as
    objects, ~22KB as arrays), and this is the one file read unconditionally on
    every run. It answers one question -- is this fingerprint new? -- and
    nothing else.
    """
    idx = {}
    for where, entries in groups.items():
        for fp, f in entries.items():
            idx[fp] = [f.get("check"), f.get("client"), f.get("status"),
                       f.get("last_seen"), where]
    return idx


def rotate(apply: bool) -> int:
    raw = load()
    F = raw["findings"]
    groups: dict[str, dict] = {"findings": {}, "triage": {}, "archive": {}}
    for fp, f in F.items():
        groups[classify(fp, f)][fp] = f

    total = len(F)
    moved = len(groups["triage"]) + len(groups["archive"])
    assert sum(len(g) for g in groups.values()) == total, "entries lost during classification"

    def size(d):
        return len(json.dumps(d))

    print(f"{'':22s} {'entries':>8s} {'bytes':>10s}")
    print(f"{'BEFORE findings.json':22s} {total:8d} {FINDINGS.stat().st_size:10,d}")
    for name in ("findings", "triage", "archive"):
        print(f"{'  -> ' + name:22s} {len(groups[name]):8d} {size(groups[name]):10,d}")
    seen = build_seen_index(groups)
    print(f"{'  -> seen-index':22s} {len(seen):8d} {size(seen):10,d}")

    by_q = collections.Counter(quarter_of(f.get("last_seen")) for f in groups["archive"].values())
    print(f"\narchive split by quarter: {dict(by_q)}")

    st = collections.Counter(f.get("status") for f in groups["findings"].values())
    print(f"remaining defect statuses : {dict(st)}")
    st_t = collections.Counter(f.get("status") for f in groups["triage"].values())
    print(f"triage queue statuses     : {dict(st_t)}")

    # Conservation. Nothing may be invented or lost.
    assert len(seen) == total, f"seen-index must cover all {total} fingerprints, has {len(seen)}"

    new_daily = size(groups["findings"]) + size(seen)
    print(f"\nEVERY-RUN load: {FINDINGS.stat().st_size:,} -> ~{new_daily:,} bytes "
          f"({100 - 100 * new_daily // FINDINGS.stat().st_size}% smaller)")
    print("(triage-queue.json is read only for J4/B6 work; archive is never read)")

    if not apply:
        print("\nDRY RUN. Nothing written. Re-run with --apply.")
        return 0

    backup = FINDINGS.with_suffix(".json.pre-rotate.bak")
    shutil.copy2(FINDINGS, backup)
    ARCHIVE_DIR.mkdir(exist_ok=True)

    for q, _ in by_q.items():
        rows = [dict(fingerprint=fp, **f) for fp, f in groups["archive"].items()
                if quarter_of(f.get("last_seen")) == q]
        path = ARCHIVE_DIR / f"{q}.jsonl"
        with path.open("a") as fh:
            for r in rows:
                fh.write(json.dumps(r, sort_keys=True) + "\n")
        print(f"archived {len(rows):4d} -> {path.relative_to(ROOT)}")

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    raw["findings"] = groups["findings"]
    raw["updated_at"] = now
    raw["rotated_at"] = now
    raw["_shape"] = ("Open DEFECTS only. ORBIT-J4/B6 review candidates live in "
                     "triage-queue.json; resolved history in archive/*.jsonl; every known "
                     "fingerprint in seen-index.json. Check seen-index BEFORE calling "
                     "anything NEW.")
    FINDINGS.write_text(json.dumps(raw, indent=2) + "\n")

    TRIAGE.write_text(json.dumps({
        "version": raw.get("version"),
        "updated_at": now,
        "_shape": ("ORBIT-J4 / ORBIT-B6 review candidates. A human work queue, not "
                   "defects in Orbit. Verdicts are read back from "
                   "ads_ghl_contacts.review_status, never decided by Andy."),
        "findings": groups["triage"],
    }, indent=2) + "\n")

    SEEN.write_text(json.dumps({
        "updated_at": now,
        "_shape": ("Every fingerprint Andy has ever recorded, with only the fields needed "
                   "to answer 'is this NEW?'. Read this unconditionally. Without it, "
                   "rotation would make the next run re-report every moved entry as NEW."),
        "_fields": SEEN_FIELDS,
        "index": seen,
    }) + "\n")

    print(f"\nwrote findings.json ({FINDINGS.stat().st_size:,}), "
          f"triage-queue.json ({TRIAGE.stat().st_size:,}), "
          f"seen-index.json ({SEEN.stat().st_size:,})")
    print(f"backup: {backup.relative_to(ROOT)}")
    return 0


def reindex(apply: bool) -> int:
    """Rebuild seen-index.json from the three live sources.

    MUST be run after any write to findings.json or triage-queue.json. The index
    is the only thing standing between a moved entry and being re-reported as
    NEW, so an index that lags its sources silently re-creates the alert storm
    rotation exists to prevent.
    """
    groups = {
        "findings": json.loads(FINDINGS.read_text()).get("findings", {}),
        "triage": json.loads(TRIAGE.read_text()).get("findings", {}) if TRIAGE.exists() else {},
        "archive": {},
    }
    if ARCHIVE_DIR.exists():
        for path in sorted(ARCHIVE_DIR.glob("*.jsonl")):
            for line in path.open():
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                fp = row.pop("fingerprint", None)
                if fp:
                    groups["archive"][fp] = row

    seen = build_seen_index(groups)
    prev = {}
    if SEEN.exists():
        prev = json.loads(SEEN.read_text()).get("index", {})

    added = sorted(set(seen) - set(prev))
    dropped = sorted(set(prev) - set(seen))
    print(f"seen-index: {len(prev)} -> {len(seen)} fingerprints "
          f"(+{len(added)} / -{len(dropped)})")
    if dropped:
        # Losing a fingerprint means the next run calls it NEW. Never silent.
        print(f"  WARNING, dropped: {dropped[:10]}{' ...' if len(dropped) > 10 else ''}")
    for name, g in groups.items():
        print(f"  {name:10s} {len(g):4d}")

    if not apply:
        print("DRY RUN. Nothing written. Re-run with --apply.")
        return 0
    SEEN.write_text(json.dumps({
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "_shape": ("Every fingerprint Andy has ever recorded, with only the fields needed "
                   "to answer 'is this NEW?'. Read this unconditionally."),
        "_fields": SEEN_FIELDS,
        "index": seen,
    }) + "\n")
    print(f"wrote {SEEN.relative_to(ROOT)} ({SEEN.stat().st_size:,} bytes)")
    return 0


def status() -> int:
    raw = load()
    F = raw["findings"]
    print(f"findings.json: {len(F)} entries, {FINDINGS.stat().st_size:,} bytes")
    for s, n in collections.Counter(f.get("status") for f in F.values()).most_common():
        print(f"  {str(s):32s} {n:4d}")
    print("\nby check:")
    for c, n in collections.Counter(f.get("check") for f in F.values()).most_common(8):
        print(f"  {str(c):24s} {n:4d}")
    for extra, label in ((TRIAGE, "triage-queue.json"), (SEEN, "seen-index.json")):
        if extra.exists():
            d = json.loads(extra.read_text())
            n = len(d.get("findings") or d.get("index") or {})
            print(f"\n{label}: {n} entries, {extra.stat().st_size:,} bytes")
    if ARCHIVE_DIR.exists():
        for p in sorted(ARCHIVE_DIR.glob("*.jsonl")):
            print(f"archive/{p.name}: {sum(1 for _ in p.open())} rows, {p.stat().st_size:,} bytes")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    r = sub.add_parser("rotate")
    r.add_argument("--apply", action="store_true",
                   help="actually write; omitted means dry run")
    x = sub.add_parser("reindex")
    x.add_argument("--apply", action="store_true",
                   help="actually write; omitted means dry run")
    a = ap.parse_args()
    if a.cmd == "status":
        return status()
    if a.cmd == "reindex":
        return reindex(a.apply)
    return rotate(a.apply)


if __name__ == "__main__":
    sys.exit(main())
