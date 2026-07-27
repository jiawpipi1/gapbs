#!/usr/bin/env bash
# Run the per-kernel MPKI upper-envelope experiment.
#
# Two distinct sweeps are generated and must not be conflated:
#   1. 1 MiB graph-scale sweep: tests whether larger applications approach a
#      natural MPKI/overhead plateau with a physically sensible cache.
#   2. fixed-graph LLC stress sweep: pushes miss intensity cheaply, but 64/32
#      KiB points are stress envelopes rather than realistic LLC configurations.
#
# Every input/binary pair has already completed verified matrix runs.  These
# extra points therefore use -R (ROI-only) and must never be added to the
# project's Verification: PASS count.  A headline point can be rerun without
# -R after the adaptive sweep identifies it.
set -uo pipefail

ROOT=/home/pitsaiyang/work/my_work
RUNNER="$ROOT/benchmark/GAP/run_gem5_point.sh"
TABLE_DIR="$ROOT/Fault_yield/remap_json_hbm3_v512_atomic32B_s32_20260720"
M5OUT="$ROOT/gem5/m5out"
MAX_JOBS=${JOBS:-32}
FAILURES=0
ACTIVE_PIDS=()

run_one() {
  local kernel=$1 graph=$2 scale=$3 l2=$4 table=$5 latency=$6
  local out="gap-mpki-${kernel}-${graph}-s${scale}-${table}-${latency}-unified-l2${l2}-atomic32s32"
  local simout="$M5OUT/$out/simout.txt"
  local stats="$M5OUT/$out/stats.txt"

  if [[ -s "$stats" ]] \
      && grep -q "ROI-only mode: stopping before the post-ROI verifier" "$simout" \
      && grep -q "completed 1 ROI" "$simout"; then
    echo "[skip] $out"
    return 0
  fi

  local args=(-k "$kernel" -g "$graph" -s "$scale" -t "$table"
              -l "$latency" -G unified -L "$l2" -R -o "$out")
  if [[ "$table" != clean ]]; then
    args+=(-P "$TABLE_DIR")
  fi
  "$RUNNER" "${args[@]}"
}

wait_one() {
  local finished_pid=${ACTIVE_PIDS[0]}
  if wait "$finished_pid"; then
    :
  else
    FAILURES=$((FAILURES + 1))
  fi
  ACTIVE_PIDS=("${ACTIVE_PIDS[@]:1}")
}

throttle() {
  while (( ${#ACTIVE_PIDS[@]} >= MAX_JOBS )); do
    wait_one
  done
}

launch_pair() {
  local kernel=$1 graph=$2 scale=$3 l2=$4
  throttle
  run_one "$kernel" "$graph" "$scale" "$l2" clean l0 &
  ACTIVE_PIDS+=("$!")
  throttle
  run_one "$kernel" "$graph" "$scale" "$l2" 193 f1s12 &
  ACTIVE_PIDS+=("$!")
}

echo "== Natural graph-scale sweep: 1 MiB LLC =="
for kernel in bc cc pr sssp; do
  for graph in kron urand; do
    for scale in 14 15 16 17; do
      launch_pair "$kernel" "$graph" "$scale" 1MB
    done
  done
done

# TC grows superlinearly.  Scales 10/12/13 establish its observed natural
# trajectory; the LLC stress sweep below supplies a conservative intensity
# envelope without pretending that a scale-17 TC simulation is affordable.
for graph in kron urand; do
  for scale in 10 12 13; do
    launch_pair tc "$graph" "$scale" 1MB
  done
done

echo "== Fixed-graph LLC stress sweep =="
for kernel in bc cc sssp; do
  for graph in kron urand; do
    for l2 in 128kB 64kB 32kB; do
      launch_pair "$kernel" "$graph" 14 "$l2"
    done
  done
done

for graph in kron urand; do
  for l2 in 256kB 128kB 64kB 32kB; do
    launch_pair pr "$graph" 14 "$l2"
    launch_pair tc "$graph" 13 "$l2"
  done
done

while (( ${#ACTIVE_PIDS[@]} > 0 )); do
  wait_one
done

if (( FAILURES > 0 )); then
  echo "FAIL: $FAILURES sweep process(es) failed" >&2
  exit 1
fi
echo "PASS: all MPKI upper-envelope ROI runs completed"
