# Andy's findings ledger

Andy's persistent memory across runs. The report is a **diff against this**, not
a re-print of it: a finding is reported in full once, then collapses to a
one-line carry-over.

## Four files, one job each

| File | Read | Holds |
|---|---|---|
| `seen-index.json` | **always, first** | every fingerprint ever recorded, 5 fields each. ~32KB. |
| `findings.json` | **always** | open DEFECTS in Orbit, full bodies. |
| `triage-queue.json` | only for ORBIT-J4 / ORBIT-B6 work | the human review queue. |
| `archive/YYYY-Qn.jsonl` | **never** (grep by hand) | resolved history, append-only. |

### Why this is four files and not one (2026-09-27)

It was one 337KB file, and `SKILL.md` Step 0.5 said to read it whole before the
first query, so ~84K tokens were spent before any work happened. Measured at the
split, 381 entries:

| status | n | bytes | share |
|---|---|---|---|
| `closed` | 219 | 144KB | 49% |
| `snoozed_until` | 88 | 96KB | 32% |
| `aged_out_of_detector_window` | 60 | 45KB | 15% |
| `new` | 12 | 7KB | 2% |
| `known` | 2 | 1KB | 0% |

and by check, **333 of 381 (87%) were ORBIT-J4 (222) or ORBIT-B6 (111)**.

That is the whole diagnosis: the file was two different things wearing one name.
A defect ledger, and a human review queue of individual bookings and opt-in
stamps. Conflating them is why the context load was enormous, why status was
ACTION on 22 of the last 25 runs, and why the queue never drained. J4/B6
verdicts are read back from `ads_ghl_contacts.review_status`, so that queue
drains when a human does the work and cannot drift.

Every-run load is now ~105KB instead of 337KB.

## The rule that makes the split safe

**Absence from `findings.json` does not mean NEW.** Check `seen-index.json`
first. 354 of the 381 entries now live in the triage queue or the archive, and
treating them as new would escalate them all in one report. An alert storm is
indistinguishable from silence.

## Entry shape

Keyed by fingerprint, `sha256("{check}|{client}|{subject}")[:10]`, where subject
is the B6 contact_id, J4 appointment_id, I2 table/sub-issue, or code-static
`file:symbol`.

```json
"7e88678361": {
  "key": "ORBIT-J4|caregenius-b2b|t9tZmCw8iX7s9CvJgTg2",
  "check": "ORBIT-J4",
  "client": "caregenius-b2b",
  "subject": "t9tZmCw8iX7s9CvJgTg2",
  "severity": "WARN",
  "title": "one line, what it is",
  "first_seen": "2026-06-12",
  "last_seen": "2026-06-15",
  "status": "new",
  "unblocking_action": "the named event that would close this"
}
```

`seen-index.json` rows are ARRAYS, not objects, keyed by its own `_fields`
header (`check, client, status, last_seen, where`). At 381 entries the repeated
JSON key names cost more than the data, and this is the one file read
unconditionally.

## Statuses

`new | known | snoozed_until | fixed_pending_verify | closed`

**`aged_out_of_detector_window` is RETIRED (2026-09-27).** It was invented to
dodge the permanent-WARN rule, and it keys suppression on the detector no longer
*looking* rather than on the finding being *resolved*, so a real issue goes
permanently silent. Its 60 entries are parked in the triage queue awaiting
disposition. Never write it again.

Never invent a seventh status either. If a finding has no legal move, the real
bug is that its check cannot re-answer for an old subject, and the fix is a
recheck path, not a new word.

Every non-closed entry carries a **named `unblocking_action`**: the actual event
that would close it. "Investigate" and "monitor" are not unblocking actions, and
letting them in is how this ledger rotted to 102 open findings aged 45 to 99
days.

## Tooling

```bash
python3 scripts/andy_ledger.py status            # current shape of all four files
python3 scripts/andy_ledger.py rotate            # dry run
python3 scripts/andy_ledger.py rotate --apply    # archive closed, split out triage
python3 scripts/andy_ledger.py reindex --apply   # rebuild seen-index; run after ANY write
```

Rotation never decides a finding's fate. It moves `closed` entries to the
archive and classifies J4/B6 into the triage queue; statuses are preserved
byte-for-byte and open findings are never touched. `tests/test_ledger.py` pins
that: conservation, no mutation, no open finding archived, no aged-out entry
buried, and full seen-index coverage.
