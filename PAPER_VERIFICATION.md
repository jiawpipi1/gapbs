# GAP paper verification

## Provenance

- Specification: `../1508.03619v4.pdf` (16 May 2017), SHA-256 `7a84108f196fcfc570432ea1fb4e35ae3f713bf06026c5a839f5a48d60228c16`.
- Reference source: <https://github.com/sbeamer/gapbs>, upstream release `v1.0`, commit `e767504cd438e4e9fb53adc892af5d156556df22`.
- Local branch: `paper-verified`, based directly on `v1.0` -- the version cited by reference [12] and the change log in the supplied paper.
- Source is C++11 and uses OpenMP, as described in paper section 3.

## Paper-to-code result

| Paper requirement | v1.0 evidence | Result |
|---|---|---|
| Six kernels: BFS, SSSP, PR, CC, BC, TC | `src/{bfs,sssp,pr,cc,bc,tc}.cc` | Match |
| BFS returns parents and uses direction optimization | `DOBFS`, `BFSVerifier` | Match |
| SSSP returns distances for positive weights and uses delta stepping | `DeltaStep`, weights generated in `[1,255]`, Dijkstra verifier | Match |
| PR uses damping 0.85 and stops below total error `1e-4` | `kDamp`, `PageRankPull`, `PRVerifier` | Match |
| CC computes weak components for directed inputs | v1.0 only traversed outgoing edges | **Mismatch found and fixed locally** |
| BC uses Brandes from four sources and normalizes scores | `Brandes`; benchmark uses `-i4` | Match |
| TC ignores direction and counts each triangle once | undirected input plus ordered intersection | Match |
| Twitter, Web, Road, Kron, and Urand inputs | `benchmark/bench.mk` | Match |
| Kron and Urand have `2^27` vertices and initial degree 16 | `-g27 -k16`, `-u27 -k16` | Match |
| Trial counts are BFS/SSSP 64, PR/CC 16, BC 16 x 4, TC 3 | `benchmark/bench.mk` | Match |
| Graph loading/building occurs outside each timed trial | `Builder::MakeGraph` precedes `BenchmarkKernel`; only the kernel call is timed | Match |
| Correctness checking exists for all kernels | six independent verifier paths | Match on focused tests |

### Local correctness fix

The paper requires weakly connected components for directed inputs. Unmodified v1.0 fails a two-vertex graph containing only `1 -> 0`, because the Shiloach-Vishkin loop reads only outgoing neighbors (the verifier reports this correctly). The local patch makes CC also visit incoming neighbors for directed graphs; `test/graphs/weak-directed.el` permanently covers the case. This is the only algorithm change relative to the pinned upstream tag:

```bash
git diff v1.0 -- src/cc.cc test/test.mk test/graphs/weak-directed.el
```

## Reproduce the verification

Use the system GCC toolchain that matches the v1.0 golden generator output: `/usr/bin/g++` 10.5.0 (Ubuntu 10.5.0-1ubuntu1~20.04).

```bash
cd /home/pitsaiyang/work/my_work/benchmark/GAP
make clean
make -j4 CXX=/usr/bin/g++
make test CXX=/usr/bin/g++
```

Expected result: `17 PASS`, including all six kernel verifiers and the directed weak-CC regression.

Do not generate serialized graphs with the Conda `gem5` compiler: it builds the source and passes all kernel verifiers, but its standard library generates 16103 edges for the `u10` golden test instead of the v1.0 expected 16104. Until that deterministic-generator difference is resolved, use `/usr/bin/g++`. A future gem5 binary may be compiled separately after loading a frozen serialized graph.

## What is not yet proven

- The five full paper datasets have not been downloaded or executed. Upstream estimates about 275 GB of build space and 64 GB of RAM.
- Scale-14 BFS on frozen Kron and Urand proxies now runs through gem5 and Ramulator2 with verification PASS. Full scale/workload/severity coverage is still open; see `GEM5_INTEGRATION.md` and the live workspace `claude.md`.
- A small graph such as `-g10` or `-u10` is a functional or simulation test, not a GAP-compliant benchmark result. Full compliance requires the paper graphs and trial counts above.
- Detailed gem5 simulation of the full graphs is unlikely to be tractable. Any reduced Web/Urand workload must be labeled a simulation proxy, use the same frozen graph for every repair-table condition, and must not be reported as a full GAP result.
- Bloom-first split-latency F1/F2 with S12 is implemented and measured. These are explicit sensitivity points, supported by an SRAM-only CACTI plausibility check, not physically proven translator bounds.

## Gate before gem5 integration (completed)

The GAP sources remain standalone in `benchmark/GAP`; gem5 executes the static GAP binaries without copying sources. The original pre-integration gate was: (1) freeze and checksum the serialized input graph; (2) choose a single-thread/parallel policy consistent with the simulated CPU; (3) compile an x86 SE-compatible workload binary with an explicit toolchain; (4) run the same binary and graph for the clean, F=0, median, p90, and worst real V512 repair tables; (5) label reduced graphs as simulation proxies, not paper-compliant GAP inputs.
