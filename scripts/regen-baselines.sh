#!/bin/bash
# regen-baselines.sh — regenerate ORBIT-H4 (code-anchor) and ORBIT-H5 (schema)
# baselines from the current state of the Moreway Orbit repo.
#
# Run this AFTER you intentionally change a piece of code that an Andy invariant
# cites verbatim (e.g., you fix a bug in `isLastTouchPaid` and update
# invariants/orbit.md to match). Andy compares against these baselines on each
# audit run; without regeneration, every audit after a deliberate change will
# false-WARN.
#
# Usage:
#   ~/.claude/skills/andy-the-auditor/scripts/regen-baselines.sh
#
# Writes:
#   ~/.claude/skills/andy-the-auditor/checksums/code-anchors.json
#   ~/.claude/skills/andy-the-auditor/checksums/schema-baseline.json
#
# Both files are committed to the andy-the-auditor repo so the morning routine
# uses the same baselines as the local launchd job.

set -euo pipefail

ORBIT_DIR="${ORBIT_DIR:-$HOME/Claude Code/Moreway/Moreway | Tasks}"
SKILL_DIR="${SKILL_DIR:-$HOME/.claude/skills/andy-the-auditor}"
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

if [ ! -d "$ORBIT_DIR" ]; then
  echo "ERROR: ORBIT_DIR not found at: $ORBIT_DIR" >&2
  echo "Set ORBIT_DIR env var if it lives elsewhere." >&2
  exit 1
fi

mkdir -p "$SKILL_DIR/checksums"

# ============================================================================
# CODE ANCHORS  (ORBIT-H4)
# ============================================================================
# Each anchor is a (file, line_start, line_end) tuple that maps to a section of
# invariants/orbit.md. If the code under any anchor changes, the invariants
# referencing it MUST be reviewed.
#
# Format below is one tuple per line:
#   anchor_id|relative_file|line_start|line_end|invariants_ref|purpose
# ============================================================================

ANCHORS=(
  "isLastTouchPaid-predicate|api/ads/_ghl-direct.ts|69|75|invariants/orbit.md#paid-attribution-rule|canonical isLastTouchPaid paid predicate"
  "paidConversionsByObject-union|api/ads/_drilldown-sql.ts|98|156|invariants/orbit.md#paid-attribution-rule|UNION semantics for paid_leads"
  "clientWindow-tz-builder|api/ads/_drilldown-sql.ts|54|60|invariants/orbit.md#window|DST-aware tz window builder"
  "cpl-cpbc-formulas|api/ads/overview.ts|208|209|invariants/orbit.md#orbit-e3|CPL and CPBC formulas"
  "overview-aggregation|api/ads/overview.ts|212|233|invariants/orbit.md#orbit-e4|cross-client SUM aggregation"
  "fetchHyrosCallsCount-predicate|api/ads/_sources.ts|123|150|invariants/orbit.md#orbit-d|Hyros paid Facebook predicate"
  "requireSession-audit-bypass|api/_db.ts|76|86|invariants/orbit.md#account-credentials|AUDIT_TOKEN bearer bypass"
  "audit-endpoint-conversion-shortcut|api/ads/audit.ts|240|258|invariants/orbit.md#orbit-b-coverage|ground_truth=dashboard caveat"
)

echo "{"                                                       >  "$SKILL_DIR/checksums/code-anchors.json.tmp"
echo "  \"version\": 1,"                                       >> "$SKILL_DIR/checksums/code-anchors.json.tmp"
echo "  \"generated_at\": \"$NOW\","                           >> "$SKILL_DIR/checksums/code-anchors.json.tmp"
echo "  \"anchors\": ["                                        >> "$SKILL_DIR/checksums/code-anchors.json.tmp"

LAST_IDX=$((${#ANCHORS[@]} - 1))
for IDX in "${!ANCHORS[@]}"; do
  IFS='|' read -r ID REL_FILE LSTART LEND INV_REF PURPOSE <<< "${ANCHORS[$IDX]}"
  FULL="$ORBIT_DIR/$REL_FILE"
  if [ ! -f "$FULL" ]; then
    echo "WARN: anchor file missing, skipping: $REL_FILE" >&2
    continue
  fi
  CONTENT="$(sed -n "${LSTART},${LEND}p" "$FULL")"
  HASH="$(printf '%s' "$CONTENT" | shasum -a 256 | awk '{print $1}')"

  COMMA=","
  [ "$IDX" -eq "$LAST_IDX" ] && COMMA=""

  printf '    {\n' >> "$SKILL_DIR/checksums/code-anchors.json.tmp"
  printf '      "id": "%s",\n' "$ID" >> "$SKILL_DIR/checksums/code-anchors.json.tmp"
  printf '      "file": "%s",\n' "$REL_FILE" >> "$SKILL_DIR/checksums/code-anchors.json.tmp"
  printf '      "line_start": %s,\n' "$LSTART" >> "$SKILL_DIR/checksums/code-anchors.json.tmp"
  printf '      "line_end": %s,\n' "$LEND" >> "$SKILL_DIR/checksums/code-anchors.json.tmp"
  printf '      "hash": "sha256:%s",\n' "$HASH" >> "$SKILL_DIR/checksums/code-anchors.json.tmp"
  printf '      "invariants_ref": "%s",\n' "$INV_REF" >> "$SKILL_DIR/checksums/code-anchors.json.tmp"
  printf '      "purpose": "%s"\n' "$PURPOSE" >> "$SKILL_DIR/checksums/code-anchors.json.tmp"
  printf '    }%s\n' "$COMMA" >> "$SKILL_DIR/checksums/code-anchors.json.tmp"
done

echo "  ]"                                                     >> "$SKILL_DIR/checksums/code-anchors.json.tmp"
echo "}"                                                       >> "$SKILL_DIR/checksums/code-anchors.json.tmp"

mv "$SKILL_DIR/checksums/code-anchors.json.tmp" "$SKILL_DIR/checksums/code-anchors.json"
echo "[regen] wrote $SKILL_DIR/checksums/code-anchors.json (${#ANCHORS[@]} anchors)"

# ============================================================================
# SCHEMA BASELINE  (ORBIT-H5)
# ============================================================================
# For each ads_* table Andy references, snapshot the column lines plus hash
# the entire table block. Andy diffs against this on each audit run.
# ============================================================================

SCHEMA="$ORBIT_DIR/drizzle/schema.ts"
if [ ! -f "$SCHEMA" ]; then
  echo "ERROR: drizzle/schema.ts not found at: $SCHEMA" >&2
  exit 1
fi

# Build a per-table block hash. The table block starts at the line containing
# `pgTable('TABLE_NAME'` and ends at the next line containing `);` at column 0
# (the closing of the pgTable() call). We extract that range and hash it.
TABLES=(
  "ads_clients_config"
  "ads_meta_structure"
  "ads_meta_insights"
  "ads_sync_log"
  "ads_paid_leads"
  "ads_paid_bookings"
  "ads_command_center_audit"
)

echo "{"                                                       >  "$SKILL_DIR/checksums/schema-baseline.json.tmp"
echo "  \"version\": 1,"                                       >> "$SKILL_DIR/checksums/schema-baseline.json.tmp"
echo "  \"generated_at\": \"$NOW\","                           >> "$SKILL_DIR/checksums/schema-baseline.json.tmp"
echo "  \"source\": \"drizzle/schema.ts\","                    >> "$SKILL_DIR/checksums/schema-baseline.json.tmp"
echo "  \"tables\": {"                                         >> "$SKILL_DIR/checksums/schema-baseline.json.tmp"

LAST_IDX=$((${#TABLES[@]} - 1))
for IDX in "${!TABLES[@]}"; do
  TABLE="${TABLES[$IDX]}"
  # Find pgTable('TABLE_NAME') whether single-line or multi-line. The table
  # name lives within 3 lines after a `pgTable(` open paren in schema.ts.
  LSTART=$(awk -v t="'${TABLE}'" '
    /pgTable\(/ { paren=NR }
    paren && index($0, t) && NR <= paren+3 { print paren; exit }
  ' "$SCHEMA")
  if [ -z "$LSTART" ]; then
    echo "WARN: table $TABLE not found in schema.ts, skipping" >&2
    continue
  fi
  # Find the first line after LSTART that closes the pgTable call. Two valid
  # closers exist depending on whether pgTable() has a 2nd-arg config callback:
  #   `});`  closes  pgTable('name', { ... });
  #   `);`   closes  pgTable('name', { ... }, (t) => ({...}));
  LEND=$(awk -v s="$LSTART" 'NR>s && /^\}?\);$/ {print NR; exit}' "$SCHEMA")
  if [ -z "$LEND" ]; then
    echo "WARN: table $TABLE block end not found, skipping" >&2
    continue
  fi
  BLOCK="$(sed -n "${LSTART},${LEND}p" "$SCHEMA")"
  HASH="$(printf '%s' "$BLOCK" | shasum -a 256 | awk '{print $1}')"
  # Extract column names: lines that contain a `: ` followed by a Drizzle type ctor
  COLUMNS=$(printf '%s' "$BLOCK" | grep -oE "[a-zA-Z_]+:\s+(text|integer|numeric|boolean|timestamp|date|uuid|jsonb)\(" | sed 's/:.*//' | sort -u | paste -sd ',' -)

  COMMA=","
  [ "$IDX" -eq "$LAST_IDX" ] && COMMA=""

  printf '    "%s": {\n' "$TABLE" >> "$SKILL_DIR/checksums/schema-baseline.json.tmp"
  printf '      "line_start": %s,\n' "$LSTART" >> "$SKILL_DIR/checksums/schema-baseline.json.tmp"
  printf '      "line_end": %s,\n' "$LEND" >> "$SKILL_DIR/checksums/schema-baseline.json.tmp"
  printf '      "hash": "sha256:%s",\n' "$HASH" >> "$SKILL_DIR/checksums/schema-baseline.json.tmp"
  printf '      "columns": "%s"\n' "$COLUMNS" >> "$SKILL_DIR/checksums/schema-baseline.json.tmp"
  printf '    }%s\n' "$COMMA" >> "$SKILL_DIR/checksums/schema-baseline.json.tmp"
done

echo "  }"                                                     >> "$SKILL_DIR/checksums/schema-baseline.json.tmp"
echo "}"                                                       >> "$SKILL_DIR/checksums/schema-baseline.json.tmp"

mv "$SKILL_DIR/checksums/schema-baseline.json.tmp" "$SKILL_DIR/checksums/schema-baseline.json"
echo "[regen] wrote $SKILL_DIR/checksums/schema-baseline.json (${#TABLES[@]} tables)"

echo ""
echo "[regen] Done. Commit the updated baselines:"
echo "  cd $SKILL_DIR && git add checksums/ && git commit -m 'chore: regen andy baselines'"
echo "  git push"
