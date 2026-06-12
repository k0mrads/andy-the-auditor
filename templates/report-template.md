---
date: {{date}}
client: {{client}}
window_start: {{window_start_iso}}
window_end: {{window_end_iso}}
window_days: 3
window_label: Last 3 days (NY, yesterday + 2 prior)
run_type: {{run_type}}
status: {{GREEN | ACTION | BROKEN}}
blockers: {{blocker_count}}
new_findings: {{new_count}}
state_changes: {{changed_count}}
known_carryovers: {{known_count}}
passes: {{pass_count}}
summary_one_line: "{{summary}}"
action_items: {{action_items_list}}
failed_checks: {{failed_check_ids}}
new_finding_keys: {{new_finding_keys}}
notable_findings: {{notable_findings}}
skill_version: {{git_sha_or_version}}
ledger_updated_at: {{ledger_updated_at}}
tags: [attribution-audit, orbit, {{client_tag}}]
---

<!--
RENDERING SCOPE: Andy is a developer-style auditor for the Orbit app, NOT a marketing analyst.
No spend-trend observations, no creative-effectiveness analysis, no spend-mix breakdowns,
no campaign-strategy recommendations, no sample-size commentary. See SKILL.md "Scope".

STRUCTURE CONTRACT (2026-06-12 revamp): the report LEADS with the three ledger-diff sections
(NEW / STATE CHANGES / KNOWN). Full check tables go BELOW the fold. A known carry-over gets
exactly ONE collapsed line - re-printing its detail block daily is the failure mode this
template exists to kill. Status is GREEN / ACTION / BROKEN, never blanket WARN.
-->

# {{client}} Attribution Audit (Orbit) - {{date}}

Window: **{{window_start_human}} to {{window_end_human}}** ({{client_timezone}})
Run type: {{run_type}} · Skill: {{git_sha_or_version}} · Ledger: {{ledger_updated_at}}

{{if status == BROKEN}}
## ❌ BROKEN - {{blocker_count}} blocker(s)

{{for each FAIL check}}
### {{check_id}} - {{check_name}}
- **Ground truth ({{source}}):** {{truth_value}}
- **App-displayed:** {{app_value}}
- **Delta:** {{delta_abs}} ({{delta_pct}}%)
- **What this means:** {{plain_english_explanation}}
- **Likely owner:** {{file_path}}{{:line}} ({{regression_class}})
- **Affected sample IDs:** {{sample_ids}}
{{end}}
{{else if status == ACTION}}
## 🟠 ACTION - {{action_count}} item(s) need a human today
{{else}}
## ✅ GREEN - nothing new, no state changes
All carry-overs validly snoozed/cadenced. Full reconciliation detail below the fold.
{{end}}

---

## 1. NEW since last run ({{new_count}})

{{if new_count == 0}}None.{{else}}
{{for each new finding}}
### {{check_id}} ({{client_id}}) - {{title}}
- **Evidence:** {{truth_vs_app_or_detector_output}}
- **Link:** {{ghl_deep_link_or_file_line}}
- **Likely owner:** {{file_path}}
- **➜ Decide today:** {{the_one_decision_or_action}}
{{end}}
{{end}}

## 2. STATE CHANGES ({{changed_count}})

{{if changed_count == 0}}None.{{else}}
| Change | Finding | Detail |
|---|---|---|
{{for each}}
| {{FIXED / REGRESSED / SNOOZE EXPIRED / MUTATION+ / MUTATION-}} | {{check_id}} ({{client_id}}) {{subject}} | {{one_liner}} |
{{end}}
{{end}}

<!-- MUT-1 adds/removes render here as MUTATION+ / MUTATION- rows
     (e.g. "MUTATION+ | excluded_from_metrics (caregenius-b2b) 8vi0K87G… | operator excluded contact; historical window counts shift"). -->

## 3. Known carry-overs ({{known_count}})

{{if known_count == 0}}None - ledger is clean.{{else}}
{{for each known/snoozed finding, one line, NO detail blocks}}
- `{{check_id}}` ({{client_id}}): known, day {{age}}, {{snoozed until {{date}} | weekly cadence (next: Monday)}} - {{unblocking_action}}
{{end}}
{{end}}

{{if is_monday AND j4_queue_nonempty}}
## Monday triage - J4 yes/no queue ({{j4_count}})

{{for each J4 candidate}}
- [ ] **{{full_name}}** booked {{booked_at}} on "{{calendar_name}}" - signal: {{signal}}. Real paid booking?
      GHL: https://app.gohighlevel.com/v2/location/{{ghl_location_id}}/contacts/detail/{{contact_id}}
      YES → `curl -X POST {{origin}}/api/ads/bookings/promote -H "Authorization: Bearer $AUDIT_TOKEN" -H 'Content-Type: application/json' -d '{"client_id":"{{client_id}}","appointment_id":"{{appointment_id}}","action":"promote"}'`
      NO  → `curl -X POST {{origin}}/api/ads/contacts/review -H "Authorization: Bearer $AUDIT_TOKEN" -H 'Content-Type: application/json' -d '{"client_id":"{{client_id}}","contact_id":"{{contact_id}}","status":"ignored"}'`
{{end}}
{{end}}

---

*--- full check detail below the fold ---*

## ORBIT-A: Meta Graph API vs Neon `ads_meta_insights`

| Metric | Meta (truth) | Neon | App | Delta vs Meta | Status |
|---|---|---|---|---|---|
| Spend | ${{meta_spend}} | ${{neon_spend}} | ${{app_spend}} | {{delta_spend_pct}}% | {{status_a1}} |
| Impressions | {{meta_impressions}} | {{neon_impressions}} | {{app_impressions}} | {{delta_impressions_pct}}% | {{status_a2}} |
| Inline link clicks | {{meta_clicks}} | {{neon_clicks}} | {{app_clicks}} | {{delta_clicks_pct}}% | {{status_a3}} |
| CPC / CPM / CTR | ... | ... | ... | ... | {{status_a4}} |

Note: most-recent day tolerance loosens to ±10% (Meta still aggregating).

{{if has_ghl}}
## ORBIT-B: GHL (live walk) vs Neon `ads_paid_leads`

Counted union semantics per invariants/orbit.md (28-day click gate, exclusions antijoin, primary-booking anchor, `counts_as_separate`).

| Metric | Ground truth (GHL walk) | Neon | App | Delta | Status |
|---|---|---|---|---|---|
| Paid leads in window (counted union) | {{truth_paid_leads}} | {{neon_paid_leads}} | {{app_paid_leads}} | {{delta_b1}} | {{status_b1}} |
| Re-opt-in survival test (B3) | {{b3_result}} | - | - | - | {{status_b3}} |
| B5 now()-stamp corroboration | {{b5_result}} | - | - | - | {{status_b5}} |
| B6 rung-2 candidates (count; detail lives in the ledger) | {{b6_candidate_count}} ({{b6_new_count}} new) | - | - | - | {{status_b6}} |

**Golden-rule grep (B2):** {{b2_result}}

## ORBIT-C: GHL bookings vs Neon `ads_paid_bookings` (COUNTED)

| Metric | Ground truth (counted) | Neon (counted) | App | Delta | Status |
|---|---|---|---|---|---|
| Counted paid booked calls in window | {{truth_paid_booked}} | {{neon_paid_booked}} | {{app_paid_booked}} | {{delta_c1}} | {{status_c1}} |
| Cost per booked | ${{truth_cpbc}} | - | ${{app_cpbc}} | {{delta_cpbc_pct}}% | {{status_c2}} |
{{end}}

{{if is_leadform_client}}
## LEADFORM-1{{/CAL-1}}: writer truth vs raw payloads

| Check | Rows scanned | Drift rows | Status |
|---|---|---|---|
| LEADFORM-1 `last_paid_opt_in_at == raw.created_time` | {{n}} | {{drift}} | {{status}} |
| LEADFORM-1 dup-person scan (INFO) | {{n}} | {{dups}} | INFO |
{{if queen}}| CAL-1 `booked_at == event.created_at` / no cancelled counted / no `cal:` synthetics | {{n}} | {{drift}} | {{status}} |{{end}}
{{end}}

## ORBIT-E: API vs Neon (display layer)

| Check | Truth | App | Delta | Status |
|---|---|---|---|---|
| E1 spend/impr/clicks exact | ... | ... | {{e1_delta}} | {{status_e1}} |
| E2 paid_leads / paid_booked exact | ... | ... | {{e2_delta}} | {{status_e2}} |
| E3 CPL/CPBC recompute | ... | ... | {{e3_delta}} | {{status_e3}} |
| E4 totals == SUM(clients) | ... | ... | {{e4_delta}} | {{status_e4}} |
| E5 CAD/USD blend | INFO | INFO | - | INFO |

{{if include_per_adset}}
## ORBIT-F: Per-adset drill-down

{{adset_table_top20_plus_aggregate_note}}
{{end}}

## ORBIT-G: Sync freshness + latency

{{sync_freshness_table}}
{{latency_line}}

{{if include_code_static}}
## ORBIT-H: Code-static checks

| Check | Result | Detail |
|---|---|---|
| H1 banned columns | {{status_h1}} | {{h1_detail}} |
| H2 bare dates / clientWindow | {{status_h2}} | {{h2_detail}} |
| H3 single predicate definition | {{status_h3}} | {{h3_detail}} |
| H4 code anchors | {{status_h4}} | {{h4_detail}} |
| H5 schema baseline | {{status_h5}} | {{h5_detail}} |
| H6 endpoint catalog | {{status_h6}} | {{h6_detail}} |
{{end}}

## ORBIT-I / ORBIT-J: conversion surfaces + booked-calls buckets

| Check | Result | Status |
|---|---|---|
| I1 Best Ads reconciles | {{detail}} | {{status_i1}} |
| I2 ad-coverage vs ledger floor ({{floor_pct}}% → {{today_pct}}%) | {{detail}} | {{status_i2}} |
| I3 popover/list == KPI | {{detail}} | {{status_i3}} |
| J1 PAID ⊆ ALL | {{detail}} | {{status_j1}} |
| J2 bucket math == Neon | {{detail}} | {{status_j2}} |
| J3 counted PAID == KPI | {{detail}} | {{status_j3}} |
| J4 triage candidates ({{weekly cadence}}) | {{count}} queued{{, listed above if Monday}} | {{status_j4}} |
| J5 unreviewed backlog | {{count}} | INFO |

## MUT-1: operator mutations

{{if mut1_diff_empty}}No operator mutations since last run. Snapshot refreshed.{{else}}Diffs listed under STATE CHANGES above. Snapshot refreshed.{{end}}

## Raw counts (for spot-checking)

```
Client:   {{client}}   Window: {{window_start_iso}} → {{window_end_iso}} ({{client_timezone}})
Spend (Meta/Neon/App):       {{...}}
Leads (truth/neon/app):      {{...}}
Booked (truth/neon/app):     {{...}}
CPL / CPBC:                  {{...}}
```

---

*Generated by /andy-the-auditor. Invariants: ~/.claude/skills/andy-the-auditor/invariants/orbit.md. Findings ledger: ledger/findings.json (committed + pushed every vault run). Edit invariants there, not in this report.*
