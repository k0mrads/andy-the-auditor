---
client: Moreway Orbit
client_dir: ~/Claude Code/Moreway/Moreway | Tasks
vault_subfolder: _Moreway-Agency
sub_clients: [caregenius-b2b, builderpro, obb]
repo: k0mrads/moreway-orbit
---

# Moreway Orbit, Ads Command Center, Audit Invariants

This file is the single source of truth for HOW the `andy-the-auditor` skill runs against the **Moreway Orbit** Ads Command Center (the `/ads` route inside `~/Claude Code/Moreway/Moreway | Tasks/`, GitHub `k0mrads/moreway-orbit`). It replaces the three older invariants files (`caregenius.md`, `builderpro.md`, `moreway-command-center.md`) from the deprecated `/attribution-audit` skill.

Three executors share this file:

1. The local skill (vault mode, deep audit).
2. The same skill invoked with `--slack` (post smoke summary to Slack).
3. The remote routine `trig_01K8mpqa8e9F2DmBRHivNNPV` which invokes the skill on schedule.

If the rule changes, update HERE first, then code. Every Andy check ID below (ORBIT-A1 ... ORBIT-H3) MUST agree with `~/.claude/skills/andy-the-auditor/SKILL.md`. If they drift, SKILL.md and this file together fail the audit before any check runs.

---

## Scope

Andy is a **developer-style auditor of the Moreway Orbit app**, not a marketing analyst. Every check below verifies that the app is working and that attribution math is honest. Andy never comments on marketing performance (spend trends, creative effectiveness, campaign-strategy choices, ROAS, sample-size noise). A separate bot owns that. The test: if a finding would fit in a marketing Slack channel, it does NOT belong in an Andy report; if it would fit in a pull-request review of the Orbit codebase, it does. See `~/.claude/skills/andy-the-auditor/SKILL.md` "Scope" section for the full anti-example list.

---

## Account & credentials

| Field | Value |
|---|---|
| **Project root** | `~/Claude Code/Moreway/Moreway \| Tasks/` |
| **Env file** | `.env` at project root (mirrored in Vercel Production + Preview) |
| **Database** | Neon Postgres via `DATABASE_URL` |
| **Auth token (audit)** | `AUDIT_TOKEN` in `.env`, mirrored to Vercel. Consumed by [api/_db.ts:52-86 `requireSession()`](api/_db.ts#L52) as a service-auth bypass. |
| **Frontend route** | `/ads` (entry `src/pages/AdsCommandCenter.tsx` → `src/components/ads-command-center/AdsCommandCenterRoot.tsx`) |
| **Overview page** | `src/components/ads-command-center/routes/Overview.tsx` |
| **Cross-client strip** | [src/components/ads-command-center/components/CrossClientStrip.tsx:43-76](src/components/ads-command-center/components/CrossClientStrip.tsx#L43) |
| **Backend KPI endpoint** | `GET /api/ads/overview?date_start=YYYY-MM-DD&date_end=YYYY-MM-DD` |
| **Backend in-app audit endpoint** | `GET /api/ads/audit?date_start=...&date_end=...` (Andy verifies its drift report independently, never trusts it as oracle) |
| **Drill-down endpoints** | `GET /api/ads/drilldown/campaigns`, `/adsets`, `/ad` |
| **Cron orchestrator** | `GET\|POST /api/ads/cron-orchestrator` (scheduled at 11:00 + 16:00 UTC via `vercel.json`) |
| **Deployed origin** | Auto-resolve at run time via `vercel ls --prod \| head -3`. Never hard-code (preview branches rotate). |

---

## Per sub-client config

The audit reads `ads_clients_config` from Neon **at run time**. Do not hard-code these values inside Andy's prompts or scripts. Three rows expected (all `enabled = true` today):

| client_id | label | meta_account_id | currency | timezone | conversion source | enabled |
|---|---|---|---|---|---|---|
| `caregenius-b2b` | CareGenius B2B | `act_27449078924707675` | CAD | `America/New_York` | Neon (`ads_paid_leads`, `ads_paid_bookings`, fed by GHL walker) | true |
| `builderpro` | BuilderPro | `act_1586857008888840` | USD | `America/Los_Angeles` | Neon (same shape as CG, fed by GHL walker) | true |
| `obb` | OBB Home Care | `act_425612416873215` | USD | `America/New_York` | Hyros (read live by [api/ads/_sources.ts:62-105 `fetchConversionCounts()`](api/ads/_sources.ts#L62), no Neon mirror yet) | true |

Other columns the audit reads: `meta_secret_name`, `ghl_api_secret_name`, `hyros_secret_name`, `ghl_paid_calendar_ids`, `token_expires_at`. If `enabled = false` for a client, skip its entire section.

Conversion source dispatch lives at [api/ads/_sources.ts:62-105](api/ads/_sources.ts#L62) (`fetchConversionCounts`): CG and BP route to the Neon-backed GHL UNION path, OBB routes to `fetchHyrosCallsCount`.

---

## Window

Orbit's "Last 3 days" preset, from [DateRangePresetPicker.tsx:60-78](src/components/ads-command-center/components/DateRangePresetPicker.tsx#L60):

```
end   = yesterday in America/New_York (today EXCLUDED)
start = end minus 2 NY days
days  = 3
```

- Today is 2026-05-19, window = `2026-05-16` → `2026-05-18` (yesterday + 2 prior).
- Tomorrow, window auto-shifts to `2026-05-17` → `2026-05-19`.
- Today is excluded because partial-day data skews CPL and CPBC.

**Per-client timezone**: read from `ads_clients_config.timezone` and passed into [api/ads/_drilldown-sql.ts:54-60 `clientWindow()`](api/ads/_drilldown-sql.ts#L54) when computing exact timestamp boundaries. Bare `YYYY-MM-DD` strings without `clientWindow()` get parsed as UTC midnight and shift 4 to 5 hours.

> **Known inconsistency**: [api/ads/audit.ts:316-325 `defaultLast3Days()`](api/ads/audit.ts#L316) uses "today + 2 prior" (INCLUDES today), which disagrees with the picker. Andy matches the **picker**, not the audit endpoint's default. When the endpoint is fixed, no change to Andy.

---

## Paid attribution rule (north star)

> **A lead is a paid lead in a given window iff its paid opt-in event timestamp falls inside the window. The age of the contact is irrelevant. Re-opt-ins of older contacts COUNT.**

The rule has exactly **two** code homes. They MUST agree, byte-for-byte, on the predicate.

### Home 1, canonical predicate, [api/ads/_ghl-direct.ts:69-75 `isLastTouchPaid()`](api/ads/_ghl-direct.ts#L69):

```ts
function isLastTouchPaid(lastTouch: LastTouchAttribution): boolean {
  const hasFbclid = !!(lastTouch.utmFbclid || lastTouch.fbclid || lastTouch.fbc);
  const src = (lastTouch.utm_source || '').toLowerCase();
  const isMetaSource = ['facebook', 'instagram', 'fb', 'ig', 'meta'].includes(src);
  return hasFbclid || isMetaSource;
}
```

No tag backup (no `BAC` / `OPT IN` fallback like the deprecated sister apps had). UTM/fbclid is the only signal.

### Home 2, UNION semantics, [api/ads/_drilldown-sql.ts:98-156 `paidConversionsByObject()`](api/ads/_drilldown-sql.ts#L98):

```sql
-- paid_leads = COUNT(DISTINCT contact_id) over the UNION of:
--   (1) rows in ads_paid_leads where last_paid_opt_in_at in [window_start, window_end]
--   (2) rows in ads_paid_bookings where booked_at in [window_start, window_end]
-- Bookers whose original opt-in landed BEFORE the window still count as a lead in this window
-- because the booking lands in window. This is intentional and matches the north star.
```

**Andy enforces:** any third site that computes paid_leads (a new endpoint, a new view, a Slack-bot query) is a regression. ORBIT-H3 detects re-implementations.

### Booked-call paid predicate

A booking is paid iff:

1. Its parent contact passes `isLastTouchPaid()` above.
2. `calendar_id ∈ ads_clients_config.ghl_paid_calendar_ids[client_id]`.
3. `booking_source ∈ ('booking_widget', NULL)`.

---

## Tolerances

| Metric | Tolerance | Notes |
|---|---|---|
| Spend (total, per-adset) | ±5% | ±10% for the most-recent day in window (Meta still aggregating) |
| Impressions | ±5% | |
| Clicks | ±5% | Use `inline_link_clicks` from Meta. Neon column is named `clicks` but holds `inline_link_clicks`. See [api/ads/audit.ts:88-95](api/ads/audit.ts#L88). |
| CPC | ±5% | Derived from spend / inline_link_clicks |
| CPM | ±5% | Derived from spend / impressions * 1000 |
| CTR | ±0.1pp absolute | Not ±5% relative; small clicks magnify percentage |
| Paid lead count | exact (0) | Hard equality. UNION semantics applied on both sides before compare. |
| Paid booked count | exact (0) | Hard equality vs `ads_paid_bookings` rows with `booked_at` in window |
| CPL (per client) | ±0.5% | Derived: spend / paid_leads |
| CPBC (per client) | ±5% | Derived: spend / paid_booked_calls. Formula at [api/ads/overview.ts:208-209](api/ads/overview.ts#L208). |
| Cross-client totals (sums) | exact (0) | Strip is a deterministic sum of per-client values |

**Most-recent-day rule**: when the window includes a day where Meta is still backfilling (typically the last day in window), Andy loosens spend/impressions/clicks tolerance to ±10% for **that day only**. Other days stay ±5%.

---

## Required Neon queries

Connect via `DATABASE_URL` from `~/Claude Code/Moreway/Moreway | Tasks/.env`. **READ-ONLY**. Never `UPDATE`, `INSERT`, `DELETE`, or `TRUNCATE`. Andy is post-hoc, not transactional.

### Spend layer rollup (per client)

```sql
SELECT
  SUM(spend)::numeric  AS spend,
  SUM(impressions)::int AS impressions,
  SUM(clicks)::int      AS clicks
FROM ads_meta_insights
WHERE client_id = $client_id
  AND level = 'campaign'
  AND date_start >= $window_start_date
  AND date_start <= $window_end_date;
```

Schema reference: [drizzle/schema.ts:223-242 `adsClientsConfig`](drizzle/schema.ts#L223). `level='campaign'` is preferred over `level='account'` because campaign-level is always synced; account-level rows are optional. Both should reconcile within ±5% of Meta Graph API.

### Lead layer (per client, CG + BP only)

```sql
SELECT contact_id, last_paid_opt_in_at, meta_campaign_id, meta_adset_id, meta_ad_id
FROM ads_paid_leads
WHERE client_id = $client_id
  AND last_paid_opt_in_at >= $window_start_iso
  AND last_paid_opt_in_at <= $window_end_iso;
```

Schema: [drizzle/schema.ts:339-381 `adsPaidLeads`](drizzle/schema.ts#L339).

> **Important**: the client-facing paid lead count is **NOT** the plain row count from this query. It is the **UNION** at [api/ads/_sources.ts:77-100](api/ads/_sources.ts#L77) (`fetchGhlCountsFromNeon`), which also pulls in bookers whose `booked_at` is in window even if their `last_paid_opt_in_at` is outside the window. The audit MUST compute the UNION on its side before comparing to `/api/ads/overview`. Plain `ads_paid_leads` row count is for ORBIT-B1 diagnostics only, not for B1 pass/fail.

### Booking layer (per client, CG + BP only)

```sql
SELECT appointment_id, contact_id, booked_at, calendar_id, meta_campaign_id, meta_adset_id, meta_ad_id
FROM ads_paid_bookings
WHERE client_id = $client_id
  AND booked_at >= $window_start_iso
  AND booked_at <= $window_end_iso;
```

Schema: [drizzle/schema.ts:386-419 `adsPaidBookings`](drizzle/schema.ts#L386).

### Sync freshness (per client_id + source)

```sql
SELECT
  source,
  MAX(started_at)  AS last_started,
  MAX(finished_at) AS last_finished,
  bool_and(ok)     AS last_ok
FROM ads_sync_log
WHERE client_id = $client_id
GROUP BY source;
```

Schema: [drizzle/schema.ts:309-325 `adsSyncLog`](drizzle/schema.ts#L309). Sources expected: `meta_insights`, `meta_structure`, `ghl` (CG/BP), `hyros` (OBB), `orchestrator`.

### Most-recent paid event (sanity)

```sql
SELECT MAX(last_paid_opt_in_at) AS latest_lead    FROM ads_paid_leads     WHERE client_id = $client_id;
SELECT MAX(booked_at)            AS latest_booking FROM ads_paid_bookings  WHERE client_id = $client_id;
```

---

## Required endpoint replays

All endpoint calls use `Authorization: Bearer ${AUDIT_TOKEN}`. Auth bypass was added in [api/_db.ts:52-86 `requireSession()`](api/_db.ts#L52) (service-auth path: if `Authorization` header matches `AUDIT_TOKEN`, return a synthetic admin session). If the deployed code lacks this bypass, every replay returns `401` and Andy halts ORBIT-E with a bootstrap note.

```
GET {origin}/api/ads/overview?date_start=YYYY-MM-DD&date_end=YYYY-MM-DD
GET {origin}/api/ads/audit?date_start=YYYY-MM-DD&date_end=YYYY-MM-DD
GET {origin}/api/ads/drilldown/campaigns?client_id=...&date_start=...&date_end=...
GET {origin}/api/ads/drilldown/adsets?client_id=...&campaign_id=...&date_start=...&date_end=...
GET {origin}/api/ads/drilldown/ad?client_id=...&adset_id=...&date_start=...&date_end=...
```

Compare each response field by field to Andy's independent Neon + Meta + GHL/Hyros computation. Any divergence is a finding.

---

## Per-section invariant IDs

These IDs are the contract with SKILL.md. Do not rename. Do not renumber. Add new IDs by appending.

| ID | Severity | Section | One-line description |
|---|---|---|---|
| ORBIT-A1 | BLOCKER | Meta ↔ Neon | Spend, ±5% (±10% most-recent day) |
| ORBIT-A2 | BLOCKER | Meta ↔ Neon | Impressions, ±5% |
| ORBIT-A3 | BLOCKER | Meta ↔ Neon | Clicks (inline_link_clicks), ±5% |
| ORBIT-A4 | WARN    | Meta ↔ Neon | Derived CPC/CPM/CTR, ±5% (CTR ±0.1pp) |
| ORBIT-B1 | BLOCKER | GHL ↔ Neon, CG+BP | Paid lead UNION count equality |
| ORBIT-B2 | BLOCKER | Golden rule grep | No `created_at`/`dateAdded`/`first_paid_opt_in_at` in window filters |
| ORBIT-B3 | BLOCKER | GHL ↔ Neon, CG+BP | Re-opt-in survives: contact with `dateAdded` < window_start but `last_paid_opt_in_at` in window appears in Neon |
| ORBIT-C1 | BLOCKER | GHL ↔ Neon, CG+BP | Paid booked count equality vs walked GHL events |
| ORBIT-C2 | BLOCKER | Display, CG+BP | CPBC = spend / paid_booked within ±5% of `/api/ads/overview` |
| ORBIT-D1 | SKIP    | Hyros, OBB | Hyros leads not server-filterable; promote to BLOCKER post Phase 3 |
| ORBIT-D2 | BLOCKER | Hyros, OBB | Hyros paid booked count == `clients.obb.paid_booked_calls` from `/api/ads/overview` |
| ORBIT-D3 | WARN    | Hyros, OBB | `HYROS_KEY_OBB` not nearing expiry (stub, no Hyros introspection endpoint) |
| ORBIT-E1 | BLOCKER | API ↔ Neon | Per-client spend/impressions/clicks exact match to Neon rollup |
| ORBIT-E2 | BLOCKER | API ↔ Neon | Per-client paid_leads / paid_booked_calls exact match to B/C/D2 ground truth |
| ORBIT-E3 | BLOCKER | API ↔ Neon | CPL/CPBC recomputed within ±0.5% / ±5% |
| ORBIT-E4 | BLOCKER | Cross-client | `totals.*` == SUM(`clients.*.*`), exact, all fields |
| ORBIT-E5 | INFO    | Cross-client | 1:1 CAD/USD blend (Phase 4 = live FX) |
| ORBIT-F1 | BLOCKER | Drill-down | Meta `level=adset` ↔ Orbit drilldown spend/impr/clicks, ±5% |
| ORBIT-F2 | BLOCKER | Drill-down | SUM(per-adset paid_leads) == client total, no orphan ads |
| ORBIT-F3 | BLOCKER | Drill-down | SUM(per-adset paid_booked_calls) == client total |
| ORBIT-G1 | BLOCKER | Sync freshness | Each (client, source) has row in `ads_sync_log` within 24h with `ok = true` |
| ORBIT-G2 | WARN    | Sync freshness | Latest `last_paid_opt_in_at` per CG/BP client within 48h when window spend > 0 |
| ORBIT-G3 | WARN    | Sync freshness | `ads_clients_config.token_expires_at` > 14 days out per client |
| ORBIT-H1 | BLOCKER | Code-static | Broader sweep of B2: no banned column references anywhere `ads_paid_leads` is queried |
| ORBIT-H2 | WARN    | Code-static | No bare `YYYY-MM-DD` strings into Meta Graph or drill-down SQL without `clientWindow(timezone, ...)` |
| ORBIT-H3 | WARN    | Code-static | `isLastTouchPaid()` defined exactly once in the repo (drift detector) |

Sections marked **CG+BP only** are skipped for OBB. ORBIT-D is OBB-only.

---

## Known failure-mode → file mapping

This table is identical to SKILL.md's. When a check fails, Andy includes the likely-owner hint in the report.

| Symptom | Likely file |
|---|---|
| ORBIT-A spend mismatch | [api/ads/sync-meta-insights.ts](api/ads/sync-meta-insights.ts), date alignment / level filtering |
| ORBIT-A clicks drift | [api/ads/audit.ts:88-95](api/ads/audit.ts#L88), `inline_link_clicks` vs `clicks` |
| ORBIT-B count off | [api/ads/sync-conversions.ts](api/ads/sync-conversions.ts), paid-attribution logic in walker, 14-day stale cutoff |
| ORBIT-B golden rule violation | grep target file:line, the violator query lives at the cited line |
| ORBIT-C booked count off | [api/ads/sync-conversions.ts](api/ads/sync-conversions.ts), calendar filter, booking_source filter |
| ORBIT-D Hyros count off | [api/ads/_sources.ts:123-150](api/ads/_sources.ts#L123), Hyros pagination, organic filter |
| ORBIT-E aggregation off | [api/ads/overview.ts:212-233](api/ads/overview.ts#L212), cross-client SUM logic |
| ORBIT-E CPL/CPBC off | [api/ads/overview.ts:208-209](api/ads/overview.ts#L208), null-safe formulas |
| ORBIT-F orphan ads | [api/ads/sync-meta-structure.ts](api/ads/sync-meta-structure.ts), missing `parent_id` / `campaign_id` on ad rows |
| ORBIT-G stale | [api/ads/cron-orchestrator.ts](api/ads/cron-orchestrator.ts) + cron schedule in `vercel.json` |
| ORBIT-H1 code-static fail | the grep hit's file:line |

---

## Local mode vs --slack mode scope

Andy runs in two modes, both invoking the same skill body. Section scope differs:

| Section | Local (vault) | `--slack` (Slack post) |
|---|---|---|
| ORBIT-A (Meta ↔ Neon) | RUN | RUN |
| ORBIT-B (GHL ↔ Neon, CG+BP) | RUN | RUN |
| ORBIT-C (Booked, CG+BP) | RUN | RUN |
| ORBIT-D (Hyros, OBB) | RUN | RUN |
| ORBIT-E (API ↔ Neon) | RUN | RUN |
| ORBIT-F (Per-adset drilldown) | RUN | **SKIP** (top-20 loop is too slow for Slack TTL) |
| ORBIT-G (Sync freshness) | RUN | RUN |
| ORBIT-H (Code-static grep) | RUN | **SKIP** (no repo checkout in cloud routine) |

**Vault is the deep audit. Slack is a smoke check.** Slack post format: one line per client with PASS / WARN / FAIL totals + the top failing check ID, plus a vault link for the full report. Slack mode never substitutes for the vault report; both run on the daily 7am schedule.

---

## Drift between executors

The local skill, the `--slack` mode, and the remote routine `trig_01K8mpqa8e9F2DmBRHivNNPV` all invoke **the same skill body** at `~/.claude/skills/andy-the-auditor/SKILL.md`, propagated to the cloud via `/cco` user-scope sync. There is no Python-script duplication and no separate cloud-side prompt template.

If a cloud run and a local run disagree on the same window:

1. First, confirm both ran against the same window (cron timezone vs local terminal timezone can differ by hours near midnight).
2. Second, force `/cco` re-sync. The most common cause of executor drift is a stale cloud-side copy of the skill after a local edit.
3. Third, if disagreement persists after re-sync with identical windows, that is itself a finding: open a vault note in `_Moreway-Agency/attribution-audits/` titled `executor-drift-YYYY-MM-DD.md` with both reports inline.

Never patch around drift by editing the cloud copy separately. The local skill body is the source; cloud is a mirror.
