#!/usr/bin/env bash
# Give clustered Layer-D placement the same current, thesis-valid simulation
# depth as spread without deleting or overwriting any existing result:
#   - 34 formal F1/S12 cells with post-ROI GAP verification
#   - 24 matching L0 cells used by the spread translation/lookup decomposition
#   - 72 natural-scale / LLC-stress points (22 reuse deeper formal runs)
#
# Historical BFS scale runs that used the superseded 20260714 full-row table are
# deliberately excluded. The coverage contract here is the current atomic32B/s32
# spread dataset in Fault_yield/data.md S11.1 and S11.6.
set -uo pipefail

ROOT=/home/pitsaiyang/work/my_work
RUNNER="$ROOT/benchmark/GAP/run_gem5_point.sh"
TABLE_DIR="$ROOT/Fault_yield/remap_json_hbm3_v512_atomic32B_s32_20260720"
M5OUT="$ROOT/gem5/m5out"
MAX_JOBS=${JOBS:-16}
FAILURES=0
ACTIVE_PIDS=()

is_complete() {
  local out=$1 mode=$2
  local dir="$M5OUT/$out"
  [[ -s "$dir/stats.txt" && -s "$dir/simout.txt" && -s "$dir/ramulator2_resolved.yaml" ]] || return 1
  grep -q "completed 1 ROI" "$dir/simout.txt" || return 1
  grep -q "Ramulator2 statistics: ROI" "$dir/simout.txt" || return 1
  grep -Eq '^\s*repair_d_mapping:\s*clustered\s*$' "$dir/ramulator2_resolved.yaml" || return 1
  if [[ "$mode" == formal ]]; then
    grep -q "Verification:[[:space:]]*PASS" "$dir/simout.txt" || return 1
    ! grep -q "ROI-only mode" "$dir/simout.txt" || return 1
  else
    grep -q "ROI-only mode: stopping before the post-ROI verifier" "$dir/simout.txt" || return 1
  fi
  if [[ -f "$dir/simerr.txt" ]] && grep -Eqi '(^|[^[:alpha:]])(fatal|panic)([^[:alpha:]]|$)' "$dir/simerr.txt"; then
    return 1
  fi
}

run_one() {
  local mode=$1 kernel=$2 graph=$3 scale=$4 llc=$5 latency=$6 out=$7
  if is_complete "$out" "$mode"; then
    echo "[reuse] $out"
    return 0
  fi
  if [[ -e "$M5OUT/$out" ]]; then
    echo "[stop] incomplete or mismatched existing directory: $M5OUT/$out" >&2
    echo "       move it aside explicitly; this script never deletes results" >&2
    return 1
  fi
  local args=(-k "$kernel" -g "$graph" -s "$scale" -t 193 -l "$latency"
              -G unified -D clustered -L "$llc" -P "$TABLE_DIR" -o "$out")
  [[ "$mode" == roi ]] && args+=(-R)
  "$RUNNER" "${args[@]}"
}

wait_one() {
  local finished_pid=""
  while [[ -z "$finished_pid" ]]; do
    for pid in "${ACTIVE_PIDS[@]}"; do
      if ! kill -0 "$pid" 2>/dev/null; then
        finished_pid=$pid
        break
      fi
    done
    [[ -n "$finished_pid" ]] || sleep 1
  done
  wait "$finished_pid" || FAILURES=$((FAILURES + 1))
  local remaining=()
  for pid in "${ACTIVE_PIDS[@]}"; do
    [[ "$pid" == "$finished_pid" ]] || remaining+=("$pid")
  done
  ACTIVE_PIDS=("${remaining[@]}")
}

throttle() {
  while (( ${#ACTIVE_PIDS[@]} >= MAX_JOBS )); do
    wait_one
  done
}

launch() {
  throttle
  run_one "$@" &
  ACTIVE_PIDS+=("$!")
}

formal_name() {
  local kernel=$1 graph=$2 scale=$3 llc=$4 latency=$5
  echo "gap-cluster-full-${kernel}-${graph}-s${scale}-193-${latency}-unified-l2${llc}-atomic32s32"
}

echo "== Clustered formal matrix: 34 F1/S12 + 24 L0 verified runs =="
for kernel in bc bfs cc pr sssp tc; do
  scale=14
  llcs=(1MB 256kB 128kB)
  if [[ "$kernel" == tc ]]; then
    scale=13
    llcs=(1MB 128kB)
  fi
  for graph in kron urand; do
    for llc in "${llcs[@]}"; do
      out=$(formal_name "$kernel" "$graph" "$scale" "$llc" f1s12)
      launch formal "$kernel" "$graph" "$scale" "$llc" f1s12 "$out"
    done
    # Spread has L0 decomposition at the two headline LLC sizes.
    for llc in 1MB 128kB; do
      out=$(formal_name "$kernel" "$graph" "$scale" "$llc" l0)
      launch formal "$kernel" "$graph" "$scale" "$llc" l0 "$out"
    done
  done
done

while (( ${#ACTIVE_PIDS[@]} > 0 )); do wait_one; done

if (( FAILURES > 0 )); then
  echo "FAIL: $FAILURES formal clustered process(es) failed; sweep not started" >&2
  exit 1
fi

echo "== Clustered 72-point application-scale / LLC-stress coverage =="

# The 22 base operating points below already have a stronger, post-ROI-verified
# clustered formal result. Do not waste time duplicating them under an ROI-only
# directory; the analyzer verifies and reuses the formal run for those points.
is_formal_reuse() {
  local kernel=$1 scale=$2 llc=$3
  if [[ "$kernel" == tc ]]; then
    # The formal TC band is 1MB/128kB; 256kB exists only in the stress sweep.
    [[ "$scale" == 13 && ( "$llc" == 1MB || "$llc" == 128kB ) ]]
  else
    [[ "$scale" == 14 && ( "$llc" == 1MB || "$llc" == 256kB || "$llc" == 128kB ) ]]
  fi
}

launch_sweep_point() {
  local kernel=$1 graph=$2 scale=$3 llc=$4
  if is_formal_reuse "$kernel" "$scale" "$llc"; then
    local formal
    formal=$(formal_name "$kernel" "$graph" "$scale" "$llc" f1s12)
    if ! is_complete "$formal" formal; then
      echo "FAIL: expected reusable formal result is incomplete: $formal" >&2
      FAILURES=$((FAILURES + 1))
    else
      echo "[reuse-formal-for-sweep] $formal"
    fi
    return
  fi
  local out="gap-mpki-cluster-${kernel}-${graph}-s${scale}-193-f1s12-unified-l2${llc}-atomic32s32"
  launch roi "$kernel" "$graph" "$scale" "$llc" f1s12 "$out"
}

for kernel in bc cc pr sssp; do
  for graph in kron urand; do
    for scale in 14 15 16 17; do
      launch_sweep_point "$kernel" "$graph" "$scale" 1MB
    done
  done
done
for graph in kron urand; do
  for scale in 10 12 13; do
    launch_sweep_point tc "$graph" "$scale" 1MB
  done
done

for kernel in bc cc sssp; do
  for graph in kron urand; do
    for llc in 128kB 64kB 32kB; do
      launch_sweep_point "$kernel" "$graph" 14 "$llc"
    done
  done
done
for graph in kron urand; do
  for llc in 256kB 128kB 64kB 32kB; do
    launch_sweep_point pr "$graph" 14 "$llc"
    launch_sweep_point tc "$graph" 13 "$llc"
  done
done

while (( ${#ACTIVE_PIDS[@]} > 0 )); do wait_one; done

if (( FAILURES > 0 )); then
  echo "FAIL: $FAILURES clustered coverage process(es) failed" >&2
  exit 1
fi

python3 "$ROOT/benchmark/GAP/analyze_clustered_full_coverage.py" "$M5OUT"
echo "PASS: clustered now has the current spread dataset's full simulation depth"
