# gem5 integration -----------------------------------------------------#
# Builds serial static x86 binaries with gem5 ROI annotations. The graph
# generator is deliberately compiled with /usr/bin/g++ so v1.0's frozen
# synthetic graphs do not depend on the active Conda toolchain.

GEM5_ROOT ?= ../../gem5
GEM5_CXX ?= /usr/bin/g++
GEM5_SCONS ?= scons
GEM5_BIN_DIR ?= build/gem5
GEM5_GRAPH_DIR ?= benchmark/graphs/gem5
GEM5_SCALE ?= 14
GEM5_DEGREE ?= 16
GEM5_M5_DIR = $(GEM5_ROOT)/util/m5
GEM5_M5_LIB = $(GEM5_M5_DIR)/build/x86/out/libm5.a
GEM5_KERNEL_BINS = $(addprefix $(GEM5_BIN_DIR)/,$(KERNELS))
GEM5_GRAPH_FILES = \
	$(GEM5_GRAPH_DIR)/kron-s$(GEM5_SCALE)-d$(GEM5_DEGREE).sg \
	$(GEM5_GRAPH_DIR)/urand-s$(GEM5_SCALE)-d$(GEM5_DEGREE).sg
GEM5_FLAGS = -std=c++11 -O3 -Wall -Wno-unknown-pragmas -DGEM5_ROI \
	-I$(abspath $(GEM5_ROOT)/include) -static

.PHONY: gem5-ready gem5-build gem5-graphs gem5-check-sources gem5-clean
gem5-ready: gem5-build gem5-graphs gem5-check-sources

gem5-build: $(GEM5_KERNEL_BINS)

gem5-graphs: $(GEM5_GRAPH_FILES)

# Refuse to hand a graph to the simulator whose search source is degenerate.
# kron-s14 vertex 0 has degree 0, so `-r0` produced a BFS that scanned zero
# edges and still passed verification. Never pin a source with -r; let GAP's
# SourcePicker choose it (deterministic via kRandSeed, skips zero-degree).
gem5-check-sources: $(GEM5_BIN_DIR)/gem5_source_audit $(GEM5_GRAPH_FILES)
	@for g in $(GEM5_GRAPH_FILES); do \
		echo "== $$g"; \
		$(GEM5_BIN_DIR)/gem5_source_audit -f $$g || exit 1; \
	done
	@echo "gem5-check-sources: all frozen graphs have a non-degenerate source."

$(GEM5_M5_LIB):
	cd $(GEM5_M5_DIR) && $(GEM5_SCONS) build/x86/out/libm5.a

$(GEM5_BIN_DIR):
	mkdir -p $@

$(GEM5_GRAPH_DIR):
	mkdir -p $@

$(GEM5_BIN_DIR)/converter-host: src/converter.cc src/*.h | $(GEM5_BIN_DIR)
	$(GEM5_CXX) -std=c++11 -O3 -Wall -Wno-unknown-pragmas $< -o $@

# Host tool (not a simulated workload): links GAP's real SourcePicker/Builder.
$(GEM5_BIN_DIR)/gem5_source_audit: benchmark/gem5_source_audit.cc src/*.h \
		| $(GEM5_BIN_DIR)
	$(GEM5_CXX) -std=c++11 -O3 -Wall -Wno-unknown-pragmas -Isrc $< -o $@

$(GEM5_BIN_DIR)/%: src/%.cc src/*.h $(GEM5_M5_LIB) | $(GEM5_BIN_DIR)
	$(GEM5_CXX) $(GEM5_FLAGS) $< $(GEM5_M5_LIB) -o $@

$(GEM5_GRAPH_DIR)/kron-s$(GEM5_SCALE)-d$(GEM5_DEGREE).sg: \
		$(GEM5_BIN_DIR)/converter-host | $(GEM5_GRAPH_DIR)
	$< -g$(GEM5_SCALE) -k$(GEM5_DEGREE) -b $@

$(GEM5_GRAPH_DIR)/urand-s$(GEM5_SCALE)-d$(GEM5_DEGREE).sg: \
		$(GEM5_BIN_DIR)/converter-host | $(GEM5_GRAPH_DIR)
	$< -u$(GEM5_SCALE) -k$(GEM5_DEGREE) -b $@

gem5-clean:
	rm -rf $(GEM5_BIN_DIR) $(GEM5_GRAPH_DIR)
