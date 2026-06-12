# Findings ledger

`findings.json` is Andy's persistent memory of every WARN/FAIL ever emitted. It is what makes the daily report lead with NEW / STATE CHANGES / known-collapsed instead of re-printing the same warnings forever. Added 2026-06-12 (report-actionability revamp).

## Single-writer rule

- **Vault mode (local) is the ONLY writer.** Every vault run reconciles the ledger and then **commits AND pushes it** in the same run (`git add ledger/ && git commit && git push`). This is mandatory, not optional: both launchd runners (`andy-morning-run.sh`, `andy-gap-scan-run.sh`) do `git reset --hard origin/main` on this repo before invoking the skill, so an unpushed ledger update is silently destroyed by the next scheduled run.
- **Slack mode (cloud routine) is read-only.** It reads the committed copy it cloned. Anything it finds that is not in the committed ledger it reports as NEW (and the next vault run ledgers it).

## Finding identity

`id = sha256("{check}|{client}|{subject}")[:10]` (lowercase hex). The `key` field stores the readable triple.

- `subject` is the stable per-finding anchor: B6 → `contact_id`; J4 → `appointment_id`; I2 → table name or a named sub-issue; code-static findings → `file:symbol`; agency-wide findings use `client: "global"`.

## Fields

| Field | Meaning |
|---|---|
| `check` | Check ID (`ORBIT-B6`, `ORBIT-J4`, `MUT-1`, `MIRROR-PAID-FLAG-DRIFT`, ...) |
| `client` | `client_id` or `global` |
| `severity` | `BLOCKER` / `WARN` / `INFO` at last observation |
| `first_seen` / `last_seen` | dates (YYYY-MM-DD). `last_seen` is bumped every run that still observes the finding. Age = today − first_seen. |
| `status` | `new` \| `known` \| `snoozed_until` \| `fixed_pending_verify` \| `closed` |
| `snoozed_until` | date, required when status is `snoozed_until`. An expired snooze whose finding still reproduces is a STATE CHANGE (escalates to ACTION). |
| `unblocking_action` | **Required for every non-closed finding.** The named, concrete action that retires it. "Investigate" is not an action. |
| `note` | Free-text context (operator actions observed, evidence, links). |

## Status lifecycle

```
(first observed)  → new            — appears in the NEW section; needs a human decision today
(next run)        → known          — collapsed one-liner with age; MUST gain a snooze or escalate by day 7
(operator/dated)  → snoozed_until  — silent until the date; expiry + still-reproducing = STATE CHANGE
(fix shipped)     → fixed_pending_verify — waiting for a run that confirms the fix landed
(verified gone)   → closed         — kept for history; resurfacing = REGRESSED (STATE CHANGE, not new)
```

**The permanent-WARN rule:** a finding with severity WARN whose age exceeds **7 days** may never render as a plain repeated warning. The vault run MUST either (a) carry a valid future `snoozed_until` + `unblocking_action`, or (b) escalate it into the ACTION section of the report ("needs a snooze decision or a fix today"). There is no third state.

## Other top-level keys

- `baselines.i2_coverage` — the ORBIT-I2 numeric floors (per client/table `has_ad`/`has_campaign`/`total`). I2 is INFO by default; it WARNs only when ad-coverage (`has_ad / has_campaign`) drops more than `warn_drop_pp` below the floor, and the floor ratchets UP whenever coverage improves (vault run updates it).
- `mutations_snapshot` — MUT-1's prior-run enumeration of operator mutations (`_manual_override` leads/bookings, `excluded_from_metrics`, `counts_as_separate`). Each vault run diffs live Neon against this, reports adds/removals under STATE CHANGES, then overwrites the snapshot.
