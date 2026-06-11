---
client: Moreway Orbit
client_dir: ~/Claude Code/Moreway/Moreway | Tasks
vault_subfolder: _Moreway-Agency
sub_clients: [caregenius-b2b, builderpro, obb, contractor-launch, mustache-painting, peach-paint-co, queen-consultancy]
repo: k0mrads/moreway-orbit
---

# Moreway Orbit, Ads Command Center, Audit Invariants

This file is the single source of truth for HOW the `andy-the-auditor` skill runs against the **Moreway Orbit** Ads Command Center (the `/ads` route inside `~/Claude Code/Moreway/Moreway | Tasks/`, GitHub `k0mrads/moreway-orbit`). It replaces the three older invariants files (`caregenius.md`, `builderpro.md`, `moreway-command-center.md`) from the deprecated `/attribution-audit` skill.

> **Rewritten 2026-06-10** (ecosystem-audit findings F19/F20/F40): the predicate, booked-call semantics, client roster, and endpoint catalog below now match the DEPLOYED code (origin/main). The pre-rewrite version documented the 2026-05-20 code verbatim and had drifted on every axis.

Three executors share this file:

1. The local skill (vault mode, deep audit).
2. The same skill invoked with `--slack` (post smoke summary to Slack).
3. The remote routine `trig_01K8mpqa8e9F2DmBRHivNNPV` which invokes the skill on schedule.

If the rule changes, update HERE first, then code. Every Andy check ID below (ORBIT-A1 ... ORBIT-J5, plus ORBIT-B6) MUST agree with `~/.claude/skills/andy-the-auditor/SKILL.md`. If they drift, SKILL.md and this file together fail the audit before any check runs.

---

## Scope

Andy is a **developer-style auditor of the Moreway Orbit app**, not a marketing analyst. Every check below verifies that the app is working and that attribution math is honest. Andy never comments on marketing performance (spend trends, creative effectiveness, campaign-strategy choices, ROAS, sample-size noise). A separate bot owns that. The test: if a finding would fit in a marketing Slack channel, it does NOT belong in an Andy report; if it would fit in a pull-request review of the Orbit codebase, it does. See `~/.claude/skills/andy-the-auditor/SKILL.md` "Scope" section for the full anti-example list.

**Working-MVP clause (standing principle).** Every display surface that renders a conversion metric (`paid_leads`, `paid_booked`, `CPL`, `CPBC`) is in Andy's scope **by default**, whether or not it has its own check ID below. The north star applies to all of them. If a conversion column renders all-zero / dashes on a surface where the same client shows spend AND shows conversions elsewhere (Overview, Campaigns, Adsets), that is a correctness FAIL - a working MVP shows one truth everywhere. New conversion-bearing tabs/endpoints are presumed in-scope until explicitly justified as out-of-scope here. "Informational ranking" is not a valid skip reason for a surface that displays attribution (this is what masked the 2026-05-21 Best Ads `meta_ad_id` regression - see ORBIT-I).

---

## Account & credentials

| Field | Value |
|---|---|
| **Project root** | `~/Claude Code/Moreway/Moreway \| Tasks/` |
| **Env file** | `.env` at project root (mirrored in Vercel Production + Preview) |
| **Database** | Neon Postgres via `DATABASE_URL` |
| **Auth token (audit)** | `AUDIT_TOKEN` in `.env`, mirrored to Vercel. Consumed by [api/_db.ts:120-130 `requireSession()`](api/_db.ts#L120) as a service-auth bypass (synthetic session, `role: 'internal'`, `scopedClientId: null`). |
| **Frontend route** | `/ads` (entry `src/pages/AdsCommandCenter.tsx` → `src/components/ads-command-center/AdsCommandCenterRoot.tsx`) |
| **Overview page** | `src/components/ads-command-center/routes/Overview.tsx` |
| **Cross-client strip** | [src/components/ads-command-center/components/CrossClientStrip.tsx:43-76](src/components/ads-command-center/components/CrossClientStrip.tsx#L43) |
| **Backend KPI endpoint** | `GET /api/ads/overview?date_start=YYYY-MM-DD&date_end=YYYY-MM-DD` |
| **Backend in-app audit endpoint** | `GET /api/ads/audit?date_start=...&date_end=...` (Andy verifies its drift report independently, never trusts it as oracle) |
| **Drill-down endpoints** | `GET /api/ads/drilldown/campaigns`, `/adsets`, `/adsets-all`, `/ads`, `/ad` |
| **Cron orchestrator** | `GET\|POST /api/ads/cron-orchestrator` (scheduled via `vercel.json`) |
| **Deployed origin** | Auto-resolve at run time via `vercel ls --prod \| head -3`. Never hard-code (preview branches rotate). |

---

## Per sub-client config

The audit reads `ads_clients_config` from Neon **at run time**. Do not hard-code these values inside Andy's prompts or scripts - especially `ghl_paid_calendar_ids`, which has already drifted once (OBB gained a third paid calendar that a hard-coded list missed). **Seven rows expected (all `enabled = true` as of 2026-06-10):**

| client_id | label | meta_account_id | currency | timezone | conversion source | enabled |
|---|---|---|---|---|---|---|
| `caregenius-b2b` | CareGenius B2B | `act_27449078924707675` | CAD | `America/New_York` | Neon (`ads_paid_leads` + `ads_paid_bookings`, fed by the GHL walker in `sync-conversions.ts`) | true |
| `builderpro` | BuilderPro | `act_1586857008888840` | USD | `America/Los_Angeles` | Neon (GHL walker) | true |
| `obb` | OBB Home Care | `act_425612416873215` | USD | `America/New_York` | Neon (GHL walker; Part 11, 2026-05-20; Hyros retired). **THREE paid calendars** - read `ghl_paid_calendar_ids` live. | true |
| `contractor-launch` | Contractor Launch | `act_626274846998122` | USD | `America/Chicago` | Neon (GHL walker; added 2026-05-28) | true |
| `mustache-painting` | Mustache Painting | per `ads_clients_config` | USD | per config | Neon, fed by **`sync-meta-leadforms.ts`** (Meta lead forms → `ads_paid_leads`; no GHL, no bookings - `paid_booked_calls` naturally 0) | true |
| `peach-paint-co` | Peach Paint Co | per `ads_clients_config` | USD | per config | Neon, fed by **`sync-meta-leadforms.ts`** (same leadform path) | true |
| `queen-consultancy` | Queen Consultancy | `act_2115558905474636` | USD | `America/Los_Angeles` | Neon, leads from **`sync-meta-leadforms.ts`**, bookings from **`sync-calendly-bookings.ts`** (Calendly → `ads_paid_bookings`; the Calendly sync sets `click_at` = the matched lead's opt-in time so the recency gate passes) | true |

Other columns the audit reads: `meta_secret_name`, `ghl_api_secret_name`, `hyros_secret_name`, `ghl_paid_calendar_ids`, `token_expires_at`. If `enabled = false` for a client, skip its entire section.

OBB's `ghl_location_id` is `Mns7ICmnKi3Pr4QuKmgp`. Known paid calendars as of 2026-06-10: `ClJ06JUJICgDCoELfn9A` (Home Care Hero Application: Interview Scheduling), `1FlpwUCCzC52Zt9y6cr2` (Franchise Interview), and `KtiOSC0uuSUbEyt3Ikpd` (third paid calendar, carries ~14 percent of OBB paid bookings). This list is a snapshot for orientation only - the live `ghl_paid_calendar_ids` row is authoritative. API key in `GHL_KEY_OBB`. `hyros_secret_name` is still 'HYROS_KEY_OBB' in the row but the env var is unused by the dashboard post-Part-11.

Conversion source dispatch lives at [api/ads/_sources.ts:164-213](api/ads/_sources.ts#L164) (`fetchConversionCounts`): **all seven clients** route to the Neon row-counter (`fetchGhlCountsFromNeon`) - the GHL-walker clients via explicit cases, leadform/Calendly clients via the default case reading `timezone` from `ads_clients_config`. `fetchHyrosCallsCount` remains in the file as dead code pending a follow-up cleanup PR.

GHL applies to 4 of 7 (caregenius-b2b, builderpro, obb, contractor-launch). ORBIT-B/C live GHL walks run for those four only; for leadform/Calendly clients, the writer-side truth checks are the raw-payload comparisons (`last_paid_opt_in_at == raw->>'created_time'` for leadforms; `booked_at == raw->'event'->>'created_at'` for Calendly).

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

**Per-client timezone**: read from `ads_clients_config.timezone` and passed into [api/ads/_drilldown-sql.ts:160-166 `clientWindow()`](api/ads/_drilldown-sql.ts#L160) when computing exact timestamp boundaries. Bare `YYYY-MM-DD` strings without `clientWindow()` get parsed as UTC midnight and shift 4 to 8 hours. (Note: `_sources.ts:46-53` carries a private byte-identical copy of `clientWindow` - a known drift seed, flagged in the 2026-06-10 audit as H2-c.)

> **Known inconsistency**: [api/ads/audit.ts `defaultLast3Days()`](api/ads/audit.ts#L318) uses "today + 2 prior" (INCLUDES today), which disagrees with the picker. Andy matches the **picker**, not the audit endpoint's default. When the endpoint is fixed, no change to Andy.

---

## Paid attribution rule (north star)

> **A lead is a paid lead in a given window iff its paid opt-in event timestamp falls inside the window. The age of the contact is irrelevant. Re-opt-ins of older contacts COUNT.**

The rule has exactly **two** code homes. They MUST agree on semantics: Home 1 is the per-contact paid predicate, Home 2 is the counted UNION the display layer serves.

### Home 1, canonical predicate, [api/ads/_ghl-direct.ts:149-170 `touchIsPaidMeta()` + `isLastTouchPaid()`](api/ads/_ghl-direct.ts#L149)

Verbatim from origin/main (shipped in #79 `ba3d93c` 2026-05-22 first-or-last widening, and #147 `ce44698` 2026-06-02 fbclid demotion):

```ts
// Per-touch predicate (:149-156). Paid IFF any of:
//   isPaidSocialSession(t)  - GHL sessionSource == 'paid social'
//   hasMetaEntityId(t)      - adId / adGroupId / utmTerm is a 6+ digit Meta id,
//                             or adId/adGroupId/adsetId/utm_id/utm_term resolves
//                             in the landing-page URL
//   hasPaidMedium(t)        - utm_medium matches /paid|cpc|ppc/
export function touchIsPaidMeta(t: GhlAttribution | null | undefined): boolean {
  if (!t) return false;
  return isPaidSocialSession(t) || hasMetaEntityId(t) || hasPaidMedium(t);
}

// Contact-level: FIRST OR LAST touch (:168-170). Name retained for
// compatibility though it now means first-or-last.
export function isLastTouchPaid(c: GhlContact): boolean {
  return touchIsPaidMeta(getEffectiveLastTouch(c)) || touchIsPaidMeta(getEffectiveFirstTouch(c));
}
```

**A bare `fbclid` / `_fbc` is NO LONGER sufficient** (narrowed 2026-06-02, #147): Facebook stamps `fbclid` on EVERY outbound click - organic posts, bio links, DMs - so the old `fbclid ⇒ paid` rule swept organic-social leads into the paid bucket (the Deborah Dorsett / Latasha Stevenson false positives). The old `utm_source ∈ {facebook, instagram, fb, ig, meta}` list is gone too, replaced by the three signals above. **Regression note:** the Pauline candidate-J1 escalation of 2026-06-08 was a false positive produced by asserting the OLD (bare-fbclid) predicate against the new code; with this rewrite that class of escalation is resolved.

**First-OR-last** (widened 2026-05-22, #79): a contact whose paid click is the FIRST touch but whose last touch decayed to "Direct traffic" (same-session funnel nav drops UTMs) counts as paid. GHL stores only first + last touches, so a paid touch that is ONLY in the middle stays invisible by design; the manual review queue (ORBIT-J4) backstops that rarer case.

No tag backup (no `BAC` / `OPT IN` fallback like the deprecated sister apps had).

### Home 2, counted UNION semantics, [api/ads/_drilldown-sql.ts:118-133 `countedPaidBookings()` + :223-267 `paidConversionsByObject()`](api/ads/_drilldown-sql.ts#L118)

```
paid_leads  = COUNT(DISTINCT contact_id) over the UNION of:
  (1) ads_paid_leads rows with last_paid_opt_in_at in [window_start, window_end]
      AND contact not excluded_from_metrics
  (2) COUNTED bookings (see below) with booked_at in window
Bookers whose original opt-in landed BEFORE the window still count as a lead
(you can't book without opting in at some point). Intentional; matches the north star.

paid_booked = COUNT(*) of COUNTED bookings with booked_at in window.
Per COUNTED BOOKING, not per contact.
```

A **COUNTED booking** (the `countedPaidBookings` CTE, `_drilldown-sql.ts:118-133`) is an `ads_paid_bookings` row that survives ALL of:

1. **28-day click-recency gate** ([`recentPaidClickClauseSql`, :49-61](api/ads/_drilldown-sql.ts#L49), shipped #94 `ee20fb9` 2026-05-26): `click_at` within `[booked_at - 28d, booked_at + 1d]`, OR `raw->>'_manual_override' = 'true'` (operator promotion via `bookings/promote.ts`). NULL `click_at` without the override = excluded (no provable recent ad click).
2. **Excluded-contacts antijoin** ([`notExcludedContactClauseSql`, :77-90](api/ads/_drilldown-sql.ts#L77)): the parent contact is not `ads_ghl_contacts.excluded_from_metrics = true`. The antijoin MUST qualify the outer reference (unqualified correlation self-references `gex.*` and wipes every row - the testy-LLC BuilderPro zero-out bug).
3. **One primary booking per contact** (shipped #208 `549f06f` 2026-06-09): `MIN(booked_at) OVER (PARTITION BY contact_id)` over the ALL-TIME qualifying rows anchors each contact to their FIRST qualifying booking. A row counts iff `booked_at = first_counted_booked_at` OR `counts_as_separate = true` (operator override via `bookings/count-separate.ts`). GHL creates a brand-new confirmed appointment per reschedule with no cancel signal, so first-booking anchoring is the only robust reschedule dedupe - and because the MIN is all-time, a reschedule landing in a LATER window never resurfaces the contact (the Michael Jameson cross-window double-count).

**Andy enforces:** any third site that computes paid_leads or paid_booked (a new endpoint, a new view, a Slack-bot query) is a regression. ORBIT-H3 detects predicate re-implementations; the working-MVP clause covers new surfaces.

### Booked-call paid predicate (write + read combined)

A booking COUNTS as a paid booked call iff:

1. Its parent contact passes `isLastTouchPaid()` above (first-or-last touchIsPaidMeta).
2. `calendar_id ∈ ads_clients_config.ghl_paid_calendar_ids[client_id]` (GHL clients; Calendly rows are written paid-by-construction after lead matching).
3. `booking_source ∈ ('booking_widget', NULL)`.
4. **28-day click recency**: `click_at ∈ [booked_at - 28d, booked_at + 1d]` OR `raw->>'_manual_override' = 'true'`. (#94)
5. **Counted semantics**: the row is the contact's primary (all-time `MIN(booked_at)` over qualifying rows) OR `counts_as_separate = true`; and the contact is not `excluded_from_metrics`. The KPI counts COUNTED bookings in window. (#208)

Gates 1-3 are write-side (rows that fail never enter `ads_paid_bookings`); gates 4-5 are read-side (rows exist in the table but do not count). Any audit SQL that reads `ads_paid_bookings` raw, without gates 4-5, WILL overcount and produce false blockers (reproduced 2026-06-10: naive SQL gave CG 16/12 vs correct 10/6, OBB 27/9 vs 25/5, BP 12/11 vs 11/9).

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
| Paid lead count | exact (0) | Hard equality. Counted-UNION semantics applied on both sides before compare. |
| Paid booked count | exact (0) | Hard equality vs COUNTED bookings (`countedPaidBookings` gates) with `booked_at` in window - NEVER raw `ads_paid_bookings` row counts |
| CPL (per client) | ±0.5% | Derived: spend / paid_leads |
| CPBC (per client) | ±5% | Derived: spend / paid_booked_calls. Formula at [api/ads/overview.ts:220-221](api/ads/overview.ts#L220). |
| Cross-client totals (sums) | exact (0) | Strip is a deterministic sum of per-client values |

**Most-recent-day rule**: when the window includes a day where Meta is still backfilling (typically the last day in window), Andy loosens spend/impressions/clicks tolerance to ±10% for **that day only**. Other days stay ±5%.

---

## Required Neon queries

Connect via `DATABASE_URL` from `~/Claude Code/Moreway/Moreway | Tasks/.env`. **READ-ONLY**. Never `UPDATE`, `INSERT`, `DELETE`, or `TRUNCATE`. Andy is post-hoc, not transactional.

### The counted-bookings CTE (use it EVERYWHERE bookings are counted)

This is the SQL-equivalent of `countedPaidBookings()` in `_drilldown-sql.ts:118-133`. Every booked-count query below embeds it. Substituting a raw `ads_paid_bookings` read for this CTE is the false-blocker bug class F40.

```sql
-- counted_bookings($client_id): the bookings that COUNT as paid booked calls.
WITH counted_bookings AS (
  SELECT cpb.*
  FROM (
    SELECT pb.*,
           MIN(pb.booked_at) OVER (PARTITION BY pb.contact_id) AS first_counted_booked_at
    FROM ads_paid_bookings pb
    WHERE pb.client_id = $client_id
      AND ((pb.click_at IS NOT NULL
            AND pb.click_at >= pb.booked_at - interval '28 days'
            AND pb.click_at <= pb.booked_at + interval '1 day')
           OR COALESCE(pb.raw->>'_manual_override', '') = 'true')
      AND NOT EXISTS (
        SELECT 1 FROM ads_ghl_contacts gex
        WHERE gex.client_id = pb.client_id
          AND gex.contact_id = pb.contact_id
          AND gex.excluded_from_metrics = true)
  ) cpb
  WHERE cpb.booked_at = cpb.first_counted_booked_at
     OR cpb.counts_as_separate = true
)
```

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

`level='campaign'` is preferred over `level='account'` because campaign-level is always synced; account-level rows are optional. Both should reconcile within ±5% of Meta Graph API.

### Lead layer (per client, all 7)

```sql
SELECT contact_id, last_paid_opt_in_at, meta_campaign_id, meta_adset_id, meta_ad_id
FROM ads_paid_leads
WHERE client_id = $client_id
  AND last_paid_opt_in_at >= $window_start_iso
  AND last_paid_opt_in_at <= $window_end_iso;
```

> **Important**: the client-facing paid lead count is **NOT** the plain row count from this query. It is the counted UNION at [api/ads/_sources.ts:55-115](api/ads/_sources.ts#L55) (`fetchGhlCountsFromNeon`):

```sql
-- paid_leads (the Overview KPI):
WITH counted_bookings AS ( ... CTE above ... )
SELECT COUNT(DISTINCT contact_id)::int AS paid_leads FROM (
  SELECT contact_id FROM ads_paid_leads
  WHERE client_id = $client_id
    AND last_paid_opt_in_at >= $window_start_iso
    AND last_paid_opt_in_at <= $window_end_iso
    AND NOT EXISTS (
      SELECT 1 FROM ads_ghl_contacts gex
      WHERE gex.client_id = ads_paid_leads.client_id
        AND gex.contact_id = ads_paid_leads.contact_id
        AND gex.excluded_from_metrics = true)
  UNION
  SELECT contact_id FROM counted_bookings
  WHERE booked_at >= $window_start_iso
    AND booked_at <= $window_end_iso
) u;
```

The audit MUST compute this counted UNION on its side before comparing to `/api/ads/overview`. Plain `ads_paid_leads` row count is for ORBIT-B1 diagnostics only, not for B1 pass/fail.

### Booking layer (per client, all clients with bookings)

```sql
-- paid_booked (the Overview KPI): COUNTED bookings in window. Per booking, not per contact.
WITH counted_bookings AS ( ... CTE above ... )
SELECT COUNT(*)::int AS paid_booked
FROM counted_bookings
WHERE booked_at >= $window_start_iso
  AND booked_at <= $window_end_iso;
```

For row-level diagnostics (sampling appointment_ids on a delta), select columns from the same CTE - never from raw `ads_paid_bookings`, which includes reschedules, stale-click rows, and excluded contacts that the app correctly does not count.

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

The Leads / Booked popovers and the Contacts tab expand a count via `api/ads/contacts/list.ts`. The list cohort MUST equal the aggregate it expands.

**I3 MUST be non-tautological.** Compare two INDEPENDENTLY-PRODUCED surfaces:

- **List side**: the LIVE endpoint response - `GET {origin}/api/ads/contacts/list?client_id=...&date_start=...&date_end=...&booked=yes&limit=250` → `rows.length`. Same for `booked=any`.
- **Aggregate side**: the LIVE overview KPI - `/api/ads/overview` `clients.<id>.paid_booked_calls` (for `booked=yes`) and `paid_leads` (for `booked=any`).

NEVER recompute both sides from the same SQL - the pre-2026-06-10 doc form derived both sides from one naive query, a tautological PASS that structurally could not catch the very bug I3 exists for. **This is the check that would have caught the 2026-06-09 popover bug** (commit #208 wired `countedPaidBookings` into `_drilldown-sql`/`_sources`/`best-ads`/`bookings/list` but missed `contacts/list.ts`, so popovers listed reschedule ghosts the KPI correctly excluded: CG popover 8 vs KPI 6, OBB 7 vs 5).

When the two live surfaces disagree, referee with the counted Neon form to determine which side drifted:

```sql
-- Referee, booked=yes cohort: distinct contacts with a COUNTED booking in window.
WITH counted_bookings AS ( ... CTE above ... )
SELECT COUNT(DISTINCT contact_id) AS counted_bookers
FROM counted_bookings
WHERE booked_at >= $window_start_iso AND booked_at <= $window_end_iso;

-- Referee, booked=any cohort: the counted paid_leads UNION (see Lead layer above).
```

BLOCKER on any list-vs-KPI inequality. Note `paid_booked_calls` counts BOOKINGS while the popover lists CONTACTS - for a window containing a `counts_as_separate` re-book by one contact, expected list length = KPI minus (extra counted bookings beyond each contact's first in-window). Compute the expected list length from the referee SQL when overrides are present, and say so in the report.

### Booked Calls surface (ORBIT-J, per client + window)

Schema: `ads_all_bookings` (added 2026-05-22) holds every appointment from every calendar in the location; columns `client_id, appointment_id, contact_id, booked_at, appointment_date, status, calendar_id, calendar_name, raw, synced_at`, PK `(client_id, appointment_id)`. PAID/OTHER is derived at read time, never stored.

**J1 - PAID ⊆ ALL** (any row returned = BLOCKER; lists paid bookings missing from all-bookings). Counted rows only - a non-counted `ads_paid_bookings` row (reschedule, stale click) missing from `ads_all_bookings` is a different, lesser finding (WARN):

```sql
WITH counted_bookings AS ( ... CTE above ... )
SELECT cb.appointment_id, cb.contact_id, cb.calendar_id, cb.booked_at
FROM counted_bookings cb
LEFT JOIN ads_all_bookings ab
  ON ab.client_id = cb.client_id AND ab.appointment_id = cb.appointment_id
WHERE cb.booked_at >= $window_start_iso AND cb.booked_at <= $window_end_iso
  AND ab.appointment_id IS NULL;
```

**J2 - bucket math** (Neon side; must equal the endpoint's `counts` and satisfy **all = paid + other + excluded** exactly, per-appointment). Re-derived 2026-06-11 from deployed `bookings/list.ts` (origin/main): the endpoint now has FOUR buckets plus a `counted` field. The PAID join carries `recentPaidClickClause('pb')` (28-day click gate + manual override), and excluded contacts (`ads_ghl_contacts.excluded_from_metrics`) move OUT of paid/other into their own bucket so the PAID count matches the Overview KPI layer-for-layer:

```sql
SELECT
  COUNT(*)::int AS all_count,
  COUNT(*) FILTER (
    WHERE pb.appointment_id IS NOT NULL
      AND COALESCE(g.excluded_from_metrics, false) = false
  )::int AS paid_count,
  COUNT(*) FILTER (
    WHERE pb.appointment_id IS NULL
      AND COALESCE(g.excluded_from_metrics, false) = false
  )::int AS other_count,
  COUNT(*) FILTER (WHERE COALESCE(g.excluded_from_metrics, false) = true)::int AS excluded_count
FROM ads_all_bookings ab
LEFT JOIN ads_paid_bookings pb
  ON pb.client_id = ab.client_id AND pb.appointment_id = ab.appointment_id
  AND ((pb.click_at IS NOT NULL
        AND pb.click_at >= pb.booked_at - interval '28 days'
        AND pb.click_at <= pb.booked_at + interval '1 day')
       OR COALESCE(pb.raw->>'_manual_override', '') = 'true')
WHERE ab.client_id = $client_id
  AND ab.booked_at >= $window_start_iso AND ab.booked_at <= $window_end_iso;
-- excluded join: LEFT JOIN ads_ghl_contacts g
--   ON g.client_id = ab.client_id AND g.contact_id = ab.contact_id
-- (include it in the FROM block; shown separately here for readability)
```

The endpoint's `counts.counted` (5th field) = the counted CTE windowed on `booked_at` (`WITH counted_bookings AS (...CTE above...) SELECT COUNT(*) WHERE booked_at in window`); assert `counted <= paid_count` and `counted == overview KPI` (that part is J3). The pb-join click-gate SQL above mirrors `recentPaidClickClauseSql()` in `api/ads/_drilldown-sql.ts` with `PAID_CLICK_LOOKBACK_DAYS = 28`; if that constant or clause changes on origin/main, re-derive THIS block from the deployed file rather than editing the numbers in place.

**J3 - PAID bucket reconciles with `/api/ads/overview` `paid_booked_calls`** (the ORBIT-C/E2 number). The KPI is COUNTED bookings in window, so the reconciling Neon form is the counted CTE joined into all-bookings - NOT a distinct-contact count over the raw join:

```sql
WITH counted_bookings AS ( ... CTE above ... )
SELECT COUNT(*)::int AS paid_counted
FROM counted_bookings cb
JOIN ads_all_bookings ab
  ON ab.client_id = cb.client_id AND ab.appointment_id = cb.appointment_id
WHERE cb.booked_at >= $window_start_iso AND cb.booked_at <= $window_end_iso;
```

`paid_counted` MUST equal the overview KPI (J1 guarantees the join drops nothing). The endpoint's per-appointment `counts.paid` (raw `ads_paid_bookings` membership) MAY exceed it - reschedules and stale-click rows sit in the PAID bucket display but do not count; that is documented and by design.

**J4 - OTHER-bucket paid-signal triage** (WARN; the morning "look through these" queue). Up to 15/client in vault mode, count-only in Slack:

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

(Heads-up: this triage screen intentionally uses the BROAD signal set - utm_source list + fbclid - to surface candidates. That is wider than the counting predicate `touchIsPaidMeta` by design; J4 is a review queue, not a count. Do not "fix" J4 candidates into the paid set unless they pass the real predicate.)

GHL deep link for each: `https://app.gohighlevel.com/v2/location/{ghl_location_id}/contacts/detail/{contact_id}` (`ghl_location_id` from `ads_clients_config`). Helper in code: `buildGhlContactUrl()` in `src/lib/ads-clients.ts`.

**J5 - unreviewed backlog** (INFO):

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

> **B5 coverage gap (companion note, 2026-06-10):** B5 only catches `now()`-stamps. The re-opt-in ladder's rung 2 takes `raw.dateUpdated` as the event time, and GHL bumps `dateUpdated` on ANY field change - touch-flips, bulk edits, and reactivation workflows (e.g. CG's `tfu_ai_reactivation`) all produce **phantom re-opt-ins stamped at a real, non-clock timestamp** that B5 structurally cannot see (audit finding F23: ~13-16 false placements all-time). These need fresh-event corroboration - that is ORBIT-B6 below.

### Rung-2 stamps need fresh-event corroboration (ORBIT-B6, WARN, per client)

A rung-2 stamp is a row where `last_paid_opt_in_at` equals `raw.dateUpdated` (and is NOT a B5 `now()`-stamp). It claims "this contact re-opted-in at dateUpdated" - but `dateUpdated` moves on any workflow touch. Corroborate against the freshest ACTUAL paid event available (the parseable fbc click time). WARN when the corroborating event is more than 7 days older than the stamp, or absent entirely on a rung-2 re-stamp:

```sql
-- Rung-2 stamps whose best corroborating event (fbc click) is >7d stale or missing.
SELECT client_id, contact_id, last_paid_opt_in_at,
       raw->>'dateUpdated'                  AS date_updated,
       raw->'lastAttributionSource'->>'fbc' AS fbc,
       CASE WHEN raw->'lastAttributionSource'->>'fbc' ~ '^fb\.\d+\.\d+\.'
            THEN to_timestamp((split_part(raw->'lastAttributionSource'->>'fbc', '.', 3))::bigint / 1000.0)
       END                                  AS fbc_click_at
FROM ads_paid_leads
WHERE client_id = $client_id
  AND raw->>'dateUpdated' IS NOT NULL
  AND ABS(EXTRACT(EPOCH FROM (last_paid_opt_in_at - (raw->>'dateUpdated')::timestamptz))) < 2
  AND ABS(EXTRACT(EPOCH FROM (last_paid_opt_in_at - synced_at))) >= 2     -- not a B5 now()-stamp
  AND (
    raw->'lastAttributionSource'->>'fbc' IS NULL
    OR NOT (raw->'lastAttributionSource'->>'fbc' ~ '^fb\.\d+\.\d+\.')
    OR to_timestamp((split_part(raw->'lastAttributionSource'->>'fbc', '.', 3))::bigint / 1000.0)
       < last_paid_opt_in_at - interval '7 days'
  );
```

Each hit is a phantom-re-opt-in CANDIDATE: a workflow likely re-dated an old lead into the current window. WARN (not BLOCKER - a genuine re-opt-in through a UTM-less path can look identical); list rows with GHL deep links in vault mode, count-only in Slack. Scope to `last_paid_opt_in_at` within the last 14 days to keep the queue current. Root cause class: [api/ads/_optin-timestamp.ts](api/ads/_optin-timestamp.ts) `resolveReOptInDate` rung 2 accepts any `dateUpdated > priorAt && <= now`. Forward fix (tracked as audit F23): rung 2 should require fresh-event corroboration in code; until then B6 is the data-side detector.

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

Sources expected: `meta_insights:campaign`, `meta_insights:adset`, `meta_insights:ad`, `meta_structure`, `orchestrator` (all 7 clients); `ghl_conversions` (the 4 GHL clients); `meta_leadforms` (mustache-painting, peach-paint-co, queen-consultancy); `calendly` (queen-consultancy). `hyros` is no longer expected; if it appears, it's residual log data from before Part 11.

### Most-recent paid event (sanity)

```sql
SELECT MAX(last_paid_opt_in_at) AS latest_lead    FROM ads_paid_leads     WHERE client_id = $client_id;
SELECT MAX(booked_at)            AS latest_booking FROM ads_paid_bookings  WHERE client_id = $client_id;
```

---

## Required endpoint replays

All endpoint calls use `Authorization: Bearer ${AUDIT_TOKEN}`. Auth bypass lives in [api/_db.ts:120-130 `requireSession()`](api/_db.ts#L120) (service-auth path: if `Authorization` header matches `AUDIT_TOKEN`, return a synthetic internal session). If the deployed code lacks this bypass, every replay returns `401` and Andy halts ORBIT-E with a bootstrap note.

```
GET {origin}/api/ads/overview?date_start=YYYY-MM-DD&date_end=YYYY-MM-DD
GET {origin}/api/ads/audit?date_start=...&date_end=...
GET {origin}/api/ads/drilldown/campaigns?client_id=...&date_start=...&date_end=...
GET {origin}/api/ads/drilldown/adsets?client_id=...&campaign_id=...&date_start=...&date_end=...
GET {origin}/api/ads/drilldown/adsets-all?client_id=...&date_start=...&date_end=...
GET {origin}/api/ads/drilldown/ad?client_id=...&adset_id=...&date_start=...&date_end=...
GET {origin}/api/ads/best-ads?date_start=...&date_end=...&min_spend=0   # ORBIT-I1
GET {origin}/api/ads/contacts/list?client_id=...&date_start=...&date_end=...&booked=yes&limit=250   # ORBIT-I3 (rows.length vs overview paid_booked_calls)
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
| ORBIT-B1 | BLOCKER | GHL ↔ Neon (4 GHL clients) | Paid lead counted-UNION count equality |
| ORBIT-B2 | BLOCKER | Golden rule grep | No `created_at`/`dateAdded`/`first_paid_opt_in_at` in window filters |
| ORBIT-B3 | BLOCKER | GHL ↔ Neon (4 GHL clients) | Re-opt-in survives: contact with `dateAdded` < window_start but `last_paid_opt_in_at` in window appears in Neon |
| ORBIT-B5 | BLOCKER/WARN | Neon writer, all clients | Opt-in dated by the EVENT not the sync clock: a `now()`-stamp (`\|opt_in - synced_at\| < 2s`) must corroborate a real event timestamp (fbc click time / `dateUpdated`) on the same calendar day. BLOCKER on different-day; WARN on same-day but >1h off |
| ORBIT-C1 | BLOCKER | GHL ↔ Neon (4 GHL clients) | Paid booked COUNTED-booking count equality vs walked GHL events (apply gates 4-5 on the walked side too) |
| ORBIT-C2 | BLOCKER | Display, all clients | CPBC = spend / counted paid_booked within ±5% of `/api/ads/overview` |
| ORBIT-D1 | DEPRECATED | Hyros, OBB | (Part 11) OBB no longer Hyros-backed; section retired |
| ORBIT-D2 | DEPRECATED | Hyros, OBB | (Part 11) Same - count now sourced from Neon under B/C |
| ORBIT-D3 | DEPRECATED | Hyros, OBB | (Part 11) HYROS_KEY_OBB env unused; advisory retired |
| ORBIT-E1 | BLOCKER | API ↔ Neon | Per-client spend/impressions/clicks exact match to Neon rollup |
| ORBIT-E2 | BLOCKER | API ↔ Neon | Per-client paid_leads / paid_booked_calls exact match to the counted B/C ground truth |
| ORBIT-E3 | BLOCKER | API ↔ Neon | CPL/CPBC recomputed within ±0.5% / ±5% |
| ORBIT-E4 | BLOCKER | Cross-client | `totals.*` == SUM(`clients.*.*`), exact, all fields |
| ORBIT-E5 | INFO    | Cross-client | 1:1 CAD/USD blend (Phase 4 = live FX) |
| ORBIT-F1 | BLOCKER | Drill-down | Meta `level=adset` ↔ Orbit drilldown spend/impr/clicks, ±5% |
| ORBIT-F2 | BLOCKER | Drill-down | SUM(per-adset paid_leads) == client total, no orphan ads |
| ORBIT-F3 | BLOCKER | Drill-down | SUM(per-adset paid_booked_calls) == client total |
| ORBIT-G1 | BLOCKER | Sync freshness | Each (client, expected source) has row in `ads_sync_log` within 24h with `ok = true` |
| ORBIT-G2 | WARN    | Sync freshness | Latest `last_paid_opt_in_at` per client within 48h when window spend > 0 |
| ORBIT-G3 | WARN    | Sync freshness | `ads_clients_config.token_expires_at` > 14 days out per client |
| ORBIT-G4 | WARN    | Latency | `/api/ads/overview` response time < 5s |
| ORBIT-G5 | WARN    | Latency | `/api/ads/drilldown/*` per-call response time < 10s |
| ORBIT-G6 | WARN    | Latency | `/api/ads/audit` response time < 30s |
| ORBIT-G7 | BLOCKER | Latency | No endpoint times out (>60s = Vercel function ceiling hit) |
| ORBIT-H1 | BLOCKER | Code-static | Broader sweep of B2: no banned column references anywhere `ads_paid_leads` is queried |
| ORBIT-H2 | WARN    | Code-static | No bare `YYYY-MM-DD` strings into Meta Graph or drill-down SQL without `clientWindow(timezone, ...)` |
| ORBIT-H3 | WARN    | Code-static | `isLastTouchPaid()` defined exactly once in the repo (drift detector) |
| ORBIT-H4 | WARN    | Code drift | Cited code lines (checksums/code-anchors.json) hash unchanged. Regen via scripts/regen-baselines.sh after intentional changes. |
| ORBIT-H5 | WARN/BLOCKER | Schema drift | Tracked `ads_*` + `fmt_*` table blocks (checksums/schema-baseline.json) hash unchanged. BLOCKER if referenced column removed/renamed. |
| ORBIT-H6 | WARN    | Endpoint coverage | All `api/ads/*.ts` route files (excluding `_*.ts` helpers) appear in `known_endpoints` below or are explicitly skipped |
| ORBIT-I1 | BLOCKER | Per-ad surface | Best Ads (`/api/ads/best-ads`) shows non-zero conversions when the client has ad-attributable conversions in window; SUM(per-ad paid_leads) reconciles to the `meta_ad_id`-attributed subset |
| ORBIT-I2 | BLOCKER/WARN | Attribution writer | `meta_ad_id` population health: BLOCKER if `COUNT(meta_campaign_id) > 0` but `COUNT(meta_ad_id) = 0` per (client, table); WARN if non-zero but materially below campaign coverage |
| ORBIT-I3 | BLOCKER | Drill-in lists | LIVE `contacts/list.ts` response length reconciles with the LIVE overview KPI it expands (counted cohort): `booked=yes` rows == `paid_booked_calls` (modulo documented counts_as_separate cases); `booked=any` rows == `paid_leads`. Sides computed independently; Neon counted SQL is the referee only |
| ORBIT-J1 | BLOCKER | Booked Calls surface | PAID ⊆ ALL: every COUNTED booking (booked_at in window) exists in `ads_all_bookings`. Missing = `listCalendars()` skipped a paid calendar |
| ORBIT-J2 | BLOCKER | Booked Calls surface | Bucket math: `/api/ads/bookings/list?bucket=all` `counts.all == counts.paid + counts.other`, and counts match independent Neon derivation exactly |
| ORBIT-J3 | BLOCKER | Booked Calls surface | COUNTED bookings joined into `ads_all_bookings` == `/api/ads/overview` `paid_booked_calls` (per-appointment `counts.paid` may exceed it: non-counted rows display in the bucket by design) |
| ORBIT-J4 | WARN | Booked Calls triage | OTHER-bucket bookings carrying an ad signal (first OR last touch) - the morning "look through these" review queue. Vault: list ≤15/client w/ GHL link; Slack: count only |
| ORBIT-J5 | INFO | Booked Calls triage | Unreviewed booked-call backlog: in-window bookings with `review_status IS NULL`, split ALL vs OTHER |
| ORBIT-B6 | WARN | Neon writer, all clients | Rung-2 (`dateUpdated`) re-opt-in stamps require fresh-event corroboration: WARN when the parseable fbc click time is >7d older than the stamp or absent (phantom re-opt-in via workflow touch; the F23 class B5 cannot see). Appended 2026-06-10 |

Sections B and C apply to the **4 GHL-walker clients** (CG B2B, BuilderPro, OBB, Contractor Launch); B5/B6 data-side detectors apply to ALL clients with `ads_paid_leads` rows. Leadform clients (mustache-painting, peach-paint-co) and queen-consultancy have no GHL to walk - their writer-truth checks compare Neon against the stored raw payloads (`last_paid_opt_in_at == raw->>'created_time'`; queen `booked_at == raw->'event'->>'created_at'`).

ORBIT-J (added 2026-05-22) audits the Booked Calls (ALL / PAID / OTHER) tab + `ads_all_bookings` table + `/api/ads/bookings/list`. J1–J3 enforce correctness (PAID ⊆ ALL, bucket sum, KPI reconciliation) and run in both modes. J4–J5 are the deep morning triage queue Zander asked Andy to "look through" - OTHER-bucket calls that carry a paid signal but missed the confident set, plus the unreviewed backlog. Freshness is covered by ORBIT-G1 (the all-bookings sync runs inside `sync-conversions.ts`, source `ghl_conversions`). ORBIT-D is fully **DEPRECATED** - there is nothing for Andy to audit on the Hyros path because the dashboard no longer reads from it.

ORBIT-I (added 2026-05-21) enforces the working-MVP clause on the conversion surfaces downstream of the headline counts: the per-ad Best Ads tab (I1), the `meta_ad_id` writer health (I2), and the drill-in popovers/Contacts list (I3, added later on 2026-05-21 after the Booked-popover count-vs-list bug; rewritten 2026-06-10 to compare the counted cohort non-tautologically). It runs in **both** vault and `--slack` modes (a best-ads call + a handful of Neon counts; cheap, unlike per-adset ORBIT-F).

---

## Known endpoints (ORBIT-H6 catalog)

This list is the contract for ORBIT-H6. When a new file appears in `api/ads/*.ts` and isn't listed here, andy WARNs. Either add the new route to this list AND determine whether it warrants an explicit audit check, or mark it as `skipped: <reason>`.

Underscore-prefixed files (`api/ads/_*.ts`) are helper modules, not routes, so they're not subject to ORBIT-H6. 50 route files exist as of 2026-06-10.

| Route | Audited by | Notes |
|---|---|---|
| `api/ads/overview.ts` | ORBIT-A, E | per-client + cross-client KPI cards |
| `api/ads/audit.ts` | cross-validation only (not ground truth, per audit.ts:243-260 caveat) | in-app drift report |
| `api/ads/sync-meta-structure.ts` | ORBIT-G1 (freshness) + Slack alert on fail | Meta object metadata sync |
| `api/ads/sync-meta-insights.ts` | ORBIT-A, G1 + Slack alert on fail | Meta insights sync |
| `api/ads/sync-conversions.ts` | ORBIT-B, C, G1 + Slack alert on fail | GHL contacts + bookings walker (4 GHL clients) |
| `api/ads/cron-orchestrator.ts` | ORBIT-G1 + Slack alert on fail | structure + insights fan-out |
| `api/ads/drilldown/campaigns.ts` | ORBIT-F | per-campaign breakdown |
| `api/ads/drilldown/adsets.ts` | ORBIT-F | per-adset breakdown |
| `api/ads/drilldown/ads.ts` | ORBIT-F | per-ad list under an adset |
| `api/ads/drilldown/ad.ts` | ORBIT-F | single-ad detail |
| `api/ads/contacts/list.ts` | ORBIT-I3 | backs the Leads / Booked popovers + Contacts tab. Renders the cohort behind every clickable count, so it IS a conversion surface - its list MUST reconcile with the counted KPI (was wrongly skipped as a "convenience listing" pre-2026-05-21, which masked the Booked count-vs-popover bug; missed the counted migration in #208, the 2026-06-09 popover-ghost bug). |
| `api/ads/contacts/all.ts` | ORBIT-I3 | full-contacts view; renders attribution per contact, so it IS a conversion surface - its cohort MUST reconcile with the counted semantics for the same window/client like `contacts/list.ts` (cataloged 2026-05-21, H6). |
| `api/ads/contacts/[id].ts` | skipped (read-only convenience detail) | single contact |
| `api/ads/contacts/review.ts` | skipped (reviewer-state writer, no conversion attribution) | marks contacts reviewed/needs-review. NOTE: also the write path behind the Booked Calls review toggle (J4/J5 surface review state but don't write it). |
| `api/ads/bookings/list.ts` | ORBIT-J | Booked Calls (ALL/PAID/OTHER) tab. Reads `ads_all_bookings` joined to `ads_paid_bookings` + `ads_ghl_contacts`. PAID bucket IS a conversion surface (must reconcile with counted `paid_booked_calls`); ALL/OTHER are the triage queue. Cataloged 2026-05-22. |
| `api/ads/best-ads.ts` | ORBIT-I | cross-client best ads. Renders paid_leads/booked/CPL/CPBC per ad, so it IS a conversion surface (was wrongly skipped pre-2026-05-21). Keys on `meta_ad_id`. Counted semantics since #208. |
| `api/ads/drilldown/adsets-all.ts` | ORBIT-F | cross-campaign per-adset breakdown; per-adset leads/booked MUST reconcile with `paidConversionsByObject` the same way `drilldown/adsets.ts` does (cataloged 2026-05-21, H6). |
| `api/ads/drilldown/paused-ads-history.ts` | skipped (read-only historical status display, no conversion attribution) | paused-ad timeline |
| `api/ads/actions/meta.ts` | out of scope (write path, separate audit concern) | pause / resume / budget |
| `api/ads/actions/log.ts` | out of scope (audit log write) | write audit trail |
| `api/ads/sync-status.ts` | skipped (read-only sync state for the dashboard) | feeds the Last-sync badge + SyncNowButton polling |
| `api/ads/slack-client-weekly.ts` | skipped (Slack-only output, no Neon writes) | weekly client-facing Slack recap |
| `api/ads/slack-daily.ts` | skipped (Slack-only output, no Neon writes) | daily Moreway audit/perf/eod Slack posts; reads /overview + /audit, posts to Slack |
| `api/ads/sync-ghl-contacts.ts` | skipped (sync writer; freshness covered transitively by ORBIT-B/G1) | GHL contacts sync |
| `api/ads/cron-ghl-contacts.ts` | skipped (cron wrapper for sync-ghl-contacts) | scheduled GHL contacts fan-out |
| `api/ads/kpi-targets.ts` | skipped (config CRUD, no conversion attribution) | per-client KPI target storage |
| `api/ads/diagnose-meta-permissions.ts` | skipped (ops diagnostic, read-only) | Meta token/role debug |
| `api/ads/migrate-ghl-contacts.ts` | skipped (one-off migration) | backfill script |
| `api/ads/migrate-kpi-targets.ts` | skipped (one-off migration) | backfill script |
| `api/ads/migrate-kpi-overrides.ts` | skipped (one-off migration) | backfill script |
| `api/ads/migrate-paused-history.ts` | skipped (one-off migration) | backfill script |
| `api/ads/contacts/attribute.ts` | **CONVERSION-BEARING writer** (cataloged 2026-06-10) | manual attribution: WRITES `ads_paid_leads` + `ads_paid_bookings` rows with `raw._manual_override='true'`. Changes paid counts. KNOWN ISSUE (audit H1-a): stamps `lastPaidOptInAt = contact.date_added` (fallback now), mis-windowing re-opted old contacts. Mutation rows surface under the B-family checks; treat `_manual_override` rows as operator-authored. |
| `api/ads/contacts/exclusion.ts` | **CONVERSION-BEARING writer** (cataloged 2026-06-10) | sets `ads_ghl_contacts.excluded_from_metrics`; hard-excludes a contact from EVERY paid surface. Counted CTE honors it (gate 2). A new exclusion changes historical window counts - expect day-over-day KPI shifts when operators use it. |
| `api/ads/bookings/count-separate.ts` | **CONVERSION-BEARING writer** (cataloged 2026-06-10) | flips `ads_paid_bookings.counts_as_separate`; changes paid_booked counting (counted CTE gate 3). |
| `api/ads/bookings/promote.ts` | **CONVERSION-BEARING writer** (cataloged 2026-06-10) | promotes OTHER-bucket bookings into `ads_paid_bookings` (and demotes); promoted rows carry `_manual_override='true'` so they bypass the click-recency gate by design. |
| `api/ads/sync-meta-leadforms.ts` | **CONVERSION WRITER** - ORBIT-G1 (source `meta_leadforms`) + writer-truth check (cataloged 2026-06-10) | THE lead path for mustache-painting + peach-paint-co (and queen leads): writes `ads_paid_leads.last_paid_opt_in_at` from Meta leadform `created_time`. Writer invariant: `last_paid_opt_in_at == raw->>'created_time'`. |
| `api/ads/sync-calendly-bookings.ts` | **CONVERSION WRITER** - ORBIT-G1 (source `calendly`) + writer-truth check (cataloged 2026-06-10) | THE booking path for queen-consultancy: Calendly events → `ads_paid_bookings`, `booked_at = event.created_at`, `click_at` = matched lead opt-in time (so the recency gate passes). Writer invariant: `booked_at == raw->'event'->>'created_at'`; cancelled-status rows must not count. |
| `api/ads/slack-obb-update.ts` | **CONVERSION-BEARING display** (cataloged 2026-06-10) | client-facing daily/weekly OBB Slack post. KNOWN DRIFT (audit F03): reimplements leads/booked from retired Hyros walkers (cancelled calls + organic leads included), diverging from the dashboard definition; fix tracked separately. Until fixed, expect its numbers NOT to reconcile with overview - report as the known F03 finding, not a new regression. |
| `api/ads/slack-eod-sales.ts` | **CONVERSION-ADJACENT display** (cataloged 2026-06-10) | nightly booked/show/close counts to Slack; reads sales dispositions + booking counts. |
| `api/ads/slack-weekly-sales.ts` | **CONVERSION-BEARING display** (cataloged 2026-06-10) | weekly spend/leads/booked/CPBC/revenue/ROAS per client to Slack; must use the counted path. |
| `api/ads/triage-sweep.ts` | **CONVERSION-BEARING compute** (cataloged 2026-06-10) | computes 3-day CPL/CPBC red zones per ad and posts pause/keep cards that drive real Meta writes. Its CPL/CPBC math must match the counted semantics; decisions hang off it. |
| `api/ads/clients.ts` | skipped (ops: roster read for the UI) | cataloged 2026-06-10 |
| `api/ads/contacts/ads-list.ts` | skipped (ops: ad-picker roster, reads `ads_meta_structure` only) | cataloged 2026-06-10 |
| `api/ads/detect-new-clients.ts` | skipped (ops: auto-onboard detector) | cataloged 2026-06-10 |
| `api/ads/spend-controller-config.ts` | skipped (ops: config CRUD) | cataloged 2026-06-10 |
| `api/ads/cron-obb-spend-controller.ts` | skipped (ops: budget-proposal bot; proposes, never auto-applies) | cataloged 2026-06-10 |
| `api/ads/migrate-exclusion-columns.ts` | skipped (one-off migration) | cataloged 2026-06-10 |
| `api/ads/migrate-spend-controller-config.ts` | skipped (one-off migration) | cataloged 2026-06-10 |
| `api/ads/migrate-spend-proposals.ts` | skipped (one-off migration) | cataloged 2026-06-10 |
| `api/ads/triage-migrate.ts` | skipped (one-off migration) | cataloged 2026-06-10 |

Underscore-prefixed helpers (not routes; NEVER counted by ORBIT-H6). 16 as of 2026-06-10:
`_classify-health.ts`, `_client-roster.ts`, `_drilldown-sql.ts`, `_freshness.ts`, `_ghl-availability.ts`, `_ghl-direct.ts`, `_insights-window.ts`, `_meta-write.ts`, `_meta.ts`, `_onboard-client.ts`, `_optin-timestamp.ts`, `_reap-stale-sync.ts`, `_slack-alert.ts`, `_sources.ts`, `_spend-controller.ts`, `_spend-proposals.ts` (plus `api/_db.ts` one level up).

> **Outside-`api/ads/` scope note:** `api/formats/*` (Format Lab: `tracker.ts`, `ingest-catalog.ts`, `ingest-usage.ts`, `set-format.ts`, `migrate.ts`, added PR #218) reads `ads_*` tables READ-ONLY and writes only its own `fmt_catalog` / `fmt_usage` tables. It lives outside `api/ads/` so the H6 glob never sees it - this entry is the explicit acknowledgment. Treat as skipped (read-only on conversion tables); if a formats route ever WRITES an `ads_*` table, that is a finding.

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
| ORBIT-B6 rung-2 stamp without fresh corroboration | [api/ads/_optin-timestamp.ts](api/ads/_optin-timestamp.ts) `resolveReOptInDate` rung 2 (accepts any `dateUpdated > priorAt`); triggering writer is usually a GHL workflow/bulk edit bumping `dateUpdated` (F23 class) |
| ORBIT-C booked count off | [api/ads/sync-conversions.ts](api/ads/sync-conversions.ts), calendar filter, booking_source filter; read-side: the counted gates in [api/ads/_drilldown-sql.ts:49-133](api/ads/_drilldown-sql.ts#L49) |
| ORBIT-D (DEPRECATED post-Part-11) | n/a - Hyros no longer in dashboard data path |
| ORBIT-E aggregation off | [api/ads/overview.ts:224-245](api/ads/overview.ts#L224), cross-client SUM logic |
| ORBIT-E CPL/CPBC off | [api/ads/overview.ts:220-221](api/ads/overview.ts#L220), null-safe formulas |
| ORBIT-F orphan ads | [api/ads/sync-meta-structure.ts](api/ads/sync-meta-structure.ts), missing `parent_id` / `campaign_id` on ad rows |
| ORBIT-G stale | [api/ads/cron-orchestrator.ts](api/ads/cron-orchestrator.ts) + cron schedule in `vercel.json`; leadform/calendly staleness: [api/ads/sync-meta-leadforms.ts](api/ads/sync-meta-leadforms.ts) / [api/ads/sync-calendly-bookings.ts](api/ads/sync-calendly-bookings.ts) |
| ORBIT-H1 code-static fail | the grep hit's file:line |
| ORBIT-H4 code-anchor drift | the cited anchor's invariants_ref + the file:line in code-anchors.json |
| ORBIT-H5 schema drift | [drizzle/schema.ts](drizzle/schema.ts) at the cited line range |
| ORBIT-H6 uncatalogued endpoint | the `api/ads/*.ts` file path returned by the grep |
| ORBIT-G4-G7 latency | endpoint config in `vercel.json` (`maxDuration`), Neon pool exhaustion, or upstream Meta/GHL slowness inside the endpoint |
| ORBIT-I `meta_ad_id` all-zero / Best Ads shows 0 | [api/ads/sync-conversions.ts](api/ads/sync-conversions.ts) `resolveMetaIds` / `adByName` - ad-name → ad-id backfill dropped. Read path [api/ads/best-ads.ts](api/ads/best-ads.ts) keys on `meta_ad_id` with no true-total fallback. |
| ORBIT-I3 popover/list count ≠ the KPI it expands | [api/ads/contacts/list.ts](api/ads/contacts/list.ts) cohort SQL diverged from the counted semantics ([api/ads/_drilldown-sql.ts](api/ads/_drilldown-sql.ts) `countedPaidBookings`): leads window on `last_paid_opt_in_at`, bookings MUST be COUNTED bookings windowed on `booked_at` (primary anchor + counts_as_separate + click gate + exclusions); "booked" cohort is counted-bookers-in-window, not EXISTS-any-booking and not raw rows (the #208 partial-migration bug). |
| ORBIT-J1 paid booking missing from `ads_all_bookings` | [api/ads/sync-conversions.ts](api/ads/sync-conversions.ts) `listCalendars()` / `syncOneClientAllBookings` - all-calendars walk didn't return the paid calendar (wrong `Version` header, archived calendar, or calendars-API outage → `calendars.size === 0` warn). |
| ORBIT-J2 bucket counts wrong / don't sum | [api/ads/bookings/list.ts](api/ads/bookings/list.ts) - `pb.appointment_id IS NULL/NOT NULL` bucket join or the `COUNT(*) FILTER` counts query drifted. |
| ORBIT-J3 counted PAID ≠ paid_booked KPI | [api/ads/bookings/list.ts](api/ads/bookings/list.ts) counted join, or upstream `ads_paid_bookings`/gates diverged from ORBIT-C (fix ORBIT-C first). |

---

## Local mode vs --slack mode scope

Andy runs in two modes, both invoking the same skill body. Section scope differs:

| Section | Local (vault) | `--slack` (Slack post) |
|---|---|---|
| ORBIT-A (Meta ↔ Neon) | RUN | RUN |
| ORBIT-B (GHL ↔ Neon, 4 GHL clients; B5/B6 all clients) | RUN | RUN |
| ORBIT-C (Booked, 4 GHL clients; counted read-side all clients) | RUN | RUN |
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
