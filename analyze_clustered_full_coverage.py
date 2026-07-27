#!/usr/bin/env python3
"""Validate and report clustered coverage against the current spread dataset.

The manifest is intentionally explicit. It covers the 34 formal cells in S11.1,
the 24 L0 decomposition cells that exist for spread, and the 72 current
atomic32B/s32 scale/stress pairs in S11.6. Twenty-two sweep points reuse a deeper
post-ROI-verified formal clustered run with identical parameters.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


TICKS_RE = re.compile(r"ROI 0 end.*\((\d+) ticks\)")


@dataclass(frozen=True, order=True)
class Point:
    kernel: str
    graph: str
    scale: int
    llc: str


def formal_points() -> list[Point]:
    points = []
    for kernel in ("bc", "bfs", "cc", "pr", "sssp", "tc"):
        scale = 13 if kernel == "tc" else 14
        llcs = ("1MB", "128kB") if kernel == "tc" else ("1MB", "256kB", "128kB")
        for graph in ("kron", "urand"):
            points.extend(Point(kernel, graph, scale, llc) for llc in llcs)
    assert len(points) == 34
    return points


def decomposition_points() -> list[Point]:
    points = [
        Point(kernel, graph, 13 if kernel == "tc" else 14, llc)
        for kernel in ("bc", "bfs", "cc", "pr", "sssp", "tc")
        for graph in ("kron", "urand")
        for llc in ("1MB", "128kB")
    ]
    assert len(points) == 24
    return points


def sweep_points() -> list[Point]:
    points = []
    for kernel in ("bc", "cc", "pr", "sssp"):
        for graph in ("kron", "urand"):
            points.extend(Point(kernel, graph, scale, "1MB") for scale in (14, 15, 16, 17))
    for graph in ("kron", "urand"):
        points.extend(Point("tc", graph, scale, "1MB") for scale in (10, 12, 13))
    for kernel in ("bc", "cc", "sssp"):
        for graph in ("kron", "urand"):
            points.extend(Point(kernel, graph, 14, llc) for llc in ("128kB", "64kB", "32kB"))
    for graph in ("kron", "urand"):
        for llc in ("256kB", "128kB", "64kB", "32kB"):
            points.append(Point("pr", graph, 14, llc))
            points.append(Point("tc", graph, 13, llc))
    assert len(points) == 72 and len(set(points)) == 72
    return points


def formal_name(p: Point, table: str, latency: str, clustered: bool = False) -> str:
    if clustered:
        return (f"gap-cluster-full-{p.kernel}-{p.graph}-s{p.scale}-193-{latency}-"
                f"unified-l2{p.llc}-atomic32s32")
    # BFS/1MB is the first corrected formal pair and predates the later explicit
    # LLC suffix convention. Keep those immutable result directories in place;
    # resolve their audited legacy names here instead of copying or renaming data.
    if p.kernel == "bfs" and p.llc == "1MB":
        if table == "clean":
            return f"gap-bfs-{p.graph}-s14-clean-l0"
        suffix = "-unified" if latency == "f1s12" else ""
        return f"gap-bfs-{p.graph}-s14-{table}-{latency}{suffix}"
    return (f"gap-{p.kernel}-{p.graph}-s{p.scale}-{table}-{latency}-"
            f"unified-l2{p.llc}")


def sweep_name(p: Point, table: str, clustered: bool = False) -> str:
    prefix = "gap-mpki-cluster" if clustered else "gap-mpki"
    latency = "f1s12" if table == "193" else "l0"
    return (f"{prefix}-{p.kernel}-{p.graph}-s{p.scale}-{table}-{latency}-"
            f"unified-l2{p.llc}-atomic32s32")


def is_formal_reuse(p: Point) -> bool:
    base_scale = 13 if p.kernel == "tc" else 14
    formal_llcs = {"1MB", "128kB"} if p.kernel == "tc" else {"1MB", "256kB", "128kB"}
    return p.scale == base_scale and p.llc in formal_llcs


def text_of(directory: Path) -> str:
    path = directory / "simout.txt"
    if not path.is_file():
        raise ValueError(f"missing {path}")
    return path.read_text(encoding="utf-8")


def ticks(directory: Path) -> int:
    match = TICKS_RE.search(text_of(directory))
    if not match:
        raise ValueError(f"missing ROI ticks in {directory}")
    return int(match.group(1))


def validate_run(directory: Path, *, clustered: bool, formal: bool) -> None:
    text = text_of(directory)
    if text.count("completed 1 ROI") != 1 or "Ramulator2 statistics: ROI" not in text:
        raise ValueError(f"incomplete ROI in {directory}")
    if formal:
        if "Verification:" not in text or not re.search(r"Verification:\s+PASS", text):
            raise ValueError(f"missing benchmark verification PASS in {directory}")
        if "ROI-only mode" in text:
            raise ValueError(f"formal run is ROI-only: {directory}")
    elif "ROI-only mode: stopping before the post-ROI verifier" not in text:
        raise ValueError(f"sweep run is not ROI-only: {directory}")
    if clustered:
        yaml_path = directory / "ramulator2_resolved.yaml"
        if not yaml_path.is_file() or not re.search(
            r"^\s*repair_d_mapping:\s*clustered\s*$",
            yaml_path.read_text(encoding="utf-8"), re.MULTILINE,
        ):
            raise ValueError(f"clustered mapping not pinned in {directory}")
    simerr = directory / "simerr.txt"
    if simerr.is_file() and re.search(
        r"(^|[^A-Za-z])(fatal|panic)([^A-Za-z]|$)",
        simerr.read_text(encoding="utf-8"), re.IGNORECASE,
    ):
        raise ValueError(f"fatal/panic in {simerr}")


def overhead(run_ticks: int, clean_ticks: int) -> float:
    return (run_ticks / clean_ticks - 1.0) * 100.0


def reduction(spread: float, clustered: float) -> float:
    return (spread - clustered) / spread * 100.0


def llc_key(llc: str) -> int:
    number = int(re.match(r"\d+", llc).group())
    return number * (1024 if llc.endswith("MB") else 1)


def point_label(p: Point) -> str:
    return f"{p.kernel}/{p.graph}/s{p.scale}/{p.llc}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "m5out", nargs="?", type=Path,
        default=Path("/home/pitsaiyang/work/my_work/gem5/m5out"),
    )
    ap.add_argument(
        "--check-data", type=Path,
        help="require every rendered measurement row to appear in data.md",
    )
    ap.add_argument(
        "--checkpoint", action="store_true",
        help="render only completed rows and list still-incomplete clustered runs",
    )
    args = ap.parse_args()
    root = args.m5out

    pending = []
    formal_rows = []
    for p in formal_points():
        clean_dir = root / formal_name(p, "clean", "l0")
        spread_dir = root / formal_name(p, "193", "f1s12")
        cluster_dir = root / formal_name(p, "193", "f1s12", clustered=True)
        validate_run(clean_dir, clustered=False, formal=True)
        validate_run(spread_dir, clustered=False, formal=True)
        try:
            validate_run(cluster_dir, clustered=True, formal=True)
        except ValueError as exc:
            if not args.checkpoint:
                raise
            pending.append(str(exc))
            continue
        clean_ticks, spread_ticks, cluster_ticks = map(ticks, (clean_dir, spread_dir, cluster_dir))
        formal_rows.append((p, clean_ticks, spread_ticks, cluster_ticks))

    decomp_rows = []
    for p in decomposition_points():
        clean_dir = root / formal_name(p, "clean", "l0")
        spread_l0_dir = root / formal_name(p, "193", "l0")
        spread_f1_dir = root / formal_name(p, "193", "f1s12")
        cluster_l0_dir = root / formal_name(p, "193", "l0", clustered=True)
        cluster_f1_dir = root / formal_name(p, "193", "f1s12", clustered=True)
        cluster_complete = True
        for directory, clustered in (
            (clean_dir, False), (spread_l0_dir, False), (spread_f1_dir, False),
            (cluster_l0_dir, True), (cluster_f1_dir, True),
        ):
            try:
                validate_run(directory, clustered=clustered, formal=True)
            except ValueError as exc:
                if not args.checkpoint:
                    raise
                pending.append(str(exc))
                cluster_complete = False
                break
        if not cluster_complete:
            continue
        decomp_rows.append((p, *(ticks(d) for d in (
            clean_dir, spread_l0_dir, spread_f1_dir, cluster_l0_dir, cluster_f1_dir
        ))))

    sweep_rows = []
    reused = 0
    for p in sweep_points():
        clean_dir = root / sweep_name(p, "clean")
        spread_dir = root / sweep_name(p, "193")
        validate_run(clean_dir, clustered=False, formal=False)
        validate_run(spread_dir, clustered=False, formal=False)
        cluster_complete = True
        if is_formal_reuse(p):
            cluster_dir = root / formal_name(p, "193", "f1s12", clustered=True)
            try:
                validate_run(cluster_dir, clustered=True, formal=True)
            except ValueError as exc:
                if not args.checkpoint:
                    raise
                pending.append(str(exc))
                cluster_complete = False
            reused += 1
        else:
            cluster_dir = root / sweep_name(p, "193", clustered=True)
            try:
                validate_run(cluster_dir, clustered=True, formal=False)
            except ValueError as exc:
                if not args.checkpoint:
                    raise
                pending.append(str(exc))
                cluster_complete = False
        if not cluster_complete:
            continue
        clean_ticks, spread_ticks, cluster_ticks = map(ticks, (clean_dir, spread_dir, cluster_dir))
        # Identical clean configurations from the formal and sweep datasets must
        # have identical ROI ticks before a formal clustered run can be reused.
        if is_formal_reuse(p):
            formal_clean_ticks = ticks(root / formal_name(p, "clean", "l0"))
            if clean_ticks != formal_clean_ticks:
                raise ValueError(f"formal/sweep clean tick mismatch for {p}")
        sweep_rows.append((p, clean_ticks, spread_ticks, cluster_ticks))
    assert reused == 22

    rendered_rows = []
    print(f"## FORMAL_F1_{len(formal_rows)}")
    print("| kernel | graph | scale | LLC | clean ticks | spread F1 | clustered F1 | "
          "spread overhead | clustered overhead | reduction |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for p, clean, spread, cluster in sorted(
        formal_rows, key=lambda r: (r[0].kernel, r[0].graph, -llc_key(r[0].llc))
    ):
        spread_ov, cluster_ov = overhead(spread, clean), overhead(cluster, clean)
        row = (f"| `{p.kernel}` | {p.graph.capitalize()} | {p.scale} | {p.llc} | "
               f"{clean:,} | {spread:,} | {cluster:,} | {spread_ov:+.3f}% | "
               f"{cluster_ov:+.3f}% | {reduction(spread_ov, cluster_ov):.1f}% |")
        rendered_rows.append(row)
        print(row)

    print(f"\n## DECOMPOSITION_{len(decomp_rows)}")
    print("| kernel | graph | LLC | mapping | translation | lookup | total |")
    print("|---|---|---:|---|---:|---:|---:|")
    for p, clean, spread_l0, spread_f1, cluster_l0, cluster_f1 in sorted(
        decomp_rows, key=lambda r: (r[0].kernel, r[0].graph, -llc_key(r[0].llc))
    ):
        for mapping, l0, f1 in (("spread", spread_l0, spread_f1),
                                ("clustered", cluster_l0, cluster_f1)):
            trans = overhead(l0, clean)
            total = overhead(f1, clean)
            row = (f"| `{p.kernel}` | {p.graph.capitalize()} | {p.llc} | {mapping} | "
                   f"{trans:+.3f}% | {total-trans:+.3f}% | {total:+.3f}% |")
            rendered_rows.append(row)
            print(row)

    print("\n## DECOMPOSITION_SHARE")
    print("| mapping | normalized translation sum | normalized lookup sum | "
          "translation share | lookup share |")
    print("|---|---:|---:|---:|---:|")
    for mapping, l0_index, f1_index in (
        ("spread", 2, 3),
        ("clustered", 4, 5),
    ):
        translation_sum = sum(
            overhead(row[l0_index], row[1]) for row in decomp_rows
        )
        lookup_sum = sum(
            overhead(row[f1_index], row[1]) - overhead(row[l0_index], row[1])
            for row in decomp_rows
        )
        total_sum = translation_sum + lookup_sum
        row = (f"| {mapping} | {translation_sum:+.6f}% | {lookup_sum:+.6f}% | "
               f"{translation_sum / total_sum * 100:.3f}% | "
               f"{lookup_sum / total_sum * 100:.3f}% |")
        rendered_rows.append(row)
        print(row)

    print(f"\n## SCALE_STRESS_{len(sweep_rows)}")
    print("| kernel | graph | scale | LLC | spread overhead | clustered overhead | reduction |")
    print("|---|---|---:|---:|---:|---:|---:|")
    for p, clean, spread, cluster in sorted(
        sweep_rows, key=lambda r: (
            r[0].kernel, r[0].graph, r[0].scale, -llc_key(r[0].llc)
        ),
    ):
        spread_ov, cluster_ov = overhead(spread, clean), overhead(cluster, clean)
        row = (f"| `{p.kernel}` | {p.graph.capitalize()} | {p.scale} | {p.llc} | "
               f"{spread_ov:+.3f}% | {cluster_ov:+.3f}% | "
               f"{reduction(spread_ov, cluster_ov):.1f}% |")
        rendered_rows.append(row)
        print(row)

    formal_cluster_ovs = [overhead(c, clean) for _p, clean, _s, c in formal_rows]
    formal_spread_ovs = [overhead(s, clean) for _p, clean, s, _c in formal_rows]
    sweep_cluster_ovs = [overhead(c, clean) for _p, clean, _s, c in sweep_rows]
    sweep_spread_ovs = [overhead(s, clean) for _p, clean, s, _c in sweep_rows]
    formal_worst = max(formal_rows, key=lambda r: overhead(r[3], r[1]))
    sweep_worst = max(sweep_rows, key=lambda r: overhead(r[3], r[1]))
    formal_best = min(formal_rows, key=lambda r: overhead(r[3], r[1]))
    sweep_best = min(sweep_rows, key=lambda r: overhead(r[3], r[1]))
    print("\n## SUMMARY")
    print(f"completed formal={len(formal_rows)} verified F1; "
          f"completed decomposition={len(decomp_rows)} verified points; "
          f"completed sweep={len(sweep_rows)}")
    print(f"formal spread range={min(formal_spread_ovs):+.3f}%..{max(formal_spread_ovs):+.3f}%")
    print(f"formal clustered range={min(formal_cluster_ovs):+.3f}%..{max(formal_cluster_ovs):+.3f}%")
    print(f"sweep spread range={min(sweep_spread_ovs):+.3f}%..{max(sweep_spread_ovs):+.3f}%")
    print(f"sweep clustered range={min(sweep_cluster_ovs):+.3f}%..{max(sweep_cluster_ovs):+.3f}%")
    print(f"formal clustered best={point_label(formal_best[0])} "
          f"{overhead(formal_best[3], formal_best[1]):+.3f}%")
    print(f"formal clustered worst={point_label(formal_worst[0])} "
          f"{overhead(formal_worst[3], formal_worst[1]):+.3f}%")
    print(f"sweep clustered best={point_label(sweep_best[0])} "
          f"{overhead(sweep_best[3], sweep_best[1]):+.3f}%")
    print(f"sweep clustered worst={point_label(sweep_worst[0])} "
          f"{overhead(sweep_worst[3], sweep_worst[1]):+.3f}%")
    if pending:
        print("\n## PENDING")
        for item in dict.fromkeys(pending):
            print(f"- {item}")
    if args.check_data:
        document = args.check_data.read_text(encoding="utf-8")
        missing = [row for row in rendered_rows if row not in document]
        if missing:
            print("\nMISSING DATA.MD ROWS:")
            print("\n".join(missing))
            raise SystemExit(f"FAIL: {len(missing)} clustered measurement rows missing from data.md")
        print(f"PASS: data.md contains all {len(rendered_rows)} rendered measurement rows")
    if pending:
        print(f"CHECKPOINT: {len(dict.fromkeys(pending))} clustered runs remain incomplete")
    else:
        print("PASS: exact clustered coverage manifest is complete")


if __name__ == "__main__":
    main()
