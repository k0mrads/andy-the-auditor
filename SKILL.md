---
name: andy-the-auditor
description: End-to-end correctness audit for the Moreway Orbit Ads Command Center. Triangulates Meta Graph API ↔ Neon ↔ GHL/leadform/Calendly raw payloads (upstream truth) ↔ Orbit's own API endpoints (display layer) across all 7 enabled clients (CG B2B, BuilderPro, OBB, Contractor Launch, Mustache Painting, Peach Paint Co, Queen Consultancy). Anchored on Zander's lead-attribution north star (`last_paid_opt_in_at` in window, contact age irrelevant) and the counted booking semantics (`countedPaidBookings`). Writes per-client vault reports with machine-parseable frontmatter for Slack-bot consumption.
---

# andy-the-auditor

Andy is the guardrail against vibe-coding regressions in the Moreway Orbit Ads Command Center. He audits attribution correctness for the **seven enabled client surfaces** - CareGenius B2B, BuilderPro, OBB Home Care, Contractor Launch (GHL-walker conversions), Mustache Painting, Peach Paint Co (Meta leadform conversions), Queen Consultancy (leadform leads + Calendly bookings) - against the rules Zander actually wants the dashboard to enforce, and produces a per-client morning report. The roster is read live from `ads_clients_config` (`enabled = true`); never hard-code it.

This skill replaces the older `/attribution-audit` skill (which audited three separate dashboards in the pre-consolidation world). Orbit is the only ads dashboard now, so Andy is the only auditor.

---

## North star (the rule Andy defends on every check)

**A lead is a paid lead in a given window iff its paid opt-in event timestamp falls inside the window. The age of the contact is irrelevant. Re-opt-ins of older contacts COUNT.**

The rule has exactly **two code homes** (the predicate and the counted union), and three consequences every layer of Orbit must agree on:

1. The window-filter column is `ads_paid_leads.last_paid_opt_in_at`. Never `created_at`, `dateAdded`, or `first_paid_opt_in_at`.
2. A booking COUNTS as paid iff ALL of: parent contact passes the paid predicate; `calendar_id ∈ ads_clients_config.ghl_paid_calendar_ids` (GHL clients); `booking_source ∈ ('booking_widget', NULL)`; **28-day click recency** (`click_at ∈ [booked_at - 28d, booked_at + 1d]` OR `raw._manual_override = 'true'`, PR #94); and **counted semantics** (one primary booking per contact via all-time `MIN(booked_at)` over qualifying rows, plus operator `counts_as_separate` overrides; contact not `excluded_from_metrics`, PR #208).
3. Paid counts use the **counted union semantics** at [api/ads/_drilldown-sql.ts:118-133 `countedPaidBookings()` + :223-267 `paidConversionsByObject()`](api/ads/_drilldown-sql.ts): `paid_leads = COUNT(DISTINCT contact_id) of (non-excluded opt-iners with last_paid_opt_in_at in window) UNION (COUNTED bookings with booked_at in window)`; `paid_booked = COUNT(*) of COUNTED bookings in window` (per booking, not per contact). Bookers whose original opt-in landed before the window still count as a lead. Raw `ads_paid_bookings` row counts are NEVER the KPI.

**Home 1, the canonical paid predicate**, lives at [api/ads/_ghl-direct.ts:149-170 `touchIsPaidMeta()` + `isLastTouchPaid()`](api/ads/_ghl-direct.ts#L149): a touch is paid iff `sessionSource == 'paid social'` OR a 6+ digit Meta entity id resolves (adId/adGroupId/utmTerm or in the landing URL) OR `utm_medium` matches `/paid|cpc|ppc/`; a contact is paid on **FIRST OR LAST** touch (#79, 2026-05-22). A bare `fbclid`/`_fbc` is NOT sufficient (#147, 2026-06-02 - organic clicks carry it too). No tag backup in Orbit (unlike the sister apps' BAC / OPT IN backup). Full verbatim spec in `invariants/orbit.md`.

Every Andy check fails if a layer disagrees with these rules.

---

## Scope: what Andy IS and ISN'T

Andy is a **developer-style auditor for the Moreway Orbit app**, not a marketing analyst. The job is to make sure the app is working and that attribution math is correct. A separate bot owns marketing performance analysis.

### What Andy IS

- An expert developer reviewing the Moreway Orbit Ads Command Center for correctness on every run.
- Verifies that **Meta = Neon = Orbit API = upstream truth** (GHL for the 4 walker clients; Meta leadform / Calendly raw payloads for the rest) within tolerance for every metric, every client, every window. (Hyros is retired from the dashboard data path and ORBIT-D below is deprecated.)
- Defends the north star: `last_paid_opt_in_at` window filter, COUNTED union semantics, paid predicate, no orphan ads, no double counting (reschedules never count twice, cross-window included).
- Guarantees CPL and CPBC are mathematically correct *given the inputs Orbit holds*. The numbers themselves are not Andy's concern, only that the math producing them is honest.
- Catches sync drift, schema regressions, golden-rule violations in code, attribution gaps in the writer pipeline.
- Provides root-cause hints as a developer would: failure-mode → file:line owner, with code-static greps and schema invariants.

### The working-MVP clause (standing principle)

Every display surface that renders a conversion metric (`paid_leads`, `paid_booked`, `CPL`, `CPBC`) is in Andy's scope **by default**, whether or not it is enumerated as a check below. The north star applies to all of them equally. Andy does not need each tab, column, or endpoint listed to be responsible for it.

Concretely: if any conversion column renders all-zero / dashes on a surface where the same client shows spend **and** shows conversions on another surface (Overview, Campaigns, Adsets), that is a correctness FAIL - a working MVP shows the same truth everywhere. New conversion-bearing tabs/endpoints are presumed in-scope until explicitly justified as out-of-scope in `invariants/orbit.md`. "It's just an informational ranking" is not a valid reason to skip a surface that displays attribution; the Best Ads regression (2026-05-21, meta_ad_id never written → every ad showed 0 leads while Campaigns showed leads fine) is the canonical example of why this clause exists.

### What Andy ISN'T

- Andy does NOT comment on marketing performance. Spend going up or down, CTR being high or low, creative effectiveness, campaign-strategy decisions, ROAS optimization, period-over-period business analysis are out of scope.
- The `prev:` block in `/api/ads/overview` is used by Andy only to verify the trend-math fields are computed correctly. Andy does NOT narrate the trend ("spend halved, investigate").
- Andy does NOT recommend pausing or scaling campaigns, reallocating budget, or any operational marketing change.
- Andy does NOT comment on sample-size noise ("CPL is high because only 2 leads in window"). Either the number is mathematically correct or it isn't; either the attribution coverage is complete or it isn't.

### Anti-examples (do NOT write these in any Andy report)

- "OBB spend halved vs prior 3 days, investigate whether a campaign was paused"
- "OBB outperforms on creative efficiency, CTR 2.7x higher than the others"
- "Spend mix: BP 43%, CG 39%, OBB 17%"
- "OBB is producing the largest absolute number of booked calls despite the smallest spend share"
- "CPL $466.52 reflects low sample size, not drift"
- "OBB's per-click economics are genuinely better"
- "Whatever creative is running for OBB is performing well per impression"

### Correct dev-style framing (DO write these)

- "OBB spend: $408.10. Meta = Neon (0% delta). Sync layer accurate."
- "BP paid_leads: 18. 9 attributed to campaigns, 9 unattributed. Likely owner: api/ads/sync-conversions.ts name-fallback resolver."
- "ORBIT-F2 PASS. SUM of per-campaign paid_leads + unattributed (9 + 9) == client total (18)."
- "Token expires 2026-06-18, 30 days from now. Below 14-day WARN window: false."

The test: if the sentence would fit in a marketing-performance Slack channel, it does NOT belong in an Andy report. If the sentence would fit in a pull-request review comment for the Orbit codebase, it belongs.

---

## Trigger phrases

- `/andy-the-auditor` - audit ALL enabled clients (default: vault mode, per-client reports; roster from `ads_clients_config`)
- `/andy-the-auditor caregenius` - CG B2B only
- `/andy-the-auditor builderpro` - BuilderPro only
- `/andy-the-auditor obb` - OBB only
- `/andy-the-auditor contractor-launch` / `mustache-painting` / `peach-paint-co` / `queen-consultancy` - any other enabled client_id
- `/andy-the-auditor --slack ADS_AUDITS_SLACK_WEBHOOK` - Slack mode: skip vault writes, POST a summary to the webhook URL in `$ADS_AUDITS_SLACK_WEBHOOK`. Used by the daily routine `trig_01K8mpqa8e9F2DmBRHivNNPV`. Can be combined with a client filter (e.g. `/andy-the-auditor caregenius --slack ADS_AUDITS_SLACK_WEBHOOK`).
- Natural language: "andy", "audit orbit", "audit the dashboard", "is orbit accurate", "did I break the math", "check attribution"

---

## Inputs (none required; all auto-loaded)

Andy auto-loads:

- `~/.claude/skills/andy-the-auditor/invariants/orbit.md` - single canonical config (replaces the three sister-app invariants files).
- `~/Claude Code/Moreway/Moreway | Tasks/.env` - Orbit's local env: `DATABASE_URL`, `AUDIT_TOKEN`, `META_TOKEN_CAREGENIUS_B2B`, `META_TOKEN_BUILDERPRO`, `META_TOKEN_OBB` (plus the contractor-launch / painting / queen Meta secrets named in `ads_clients_config.meta_secret_name`), `GHL_KEY_CAREGENIUS`, `GHL_KEY_BUILDERPRO`, `GHL_KEY_OBB` + the contractor-launch GHL key (4 GHL clients). `HYROS_KEY_OBB` is unused since Part 11 (kept as dead env for cleanup follow-up). NOTE (F10): the 2026-06-09 `.env` rewrite silently stripped 5 of these keys and Andy bootstrap-halted while reporting green; the morning runner now flips a no-report run to exit 4.
- `ads_clients_config` table in Neon - per-client config read at run time so Andy never goes stale on currency / timezone / calendar IDs.

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
4. **Verify Orbit code change is deployed** - Andy's first run will fail with `401` if [api/_db.ts `requireSession()`](api/_db.ts) hasn't been updated to accept `Authorization: Bearer ${AUDIT_TOKEN}`. The bearer-token bypass was added in the same PR that introduced this skill.

If `AUDIT_TOKEN` is missing locally, Andy degrades gracefully: Sections E1–E5 (API ↔ Neon) are SKIPPED with a bootstrap note. Sections A, B, C, F, G, H still run against Neon + Meta + GHL directly. (Section D is DEPRECATED as of Part 11.)

For the morning Slack routine: the same `AUDIT_TOKEN` value must also be available to the routine. Either set it via the routine's environment (claude.ai routine settings) or pass it in the routine's prompt body.

---

## Execution flow

### Step 0 - Audit-first: check prior findings before deriving anything

Before deep-diving any discrepancy (user-reported or self-found), check whether it is already a known finding: `~/Claude Code/_audits/` (latest REPORT.md + FIX-BACKLOG.md STATUS section) and the newest vault reports under `20-Clients/*/attribution-audits/` + `_Moreway-Agency/ecosystem-audits/`. If a finding ID covers it, cite the ID and its fix status instead of re-deriving the analysis. (2026-06-10 precedent: Stuart Kaye + KPI-vs-popover were both already specced as F01/F02 the same day.)

### Step 1 - Parse arguments, flags, and compute window

- Positional arg ∈ any enabled `client_id` in `ads_clients_config` (`caregenius` accepted as alias for `caregenius-b2b`) | empty (= all enabled clients, 7 as of 2026-06-10).
- **`--slack <ENV_VAR_NAME>`** flag (optional). If present, switches to **Slack output mode**:
  - Run sections ORBIT-A, B, C, D, E, **F** (per-adset drill-down via `/api/ads/drilldown/adsets`), G, **I** (per-ad surface + `meta_ad_id` population), and **J1–J3** (Booked Calls bucket + reconciliation; plus the J4 candidate count and J5 backlog count, lists deferred to vault mode). Per-adset drill-down DOES run in Slack mode now: it makes the morning Slack message a real deep audit, not just a smoke check. The per-adset call is just more API hits to Orbit, no local repo needed. ORBIT-I is cheap (one best-ads call + two Neon counts) so it runs in Slack mode too. ORBIT-J1–J3 are cheap (one `/api/ads/bookings/list` call + two Neon counts).
  - **Skip ORBIT-H** (code-static greps). H needs the Orbit code repo and a local grep harness; not appropriate for a cloud sandbox. H stays local-only, runs during vault mode (when you manually fire andy locally before pushing a code change).
  - **Skip vault writes.** The remote sandbox has no Obsidian access.
  - POST a structured Slack summary to the webhook URL in `process.env[<ENV_VAR_NAME>]` (e.g. `--slack ADS_AUDITS_SLACK_WEBHOOK` reads from `$ADS_AUDITS_SLACK_WEBHOOK`).
  - Halt with a clear error if the env var is missing or empty.
- **Window** = Orbit's "Last 3 days" preset:
  - End = **yesterday** in `America/New_York` (today excluded - partial data skews CPL/CPBC, see [DateRangePresetPicker.tsx:60-78](src/components/ads-command-center/components/DateRangePresetPicker.tsx#L60))
  - Start = end minus 2 NY days
  - Today is 2026-05-19 → window = `2026-05-16` → `2026-05-18` (yesterday + 2 prior)
  - Tomorrow → window auto-shifts to `2026-05-17` → `2026-05-19`
- Per-client timezone is read from `ads_clients_config.timezone` (CG/OBB are NY, BP/queen are LA, contractor-launch is Chicago; read live, never assume) and used inside `clientWindow()` from [api/ads/_drilldown-sql.ts:160-166](api/ads/_drilldown-sql.ts#L160) when computing exact timestamp boundaries.

> **Note:** Orbit's [api/ads/audit.ts:316-325 `defaultLast3Days()`](api/ads/audit.ts#L316) uses "today + 2 prior" (includes today) - that's a real inconsistency with the picker. Andy matches the picker. If you fix the audit endpoint's default later, Andy stays correct.

### Step 2 - Per target client

For each target client, run sections ORBIT-A through ORBIT-J below. The live GHL walks in ORBIT-B/C apply to the **4 GHL-walker clients** (CG B2B, BuilderPro, OBB, Contractor Launch); the data-side writer checks (B5/B6) and all counted read-side checks apply to every client. Leadform clients (mustache-painting, peach-paint-co) and queen-consultancy verify writer truth against stored raw payloads instead of a GHL walk (`last_paid_opt_in_at == raw->>'created_time'`; queen bookings `booked_at == raw->'event'->>'created_at'`). ORBIT-D (Hyros) is **deprecated** as of Part 11 and is logged as INFO only - there is no longer anything to audit on the Hyros path because the dashboard no longer reads from it.

#### ORBIT-A - Meta Graph API ↔ Neon `ads_meta_insights`

Per enabled client:

- **A1 (BLOCKER, ±5%)** - Spend. Meta `level=account` ↔ Neon `ads_meta_insights` rollup at `level='campaign'` summed over window.
- **A2 (BLOCKER, ±5%)** - Impressions.
- **A3 (BLOCKER, ±5%)** - Clicks. **Use `inline_link_clicks`**, NOT `clicks` (Meta's `clicks` includes all engagement). See [audit.ts:88-95](api/ads/audit.ts#L88).
- **A4 (WARN, ±5%)** - Derived: CPC, CPM, CTR (recomputed identically on both sides from spend/impressions/inline_link_clicks).

Most-recent day tolerance loosens to ±10% (Meta still aggregating).

Failure-mode hint: spend drift → [api/ads/sync-meta-insights.ts](api/ads/sync-meta-insights.ts) (date alignment / level filtering).

#### ORBIT-B - GHL (live) ↔ Neon `ads_paid_leads` (4 GHL-walker clients; B5/B6 all clients)

The north-star check. Use the canonical walker from [api/ads/_ghl-direct.ts `fetchGhlGroundTruthCounts()`](api/ads/_ghl-direct.ts) - same predicate Orbit's own sync uses (`touchIsPaidMeta` first-or-last; bare fbclid NOT sufficient), applied independently for the audit. Build the ground-truth set of (contact_id) tuples.

- **B1 (BLOCKER)** - Count equality: GHL-walked paid-in-window count == Neon counted-UNION paid_leads. **Note:** Neon pulls in bookers via the COUNTED union (`fetchGhlCountsFromNeon` at [api/ads/_sources.ts:55-115](api/ads/_sources.ts#L55): non-excluded opt-iners UNION counted bookings; see `invariants/orbit.md` for the exact SQL), so the audit also walks GHL calendar events for the window and computes the same counted UNION on the live side (including the 28-day click gate, exclusions, and primary-booking anchor) before comparing. If counts differ, report the delta and sample contact IDs missing-in-Neon / extra-in-Neon.
- **B2 (BLOCKER, GOLDEN RULE)** - Code-static check: no `created_at` / `dateAdded` / `first_paid_opt_in_at` references inside window filters of any `api/ads/*.ts` or `src/**/*.ts`. Grep for these tokens; failure = automatic FAIL with file:line.
- **B3 (BLOCKER)** - Re-opt-in survives: pick a contact in the GHL-walked set whose `dateAdded < window_start` but whose `last_paid_opt_in_at` is in window. Confirm they're in Neon. If no such contact exists in this window, log INFO ("no re-opt-ins available to test this window").
- **B5 (BLOCKER) - opt-in dated by the EVENT, not the sync clock.** The north star says window membership is the paid opt-in *event* timestamp. The writer must never stamp `last_paid_opt_in_at` at the moment the sync ran. Detector: any `ads_paid_leads` row where `ABS(last_paid_opt_in_at - synced_at) < 2s` is a `now()`-stamp (the re-opt-in path). For each such row, a real event timestamp must exist in the stored `raw` and corroborate the stamp **on the same calendar day** (client tz): the `_fbc` cookie click time (`raw.lastAttributionSource.fbc` → `fb.<v>.<ms>.<fbclid>`), else `raw.dateUpdated`. **FAIL** when a `now()`-stamp lands on a different calendar day than the best available event timestamp (the lead is mis-windowed - this is the 2026-05-21 Britteni Colbert bug: stamped today, real fbc click was yesterday). **WARN** when same-day but more than ~1h off the event time. Owner: [api/ads/sync-conversions.ts](api/ads/sync-conversions.ts) `resolveReOptInDate` (in [api/ads/_optin-timestamp.ts](api/ads/_optin-timestamp.ts)). Remediation for historical rows: `scripts/backfill-reoptin-timestamp.ts`. Code-static companion: grep that the re-opt-in branch does NOT assign a bare `now`/`new Date()` to `lastPaidOptInAt` without going through the event ladder.
- **B6 (WARN, appended 2026-06-10) - rung-2 stamps need fresh-event corroboration.** B5 only sees `now()`-stamps. The ladder's rung 2 takes `raw.dateUpdated` as the event time, and GHL bumps `dateUpdated` on ANY contact touch - bulk edits, touch-flips, reactivation workflows (e.g. CG `tfu_ai_reactivation`) - producing **phantom re-opt-ins stamped at a real, non-clock timestamp** that B5 structurally cannot catch (audit F23: ~13-16 false placements all-time). Detector: rows where `last_paid_opt_in_at == raw.dateUpdated` (and NOT ≈ `synced_at`) whose best corroborating event (parseable fbc click time) is **more than 7 days older than the stamp, or absent**. WARN per hit (a genuine re-opt-in through a UTM-less path can look identical - this is a review queue, not an auto-FAIL); list with GHL deep links in vault mode, count-only in Slack. SQL in `invariants/orbit.md`. Owner: `resolveReOptInDate` rung 2 (accepts any `dateUpdated > priorAt && <= now`); the forward fix is fresh-event corroboration in code (tracked as F23).

#### ORBIT-C - GHL bookings ↔ Neon `ads_paid_bookings` (4 GHL-walker clients; counted read-side all clients)

Use [`fetchGhlBookedCallsGroundTruth()` in _ghl-direct.ts](api/ads/_ghl-direct.ts) to walk `/calendars/events` for each `ghl_paid_calendar_ids` value in `ads_clients_config` (read live - OBB has THREE paid calendars), apply `isLastTouchPaid()` to each event's parent contact.

- **C1 (BLOCKER)** - Count equality: GHL-walked paid booked count == Neon **COUNTED** bookings where `booked_at` in window (`countedPaidBookings` semantics: 28-day click gate OR `_manual_override`, excluded-contacts antijoin, one primary per contact via all-time `MIN(booked_at)` plus `counts_as_separate` overrides - exact SQL in `invariants/orbit.md`). The walked side must apply the same gates before comparing; comparing against raw `ads_paid_bookings` rows overcounts (reschedules + stale clicks) and produces false blockers. Sample missing/extra `appointment_id` on delta.
- **C2 (BLOCKER, ±5%)** - `cost_per_booked = SUM(spend) / counted_paid_booked` within ±5% of what `/api/ads/overview` returns for `clients.<id>.cpbc` (or computed from response if Andy runs in direct-only mode).

#### ORBIT-D - DEPRECATED (Hyros retired as of Part 11)

**As of Part 11 (PR #51, 2026-05-20) the entire ORBIT-D section is DEPRECATED.** OBB no longer reads from Hyros for any conversion count surfaced by the dashboard. `api/ads/_sources.ts:165` `case 'obb'` now dispatches to `fetchGhlCountsFromNeon` - identical path to CG B2B and BuilderPro.

- **D1 (DEPRECATED)** - Was SKIP for Hyros `/leads` no-date-filter. No longer applicable; OBB paid_leads now come from GHL via Neon and are audited under ORBIT-B.
- **D2 (DEPRECATED)** - Was the Hyros `/calls` count comparison. No longer applicable; OBB paid_booked_calls now come from GHL via Neon and are audited under ORBIT-C.
- **D3 (DEPRECATED)** - `HYROS_KEY_OBB` env var is still present but unused by Orbit. No advisory needed.

`fetchHyrosCallsCount` remains in `_sources.ts` as dead code pending a follow-up cleanup PR. Andy should log this section as `DEPRECATED` (INFO-level) and move on. If a future change re-wires Hyros as a source, un-deprecate by reverting this block.

#### ORBIT-E - Orbit API ↔ Neon (display-layer verification)

Hit `GET /api/ads/overview?date_start=…&date_end=…` with `Authorization: Bearer ${AUDIT_TOKEN}`. Compare to direct Neon queries.

- **E1 (BLOCKER, exact)** - Per-client `spend / impressions / clicks` matches Neon rollup to the cent / unit (both read the same rows; any drift = aggregation bug in [api/ads/overview.ts:58-75](api/ads/overview.ts#L58)).
- **E2 (BLOCKER, exact)** - Per-client `paid_leads / paid_booked_calls` matches the COUNTED Section B + C ground truth exactly (counted UNION for leads, counted bookings for booked).
- **E3 (BLOCKER, ±0.5%)** - Per-client `cpl = spend / paid_leads` and `cpbc = spend / paid_booked_calls` recomputed within ±0.5%. Formula at [api/ads/overview.ts:220-221](api/ads/overview.ts#L220).
- **E4 (BLOCKER, exact)** - `totals.spend == SUM(clients.*.spend)`, same for impressions, clicks, paid_leads, paid_booked_calls. Cross-client strip math at [CrossClientStrip.tsx:43-76](src/components/ads-command-center/components/CrossClientStrip.tsx#L43) and aggregation at [overview.ts:224-245](api/ads/overview.ts#L224).
- **E5 (INFO)** - 1:1 CAD/USD blend in totals is a known caveat (Phase 4 = live FX). Logged, never failed.

#### ORBIT-F - Per-adset drill-down attribution

For each adset with non-zero activity in the window (spend > 0 OR leads > 0 OR booked > 0), call `GET /api/ads/drilldown/adsets?client_id=…&campaign_id=…&date_start=…&date_end=…`. Cap top 20 by spend; aggregate-check the remainder.

- **F1 (BLOCKER, ±5%)** - Meta `level=adset` spend / impressions / clicks ↔ Orbit's drilldown response.
- **F2 (BLOCKER)** - Sum of per-adset `paid_leads` == client total `paid_leads` from `/api/ads/overview`. No orphan ads (where `meta_ad_id` is populated but `meta_adset_id` is null).
- **F3 (BLOCKER)** - Same for per-adset `paid_booked_calls`.

#### ORBIT-G - Sync freshness and endpoint latency

Read `ads_sync_log` per `(client_id, source)`.

- **G1 (BLOCKER)** - Each enabled client has rows for its expected sources with latest `started_at` within last 24h AND latest row's `ok = true`. Expected: `meta_insights:*` + `meta_structure` (all 7); `ghl_conversions` (the 4 GHL clients); `meta_leadforms` (mustache-painting, peach-paint-co, queen-consultancy); `calendly` (queen-consultancy). The check is "latest row" not "any row in last 24h" - an aggregate `bool_and(ok)` over 48h is a different question (transient retry history) and does not count as G1 failure.
- **G2 (WARN)** - Latest `ads_paid_leads.last_paid_opt_in_at` per client within last 48h when window spend > 0 (detects silent conversion-sync regression). Applies to all enabled clients.
- **G3 (WARN)** - `ads_clients_config.token_expires_at` per client > 14 days out. For BuilderPro, current expiry is 2026-06-18 per memory - flag when within window.

**Latency sub-checks (added Tier 2 #8).** Time every Orbit endpoint call andy makes. Surface in a "Latency" sub-table in the report.

- **G4 (WARN, >5s)** - `/api/ads/overview` response time.
- **G5 (WARN, >10s)** - Each `/api/ads/drilldown/*` response time.
- **G6 (WARN, >30s)** - `/api/ads/audit` response time.
- **G7 (BLOCKER, >60s timeout)** - Any endpoint times out. A 60s+ latency means the function hit Vercel's hard ceiling and probably returned a partial / errored response.

Failure-mode hint: latency drift → check Vercel function configuration (`maxDuration` in `vercel.json`), Neon connection pool exhaustion, or a slow Meta/GHL upstream call inside the endpoint.

#### ORBIT-H - Code-static and drift checks (vault mode only)

Read-only grep + hash comparisons against the Orbit repo. Each is INFO unless it directly violates the north star.

- **H1 (BLOCKER)** - No `created_at` / `dateAdded` / `first_paid_opt_in_at` inside any query touching `ads_paid_leads`. Same as B2 but broader - covers any callsite, not just the audit's own.
- **H2 (WARN)** - No bare `YYYY-MM-DD` strings passed to Meta Graph or to drill-down SQL without `clientWindow(timezone, ...)`. Bare strings get parsed as UTC midnight and shift the window 4-5 hours.
- **H3 (WARN)** - `isLastTouchPaid()` defined exactly once in the repo (drift detector: a re-implementation in a second file is a regression class).
- **H4 (WARN)** - Code-anchor drift detection. Reads `~/.claude/skills/andy-the-auditor/checksums/code-anchors.json`, re-hashes each cited code range, and compares. Any drift means the invariants doc may reference code that has changed, so a human review is needed. If a hash drifts intentionally (you just fixed a bug), regenerate the baseline with `~/.claude/skills/andy-the-auditor/scripts/regen-baselines.sh` and commit.
- **H5 (WARN/BLOCKER)** - Schema drift detection. Reads `~/.claude/skills/andy-the-auditor/checksums/schema-baseline.json`, re-hashes each tracked ads_* table block in `drizzle/schema.ts`, and compares. **BLOCKER** if a column andy references (`last_paid_opt_in_at`, `meta_campaign_id`, `meta_adset_id`, `meta_ad_id`, `booked_at`, `client_id`, `enabled`) is removed or renamed. **WARN** if a tracked table block hashes differently but the referenced columns are still present (suggests an additive change worth reviewing).
- **H6 (WARN)** - Uncatalogued endpoint detection. Lists `api/ads/*.ts` files (recursive, excluding `_*.ts` helpers), compares to the `known_endpoints` list in `invariants/orbit.md`. Any uncatalogued endpoint = WARN with the file path. Forces a conscious decision to either include the new endpoint in andy's coverage or explicitly mark it skipped in invariants.

These run in vault mode only (require local Orbit repo + skill checksums dir). In `--slack` mode they're skipped - the morning Slack post is a smoke check, the deep code-level audit is local.

> When a new conversion-bearing endpoint ships, add it to the `known_endpoints` catalog in `invariants/orbit.md` so H6 stops WARNing. `api/ads/bookings/list.ts` was cataloged 2026-05-22 (audited by ORBIT-J).

#### ORBIT-I - Conversion-surface integrity (per-ad attribution, `meta_ad_id` health, drill-in reconciliation)

This section is the concrete enforcement of the working-MVP clause for the surfaces that render attribution downstream of the headline counts: the **Best ads** tab (I1, backed by [api/ads/best-ads.ts](api/ads/best-ads.ts)), the `meta_ad_id` writer health (I2), and the click-to-expand **Leads / Booked popovers + Contacts tab** (I3, backed by [api/ads/contacts/list.ts](api/ads/contacts/list.ts)). The common failure mode: a surface answers a *slightly different question* than the number it sits under, so it silently disagrees. Best Ads keyed on a `meta_ad_id` the writer never populated (every ad showed 0); the popover windowed the wrong column (count and dropdown disagreed). All three run in **both** vault and `--slack` modes (a handful of API calls + Neon counts; cheap, unlike the per-adset ORBIT-F loop).

- **ORBIT-I1 (BLOCKER)** - Per-ad surface reconciles. Call `GET {origin}/api/ads/best-ads?date_start=…&date_end=…&min_spend=0`. For each client that has **ad-attributable** conversions in window (Neon: `COUNT(DISTINCT contact_id)` over `ads_paid_leads`/`ads_paid_bookings` with non-null `meta_ad_id` in window), the Best Ads response must contain rows for that client with `paid_leads`/`paid_booked > 0`, and `SUM(per-ad paid_leads)` must reconcile to the ad-attributed subset (DISTINCT-contact UNION semantics, same as ORBIT-B). **FAIL** if the surface returns all-zero conversions while ORBIT-B/E show the client has leads in window - that is the regression class this section exists to catch.
- **ORBIT-I2 (BLOCKER)** - `meta_ad_id` population health. For each `(client, table)` in {`ads_paid_leads`, `ads_paid_bookings`}: if `COUNT(meta_campaign_id) > 0` but `COUNT(meta_ad_id) = 0`, **FAIL** - the writer dropped ad-level resolution wholesale. Likely owner: [api/ads/sync-conversions.ts](api/ads/sync-conversions.ts) `resolveMetaIds` / `adByName` (the unique-ad-name → ad-id backfill). If `meta_ad_id` coverage is non-zero but materially below `meta_campaign_id` coverage, that is a **WARN**, not a FAIL - it reflects URL-tag coverage (some conversions only carry adset/campaign-level signal), not a code regression. Use the population query in `invariants/orbit.md`.
- **ORBIT-I3 (BLOCKER)** - Drill-in list reconciles with the count above it, on the **COUNTED cohort**, computed **non-tautologically**. Every clickable count (Leads / Booked popovers, the Contacts tab) expands a list via [api/ads/contacts/list.ts](api/ads/contacts/list.ts). That list MUST be the same cohort as the number it expands. Compare two INDEPENDENT live surfaces: the list side is the LIVE endpoint response length (`GET /api/ads/contacts/list?...&booked=yes&limit=250` → `rows.length`; same for `booked=any`), the aggregate side is the LIVE `/api/ads/overview` KPI (`paid_booked_calls` / `paid_leads`). NEVER recompute both sides from one SQL - the pre-2026-06-10 form did, a tautological PASS that structurally could not catch the bug class. Neon counted SQL (in `invariants/orbit.md`) is the referee when the surfaces disagree. **FAIL** on any divergence (modulo documented `counts_as_separate` booking-vs-contact cases, which the referee SQL quantifies). Two canonical breaks: (2026-05-21) the list windowed every mode on `last_paid_opt_in_at` and treated "booked" as EXISTS(any booking, any date); (2026-06-09, #208) `countedPaidBookings` was wired into `_drilldown-sql`/`_sources`/`best-ads`/`bookings/list` but NOT `contacts/list.ts`, so popovers listed reschedule ghosts the KPI excluded (CG 8 vs 6, OBB 7 vs 5) - **this check, run this way, is what catches that**. Owner: `api/ads/contacts/list.ts` cohort SQL must mirror the counted semantics in [api/ads/_drilldown-sql.ts](api/ads/_drilldown-sql.ts). Cheap: two API calls + referee counts; runs in **both** modes.

> Coverage ceiling: conversions whose only signal is an adset- or campaign-name match can never tie to a single ad row, so Best Ads shows the **ad-attributable subset** by design - it is not expected to equal the client total. The durable lift path is the URL-tag rewriter at [api/ads/sync-conversions.ts:148](api/ads/sync-conversions.ts#L148) referencing `scripts/rewrite-meta-url-tags.ts`.

#### ORBIT-J - Booked Calls surface (ALL / PAID / OTHER) integrity + morning triage queue

Added 2026-05-22. Backs the **Booked Calls tab** on each client (`ClientHome.tsx` tab `booked-calls` → `BookedCallsView.tsx`), the `ads_all_bookings` table, and `GET /api/ads/bookings/list`. This surface stores **every** appointment from **every** calendar in the client's GHL location (not just `ghl_paid_calendar_ids`), then derives three buckets at read time: `ALL = ads_all_bookings` in window; `PAID = ALL ∩ ads_paid_bookings` (the confident, ad-attributed set ORBIT-C/E already defend); `OTHER = ALL − PAID` (organic / direct / TOF / onboarding / ambiguous). Per Zander's rule: push everything through, trust the existing paid set, dump everything else in OTHER, and let the assistant triage OTHER by hand. The all-bookings sync runs inside [api/ads/sync-conversions.ts](api/ads/sync-conversions.ts) `syncOneClientAllBookings` (source `ghl_conversions`), so ORBIT-G1 freshness already covers it - J adds correctness + triage, not freshness. J1–J3 run in **both** vault and `--slack` modes (a few Neon counts + one endpoint call). J4–J5 (the deep "look through these" queue) emit a full list in vault mode and counts-only in Slack mode.

- **ORBIT-J1 (BLOCKER) - PAID ⊆ ALL.** Every `(client_id, appointment_id)` in `ads_paid_bookings` with `booked_at` in window MUST also exist in `ads_all_bookings`. A paid booking missing from all-bookings would wrongly fall into OTHER (or vanish from the tab entirely). **FAIL** with sample `appointment_id`s. Root cause when it fails: `listCalendars()` didn't return the paid calendar (wrong `Version` header, archived/renamed calendar, or GHL calendars-API outage - note the silent `calendars.size === 0` warn added in `syncOneClientAllBookings`), so the all-bookings walk skipped a calendar the paid walk reaches via `ghl_paid_calendar_ids`.
- **ORBIT-J2 (BLOCKER) - Bucket math invariant.** Call `GET {origin}/api/ads/bookings/list?client_id=…&date_start=…&date_end=…&bucket=all`. Require `counts.all == counts.paid + counts.other`. Independently re-derive all/paid/other from Neon (query in `invariants/orbit.md`) and require the endpoint's `counts` to match Neon **exactly**. Catches a bucket-filter regression where the `pb.appointment_id IS NULL/NOT NULL` join drifts.
- **ORBIT-J3 (BLOCKER) - PAID reconciles with the paid-booked KPI on COUNTED semantics.** The KPI is COUNTED bookings in window, so the reconciling Neon form is the counted CTE joined into `ads_all_bookings` (`COUNT(*)` of counted bookings in window that exist in all-bookings; SQL in `invariants/orbit.md`) - NOT a distinct-contact count over the raw join (that pre-counted form double-counted cross-window reschedules and missed `counts_as_separate`). It MUST equal `/api/ads/overview` `clients.<id>.paid_booked_calls` (the same number ORBIT-C1/E2 verify). The endpoint's per-appointment `counts.paid` (raw `ads_paid_bookings` membership) MAY exceed it - non-counted rows (reschedules, stale-click rows) display in the bucket by design. FAIL only on the counted mismatch.
- **ORBIT-J4 (WARN) - OTHER-bucket paid-signal triage ("look through these").** This is the morning review queue Zander asked for. Surface OTHER-bucket bookings whose parent contact carries an ad signal on **first OR last** touch (`ads_ghl_contacts`: `last_utm_source ∈ {facebook,instagram,fb,ig,meta}` OR `last_fbclid` present OR `first_utm_source ∈ {…}`). These look paid but missed the confident set - either booked on a calendar outside `ghl_paid_calendar_ids`, or first-touch-paid / last-touch-organic. In **vault mode**, list up to 15 per client: `appointment_id`, `contact_id`, `calendar_name`, the signal (which UTM/fbclid), `booked_at`, and the GHL deep link (`https://app.gohighlevel.com/v2/location/{ghl_location_id}/contacts/detail/{contact_id}`) so the assistant can confirm/deny and re-bucket. In **`--slack` mode**, post only the candidate count. WARN, never FAIL: ambiguous calls living in OTHER is by design - this is a queue, not a correctness break. (If a candidate's calendar IS in `ghl_paid_calendar_ids` yet it's in OTHER, escalate that specific row to BLOCKER under J1 - it means the paid walk and the all walk disagree.)
- **ORBIT-J5 (INFO) - Unreviewed booked-call backlog.** Count in-window booked calls with `review_status IS NULL` (from `ads_ghl_contacts`), split ALL vs OTHER, so the report tells the assistant how big the triage queue is. Pure surfacing; never fails.

> Onboarding calls: by design they are pushed through into ALL/OTHER (no calendar taxonomy). Andy does NOT fail on their presence - `calendar_name` is surfaced on every row so the assistant can `ignore` them via the review workflow. If Zander later adds an excluded-calendar list, add a J6 to assert excluded calendars never appear in any bucket.

### Step 2.5 - Optional: `--gap-scan` mode

If invoked with `--gap-scan` (typically: `claude -p "/andy-the-auditor --gap-scan"` from a weekly launchd job), andy switches from the rolling 3-day deep audit to a **90-day rolling historical-gap detection** pass.

What it does:

1. Queries `ads_meta_insights` directly for the last 90 days per client (requires `DATABASE_URL` in env; halts with a bootstrap message otherwise).
2. For each (client, calendar date), checks whether spend exists in Neon.
3. For dates with zero spend in Neon, hits Meta Graph API directly for that single day. If Meta reports non-zero spend but Neon has nothing, that's a sync gap.
4. Writes a single combined vault report at `~/Obsidian/Vault/20-Clients/_Moreway-Agency/attribution-audits/gap-scan-YYYY-MM-DD.md` listing every detected gap with date, client, missing spend amount, and a backfill command.

Skipped automatically when `DATABASE_URL` isn't reachable. The remote routine doesn't run gap-scan (only `--slack` mode). Scheduled locally as a separate launchd job: `com.zander.andy-gap-scan` firing Sunday 7am NY.

### Step 3 - Aggregate and emit

For each client, total PASS / WARN / FAIL across all sections.

#### 3a - Vault mode (default)

Render the report using `~/.claude/skills/andy-the-auditor/templates/report-template.md`.

**Day-over-day delta**: read yesterday's report if it exists; surface any check that flipped from PASS → FAIL or PASS → WARN today at the very top under a "Newly failing since yesterday" section.

Write to:
```
~/Obsidian/Vault/20-Clients/CareGenius/attribution-audits/YYYY-MM-DD.md      # CG B2B
~/Obsidian/Vault/20-Clients/BuilderPro/attribution-audits/YYYY-MM-DD.md      # BP
~/Obsidian/Vault/20-Clients/_Moreway-Agency/attribution-audits/YYYY-MM-DD.md # OBB + contractor-launch + mustache-painting + peach-paint-co + queen-consultancy + cross-client totals
```

If the per-client folder doesn't exist, create it.

#### 3b - Slack mode (--slack ENV_VAR)

POST a single Slack message to the webhook URL stored in `process.env[ENV_VAR]`. Format:

**Main message** (one line per client + a top header):

```
*Orbit Attribution Audit, {{date}} ({{window_label}})*
{{client_emoji}} {{client_label}}: {{status_word}} ({{counts}})       # one line per enabled client (7 today)
...
Skill version: `{{skill_sha_or_version}}`  ·  Window: {{date_start}} to {{date_end}}
```

Where `{{status_word}}` ∈ "all clear", "WARN", "FAIL"; `{{client_emoji}}` ∈ ✅ ⚠️ ❌; `{{counts}}` is e.g. "ORBIT-A through G + F, 0 blockers, 1 warning, 12 adsets checked".

**Threaded reply** (only when ANY client status != PASS) - for each failed/warning check across all clients, including per-adset drift findings from ORBIT-F:

```
{{client}} :: {{check_id}} ({{severity}}) :: {{one_line_explanation}}
  truth: {{truth_value}}  app: {{app_value}}  delta: {{delta}}
  likely owner: {{file_path}}:{{line}}
```

For ORBIT-F per-adset findings, include the adset_id and name in the explanation. Cap at top 10 failing adsets per client; aggregate-summarize the rest with a line like "12 more adsets within tolerance, 3 more failed (see vault report for full list)."

Skip vault writes entirely in Slack mode. ORBIT-F runs in Slack mode but ORBIT-H does not (no local repo). Include the skill commit SHA (from `git -C $(find / -name SKILL.md -path '*andy-the-auditor*' 2>/dev/null | head -1 | xargs dirname) rev-parse --short HEAD` if available, else "unversioned") so Zander can see which version of the skill produced the message.

If the Slack POST fails (non-2xx response), retry once with exponential backoff, then halt with the response body printed to stdout (the routine logs that).

### Step 4 - Surface in terminal (vault mode only)

After writing files in vault mode:

1. If any BLOCKER failed, print a top banner with the failed check IDs and a one-line summary each, plus file:line hints from the failure-mode map.
2. Print the vault note path(s) so Zander can click and read.
3. Print PASS / WARN / FAIL totals per client.
4. Do NOT print the full report inline - the vault notes are the artifact.

Example banner:

```
✗ CG B2B: ORBIT-B1 paid lead set off by 3 contacts - vault://20-Clients/CareGenius/attribution-audits/2026-05-19.md
✓ BuilderPro: all 22 checks green
⚠ OBB: ORBIT-G2 sync stale (last GHL run 27h ago) - vault://20-Clients/_Moreway-Agency/attribution-audits/2026-05-19.md
```

In `--slack` mode, terminal output is minimal: one line confirming the POST succeeded and the message ts (Slack timestamp) for thread anchoring. The routine's logs capture this for debugging.

---

## Failure-mode → file mapping

When a check fails, Andy includes a likely-owner hint in the report. The mapping:

| Symptom | Likely file |
|---|---|
| ORBIT-A spend mismatch | [api/ads/sync-meta-insights.ts](api/ads/sync-meta-insights.ts) - date alignment, level filtering |
| ORBIT-A clicks drift | [api/ads/audit.ts:88-95](api/ads/audit.ts#L88) - `inline_link_clicks` vs `clicks` |
| ORBIT-B count off | [api/ads/sync-conversions.ts](api/ads/sync-conversions.ts) - paid-attribution logic in walker, 14-day stale cutoff |
| ORBIT-B golden rule violation | grep target file:line; the violator query lives at the cited line |
| ORBIT-C booked count off | [api/ads/sync-conversions.ts](api/ads/sync-conversions.ts) - calendar filter, booking_source filter |
| ORBIT-D (DEPRECATED post-Part-11) | n/a - Hyros no longer in dashboard data path |
| ORBIT-E aggregation off | [api/ads/overview.ts:224-245](api/ads/overview.ts#L224) - cross-client SUM logic |
| ORBIT-E CPL/CPBC off | [api/ads/overview.ts:220-221](api/ads/overview.ts#L220) - null-safe formulas |
| ORBIT-F orphan ads | structure walker in [api/ads/sync-meta-structure.ts](api/ads/sync-meta-structure.ts) - missing `parent_id`/`campaign_id` on ad rows |
| ORBIT-G stale | [api/ads/cron-orchestrator.ts](api/ads/cron-orchestrator.ts) + cron schedule in `vercel.json` |
| ORBIT-H1 code-static fail | the grep hit's file:line |
| ORBIT-I `meta_ad_id` all-zero / Best Ads shows 0 | [api/ads/sync-conversions.ts](api/ads/sync-conversions.ts) `resolveMetaIds` / `adByName` - ad-name → ad-id backfill dropped |
| ORBIT-I3 popover/list count ≠ the KPI it expands | [api/ads/contacts/list.ts](api/ads/contacts/list.ts) cohort SQL diverged from the counted semantics (`countedPaidBookings` in [api/ads/_drilldown-sql.ts](api/ads/_drilldown-sql.ts)): bookings must be COUNTED bookings windowed on `booked_at` (primary anchor + counts_as_separate + 28d click gate + exclusions), not raw rows (the #208 partial-migration bug) and not EXISTS-any-booking |
| ORBIT-B5 opt-in == synced_at on wrong calendar day | [api/ads/_optin-timestamp.ts](api/ads/_optin-timestamp.ts) `resolveReOptInDate` / its caller in [api/ads/sync-conversions.ts](api/ads/sync-conversions.ts) re-opt-in branch - dated by the sync clock instead of the fbc click time / dateUpdated event ladder |
| ORBIT-B6 rung-2 stamp without fresh corroboration | [api/ads/_optin-timestamp.ts](api/ads/_optin-timestamp.ts) `resolveReOptInDate` rung 2 accepts any `dateUpdated > priorAt`; triggering writer is usually a GHL workflow / bulk edit bumping `dateUpdated` (F23 phantom re-opt-in class) |
| ORBIT-J1 a paid booking is missing from `ads_all_bookings` | [api/ads/sync-conversions.ts](api/ads/sync-conversions.ts) `listCalendars()` / `syncOneClientAllBookings` - the all-calendars walk didn't return the paid calendar (wrong `Version` header, archived calendar, or calendars-API outage → `calendars.size === 0`). Paid walk reaches it via `ghl_paid_calendar_ids`; all walk must reach it via `GET /calendars/?locationId=` |
| ORBIT-J2 bucket counts don't sum / don't match Neon | [api/ads/bookings/list.ts](api/ads/bookings/list.ts) - the `pb.appointment_id IS NULL / IS NOT NULL` bucket join or the `COUNT(*) FILTER` counts query drifted |
| ORBIT-J3 PAID distinct-contact ≠ paid_booked KPI | [api/ads/bookings/list.ts](api/ads/bookings/list.ts) join to `ads_paid_bookings`, or upstream `ads_paid_bookings` diverged from ORBIT-C (fix C first) |

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
summary_one_line: "CG ✓ - all 9 checks passed within tolerance"
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

Andy already has a daily scheduled run. The remote routine `trig_01K8mpqa8e9F2DmBRHivNNPV` ("Attribution Audit 7am ET", fires `0 11 * * *` UTC) clones this skill's git repo at every firing, reads `SKILL.md`, and follows the `--slack` execution flow to post to `#ads-audits`. **Do NOT create a separate `/schedule` entry** - the routine is already wired.

**Single source of truth via git.** The skill lives at TWO places that stay in sync:

- **Local**: `~/.claude/skills/andy-the-auditor/` - what you edit and what Andy reads in vault mode.
- **Remote**: `https://github.com/k0mrads/andy-the-auditor` (private repo) - what the morning routine clones.

Workflow for any change (rule, tolerance, new section, fix):

```
cd ~/.claude/skills/andy-the-auditor/
# edit SKILL.md or invariants/orbit.md or templates/report-template.md
git add -A
git commit -m "describe the change"
git push
```

The next morning's routine firing picks up the change automatically. No cco. No cloud sync. Just git.

For VAULT reports specifically (the deep audit, including ORBIT-F and ORBIT-H): run `/andy-the-auditor` manually whenever you want them, or wire a separate local-scheduler entry that doesn't conflict with the remote routine.

If the morning Slack message looks stale: confirm `git log -1 --format=%h` matches the SHA the routine prints in its threaded reply. If they differ, you forgot to `git push`.

---

## Known limitations & future work

- **Hyros retired (Part 11, 2026-05-20)** - OBB now flows through GHL like CG/BP. Hyros code (`fetchHyrosCallsCount`) and env (`HYROS_KEY_OBB`) remain in the repo as dead code pending a follow-up cleanup PR. ORBIT-D is deprecated; no Hyros checks today.
- **OBB attribution rate** - at the time Part 11 shipped, ~62% of OBB leads/bookings carry a Meta `meta_campaign_id`. Lower than CG (~72%) and far below BP (~99%) because OBB Meta ads were explicitly skipped from the Part 3 Track 2 URL-tag rewrite when OBB was Hyros-only. Recommended follow-up: `scripts/rewrite-meta-url-tags.ts --client obb --apply` to lift the rate above ~95%.
- **Ad-level attribution ceiling (ORBIT-I)** - `meta_ad_id` is only resolvable when a conversion's ad name (`ad_name` or `utm_content`) uniquely matches one ad in `ads_meta_structure`, or GHL delivers `adId` directly. Conversions whose only signal is an adset/campaign-name match can't tie to a single ad, so Best Ads shows the **ad-attributable subset** by design (not the client total). After the 2026-05-21 writer fix + backfill, coverage was ~100% of attributed for BuilderPro, ~64% for CG, ~83% for OBB leads. The durable lift path is the URL-tag rewriter `scripts/rewrite-meta-url-tags.ts`. ORBIT-I2 WARNs on low-but-nonzero coverage, FAILs only on wholesale zero.
- **GHL walker timezone** - [_ghl-direct.ts:165-166](api/ads/_ghl-direct.ts#L165) builds the window as UTC (`T00:00:00Z` / `T23:59:59.999Z`), while Neon's union semantics use client-tz-aware boundaries via [_drilldown-sql.ts `clientWindow()`](api/ads/_drilldown-sql.ts#L54). A contact whose lastTouch is e.g. 23:00 EST can fall in different windows depending on path. Treat as a known low-magnitude drift class until the walker also uses `clientWindow()`.
- **Pre-commit / post-edit hooks** - out of scope; Andy is the post-hoc audit.

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
