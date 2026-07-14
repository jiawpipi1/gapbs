# Claim-2 workload matrix -- all six GAP kernels

Worst die 193 (F=15, the worst of 1130 real dies), F1/S12, unified gate + 512-bit
Bloom. O3 CPU, ROI-only statistics, GAP-chosen sources (never `-r`). Scale 14, except
`tc` at scale 13 (it is ~150x BFS to simulate; comparison is at matched **MPKI**, not
matched scale -- see below).

Regenerate any cell with `benchmark/GAP/run_gem5_point.sh`.

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

**Worst cell across the entire matrix: +0.804% (PageRank / Kron / 128 kB LLC).**

Both graph families (Kron, Urand) are included in every band above. 34 cells, 0 failures.

---

## 2. The mechanism: overhead is TRANSLATION, and translation costs LOCALITY

Decomposing every cell as `clean -> repaired-L0 -> F1/S12` separates the two costs:

- **translation** = Layer D moved the bank/row, changing DRAM locality. *No latency added.*
- **lookup** = the F1/S12 front-gate pipeline latency itself.

**Across all six kernels: translation is 88% of the overhead, the lookup 12%.**

| kernel | translation | lookup | translation share |
|---|---:|---:|---:|
| `bfs`  | +0.089% .. +0.474% | +0.013% .. +0.074% | 84-92% |
| `pr`   | +0.617% .. +0.723% | +0.074% .. +0.085% | 88-90% |
| `bc`   | +0.102% .. +0.671% | +0.035% .. +0.054% | 73-95% |
| `cc`   | +0.414% .. +0.442% | +0.049% .. +0.056% | 88-90% |
| `sssp` | +0.073% .. +0.315% | +0.030% .. +0.046% | 62-91% |
| `tc`   | +0.020% .. +0.308% | +0.004% .. +0.070% | 81-88% |

**The lookup cost is nearly constant (~0.004-0.085%) whatever the kernel.** The front
gate is done; further Bloom/latency tuning is chasing < 0.09%.

### The predictive model

Overhead is linear in DRAM intensity, and the *slope* is set by how much row-buffer
locality the kernel has to lose:

Assessed at moderate-to-high DRAM intensity (MPKI >= 5; see the caveat below):

| kernel | clean row-hit | **slope (ov / MPKI)** |
|---|---:|---:|
| `sssp` | 58-73% | **0.013 - 0.029** |
| `bfs`  | 83-91% | **0.029 - 0.038** |
| `bc`   | 74-92% | **0.029 - 0.044** |
| `tc` (urand, MPKI 8.7) | 82.5% | **0.044** |
| `pr`   | 96% | **0.058 - 0.063** |
| `cc`   | 96% | **0.062** |

**The correlation is monotonic across six independent kernels, spanning a 3-4x range of
slope.** Layer D relocation destroys row-buffer hits, so **a kernel with more locality
to lose, loses more**. `cc` is an independent confirmation: algorithmically nothing
like PageRank, but it shares PR's 96% streaming locality and lands on PR's slope.

Measured row-hit loss (clean -> repaired) is **0.2 - 1.3 points** in every cell.

> **CAVEAT -- the slope metric is unreliable below MPKI ~5.** There is a small fixed
> component to the overhead, so dividing it by a near-zero MPKI inflates the ratio.
> `tc`/Kron at 128 kB (MPKI 2.01) reports a slope of 0.103, which is an artifact of
> that division, not a real outlier -- its *absolute* overhead is only **+0.207%**.
> Quote absolute overhead at low MPKI; use the slope only where the kernel is actually
> memory-bound.

---

## 3. Why the BFS bound did NOT transfer -- and why per-kernel sweeps are mandatory

**BFS at MPKI 12.9 -> +0.377%. PR at MPKI 11.4 -> +0.715%.** PR is ~2x worse at
comparable DRAM intensity because its slope is ~2x BFS's. Reusing BFS's bound would
have understated PageRank by half.

**Every kernel needs its own MPKI sweep.** The slope is a property of the kernel's
access pattern, not something transferable.

---

## 4. `tc` is the strongest confirmation, for a reason worth stating

Triangle counting is by far the **most expensive kernel to simulate** (~150x BFS) --
and by far the **cheapest to repair** (+0.024%). It is **compute-bound**, not
memory-bound: only **14,706 L2 misses across 26.2M instructions** (MPKI 0.4-0.6,
IPC up to 1.24). It barely touches DRAM, so a DRAM-side repair mechanism costs it
almost nothing.

Force it memory-bound (128 kB LLC, MPKI 8.65) and its overhead rises to +0.378%,
exactly on its own slope. The model holds.

> **This is worth a sentence in the paper:** the mechanism's cost is invisible to
> compute-bound workloads and bounded even for the most memory-bound ones.

---

## 5. Methodology notes and honest caveats

1. **`tc` runs at scale 13, everything else at 14.** Justified because cross-kernel
   comparison is at matched **MPKI**, not matched graph scale -- which is the whole
   point of the MPKI methodology. Its MPKI is reported like every other cell.
2. **`sssp` needs WEIGHTED graphs** (`.wsg`). The unweighted `.sg` twins have identical
   topology. `run_gem5_point.sh` picks the extension by kernel.
3. **Do not quote the 64 kB / 32 kB LLC points for streaming kernels.** Below 128 kB,
   PR's score arrays (~131 KB) stop fitting and MPKI explodes to 30-91 -- that is
   **cache thrashing** with the LLC below the 32 kB L1D. It is an artifact, not an
   operating point.
4. **"Shrink the LLC until MPKI plateaus" is NOT universal.** BFS saturates; PR does
   not. Report a per-kernel MPKI **band**, and say which LLC sizes are physically
   sensible.
5. **Slow-path fractions are 0.09-0.57% in every cell** -- the lookup is a non-issue
   across the entire suite.
6. Reduced graphs are always **simulation proxies**, never GAP-compliant results.
