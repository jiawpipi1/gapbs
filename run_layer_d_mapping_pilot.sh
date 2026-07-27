#!/usr/bin/env bash
# Reproduce Fault_yield/data.md S11.7 without deleting or overwriting complete runs.
set -euo pipefail

ROOT=/home/pitsaiyang/work/my_work
DRIVER="$ROOT/benchmark/GAP/run_gem5_point.sh"
M5OUT="$ROOT/gem5/m5out"

run_point() {
  local kernel=$1 graph=$2 llc=$3 table=$4 latency=$5 mapping=$6 outdir=$7
  local simout="$M5OUT/$outdir/simout.txt"
  if [[ -f "$simout" ]] && grep -q "completed 1 ROI" "$simout" \
     && grep -q "Ramulator2 statistics: ROI" "$simout"; then
    echo "[reuse] $outdir"
    return
  fi
  if [[ -e "$M5OUT/$outdir" ]]; then
    echo "[stop] incomplete existing directory: $M5OUT/$outdir" >&2
    echo "       move it aside explicitly before rerunning; this script will not delete it" >&2
    exit 1
  fi
  "$DRIVER" -k "$kernel" -g "$graph" -t "$table" -l "$latency" \
    -s 14 -G unified -D "$mapping" -L "$llc" -R -o "$outdir"
}

# kernel graph LLC. These are the eight translation-only triples in data.md S11.7.
while read -r kernel graph llc; do
  [[ -n "$kernel" ]] || continue
  run_point "$kernel" "$graph" "$llc" clean l0 spread \
    "gap-${kernel}-${graph}-s14-clean-l0-unified-l2${llc}"
  run_point "$kernel" "$graph" "$llc" 193 l0 spread \
    "gap-${kernel}-${graph}-s14-193-l0-unified-l2${llc}"
  run_point "$kernel" "$graph" "$llc" 193 l0 clustered \
    "gap-cluster-${kernel}-${graph}-s14-193-l0-clustered-l2${llc}"
done <<'POINTS'
bfs kron 128kB
bfs urand 128kB
cc kron 1MB
cc urand 1MB
pr kron 1MB
pr kron 128kB
pr urand 1MB
pr urand 128kB
POINTS

# Four points also carry the normal F1/S12 sensitivity decomposition.
while read -r kernel graph llc; do
  [[ -n "$kernel" ]] || continue
  run_point "$kernel" "$graph" "$llc" 193 f1s12 spread \
    "gap-${kernel}-${graph}-s14-193-f1s12-unified-l2${llc}"
  run_point "$kernel" "$graph" "$llc" 193 f1s12 clustered \
    "gap-cluster-${kernel}-${graph}-s14-193-f1s12-clustered-l2${llc}"
done <<'POINTS'
bfs kron 128kB
bfs urand 128kB
pr kron 128kB
pr urand 1MB
POINTS

python3 "$ROOT/benchmark/GAP/analyze_layer_d_mapping.py" "$M5OUT"
