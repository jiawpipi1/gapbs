#!/usr/bin/env bash
# run_gem5_point.sh -- run ONE cell of the Claim-2 matrix.
#
# One code path for every GAP/gem5/Ramulator2 run, so an experiment cannot
# silently drift from the documented configuration. In particular it NEVER
# passes -r: the source is chosen by GAP's own SourcePicker, which is
# deterministic (kRandSeed) and skips zero-degree vertices.
#
#   Pinning `-r0` is what produced the invalid scale-14 Kron numbers: vertex 0
#   of kron-s14 is isolated, so BFS scanned zero edges, touched almost no DRAM,
#   and still passed verification. `make gem5-check-sources` guards the frozen
#   graphs; this script keeps the run side honest.
#
# Usage:
#   run_gem5_point.sh -k KERNEL -g GRAPH -t TABLE -l LATENCY [-s SCALE] [-o DIR]
#
#   -k  bfs|bc|cc|pr|sssp|tc
#   -g  kron|urand
#   -t  clean | 1040 | 796 | 642 | 193      (repair table / severity point)
#   -l  l0 | l12 | f1s12 | f2s12            (lookup-latency model)
#   -s  graph scale (default 14)
#   -o  output dir under gem5/m5out (default: gap-<k>-<g>-s<scale>-<t>-<l>)
#
set -euo pipefail

ROOT=/home/pitsaiyang/work/my_work
TABLE_DIR="$ROOT/Fault_yield/remap_json_hbm3_v512_20260714"
SCALE=14
DEGREE=16
OUTDIR=""

GATE=""
L2SIZE=""
while getopts "k:g:t:l:s:o:G:L:" opt; do
  case "$opt" in
    k) KERNEL="$OPTARG" ;;
    g) GRAPH="$OPTARG" ;;
    t) TABLE="$OPTARG" ;;
    l) LAT="$OPTARG" ;;
    s) SCALE="$OPTARG" ;;
    o) OUTDIR="$OPTARG" ;;
    G) GATE="$OPTARG" ;;   # unified | legacy
    L) L2SIZE="$OPTARG" ;; # LLC size, e.g. 1MB / 256kB. Sets DRAM intensity.
    *) echo "bad option" >&2; exit 2 ;;
  esac
done
: "${KERNEL:?-k required}" "${GRAPH:?-g required}" "${TABLE:?-t required}" "${LAT:?-l required}"

# -G unified: a Bloom reject is fast even when Layer D relocated the request.
# -G legacy : every dead-bank access pays the slow latency (conservative).
GATE_ARG=()
if [[ -n "$GATE" ]]; then GATE_ARG=(--repair-gate "$GATE"); fi
L2_ARG=()
if [[ -n "$L2SIZE" ]]; then L2_ARG=(--l2-size "$L2SIZE"); fi

# -- repair table ------------------------------------------------------------
# `--repair-table none` is the clean-die baseline. Everything else must be a
# real production V512 table; the toy json/remap_hbm3_smoke.json is a no-op
# repair path (~1500x too few Layer C segments) and must never be measured.
if [[ "$TABLE" == "clean" ]]; then
  TABLE_ARG=(--repair-table none)
else
  TABLE_JSON="$TABLE_DIR/remap_hbm_${TABLE}.json"
  [[ -f "$TABLE_JSON" ]] || { echo "no such table: $TABLE_JSON" >&2; exit 1; }
  TABLE_ARG=(--repair-table "$TABLE_JSON")
fi

# -- latency model -----------------------------------------------------------
# l0/l12 are fixed-latency controls (every request pays the same). f1s12/f2s12
# are the blocked-Bloom split model: only dead-bank or Bloom-maybe requests pay
# the slow path.
case "$LAT" in
  l0)    LAT_ARG=(--repair-lookup-latency 0) ;;
  l12)   LAT_ARG=(--repair-lookup-latency 12) ;;
  f1s12) LAT_ARG=(--repair-fast-lookup-latency 1 --repair-slow-lookup-latency 12) ;;
  f2s12) LAT_ARG=(--repair-fast-lookup-latency 2 --repair-slow-lookup-latency 12) ;;
  *) echo "bad -l: $LAT (l0|l12|f1s12|f2s12)" >&2; exit 2 ;;
esac

SG="$ROOT/benchmark/GAP/benchmark/graphs/gem5/${GRAPH}-s${SCALE}-d${DEGREE}.sg"
BIN="$ROOT/benchmark/GAP/build/gem5/${KERNEL}"
[[ -f "$SG"  ]] || { echo "no such graph: $SG" >&2; exit 1; }
[[ -x "$BIN" ]] || { echo "no such kernel: $BIN" >&2; exit 1; }

# Refuse to run a graph whose GAP-chosen source is degenerate.
"$ROOT/benchmark/GAP/build/gem5/gem5_source_audit" -f "$SG" > /dev/null || {
  echo "source audit FAILED for $SG -- refusing to run" >&2; exit 1; }

[[ -n "$OUTDIR" ]] || OUTDIR="gap-${KERNEL}-${GRAPH}-s${SCALE}-${TABLE}-${LAT}${GATE:+-$GATE}${L2SIZE:+-l2$L2SIZE}"

cd "$ROOT/gem5"
echo "[run] $OUTDIR"
./build/X86/gem5.opt --redirect-stdout --redirect-stderr \
  -d "m5out/$OUTDIR" \
  configs/w2w/se_ramulator2.py \
  --cmd "$BIN" \
  --options "-f $SG -n1 -v" \
  --cpu-type o3 \
  --ramulator-config "$ROOT/ramulator2/gem5_hbm3.yaml" \
  --ramulator-dir "$ROOT/ramulator2" \
  "${TABLE_ARG[@]}" \
  "${LAT_ARG[@]}" \
  "${GATE_ARG[@]}" \
  "${L2_ARG[@]}"

# -- success criteria --------------------------------------------------------
OUT="m5out/$OUTDIR/simout.txt"
ERR="m5out/$OUTDIR/simerr.txt"
grep -q "Verification:  *PASS" "$OUT" || { echo "FAIL: verification" >&2; exit 1; }
grep -q "completed 1 ROI" "$OUT"      || { echo "FAIL: not exactly one ROI" >&2; exit 1; }
grep -q "Ramulator2 statistics: ROI" "$OUT" || {
  echo "FAIL: no ROI-scoped Ramulator block" >&2; exit 1; }
if grep -qE "^(fatal|panic):" "$ERR"; then echo "FAIL: fatal/panic" >&2; exit 1; fi

ROI_TICKS=$(grep -oP 'ROI 0 end.*\(\K[0-9]+' "$OUT")
echo "[ok ] $OUTDIR  ROI ticks = $ROI_TICKS"
