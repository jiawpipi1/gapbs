# gem5 + Ramulator2 integration

The GAP algorithms stay in this standalone repository. The gem5 build only adds ROI annotations around each kernel trial; no kernel changes, no graph-specific algorithm selection.

## Build

```bash
make -C benchmark/GAP gem5-ready GEM5_SCALE=14
```

From the workspace root. It (1) builds gem5's x86 `libm5.a` if needed, (2) builds static, serial, ROI-annotated binaries in `build/gem5/`, (3) uses `/usr/bin/g++` to freeze scale-14 Kron and Urand serialized graphs in `benchmark/graphs/gem5/`. Binaries are deliberately serial: the simulated system has one O3 CPU, so parallel binaries would measure an OpenMP runtime on a one-core machine.

Frozen scale-14 inputs generated on 2026-07-14:

| input | vertices | undirected edges | SHA-256 |
|---|---:|---:|---|
| `kron-s14-d16.sg` | 16,383 | 212,930 | `d4d1188a70d33a345972b71947b7e49fa4ec76c36093eb8c3d3714fed23189c7` |
| `urand-s14-d16.sg` | 16,384 | 261,864 | `413cfbbb4d16426b8d27c44c6532843a5f5f1b6c67b2d3b1067ede9dfc54f0be` |

## Never pin a search source with `-r`

**Omit `-r`.** `SourcePicker` is already deterministic (`kRandSeed = 27491095`) and already redraws until it finds a non-zero-degree vertex; `-r <n>` bypasses that guard, because `benchmark.h` does `if (given_source != -1) return given_source;` before the zero-degree loop.

Every scale-14 Kron result up to 2026-07-14 used `-r0`. Vertex 0 of `kron-s14-d16` has degree 0 (3,830 of its 16,383 vertices are isolated), so BFS visited one vertex, scanned zero edges, produced 136 L2 misses -- and still printed `Verification: PASS`, because a one-vertex BFS tree is trivially correct. Every Kron performance number was measuring an empty kernel.

Without `-r` the chosen sources are deterministic *and* valid:

| graph | source | degree | reaches |
|---|---:|---:|---|
| `kron-s14`  | 14341 | 10 | 12,543 / 16,383 (the giant component) |
| `urand-s14` | 3274  | 36 | 16,384 / 16,384 |

Guarded by `make gem5-check-sources` (part of `gem5-ready`), which links GAP's real `SourcePicker`/`Builder` and fails on an isolated or near-isolated source.

## Running an experiment

The driver never passes `-r`, audits the source first, and post-checks verification / exactly one ROI / a ROI-scoped Ramulator block / no fatal or panic.

```bash
# -k kernel  -g kron|urand  -t clean|1040|796|642|193  -l l0|l12|f1s12|f2s12  [-s scale]
./run_gem5_point.sh -k bfs -g urand -t 193 -l f1s12

# Layer-D placement is independently selectable. spread is the default and
# preserves the published matrix; clustered is the opt-in locality policy.
./run_gem5_point.sh -k bfs -g urand -t 193 -l l0 -L 128kB -D clustered
```

- Never reuse an output directory across `-D spread` and `-D clustered`: the two policies produce different translations. Focused mechanism metrics are in `Fault_yield/data.md` S11.7; complete worst-die coverage and reproduction commands are in S11.8 and `benchmark/GAP/run_clustered_full_coverage.sh`.
- Severity points: `clean` (no table), `1040` (F=0), `796` (median F=4), `642` (p90 F=12), `193` (worst F=15). Only `--cmd` changes the kernel and only the `.sg` path changes the graph family.
- Never point a GAP run at `ramulator2/json/remap_hbm3_smoke.json` -- it is a toy table. The driver requires `--repair-table` and writes a resolved YAML into the output directory so omission cannot silently select it.

Manual equivalent -- paths must be absolute, because the Ramulator2 wrapper chdirs while resolving config files (note there is no `-r`):

```bash
ROOT=/home/pitsaiyang/work/my_work
./build/X86/gem5.opt -d m5out/gap-bfs-kron-s14-clean-l0 \
  configs/w2w/se_ramulator2.py \
  --cmd "$ROOT/benchmark/GAP/build/gem5/bfs" \
  --options "-f $ROOT/benchmark/GAP/benchmark/graphs/gem5/kron-s14-d16.sg -n1 -v" \
  --cpu-type o3 \
  --ramulator-config "$ROOT/ramulator2/gem5_hbm3.yaml" \
  --ramulator-dir "$ROOT/ramulator2" \
  --repair-table none \
  --repair-lookup-latency 0
```

## Measurement boundary

- Graph loading and CSR deserialization happen before `workbegin`. gem5 resets statistics at `workbegin`, dumps them at `workend`, and prints the measured ROI ticks. Use `-n1` for one ROI per process.
- The first block in `stats.txt` holds resettable kernel-ROI counters; gem5 appends a second post-ROI block at process exit. Ignore fields documented as never-reset/cumulative (`finalTick`, host bookkeeping, some power residency).
- Verification (`-v`) and result analysis (`-a`) run after `workend` and are not measured.
- **Ramulator2's statistics are ROI-scoped as of 2026-07-14.** Its counters live outside gem5's statistics system, so they are reset at workbegin and dumped at workend (before the following reset). Two labelled blocks are printed:

```
[w2w] ==== Ramulator2 statistics: ROI (kernel only) ====            <-- use this
[w2w] ==== Ramulator2 statistics: SINCE LAST RESET (post-ROI tail) ==
```

- Clocks are exempt from the reset: they timestamp in-flight repair-lookup entries, and zeroing `m_clk` would strand every in-flight request. Window length is `roi_cycles`, distinct from cumulative `memory_system_cycles`.
- Requests in flight at an ROI boundary are attributed exactly as gem5 attributes its own -- a normal boundary artifact worth one sentence in the paper.

## Scale rule: the variable is DRAM intensity, not graph size

The repair lookup is charged **per DRAM request**, so overhead tracks **L2 misses per 1000 instructions (MPKI)**. Graph scale matters only *through* MPKI: a bigger graph outgrows the 1 MB L2, so more of the kernel becomes DRAM-bound. Proof -- hold the graph at scale 14 and shrink the LLC instead (BFS, O3, worst die 193, F1/S12, unified gate + 512-bit Bloom, ROI-only):

| graph | config | MPKI | IPC | overhead | ov/MPKI |
|---|---|---:|---:|---:|---:|
| Kron | s14 / 1 MB   |  6.03 | 0.93 | +0.102% | 0.017 |
| Kron | s14 / 256 kB | 14.12 | 0.75 | +0.413% | 0.029 |
| Kron | **s14 / 128 kB** | **17.56** | 0.69 | **+0.514%** | 0.029 |
| Kron | s15 / 1 MB   |  7.06 | 0.91 | +0.218% | 0.031 |
| Kron | s16 / 1 MB   | 12.90 | 0.74 | +0.377% | 0.029 |
| Kron | **s17 / 1 MB**   | **16.02** | 0.68 | **+0.457%** | 0.029 |
| Urand | s14 / 1 MB   |  4.54 | 0.92 | +0.071% | 0.016 |
| Urand | s14 / 256 kB |  9.61 | 0.77 | +0.309% | 0.032 |
| Urand | s14 / 128 kB | 12.09 | 0.73 | +0.462% | 0.038 |
| Urand | s15 / 1 MB   | 11.51 | 0.79 | +0.262% | 0.023 |
| Urand | s16 / 1 MB   | 16.84 | 0.70 | +0.416% | 0.025 |
| Urand | s17 / 1 MB   | 20.36 | 0.66 | +0.455% | 0.022 |

`overhead / MPKI` is ~constant, so **a scale-14 graph with a 128 kB L2 reproduces a scale-17 graph with a 1 MB L2** -- 8x smaller, ~10x cheaper to simulate. Therefore:
- **Report overhead against MPKI**, not graph scale, and report the MPKI of every cell -- that is what makes a reduced-graph proxy defensible.
- **Shrink the LLC (`-L 256kB`)** to reach a realistic operating point rather than paying for a bigger graph; this makes the 60-cell matrix affordable.
- A low-MPKI number **understates** the overhead. Real GAP graphs sit at high MPKI.
- The 1 MB L2 is a config choice that moves the curve -- declare it.

Add a scale without rebuilding gem5 (this also audits sources):

```bash
make -C benchmark/GAP gem5-graphs GEM5_SCALE=17
make -C benchmark/GAP gem5-check-sources GEM5_SCALE=17
```

## Results (2026-07-14, corrected source + ROI-scoped statistics)

**Superseded / do not cite:** the earlier calibration on this page (91,542,366 / 91,548,027 ticks, +0.006184%, 136 L2 misses) is INVALID -- it was the empty BFS produced by `-r0`.

O3, one trial, GAP-chosen source, `-v`, worst die 193. All runs pass verification, complete exactly one ROI, and exit normally; all metrics are ROI-only. Scale-14 F1/S12 versus the clean baseline; the overhead fell ~6x as two design defects were fixed, so **quote only the last row** -- the others are the audit trail.

| configuration | Kron | Urand |
|---|---:|---:|
| legacy gate + 64-bit Bloom block *(as first measured)* | +0.621% | +0.536% |
| unified gate (dead-bank Bloom reject is fast) | +0.283% | +0.238% |
| **unified gate + 512-bit Bloom block**  **<- CURRENT** | **+0.102%** | **+0.071%** |
| *(repaired at L0: translation only, no lookup latency)* | +0.089% | +0.076% |

- F1/S12 overhead is essentially at the zero-latency floor. **But these are low-MPKI points; see the scale rule above before quoting them.**
- Kernel-only locality (scale 14, worst die): row-buffer hit rate 85.6% Kron / 68.5% Urand. Layer D dominates ROI repair traffic; A and C never fire.
- **Kron is not cheaper than Urand.** The old numbers said it was (+0.200% vs +0.500%) and credited Kron's locality; that came entirely from the empty-BFS bug. Kron does have better locality, but the slow path is set by the dead-bank rate (15/512 = 2.93% of banks) and the Bloom FP rate -- properties of the die and the filter, not the access pattern.

### Bloom-first lookup-latency sensitivity

- `--repair-lookup-latency N` sets both paths for a fixed-latency control. Production sensitivity uses `--repair-fast-lookup-latency F` with `--repair-slow-lookup-latency S`.
- The safe front gate checks dead-bank membership beside a blocked Bloom filter: only a live-bank Bloom reject uses F; dead-bank and Bloom-maybe requests use S. Dead-bank requests recheck Bloom after Layer D, because the translated bank/row may have an A/B/C entry.
- Charging **every** request the slow latency (fixed L12) is what produced the original 11.664% Urand penalty -- an all-request timing model, not the cost of rare repairs. The split path brings it under 1%.
- The slow-path fraction is **not** 0.1%: 15 of 512 banks are dead (2.93%) and every access mapped to one needs Layer D. ROI-only measurements are 5.25% (Kron) and 4.86% (Urand).
- The blocked Bloom uses **512-bit blocks** (8 x 64-bit words, read as ONE SRAM row), 16 bits/key, 8 probes -> 3,968 B and a measured 0.182% false-positive rate on worst die 193. The earlier 64-bit-block / 12-bit config measured 2.178% FP -- 7x the textbook formula -- because block occupancy is Poisson-spread and a block's FP rate is convex in occupancy, so overloaded blocks dominate. See `data.md` S11.4.
- Current CACTI 6.5 at 32 nm estimates the 8-KiB-capacity, 512-bit-row Bloom array at 0.183 ns access. Hash/mux/routing/PVT are excluded, so F1 is optimistic, F2 is the conservative bracket, and S12 remains an explicit slow-path assumption rather than a physical bound.
- `--repair-gate unified` (default) makes a dead-bank Bloom reject take the fast path, because Layer D reads no repair table. `legacy` charges every dead-bank access the slow latency. Both translate identical addresses; only the timing class differs.
