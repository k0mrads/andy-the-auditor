#!/usr/bin/env python3
"""Read the LIVE client roster and derive each client's capabilities.

WHY THIS EXISTS
---------------
Andy carried three disagreeing hardcoded rosters: SKILL.md said "seven enabled
clients" (while also instructing "never hard-code it, read live from
ads_clients_config"), scripts/andy-read.mjs hardcoded a DIFFERENT eight-client
map with hardcoded calendar ids, and the live table had nine. Every run started
from a wrong map.

checks/registry.json routes on CAPABILITIES (has_ghl_walk, has_leadform_source,
has_calendly_source, ...), never on client names, so this is the one place the
roster is resolved. Add a client to Orbit and Andy picks it up; there is no list
to forget to update.

READ-ONLY. SELECT only. Never UPDATE, INSERT, DELETE or TRUNCATE -- Andy is
post-hoc, not transactional.

Usage:
    andy_roster.py                # human-readable table
    andy_roster.py --json         # machine form, what the collector consumes
    andy_roster.py --all          # include disabled clients
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

ORBIT_ENV = pathlib.Path.home() / "Claude Code/Moreway/Moreway | Tasks/.env"


def load_db_url() -> str:
    url = os.environ.get("ORBIT_READONLY_URL") or os.environ.get("DATABASE_URL")
    if url:
        return url
    if ORBIT_ENV.is_file():
        for line in ORBIT_ENV.read_text().splitlines():
            for key in ("ORBIT_READONLY_URL=", "DATABASE_URL="):
                if line.startswith(key):
                    return line[len(key):].strip().strip('"').strip("'")
    print("BOOTSTRAP HALT: no ORBIT_READONLY_URL or DATABASE_URL", file=sys.stderr)
    sys.exit(2)


def columns(cur) -> set[str]:
    cur.execute("""SELECT column_name FROM information_schema.columns
                   WHERE table_name = 'ads_clients_config'""")
    return {r[0] for r in cur.fetchall()}


def capabilities(row: dict, cols: set[str]) -> dict:
    """Derive registry capability flags from the columns that actually exist.

    There is NO `conversion_source` column. An earlier draft of this function
    read one, which would have made has_leadform_source permanently False and
    silently skipped LEADFORM-1 for every client -- precisely the class of
    silent-skip bug Andy exists to catch. The real discriminators, verified
    against the live table 2026-09-27:

        ghl_paid_calendar_ids non-empty -> GHL walker   (5 clients)
        meta_leads_page_id not null     -> Meta instant lead forms (3)
        hyros_secret_name not null      -> platform-routed truth (obb only)

    Calendly has no column at all; Queen Consultancy was its only user and is
    no longer enabled, so CAL-1 currently has no live subject. That is recorded
    explicitly rather than left to look like a passing check.
    """
    return {
        "has_ghl_walk": bool(row.get("ghl_paid_calendar_ids") or []),
        "has_leadform_source": row.get("meta_leads_page_id") is not None,
        # No column exists. Queen Consultancy was the only Calendly client and
        # is not in the enabled roster; revisit if one is onboarded.
        "has_calendly_source": False,
        # OBB's conversion truth differs per ad platform: Hyros for Facebook,
        # Neon/Orbit for Whop (Zander, 2026-09-27). Keyed on the Hyros secret
        # being configured, not on the client's name.
        "has_platform_routed_truth": row.get("hyros_secret_name") is not None,
    }


def fetch(include_disabled: bool) -> list[dict]:
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        print("BOOTSTRAP HALT: psycopg2 not installed", file=sys.stderr)
        sys.exit(2)

    conn = psycopg2.connect(load_db_url())
    try:
        cur = conn.cursor()
        cur.execute("SET statement_timeout = '15s'")
        cols = columns(cur)
        wanted = [c for c in (
            "id", "label", "enabled", "timezone", "currency", "meta_account_id",
            "meta_secret_name", "ghl_paid_calendar_ids", "ghl_api_secret_name",
            "ghl_location_id", "meta_leads_page_id", "hyros_secret_name",
            "token_expires_at",
        ) if c in cols]
        where = "" if include_disabled else " WHERE enabled = true"
        cur.execute(f"SELECT {', '.join(wanted)} FROM ads_clients_config{where} ORDER BY id")
        out = []
        for rec in cur.fetchall():
            row = dict(zip(wanted, rec))
            row["capabilities"] = capabilities(row, cols)
            out.append(row)
        return out
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--all", action="store_true", help="include disabled clients")
    a = ap.parse_args()

    roster = fetch(a.all)

    # Every client must have exactly ONE lead pipe. A client with none is
    # invisible to Orbit and its conversion checks must SKIP with a reason
    # rather than fail; a client with two means the schema has drifted.
    for c in roster:
        caps = c["capabilities"]
        pipes = [k for k in ("has_ghl_walk", "has_leadform_source", "has_calendly_source")
                 if caps[k]]
        c["lead_pipes"] = pipes
        if len(pipes) != 1 and c.get("enabled"):
            print(f"WARNING: {c.get('id')} has {len(pipes)} lead pipes ({pipes or 'none'}); "
                  f"conversion checks cannot be routed for it", file=sys.stderr)

    if a.json:
        print(json.dumps({"count": len(roster), "clients": roster}, indent=2, default=str))
        return 0

    print(f"{len(roster)} client(s){'' if a.all else ' (enabled only)'}\n")
    hdr = f"{'id':22s} {'enabled':7s} {'tz':20s} {'cur':4s} {'capabilities'}"
    print(hdr)
    print("-" * len(hdr))
    for c in roster:
        caps = ",".join(k for k, v in c["capabilities"].items() if v) or "-"
        print(f"{str(c.get('id')):22s} {str(c.get('enabled')):7s} "
              f"{str(c.get('timezone')):20s} {str(c.get('currency')):4s} {caps}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
