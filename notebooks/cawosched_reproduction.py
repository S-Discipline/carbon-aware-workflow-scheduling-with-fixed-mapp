import marimo

__generated_with = "0.24.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md(r"""
    # CaWoSched reproduction: can workflow timing cut carbon?

    ![Headline reproduction result](https://raw.githubusercontent.com/S-Discipline/carbon-aware-workflow-scheduling-with-fixed-mapp/main/reports/cawosched-reproduction/images/headline-result.png)

    **Observed evidence first:** on 224 official, stratified instances, every tested
    heuristic had a median carbon cost below ASAP. The paper reports **0.58** for
    `pressWR-LS`; this reproduction observed **0.503** (lower is better).

    This notebook is a self-contained tutorial over the already-produced evidence.
    It does not rerun the seven-hour formal experiment.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Goal

    A workflow is a dependency graph: task B cannot start until task A has produced
    its output. CaWoSched keeps the paper's task-to-processor mapping fixed and asks
    a narrower question: **when should each task run before a deadline, given a
    changing supply of low-carbon energy?**

    The comparison metric is

    $$\text{relative cost}=\frac{\text{heuristic carbon cost}}{\text{ASAP carbon cost}}.$$

    A value of 0.50 means the schedule incurs half the carbon cost of running every
    task as early as dependencies allow.
    """)
    return


@app.cell
def _():
    observed_ratios = {
        "pressR-LS": 0.455518,
        "slackR-LS": 0.481451,
        "press-LS": 0.493888,
        "pressWR-LS": 0.502893,
        "pressW-LS": 0.517815,
        "slackWR-LS": 0.526037,
        "slack-LS": 0.526404,
        "slackW-LS": 0.590111,
    }
    paper_presswr = 0.58
    return observed_ratios, paper_presswr


@app.cell
def _(mo, observed_ratios):
    variant_picker = mo.ui.dropdown(
        options=list(observed_ratios), value="pressWR-LS", label="Inspect a heuristic"
    )
    variant_picker
    return (variant_picker,)


@app.cell
def _(mo, observed_ratios, paper_presswr, variant_picker):
    selected_ratio = observed_ratios[variant_picker.value]
    reference = (
        f"The paper's matching value is {paper_presswr:.2f}."
        if variant_picker.value == "pressWR-LS"
        else "The paper gives an approximately 0.60 headline across variants."
    )
    mo.md(
        f"""
        **{variant_picker.value}: {selected_ratio:.3f}** relative to ASAP, or an observed
        median reduction of **{(1 - selected_ratio) * 100:.1f}%**. {reference}
        """
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Setup and implementation

    The formal run compiled the authors' C++17 code, then used repository-native
    DAGs, fixed mappings, and carbon/deadline profiles. It evaluated:

    1. ASAP as the baseline;
    2. eight greedy heuristic variants with local search;
    3. the same eight variants without local search;
    4. six additional runtime probes from 4k to 30k tasks.

    The 224 primary instances span seven workflow/scale groups, two cluster sizes,
    four scenarios, and four deadline levels. All 3,910 output rows were valid.

    ```text
    DAG + mapping + carbon profile
                ↓
    C++ scheduler → ASAP / heuristic / heuristic without LS
                ↓
         validity + cost + runtime
    ```
    """)
    return


@app.cell
def _():
    deadline_ratios = {"1×": 0.821634, "1.5×": 0.457140, "2×": 0.402483, "3×": 0.156061}
    local_search_ratios = {
        "slackR": 0.879147,
        "slackWR": 0.922331,
        "pressR": 0.932359,
        "pressWR": 0.922694,
    }
    runtime_minutes = {"4k": 0.370, "10k": 2.371, "30k": 26.370}
    return deadline_ratios, local_search_ratios, runtime_minutes


@app.cell
def _(deadline_ratios, local_search_ratios, mo, runtime_minutes):
    deadline_text = ", ".join(f"{key}: {value:.3f}" for key, value in deadline_ratios.items())
    local_text = ", ".join(f"{key}: {value:.3f}" for key, value in local_search_ratios.items())
    runtime_text = ", ".join(f"{key}: {value:.1f} min" for key, value in runtime_minutes.items())
    mo.md(
        f"""
        ## Checks and evidence

        **Deadline mechanism.** `pressWR-LS` relative costs were {deadline_text}. More
        time lets the scheduler move work into cleaner intervals, matching the paper's
        direction and endpoint magnitude.

        **Rank checks.** ASAP was tied for worst on 95.98% of cases (paper: 84.01%),
        while `pressWR-LS` was tied for best on 39.73% (paper: 34.47%).

        **Local-search diagnostic.** Mean with/without ratios on the matched 96-case
        subset were {local_text}. These are below one but far from the paper's 0.23–0.25,
        so the reported effect size is inconclusive under this downscaled cohort.

        **Runtime.** Median per-variant times were {runtime_text}. Scaling is steep, but
        the 30k absolute runtime is much longer than the paper's “several minutes.”
        """
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Assessment and next steps

    The central claim is **aligned on this downscaled setup**: CaWoSched schedules
    generally incurred about half ASAP's median carbon cost, and flexibility helped.
    The local-search effect is **inconclusive under this setup**, while runtime is
    **partially aligned** because only its scaling trend agrees.

    A full reproduction still needs the exact 1,088-instance-per-algorithm manifest,
    isolated CPU timing, and a licensed Gurobi run for the small-instance ILP claim.
    The most useful next check is the local-search comparison on the paper's exact
    workflow cohort.

    - [Detailed illustrated report](https://github.com/S-Discipline/carbon-aware-workflow-scheduling-with-fixed-mapp/blob/main/reports/cawosched-reproduction/report.md)
    - [Paper](https://arxiv.org/abs/2507.08725)
    - [Official implementation](https://github.com/KIT-EAE/CaWoSched)
    """)
    return


if __name__ == "__main__":
    app.run()
