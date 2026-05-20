---
name: andy-the-auditor
description: End-to-end correctness audit for the Moreway Orbit Ads Command Center. Triangulates Meta Graph API ↔ Neon ↔ GHL/Hyros (upstream truth) ↔ Orbit's own API endpoints (display layer) across CG B2B + BuilderPro + OBB. Anchored on Zander's lead-attribution north star (`last_paid_opt_in_at` in window, contact age irrelevant). Writes per-client vault reports with machine-parseable frontmatter for Slack-bot consumption.
---

# andy-the-auditor

Andy is the guardrail against vibe-coding regressions in the Moreway Orbit Ads Command Center. He audits attribution correctness for the three live client surfaces — CareGenius B2B, BuilderPro, OBB Home Care — against the rules Zander actually wants the dashboard to enforce, and produces a per-client morning report.

This skill replaces the older `/attribution-audit` skill (which audited three separate dashboards in the pre-consolidation world). Orbit is the only ads dashboard now, so Andy is the only auditor.

---

## North star (the rule Andy defends on every check)

**A lead is a paid lead in a given window iff its paid opt-in event timestamp falls inside the window. The age of the contact is irrelevant. Re-opt-ins of older contacts COUNT.**

That single sentence has three consequences every layer of Orbit must agree on:

1. The window-filter column is `ads_paid_leads.last_paid_opt_in_at`. Never `created_at`, `dateAdded`, or `first_paid_opt_in_at`.
2. A booking is paid iff its parent contact's effective last touch is paid Meta AND `calendar_id` is in `ads_clients_config.ghl_paid_calendar_ids` for that client AND `booking_source ∈ ('booking_widget', NULL)`.
3. Paid lead count uses the **union semantics** at [api/ads/_drilldown-sql.ts:98-156](api/ads/_drilldown-sql.ts): `paid_leads = COUNT(DISTINCT contact_id) of (opt-iners with last_paid_opt_in_at in window) UNION (bookers with booked_at in window)`. Bookers whose original opt-in landed before the window still count as a lead.

The canonical paid predicate lives at [api/ads/_ghl-direct.ts:69-75 `isLastTouchPaid()`](api/ads/_ghl-direct.ts#L69): `(utmFbclid || fbclid || fbc) || utm_source.toLowerCase() ∈ {facebook, instagram, fb, ig, meta}`. No tag backup in Orbit (unlike the sister apps' BAC / OPT IN backup).

Every Andy check fails if a layer disagrees with these rules.

---

## Trigger phrases

- `/andy-the-auditor` — audit all three clients (default: vault mode, writes 3 per-client reports)
- `/andy-the-auditor caregenius` — CG B2B only
- `/andy-the-auditor builderpro` — BuilderPro only
- `/andy-the-auditor obb` — OBB only
- `/andy-the-auditor --slack ADS_AUDITS_SLACK_WEBHOOK` — Slack mode: skip vault writes, POST a summary to the webhook URL in `$ADS_AUDITS_SLACK_WEBHOOK`. Used by the daily routine `trig_01K8mpqa8e9F2DmBRHivNNPV`. Can be combined with a client filter (e.g. `/andy-the-auditor caregenius --slack ADS_AUDITS_SLACK_WEBHOOK`).
- Natural language: "andy", "audit orbit", "audit the dashboard", "is orbit accurate", "did I break the math", "check attribution"

---

## Inputs (none required; all auto-loaded)

Andy auto-loads:

- `~/.claude/skills/andy-the-auditor/invariants/orbit.md` — single canonical config (replaces the three sister-app invariants files).
- `~/Claude Code/Moreway/Moreway | Tasks/.env` — Orbit's local env: `DATABASE_URL`, `META_TOKEN_CAREGENIUS_B2B`, `META_TOKEN_BUILDERPRO`, `META_TOKEN_OBB`, `HYROS_KEY_OBB`, `GHL_*` (one set per client), `AUDIT_TOKEN`.
- `ads_clients_config` table in Neon — per-client config read at run time so Andy never goes stale on currency / timezone / calendar IDs.

If any required env var is missing, Andy halts with a bootstrap message rather than emitting a misleading green report.

---

## One-time bootstrap (do once)

Andy needs to call Orbit's API endpoints non-interactively, but Orbit's auth is session-token-only. Add a dedicated audit token:

1. **Generate a random token**:
   ```
   openssl rand -hex 32
   ```
2. **Add to Orbit's local `.env`**:
   ```
   AUDIT_TOKEN="<the random value>"
   ```
3. **Mirror to Vercel** (Production + Preview):
   ```
   vercel env add AUDIT_TOKEN production
   vercel env add AUDIT_TOKEN preview
   ```
4. **Verify Orbit code change is deployed** — Andy's first run will fail with `401` if [api/_db.ts `requireSession()`](api/_db.ts) hasn't been updated to accept `Authorization: Bearer ${AUDIT_TOKEN}`. See the andy-the-auditor implementation PR for the one-file change.

If `AUDIT_TOKEN` is missing locally, Andy degrades gracefully: Sections E1–E5 (API ↔ Neon) are SKIPPED with a bootstrap note. Sections A–D, F, G, H still run against Neon + Meta + GHL/Hyros directly.

---

## Execution flow

### Step 1 — Parse arguments, flags, and compute window

- Positional arg ∈ `caregenius` | `builderpro` | `obb` | empty (= all enabled clients in `ads_clients_config`).
- **`--slack <ENV_VAR_NAME>`** flag (optional). If present, switches to **Slack output mode**:
  - Skip ORBIT-F (per-adset drill-down) and ORBIT-H (code-static greps). Both require local repo access and are too slow for a 60s routine ceiling.
  - Skip vault writes. The remote sandbox has no Obsidian access.
  - POST a structured Slack summary to the webhook URL in `process.env[<ENV_VAR_NAME>]` (e.g. `--slack ADS_AUDITS_SLACK_WEBHOOK` reads from `$ADS_AUDITS_SLACK_WEBHOOK`).
  - Halt with a clear error if the env var is missing or empty.
- **Window** = Orbit's "Last 3 days" preset:
  - End = **yesterday** in `America/New_York` (today excluded — partial data skews CPL/CPBC, see [DateRangePresetPicker.tsx:60-78](src/components/ads-command-center/components/DateRangePresetPicker.tsx#L60))
  - Start = end minus 2 NY days
  - Today is 2026-05-19 → window = `2026-05-16` → `2026-05-18` (yesterday + 2 prior)
  - Tomorrow → window auto-shifts to `2026-05-17` → `2026-05-19`
- Per-client timezone is read from `ads_clients_config.timezone` (CG is NY, BP is LA, OBB is NY) and used inside `clientWindow()` from [api/ads/_drilldown-sql.ts:54-60](api/ads/_drilldown-sql.ts#L54) when computing exact timestamp boundaries.

> **Note:** Orbit's [api/ads/audit.ts:316-325 `defaultLast3Days()`](api/ads/audit.ts#L316) uses "today + 2 prior" (includes today) — that's a real inconsistency with the picker. Andy matches the picker. If you fix the audit endpoint's default later, Andy stays correct.

### Step 2 — Per target client

For each target client, run sections ORBIT-A through ORBIT-H below. Sections marked **(CG + BP only)** are skipped for OBB; sections marked **(OBB only)** are skipped for CG/BP.

#### ORBIT-A — Meta Graph API ↔ Neon `ads_meta_insights`

Per enabled client:

- **A1 (BLOCKER, ±5%)** — Spend. Meta `level=account` ↔ Neon `ads_meta_insights` rollup at `level='campaign'` summed over window.
- **A2 (BLOCKER, ±5%)** — Impressions.
- **A3 (BLOCKER, ±5%)** — Clicks. **Use `inline_link_clicks`**, NOT `clicks` (Meta's `clicks` includes all engagement). See [audit.ts:88-95](api/ads/audit.ts#L88).
- **A4 (WARN, ±5%)** — Derived: CPC, CPM, CTR (recomputed identically on both sides from spend/impressions/inline_link_clicks).

Most-recent day tolerance loosens to ±10% (Meta still aggregating).

Failure-mode hint: spend drift → [api/ads/sync-meta-insights.ts](api/ads/sync-meta-insights.ts) (date alignment / level filtering).

#### ORBIT-B — GHL (live) ↔ Neon `ads_paid_leads` (CG + BP only)

The north-star check. Use the canonical walker from [api/ads/_ghl-direct.ts `fetchGhlGroundTruthCounts()`](api/ads/_ghl-direct.ts) — same predicate Orbit's own sync uses, applied independently for the audit. Build the ground-truth set of (contact_id) tuples.

- **B1 (BLOCKER)** — Count equality: GHL-walked paid-in-window count == Neon `ads_paid_leads` rows where `last_paid_opt_in_at` in window. **Note:** Neon also pulls in bookers via the UNION (`fetchGhlCountsFromNeon` at [api/ads/_sources.ts:77-99](api/ads/_sources.ts#L77)), so the audit also walks GHL calendar events for the window and computes the same UNION on the live side before comparing. If counts differ, report the delta and sample contact IDs missing-in-Neon / extra-in-Neon.
- **B2 (BLOCKER, GOLDEN RULE)** — Code-static check: no `created_at` / `dateAdded` / `first_paid_opt_in_at` references inside window filters of any `api/ads/*.ts` or `src/**/*.ts`. Grep for these tokens; failure = automatic FAIL with file:line.
- **B3 (BLOCKER)** — Re-opt-in survives: pick a contact in the GHL-walked set whose `dateAdded < window_start` but whose `last_paid_opt_in_at` is in window. Confirm they're in Neon. If no such contact exists in this window, log INFO ("no re-opt-ins available to test this window").

#### ORBIT-C — GHL bookings ↔ Neon `ads_paid_bookings` (CG + BP only)

Use [`fetchGhlBookedCallsGroundTruth()` in _ghl-direct.ts](api/ads/_ghl-direct.ts) to walk `/calendars/events` for each `ghl_paid_calendar_ids` value in `ads_clients_config`, apply `isLastTouchPaid()` to each event's parent contact.

- **C1 (BLOCKER)** — Count equality: GHL-walked paid booked count == Neon `ads_paid_bookings` rows where `booked_at` in window. Sample missing/extra `appointment_id` on delta.
- **C2 (BLOCKER, ±5%)** — `cost_per_booked = SUM(spend) / |paid_booked_set|` within ±5% of what `/api/ads/overview` returns for `clients.<id>.cpbc` (or computed from response if Andy runs in direct-only mode).

#### ORBIT-D — Hyros ↔ Orbit API for OBB (OBB only)

Hit Hyros `/v1/api/v1.0/calls` directly (key in `HYROS_KEY_OBB`). The API reads Hyros directly via [_sources.ts:155-179 `fetchHyrosCallsCount()`](api/ads/_sources.ts#L155), so this is API ↔ Hyros (not Neon ↔ Hyros).

- **D1 (SKIP)** — OBB paid leads. Hyros `/leads` has no server-side date filter; Orbit returns `null`. Logged as SKIPPED, not FAIL. Promote to BLOCKER when Phase 3 (paginate + cache Hyros leads in Neon) ships.
- **D2 (BLOCKER)** — Hyros paid booked count == `clients.obb.paid_booked_calls` from `/api/ads/overview`. Predicate: `firstSource.organic !== true && firstSource.adSource.platform === 'FACEBOOK'` (matches [_sources.ts:141-143](api/ads/_sources.ts#L141)).
- **D3 (WARN)** — `HYROS_KEY_OBB` not nearing expiry (advisory; Hyros keys don't have a documented introspection endpoint, so this is a stub for now).

#### ORBIT-E — Orbit API ↔ Neon (display-layer verification)

Hit `GET /api/ads/overview?date_start=…&date_end=…` with `Authorization: Bearer ${AUDIT_TOKEN}`. Compare to direct Neon queries.

- **E1 (BLOCKER, exact)** — Per-client `spend / impressions / clicks` matches Neon rollup to the cent / unit (both read the same rows; any drift = aggregation bug in [api/ads/overview.ts:58-75](api/ads/overview.ts#L58)).
- **E2 (BLOCKER, exact)** — Per-client `paid_leads / paid_booked_calls` matches Section B + C ground truth (or D2 for OBB) exactly.
- **E3 (BLOCKER, ±0.5%)** — Per-client `cpl = spend / paid_leads` and `cpbc = spend / paid_booked_calls` recomputed within ±0.5%. Formula at [api/ads/overview.ts:208-209](api/ads/overview.ts#L208).
- **E4 (BLOCKER, exact)** — `totals.spend == SUM(clients.*.spend)`, same for impressions, clicks, paid_leads, paid_booked_calls. Cross-client strip math at [CrossClientStrip.tsx:43-76](src/components/ads-command-center/components/CrossClientStrip.tsx#L43) and aggregation at [overview.ts:212-233](api/ads/overview.ts#L212).
- **E5 (INFO)** — 1:1 CAD/USD blend in totals is a known caveat (Phase 4 = live FX). Logged, never failed.

#### ORBIT-F — Per-adset drill-down attribution

For each adset with non-zero activity in the window (spend > 0 OR leads > 0 OR booked > 0), call `GET /api/ads/drilldown/adsets?client_id=…&campaign_id=…&date_start=…&date_end=…`. Cap top 20 by spend; aggregate-check the remainder.

- **F1 (BLOCKER, ±5%)** — Meta `level=adset` spend / impressions / clicks ↔ Orbit's drilldown response.
- **F2 (BLOCKER)** — Sum of per-adset `paid_leads` == client total `paid_leads` from `/api/ads/overview`. No orphan ads (where `meta_ad_id` is populated but `meta_adset_id` is null).
- **F3 (BLOCKER)** — Same for per-adset `paid_booked_calls`.

#### ORBIT-G — Sync freshness

Read `ads_sync_log` per `(client_id, source)`.

- **G1 (BLOCKER)** — Each enabled client has rows for `meta_insights`, `meta_structure`, and `ghl` (CG/BP) or `hyros` (OBB) with latest `started_at` within last 24h AND latest row's `ok = true`.
- **G2 (WARN)** — Latest `ads_paid_leads.last_paid_opt_in_at` per CG/BP client within last 48h when window spend > 0 (detects silent GHL-walk regression).
- **G3 (WARN)** — `ads_clients_config.token_expires_at` per client > 14 days out. For BuilderPro, current expiry is 2026-06-18 per memory — flag when within window.

#### ORBIT-H — Code-static checks (read-only grep)

Read-only grep against the Orbit repo. Each is INFO unless it directly violates the north star.

- **H1 (BLOCKER)** — No `created_at` / `dateAdded` / `first_paid_opt_in_at` inside any query touching `ads_paid_leads`. Same as B2 but broader — covers any callsite, not just the audit's own.
- **H2 (WARN)** — No bare `YYYY-MM-DD` strings passed to Meta Graph or to drill-down SQL without `clientWindow(timezone, ...)`. Bare strings get parsed as UTC midnight and shift the window 4-5 hours.
- **H3 (WARN)** — `isLastTouchPaid()` defined exactly once in the repo (drift detector: a re-implementation in a second file is a regression class).

### Step 3 — Aggregate and emit

For each client, total PASS / WARN / FAIL across all sections.

#### 3a — Vault mode (default)

Render the report using `~/.claude/skills/andy-the-auditor/templates/report-template.md`.

**Day-over-day delta**: read yesterday's report if it exists; surface any check that flipped from PASS → FAIL or PASS → WARN today at the very top under a "Newly failing since yesterday" section.

Write to:
```
~/Obsidian/Vault/20-Clients/CareGenius/attribution-audits/YYYY-MM-DD.md      # CG B2B
~/Obsidian/Vault/20-Clients/BuilderPro/attribution-audits/YYYY-MM-DD.md      # BP
~/Obsidian/Vault/20-Clients/_Moreway-Agency/attribution-audits/YYYY-MM-DD.md # OBB + cross-client totals + Hyros notes
```

If the per-client folder doesn't exist, create it.

#### 3b — Slack mode (--slack ENV_VAR)

POST a single Slack message to the webhook URL stored in `process.env[ENV_VAR]`. Format:

**Main message** (one line per client + a top header):

```
*Orbit Attribution Audit — {{date}} ({{window_label}})*
{{client_emoji}} CareGenius: {{status_word}} ({{counts}})
{{client_emoji}} BuilderPro: {{status_word}} ({{counts}})
{{client_emoji}} OBB: {{status_word}} ({{counts}})
Skill version: `{{skill_sha_or_version}}`
```

Where `{{status_word}}` ∈ "all clear", "WARN", "FAIL"; `{{client_emoji}}` ∈ ✅ ⚠️ ❌; `{{counts}}` is e.g. "ORBIT-A through G, 0 blockers, 1 warning".

**Threaded reply** (only when ANY client status != PASS) — for each failed/warning check across all clients:

```
{{client}} :: {{check_id}} ({{severity}}) — {{one_line_explanation}}
  truth: {{truth_value}}  app: {{app_value}}  delta: {{delta}}
  likely owner: {{file_path}}:{{line}}
```

Skip vault writes entirely in Slack mode. Skip ORBIT-F and ORBIT-H sections (not run). Include the skill commit SHA (from `git -C ~/.claude/skills/andy-the-auditor rev-parse --short HEAD` if available, else "unversioned") so Zander can see which version of the skill produced the message.

If the Slack POST fails (non-2xx response), retry once with exponential backoff, then halt with the response body printed to stdout (the routine logs that).

### Step 4 — Surface in terminal (vault mode only)

After writing files in vault mode:

1. If any BLOCKER failed, print a top banner with the failed check IDs and a one-line summary each, plus file:line hints from the failure-mode map.
2. Print the vault note path(s) so Zander can click and read.
3. Print PASS / WARN / FAIL totals per client.
4. Do NOT print the full report inline — the vault notes are the artifact.

Example banner:

```
✗ CG B2B: ORBIT-B1 paid lead set off by 3 contacts — vault://20-Clients/CareGenius/attribution-audits/2026-05-19.md
✓ BuilderPro: all 22 checks green
⚠ OBB: ORBIT-G2 sync stale (last GHL run 27h ago) — vault://20-Clients/_Moreway-Agency/attribution-audits/2026-05-19.md
```

In `--slack` mode, terminal output is minimal: one line confirming the POST succeeded and the message ts (Slack timestamp) for thread anchoring. The routine's logs capture this for debugging.

---

## Failure-mode → file mapping

When a check fails, Andy includes a likely-owner hint in the report. The mapping:

| Symptom | Likely file |
|---|---|
| ORBIT-A spend mismatch | [api/ads/sync-meta-insights.ts](api/ads/sync-meta-insights.ts) — date alignment, level filtering |
| ORBIT-A clicks drift | [api/ads/audit.ts:88-95](api/ads/audit.ts#L88) — `inline_link_clicks` vs `clicks` |
| ORBIT-B count off | [api/ads/sync-conversions.ts](api/ads/sync-conversions.ts) — paid-attribution logic in walker, 14-day stale cutoff |
| ORBIT-B golden rule violation | grep target file:line; the violator query lives at the cited line |
| ORBIT-C booked count off | [api/ads/sync-conversions.ts](api/ads/sync-conversions.ts) — calendar filter, booking_source filter |
| ORBIT-D Hyros count off | [api/ads/_sources.ts:123-150](api/ads/_sources.ts#L123) — Hyros pagination, organic filter |
| ORBIT-E aggregation off | [api/ads/overview.ts:212-233](api/ads/overview.ts#L212) — cross-client SUM logic |
| ORBIT-E CPL/CPBC off | [api/ads/overview.ts:208-209](api/ads/overview.ts#L208) — null-safe formulas |
| ORBIT-F orphan ads | structure walker in [api/ads/sync-meta-structure.ts](api/ads/sync-meta-structure.ts) — missing `parent_id`/`campaign_id` on ad rows |
| ORBIT-G stale | [api/ads/cron-orchestrator.ts](api/ads/cron-orchestrator.ts) + cron schedule in `vercel.json` |
| ORBIT-H1 code-static fail | the grep hit's file:line |

---

## Vault report layout

Three per-client files per day, identical frontmatter shape. See `~/.claude/skills/andy-the-auditor/templates/report-template.md`.

Frontmatter (required for Slack-bot consumption):

```yaml
---
date: YYYY-MM-DD
client: CareGenius | BuilderPro | Moreway-Agency
window_start: YYYY-MM-DD
window_end: YYYY-MM-DD
window_days: 3
run_type: scheduled | manual
status: PASS | WARN | FAIL
blockers: 0
warnings: 0
passes: 0
summary_one_line: "CG ✓ — all 9 checks passed within tolerance"
failed_checks: []           # ["ORBIT-B1", "ORBIT-E4"] when status != PASS
warning_checks: []
notable_findings: []
---
```

Status rules:
- `status = FAIL` if any BLOCKER failed
- `status = WARN` if no BLOCKERs but at least one WARN failed
- `status = PASS` otherwise

`summary_one_line` < 100 chars, Slack-friendly.

---

## Scheduling

Andy already has a daily scheduled run. The existing remote routine `trig_01K8mpqa8e9F2DmBRHivNNPV` ("Attribution Audit 7am ET", fires `0 11 * * *` UTC) invokes `/andy-the-auditor --slack ADS_AUDITS_SLACK_WEBHOOK` and posts to `#ads-audits`. **Do NOT create a separate `/schedule` entry** — the routine is already wired.

When Zander updates the local skill (this directory), `cco` syncs the change to the Anthropic cloud, and the next morning's routine firing picks it up automatically. Single source of truth: edit here, both vault (manual local runs) and Slack (daily routine) outputs reflect the change.

For VAULT reports specifically (the deep audit, including ORBIT-F and ORBIT-H): run `/andy-the-auditor` manually whenever you want them, or wire a separate local-scheduler entry that doesn't conflict with the remote routine.

Force a cloud re-sync if the Slack message looks stale: invoke `/cco` and promote/refresh the skill scope.

---

## Known limitations & future work

- **Hyros leads (ORBIT-D1)** — Hyros `/leads` has no server-side date filter; counts stay null until Phase 3 (paginate + cache in Neon like the GHL path). Until then, OBB paid leads are SKIPPED, not audited.
- **GHL walker timezone** — [_ghl-direct.ts:165-166](api/ads/_ghl-direct.ts#L165) builds the window as UTC (`T00:00:00Z` / `T23:59:59.999Z`), while Neon's union semantics use client-tz-aware boundaries via [_drilldown-sql.ts `clientWindow()`](api/ads/_drilldown-sql.ts#L54). A contact whose lastTouch is e.g. 23:00 EST can fall in different windows depending on path. Treat as a known low-magnitude drift class until the walker also uses `clientWindow()`.
- **Pre-commit / post-edit hooks** — out of scope; Andy is the post-hoc audit.
- **OBB Hyros key introspection** — not available; D3 is a stub.

---

## File map

```
~/.claude/skills/andy-the-auditor/
├── SKILL.md                                # this file
├── invariants/
│   └── orbit.md                            # single canonical config (account, env, rules, tolerances, queries)
├── references/
│   └── orbit-architecture.md               # cross-layer explainer with file:line refs
└── templates/
    └── report-template.md                  # vault report layout + frontmatter spec
```

Old skill at `~/.claude/skills/attribution-audit/` is kept read-only as a fallback until andy is validated against a clean run. Delete after two consecutive green Andy runs.
