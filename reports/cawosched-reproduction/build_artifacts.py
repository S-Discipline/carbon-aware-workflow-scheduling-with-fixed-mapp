#!/usr/bin/env python3
"""Extract one OpenResearch run log and build publication-ready evidence."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import subprocess
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


BLUE = "#3568A8"
BLUE_DARK = "#24466F"
BLUE_LIGHT = "#A9C6E8"
GOLD = "#C58A22"
GOLD_LIGHT = "#E8C98F"
INK = "#20252B"
GREY = "#66717D"
GRID = "#D9DEE5"
PAPER = "#F7F9FB"


def extract_between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0].strip()


def fetch(run_id: str) -> tuple[list[dict[str, str]], dict]:
    result = subprocess.run(
        ["orx", "logs", run_id, "--bytes", "1000000"],
        check=True,
        text=True,
        capture_output=True,
    )
    rows = list(csv.DictReader(extract_between(result.stdout, "RESULT_CSV_BEGIN", "RESULT_CSV_END").splitlines()))
    summary = json.loads(extract_between(result.stdout, "REPRO_SUMMARY_JSON_BEGIN", "REPRO_SUMMARY_JSON_END"))
    return rows, summary


def ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return 1.0 if numerator == 0 else None
    return numerator / denominator


def prepare(rows: list[dict[str, str]], summary: dict, run_id: str) -> dict:
    for row in rows:
        row["cost"] = int(row["cost"])
        row["algorithm_time_ms"] = float(row["algorithm_time_ms"])
        row["deadline_factor"] = float(row["deadline_factor"])
        row["scenario"] = int(row["scenario"])
        row["valid"] = row["valid"] == "True"

    primary = [row for row in rows if row["cohort"] == "primary"]
    baseline = {row["instance"]: row for row in primary if row["mode"] == "baseline"}
    with_ls = [row for row in primary if row["mode"] == "with_ls"]
    without_ls = {(row["instance"], row["variant"]): row for row in primary if row["mode"] == "without_ls"}

    deadline_slackw = defaultdict(list)
    for observed in with_ls:
        if observed["variant"] != "slackW-LS":
            continue
        value = ratio(observed["cost"], baseline[observed["instance"]]["cost"])
        if value is not None:
            deadline_slackw[observed["deadline_factor"]].append(value)

    local_search_matched = {}
    for variant in ("slackR", "slackWR", "pressR", "pressWR"):
        values = []
        for observed in with_ls:
            if observed["variant"] != f"{variant}-LS" or observed["workflow_family"] not in {"atacseq", "bacass"}:
                continue
            plain = without_ls[(observed["instance"], variant)]
            value = ratio(observed["cost"], plain["cost"])
            if value is not None:
                values.append(value)
        local_search_matched[variant] = {
            "mean_ratio": statistics.fmean(values),
            "median_ratio": statistics.median(values),
            "n": len(values),
        }

    heatmap = {}
    for scenario in range(1, 5):
        for deadline in (1.0, 1.5, 2.0, 3.0):
            values = []
            for observed in with_ls:
                if observed["variant"] != "pressWR-LS" or observed["scenario"] != scenario or observed["deadline_factor"] != deadline:
                    continue
                value = ratio(observed["cost"], baseline[observed["instance"]]["cost"])
                if value is not None:
                    values.append(value)
            heatmap[f"S{scenario}|{deadline:g}x"] = statistics.median(values)

    best_ratios = []
    grouped = defaultdict(list)
    for observed in with_ls:
        grouped[observed["instance"]].append(observed)
    for instance, candidates in grouped.items():
        best = min(item["cost"] for item in candidates)
        value = ratio(best, baseline[instance]["cost"])
        if value is not None:
            best_ratios.append(value)

    enriched = {
        "run_id": run_id,
        "paper_claims": {
            "median_heuristic_over_asap_approx": 0.60,
            "pressWR_LS_over_asap": 0.58,
            "baseline_worst_fraction": 0.8401,
            "pressWR_best_fraction": 0.3447,
            "slackW_LS_3x_over_asap": 0.15,
            "local_search_mean_ratio": {"slackR": 0.25, "slackWR": 0.25, "pressR": 0.25, "pressWR": 0.23},
        },
        "observed": summary,
        "matched_atacseq_bacass_local_search": local_search_matched,
        "matched_deadline_slackW_LS": {
            f"{factor:g}x": statistics.median(values)
            for factor, values in sorted(deadline_slackw.items())
        },
        "pressWR_scenario_deadline_medians": heatmap,
        "best_heuristic_over_asap": {
            "median": statistics.median(best_ratios),
            "q1": np.quantile(best_ratios, 0.25).item(),
            "q3": np.quantile(best_ratios, 0.75).item(),
            "n": len(best_ratios),
        },
        "compute": {
            "backend": "ssh",
            "instance": "Vast.ai RTX 3090 standalone instance (CPU used)",
            "listed_price_usd_per_hour": 0.12,
            "measured_wall_seconds": summary["setup"]["wall_seconds"],
            "estimated_run_cost_usd": summary["setup"]["wall_seconds"] / 3600 * 0.12,
        },
        "data_quality": {
            "expected_rows": 224 * 17 + 6 * 17,
            "observed_rows": len(rows),
            "unique_result_keys": len(
                {(row["cohort"], row["instance"], row["mode"], row["variant"]) for row in rows}
            ),
            "invalid_rows": sum(not row["valid"] for row in rows),
            "primary_instances": len(baseline),
            "primary_zero_cost_baselines": sum(row["cost"] == 0 for row in baseline.values()),
        },
        "standard_assessment": {
            "grade": "C",
            "conclusion": "partial reproduction success",
            "confidence": "medium",
            "relative_difference": {
                "pressWR_LS_headline": abs(summary["headline"]["median_heuristic_over_asap"]["pressWR-LS"] - 0.58) / 0.58,
                "baseline_worst_fraction": abs(summary["headline"]["baseline_worst_fraction"] - 0.8401) / 0.8401,
                "pressWR_best_fraction": abs(summary["headline"]["pressWR_best_fraction"] - 0.3447) / 0.3447,
                "slackW_LS_3x": abs(statistics.median(deadline_slackw[3.0]) - 0.15) / 0.15,
                "local_search": {
                    variant: abs(local_search_matched[variant]["mean_ratio"] - paper) / paper
                    for variant, paper in {"slackR": 0.25, "slackWR": 0.25, "pressR": 0.25, "pressWR": 0.23}.items()
                },
            },
        },
    }
    return enriched


def style_axes(ax, title: str, subtitle: str) -> None:
    ax.set_title(title, loc="left", color=INK, fontsize=15, fontweight="bold", pad=22)
    ax.text(0, 1.025, subtitle, transform=ax.transAxes, color=GREY, fontsize=9, va="bottom")
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GRID)
    ax.tick_params(colors=GREY, labelsize=9)
    ax.set_facecolor("white")


def save(fig, path: Path) -> None:
    fig.patch.set_facecolor("white")
    fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def headline(summary: dict, path: Path) -> None:
    values = summary["headline"]["median_heuristic_over_asap"]
    ordered = sorted(values, key=values.get, reverse=True)
    fig, ax = plt.subplots(figsize=(9.2, 5.5))
    colors = [GOLD if name == "pressWR-LS" else BLUE for name in ordered]
    bars = ax.barh(ordered, [values[name] for name in ordered], color=colors, edgecolor=BLUE_DARK, linewidth=0.6)
    ax.axvline(0.60, color=INK, linestyle="--", linewidth=1.4, label="Paper: ≈0.60 overall")
    ax.scatter([0.58], [ordered.index("pressWR-LS")], color=INK, marker="D", s=45, zorder=4, label="Paper pressWR-LS: 0.58")
    for bar, name in zip(bars, ordered):
        ax.text(bar.get_width() + 0.012, bar.get_y() + bar.get_height() / 2, f"{values[name]:.3f}", va="center", color=INK, fontsize=9)
    ax.set_xlim(0, 0.72)
    ax.set_xlabel("Median carbon cost ÷ ASAP cost (lower is better)", color=GREY)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.legend(
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.12),
        ncol=2,
        fontsize=9,
    )
    style_axes(
        ax,
        "Direction matches, but the exact headline differs by 13.3%",
        "224 stratified instances; pressWR-LS observed 0.503 vs paper 0.580",
    )
    save(fig, path)


def deadline(enriched: dict, path: Path) -> None:
    values = enriched["matched_deadline_slackW_LS"]
    labels = ["1×", "1.5×", "2×", "3×"]
    y = [values[key] for key in ("1x", "1.5x", "2x", "3x")]
    fig, ax = plt.subplots(figsize=(8.8, 4.8))
    bars = ax.bar(labels, y, color=[BLUE, BLUE, BLUE, GOLD], edgecolor=BLUE_DARK, linewidth=0.6, width=0.62)
    for bar, value in zip(bars, y):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.025, f"{value:.3f}", ha="center", color=INK, fontsize=10)
    ax.set_ylim(0, 1.0)
    ax.set_ylabel("Median slackW-LS cost ÷ ASAP cost", color=GREY)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    style_axes(
        ax,
        "Deadline trend matches the paper",
        "Exact 3× comparison: observed slackW-LS 0.148 vs paper 0.150",
    )
    save(fig, path)


def local_search(enriched: dict, path: Path) -> None:
    variants = ["slackR", "slackWR", "pressR", "pressWR"]
    observed = [enriched["matched_atacseq_bacass_local_search"][name]["mean_ratio"] for name in variants]
    paper = [enriched["paper_claims"]["local_search_mean_ratio"][name] for name in variants]
    positions = np.arange(len(variants))
    fig, ax = plt.subplots(figsize=(9.0, 5.0))
    width = 0.34
    left = ax.bar(positions - width / 2, paper, width, label="Paper", color=GOLD_LIGHT, edgecolor=GOLD)
    right = ax.bar(positions + width / 2, observed, width, label="Observed", color=BLUE, edgecolor=BLUE_DARK)
    for bars in (left, right):
        for bar in bars:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.025, f"{bar.get_height():.2f}", ha="center", color=INK, fontsize=9)
    ax.set_xticks(positions, variants)
    ax.set_ylim(0, 1.08)
    ax.set_ylabel("Mean with-LS cost ÷ without-LS cost", color=GREY)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="upper left")
    style_axes(ax, "Local-search improvement", "Paper subset vs 96-instance downscaled atacseq + bacass cohort; lower is better")
    save(fig, path)


def runtime(summary: dict, path: Path) -> None:
    scales = ["4k", "10k", "30k"]
    keys = ["atacseq4000", "atacseq10000", "atacseq30000"]
    seconds = [summary["runtime_profile"][key]["median_algorithm_time_ms"] / 1000 for key in keys]
    fig, ax = plt.subplots(figsize=(8.8, 4.8))
    bars = ax.bar(scales, seconds, color=[BLUE_LIGHT, BLUE, GOLD], edgecolor=BLUE_DARK, linewidth=0.6, width=0.62)
    ax.set_yscale("log")
    for bar, value in zip(bars, seconds):
        label = f"{value:.1f}s" if value < 60 else f"{value / 60:.1f}m"
        ax.text(bar.get_x() + bar.get_width() / 2, value * 1.12, label, ha="center", color=INK, fontsize=10)
    ax.set_ylabel("Median per-variant scheduler time (log scale)", color=GREY)
    ax.yaxis.grid(True, which="both", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    style_axes(ax, "Scheduler runtime by workflow size", "Six atacseq profiles on the reproduction host; medians across algorithm variants")
    save(fig, path)


def robustness(enriched: dict, path: Path) -> None:
    factors = [1.0, 1.5, 2.0, 3.0]
    matrix = np.array([[enriched["pressWR_scenario_deadline_medians"][f"S{s}|{factor:g}x"] for factor in factors] for s in range(1, 5)])
    fig, ax = plt.subplots(figsize=(8.8, 5.0))
    image = ax.imshow(matrix, vmin=0, vmax=1, cmap="Blues", aspect="auto")
    for row in range(matrix.shape[0]):
        for col in range(matrix.shape[1]):
            color = "white" if matrix[row, col] > 0.55 else INK
            ax.text(col, row, f"{matrix[row, col]:.2f}", ha="center", va="center", color=color, fontsize=10, fontweight="bold")
    ax.set_xticks(range(4), ["1×", "1.5×", "2×", "3×"])
    ax.set_yticks(range(4), ["S1", "S2", "S3", "S4"])
    ax.set_xlabel("Deadline factor", color=GREY)
    ax.set_ylabel("Green-power scenario", color=GREY)
    colorbar = fig.colorbar(image, ax=ax, shrink=0.78)
    colorbar.set_label("Median pressWR-LS ÷ ASAP", color=GREY)
    style_axes(
        ax,
        "Energy-profile behavior is not robustly reproduced",
        "224-instance diagnostic; upstream large-cluster filenames are asymmetric",
    )
    save(fig, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    images = args.output / "images"
    images.mkdir(exist_ok=True)
    rows, summary = fetch(args.run_id)
    enriched = prepare(rows, summary, args.run_id)

    with (args.output / "results.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    (args.output / "summary.json").write_text(json.dumps(enriched, indent=2, sort_keys=True) + "\n")

    headline(summary, images / "headline-result.png")
    deadline(enriched, images / "deadline-sensitivity.png")
    local_search(enriched, images / "local-search-gap.png")
    runtime(summary, images / "runtime-scaling.png")
    robustness(enriched, images / "robustness-heatmap.png")
    print(json.dumps({"rows": len(rows), "summary": enriched}, indent=2))


if __name__ == "__main__":
    main()
