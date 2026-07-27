#!/usr/bin/env python3
"""Parse paired clean/repaired ROI results from run_mpki_upperbound_sweep.sh."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


NAME_RE = re.compile(
    r"^gap-mpki-(?P<kernel>bfs|bc|cc|pr|sssp|tc)-"
    r"(?P<graph>kron|urand)-s(?P<scale>\d+)-"
    r"(?P<table>clean|193)-(?P<latency>l0|f1s12)-unified-"
    r"l2(?P<llc>[^-]+)-atomic32s32$"
)
TICKS_RE = re.compile(r"ROI 0 end.*\((\d+) ticks\)")


@dataclass(frozen=True)
class Run:
    kernel: str
    graph: str
    scale: int
    llc: str
    table: str
    ticks: int
    insts: int
    misses: int
    ipc: float

    @property
    def mpki(self) -> float:
        return self.misses * 1000.0 / self.insts


def first_stat(path: Path, key: str, cast):
    with path.open(encoding="utf-8") as src:
        for line in src:
            if line.startswith(key + " "):
                return cast(line.split()[1])
    raise ValueError(f"missing {key} in {path}")


def read_run(path: Path, match: re.Match[str]) -> Run:
    simout = (path / "simout.txt").read_text(encoding="utf-8")
    ticks_match = TICKS_RE.search(simout)
    if not ticks_match:
        raise ValueError(f"missing ROI ticks in {path}")
    if "ROI-only mode: stopping before the post-ROI verifier" not in simout:
        raise ValueError(f"not a completed ROI-only sweep run: {path}")
    stats = path / "stats.txt"
    return Run(
        kernel=match["kernel"],
        graph=match["graph"],
        scale=int(match["scale"]),
        llc=match["llc"],
        table=match["table"],
        ticks=int(ticks_match.group(1)),
        insts=first_stat(stats, "simInsts", int),
        misses=first_stat(stats, "system.l2cache.overallMisses::total", int),
        ipc=first_stat(stats, "system.cpu.ipc", float),
    )


def llc_order(value: str) -> int:
    number = int(re.match(r"\d+", value).group())
    return number * (1024 if value.endswith("MB") else 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "m5out", nargs="?",
        default="/home/pitsaiyang/work/my_work/gem5/m5out",
        type=Path,
    )
    ap.add_argument(
        "--check-data",
        type=Path,
        help="verify that Fault_yield/data.md S11.6 exactly matches parsed runs",
    )
    args = ap.parse_args()

    runs: dict[tuple[str, str, int, str, str], Run] = {}
    for path in sorted(args.m5out.iterdir()):
        match = NAME_RE.match(path.name)
        if match and path.is_dir():
            simout_path = path / "simout.txt"
            stats_path = path / "stats.txt"
            if not simout_path.is_file() or not stats_path.is_file():
                continue
            if "ROI-only mode: stopping before the post-ROI verifier" not in (
                simout_path.read_text(encoding="utf-8")
            ):
                continue
            run = read_run(path, match)
            key = (run.kernel, run.graph, run.scale, run.llc, run.table)
            runs[key] = run

    pairs = []
    incomplete = []
    bases = sorted({key[:4] for key in runs})
    for base in bases:
        clean = runs.get(base + ("clean",))
        repaired = runs.get(base + ("193",))
        if clean is None or repaired is None:
            incomplete.append(base)
            continue
        overhead = (repaired.ticks / clean.ticks - 1.0) * 100.0
        pairs.append((clean, repaired, overhead))

    print("| kernel | graph | scale | LLC | clean MPKI | clean IPC | overhead |")
    print("|---|---|---:|---:|---:|---:|---:|")
    for clean, _repaired, overhead in sorted(
        pairs,
        key=lambda p: (
            p[0].kernel, p[0].graph, p[0].scale, -llc_order(p[0].llc)
        ),
    ):
        print(
            f"| {clean.kernel} | {clean.graph} | {clean.scale} | {clean.llc} | "
            f"{clean.mpki:.3f} | {clean.ipc:.3f} | {overhead:+.3f}% |"
        )

    if args.check_data:
        data_text = args.check_data.read_text(encoding="utf-8")
        natural = data_text.split(
            "#### 11.6.1 Natural application-scale sweep", 1
        )[1].split("#### 11.6.2 Fixed-graph LLC stress sweep", 1)[0]
        stress = data_text.split(
            "#### 11.6.2 Fixed-graph LLC stress sweep", 1
        )[1].split("Reproduce with `benchmark/GAP/run_mpki_upperbound_sweep.sh`", 1)[0]

        natural_re = re.compile(
            r"^\| `(?P<kernel>bc|cc|pr|sssp|tc)` \| "
            r"(?P<graph>Kron|Urand) \| (?P<point>\d+) \| "
            r"(?P<mpki>\d+\.\d{3}) \| (?P<ipc>\d+\.\d{3}) \| "
            r"\+(?P<overhead>\d+\.\d{3})% \|$",
            re.MULTILINE,
        )
        stress_re = re.compile(
            r"^\| `(?P<kernel>bc|cc|pr|sssp|tc)` \| "
            r"(?P<graph>Kron|Urand) \| (?P<point>\d+) KiB \| "
            r"(?P<mpki>\d+\.\d{3}) \| (?P<ipc>\d+\.\d{3}) \| "
            r"\+(?P<overhead>\d+\.\d{3})% \|$",
            re.MULTILINE,
        )

        def rows_from_doc(block: str, pattern: re.Pattern[str]):
            return {
                (m["kernel"], m["graph"].lower(), m["point"]): (
                    m["mpki"], m["ipc"], m["overhead"]
                )
                for m in pattern.finditer(block)
            }

        actual_natural = rows_from_doc(natural, natural_re)
        actual_stress = rows_from_doc(stress, stress_re)
        expected_natural = {}
        expected_stress = {}
        for clean, _repaired, overhead in pairs:
            values = (f"{clean.mpki:.3f}", f"{clean.ipc:.3f}", f"{overhead:.3f}")
            if clean.llc == "1MB":
                expected_natural[(clean.kernel, clean.graph, str(clean.scale))] = values
            else:
                expected_stress[
                    (clean.kernel, clean.graph, str(llc_order(clean.llc)))
                ] = values
        if actual_natural != expected_natural:
            raise SystemExit("FAIL: data.md S11.6.1 differs from parsed natural runs")
        if actual_stress != expected_stress:
            raise SystemExit("FAIL: data.md S11.6.2 differs from parsed stress runs")
        print("\nPASS: data.md S11.6 exactly matches all 72 parsed pairs")

    if incomplete:
        print("\nINCOMPLETE PAIRS:")
        for key in incomplete:
            print("  " + " / ".join(map(str, key)))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
