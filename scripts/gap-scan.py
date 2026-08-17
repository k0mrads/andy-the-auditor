#!/usr/bin/env python3
"""
Andy the auditor - 90-day historical spend-sync gap scan.

For each enabled client:
  1. Query per-day spend from ads_meta_insights over the 90-day window.
  2. Call Meta Graph API /act_X/insights?level=account&time_increment=1 for the same window.
  3. Report every (client, date) where Meta > 0 but Neon = 0 (missing sync) or where
     Meta and Neon disagree by more than 5%.

Output: markdown summary to stdout + returns a structured dict for the caller to write.
"""
import os
import sys
import json
import datetime as dt
from decimal import Decimal
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

import psycopg2

WINDOW_DAYS = 90
META_API_VERSION = "v21.0"
DRIFT_TOLERANCE_PCT = 5.0  # >5% delta = warn; missing entirely = fail


def yesterday_ny() -> dt.date:
    # Approximate: use system UTC minus 5h then floor to date, then step back one day.
    # We're only using this for a calendar-date window boundary, not for exact tz math.
    now_utc = dt.datetime.utcnow()
    ny_now = now_utc - dt.timedelta(hours=5)
    return (ny_now - dt.timedelta(days=1)).date()


def fetch_neon_per_day(conn, client_id: str, start: dt.date, end: dt.date) -> dict:
    """Return {date: spend_decimal} rolled up from ads_meta_insights level='campaign'."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT date_start, COALESCE(SUM(spend), 0)::numeric AS spend
        FROM ads_meta_insights
        WHERE client_id = %s
          AND level = 'campaign'
          AND date_start >= %s
          AND date_start <= %s
        GROUP BY date_start
        ORDER BY date_start
        """,
        (client_id, start, end),
    )
    return {row[0]: Decimal(row[1]) for row in cur.fetchall()}


def fetch_meta_per_day(account_id: str, token: str, start: dt.date, end: dt.date) -> dict:
    """Return {date: spend_decimal} from Meta Graph API, using time_increment=1."""
    result = {}
    url_base = f"https://graph.facebook.com/{META_API_VERSION}/{account_id}/insights"
    params = {
        "level": "account",
        "fields": "spend,date_start,date_stop",
        "time_range": json.dumps({"since": start.isoformat(), "until": end.isoformat()}),
        "time_increment": 1,
        "limit": 500,
        "access_token": token,
    }
    url = url_base + "?" + urlencode(params)
    while url:
        req = Request(url, headers={"User-Agent": "andy-gap-scan/1.0"})
        try:
            with urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Meta API HTTP {e.code}: {err}") from e
        except URLError as e:
            raise RuntimeError(f"Meta API network error: {e}") from e

        for row in body.get("data", []):
            d = dt.date.fromisoformat(row["date_start"])
            spend = Decimal(str(row.get("spend", "0") or "0"))
            result[d] = spend
        url = body.get("paging", {}).get("next")
    return result


def scan_client(conn, client: dict, start: dt.date, end: dt.date) -> dict:
    token_env = client["meta_secret_name"]
    token = os.environ.get(token_env)
    if not token:
        return {
            "client_id": client["id"],
            "label": client["label"],
            "meta_account_id": client["meta_account_id"],
            "status": "SKIPPED",
            "reason": f"env var {token_env} not set",
            "gaps": [],
            "drifts": [],
            "neon_days_with_spend": 0,
            "meta_days_with_spend": 0,
        }

    neon = fetch_neon_per_day(conn, client["id"], start, end)
    try:
        meta = fetch_meta_per_day(client["meta_account_id"], token, start, end)
    except RuntimeError as e:
        return {
            "client_id": client["id"],
            "label": client["label"],
            "meta_account_id": client["meta_account_id"],
            "status": "META_ERROR",
            "reason": str(e)[:400],
            "gaps": [],
            "drifts": [],
            "neon_days_with_spend": sum(1 for v in neon.values() if v > 0),
            "meta_days_with_spend": 0,
        }

    gaps = []      # Meta > 0, Neon = 0 (or missing)
    drifts = []    # Both > 0 but off by more than tolerance
    all_dates = sorted(set(neon.keys()) | set(meta.keys()))
    for d in all_dates:
        n = neon.get(d, Decimal("0"))
        m = meta.get(d, Decimal("0"))
        if m > Decimal("0") and n == Decimal("0"):
            gaps.append({"date": d.isoformat(), "meta_spend": float(m), "neon_spend": 0.0})
        elif m > Decimal("0") and n > Decimal("0"):
            delta_pct = float(abs(m - n) / m * Decimal("100"))
            if delta_pct > DRIFT_TOLERANCE_PCT:
                drifts.append(
                    {
                        "date": d.isoformat(),
                        "meta_spend": float(m),
                        "neon_spend": float(n),
                        "delta_pct": round(delta_pct, 2),
                    }
                )

    neon_days = sum(1 for v in neon.values() if v > 0)
    meta_days = sum(1 for v in meta.values() if v > 0)

    if gaps:
        status = "GAPS_FOUND"
    elif drifts:
        status = "DRIFTS_ONLY"
    else:
        status = "CLEAN"

    return {
        "client_id": client["id"],
        "label": client["label"],
        "meta_account_id": client["meta_account_id"],
        "currency": client["currency"],
        "status": status,
        "gaps": gaps,
        "drifts": drifts,
        "neon_days_with_spend": neon_days,
        "meta_days_with_spend": meta_days,
    }


def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("BOOTSTRAP HALT: DATABASE_URL not set", file=sys.stderr)
        sys.exit(2)

    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, label, meta_account_id, currency, timezone, meta_secret_name
        FROM ads_clients_config
        WHERE enabled = true
        ORDER BY id
        """
    )
    clients = [
        dict(zip(["id", "label", "meta_account_id", "currency", "timezone", "meta_secret_name"], row))
        for row in cur.fetchall()
    ]

    end = yesterday_ny()
    start = end - dt.timedelta(days=WINDOW_DAYS - 1)

    print(f"# Gap scan window: {start} to {end} ({WINDOW_DAYS} days)", file=sys.stderr)
    print(f"# Clients: {len(clients)}", file=sys.stderr)

    reports = []
    for client in clients:
        print(f"# scanning {client['id']} ({client['meta_account_id']})...", file=sys.stderr)
        report = scan_client(conn, client, start, end)
        reports.append(report)
        gcount = len(report.get("gaps", []))
        dcount = len(report.get("drifts", []))
        print(
            f"#   status={report['status']} gaps={gcount} drifts={dcount} "
            f"neon_active_days={report.get('neon_days_with_spend',0)} "
            f"meta_active_days={report.get('meta_days_with_spend',0)}",
            file=sys.stderr,
        )

    out = {
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "window_days": WINDOW_DAYS,
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "tolerance_pct": DRIFT_TOLERANCE_PCT,
        "clients": reports,
    }
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
