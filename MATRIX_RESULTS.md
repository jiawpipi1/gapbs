# Claim-2 workload matrix -- all six GAP kernels

Worst die 193 (F=15, the worst of 1131 real dies), F1/S12, unified gate + 512-bit Bloom. O3 CPU, ROI-only statistics, GAP-chosen sources (never `-r`). Scale 14, except `tc` at scale 13 (it is ~150x BFS to simulate; comparison is at matched **MPKI**, not matched scale -- see below). Regenerate any cell with `benchmark/GAP/run_gem5_point.sh`.

**Mapping boundary:** this matrix uses the published/original `spread` Layer-D policy, which remains the default. Matching worst-die `clustered` coverage is complete separately in `Fault_yield/data.md` S11.8: 34 formal F1 cells, 24 L0 decompositions and 72 scale/stress points. The three milder severity points and physical target-select timing/area remain open. Do not silently replace spread cells or directories with clustered values.

---

## 1. Headline: the overhead is under 1% for every kernel, on the worst die

| kernel | character | clean row-hit | **overhead @ 1 MB LLC** | **overhead @ 128 kB LLC** |
|---|---|---:|---:|---:|
| `tc`   | triangle counting (compute-bound) | 83-95% | **+0.024% .. +0.031%** | +0.207% .. +0.378% |
| `bfs`  | irregular frontier walk | 69-91% | +0.071% .. +0.102% | +0.462% .. +0.514% |
| `sssp` | delta-stepping (weighted) | 58-73% | +0.119% .. +0.237% | +0.265% .. +0.345% |
| `bc`   | betweenness centrality | 63-92% | +0.140% .. +0.242% | +0.611% .. +0.706% |
| `cc`   | connected components | 96% | +0.463% .. +0.476% | +0.477% .. +0.493% |
| `pr`   | PageRank (pull / streaming) | 96% | +0.691% .. +0.715% | +0.757% .. **+0.804%** |

**Worst cell across the entire matrix: +0.804% (PageRank / Kron / 128 kB LLC).** Both graph families (Kron, Urand) are in every band above. 34 cells, 0 failures.

---

## 2. The mechanism: overhead is TRANSLATION, and translation costs LOCALITY

Decomposing every cell as `clean -> repaired-L0 -> F1/S12` separates the two costs: **translation** = Layer D moved the bank/row, changing DRAM locality (no latency added); **lookup** = the F1/S12 front-gate pipeline latency itself.

**Across all six kernels under spread: translation is 89% of the overhead, the lookup 11%.**

| kernel | translation | lookup | translation share |
|---|---:|---:|---:|
| `bfs`  | +0.089% .. +0.474% | +0.013% .. +0.074% | 84-92% |
| `pr`   | +0.617% .. +0.723% | +0.074% .. +0.085% | 88-90% |
| `bc`   | +0.102% .. +0.671% | +0.035% .. +0.054% | 73-95% |
| `cc`   | +0.414% .. +0.442% | +0.049% .. +0.056% | 88-90% |
| `sssp` | +0.073% .. +0.315% | +0.030% .. +0.046% | 62-91% |
| `tc`   | +0.020% .. +0.308% | +0.004% .. +0.070% | 81-92% |

**The lookup cost is nearly constant (~0.004-0.085%) whatever the kernel.** The front gate is done; further Bloom/latency tuning is chasing < 0.09%.

### The local operating-band model

Within the fixed-scale, physically sensible 1 MiB--128 KiB LLC band, MPKI is a useful first-order screen and the local *slope* correlates with how much row-buffer locality the kernel has to lose. Assessed at moderate-to-high DRAM intensity (MPKI >= 5; see the caveat below):

| kernel | clean row-hit | **slope (ov / MPKI)** |
|---|---:|---:|
| `sssp` | 58-73% | **0.013 - 0.029** |
| `bfs`  | 83-91% | **0.029 - 0.038** |
| `bc`   | 74-92% | **0.029 - 0.044** |
| `tc` (urand, MPKI 8.7) | 82.5% | **0.044** |
| `pr`   | 96% | **0.058 - 0.063** |
| `cc`   | 96% | **0.062** |

**The cross-kernel ordering is monotonic across a 3-4x range of local slope.** Layer D relocation destroys row-buffer hits, so **a kernel with more locality to lose generally loses more in this band**. `cc` is an independent confirmation: algorithmically nothing like PageRank, but it shares PR's 96% streaming locality and lands on PR's slope. Measured row-hit loss (clean -> repaired) is **0.2 - 1.3 points** in every cell.

**CAVEAT -- the slope metric is unreliable below MPKI ~5.** A small fixed component of the overhead divided by a near-zero MPKI inflates the ratio: `tc`/Kron at 128 kB (MPKI 2.01) reports a slope of 0.103, an artifact of that division, not a real outlier -- its *absolute* overhead is only **+0.207%**. Quote absolute overhead at low MPKI; use the slope only where the kernel is actually memory-bound.

---

## 3. Why the BFS bound did NOT transfer

**BFS at MPKI 12.9 -> +0.377%. PR at MPKI 11.4 -> +0.715%.** PR is ~2x worse at comparable DRAM intensity because its slope is ~2x BFS's, so reusing BFS's bound would have understated PageRank by half. **Every kernel needs its own curve** -- the slope is a local property of the kernel's access pattern, not something transferable. That experiment is now complete; see section 6 and `Fault_yield/data.md` S11.6.

---

## 4. `tc` is the strongest confirmation, for a reason worth stating

Triangle counting is by far the **most expensive kernel to simulate** (~150x BFS) -- and by far the **cheapest to repair** (+0.024%). It is **compute-bound**: only **14,706 L2 misses across 26.2M instructions** (MPKI 0.4-0.6, IPC up to 1.24), so a DRAM-side repair mechanism costs it almost nothing. Force it memory-bound (128 kB LLC, MPKI 8.65) and its overhead rises to +0.378%, exactly on its own slope.

**Worth a sentence in the paper:** the mechanism's cost is nearly invisible to compute-bound workloads in the measured operating band.

---

## 5. Methodology notes and honest caveats

1. **`tc` runs at scale 13, everything else at 14.** Justified because cross-kernel comparison is at matched **MPKI**, not matched graph scale -- which is the whole point of the MPKI methodology. Its MPKI is reported like every other cell.
2. **`sssp` needs WEIGHTED graphs** (`.wsg`). The unweighted `.sg` twins have identical topology. `run_gem5_point.sh` picks the extension by kernel.
3. **Do not quote the 64 KiB / 32 KiB LLC points as operating points.** Below 128 KiB, PR's score arrays (~131 KB) stop fitting and MPKI explodes to 30-91 -- that is **cache thrashing**; at 32 KiB the L2 is only as large as the 32 KiB L1D. It is an artifact, not an operating point.
4. **"Shrink the LLC until MPKI plateaus" is NOT universal.** BFS saturates; PR does not. Report a per-kernel MPKI **band**, and say which LLC sizes are physically sensible.
5. **Slow-path fractions are 0.09-0.57% in every cell** -- the lookup is a non-issue across the entire suite.
6. Reduced graphs are always **simulation proxies**, never GAP-compliant results.

---

## 6. Per-kernel upper-envelope sweep (2026-07-22)

The follow-up contains **72 clean/repaired pairs = 144 ROI-only runs** on the current atomic32B/s32 worst-die table. All 144 runs completed one ROI with non-empty stats, zero fatal/panic, and zero Layer-A hits in all 72 repaired runs. These sweep points skip the already-covered post-ROI verifier and do not increase the formal 60/60 verification count.

At a fixed 1 MiB LLC, the largest overhead observed in each natural graph-scale curve:

| kernel | Kron | Urand | largest tested scale |
|---|---:|---:|---:|
| `bc` | +0.317% | +0.140% | s17 |
| `cc` | +0.476% | +0.463% | s17 |
| `pr` | +0.722% | +0.691% | s17 |
| `sssp` | +0.250% | +0.119% | s17 |
| `tc` | +0.096% | +0.055% | s13 |

Every measured natural-scale curve is flat by its largest tested scale: application growth did not make the overhead keep increasing. These are measured envelopes, not mathematical asymptotes. MPKI itself plateaus for `cc`, `pr`, and `tc`; `bc` and `sssp` MPKI still rises at s17 while overhead stays flat. Therefore MPKI is a first-order intensity axis, not a sufficient one-variable predictor.

The separate 64/32 KiB fixed-graph sweep is a **stress envelope**. At 32 KiB the Kron/Urand overheads are `bc` +1.157%/+0.865%, `cc` +1.245%/+1.361%, `pr` +3.523%/+2.448%, `sssp` +0.739%/+0.818%, and `tc` +0.366%/+0.575%. Do not merge these cache-thrashing points into the formal 1 MiB--128 KiB Claim-2 matrix.

Exact every-point tables: `Fault_yield/data.md` S11.6. Reproduce with `benchmark/GAP/run_mpki_upperbound_sweep.sh`; parse with `benchmark/GAP/analyze_mpki_upperbound.py`.
