#!/usr/bin/env python3
"""Regression test for the gap-scan DST bug (fixed 2026-09-27).

The old implementation was `utcnow() - timedelta(hours=5)`: a hardcoded EST
offset. NY is on EDT (UTC-4) for roughly eight months of the year, so during
DST the old code resolved one hour early. Between 00:00 and 01:00 NY that
returned the WRONG calendar day, silently shifting the entire 90-day scan
window by a day.

Two properties must hold, and the second is the one that was broken:
  1. EST (winter) dates resolve correctly.
  2. EDT (summer) dates resolve correctly, especially just after NY midnight.

Run: python3 tests/test_gap_scan_tz.py
"""
import datetime as dt
import importlib.util
import pathlib
import sys

_spec = importlib.util.spec_from_file_location(
    "gap_scan", pathlib.Path(__file__).resolve().parent.parent / "scripts" / "gap-scan.py"
)
gap_scan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gap_scan)

UTC = dt.timezone.utc

# (utc_instant, expected_yesterday_ny, description)
CASES = [
    # --- EDT (UTC-4), summer. The season the old code got wrong. ---
    (dt.datetime(2026, 7, 15, 4, 30, tzinfo=UTC), dt.date(2026, 7, 14),
     "EDT, 00:30 NY on Jul 15 -> yesterday is Jul 14"),
    (dt.datetime(2026, 7, 15, 4, 5, tzinfo=UTC), dt.date(2026, 7, 14),
     "EDT, 00:05 NY (the hour the old -5h offset broke) -> Jul 14"),
    (dt.datetime(2026, 7, 15, 23, 0, tzinfo=UTC), dt.date(2026, 7, 14),
     "EDT, 19:00 NY on Jul 15 -> yesterday is Jul 14"),
    (dt.datetime(2026, 7, 15, 3, 59, tzinfo=UTC), dt.date(2026, 7, 13),
     "EDT, 23:59 NY on Jul 14 -> yesterday is Jul 13"),

    # --- EST (UTC-5), winter. The season the old code happened to get right. ---
    (dt.datetime(2026, 1, 15, 5, 30, tzinfo=UTC), dt.date(2026, 1, 14),
     "EST, 00:30 NY on Jan 15 -> yesterday is Jan 14"),
    (dt.datetime(2026, 1, 15, 4, 59, tzinfo=UTC), dt.date(2026, 1, 13),
     "EST, 23:59 NY on Jan 14 -> yesterday is Jan 13"),

    # --- DST boundaries themselves. ---
    (dt.datetime(2026, 3, 8, 7, 30, tzinfo=UTC), dt.date(2026, 3, 7),
     "spring-forward day, 02:30 NY -> yesterday is Mar 7"),
    (dt.datetime(2026, 11, 1, 5, 30, tzinfo=UTC), dt.date(2026, 10, 31),
     "fall-back day, 01:30 NY -> yesterday is Oct 31"),
]


def old_buggy(now_utc: dt.datetime) -> dt.date:
    """The pre-fix implementation, kept so the test proves the bug was real."""
    return (now_utc.replace(tzinfo=None) - dt.timedelta(hours=5) - dt.timedelta(days=1)).date()


def main() -> int:
    fails = 0
    for instant, expected, desc in CASES:
        got = gap_scan.yesterday_ny(instant)
        ok = got == expected
        print(f"{'PASS' if ok else 'FAIL'}  {desc}")
        if not ok:
            print(f"        expected {expected}, got {got}")
            fails += 1

    # The test must also prove the old code actually failed, otherwise it is
    # guarding nothing. At least one EDT case has to differ under the old math.
    regressions_caught = sum(
        1 for instant, expected, _ in CASES if old_buggy(instant) != expected
    )
    if regressions_caught == 0:
        print("FAIL  test is vacuous: the old implementation passes every case")
        fails += 1
    else:
        print(f"PASS  test is meaningful: old implementation fails {regressions_caught}/{len(CASES)} cases")

    total = len(CASES) + 1
    print(f"\n{total - fails}/{total} passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
