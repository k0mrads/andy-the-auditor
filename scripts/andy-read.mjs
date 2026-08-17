#!/usr/bin/env node
// Andy read-side collector. Runs all Neon queries for the window across 7 clients
// and prints one JSON blob. Window dates passed as argv[2]=start argv[3]=end (YYYY-MM-DD).
import { readFileSync } from 'node:fs';
import { neon } from '/Users/zander/Claude Code/Moreway/Moreway | Tasks/node_modules/@neondatabase/serverless/index.mjs';

function loadEnv(path){const raw=readFileSync(path,'utf8');for(const line of raw.split('\n')){const m=line.match(/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)\s*$/);if(!m)continue;let v=m[2];if((v.startsWith('"')&&v.endsWith('"'))||(v.startsWith("'")&&v.endsWith("'")))v=v.slice(1,-1);if(!(m[1] in process.env))process.env[m[1]]=v;}}
loadEnv('/Users/zander/Claude Code/Moreway/Moreway | Tasks/.env');
const sql = neon(process.env.DATABASE_URL);
const DS = process.argv[2], DE = process.argv[3];

// Roster synced to live ads_clients_config (enabled=true) on 2026-08-16.
// queen-consultancy now enabled=false -> dropped. ac-guy-near-me added (B2C leadform).
// cals[] reflect live ghl_paid_calendar_ids (BP +h7zdc, CG +WewAu +aWr0I) though the
// read-side Neon queries do not use them (ads_paid_bookings is pre-filtered by the sync).
const CLIENTS = {
  'ac-guy-near-me':{tz:'America/New_York',ghl:false,leadform:true},
  'builderpro':{tz:'America/Los_Angeles',ghl:true,cals:['O8gu806gdTKPAzC7eVxs','9LDJxs6du790AQ3l90PI','h7zdcLFdsWVoLZGG8Rmg']},
  'caregenius-b2b':{tz:'America/New_York',ghl:true,cals:['BcrVAYO1f55PnzJfZpQE','fykIVqFyF0VDTvMxhjTX','xbEpiw5G1HXrqdT76TD5','03t4uqmxqh8kHMfnIg5W','WewAuH3LXZ5dk3NNQV1y','aWr0IM5s7DYKMwoiLqkH']},
  'contractor-launch':{tz:'America/Chicago',ghl:true,cals:['dHorq0xLp27jznCt5r5Z','p7teuNzlEAQhM9rTsr0P']},
  'mustache-painting':{tz:'America/New_York',ghl:false,leadform:true},
  'obb':{tz:'America/New_York',ghl:true,cals:['ClJ06JUJICgDCoELfn9A','1FlpwUCCzC52Zt9y6cr2','KtiOSC0uuSUbEyt3Ikpd']},
  'occupancy-partners':{tz:'America/New_York',ghl:true,cals:['wyhBXhBWf6PokaZjujLB','BOO366IfVoNVzk8OEtOP','2oOJbhE0x01KXYKI1Fbs']},
  'peach-paint-co':{tz:'America/New_York',ghl:false,leadform:true},
};

// counted_bookings CTE text for a client (booked window applied by caller)
function cbCTE(cid){return `WITH counted_bookings AS (
  SELECT cpb.* FROM (
    SELECT pb.*, MIN(pb.booked_at) OVER (PARTITION BY pb.contact_id) AS first_counted_booked_at
    FROM ads_paid_bookings pb
    WHERE pb.client_id = '${cid}'
      AND ((pb.click_at IS NOT NULL AND pb.click_at >= pb.booked_at - interval '28 days' AND pb.click_at <= pb.booked_at + interval '1 day')
           OR COALESCE(pb.raw->>'_manual_override','')='true')
      AND NOT EXISTS (SELECT 1 FROM ads_ghl_contacts gex WHERE gex.client_id = pb.client_id AND gex.contact_id = pb.contact_id AND gex.excluded_from_metrics = true)
  ) cpb WHERE cpb.booked_at = cpb.first_counted_booked_at OR cpb.counts_as_separate = true )`;}

const out = {window:{DS,DE}, clients:{}, mutations:{}};

for (const [cid,cfg] of Object.entries(CLIENTS)) {
  const tz = cfg.tz;
  const ws = `('${DS}'::timestamp AT TIME ZONE '${tz}')`;      // window start instant
  const we = `(('${DE}'::date + 1)::timestamp AT TIME ZONE '${tz}')`; // exclusive end (next midnight)
  const c = {};

  // spend rollup
  c.spend = (await sql(`SELECT COALESCE(SUM(spend),0)::numeric AS spend, COALESCE(SUM(impressions),0)::bigint AS impressions, COALESCE(SUM(clicks),0)::bigint AS clicks FROM ads_meta_insights WHERE client_id='${cid}' AND level='campaign' AND date_start >= '${DS}' AND date_start <= '${DE}'`))[0];

  // counted paid_leads UNION
  c.paid_leads = (await sql(`${cbCTE(cid)}
    SELECT COUNT(DISTINCT contact_id)::int AS n FROM (
      SELECT contact_id FROM ads_paid_leads WHERE client_id='${cid}'
        AND last_paid_opt_in_at >= ${ws} AND last_paid_opt_in_at < ${we}
        AND NOT EXISTS (SELECT 1 FROM ads_ghl_contacts gex WHERE gex.client_id=ads_paid_leads.client_id AND gex.contact_id=ads_paid_leads.contact_id AND gex.excluded_from_metrics=true)
      UNION
      SELECT contact_id FROM counted_bookings WHERE booked_at >= ${ws} AND booked_at < ${we}
    ) u`))[0].n;

  // counted paid_booked
  c.paid_booked = (await sql(`${cbCTE(cid)} SELECT COUNT(*)::int AS n FROM counted_bookings WHERE booked_at >= ${ws} AND booked_at < ${we}`))[0].n;

  // raw plain lead rowcount (diagnostic)
  c.plain_leads = (await sql(`SELECT COUNT(*)::int AS n FROM ads_paid_leads WHERE client_id='${cid}' AND last_paid_opt_in_at >= ${ws} AND last_paid_opt_in_at < ${we}`))[0].n;
  c.raw_bookings = (await sql(`SELECT COUNT(*)::int AS n FROM ads_paid_bookings WHERE client_id='${cid}' AND booked_at >= ${ws} AND booked_at < ${we}`))[0].n;

  // meta_ad_id health both tables
  c.i2_leads = (await sql(`SELECT COUNT(*)::int total, COUNT(meta_campaign_id)::int has_campaign, COUNT(meta_ad_id)::int has_ad FROM ads_paid_leads WHERE client_id='${cid}'`))[0];
  c.i2_bookings = (await sql(`SELECT COUNT(*)::int total, COUNT(meta_campaign_id)::int has_campaign, COUNT(meta_ad_id)::int has_ad FROM ads_paid_bookings WHERE client_id='${cid}'`))[0];
  // in-window ad-attributed leads (I1)
  c.ad_attr_leads = (await sql(`SELECT COUNT(DISTINCT contact_id)::int n FROM ads_paid_leads WHERE client_id='${cid}' AND meta_ad_id IS NOT NULL AND last_paid_opt_in_at >= ${ws} AND last_paid_opt_in_at < ${we}`))[0].n;

  // latest paid events
  c.latest_lead = (await sql(`SELECT MAX(last_paid_opt_in_at) m FROM ads_paid_leads WHERE client_id='${cid}'`))[0].m;
  c.latest_booking = (await sql(`SELECT MAX(booked_at) m FROM ads_paid_bookings WHERE client_id='${cid}'`))[0].m;

  // B5 detector: now()-stamp on wrong calendar day
  c.b5 = await sql(`SELECT contact_id, last_paid_opt_in_at, raw->>'dateUpdated' date_updated, raw->'lastAttributionSource'->>'fbc' fbc
    FROM ads_paid_leads WHERE client_id='${cid}'
      AND ABS(EXTRACT(EPOCH FROM (last_paid_opt_in_at - synced_at))) < 2
      AND raw->>'dateUpdated' IS NOT NULL
      AND (last_paid_opt_in_at AT TIME ZONE '${tz}')::date <> ((raw->>'dateUpdated')::timestamptz AT TIME ZONE '${tz}')::date`);

  // B6 detector: rung-2 stamp, fbc >7d stale or missing, stamp within last 14d
  c.b6 = await sql(`SELECT contact_id, last_paid_opt_in_at, raw->>'dateUpdated' date_updated,
       raw->'lastAttributionSource'->>'fbc' fbc,
       raw->'lastAttributionSource'->>'sessionSource' last_session,
       raw->'attributionSource'->>'sessionSource' first_session
    FROM ads_paid_leads WHERE client_id='${cid}'
      AND raw->>'dateUpdated' IS NOT NULL
      AND ABS(EXTRACT(EPOCH FROM (last_paid_opt_in_at - (raw->>'dateUpdated')::timestamptz))) < 2
      AND ABS(EXTRACT(EPOCH FROM (last_paid_opt_in_at - synced_at))) >= 2
      AND last_paid_opt_in_at >= now() - interval '14 days'
      AND (raw->'lastAttributionSource'->>'fbc' IS NULL
           OR NOT (raw->'lastAttributionSource'->>'fbc' ~ '^fb\\.[0-9]+\\.[0-9]+\\.')
           OR to_timestamp((split_part(raw->'lastAttributionSource'->>'fbc','.',3))::bigint/1000.0) < last_paid_opt_in_at - interval '7 days')`);

  // sync freshness
  c.sync = await sql(`SELECT source, MAX(started_at) last_started, MAX(finished_at) last_finished, bool_and(ok) last_ok,
      (SELECT ok FROM ads_sync_log s2 WHERE s2.client_id='${cid}' AND s2.source=s.source ORDER BY started_at DESC LIMIT 1) latest_ok
    FROM ads_sync_log s WHERE client_id='${cid}' GROUP BY source ORDER BY source`);

  if (cfg.leadform) {
    c.leadform_bad = await sql(`SELECT contact_id, last_paid_opt_in_at, raw->>'created_time' created_time FROM ads_paid_leads WHERE client_id='${cid}' AND (raw->>'created_time' IS NULL OR ABS(EXTRACT(EPOCH FROM (last_paid_opt_in_at - (raw->>'created_time')::timestamptz))) > 1) LIMIT 20`);
    c.leadform_dupcount = (await sql(`SELECT COUNT(*)::int n FROM (SELECT LOWER(COALESCE(raw->>'email','')) em FROM ads_paid_leads WHERE client_id='${cid}' AND COALESCE(raw->>'email','')<>'' GROUP BY 1 HAVING COUNT(DISTINCT contact_id)>1) d`))[0].n;
  }
  if (cfg.calendly) {
    c.cal_bad_date = await sql(`SELECT appointment_id, booked_at, raw->'event'->>'created_at' ec FROM ads_paid_bookings WHERE client_id='${cid}' AND (raw->'event'->>'created_at' IS NULL OR ABS(EXTRACT(EPOCH FROM (booked_at - (raw->'event'->>'created_at')::timestamptz))) > 1) LIMIT 20`);
    c.cal_cancelled = (await sql(`${cbCTE(cid)} SELECT COUNT(*)::int n FROM counted_bookings WHERE LOWER(COALESCE(raw->'event'->>'status','')) IN ('canceled','cancelled')`))[0].n;
    c.cal_synthetic = (await sql(`SELECT COUNT(*)::int n FROM ads_paid_bookings WHERE client_id='${cid}' AND contact_id LIKE 'cal:%'`))[0].n;
  }

  if (cfg.ghl) {
    // J2 bucket math
    c.jbuckets = (await sql(`SELECT COUNT(*)::int all_count,
        COUNT(*) FILTER (WHERE pb.appointment_id IS NOT NULL AND COALESCE(g.excluded_from_metrics,false)=false)::int paid_count,
        COUNT(*) FILTER (WHERE pb.appointment_id IS NULL AND COALESCE(g.excluded_from_metrics,false)=false)::int other_count,
        COUNT(*) FILTER (WHERE COALESCE(g.excluded_from_metrics,false)=true)::int excluded_count
      FROM ads_all_bookings ab
      LEFT JOIN ads_paid_bookings pb ON pb.client_id=ab.client_id AND pb.appointment_id=ab.appointment_id
        AND ((pb.click_at IS NOT NULL AND pb.click_at >= pb.booked_at - interval '28 days' AND pb.click_at <= pb.booked_at + interval '1 day') OR COALESCE(pb.raw->>'_manual_override','')='true')
      LEFT JOIN ads_ghl_contacts g ON g.client_id=ab.client_id AND g.contact_id=ab.contact_id
      WHERE ab.client_id='${cid}' AND ab.booked_at >= ${ws} AND ab.booked_at < ${we}`))[0];
    // J1 PAID subset ALL
    c.j1_missing = await sql(`${cbCTE(cid)}
      SELECT cb.appointment_id, cb.contact_id, cb.calendar_id, cb.booked_at FROM counted_bookings cb
      LEFT JOIN ads_all_bookings ab ON ab.client_id=cb.client_id AND ab.appointment_id=cb.appointment_id
      WHERE cb.booked_at >= ${ws} AND cb.booked_at < ${we} AND ab.appointment_id IS NULL`);
    // J3 counted joined into all
    c.j3_counted = (await sql(`${cbCTE(cid)} SELECT COUNT(*)::int n FROM counted_bookings cb JOIN ads_all_bookings ab ON ab.client_id=cb.client_id AND ab.appointment_id=cb.appointment_id WHERE cb.booked_at >= ${ws} AND cb.booked_at < ${we}`))[0].n;
    // J4 candidates
    c.j4 = await sql(`SELECT ab.appointment_id, ab.contact_id, ab.calendar_name, ab.booked_at, g.full_name, g.email, g.first_utm_source, g.last_utm_source, g.last_fbclid, g.review_status
      FROM ads_all_bookings ab
      LEFT JOIN ads_paid_bookings pb ON pb.client_id=ab.client_id AND pb.appointment_id=ab.appointment_id
      LEFT JOIN ads_ghl_contacts g ON g.client_id=ab.client_id AND g.contact_id=ab.contact_id
      WHERE ab.client_id='${cid}' AND ab.booked_at >= ${ws} AND ab.booked_at < ${we}
        AND pb.appointment_id IS NULL AND g.review_status IS NULL
        AND (LOWER(COALESCE(g.last_utm_source,'')) IN ('facebook','instagram','fb','ig','meta')
             OR LOWER(COALESCE(g.first_utm_source,'')) IN ('facebook','instagram','fb','ig','meta')
             OR g.last_fbclid IS NOT NULL)
      ORDER BY ab.booked_at DESC LIMIT 15`);
    // J5 backlog
    c.j5 = (await sql(`SELECT COUNT(*)::int all_unreviewed, COUNT(*) FILTER (WHERE pb.appointment_id IS NULL)::int other_unreviewed
      FROM ads_all_bookings ab
      LEFT JOIN ads_paid_bookings pb ON pb.client_id=ab.client_id AND pb.appointment_id=ab.appointment_id
      LEFT JOIN ads_ghl_contacts g ON g.client_id=ab.client_id AND g.contact_id=ab.contact_id
      WHERE ab.client_id='${cid}' AND ab.booked_at >= ${ws} AND ab.booked_at < ${we} AND g.review_status IS NULL`))[0];
  }
  out.clients[cid] = c;
}

// MUT-1 global sets
out.mutations.mo_leads = await sql(`SELECT client_id, contact_id FROM ads_paid_leads WHERE raw->>'_manual_override'='true' ORDER BY 1,2`);
out.mutations.mo_bookings = await sql(`SELECT client_id, appointment_id FROM ads_paid_bookings WHERE raw->>'_manual_override'='true' ORDER BY 1,2`);
out.mutations.excluded = await sql(`SELECT client_id, contact_id FROM ads_ghl_contacts WHERE excluded_from_metrics=true ORDER BY 1,2`);
out.mutations.cas = await sql(`SELECT client_id, appointment_id FROM ads_paid_bookings WHERE counts_as_separate=true ORDER BY 1,2`);

process.stdout.write(JSON.stringify(out));
