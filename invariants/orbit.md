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

**Working-MVP clause (standing principle).** Every display surface that renders a conversion metric (`paid_leads`, `paid_booked`, `CPL`, `CPBC`) is in Andy's scope **by default**, whether or not it has its own check ID below. The north star applies to all of them. If a conversion column renders all-zero / dashes on a surface where the same client shows spend AND shows conversions elsewhere (Overview, Campaigns, Adsets), that is a correctness FAIL — a working MVP shows one truth everywhere. New conversion-bearing tabs/endpoints are presumed in-scope until explicitly justified as out-of-scope here. "Informational ranking" is not a valid skip reason for a surface that displays attribution (this is what masked the 2026-05-21 Best Ads `meta_ad_id` regression — see ORBIT-I).

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
| `obb` | OBB Home Care | `act_425612416873215` | USD | `America/New_York` | **Neon (GHL walker, identical to CG/BP) as of Part 11 / 2026-05-20.** Hyros retired. | true |

Other columns the audit reads: `meta_secret_name`, `ghl_api_secret_name`, `hyros_secret_name`, `ghl_paid_calendar_ids`, `token_expires_at`. If `enabled = false` for a client, skip its entire section.

OBB's `ghl_location_id` is `Mns7ICmnKi3Pr4QuKmgp`, paid calendars are `ClJ06JUJICgDCoELfn9A` (Home Care Hero Application: Interview Scheduling) and `1FlpwUCCzC52Zt9y6cr2` (Home Care Hero Application: Franchise Interview). API key in `GHL_KEY_OBB`. `hyros_secret_name` is still 'HYROS_KEY_OBB' in the row but the env var is unused by the dashboard post-Part-11.

Conversion source dispatch lives at [api/ads/_sources.ts:155-179](api/ads/_sources.ts#L155) (`fetchConversionCounts`): **all three clients** route to the Neon-backed GHL UNION path (`fetchGhlCountsFromNeon`). `fetchHyrosCallsCount` remains in the file as dead code pending a follow-up cleanup PR.

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

### `meta_ad_id` population health (ORBIT-I2, per client + table)

```sql
SELECT client_id,
       COUNT(*)                AS total,
       COUNT(meta_campaign_id) AS has_campaign,
       COUNT(meta_adset_id)    AS has_adset,
       COUNT(meta_ad_id)       AS has_ad
FROM ads_paid_leads      -- repeat for ads_paid_bookings
GROUP BY client_id
ORDER BY client_id;
```

BLOCKER when `has_campaign > 0` AND `has_ad = 0` (writer dropped ad-level resolution). WARN when `has_ad` is non-zero but well below `has_campaign` (URL-tag coverage limitation, not a code bug). For ORBIT-I1, also count the **in-window** ad-attributed contacts to compare against the Best Ads response:

```sql
SELECT COUNT(DISTINCT contact_id) AS ad_attributed_leads
FROM ads_paid_leads
WHERE client_id = $client_id AND meta_ad_id IS NOT NULL
  AND last_paid_opt_in_at >= $window_start_iso
  AND last_paid_opt_in_at <= $window_end_iso;
```

### Drill-in list ↔ aggregate reconciliation (ORBIT-I3, per client + window)

The Leads / Booked popovers and the Contacts tab expand a count via `api/ads/contacts/list.ts`. The list cohort MUST equal the aggregate it expands (`paidConversionsByObject` in `api/ads/_drilldown-sql.ts`). Compute both independently in Neon and require equality:

```sql
-- Aggregate paid_booked (what the count shows): bookers windowed on booked_at.
SELECT COUNT(DISTINCT contact_id) AS agg_booked
FROM ads_paid_bookings
WHERE client_id = $client_id
  AND booked_at >= $window_start_iso AND booked_at <= $window_end_iso;

-- List cohort for booked=yes (what the popover lists). MUST equal agg_booked.
SELECT COUNT(*) AS list_booked FROM (
  SELECT contact_id FROM ads_paid_bookings
  WHERE client_id = $client_id
    AND booked_at >= $window_start_iso AND booked_at <= $window_end_iso
  GROUP BY contact_id) x;

-- Aggregate paid_leads (UNION) vs list cohort for booked=any. MUST be equal.
SELECT COUNT(DISTINCT contact_id) AS agg_leads FROM (
  SELECT contact_id FROM ads_paid_leads
    WHERE client_id=$client_id AND last_paid_opt_in_at>=$window_start_iso AND last_paid_opt_in_at<=$window_end_iso
  UNION
  SELECT contact_id FROM ads_paid_bookings
    WHERE client_id=$client_id AND booked_at>=$window_start_iso AND booked_at<=$window_end_iso) u;
```

BLOCKER on any inequality. The legacy bug windowed *all* list modes on `last_paid_opt_in_at` and treated booked as `EXISTS(any booking)`, so the popover both leaked (opt-in in window, booking out) and dropped (booked in window, opt-in before) vs the count. Equivalent live check: call `GET /api/ads/contacts/list?...&booked=yes&limit=250` and compare `rows.length` to the campaign/client `paid_booked` from `/api/ads/drilldown/campaigns` for the same window.

### Booked Calls surface (ORBIT-J, per client + window)

Schema: `ads_all_bookings` (added 2026-05-22, migration `drizzle/ads_all_bookings.sql`) holds every appointment from every calendar in the location; columns `client_id, appointment_id, contact_id, booked_at, appointment_date, status, calendar_id, calendar_name, raw, synced_at`, PK `(client_id, appointment_id)`. PAID/OTHER is derived at read time, never stored.

**J1 — PAID ⊆ ALL** (any row returned = BLOCKER; lists paid bookings missing from all-bookings):

```sql
SELECT pb.appointment_id, pb.contact_id, pb.calendar_id, pb.booked_at
FROM ads_paid_bookings pb
LEFT JOIN ads_all_bookings ab
  ON ab.client_id = pb.client_id AND ab.appointment_id = pb.appointment_id
WHERE pb.client_id = $client_id
  AND pb.booked_at >= $window_start_iso AND pb.booked_at <= $window_end_iso
  AND ab.appointment_id IS NULL;
```

**J2 — bucket math** (Neon side; must equal the endpoint's `counts` and satisfy all = paid + other):

```sql
SELECT
  COUNT(*)::int                                                AS all_count,
  COUNT(*) FILTER (WHERE pb.appointment_id IS NOT NULL)::int    AS paid_count,
  COUNT(*) FILTER (WHERE pb.appointment_id IS NULL)::int        AS other_count
FROM ads_all_bookings ab
LEFT JOIN ads_paid_bookings pb
  ON pb.client_id = ab.client_id AND pb.appointment_id = ab.appointment_id
WHERE ab.client_id = $client_id
  AND ab.booked_at >= $window_start_iso AND ab.booked_at <= $window_end_iso;
```

**J3 — PAID deduped by contact == `/api/ads/overview` `paid_booked_calls`** (the ORBIT-C/E2 number):

```sql
SELECT COUNT(DISTINCT ab.contact_id)::int AS paid_distinct_contacts
FROM ads_all_bookings ab
JOIN ads_paid_bookings pb
  ON pb.client_id = ab.client_id AND pb.appointment_id = ab.appointment_id
WHERE ab.client_id = $client_id
  AND ab.booked_at >= $window_start_iso AND ab.booked_at <= $window_end_iso;
```

**J4 — OTHER-bucket paid-signal triage** (WARN; the morning "look through these" queue). Up to 15/client in vault mode, count-only in Slack:

```sql
SELECT ab.appointment_id, ab.contact_id, ab.calendar_name, ab.booked_at,
       g.first_utm_source, g.last_utm_source, g.last_fbclid
FROM ads_all_bookings ab
LEFT JOIN ads_paid_bookings pb
  ON pb.client_id = ab.client_id AND pb.appointment_id = ab.appointment_id
LEFT JOIN ads_ghl_contacts g
  ON g.client_id = ab.client_id AND g.contact_id = ab.contact_id
WHERE ab.client_id = $client_id
  AND ab.booked_at >= $window_start_iso AND ab.booked_at <= $window_end_iso
  AND pb.appointment_id IS NULL                              -- OTHER bucket
  AND (
    LOWER(COALESCE(g.last_utm_source,''))  IN ('facebook','instagram','fb','ig','meta')
    OR LOWER(COALESCE(g.first_utm_source,'')) IN ('facebook','instagram','fb','ig','meta')
    OR g.last_fbclid IS NOT NULL
  )
ORDER BY ab.booked_at DESC
LIMIT 15;
```

GHL deep link for each: `https://app.gohighlevel.com/v2/location/{ghl_location_id}/contacts/detail/{contact_id}` (`ghl_location_id` from `ads_clients_config`). Helper in code: `buildGhlContactUrl()` in `src/lib/ads-clients.ts`.

**J5 — unreviewed backlog** (INFO):

```sql
SELECT
  COUNT(*)::int AS all_unreviewed,
  COUNT(*) FILTER (WHERE pb.appointment_id IS NULL)::int AS other_unreviewed
FROM ads_all_bookings ab
LEFT JOIN ads_paid_bookings pb
  ON pb.client_id = ab.client_id AND pb.appointment_id = ab.appointment_id
LEFT JOIN ads_ghl_contacts g
  ON g.client_id = ab.client_id AND g.contact_id = ab.contact_id
WHERE ab.client_id = $client_id
  AND ab.booked_at >= $window_start_iso AND ab.booked_at <= $window_end_iso
  AND (g.review_status IS NULL);
```

### Opt-in dated by event, not sync clock (ORBIT-B5, per client)

A `now()`-stamped re-opt-in is detectable by `last_paid_opt_in_at ≈ synced_at`. For each such row, the stored `raw` must carry a real event timestamp on the SAME calendar day (client tz). The fbc click time is `raw.lastAttributionSource.fbc` parsed as `fb.<v>.<ms>.<fbclid>` (the `<ms>` is epoch-ms); fallback is `raw.dateUpdated`.

```sql
-- now()-stamped rows whose dateUpdated lands on a DIFFERENT day than the stamp = FAIL (mis-windowed).
SELECT client_id, contact_id,
       last_paid_opt_in_at,
       raw->>'dateUpdated'                                  AS date_updated,
       raw->'lastAttributionSource'->>'fbc'                 AS fbc
FROM ads_paid_leads
WHERE client_id = $client_id
  AND ABS(EXTRACT(EPOCH FROM (last_paid_opt_in_at - synced_at))) < 2
  AND raw->>'dateUpdated' IS NOT NULL
  AND (last_paid_opt_in_at AT TIME ZONE $tz)::date
      <> ((raw->>'dateUpdated')::timestamptz AT TIME ZONE $tz)::date;
```

Any row returned is a BLOCKER (the writer dated the lead by the clock; the fbc click time / dateUpdated proves the real event was on another day). Remediation for historical rows: `scripts/backfill-reoptin-timestamp.ts`. Forward owner: [api/ads/_optin-timestamp.ts](api/ads/_optin-timestamp.ts) `resolveReOptInDate`.

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

Schema: [drizzle/schema.ts:309-325 `adsSyncLog`](drizzle/schema.ts#L309). Sources expected (post-Part-11): `meta_insights:campaign`, `meta_insights:adset`, `meta_insights:ad`, `meta_structure`, `ghl_conversions` (all 3 clients), `orchestrator`. `hyros` is no longer expected; if it appears, it's residual log data from before Part 11.

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
GET {origin}/api/ads/best-ads?date_start=...&date_end=...&min_spend=0   # ORBIT-I1
GET {origin}/api/ads/contacts/list?client_id=...&date_start=...&date_end=...&booked=yes&limit=250   # ORBIT-I3 (rows.length == paid_booked)
GET {origin}/api/ads/bookings/list?client_id=...&date_start=...&date_end=...&bucket=all             # ORBIT-J2 (counts.all == counts.paid + counts.other)
```

Compare each response field by field to Andy's independent Neon + Meta + GHL computation. Any divergence is a finding.

---

## Per-section invariant IDs

These IDs are the contract with SKILL.md. Do not rename. Do not renumber. Add new IDs by appending.

| ID | Severity | Section | One-line description |
|---|---|---|---|
| ORBIT-A1 | BLOCKER | Meta ↔ Neon | Spend, ±5% (±10% most-recent day) |
| ORBIT-A2 | BLOCKER | Meta ↔ Neon | Impressions, ±5% |
| ORBIT-A3 | BLOCKER | Meta ↔ Neon | Clicks (inline_link_clicks), ±5% |
| ORBIT-A4 | WARN    | Meta ↔ Neon | Derived CPC/CPM/CTR, ±5% (CTR ±0.1pp) |
| ORBIT-B1 | BLOCKER | GHL ↔ Neon, all 3 clients | Paid lead UNION count equality |
| ORBIT-B2 | BLOCKER | Golden rule grep | No `created_at`/`dateAdded`/`first_paid_opt_in_at` in window filters |
| ORBIT-B3 | BLOCKER | GHL ↔ Neon, all 3 clients | Re-opt-in survives: contact with `dateAdded` < window_start but `last_paid_opt_in_at` in window appears in Neon |
| ORBIT-B5 | BLOCKER/WARN | Neon writer, all 3 clients | Opt-in dated by the EVENT not the sync clock: a `now()`-stamp (`\|opt_in - synced_at\| < 2s`) must corroborate a real event timestamp (fbc click time / `dateUpdated`) on the same calendar day. BLOCKER on different-day; WARN on same-day but >1h off |
| ORBIT-C1 | BLOCKER | GHL ↔ Neon, all 3 clients | Paid booked count equality vs walked GHL events |
| ORBIT-C2 | BLOCKER | Display, all 3 clients | CPBC = spend / paid_booked within ±5% of `/api/ads/overview` |
| ORBIT-D1 | DEPRECATED | Hyros, OBB | (Part 11) OBB no longer Hyros-backed; section retired |
| ORBIT-D2 | DEPRECATED | Hyros, OBB | (Part 11) Same — count now sourced from Neon under B/C |
| ORBIT-D3 | DEPRECATED | Hyros, OBB | (Part 11) HYROS_KEY_OBB env unused; advisory retired |
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
| ORBIT-G4 | WARN    | Latency | `/api/ads/overview` response time < 5s |
| ORBIT-G5 | WARN    | Latency | `/api/ads/drilldown/*` per-call response time < 10s |
| ORBIT-G6 | WARN    | Latency | `/api/ads/audit` response time < 30s |
| ORBIT-G7 | BLOCKER | Latency | No endpoint times out (>60s = Vercel function ceiling hit) |
| ORBIT-H1 | BLOCKER | Code-static | Broader sweep of B2: no banned column references anywhere `ads_paid_leads` is queried |
| ORBIT-H2 | WARN    | Code-static | No bare `YYYY-MM-DD` strings into Meta Graph or drill-down SQL without `clientWindow(timezone, ...)` |
| ORBIT-H3 | WARN    | Code-static | `isLastTouchPaid()` defined exactly once in the repo (drift detector) |
| ORBIT-H4 | WARN    | Code drift | Cited code lines (checksums/code-anchors.json) hash unchanged. Regen via scripts/regen-baselines.sh after intentional changes. |
| ORBIT-H5 | WARN/BLOCKER | Schema drift | Tracked `ads_*` table blocks (checksums/schema-baseline.json) hash unchanged. BLOCKER if referenced column removed/renamed. |
| ORBIT-H6 | WARN    | Endpoint coverage | All `api/ads/*.ts` route files (excluding `_*.ts` helpers) appear in `known_endpoints` below or are explicitly skipped |
| ORBIT-I1 | BLOCKER | Per-ad surface | Best Ads (`/api/ads/best-ads`) shows non-zero conversions when the client has ad-attributable conversions in window; SUM(per-ad paid_leads) reconciles to the `meta_ad_id`-attributed subset |
| ORBIT-I2 | BLOCKER/WARN | Attribution writer | `meta_ad_id` population health: BLOCKER if `COUNT(meta_campaign_id) > 0` but `COUNT(meta_ad_id) = 0` per (client, table); WARN if non-zero but materially below campaign coverage |
| ORBIT-I3 | BLOCKER | Drill-in lists | `contacts/list.ts` cohort reconciles with `paidConversionsByObject`: `booked=yes` count == aggregate `paid_booked`; `booked=any` count == aggregate `paid_leads`, per client + window |
| ORBIT-J1 | BLOCKER | Booked Calls surface | PAID ⊆ ALL: every `ads_paid_bookings` row (booked_at in window) exists in `ads_all_bookings`. Missing = `listCalendars()` skipped a paid calendar |
| ORBIT-J2 | BLOCKER | Booked Calls surface | Bucket math: `/api/ads/bookings/list?bucket=all` `counts.all == counts.paid + counts.other`, and counts match independent Neon derivation exactly |
| ORBIT-J3 | BLOCKER | Booked Calls surface | PAID bucket deduped by contact == `/api/ads/overview` `paid_booked_calls` (per-appointment `counts.paid` may exceed it for re-bookers, by design) |
| ORBIT-J4 | WARN | Booked Calls triage | OTHER-bucket bookings carrying an ad signal (first OR last touch) — the morning "look through these" review queue. Vault: list ≤15/client w/ GHL link; Slack: count only |
| ORBIT-J5 | INFO | Booked Calls triage | Unreviewed booked-call backlog: in-window bookings with `review_status IS NULL`, split ALL vs OTHER |

As of Part 11 (2026-05-20), Sections B and C apply to **all three clients** (CG B2B, BuilderPro, OBB).

ORBIT-J (added 2026-05-22) audits the Booked Calls (ALL / PAID / OTHER) tab + `ads_all_bookings` table + `/api/ads/bookings/list`. J1–J3 enforce correctness (PAID ⊆ ALL, bucket sum, KPI reconciliation) and run in both modes. J4–J5 are the deep morning triage queue Zander asked Andy to "look through" — OTHER-bucket calls that carry a paid signal but missed the confident set, plus the unreviewed backlog. Freshness is covered by ORBIT-G1 (the all-bookings sync runs inside `sync-conversions.ts`, source `ghl_conversions`). ORBIT-D is fully **DEPRECATED** — there is nothing for Andy to audit on the Hyros path because the dashboard no longer reads from it.

ORBIT-I (added 2026-05-21) enforces the working-MVP clause on the conversion surfaces downstream of the headline counts: the per-ad Best Ads tab (I1), the `meta_ad_id` writer health (I2), and the drill-in popovers/Contacts list (I3, added later on 2026-05-21 after the Booked-popover count-vs-list bug). It runs in **both** vault and `--slack` modes (a best-ads call + a handful of Neon counts; cheap, unlike per-adset ORBIT-F).

---

## Known endpoints (ORBIT-H6 catalog)

This list is the contract for ORBIT-H6. When a new file appears in `api/ads/*.ts` and isn't listed here, andy WARNs. Either add the new route to this list AND determine whether it warrants an explicit audit check, or mark it as `skipped: <reason>`.

Underscore-prefixed files (`api/ads/_*.ts`) are helper modules, not routes, so they're not subject to ORBIT-H6.

| Route | Audited by | Notes |
|---|---|---|
| `api/ads/overview.ts` | ORBIT-A, E | per-client + cross-client KPI cards |
| `api/ads/audit.ts` | cross-validation only (not ground truth, per audit.ts:240-258 caveat) | in-app drift report |
| `api/ads/sync-meta-structure.ts` | ORBIT-G1 (freshness) + Slack alert on fail | Meta object metadata sync |
| `api/ads/sync-meta-insights.ts` | ORBIT-A, G1 + Slack alert on fail | Meta insights sync |
| `api/ads/sync-conversions.ts` | ORBIT-B, C, G1 + Slack alert on fail | GHL contacts + bookings walker (all 3 clients post-Part-11) |
| `api/ads/cron-orchestrator.ts` | ORBIT-G1 + Slack alert on fail | structure + insights fan-out |
| `api/ads/drilldown/campaigns.ts` | ORBIT-F | per-campaign breakdown |
| `api/ads/drilldown/adsets.ts` | ORBIT-F | per-adset breakdown |
| `api/ads/drilldown/ads.ts` | ORBIT-F | per-ad list under an adset |
| `api/ads/drilldown/ad.ts` | ORBIT-F | single-ad detail |
| `api/ads/contacts/list.ts` | ORBIT-I3 | backs the Leads / Booked popovers + Contacts tab. Renders the cohort behind every clickable count, so it IS a conversion surface — its list MUST reconcile with `paidConversionsByObject` (was wrongly skipped as a "convenience listing" pre-2026-05-21, which masked the Booked count-vs-popover bug). |
| `api/ads/contacts/all.ts` | ORBIT-I3 | full-contacts view; renders attribution per contact, so it IS a conversion surface — its cohort MUST reconcile with `paidConversionsByObject` for the same window/client like `contacts/list.ts` (cataloged 2026-05-21, H6). |
| `api/ads/contacts/[id].ts` | skipped (read-only convenience detail) | single contact |
| `api/ads/contacts/review.ts` | skipped (reviewer-state writer, no conversion attribution) | marks contacts reviewed/needs-review. NOTE: also the write path behind the Booked Calls review toggle (J4/J5 surface review state but don't write it). |
| `api/ads/bookings/list.ts` | ORBIT-J | Booked Calls (ALL/PAID/OTHER) tab. Reads `ads_all_bookings` joined to `ads_paid_bookings` + `ads_ghl_contacts`. PAID bucket IS a conversion surface (must reconcile with `paid_booked_calls`); ALL/OTHER are the triage queue. Cataloged 2026-05-22. |
| `api/ads/best-ads.ts` | ORBIT-I | cross-client best ads. Renders paid_leads/booked/CPL/CPBC per ad, so it IS a conversion surface (was wrongly skipped pre-2026-05-21). Keys on `meta_ad_id`. |
| `api/ads/drilldown/adsets-all.ts` | ORBIT-F | cross-campaign per-adset breakdown; per-adset leads/booked MUST reconcile with `paidConversionsByObject` the same way `drilldown/adsets.ts` does (cataloged 2026-05-21, H6). |
| `api/ads/drilldown/paused-ads-history.ts` | skipped (read-only historical status display, no conversion attribution) | paused-ad timeline |
| `api/ads/actions/meta.ts` | out of scope (write path, separate audit concern) | pause / resume / budget |
| `api/ads/actions/log.ts` | out of scope (audit log write) | write audit trail |
| `api/ads/sync-status.ts` | skipped (read-only sync state for the dashboard) | feeds the Last-sync badge + SyncNowButton polling |
| `api/ads/slack-client-weekly.ts` | skipped (Slack-only output, no Neon writes) | weekly client-facing Slack recap, all 3 clients |
| `api/ads/slack-daily.ts` | skipped (Slack-only output, no Neon writes) | daily Moreway audit/perf/eod Slack posts; reads /overview + /audit, posts to Slack |
| `api/ads/sync-ghl-contacts.ts` | skipped (sync writer; freshness covered transitively by ORBIT-B/G1) | GHL contacts sync |
| `api/ads/cron-ghl-contacts.ts` | skipped (cron wrapper for sync-ghl-contacts) | scheduled GHL contacts fan-out |
| `api/ads/kpi-targets.ts` | skipped (config CRUD, no conversion attribution) | per-client KPI target storage |
| `api/ads/diagnose-meta-permissions.ts` | skipped (ops diagnostic, read-only) | Meta token/role debug |
| `api/ads/migrate-ghl-contacts.ts` | skipped (one-off migration) | backfill script |
| `api/ads/migrate-kpi-targets.ts` | skipped (one-off migration) | backfill script |
| `api/ads/migrate-kpi-overrides.ts` | skipped (one-off migration) | backfill script |
| `api/ads/migrate-paused-history.ts` | skipped (one-off migration) | backfill script |

Underscore-prefixed helpers (not routes; NEVER counted by ORBIT-H6):
`_db.ts`, `_drilldown-sql.ts`, `_ghl-direct.ts`, `_meta.ts`, `_slack-alert.ts`, `_sources.ts`

---

## Known failure-mode → file mapping

This table is identical to SKILL.md's. When a check fails, Andy includes the likely-owner hint in the report.

| Symptom | Likely file |
|---|---|
| ORBIT-A spend mismatch | [api/ads/sync-meta-insights.ts](api/ads/sync-meta-insights.ts), date alignment / level filtering |
| ORBIT-A clicks drift | [api/ads/audit.ts:88-95](api/ads/audit.ts#L88), `inline_link_clicks` vs `clicks` |
| ORBIT-B count off | [api/ads/sync-conversions.ts](api/ads/sync-conversions.ts), paid-attribution logic in walker, 14-day stale cutoff |
| ORBIT-B golden rule violation | grep target file:line, the violator query lives at the cited line |
| ORBIT-B5 opt-in == synced_at on wrong day | [api/ads/_optin-timestamp.ts](api/ads/_optin-timestamp.ts) `resolveReOptInDate` (fbc click → dateUpdated → now ladder) + its caller in [api/ads/sync-conversions.ts](api/ads/sync-conversions.ts) re-opt-in branch. Historical rows: `scripts/backfill-reoptin-timestamp.ts` |
| ORBIT-C booked count off | [api/ads/sync-conversions.ts](api/ads/sync-conversions.ts), calendar filter, booking_source filter |
| ORBIT-D (DEPRECATED post-Part-11) | n/a — Hyros no longer in dashboard data path |
| ORBIT-E aggregation off | [api/ads/overview.ts:212-233](api/ads/overview.ts#L212), cross-client SUM logic |
| ORBIT-E CPL/CPBC off | [api/ads/overview.ts:208-209](api/ads/overview.ts#L208), null-safe formulas |
| ORBIT-F orphan ads | [api/ads/sync-meta-structure.ts](api/ads/sync-meta-structure.ts), missing `parent_id` / `campaign_id` on ad rows |
| ORBIT-G stale | [api/ads/cron-orchestrator.ts](api/ads/cron-orchestrator.ts) + cron schedule in `vercel.json` |
| ORBIT-H1 code-static fail | the grep hit's file:line |
| ORBIT-H4 code-anchor drift | the cited anchor's invariants_ref + the file:line in code-anchors.json |
| ORBIT-H5 schema drift | [drizzle/schema.ts](drizzle/schema.ts) at the cited line range |
| ORBIT-H6 uncatalogued endpoint | the `api/ads/*.ts` file path returned by the grep |
| ORBIT-G4-G7 latency | endpoint config in `vercel.json` (`maxDuration`), Neon pool exhaustion, or upstream Meta/GHL slowness inside the endpoint |
| ORBIT-I `meta_ad_id` all-zero / Best Ads shows 0 | [api/ads/sync-conversions.ts](api/ads/sync-conversions.ts) `resolveMetaIds` / `adByName` — ad-name → ad-id backfill dropped. Read path [api/ads/best-ads.ts:245-272](api/ads/best-ads.ts#L245) keys on `meta_ad_id` with no true-total fallback. |
| ORBIT-I3 popover/list count ≠ the number it expands | [api/ads/contacts/list.ts](api/ads/contacts/list.ts) cohort SQL diverged from `paidConversionsByObject` ([api/ads/_drilldown-sql.ts](api/ads/_drilldown-sql.ts)): leads window on `last_paid_opt_in_at`, bookings MUST window on `booked_at`; "booked" cohort is bookers-in-window, not EXISTS-any-booking. |
| ORBIT-J1 paid booking missing from `ads_all_bookings` | [api/ads/sync-conversions.ts](api/ads/sync-conversions.ts) `listCalendars()` / `syncOneClientAllBookings` — all-calendars walk didn't return the paid calendar (wrong `Version` header, archived calendar, or calendars-API outage → `calendars.size === 0` warn). |
| ORBIT-J2 bucket counts wrong / don't sum | [api/ads/bookings/list.ts](api/ads/bookings/list.ts) — `pb.appointment_id IS NULL/NOT NULL` bucket join or the `COUNT(*) FILTER` counts query drifted. |
| ORBIT-J3 PAID distinct-contact ≠ paid_booked KPI | [api/ads/bookings/list.ts](api/ads/bookings/list.ts) join to `ads_paid_bookings`; if `ads_paid_bookings` itself is off, fix ORBIT-C first. |

---

## Local mode vs --slack mode scope

Andy runs in two modes, both invoking the same skill body. Section scope differs:

| Section | Local (vault) | `--slack` (Slack post) |
|---|---|---|
| ORBIT-A (Meta ↔ Neon) | RUN | RUN |
| ORBIT-B (GHL ↔ Neon, CG+BP) | RUN | RUN |
| ORBIT-C (Booked, CG+BP) | RUN | RUN |
| ORBIT-D (Hyros, OBB) | DEPRECATED (Part 11) | DEPRECATED (Part 11) |
| ORBIT-E (API ↔ Neon) | RUN | RUN |
| ORBIT-F (Per-adset drilldown) | RUN | **SKIP** (top-20 loop is too slow for Slack TTL) |
| ORBIT-G (Sync freshness) | RUN | RUN |
| ORBIT-H (Code-static grep) | RUN | **SKIP** (no repo checkout in cloud routine) |
| ORBIT-I (Per-ad surface + meta_ad_id health + I3 drill-in reconciliation) | RUN | RUN |
| ORBIT-J (Booked Calls bucket integrity + triage queue) | RUN (J1–J5, full triage lists) | RUN J1–J3 + J4/J5 counts only (lists deferred to vault) |

**Vault is the deep audit. Slack is a smoke check.** Slack post format: one line per client with PASS / WARN / FAIL totals + the top failing check ID, plus a vault link for the full report. Slack mode never substitutes for the vault report; both run on the daily 7am schedule.

---

## Drift between executors

The local skill, the `--slack` mode, and the remote routine `trig_01K8mpqa8e9F2DmBRHivNNPV` all invoke **the same skill body** at `~/.claude/skills/andy-the-auditor/SKILL.md`, propagated to the cloud via `/cco` user-scope sync. There is no Python-script duplication and no separate cloud-side prompt template.

If a cloud run and a local run disagree on the same window:

1. First, confirm both ran against the same window (cron timezone vs local terminal timezone can differ by hours near midnight).
2. Second, force `/cco` re-sync. The most common cause of executor drift is a stale cloud-side copy of the skill after a local edit.
3. Third, if disagreement persists after re-sync with identical windows, that is itself a finding: open a vault note in `_Moreway-Agency/attribution-audits/` titled `executor-drift-YYYY-MM-DD.md` with both reports inline.

Never patch around drift by editing the cloud copy separately. The local skill body is the source; cloud is a mirror.
