#!/bin/bash
# regen-baselines.sh — regenerate ORBIT-H4 (code-anchor) and ORBIT-H5 (schema)
# baselines from the Moreway Orbit repo.
#
# Run this AFTER you intentionally change a piece of code that an Andy invariant
# cites verbatim (e.g., you fix a bug in `isLastTouchPaid` and update
# invariants/orbit.md to match). Andy compares against these baselines on each
# audit run; without regeneration, every audit after a deliberate change will
# false-WARN.
#
# 2026-06-10 rewrite (audit F39): anchors are now located DYNAMICALLY by
# grepping for the anchor function/expression, instead of hard-coded line
# numbers. The old hard-coded ranges were frozen at the 2026-05-20 layout, so
# running the old script against current code would have hashed the WRONG lines
# (e.g. _ghl-direct.ts:69-75 now sits inside getEffectiveLastTouch) and blessed
# garbage. Line numbers are still RECORDED in the output JSON (Andy's hash
# check needs them), but they are derived fresh on every regen.
#
# By default the baseline is generated against ORIGIN/MAIN (the deployed code),
# not the local working tree. Override with ORBIT_REF="" to use the working
# tree, or ORBIT_REF=<any-ref>.
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
ORBIT_REF="${ORBIT_REF-origin/main}"
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

if [ ! -d "$ORBIT_DIR" ]; then
  echo "ERROR: ORBIT_DIR not found at: $ORBIT_DIR" >&2
  echo "Set ORBIT_DIR env var if it lives elsewhere." >&2
  exit 1
fi

mkdir -p "$SKILL_DIR/checksums"

# ----------------------------------------------------------------------------
# Materialize source files (from ORBIT_REF via git show, or the working tree)
# into a temp dir so the rest of the script has one consistent code state.
# ----------------------------------------------------------------------------
WORKDIR="$(mktemp -d /tmp/andy-regen.XXXXXX)"
trap 'rm -rf "$WORKDIR"' EXIT

SOURCE_DESC="working-tree"
if [ -n "$ORBIT_REF" ]; then
  git -C "$ORBIT_DIR" fetch origin main --quiet 2>/dev/null || true
  if ! git -C "$ORBIT_DIR" rev-parse --verify --quiet "$ORBIT_REF" >/dev/null; then
    echo "ERROR: ref '$ORBIT_REF' not found in $ORBIT_DIR" >&2
    exit 1
  fi
  SOURCE_DESC="$ORBIT_REF@$(git -C "$ORBIT_DIR" rev-parse --short "$ORBIT_REF")"
fi

materialize() {
  # materialize <relative_file> -> echoes the materialized absolute path
  local rel="$1" out="$WORKDIR/$1"
  if [ -f "$out" ]; then echo "$out"; return 0; fi
  mkdir -p "$(dirname "$out")"
  if [ -n "$ORBIT_REF" ]; then
    git -C "$ORBIT_DIR" show "$ORBIT_REF:$rel" > "$out" 2>/dev/null || return 1
  else
    [ -f "$ORBIT_DIR/$rel" ] || return 1
    cp "$ORBIT_DIR/$rel" "$out"
  fi
  echo "$out"
}

# ============================================================================
# CODE ANCHORS  (ORBIT-H4)
# ============================================================================
# Each anchor maps a named piece of load-bearing code to a section of
# invariants/orbit.md. If the code under any anchor changes, the invariants
# referencing it MUST be reviewed.
#
# Format, one tuple per line:
#   anchor_id|relative_file|start_pattern|end_spec|invariants_ref|purpose
#
# start_pattern: FIXED STRING (grep -F). First matching line = line_start.
# end_spec, one of:
#   brace            -> first line AFTER line_start matching ^} (top-level close)
#   +N               -> line_start + N
#   until@PAT@N      -> first line >= line_start containing fixed string PAT, plus N
# ============================================================================

ANCHORS=(
  "isLastTouchPaid-predicate|api/ads/_ghl-direct.ts|export function isLastTouchPaid(|brace|invariants/orbit.md#paid-attribution-rule|canonical isLastTouchPaid paid predicate (first-or-last touchIsPaidMeta)"
  "touchIsPaidMeta-per-touch|api/ads/_ghl-direct.ts|export function touchIsPaidMeta(|brace|invariants/orbit.md#paid-attribution-rule|per-touch paid signal set (paid-social session / Meta entity id / paid medium; bare fbclid NOT sufficient)"
  "countedPaidBookings-cte|api/ads/_drilldown-sql.ts|export function countedPaidBookings(|brace|invariants/orbit.md#paid-attribution-rule|counted-bookings CTE (28d click gate + exclusions + primary anchor + counts_as_separate)"
  "paidConversionsByObject-union|api/ads/_drilldown-sql.ts|export function paidConversionsByObject(|brace|invariants/orbit.md#paid-attribution-rule|counted UNION semantics for paid_leads/paid_booked per meta object"
  "clientWindow-tz-builder|api/ads/_drilldown-sql.ts|export function clientWindow(|brace|invariants/orbit.md#window|DST-aware tz window builder"
  "cpl-cpbc-formulas|api/ads/overview.ts|c.cpl = counts.paidLeads|+1|invariants/orbit.md#orbit-e3|CPL and CPBC formulas"
  "overview-aggregation|api/ads/overview.ts|let spend = 0;|until@cpbc: anyCallsKnown@1|invariants/orbit.md#orbit-e4|cross-client SUM aggregation"
  "fetchGhlCountsFromNeon-union|api/ads/_sources.ts|async function fetchGhlCountsFromNeon(|brace|invariants/orbit.md#paid-attribution-rule|counted UNION for paid_leads + counted bookings count (overview KPI, all clients)"
  "requireSession-audit-bypass|api/_db.ts|const auditToken = process.env.AUDIT_TOKEN|until@expiresAt: new Date@2|invariants/orbit.md#account-credentials|AUDIT_TOKEN bearer bypass"
  "audit-endpoint-conversion-shortcut|api/ads/audit.ts|// Ground-truth side:|until@paid_booked_calls_check.ground_truth = @0|invariants/orbit.md#orbit-b-coverage|ground_truth=dashboard caveat"
)

resolve_range() {
  # resolve_range <file> <start_pattern> <end_spec>
  # echoes "LSTART LEND" or returns 1
  local file="$1" pat="$2" endspec="$3" lstart lend
  lstart=$(grep -nF -- "$pat" "$file" | head -1 | cut -d: -f1)
  [ -n "$lstart" ] || return 1
  case "$endspec" in
    brace)
      lend=$(awk -v s="$lstart" 'NR>s && /^}/ {print NR; exit}' "$file")
      ;;
    +*)
      lend=$((lstart + ${endspec#+}))
      ;;
    until@*)
      local body="${endspec#until@}"
      local upat="${body%@*}"
      local off="${body##*@}"
      local hit
      hit=$(awk -v s="$lstart" -v p="$upat" 'NR>=s && index($0, p) {print NR; exit}' "$file")
      [ -n "$hit" ] || return 1
      lend=$((hit + off))
      ;;
    *)
      echo "ERROR: unknown end_spec '$endspec'" >&2; return 1 ;;
  esac
  [ -n "$lend" ] || return 1
  echo "$lstart $lend"
}

echo "{"                                                       >  "$SKILL_DIR/checksums/code-anchors.json.tmp"
echo "  \"version\": 2,"                                       >> "$SKILL_DIR/checksums/code-anchors.json.tmp"
echo "  \"generated_at\": \"$NOW\","                           >> "$SKILL_DIR/checksums/code-anchors.json.tmp"
echo "  \"source_ref\": \"$SOURCE_DESC\","                     >> "$SKILL_DIR/checksums/code-anchors.json.tmp"
echo "  \"anchors\": ["                                        >> "$SKILL_DIR/checksums/code-anchors.json.tmp"

ANCHOR_FAILURES=0
LAST_IDX=$((${#ANCHORS[@]} - 1))
for IDX in "${!ANCHORS[@]}"; do
  IFS='|' read -r ID REL_FILE START_PAT END_SPEC INV_REF PURPOSE <<< "${ANCHORS[$IDX]}"
  FULL="$(materialize "$REL_FILE")" || { echo "ERROR: anchor file missing in $SOURCE_DESC: $REL_FILE" >&2; ANCHOR_FAILURES=$((ANCHOR_FAILURES+1)); continue; }
  RANGE="$(resolve_range "$FULL" "$START_PAT" "$END_SPEC")" || { echo "ERROR: anchor '$ID' pattern not found in $REL_FILE (pattern: $START_PAT)" >&2; ANCHOR_FAILURES=$((ANCHOR_FAILURES+1)); continue; }
  LSTART="${RANGE%% *}"; LEND="${RANGE##* }"
  CONTENT="$(sed -n "${LSTART},${LEND}p" "$FULL")"
  HASH="$(printf '%s' "$CONTENT" | shasum -a 256 | awk '{print $1}')"

  COMMA=","
  [ "$IDX" -eq "$LAST_IDX" ] && COMMA=""

  {
    printf '    {\n'
    printf '      "id": "%s",\n' "$ID"
    printf '      "file": "%s",\n' "$REL_FILE"
    printf '      "line_start": %s,\n' "$LSTART"
    printf '      "line_end": %s,\n' "$LEND"
    printf '      "start_pattern": "%s",\n' "$(printf '%s' "$START_PAT" | sed 's/\\/\\\\/g; s/"/\\"/g')"
    printf '      "end_spec": "%s",\n' "$END_SPEC"
    printf '      "hash": "sha256:%s",\n' "$HASH"
    printf '      "invariants_ref": "%s",\n' "$INV_REF"
    printf '      "purpose": "%s"\n' "$PURPOSE"
    printf '    }%s\n' "$COMMA"
  } >> "$SKILL_DIR/checksums/code-anchors.json.tmp"
  echo "[regen] anchor $ID -> $REL_FILE:$LSTART-$LEND"
done

echo "  ]"                                                     >> "$SKILL_DIR/checksums/code-anchors.json.tmp"
echo "}"                                                       >> "$SKILL_DIR/checksums/code-anchors.json.tmp"

if [ "$ANCHOR_FAILURES" -gt 0 ]; then
  echo "ERROR: $ANCHOR_FAILURES anchor(s) failed to resolve; NOT writing code-anchors.json" >&2
  rm -f "$SKILL_DIR/checksums/code-anchors.json.tmp"
  exit 1
fi

mv "$SKILL_DIR/checksums/code-anchors.json.tmp" "$SKILL_DIR/checksums/code-anchors.json"
echo "[regen] wrote $SKILL_DIR/checksums/code-anchors.json (${#ANCHORS[@]} anchors, source $SOURCE_DESC)"

# ============================================================================
# SCHEMA BASELINE  (ORBIT-H5)
# ============================================================================
# For each table Andy references, snapshot the column lines plus hash
# the entire table block. Andy diffs against this on each audit run.
# Block ranges are discovered dynamically (pgTable('name') ... closing ");"),
# so this half was always layout-safe.
# ============================================================================

SCHEMA="$(materialize "drizzle/schema.ts")" || { echo "ERROR: drizzle/schema.ts not found in $SOURCE_DESC" >&2; exit 1; }

TABLES=(
  "ads_clients_config"
  "ads_meta_structure"
  "ads_meta_insights"
  "ads_sync_log"
  "ads_paid_leads"
  "ads_paid_bookings"
  "ads_command_center_audit"
  "ads_ghl_contacts"
  "ads_all_bookings"
  "fmt_catalog"
  "fmt_usage"
)

echo "{"                                                       >  "$SKILL_DIR/checksums/schema-baseline.json.tmp"
echo "  \"version\": 2,"                                       >> "$SKILL_DIR/checksums/schema-baseline.json.tmp"
echo "  \"generated_at\": \"$NOW\","                           >> "$SKILL_DIR/checksums/schema-baseline.json.tmp"
echo "  \"source\": \"drizzle/schema.ts\","                    >> "$SKILL_DIR/checksums/schema-baseline.json.tmp"
echo "  \"source_ref\": \"$SOURCE_DESC\","                     >> "$SKILL_DIR/checksums/schema-baseline.json.tmp"
echo "  \"tables\": {"                                         >> "$SKILL_DIR/checksums/schema-baseline.json.tmp"

SCHEMA_FAILURES=0
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
    echo "ERROR: table $TABLE not found in schema.ts" >&2
    SCHEMA_FAILURES=$((SCHEMA_FAILURES+1))
    continue
  fi
  # First line after LSTART that closes the pgTable call:
  #   `});`  closes  pgTable('name', { ... });
  #   `);`   closes  pgTable('name', { ... }, (t) => ({...}));
  LEND=$(awk -v s="$LSTART" 'NR>s && /^\}?\);$/ {print NR; exit}' "$SCHEMA")
  if [ -z "$LEND" ]; then
    echo "ERROR: table $TABLE block end not found" >&2
    SCHEMA_FAILURES=$((SCHEMA_FAILURES+1))
    continue
  fi
  BLOCK="$(sed -n "${LSTART},${LEND}p" "$SCHEMA")"
  HASH="$(printf '%s' "$BLOCK" | shasum -a 256 | awk '{print $1}')"
  # Extract column names: lines that contain a `: ` followed by a Drizzle type ctor
  COLUMNS=$(printf '%s' "$BLOCK" | grep -oE "[a-zA-Z_]+:\s+(text|integer|numeric|boolean|timestamp|date|uuid|jsonb|serial|varchar)\(" | sed 's/:.*//' | sort -u | paste -sd ',' -)

  COMMA=","
  [ "$IDX" -eq "$LAST_IDX" ] && COMMA=""

  {
    printf '    "%s": {\n' "$TABLE"
    printf '      "line_start": %s,\n' "$LSTART"
    printf '      "line_end": %s,\n' "$LEND"
    printf '      "hash": "sha256:%s",\n' "$HASH"
    printf '      "columns": "%s"\n' "$COLUMNS"
    printf '    }%s\n' "$COMMA"
  } >> "$SKILL_DIR/checksums/schema-baseline.json.tmp"
  echo "[regen] table $TABLE -> schema.ts:$LSTART-$LEND"
done

if [ "$SCHEMA_FAILURES" -gt 0 ]; then
  echo "ERROR: $SCHEMA_FAILURES table(s) failed to resolve; NOT writing schema-baseline.json" >&2
  rm -f "$SKILL_DIR/checksums/schema-baseline.json.tmp"
  exit 1
fi

echo "  }"                                                     >> "$SKILL_DIR/checksums/schema-baseline.json.tmp"
echo "}"                                                       >> "$SKILL_DIR/checksums/schema-baseline.json.tmp"

mv "$SKILL_DIR/checksums/schema-baseline.json.tmp" "$SKILL_DIR/checksums/schema-baseline.json"
echo "[regen] wrote $SKILL_DIR/checksums/schema-baseline.json (${#TABLES[@]} tables, source $SOURCE_DESC)"

# ============================================================================
# VERIFY (simulated H4/H5 pass)
# ============================================================================
# Re-hash every recorded (file, line_start, line_end) range exactly the way
# Andy's audit does and compare to the recorded hash. Guards against any
# range-arithmetic bug blessing wrong code.

echo ""
echo "[verify] re-running H4/H5 hash check against $SOURCE_DESC ..."
VERIFY_FAIL=0

while IFS=$'\t' read -r VID VFILE VS VE VHASH; do
  VFULL="$(materialize "$VFILE")" || { echo "[verify] H4 $VID: file missing"; VERIFY_FAIL=1; continue; }
  VNOW="$(sed -n "${VS},${VE}p" "$VFULL" | tr -d '\n' >/dev/null; sed -n "${VS},${VE}p" "$VFULL")"
  VH="$(printf '%s' "$VNOW" | shasum -a 256 | awk '{print $1}')"
  if [ "sha256:$VH" = "$VHASH" ]; then
    echo "[verify] H4 $VID: OK"
  else
    echo "[verify] H4 $VID: HASH MISMATCH"; VERIFY_FAIL=1
  fi
done < <(python3 -c "
import json
d = json.load(open('$SKILL_DIR/checksums/code-anchors.json'))
for a in d['anchors']:
    print('\t'.join([a['id'], a['file'], str(a['line_start']), str(a['line_end']), a['hash']]))
")

while IFS=$'\t' read -r VT VS VE VHASH; do
  VNOW="$(sed -n "${VS},${VE}p" "$SCHEMA")"
  VH="$(printf '%s' "$VNOW" | shasum -a 256 | awk '{print $1}')"
  if [ "sha256:$VH" = "$VHASH" ]; then
    echo "[verify] H5 $VT: OK"
  else
    echo "[verify] H5 $VT: HASH MISMATCH"; VERIFY_FAIL=1
  fi
done < <(python3 -c "
import json
d = json.load(open('$SKILL_DIR/checksums/schema-baseline.json'))
for t, v in d['tables'].items():
    print('\t'.join([t, str(v['line_start']), str(v['line_end']), v['hash']]))
")

if [ "$VERIFY_FAIL" -ne 0 ]; then
  echo "[verify] FAILED — do not commit these baselines" >&2
  exit 1
fi
echo "[verify] all anchors + tables green"

echo ""
echo "[regen] Done. Commit the updated baselines:"
echo "  cd $SKILL_DIR && git add checksums/ && git commit -m 'chore: regen andy baselines'"
echo "  git push"
