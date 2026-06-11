---
date: {{date}}
client: {{client}}
window_start: {{window_start_iso}}
window_end: {{window_end_iso}}
window_days: 3
window_label: Last 3 days (NY, yesterday + 2 prior)
run_type: {{run_type}}
status: {{status}}
blockers: {{blocker_count}}
warnings: {{warn_count}}
passes: {{pass_count}}
summary_one_line: "{{summary}}"
failed_checks: {{failed_check_ids}}
warning_checks: {{warning_check_ids}}
notable_findings: {{notable_findings}}
skill_version: {{git_sha_or_version}}
tags: [attribution-audit, orbit, {{client_tag}}]
---

<!--
RENDERING SCOPE: Andy is a developer-style auditor for the Orbit app, NOT a marketing analyst.
DO NOT add prose sections that comment on marketing performance: no spend-trend observations,
no creative-effectiveness analysis, no spend-mix breakdowns, no campaign-strategy recommendations,
no sample-size noise commentary. Stick to the dev-style sections listed below (TL;DR, Failures,
Warnings, ORBIT-A through ORBIT-H, Raw counts, Next steps). The `notable_findings` frontmatter
field is for dev/operational items only (e.g. "BP 9 of 18 leads unattributed, owner: api/ads/sync-conversions.ts").
See SKILL.md "Scope" section for the full anti-example list.
-->

# {{client}} Attribution Audit (Orbit) - {{date}}

Window: **{{window_start_human}} to {{window_end_human}}** (America/New_York)
Run type: {{run_type}}
Skill version: {{git_sha_or_version}}

## TL;DR

- BLOCKERS: **{{blocker_count}}**
- WARNINGS: **{{warn_count}}**
- PASSES: **{{pass_count}}**

{{if blocker_count > 0}}
{{summary}} ❌ **Action required.** See "Failures" section below.
{{else if warn_count > 0}}
{{summary}} ⚠️ **Investigate.** No blockers, but warnings present.
{{else}}
{{summary}} ✅ **All green.** Orbit math reconciles with Meta + upstream conversion truth (GHL walk / leadform / Calendly payloads) on counted semantics.
{{end}}

---

## Newly failing since yesterday

{{if newly_failing_count > 0}}

| Check | Yesterday | Today | One-liner |
|---|---|---|---|
{{for each flipped check}}
| {{check_id}} | {{yesterday_status}} | {{today_status}} | {{summary}} |
{{end}}

{{else}}
None.
{{end}}

---

## Failures ({{blocker_count}} blockers)

{{if blocker_count > 0}}
{{for each FAIL check}}

### {{check_id}} - {{check_name}} ({{severity}})

- **Ground truth ({{source}}):** {{truth_value}}
- **App-displayed (/api/ads/overview):** {{app_value}}
- **Delta:** {{delta_abs}} ({{delta_pct}}%)
- **What this means:** {{plain_english_explanation}}
- **Likely owner:** {{file_path}}{{:line}} ({{regression_class}})
- **Affected sample IDs:** {{sample_ids}}

{{end}}
{{else}}
No blockers today.
{{end}}

---

## Warnings ({{warn_count}})

{{if warn_count > 0}}
{{for each WARN check}}

### {{check_id}} - {{check_name}}

- **Detail:** {{summary}}
- **Investigate:** {{file_or_query}}

{{end}}
{{else}}
No warnings today.
{{end}}

---

## ORBIT-A: Meta Graph API vs Neon `ads_meta_insights`

| Metric | Meta (truth) | Neon | App | Delta vs Meta | Status |
|---|---|---|---|---|---|
| Spend | ${{meta_spend}} | ${{neon_spend}} | ${{app_spend}} | {{delta_spend_pct}}% | {{status_a1}} |
| Impressions | {{meta_impressions}} | {{neon_impressions}} | {{app_impressions}} | {{delta_impressions_pct}}% | {{status_a2}} |
| Inline link clicks | {{meta_clicks}} | {{neon_clicks}} | {{app_clicks}} | {{delta_clicks_pct}}% | {{status_a3}} |
| CPC | ${{meta_cpc}} | ${{neon_cpc}} | ${{app_cpc}} | {{delta_cpc_pct}}% | {{status_a4}} |
| CPM | ${{meta_cpm}} | ${{neon_cpm}} | ${{app_cpm}} | {{delta_cpm_pct}}% | {{status_a4}} |
| CTR | {{meta_ctr}}% | {{neon_ctr}}% | {{app_ctr}}% | {{delta_ctr_pp}}pp | {{status_a4}} |

Note: most-recent day tolerance loosens to ±10% (Meta still aggregating).

---

{{if has_ghl}}
## ORBIT-B: GHL (live walk) vs Neon `ads_paid_leads`

Counted union semantics: `paid_leads = COUNT(DISTINCT contact_id) of (non-excluded opt-iners with last_paid_opt_in_at in window) UNION (COUNTED bookings with booked_at in window)`. COUNTED = 28-day click gate (or `_manual_override`) + excluded-contacts antijoin + one primary booking per contact (all-time MIN(booked_at)) + `counts_as_separate` overrides. Bookers whose original opt-in landed before the window still count as a lead.

| Metric | Ground truth (GHL walk) | Neon | App | Delta | Status |
|---|---|---|---|---|---|
| Paid leads in window (counted union) | {{truth_paid_leads}} | {{neon_paid_leads}} | {{app_paid_leads}} | {{delta_b1}} | {{status_b1}} |
| Re-opt-in survival test | {{b3_result}} | - | - | - | {{status_b3}} |
| B5 now()-stamp corroboration | {{b5_result}} | - | - | - | {{status_b5}} |
| B6 rung-2 stale-corroboration candidates | {{b6_candidate_count}} | - | - | - | {{status_b6}} |

**Golden-rule grep (B2):** {{b2_result}}
{{if b2_violations > 0}}
Violations:
{{for each violation}}
- `{{file}}:{{line}}` - `{{matched_text}}`
{{end}}
{{end}}

{{if b1_delta > 0}}
**Sample mismatched contact_ids on delta:**
- Missing-in-Neon: {{missing_in_neon_contact_ids}}
- Extra-in-Neon: {{extra_in_neon_contact_ids}}
{{end}}

---

## ORBIT-C: GHL bookings vs Neon `ads_paid_bookings` (COUNTED)

Both sides apply the counted gates (click recency / exclusions / primary anchor / counts_as_separate) before comparing. Raw row counts are diagnostics only.

| Metric | Ground truth (GHL walk, counted) | Neon (counted) | App | Delta | Status |
|---|---|---|---|---|---|
| Counted paid booked calls in window | {{truth_paid_booked}} | {{neon_paid_booked}} | {{app_paid_booked}} | {{delta_c1}} | {{status_c1}} |
| Cost per booked | ${{truth_cpbc}} | - | ${{app_cpbc}} | {{delta_cpbc_pct}}% | {{status_c2}} |

{{if c1_delta > 0}}
**Sample mismatched appointment_ids on delta:**
- Missing-in-Neon: {{missing_in_neon_appointment_ids}}
- Extra-in-Neon: {{extra_in_neon_appointment_ids}}
{{end}}

---
{{end}}

<!-- ORBIT-D (Hyros) is DEPRECATED as of Part 11 (2026-05-20). Hyros is retired
from every conversion path; do not render a Hyros section. Log one INFO line
("ORBIT-D: DEPRECATED, Hyros retired") under Warnings/Info if anything. -->


## ORBIT-E: API vs Neon (display-layer reconciliation)

| Check | Truth | App | Delta | Status |
|---|---|---|---|---|
| E1 Per-client spend / impressions / clicks | exact | exact | {{e1_delta}} | {{status_e1}} |
| E2 Per-client paid_leads / paid_booked_calls | exact | exact | {{e2_delta}} | {{status_e2}} |
| E3 CPL recomputed (±0.5%) | ${{truth_cpl}} | ${{app_cpl}} | {{e3_cpl_delta_pct}}% | {{status_e3}} |
| E3 CPBC recomputed (±0.5%) | ${{truth_cpbc}} | ${{app_cpbc}} | {{e3_cpbc_delta_pct}}% | {{status_e3}} |
| E4 Cross-client totals = SUM(clients) | {{sum_check_truth}} | {{sum_check_app}} | {{e4_delta}} | {{status_e4}} |
| E5 1:1 CAD/USD blend (Phase 4 caveat) | INFO | INFO | - | INFO |

---

{{if include_per_adset}}
## ORBIT-F: Per-adset drill-down (LOCAL mode)

{{for each adset with non-zero activity, sorted by spend desc, capped at top 20}}

### adset {{adset_id}} - {{adset_name}}

| Metric | Meta / truth | App drill-down | Status |
|---|---|---|---|
| Spend | ${{meta_spend}} | ${{app_spend}} | {{status}} |
| Impressions | {{meta_impressions}} | {{app_impressions}} | {{status}} |
| Inline link clicks | {{meta_clicks}} | {{app_clicks}} | {{status}} |
| Paid leads | {{truth_leads}} | {{app_leads}} | {{status}} |
| Paid booked | {{truth_booked}} | {{app_booked}} | {{status}} |

Orphan ads (meta_ad_id present, meta_adset_id null): {{orphan_count}}

{{if adset_mismatch}}
**Mismatch detail:**
- Missing contacts in app drill-down: {{missing_contact_ids}}
- Extra contacts in app drill-down: {{extra_contact_ids}}
{{end}}

{{end}}

{{if total_adsets > 20}}
**Note:** {{remaining_adsets}} additional ad sets aggregated below (no per-adset drill-down). Aggregate spend agrees within ±5%: {{aggregate_pass_or_fail}}.
{{end}}

---
{{end}}

## ORBIT-G: Sync freshness

| Client | Source | Latest started_at | ok flag | Status |
|---|---|---|---|---|
{{for each (client, source) row}}
| {{client_id}} | {{source}} | {{latest_started_at}} | {{ok}} | {{status}} |
{{end}}

{{if token_expiry_warnings > 0}}
**Token-expiry advisory (G3):**
{{for each expiring token}}
- {{client_id}}: `token_expires_at` = {{expires_at}} ({{days_remaining}} days remaining)
{{end}}
{{end}}

---

{{if include_code_static}}
## ORBIT-H: Code-static checks (LOCAL mode)

| Check | Result | Detail |
|---|---|---|
| H1 No `created_at`/`dateAdded`/`first_paid_opt_in_at` in `ads_paid_leads` queries | {{status_h1}} | {{h1_findings_count}} hits |
| H2 No bare `YYYY-MM-DD` strings to Meta / drill-down SQL without `clientWindow()` | {{status_h2}} | {{h2_findings_count}} hits |
| H3 `isLastTouchPaid()` defined exactly once | {{status_h3}} | {{h3_definition_count}} definitions found |

{{if h1_findings_count > 0}}
**H1 violations (BLOCKER):**
{{for each h1 hit}}
- `{{file}}:{{line}}` - `{{matched_text}}`
{{end}}
{{end}}

{{if h2_findings_count > 0}}
**H2 violations:**
{{for each h2 hit}}
- `{{file}}:{{line}}` - `{{matched_text}}`
{{end}}
{{end}}

{{if h3_definition_count != 1}}
**H3 violations:**
{{for each h3 hit}}
- `{{file}}:{{line}}`
{{end}}
{{end}}

---
{{end}}

## Raw counts (for spot-checking against Orbit / Meta Ads Manager / GHL UI)

```
Client:            {{client}}
Window:            {{window_start_iso}}  to  {{window_end_iso}}  (NY, yesterday + 2 prior)
Timezone:          {{client_timezone}}

Meta spend:        ${{meta_spend}}
Neon spend:        ${{neon_spend}}
App spend:         ${{app_spend}}

Meta impressions:  {{meta_impressions}}
Meta clicks:       {{meta_clicks}} (inline_link_clicks)

Paid leads, counted union (truth / neon / app):    {{truth_paid_leads}} / {{neon_paid_leads}} / {{app_paid_leads}}
Paid booked, counted (truth / neon / app):         {{truth_paid_booked}} / {{neon_paid_booked}} / {{app_paid_booked}}

CPL:               ${{app_cpl}}
CPBC:              ${{app_cpbc}}
```

---

## Next steps

{{if blocker_count > 0}}
1. Address the top-listed blocker first; subsequent failures may cascade from it.
2. After fix, re-run `/andy-the-auditor {{client_slug}}` to confirm.
3. If the blocker is a code-static violation (ORBIT-B2 or ORBIT-H1), the cited file:line IS the violator.
{{else if warn_count > 0}}
1. Review warnings, they signal drift that will become a blocker if ignored.
2. No re-run required today; next scheduled run at 7am ET tomorrow via `trig_01K8mpqa8e9F2DmBRHivNNPV`.
{{else}}
Nothing today. Next run scheduled via `trig_01K8mpqa8e9F2DmBRHivNNPV` at 7am ET tomorrow.
{{end}}

---

*Generated by /andy-the-auditor. Invariants source: ~/.claude/skills/andy-the-auditor/invariants/orbit.md. Edit invariants there, not in this report.*
