// gem5_source_audit.cc -- guard against degenerate GAP search sources.
//
// WHY THIS EXISTS
// ---------------
// The scale-14 Kron calibration was originally run with `-r0`, forcing BFS to
// start at vertex 0. In kron-s14-d16, vertex 0 has degree 0 (23% of that
// graph's vertices are isolated), so BFS visited exactly one vertex, scanned
// zero edges, and still passed verification. Every Kron performance number
// derived from it was measuring an empty kernel.
//
// GAP's own SourcePicker already guards against this -- it redraws until it
// finds a non-zero-degree vertex -- but `-r <n>` bypasses that guard entirely
// (see benchmark.h: `if (given_source != -1) return given_source;`).
//
// This tool links the REAL SourcePicker and the REAL Builder, so it cannot
// drift from what the kernels actually do. It reports the source each frozen
// graph resolves to and how much of the graph that source can reach, and it
// FAILS (non-zero exit) on a degenerate source. Run it whenever graphs are
// regenerated or a source is pinned by hand.
//
// Usage:
//   gem5_source_audit -f graph.sg [-r N] [--min-reach FRACTION]
//
// Default --min-reach is 0.10: a source reaching under 10% of the graph is
// treated as degenerate for a memory-system study, because the kernel then
// never builds a working set large enough to exercise DRAM.

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <queue>
#include <vector>

#include "benchmark.h"
#include "builder.h"
#include "command_line.h"
#include "graph.h"

// Serial BFS reachability from `source`; also counts edges scanned.
static void Reach(const Graph &g, NodeID source, int64_t &reached,
                  int64_t &edges_scanned) {
  std::vector<bool> seen(g.num_nodes(), false);
  std::queue<NodeID> q;
  seen[source] = true;
  q.push(source);
  reached = 1;
  edges_scanned = 0;
  while (!q.empty()) {
    NodeID u = q.front();
    q.pop();
    for (NodeID v : g.out_neigh(u)) {
      edges_scanned++;
      if (!seen[v]) {
        seen[v] = true;
        reached++;
        q.push(v);
      }
    }
  }
}

int main(int argc, char *argv[]) {
  // Pull --min-reach out before GAP's CLI sees the argv (it rejects unknowns).
  double min_reach = 0.10;
  std::vector<char *> passthrough;
  for (int i = 0; i < argc; i++) {
    if (!strcmp(argv[i], "--min-reach") && i + 1 < argc) {
      min_reach = atof(argv[++i]);
    } else {
      passthrough.push_back(argv[i]);
    }
  }

  CLApp cli(static_cast<int>(passthrough.size()), passthrough.data(),
            "gem5 source audit");
  if (!cli.ParseArgs()) return -1;
  Builder b(cli);
  Graph g = b.MakeGraph();

  // Exactly what bfs.cc / sssp.cc / bc.cc do to choose their source.
  SourcePicker<Graph> sp(g, cli.start_vertex());
  NodeID source = sp.PickNext();

  int64_t degree = g.out_degree(source);
  int64_t reached = 0, edges_scanned = 0;
  Reach(g, source, reached, edges_scanned);

  const double reach_frac = static_cast<double>(reached) / g.num_nodes();
  const bool pinned = (cli.start_vertex() != -1);

  printf("source          : %ld  (%s)\n", static_cast<long>(source),
         pinned ? "PINNED via -r, bypasses GAP's zero-degree guard"
                : "chosen by GAP SourcePicker (deterministic, kRandSeed)");
  printf("out_degree      : %ld\n", static_cast<long>(degree));
  printf("vertices        : %ld reached of %ld (%.2f%%)\n",
         static_cast<long>(reached), static_cast<long>(g.num_nodes()),
         100.0 * reach_frac);
  printf("edges scanned   : %ld of %ld directed\n",
         static_cast<long>(edges_scanned), static_cast<long>(g.num_edges_directed()));

  if (degree == 0) {
    printf("VERDICT         : FAIL -- source is ISOLATED. The kernel will scan "
           "zero edges and still pass verification.\n");
    return 1;
  }
  if (reach_frac < min_reach) {
    printf("VERDICT         : FAIL -- source reaches only %.2f%% of the graph "
           "(min %.2f%%). Too small to exercise DRAM.\n",
           100.0 * reach_frac, 100.0 * min_reach);
    return 1;
  }
  printf("VERDICT         : PASS\n");
  return 0;
}
