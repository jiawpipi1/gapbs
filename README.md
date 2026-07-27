GAP Benchmark Suite [![Build Status](https://travis-ci.org/sbeamer/gapbs.svg)](https://travis-ci.org/sbeamer/gapbs)
===================

Workspace note: this checkout is based on the paper-cited `v1.0` release. See
[`PAPER_VERIFICATION.md`](PAPER_VERIFICATION.md) for the exact revision, the
paper-to-code audit, the local weak-CC correctness fix, and the boundary between
a GAP-compliant run and a reduced gem5 simulation workload.

Reference implementation of the [GAP](http://gap.cs.berkeley.edu/) [Benchmark Suite](http://gap.cs.berkeley.edu/benchmark.html): a portable high-performance baseline that only requires a C++11 compiler. It uses OpenMP for parallelism, but can be compiled without OpenMP to run serially. Details are in the [specification](http://arxiv.org/abs/1508.03619). The suite standardizes graph-processing evaluations (kernels, input graphs, evaluation methodology) so research efforts are comparable; because these baselines are representative of state-of-the-art performance, new contributions should outperform them to demonstrate an improvement.

Kernels Included
----------------
+ Breadth-First Search (BFS)
+ Single-Source Shortest Paths (SSSP)
+ PageRank (PR)
+ Connected Components (CC)
+ Betweenness Centrality (BC)
+ Triangle Counting (TC)


Quick Start
-----------

    $ make                 # build the project
    $ CXX=g++-7 make       # override the default C++ compiler
    $ make test            # test the build
    $ ./bfs -g 10 -n 1     # run BFS on 1,024 vertices for 1 iteration

Additional command line flags can be found with `-h`


Graph Loading
-------------

All of the binaries use the same command-line options for loading graphs:
+ `-g 20` generates a Kronecker graph with 2^20 vertices (Graph500 specifications)
+ `-u 20` generates a uniform random graph with 2^20 vertices (degree 16)
+ `-f graph.el` loads graph from file graph.el
+ `-sf graph.el` symmetrizes graph loaded from file graph.el

Formats understood by the graph loading infrastructure:
+ `.el` plain-text edge-list with an edge per line as _node1_ _node2_
+ `.wel` plain-text weighted edge-list with an edge per line as _node1_ _node2_ _weight_
+ `.gr` [9th DIMACS Implementation Challenge](http://www.dis.uniroma1.it/challenge9/download.shtml) format
+ `.graph` Metis format (used in [10th DIMACS Implementation Challenge](http://www.cc.gatech.edu/dimacs10/index.shtml))
+ `.mtx` [Matrix Market](http://math.nist.gov/MatrixMarket/formats.html) format
+ `.sg` serialized pre-built graph (use `converter` to make)
+ `.wsg` weighted serialized pre-built graph (use `converter` to make)


Executing the Benchmark
-----------------------

The makefile-based flow below automates fetching and building the input graphs. It is a convenience, not a requirement: anything complying with the [specification](http://arxiv.org/abs/1508.03619) is allowed (for example, storing input graphs in fewer formats to save disk space at the cost of longer loading/conversion times).

__*Warning:*__ A full run of this benchmark can be demanding and should probably not be done on a laptop. Building the input graphs requires about 275 GB of disk space and 64 GB of RAM, and can take up to 8 hours depending on filesystem and internet bandwidth. Once the input graphs are built, you can delete `gapbs/benchmark/graphs/raw` to free up some disk space. Executing the benchmark itself will require only a few hours.

    $ make bench-graphs    # build the input graphs

    $ make bench-run       # execute the benchmark suite


How to Cite
-----------

Please cite this code by the benchmark specification:

Scott Beamer, Krste Asanović, David Patterson. [*The GAP Benchmark Suite*](http://arxiv.org/abs/1508.03619). arXiv:1508.03619 [cs.DC], 2015.
