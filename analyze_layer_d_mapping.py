#!/usr/bin/env python3
"""Compare clean, spread, and clustered Layer-D L0 ROI measurements.

The clustered run directories are the discovery roots. For every directory named
``gap-cluster-KERNEL-GRAPH-sSCALE-193-l0-clustered-l2LLC``, this script pairs the
published/original clean and spread directories produced by run_gem5_point.sh.
L0 is deliberate: it removes lookup latency and isolates address-placement effects.
"""

from __future__ import annotations

import argparse
import math
import re
import statistics
from dataclasses import dataclass
from pathlib import Path


CLUSTER_RE = re.compile(
    r"^gap-cluster-(?P<kernel>bfs|bc|cc|pr|sssp|tc)-"
    r"(?P<graph>kron|urand)-s(?P<scale>\d+)-193-l0-clustered-"
    r"l2(?P<llc>.+)$"
)
CLUSTER_F1_RE = re.compile(
    r"^gap-cluster-(?P<kernel>bfs|bc|cc|pr|sssp|tc)-"
    r"(?P<graph>kron|urand)-s(?P<scale>\d+)-193-f1s12-clustered-"
    r"l2(?P<llc>.+)$"
)
TICKS_RE = re.compile(r"ROI 0 end.*\((\d+) ticks\)")


@dataclass(frozen=True)
class Run:
    ticks: int
    row_hit_rate: float
    row_conflicts: int
    avg_read_latency: float
    channel_read_cv: float


def roi_block(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    start = "[w2w] ==== Ramulator2 statistics: ROI (kernel only) ===="
    end = "[w2w] ==== Ramulator2 statistics: SINCE LAST RESET"
    if text.count(start) != 1 or text.count(end) != 1:
        raise ValueError(f"expected exactly one ROI and tail block in {path}")
    return text.split(start, 1)[1].split(end, 1)[0]


def channel_values(block: str, key: str, cast=float) -> dict[int, float]:
    pattern = re.compile(rf"^\s+{re.escape(key)}_(\d+):\s+([^\s]+)\s*$", re.MULTILINE)
    values = {}
    for match in pattern.finditer(block):
        try:
            values[int(match.group(1))] = cast(match.group(2))
        except ValueError:
            # A channel with no requests may report -nan. It carries zero weight.
            values[int(match.group(1))] = math.nan
    if not values:
        raise ValueError(f"missing {key}_<channel> in ROI block")
    return values


def read_run(directory: Path) -> Run:
    simout_path = directory / "simout.txt"
    text = simout_path.read_text(encoding="utf-8")
    ticks_match = TICKS_RE.search(text)
    if not ticks_match:
        raise ValueError(f"missing ROI ticks in {simout_path}")
    block = roi_block(simout_path)
    hits = channel_values(block, "row_hits", int)
    misses = channel_values(block, "row_misses", int)
    conflicts = channel_values(block, "row_conflicts", int)
    reads = channel_values(block, "num_read_reqs", int)
    latencies = channel_values(block, "avg_read_latency", float)

    total_hits = sum(hits.values())
    total_misses = sum(misses.values())
    total_conflicts = sum(conflicts.values())
    row_accesses = total_hits + total_misses + total_conflicts
    total_reads = sum(reads.values())
    weighted_latency = sum(
        reads[ch] * latencies[ch]
        for ch in reads
        if reads[ch] and not math.isnan(latencies.get(ch, math.nan))
    ) / total_reads
    mean_reads = statistics.mean(reads.values())
    read_cv = statistics.pstdev(reads.values()) / mean_reads if mean_reads else 0.0
    return Run(
        ticks=int(ticks_match.group(1)),
        row_hit_rate=total_hits / row_accesses,
        row_conflicts=total_conflicts,
        avg_read_latency=weighted_latency,
        channel_read_cv=read_cv,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "m5out", nargs="?", type=Path,
        default=Path("/home/pitsaiyang/work/my_work/gem5/m5out"),
    )
    args = ap.parse_args()

    points = []
    for clustered_dir in sorted(args.m5out.iterdir()):
        match = CLUSTER_RE.match(clustered_dir.name)
        if not match or not (clustered_dir / "simout.txt").is_file():
            continue
        kernel, graph = match["kernel"], match["graph"]
        scale, llc = match["scale"], match["llc"]
        clean_dir = args.m5out / (
            f"gap-{kernel}-{graph}-s{scale}-clean-l0-unified-l2{llc}"
        )
        spread_dir = args.m5out / (
            f"gap-{kernel}-{graph}-s{scale}-193-l0-unified-l2{llc}"
        )
        if not (clean_dir / "simout.txt").is_file() or not (spread_dir / "simout.txt").is_file():
            print(f"SKIP {clustered_dir.name}: missing {clean_dir.name} or {spread_dir.name}")
            continue
        points.append((kernel, graph, scale, llc,
                       read_run(clean_dir), read_run(spread_dir), read_run(clustered_dir)))

    if not points:
        raise SystemExit("no complete clean/spread/clustered point found")

    print("| kernel | graph | LLC | mapping | ROI ticks | overhead vs clean | row-hit | "
          "row conflicts | avg read lat (cycles) | channel-read CV |")
    print("|---|---|---:|---|---:|---:|---:|---:|---:|---:|")
    for kernel, graph, _scale, llc, clean, spread, clustered in points:
        for name, run in (("clean", clean), ("spread", spread), ("clustered", clustered)):
            overhead = (run.ticks / clean.ticks - 1.0) * 100.0
            print(f"| `{kernel}` | {graph.capitalize()} | {llc} | {name} | "
                  f"{run.ticks:,} | {overhead:+.3f}% | {run.row_hit_rate*100:.3f}% | "
                  f"{run.row_conflicts:,} | {run.avg_read_latency:.3f} | "
                  f"{run.channel_read_cv*100:.2f}% |")
        spread_overhead = (spread.ticks / clean.ticks - 1.0) * 100.0
        clustered_overhead = (clustered.ticks / clean.ticks - 1.0) * 100.0
        reduction = (spread_overhead - clustered_overhead) / spread_overhead * 100.0
        print(f"<!-- {kernel}/{graph}/{llc}: translation overhead reduction "
              f"{reduction:.1f}% -->")

    point_index = {
        (kernel, graph, scale, llc): (clean, spread_l0, clustered_l0)
        for kernel, graph, scale, llc, clean, spread_l0, clustered_l0 in points
    }
    f1_rows = []
    for clustered_f1_dir in sorted(args.m5out.iterdir()):
        match = CLUSTER_F1_RE.match(clustered_f1_dir.name)
        if not match or not (clustered_f1_dir / "simout.txt").is_file():
            continue
        key = (match["kernel"], match["graph"], match["scale"], match["llc"])
        if key not in point_index:
            continue
        spread_f1_dir = args.m5out / (
            f"gap-{match['kernel']}-{match['graph']}-s{match['scale']}-"
            f"193-f1s12-unified-l2{match['llc']}"
        )
        if not (spread_f1_dir / "simout.txt").is_file():
            continue
        clean, spread_l0, clustered_l0 = point_index[key]
        f1_rows.append((key, clean, spread_l0, read_run(spread_f1_dir),
                        clustered_l0, read_run(clustered_f1_dir)))

    if f1_rows:
        print("\n| kernel | graph | LLC | mapping | translation | lookup | total F1/S12 | "
              "total reduction vs spread |")
        print("|---|---|---:|---|---:|---:|---:|---:|")
        for (kernel, graph, _scale, llc), clean, spread_l0, spread_f1, \
                clustered_l0, clustered_f1 in f1_rows:
            spread_translation = (spread_l0.ticks / clean.ticks - 1.0) * 100.0
            spread_total = (spread_f1.ticks / clean.ticks - 1.0) * 100.0
            clustered_translation = (clustered_l0.ticks / clean.ticks - 1.0) * 100.0
            clustered_total = (clustered_f1.ticks / clean.ticks - 1.0) * 100.0
            total_reduction = (spread_total - clustered_total) / spread_total * 100.0
            print(f"| `{kernel}` | {graph.capitalize()} | {llc} | spread | "
                  f"{spread_translation:+.3f}% | {spread_total-spread_translation:+.3f}% | "
                  f"{spread_total:+.3f}% | -- |")
            print(f"| `{kernel}` | {graph.capitalize()} | {llc} | clustered | "
                  f"{clustered_translation:+.3f}% | "
                  f"{clustered_total-clustered_translation:+.3f}% | "
                  f"{clustered_total:+.3f}% | {total_reduction:.1f}% |")


if __name__ == "__main__":
    main()
