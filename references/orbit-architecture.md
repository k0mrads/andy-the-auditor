# Orbit Architecture: Cold-Start Map for Andy

One-paragraph orientation (updated 2026-06-10): **Moreway Orbit** (repo `k0mrads/moreway-orbit`, local path `~/Claude Code/Moreway/Moreway | Tasks/`) is a single Vercel app that fronts the Ads Command Center for **seven enabled clients**: **CareGenius B2B** (CAD, NY tz), **BuilderPro** (USD, LA tz), **OBB** (USD, NY tz), **Contractor Launch** (USD, Chicago tz), **Mustache Painting**, **Peach Paint Co** (Meta leadform clients), and **Queen Consultancy** (leadform leads + Calendly bookings). The backend is **Neon Postgres + Drizzle ORM** behind Vercel serverless functions under `api/`. Conversion truth is ALWAYS Neon: the GHL walker (`sync-conversions.ts`) feeds the 4 GHL clients, `sync-meta-leadforms.ts` feeds the painting clients + queen leads, `sync-calendly-bookings.ts` feeds queen bookings. **Hyros is fully retired from every conversion path (Part 11, 2026-05-20).** The north-star attribution rule Andy defends on every check: **a lead is paid-in-window iff its `last_paid_opt_in_at` falls in the window; contact age is irrelevant; re-opt-ins of older contacts count**; booked calls count under the COUNTED semantics (28-day click gate + exclusions + one primary booking per contact + `counts_as_separate`). The canonical predicate lives in [`touchIsPaidMeta()` + `isLastTouchPaid()` at api/ads/_ghl-direct.ts:149-170](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/_ghl-direct.ts#L149) (first-or-last touch; bare fbclid NOT sufficient).

---

## 1. Three-layer diagram

```
            UPSTREAM (ground truth)            NEON (cache)              ORBIT API (display/math)
            -----------------------            -------------             -----------------------
  Meta Graph v21.0 /insights, /campaigns  ─►  ads_meta_insights      ─►  /api/ads/overview
  (per-account token, level=campaign|         ads_meta_structure         /api/ads/audit
   adset|ad)                                                             /api/ads/drilldown/{campaigns,adsets,ads,ad}
                                                                         /api/ads/best-ads
  GHL /contacts/, /contacts/{id},             ads_paid_leads         ─►  /api/ads/contacts/list, /api/ads/contacts/[id]
      /calendars/events  (4 GHL clients)      ads_paid_bookings          /api/ads/bookings/list, /api/ads/slack-*
                                              ads_all_bookings           /api/ads/actions/{meta,log}
  Meta leadforms (mustache, peach, queen)     ads_ghl_contacts
  Calendly /scheduled_events (queen)          ads_sync_log               (cron writes; auditor reads)
                                              ads_clients_config         (config; read every request)
                                              ads_command_center_audit   (write-action log; never read by auditor)
```

The display layer never talks to upstream directly except the audit endpoint's Meta cross-check. Everything else reads Neon. Hyros appears nowhere in the data path (retired Part 11).

---

## 2. Sync layer (cron writers)

All under `api/ads/`. Cron schedule from [`vercel.json`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/vercel.json) crons block:

| File | Purpose | Cron |
|---|---|---|
| [`sync-meta-insights.ts`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/sync-meta-insights.ts) (383 lines) | Walks Meta Graph per-client at `level=campaign|adset|ad`, writes `ads_meta_insights` rows per `(client, date_start, level, object_id)`. | via orchestrator |
| [`sync-meta-structure.ts`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/sync-meta-structure.ts) (299 lines) | Walks campaigns/adsets/ads + creative fields; writes `ads_meta_structure`. | via orchestrator |
| [`sync-conversions.ts`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/sync-conversions.ts) | The 4 GHL clients (CG, BP, OBB, contractor-launch). Walks GHL contacts newest-first, applies `isLastTouchPaid` (first-or-last `touchIsPaidMeta`), UPSERTs `ads_paid_leads` (re-opt-in dating via `resolveReOptInDate` event ladder). Walks each `ghl_paid_calendar_ids` value, UPSERTs `ads_paid_bookings` with `click_at` from the fbc cookie, plus `ads_all_bookings` (every calendar). | via orchestrator |
| [`sync-meta-leadforms.ts`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/sync-meta-leadforms.ts) | Leadform clients (mustache-painting, peach-paint-co, queen leads). Writes `ads_paid_leads.last_paid_opt_in_at = lead.created_time`. Sync-log source `meta_leadforms`. | cron |
| [`sync-calendly-bookings.ts`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/sync-calendly-bookings.ts) | Queen bookings. Calendly events → `ads_paid_bookings`, `booked_at = event.created_at`, `click_at` = matched lead opt-in. Sync-log source `calendly`. | cron |
| [`cron-orchestrator.ts`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/cron-orchestrator.ts) (122 lines) | Fan-out parent that triggers the three syncs per enabled client. Writes parent row to `ads_sync_log` with `source='orchestrator'`. | `0 14 * * *`, `0 19 * * *` (UTC) |
| [`slack-obb-update.ts`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/slack-obb-update.ts) (706 lines) | Daily + weekly Slack summary for OBB. Not strictly a sync, but cron-driven. | `0 13,14 * * *` (24h), `0 13,14 * * 5` (7d) |

Cron auth: handlers detect `req.headers['x-vercel-cron'] === '1'` and bypass `requireSession()`. See [`audit.ts:332-336`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/audit.ts#L332) for the canonical pattern.

OBB is a full GHL-walker client like CG/BP/contractor-launch (Part 11, 2026-05-20). `fetchHyrosCallsCount` survives in `_sources.ts` as dead code only; nothing reads Hyros live.

---

## 3. Schema essentials (`drizzle/schema.ts`; line numbers drift - locate tables by `pgTable('name'` search. New since baseline: `ads_ghl_contacts`, `ads_all_bookings`, `fmt_catalog`, `fmt_usage`, kpi/spend-controller/sales tables)

### `ads_clients_config` ([schema.ts:223](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/drizzle/schema.ts#L223))
- **PK**: `id` (e.g. `'caregenius-b2b'`, `'builderpro'`, `'obb'`)
- Holds: `meta_account_id` (with `act_` prefix), `currency`, `currency_to_usd` (numeric, manual update; 0.73 for CAD), `timezone` (IANA), `meta_secret_name`, `ghl_api_secret_name`, `ghl_location_id`, `ghl_paid_calendar_ids` (text[]), `hyros_secret_name`, `token_expires_at`, `enabled`.
- Read on EVERY request that fans out across clients. Andy reads it once per run to enumerate targets and pick up tz/calendar IDs.

### `ads_meta_structure` ([schema.ts:244](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/drizzle/schema.ts#L244))
- **PK**: `(client_id, id)`
- **Attribution columns**: `parent_id`, `campaign_id` (denormalized for ad rows)
- Indexes: `level_idx (client_id, level)`, `parent_idx (client_id, parent_id)`
- Holds creative fields: `creative_thumbnail_url`, `creative_body`, `creative_title`, `raw` (jsonb full Graph row).

### `ads_meta_insights` ([schema.ts:278](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/drizzle/schema.ts#L278))
- **PK**: `(client_id, date_start, level, object_id)`
- **Window-filter column**: `date_start` (date type, NOT timestamp)
- Metrics: `spend`, `impressions`, `clicks`, `cpm`, `ctr`, `cpc`, `reach`, `frequency`
- Denormalized parent IDs: `campaign_id`, `campaign_name`, `adset_id`, `adset_name`, `ad_id`, `ad_name`
- Indexes: `date_idx (client_id, date_start)`, `level_idx (client_id, level)`

### `ads_sync_log` ([schema.ts:309](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/drizzle/schema.ts#L309))
- **PK**: `id` (uuid)
- `source` schema comment says `'meta_insights' | 'meta_structure' | 'ghl' | 'hyros' | 'orchestrator'` ([schema.ts:316](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/drizzle/schema.ts#L316)) but **actual writes may use suffixed forms** like `'meta_insights:campaign'`, `'meta_insights:adset'`, `'ghl_conversions'`. Verify at run time via `SELECT DISTINCT source FROM ads_sync_log` before equality matching.
- Indexes: `started_at_idx`, `client_source_idx (client_id, source, started_at)`

### `ads_paid_leads` ([schema.ts, `adsPaidLeads`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/drizzle/schema.ts)) (all clients)
- **PK**: `(client_id, contact_id)` (one row per contact, NOT per opt-in event)
- **Window-filter column (north star)**: `last_paid_opt_in_at` ([schema.ts:347](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/drizzle/schema.ts#L347)). Schema comment line 344-346: "For brand-new contacts on first sync: dateAdded. For re-opt-ins detected via UTM signature change on a subsequent sync: NOW (sync time)." That bump is the entire mechanism for re-opt-in to land in a current window.
- `utm_signature` = `utm_source|utm_medium|utm_campaign|utm_content|utm_term|fbclid`, used by `sync-conversions.ts` to detect signature drift = new paid opt-in.
- **Attribution columns**: `meta_campaign_id`, `meta_adset_id`, `meta_ad_id`, `campaign_name`, `ad_name`
- Indexes: `window_idx (client_id, last_paid_opt_in_at)`, plus **three partial indexes** that skip NULLs for drill-down join speed: `meta_campaign_idx`, `meta_adset_idx`, `meta_ad_idx` (`WHERE meta_*_id IS NOT NULL`).

### `ads_paid_bookings` ([schema.ts, `adsPaidBookings`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/drizzle/schema.ts)) (all clients with bookings)
- **PK**: `(client_id, appointment_id)`
- **Window-filter column**: `booked_at` (timestamp with tz; comes from event `dateAdded` or `startTime` fallback)
- `calendar_id`, `status`, `appointment_date` (date)
- **Counted-semantics columns** (post 2026-05-26/#94 and 2026-06-09/#208): `click_at` (fbc click time; gates paid counting to clicks within 28d before booking) and `counts_as_separate` (operator override crediting a genuine re-book). Raw rows ≠ counted rows: reschedules, stale-click rows, and excluded contacts exist in the table but do NOT count.
- Same three partial meta_*_id indexes as `ads_paid_leads`.

### `ads_command_center_audit` ([schema.ts:428](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/drizzle/schema.ts#L428))
- Write-action log: every pause/resume/budget-update from the dashboard. `status` flow: `'initiated' → 'success' | 'error'`. Andy does NOT read this; it's the dashboard's own audit trail.

---

## 4. Attribution resolution: two phases

### Phase 1: sync-time (server-side, GHL walker)

Lives in [`api/ads/_ghl-direct.ts`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/_ghl-direct.ts). The same module is used both by `sync-conversions.ts` (writer) and by Andy (auditor's independent walk).

**`touchIsPaidMeta(t)` + `isLastTouchPaid(contact)` ([_ghl-direct.ts:149-170](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/_ghl-direct.ts#L149))** (current deployed semantics; the old bare-fbclid last-touch-only form was replaced by #79 + #147):

```ts
// per-touch: paid IFF GHL labeled it Paid Social, OR a 6+ digit Meta entity id
// resolves (adId/adGroupId/utmTerm, or adId/adGroupId/adsetId/utm_id/utm_term
// in the landing URL), OR utm_medium matches /paid|cpc|ppc/.
// A bare fbclid/_fbc is NOT sufficient (organic clicks carry it too).
export function touchIsPaidMeta(t) {
  if (!t) return false;
  return isPaidSocialSession(t) || hasMetaEntityId(t) || hasPaidMedium(t);
}
// contact-level: FIRST OR LAST touch (name retained for compatibility).
export function isLastTouchPaid(c) {
  return touchIsPaidMeta(getEffectiveLastTouch(c)) || touchIsPaidMeta(getEffectiveFirstTouch(c));
}
```

No tag backup. Unlike the deprecated sister apps, Orbit does NOT honor a `BAC` / `OPT IN` tag.

**`getEffectiveLastTouch(c)` ([_ghl-direct.ts:58-65](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/_ghl-direct.ts#L58))**: prefers `lastAttributionSource` (only present on `/contacts/{id}`, stripped by `/contacts/` list); falls back to last `attributions[]` entry (preferring `isLast === true`). Walker MUST fetch each contact individually because the list endpoint strips `lastAttributionSource`.

**`getLastTouchDate(c)` ([_ghl-direct.ts:92-109](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/_ghl-direct.ts#L92))**: tries last-touch date fields (`UTCClickDate`, `clickDate`, `date`, `dateTime`, `addedAt`); falls back to `contact.dateAdded`. **Never falls back to `dateUpdated`** ([_ghl-direct.ts:87-89](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/_ghl-direct.ts#L87)) because GHL bulk-stamps that field and produces ~40x false positives.

**`fetchGhlGroundTruthCounts({apiKey, locationId}, dateStart, dateEnd)` ([_ghl-direct.ts:155-251](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/_ghl-direct.ts#L155))**: bounded walker. MAX_PAGES=20 × PAGE_SIZE=100 = 2000 contacts. Concurrency 4. 6-attempt 429-aware retry with exponential backoff cap 16s.

**`fetchGhlBookedCallsGroundTruth({apiKey, locationId}, paidCalendarIds, dateStart, dateEnd)` ([_ghl-direct.ts:269-361](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/_ghl-direct.ts#L269))**: walks `/calendars/events?calendarId=...` for each paid calendar (note: pads fetch window by -7d/+90d to capture bookings whose startTime sits outside the audit window but whose creation event is inside it; intersects with the strict window via `dateAdded ?? startTime`).

### Phase 2: read-time (server-side, the UNION)

Lives in [`api/ads/_drilldown-sql.ts:118-133 `countedPaidBookings()` + :223-267 `paidConversionsByObject()`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/_drilldown-sql.ts#L118). This is **THE** paid-conversions definition the dashboard returns:

```
counted booking = ads_paid_bookings row that passes ALL of:
  (a) click_at in [booked_at - 28d, booked_at + 1d]  OR  raw._manual_override = 'true'
  (b) parent contact not ads_ghl_contacts.excluded_from_metrics
  (c) booked_at = MIN(booked_at) OVER (PARTITION BY contact_id)  [all-time, over qualifying rows]
      OR counts_as_separate = true

paid_leads  = COUNT(DISTINCT contact_id) of
              (non-excluded opt-iners with last_paid_opt_in_at in window)
              UNION
              (COUNTED bookings with booked_at in window)
paid_booked = COUNT(*) of COUNTED bookings with booked_at in window   [per booking, not per contact]
```

The "lead OR booker" union is what makes bookers whose original opt-in landed pre-window still count as a lead (you can't book without opting in at some point). The counted-booking gates are what stop reschedules double-counting (GHL creates a fresh confirmed appointment per reschedule with no cancel signal) - including ACROSS windows, which the old `COUNT(DISTINCT contact_id)`-per-window form missed. Same semantics applied scope-agnostically by `paidConversionsByObject(clientId, joinColumn, windowStart, windowEnd)` where `joinColumn ∈ {'meta_campaign_id', 'meta_adset_id', 'meta_ad_id'}`.

The overview KPI cards use the same counted union via [`_sources.ts:fetchGhlCountsFromNeon` at lines 55-115](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/_sources.ts#L55) (un-grouped variant). Any audit SQL that counts raw `ads_paid_bookings` rows in window WILL overcount vs the app and produce false blockers.

---

## 5. Display layer (read endpoints)

All gated by [`requireSession()` at api/_db.ts:58-103](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/_db.ts#L58). Cron-bypass via `x-vercel-cron: 1`; service-bypass via `AUDIT_TOKEN`.

| Endpoint | Computes | Source of truth |
|---|---|---|
| [`overview.ts`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/overview.ts) (247 lines) | Per-client + total KPI cards: spend, impressions, clicks, ctr, cpm, paid_leads, paid_booked_calls, cpl, cpbc, plus prev-window for trend arrows. | Neon `ads_meta_insights` aggregate at [overview.ts:58-75](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/overview.ts#L58); per-client conversion fan-out via `fetchConversionCounts` at [overview.ts:120-135](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/overview.ts#L120). |
| | `cpl = spend / paid_leads if paid_leads > 0 else null` | [overview.ts:208](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/overview.ts#L208) |
| | `cpbc = spend / paid_booked_calls if > 0 else null` | [overview.ts:209](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/overview.ts#L209) |
| | `totals.* = SUM(clients.*.*)` | [overview.ts:212-233](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/overview.ts#L212) |
| [`drilldown/campaigns.ts`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/drilldown/campaigns.ts) | Per-campaign rollup. | Neon `ads_meta_insights` JOIN `paidConversionsByObject(client, 'meta_campaign_id', ...)` |
| [`drilldown/adsets.ts`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/drilldown/adsets.ts) | Per-adset rollup. | same, scoped to `meta_adset_id` |
| [`drilldown/ads.ts`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/drilldown/ads.ts) | Per-ad rollup. | same, scoped to `meta_ad_id` |
| [`drilldown/ad.ts`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/drilldown/ad.ts) | Single-ad detail drawer. | same |
| [`contacts/list.ts`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/contacts/list.ts) | Paid contact list for the window. | Neon `ads_paid_leads` + `ads_paid_bookings` |
| [`contacts/[id].ts`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/contacts/%5Bid%5D.ts) | Single contact detail. | Neon |
| [`best-ads.ts`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/best-ads.ts) (370 lines) | Cross-client top performers ranked by USD-normalized CPL/CPBC. Uses `currency_to_usd` from `ads_clients_config`. | Neon + `toUsd()` helper from `_drilldown-sql.ts:174-183` |

Frontend cross-client strip ([CrossClientStrip.tsx:43-76](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/src/components/ads-command-center/components/CrossClientStrip.tsx#L43)) reads `overview.totals.*` directly. The totals are already summed server-side. Frontend does NOT re-sum per-client values; it just renders `totals.spend`, `totals.cpbc`, etc.

---

## 6. Timezone helper: `clientWindow(tz, start, end)`

Lives at [`_drilldown-sql.ts:54-60`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/_drilldown-sql.ts#L54):

```ts
export function clientWindow(timezone: string, dateStart: string, dateEnd: string): DateWindow {
  const startOffset = tzOffsetForDate(timezone, dateStart);
  const endOffset = tzOffsetForDate(timezone, dateEnd);
  return {
    start: new Date(`${dateStart}T00:00:00.000${startOffset}`),
    end: new Date(`${dateEnd}T23:59:59.999${endOffset}`),
  };
}
```

`tzOffsetForDate` ([_drilldown-sql.ts:34-46](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/_drilldown-sql.ts#L34)) uses `Intl.DateTimeFormat({timeZoneName: 'longOffset'})` to produce `-04:00` / `-05:00` (DST-aware) / `-07:00` (LA).

**Critical pitfall**: any bare `YYYY-MM-DD` string passed to a `new Date(...)` or to Meta Graph **without `clientWindow`** is interpreted as UTC midnight, which is 4-5 hours off the client's true day boundary. That shifts the window enough to drop or pick up several conversion rows. Andy check **ORBIT-H2** greps for this.

**Known divergence inside Orbit**: the GHL walker at [`_ghl-direct.ts:165-166`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/_ghl-direct.ts#L165) constructs the window as `T00:00:00Z` / `T23:59:59.999Z` (UTC). That's NOT `clientWindow()`. A contact whose last touch lands at 23:00 EST can fall in a different window depending on which path (Neon UNION via tz-aware boundaries vs walker via UTC boundaries) classifies it. Treat as a known low-magnitude drift class; report in **ORBIT-B1** as a contributing factor when counts disagree.

---

## 7. Known inconsistencies inside Orbit

For future-me (Andy) to be aware of:

1. **Audit endpoint vs picker default-window**. [`api/ads/audit.ts:316-325 defaultLast3Days()`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/audit.ts#L316) uses "today + 2 prior" (includes today). [`DateRangePresetPicker.tsx:60-78 computePresetRange`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/src/components/ads-command-center/components/DateRangePresetPicker.tsx#L60) uses "yesterday + 2 prior" (today excluded, since today is partial). **Andy matches the picker**: end = yesterday in NY, start = end - 2.

2. **GHL walker tz mismatch**. `_ghl-direct.ts:165` builds the audit window as UTC; the dashboard UNION (`_drilldown-sql.ts:54-60` and `_sources.ts:45-52`) uses client-tz-aware boundaries. Same data, different classification at the day boundary.

3. **`ads_sync_log.source` field**. Schema comment lists 5 values; actual writes may include suffixed forms (`'meta_insights:campaign'`, `'ghl_conversions'`, etc.). Treat the comment as advisory, the data as ground truth.

4. **Audit endpoint's "ground truth" is dashboard**. [`audit.ts:240-258`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/audit.ts#L240) explicitly sets `ground_truth = dashboard` for conversions. The audit endpoint does NOT independently walk GHL. That's why Andy exists.

5. **slack-obb-update.ts still reimplements conversions from retired Hyros** (audit F03, known drift): the client-facing OBB Slack post counts cancelled calls + organic leads and diverges from the dashboard definition. Every dashboard surface is GHL/Neon-counted; only this Slack post lags. Fix tracked separately - report divergence there as the known F03 finding, not a fresh regression.

6. **Cross-client totals at 1:1 FX**. [`CrossClientStrip.tsx:50`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/src/components/ads-command-center/components/CrossClientStrip.tsx#L50) explicitly: "Aggregate sums spend across USD + CAD at 1:1; Phase 4 adds live FX." Best-ads endpoint uses `currency_to_usd` (manual rate), but cross-client KPI strip does not.

---

## 8. Existing audit endpoint (`api/ads/audit.ts:1-357`)

What it DOES cover:
- Meta Graph API vs Neon `ads_meta_insights` aggregate, per client, 5% tolerance. Six metrics: spend, impressions, clicks (`inline_link_clicks`), cpm, ctr, cpc. Comparison at [`audit.ts:88-95`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/audit.ts#L88) (Meta side) and [`audit.ts:121-149`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/audit.ts#L121) (Neon side); per-metric pass/fail at [`audit.ts:151-162 check()`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/audit.ts#L151).
- Cron-callable via `x-vercel-cron: 1`; session-callable otherwise.

What it does NOT cover (Andy's job):
- No live GHL re-walk for paid-lead/paid-booked ground truth. Documented at [`audit.ts:242-252`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/audit.ts#L242): "Re-walking GHL live for the audit's ground truth duplicates the cron's work and reliably exceeds the 60s function ceiling on larger accounts (CG = ~100s)". Audit just echoes `ground_truth = dashboard`.
- No code-static checks for `created_at` / `dateAdded` / `first_paid_opt_in_at` violations.
- No per-adset attribution reconciliation.
- No sync freshness check.
- No day-over-day delta.

Andy provides all of the above (sections ORBIT-B, C, F, G, H per SKILL.md).

---

## 9. Auth pattern

[`requireSession()` at api/_db.ts:58-103](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/_db.ts#L58) accepts three auth modes:

1. **Sessions-table token**: `Authorization: Bearer <token>` or `?token=<token>` (the query-string fallback exists for `@vercel/blob`'s `upload()` helper which strips Authorization). Looked up in `sessions` table; checks `expires_at`.
2. **AUDIT_TOKEN env-var bypass** ([_db.ts:120-130](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/_db.ts#L120)): if the supplied token equals `process.env.AUDIT_TOKEN`, returns a synthetic session with `userIdentity = 'audit-bot'`, `role = 'internal'`, `scopedClientId = null` (client-portal RBAC added 2026-06). Read on every call (so Vercel env rotation takes immediate effect). This is the path Andy uses.
3. **Cron header**: handlers check `req.headers['x-vercel-cron'] === '1'` BEFORE calling `requireSession()` and skip it. See [`audit.ts:332-336`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/audit.ts#L332).

The `audit-bot` identity is logged into `ads_command_center_audit.user_identity` if any write action is ever attempted by an audit caller; Andy must NEVER call action endpoints, only read endpoints (`/api/ads/overview`, `/api/ads/audit`, `/api/ads/drilldown/*`, `/api/ads/contacts/*`, `/api/ads/best-ads`).

---

## 10. Meta Graph API reference

Account-level aggregate (used by audit and Andy's Section A):

```
GET https://graph.facebook.com/v21.0/{act_id}/insights
  ?fields=spend,impressions,inline_link_clicks
  &time_range={"since":"YYYY-MM-DD","until":"YYYY-MM-DD"}
  &level=account
  &access_token={token}
```

Per-adset (used by Andy's Section F):

```
GET https://graph.facebook.com/v21.0/{act_id}/insights
  ?fields=spend,impressions,inline_link_clicks,adset_id,adset_name
  &time_range=...
  &level=adset
  &access_token={token}
```

**Critical gotchas**:

- Use **`inline_link_clicks`**, not `clicks`. Meta's `clicks` counts all engagement (page likes, profile expansions, etc.); the dashboard counts link clicks only. Mixing them produced spurious 40-60% drift. See [`audit.ts:88-95`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/audit.ts#L88) and [`audit.ts:94`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/audit.ts#L94) comment.
- **Recompute `ctr` / `cpc` / `cpm` in code**, do not request Meta's own `ctr` / `cpc` fields. Meta computes those over `clicks` (all clicks); the dashboard computes them over `inline_link_clicks`. Recomputed identically on both sides at [`audit.ts:115-118`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/audit.ts#L115).
- Most-recent day's Meta data is still aggregating: tolerance loosens to ±10% for the latest day (per SKILL.md A1-A4 spec).
- Token per client: `process.env[client.metaSecretName]`. Names are stored in `ads_clients_config.meta_secret_name` (read live; the roster is 7 clients now). Known values include `META_TOKEN_CAREGENIUS_B2B`, `META_TOKEN_BUILDERPRO`, `META_TOKEN_OBB`, plus the contractor-launch / painting / queen secrets per config.

---

## 11. Cheat-sheet: "if you need X, look at Y"

| Need | File:line |
|---|---|
| Canonical paid-Meta predicate | [api/ads/_ghl-direct.ts:149-170](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/_ghl-direct.ts#L149) (`touchIsPaidMeta` + first-or-last `isLastTouchPaid`) |
| Paid click time (fbc → click_at) | [api/ads/_ghl-direct.ts `getPaidClickTime`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/_ghl-direct.ts) |
| GHL walker (paid leads ground truth) | [api/ads/_ghl-direct.ts `fetchGhlGroundTruthCounts`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/_ghl-direct.ts) |
| GHL walker (paid bookings ground truth) | [api/ads/_ghl-direct.ts `fetchGhlBookedCallsGroundTruth`](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/_ghl-direct.ts) |
| Counted-bookings gates (click recency, exclusions, primary anchor) | [api/ads/_drilldown-sql.ts:49-133](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/_drilldown-sql.ts#L49) |
| Tz-aware window construction | [api/ads/_drilldown-sql.ts:160-166](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/_drilldown-sql.ts#L160) (duplicate private copy: `_sources.ts:46-53`) |
| Read-side counted UNION (per meta object) | [api/ads/_drilldown-sql.ts:223-267](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/_drilldown-sql.ts#L223) |
| Read-side counted UNION (overview variant) | [api/ads/_sources.ts:55-115](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/_sources.ts#L55) |
| Conversion-source dispatcher (7 clients) | [api/ads/_sources.ts:164-213](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/_sources.ts#L164) |
| CPL formula | [api/ads/overview.ts:220](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/overview.ts#L220) |
| CPBC formula | [api/ads/overview.ts:221](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/overview.ts#L221) |
| Cross-client totals aggregation | [api/ads/overview.ts:224-245](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/overview.ts#L224) |
| Meta Graph fetch (account-level) | [api/ads/audit.ts:82-119](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/audit.ts#L82) |
| Picker window logic (yesterday + 2 prior) | [src/components/.../DateRangePresetPicker.tsx:60-78](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/src/components/ads-command-center/components/DateRangePresetPicker.tsx#L60) |
| Stale-audit default window (today + 2 prior, INCONSISTENT) | [api/ads/audit.ts:316-325](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/audit.ts#L316) |
| Auth (session + AUDIT_TOKEN bypass) | [api/_db.ts:58-103](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/_db.ts#L58) |
| Cron schedule + maxDuration overrides | [vercel.json:65-70](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/vercel.json#L65) |
| Drizzle schema (ads_* tables) | [drizzle/schema.ts:223-449](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/drizzle/schema.ts#L223) |
| Re-opt-in bump logic | [api/ads/sync-conversions.ts](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/api/ads/sync-conversions.ts) (UTM signature diff) |
| Frontend cross-client strip render | [src/components/.../CrossClientStrip.tsx:43-76](../../../Claude%20Code/Moreway/Moreway%20%7C%20Tasks/src/components/ads-command-center/components/CrossClientStrip.tsx#L43) |

---

## Per-client cheatsheet

| Client | client_id | meta_account_id | currency | tz | conversion source |
|---|---|---|---|---|---|
| CareGenius B2B | `caregenius-b2b` | act_27449078924707675 | CAD (×0.73 → USD) | America/New_York | Neon (GHL walker) |
| BuilderPro | `builderpro` | act_1586857008888840 | USD | America/Los_Angeles | Neon (GHL walker) |
| OBB | `obb` | act_425612416873215 | USD | America/New_York | Neon (GHL walker; 3 paid calendars) |
| Contractor Launch | `contractor-launch` | act_626274846998122 | USD | America/Chicago | Neon (GHL walker) |
| Mustache Painting | `mustache-painting` | per config | USD | per config | Neon (Meta leadforms; no bookings) |
| Peach Paint Co | `peach-paint-co` | per config | USD | per config | Neon (Meta leadforms; no bookings) |
| Queen Consultancy | `queen-consultancy` | act_2115558905474636 | USD | America/Los_Angeles | Neon (leadform leads + Calendly bookings) |

Andy's live GHL walks (ORBIT-B/C) cover the 4 GHL clients; B5/B6 and the counted read-side checks cover all 7. Section ORBIT-D is fully deprecated (Hyros retired). A, E, F, G, H, I, J apply to all enabled clients. Roster, tz, currency, and calendar IDs are read live from `ads_clients_config` at run time.
