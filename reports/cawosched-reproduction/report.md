# CaWoSched: a claim-by-claim reproduction on a stratified workflow cohort

![Eight CaWoSched heuristic variants use roughly half the carbon cost of ASAP on the reproduction cohort](images/headline-result.png)

The strongest observed result is straightforward: every tested CaWoSched heuristic reduced median carbon cost relative to the earliest-start (ASAP) schedule. The paper's highlighted `pressWR-LS` ratio is 0.58; this run observed 0.503 on 224 stratified instances. Lower is better, so the direction and magnitude align, although the reproduction cohort is smaller and differently sampled.

## Technical summary

The paper asks whether a workflow whose tasks are already assigned to processors can be shifted in time—without violating dependencies or a deadline—to consume more low-carbon energy. Its answer is a family of greedy schedulers, optionally followed by local search. We compiled the authors' C++ implementation and evaluated the ASAP baseline, eight local-search variants, and their eight no-local-search counterparts using the repository's own workflows, mappings, and carbon profiles.

| Empirical claim | Paper result | Observed result | Assessment |
|---|---:|---:|---|
| Heuristics reduce carbon cost versus ASAP | median ratio ≈0.60; `pressWR-LS` 0.58 | all medians 0.456–0.590; `pressWR-LS` 0.503 | **Aligned** on the stratified cohort |
| ASAP is usually the worst schedule | 84.01% of instances | 95.98% | **Aligned**; effect is stronger here |
| `pressWR-LS` is frequently best-ranked | 34.47% | 39.73% | **Aligned** |
| More deadline flexibility improves savings | most flexible `slackW` ratio ≈0.15 | `pressWR-LS`: 0.822 at 1× to 0.156 at 3× | **Aligned** in direction and endpoint magnitude |
| Local search materially improves its starting heuristic | mean with/without ratios 0.23–0.25 for four reported variants | 0.879–0.932 on the matched 96-instance subset | **Inconclusive under this setup**; improvement is much weaker |
| Large workflows finish in seconds to several minutes | up to several minutes at 30k tasks | median 26.4 min, maximum 35.6 min at 30k | **Partially aligned** on scaling; absolute runtime diverges |
| Heuristics approach the ILP optimum on small cases | near-optimal, sometimes exact | not measured; Gurobi unavailable | **Not attempted** |

The formal run took 27,846 seconds (7 h 44 min of measured harness wall time; 7 h 47 min at the orchestration layer) on a standalone Vast.ai RTX 3090 instance at a listed rate of \$0.12/hour, for an estimated shared-instance cost of \$0.93. The scheduler is CPU-only, so the 3090 was present but unused. All 3,910 emitted result rows passed the scheduler's validity check.

## What was tested

The paper reports 1,088 simulations per algorithm: two cluster sizes, 34 workflow sizes, 16 carbon/deadline profiles. This reproduction deliberately downscaled the headline evaluation to 224 instances while retaining the important axes:

- seven workflow/scale groups: `atacseq200`, `atacseq1000`, `eager200`, `eager1000`, `methylseq200`, `methylseq1000`, and `bacass`;
- small and large cluster mappings;
- four repository scenarios and four deadline levels;
- ASAP, eight heuristics with local search, and the same eight without it;
- six additional runtime probes at 4k, 10k, and 30k tasks.

The primary metric is

$$
\text{relative carbon cost}=\frac{\text{heuristic carbon cost}}{\text{ASAP carbon cost}},
$$

so 0.50 means half the ASAP carbon cost. Ties count as “worst” and “best,” matching the comparison used by the reproduction harness. There were no undefined ratios caused by a zero-cost ASAP denominator.

## Implementation path

The repository already contains the complete scheduling implementation. The smallest reproduction-specific addition was a deterministic harness: it discovers a stratified set of official inputs, compiles the release binary, invokes the same executable three ways, validates every emitted row, and prints machine-readable CSV plus a JSON summary.

```text
workflow DAG + fixed mapping + carbon/deadline profile
                         │
                         ▼
          multi_machine_scheduler (C++17)
             ├── ASAP baseline
             ├── 8 greedy variants + local search
             └── 8 matching variants without local search
                         │
                         ▼
       validity, carbon cost, algorithm time → summary
```

The consequential command path in the scheduler is compact:

```cpp
if (baseline_only) scheduler.compute_EST_schedule();
else if (no_LS)    pressWR(false, result_pressWR, ...);
else               pressWR(true,  result_pressWR, ...);
```

The formal experiment command was exactly:

```bash
bash reproduction/run.sh
```

The raw normalized evidence is in [results.csv](results.csv), the derived statistics are in [summary.json](summary.json), and [build_artifacts.py](build_artifacts.py) regenerates every figure from the run log.

## Carbon savings and deadline flexibility

![The pressWR-LS carbon ratio falls as the deadline becomes more flexible](images/deadline-sensitivity.png)

At the tightest 1× deadline, `pressWR-LS` used a median 82.2% of ASAP's carbon cost. At 1.5×, 2×, and 3×, the ratio was 45.7%, 40.2%, and 15.6%. This is the mechanism the paper relies on: slack in the deadline lets the scheduler move work toward intervals with more green-energy availability.

ASAP was tied for the highest carbon cost in 95.98% of the 224 primary instances, compared with 84.01% in the paper. `pressWR-LS` was tied for best in 39.73%, compared with 34.47%. These rank-based checks avoid relying only on the median.

## Local search: a weaker effect in this cohort

![Observed local-search ratios remain close to one, unlike the paper's approximately 0.25 ratios](images/local-search-gap.png)

For the paper-comparable `atacseq` plus `bacass` subset, local search lowered cost only modestly: mean with/without ratios were 0.879 for `slackR`, 0.922 for `slackWR`, 0.932 for `pressR`, and 0.923 for `pressWR`. The paper reports 0.25, 0.25, 0.25, and 0.23, respectively, on a cohort of more than 400 experiments per variant.

This run therefore did not show the reported size of the local-search effect. The most relevant uncertainty is cohort mismatch: only 96 matched cases were available here, with far fewer workflow scales and no reconstructed paper sampling manifest. The direction is still favorable—all four mean ratios are below one—but the magnitude is not comparable enough for a stronger conclusion.

## Runtime scaling

![Runtime grows sharply from 4k to 30k task workflows](images/runtime-scaling.png)

Median per-variant runtime rose from 22.2 seconds at 4k tasks to 2.4 minutes at 10k and 26.4 minutes at 30k; the slowest 30k result took 35.6 minutes. The paper's qualitative claim that cost grows sharply with workflow size is supported, but its “up to several minutes” absolute runtime was not observed on this machine. The reproduction ran eight independent instances concurrently on a small CPU allocation, so contention and host differences are plausible explanations; the GPU cannot accelerate this C++ scheduler.

## Robustness and negative control

![Median pressWR-LS ratios across repository scenarios and deadlines](images/robustness-heatmap.png)

The deadline effect is not uniform. Repository scenario S1 is a useful negative control: `pressWR-LS` equals ASAP at every deadline. S2–S4 show progressively large savings at flexible deadlines, reaching ratios of 0.083, 0.375, and 0.031 at 3×. Scenario labels are filename suffixes, and some large-cluster filenames are inconsistent upstream, so this heatmap should be read as a robustness diagnostic rather than a physical interpretation of scenario identity.

## Limits and remaining work

The reproduction evaluates the central heuristic-versus-ASAP claim, deadline sensitivity, ranking, local search, and runtime. It does not rerun the paper's proofs for the polynomial one-processor case or NP-hard multi-processor case. It also does not test the exact ILP comparison because a licensed Gurobi installation was unavailable.

A full-scale reproduction would still need the paper's exact 34-workflow × 16-profile sampling manifest, all 1,088 instances per algorithm, isolated CPU measurements, and a Gurobi-enabled small-instance run. Repeating the local-search comparison on that exact cohort is the highest-value next experiment.

## Assessment and provenance

The main illustrative claim is **aligned on this downscaled setup**: CaWoSched heuristics used about half of ASAP's median carbon cost, and greater deadline flexibility produced larger savings. The rank statistics also align. The local-search effect is **inconclusive under this setup**, and runtime is **partially aligned** because the scaling trend appears but the 30k absolute time is much longer.

- [Paper: Carbon-Aware Workflow Scheduling with Fixed Mapping and Deadline Constraint](https://arxiv.org/abs/2507.08725)
- [Authors' official CaWoSched repository](https://github.com/KIT-EAE/CaWoSched)
- [Formal experiment branch](https://github.com/S-Discipline/carbon-aware-workflow-scheduling-with-fixed-mapp/tree/orx/official-cawosched-headline-reproduction)
- [Publication branch](https://github.com/S-Discipline/carbon-aware-workflow-scheduling-with-fixed-mapp/tree/orx/published-reproduction-report)
