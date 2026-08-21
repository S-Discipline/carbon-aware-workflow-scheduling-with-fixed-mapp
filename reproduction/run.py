#!/usr/bin/env python3
"""Run a deterministic, downscaled reproduction of CaWoSched's core claims."""

from __future__ import annotations

import csv
import glob
import io
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "reproduction" / "build"
BINARY = BUILD / "multi_machine_scheduler"
PRIMARY_PREFIXES = (
    "atacseq200",
    "atacseq1000",
    "eager200",
    "eager1000",
    "methylseq200",
    "methylseq1000",
    "bacass",
)
PROFILE_PREFIXES = ("atacseq4000", "atacseq10000", "atacseq30000")
MODES = (
    ("baseline", "--baseline_only"),
    ("with_ls", None),
    ("without_ls", "--no_LS"),
)


def build() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["cmake", "-S", str(ROOT / "CaWoSched"), "-B", str(BUILD), "-DCMAKE_BUILD_TYPE=Release"],
        check=True,
    )
    subprocess.run(
        ["cmake", "--build", str(BUILD), "--parallel", str(min(8, os.cpu_count() or 1))],
        check=True,
    )


def profile_metadata(profile: Path) -> tuple[int, int]:
    tokens = profile.stem.split("_")
    return int(tokens[-4]), int(tokens[-1])


def instance_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for prefix in PRIMARY_PREFIXES:
        for cluster, graph_suffix, mapping_suffix in (
            ("small", "s1", "small"),
            ("large", "s2", "large"),
        ):
            graph = ROOT / "experiments" / "SchedulingGraphs" / f"{prefix}{graph_suffix}.dot"
            mapping = ROOT / "experiments" / "Mappings" / f"{prefix}_mapping_{mapping_suffix}.txt"
            profile_dir = ROOT / "experiments" / "Profiles" / f"{prefix}_{cluster}"
            if not graph.exists() or not mapping.exists() or not profile_dir.exists():
                continue
            profiles = sorted(profile_dir.glob("*.input"))
            deadlines = sorted({profile_metadata(p)[0] for p in profiles})
            for profile in profiles:
                deadline, scenario = profile_metadata(profile)
                rows.append(
                    {
                        "cohort": "primary",
                        "prefix": prefix,
                        "cluster": cluster,
                        "graph": graph,
                        "mapping": mapping,
                        "profile": profile,
                        "scenario": scenario,
                        "deadline_factor": (1.0, 1.5, 2.0, 3.0)[deadlines.index(deadline)],
                    }
                )

    for prefix in PROFILE_PREFIXES:
        cluster = "small"
        graph = ROOT / "experiments" / "SchedulingGraphs" / f"{prefix}s1.dot"
        mapping = ROOT / "experiments" / "Mappings" / f"{prefix}_mapping_small.txt"
        profile_dir = ROOT / "experiments" / "Profiles" / f"{prefix}_{cluster}"
        profiles = [p for p in sorted(profile_dir.glob("*.input")) if profile_metadata(p)[1] == 3]
        deadlines = sorted({profile_metadata(p)[0] for p in profiles})
        for profile in profiles:
            deadline, scenario = profile_metadata(profile)
            if deadline not in (deadlines[0], deadlines[-1]):
                continue
            rows.append(
                {
                    "cohort": "runtime_profile",
                    "prefix": prefix,
                    "cluster": cluster,
                    "graph": graph,
                    "mapping": mapping,
                    "profile": profile,
                    "scenario": scenario,
                    "deadline_factor": 1.0 if deadline == deadlines[0] else 3.0,
                }
            )
    return rows


def run_instance(instance: dict[str, object]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    instance_id = Path(instance["profile"]).stem
    for mode, flag in MODES:
        command = [
            str(BINARY),
            str(instance["graph"]),
            str(instance["mapping"]),
            str(instance["profile"]),
        ]
        if flag:
            command.append(flag)
        started = time.monotonic()
        completed = subprocess.run(command, check=True, text=True, capture_output=True)
        wall_seconds = time.monotonic() - started
        parsed = []
        for line in completed.stdout.splitlines():
            if not line or line.startswith("Variant,"):
                continue
            try:
                candidate = next(csv.reader([line]))
            except csv.Error:
                continue
            if len(candidate) == 10 and candidate[-1] in {"0", "1"}:
                parsed.append(candidate)
        if not parsed:
            raise RuntimeError(f"No result rows for {instance_id} mode={mode}: {completed.stdout[-1000:]}")
        for values in parsed:
            output.append(
                {
                    "cohort": instance["cohort"],
                    "instance": instance_id,
                    "workflow_family": str(instance["prefix"]).rstrip("0123456789"),
                    "task_scale": str(instance["prefix"]),
                    "cluster": instance["cluster"],
                    "scenario": instance["scenario"],
                    "deadline_factor": instance["deadline_factor"],
                    "mode": mode,
                    "variant": values[0],
                    "cost": int(values[7]),
                    "algorithm_time_ms": float(values[8]),
                    "valid": values[9] == "1",
                    "process_wall_seconds": round(wall_seconds, 6),
                }
            )
    return output


def safe_ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return 1.0 if numerator == 0 else None
    return numerator / denominator


def summarize(rows: list[dict[str, object]], wall_seconds: float) -> dict[str, object]:
    primary = [r for r in rows if r["cohort"] == "primary"]
    baseline = {r["instance"]: r for r in primary if r["mode"] == "baseline"}
    with_ls = [r for r in primary if r["mode"] == "with_ls"]
    without_ls = {(r["instance"], r["variant"]): r for r in primary if r["mode"] == "without_ls"}

    ratios_by_variant: dict[str, list[float]] = {}
    zero_denominators: dict[str, int] = {}
    for row in with_ls:
        ratio = safe_ratio(int(row["cost"]), int(baseline[row["instance"]]["cost"]))
        if ratio is None:
            zero_denominators[row["variant"]] = zero_denominators.get(row["variant"], 0) + 1
        else:
            ratios_by_variant.setdefault(str(row["variant"]), []).append(ratio)

    local_search_ratios: dict[str, list[float]] = {}
    for row in with_ls:
        plain_variant = str(row["variant"]).removesuffix("-LS")
        plain = without_ls[(row["instance"], plain_variant)]
        ratio = safe_ratio(int(row["cost"]), int(plain["cost"]))
        if ratio is not None:
            local_search_ratios.setdefault(plain_variant, []).append(ratio)

    rows_by_instance: dict[str, list[dict[str, object]]] = {}
    for row in with_ls:
        rows_by_instance.setdefault(str(row["instance"]), []).append(row)
    baseline_worst = 0
    presswr_best = 0
    for instance_id, heuristic_rows in rows_by_instance.items():
        costs = [int(r["cost"]) for r in heuristic_rows]
        baseline_cost = int(baseline[instance_id]["cost"])
        baseline_worst += int(baseline_cost >= max(costs))
        best_cost = min(costs + [baseline_cost])
        presswr = next(int(r["cost"]) for r in heuristic_rows if r["variant"] == "pressWR-LS")
        presswr_best += int(presswr == best_cost)

    deadline_presswr: dict[str, list[float]] = {}
    for row in with_ls:
        if row["variant"] != "pressWR-LS":
            continue
        ratio = safe_ratio(int(row["cost"]), int(baseline[row["instance"]]["cost"]))
        if ratio is not None:
            deadline_presswr.setdefault(str(row["deadline_factor"]), []).append(ratio)

    profile_rows = [r for r in rows if r["cohort"] == "runtime_profile" and r["mode"] == "with_ls"]
    return {
        "paper": "arXiv:2507.08725v2",
        "setup": {
            "primary_instances": len(baseline),
            "primary_workflow_scales": list(PRIMARY_PREFIXES),
            "runtime_profile_instances": len({r["instance"] for r in profile_rows}),
            "parallel_workers": min(8, os.cpu_count() or 1),
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "cmake": subprocess.check_output(["cmake", "--version"], text=True).splitlines()[0],
            "compiler": subprocess.check_output(["c++", "--version"], text=True).splitlines()[0],
            "wall_seconds": round(wall_seconds, 3),
            "gurobi_available": shutil.which("gurobi_cl") is not None,
        },
        "headline": {
            "median_heuristic_over_asap": {
                variant: round(statistics.median(values), 6)
                for variant, values in sorted(ratios_by_variant.items())
            },
            "paper_all_variants_approx": 0.6,
            "paper_pressWR_LS": 0.58,
            "baseline_worst_fraction": round(baseline_worst / len(rows_by_instance), 6),
            "paper_baseline_worst_fraction": 0.8401,
            "pressWR_best_fraction": round(presswr_best / len(rows_by_instance), 6),
            "paper_pressWR_best_fraction": 0.3447,
            "undefined_ratio_counts_baseline_zero": zero_denominators,
        },
        "local_search": {
            variant: {
                "mean_ratio": round(statistics.fmean(values), 6),
                "median_ratio": round(statistics.median(values), 6),
                "n": len(values),
            }
            for variant, values in sorted(local_search_ratios.items())
        },
        "deadline_sensitivity_pressWR_LS": {
            factor: round(statistics.median(values), 6)
            for factor, values in sorted(deadline_presswr.items(), key=lambda item: float(item[0]))
        },
        "runtime_profile": {
            scale: {
                "median_algorithm_time_ms": round(statistics.median(float(r["algorithm_time_ms"]) for r in profile_rows if r["task_scale"] == scale), 3),
                "max_algorithm_time_ms": round(max(float(r["algorithm_time_ms"]) for r in profile_rows if r["task_scale"] == scale), 3),
            }
            for scale in PROFILE_PREFIXES
        },
        "validity": {
            "rows": len(rows),
            "invalid_rows": sum(not bool(r["valid"]) for r in rows),
        },
    }


def main() -> None:
    print("REPRO_CONFIG " + json.dumps({
        "paper": "https://arxiv.org/abs/2507.08725",
        "upstream": "https://github.com/KIT-EAE/CaWoSched",
        "primary_prefixes": PRIMARY_PREFIXES,
        "runtime_profile_prefixes": PROFILE_PREFIXES,
        "modes": MODES,
    }, sort_keys=True))
    build()
    instances = instance_rows()
    started = time.monotonic()
    rows: list[dict[str, object]] = []
    workers = min(8, os.cpu_count() or 1)
    print(f"REPRO_PROGRESS instances={len(instances)} workers={workers}")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(run_instance, item): item for item in instances}
        completed_count = 0
        for future in as_completed(future_map):
            rows.extend(future.result())
            completed_count += 1
            if completed_count % 25 == 0 or completed_count == len(instances):
                print(f"REPRO_PROGRESS completed={completed_count}/{len(instances)}")
    elapsed = time.monotonic() - started
    rows.sort(key=lambda row: (str(row["cohort"]), str(row["instance"]), str(row["mode"]), str(row["variant"])))
    summary = summarize(rows, elapsed)
    print("RESULT_CSV_BEGIN")
    columns = list(rows[0])
    writer = csv.DictWriter(sys.stdout, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    print("RESULT_CSV_END")
    print("REPRO_SUMMARY_JSON_BEGIN")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print("REPRO_SUMMARY_JSON_END")
    if summary["validity"]["invalid_rows"]:
        raise SystemExit("One or more schedules were invalid")


if __name__ == "__main__":
    main()
