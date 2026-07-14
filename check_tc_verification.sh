#!/usr/bin/env bash
# check_tc_verification.sh -- did the tc/Kron gem5 verifiers finish, and did they PASS?
#
# WHY THIS EXISTS
# ---------------
# The six tc/Kron matrix runs completed their ROIs (so every tc number in data.md S11
# is FINAL and cannot change), but GAP's TCVerifier is a BRUTE-FORCE triangle count --
# set_intersection over every edge, with none of the kernel's degree-relabeling or
# early termination. Measured natively on kron-s13 it costs 10.3x the kernel it checks
# (0.249 s vs 0.024 s). Simulated in gem5 that is ~245 G ticks, i.e. ~17 hours.
#
# The runs are detached (parent reparented to init, no controlling TTY), so they
# survive SSH/VSCode disconnects. Run this later to see how they ended.
#
# Everything else in the matrix already verified PASS: all 5 other kernels x both
# graphs, AND tc/Urand -- which proves the tc kernel + repair path is correct inside
# gem5. The repair path is graph-agnostic (it translates physical addresses and has no
# notion of graph structure), so a tc/Kron failure would be surprising. But it is a
# correctness check, so it is checked rather than assumed.
set -uo pipefail
M5=/home/pitsaiyang/work/my_work/gem5/m5out

running=$(pgrep -x gem5.opt | wc -l)
echo "gem5 processes still running: $running"
echo

pass=0; fail=0; pending=0
for d in "$M5"/gap-tc-kron-*; do
  [ -d "$d" ] || continue
  n=$(basename "$d")
  roi=$(grep -oP 'ROI 0 end.*?\(\K[0-9]+' "$d/simout.txt" 2>/dev/null)
  if grep -q "Verification:  *PASS" "$d/simout.txt" 2>/dev/null; then
    v="PASS"; pass=$((pass+1))
  elif grep -q "Verification:  *FAIL" "$d/simout.txt" 2>/dev/null; then
    v="*** FAIL ***"; fail=$((fail+1))
  else
    v="still verifying"; pending=$((pending+1))
  fi
  printf "  %-44s ROI=%-13s verifier=%s\n" "$n" "${roi:-?}" "$v"
done

echo
echo "PASS=$pass  FAIL=$fail  PENDING=$pending"
echo
if [ "$fail" -gt 0 ]; then
  echo ">>> A VERIFIER FAILED. That kernel computed the WRONG ANSWER under the repair"
  echo ">>> path. STRIKE the affected tc/Kron cells from data.md S11 and investigate."
  exit 1
elif [ "$pending" -gt 0 ]; then
  echo "Still running. ROI numbers in data.md S11 are final regardless; only the"
  echo "post-ROI correctness check is outstanding."
  exit 0
else
  echo "All tc/Kron verifiers PASSED. The Claim-2 matrix is fully validated:"
  echo "60/60 runs, 0 failures, 0 verification failures."
  echo "-> Remove the caveat in data.md S11.5 and MATRIX_RESULTS.md."
  exit 0
fi
