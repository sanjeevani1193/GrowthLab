# Phase 11 — GrowthLab Decision Studio

Status: implemented, visually reviewed and approved for preservation; **not deployed**.
Research baseline: `cf97aca9ca95d7e5ee754dec0717dae815cf657b`.

The Studio presents completed research and provides hypothetical planning tools.
It does not run a new research evaluation. No model was trained, tuned or changed,
and no sealed outcome labels were parsed for this implementation. Existing
research reports, results and model configurations remain authoritative.

## Pages and working controls

| Workspace | What a business reader can do |
| --- | --- |
| Overview | See the verified headline results, distinguish the independent studies, and navigate through question cards or the sidebar |
| Purchase Intelligence | Select XGBoost, Logistic Regression or dummy; compare saved metrics; inspect top-decile purchaser capture and actual calibration-bin points |
| RetailHero Targeting | Separate the observed training-group comparison from final policy evaluation; choose the evaluated 10%, 20% or 30% budget; inspect policy intervals and paired S-minus-random differences |
| Experiment Lab | Change baseline, MDE, alpha, power and allocation; calculate sample sizes; inspect fixed A/A and A/B simulation results and prespecified examples |
| Reward Economics | Change seven hypothetical assumptions; calculate contribution, costs and break-even; compare scenarios; vary one assumption in a sensitivity chart; download the exact hypothetical calculation |
| Product Ranking | Choose K=5/10/20 and macro/micro recall; compare the same three methods; inspect candidate ceilings, missing pairs and paired macro differences |
| Methodology | Review provenance, independent populations, temporal controls, causal caveats, implicit feedback and simulation limitations; open original reports |

Primary explanations appear before expandable technical details. The sidebar,
question cards, light content area, dark navigation, consistent cards and teal
chart palette form one interface. Plotly hover details complement readable
labels; confidence-interval charts include a zero reference. Native Streamlit
widgets preserve keyboard navigation. Narrow layouts stack columns and collapse
the sidebar. No additional frontend framework or external paid API is used.

## Architecture and public data boundary

`streamlit_app.py` resolves `src/` relative to itself and calls
`growthlab.studio.app.main`. No absolute developer path is needed.

| File | Responsibility |
| --- | --- |
| `src/growthlab/studio/app.py` | Page configuration, sidebar routing, graceful evidence errors and shared footer |
| `pages.py` | Seven business-facing page renderers; no research evaluation or fitting entry points |
| `ui.py` | Shared theme, cards, source links, chart styles, labels and aggregate caching |
| `evidence.py` | Repository-relative allowlist, SHA-256 verification, JSON/field checks and adapters for existing budgets/cutoffs |
| `calculations.py` | Thin adapters to unchanged Phase 8A/9A/9B calculations; separately documented unequal-allocation extension |
| `.streamlit/config.toml` | Consistent light theme, viewer toolbar, disabled usage telemetry and headless local launch |
| `docs/decision_studio/evidence_manifest.json` | Fingerprints and required paths for twelve original aggregate files |
| `docs/decision_studio/evidence_map.md` | Every displayed metric/chart mapped to its field or pure calculation |
| `requirements-studio.lock` | Pinned public runtime; no research model libraries required |
| `requirements-studio-test.lock` | Optional pinned Playwright tooling for browser checks |
| `tests/test_studio*.py` | Evidence/calculation and actual Streamlit AppTest coverage |
| `scripts/verify_decision_studio.py` | Repeatable localhost Chromium navigation, interaction, chart and mobile smoke checks |

Only twelve allowlisted, already committed aggregate JSON sources are read:
**148,988 bytes combined**. Decoding is cached using source path, modification
time and size; changed files are verified again. Fingerprints tie the presentation
to the approved research baseline. This is integrity checking, not a security
boundary against someone editing both source files and their manifest.

Missing, malformed, structurally invalid or fingerprint-mismatched evidence
raises a friendly page error naming the affected file. Other workspaces remain
available. The app never substitutes zero or an invented metric. Restoration
from the repository is the remedy; rerunning research is unnecessary.

The app imports only presentation code and pure experiment/reward calculators.
It does not import training/evaluation entry points, query DuckDB, read ignored
data, load model weights or require customer-level predictions. The portability
test renders every workspace in a separate temporary repository copy with **no
data directory or trained artifacts**.

## Meaning of the displayed evidence

Verified headline values are read at full precision, then rounded for display:

| Study | Saved result | Interpretation |
| --- | --- | --- |
| REES46 purchase prediction | AUC **0.8487**, top-decile predictive lift **5.92×**, **324/547** purchasers captured | Predictive concentration; no demonstrated intervention benefit |
| RetailHero training comparison | SMS minus control **+3.39 pp** | Observed group difference; original assignment/compliance unverified |
| RetailHero final policy comparison | S-minus-random at 30% **−2.50/1,000**, 95% interval **[−11.85, 7.45]** | Assumption-dependent and inconclusive; learned superiority not established |
| Synthetic A/A / A/B | False positives **4.3%**, empirical power **79.3%** | Saved simulations under specified probabilities, not observed voucher effects |
| REES46 final ML ranking | Macro Recall@10 **18.42%**, NDCG@10 **0.21625** | Preferred offline ordering on the frozen candidate lists; no online sales claim |

The final ranking macro ceiling is **32.04%**, while its micro ceiling is
**29.31%**. These are different averages. **70.69% of future purchased pairs**
were absent from the shortlist; improving order cannot retrieve missing items.
The K and averaging controls use saved results only. Paired differences always
use purchaser-level macro metrics, even when the recall chart displays micro.

REES46 and RetailHero remain separate populations. The overview's +3.39 pp is
the **training-cohort** RetailHero finding; it is not substituted for the Phase 7
final group comparison. Policy estimates assume treatment propensity 0.5 and
retain the original paired intervals. A confidence interval including zero is
not described as an established improvement.

No ROC/PR curve is inferred from scalar metrics. The calibration plot shows only
the actual saved bins plus a mathematical equality reference. No new research
curve is fabricated where saved points are unavailable. Source links accompany
each results page; the [complete map](evidence_map.md) gives exact fields.

## Calculation choices, with concrete examples

### Experiment planning

At 50/50 allocation, the app calls the **unchanged Phase 8A**
`two_proportion_sample_size`. With baseline 20%, target 23%, two-sided alpha
0.05 and power 80%, it returns **2,943 control + 2,943 treatment = 5,886**.
The MDE is an absolute **3 percentage points**, not 3% of the baseline.

The earlier function explicitly supports balanced allocation only. Supporting
the requested allocation control therefore needs a small, app-only extension.
It uses the same normal approximation, with pooled null and unpooled alternative
variances, without a continuity correction. Earlier Phase 8 functions, seeds,
assignment behavior and simulation outputs are unchanged.

Let `q` be treatment share, `r=q/(1−q)`, `pT=pC+MDE`, and
`p̄=(pC+r·pT)/(1+r)`. Calculate:

```text
V0 = p̄(1−p̄)(1 + 1/r)
V1 = pC(1−pC) + pT(1−pT)/r
nC* = [ (z(1−alpha/2) sqrt(V0) + z(power) sqrt(V1)) / MDE ]²
nC = ceil(nC*)
nT = ceil(r × nC)
```

Rounding control up first, then treatment, is conservative and keeps the planned
ratio close to the requested ratio. For **30% treatment**, the same assumptions
give **4,864 control + 2,085 treatment = 6,949**. Unequal allocation needs more
total customers here. Independent two-tail power checks using SciPy's normal
distribution confirm approximately 80% power at 20/30/70/80% treatment shares
(absolute tolerance 0.001). This is approximate planning, not exact binomial or
sequential/clustered-design power. Invalid baseline-plus-effect inputs show an
error rather than a nonsensical plan.

Changing planner inputs **does not rerun simulations**. The saved 1,000-run A/A
and A/B frequencies, Wilson Monte Carlo intervals, prespecified examples and
coverage diagnostics remain fixed. An 80% design can miss a real assumed effect
in one experiment; none of this establishes that a real €5 voucher works.

### Reward economics and scenarios

All financial calculations delegate to the unchanged Phase 9A/9B engines.
Percent inputs convert through decimal strings. With `N` contacts, assumed
conversions `p0,p1`, purchase contribution `M`, reward `R`, redemption `D` and
contact cost `K`:

```text
Extra purchasers = N(p1−p0)
Extra purchase contribution = N(p1−p0)M
Reward cost = Np1DR
Contact cost = NK
Net incremental contribution = N(p1−p0)M − Np1DR − NK
```

The default hypothetical example gives **30 extra expected purchasers**, **€600
extra purchase contribution**, **€1,150 rewards**, **€0 contacts**, and **−€550
net**. Reward costs cover all assumed redemptions, including purchases that
would have happened anyway. Break-even conversion is **26.67%** (exactly 4/15),
requiring **+6.67 pp**, rather than the assumed +3 pp. A statistically detectable
effect can still be economically unattractive.

Setting reward cost to zero changes net to **+€600** without changing the
assumed conversion. Scenario ranks appear only when the original Phase 9B
comparability checks permit them; changing contact count to 2,000 blocks ranking
against the fixed 1,000-contact examples. Sensitivity varies one input at a time
using the original engine, with 3–21 grid points. Conversion does not increase
automatically when reward increases. Lines are deterministic calculations, not
empirical response curves or statistical confidence intervals. Zero contacts and
unattainable break-even cases retain the engine's explanations.

## Run locally

Use Python **3.12+** for these pinned UI dependencies; verified here with
**Python 3.14.7** on Apple Silicon/macOS. The research project's older minimum
Python declaration does not imply that every optional lock supports Python 3.11.
From the repository root, use a separate environment for the public app:

```sh
python3 -m venv .venv-studio
source .venv-studio/bin/activate
python -m pip install -r requirements-studio.lock
python -m streamlit run streamlit_app.py
```

Open the localhost URL printed by Streamlit. For an explicitly local-only bind:

```sh
python -m streamlit run streamlit_app.py --server.address 127.0.0.1
```

Runtime pins include **Streamlit 1.67.0, Plotly 7.1.0, SciPy 1.18.1** and their
transitive dependencies. Streamlit brings pandas/Arrow dependencies; the app
does not load event tables into pandas. No Kaggle authentication, raw-data
download, XGBoost, scikit-learn, local OpenMP installer or cloud account is needed
to present the app. Installing just the UI lock does not supply all dependencies
needed for the separate full research test suite.

## Tests and browser verification

Full local suite: **338 tests passed, no skips** — original 313 plus **25** new
tests. Existing research dependencies and ignored local verification artifacts
were already available. Run it with that existing environment:

```sh
LOKY_MAX_CPU_COUNT=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

For the 25 public-app tests alone after installing the UI lock:

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_studio*.py' -v
```

Coverage includes all twelve real evidence sources and requested headlines,
malformed/missing data, fingerprints, path allowlisting, saved budget/K adapters,
balanced and unequal sample sizes, exact reward arithmetic, comparison guards,
sensitivity behavior, seven-page startup, numeric displays, deep navigation,
changed widgets, invalid-design errors and the no-data-directory portability test.

Actual browser testing used **Playwright 1.64.1 / Chromium 156** against a running
localhost Streamlit server, not only mocked rendering. Repeat it separately:

```sh
python -m pip install -r requirements-studio-test.lock
python -m playwright install chromium
python scripts/verify_decision_studio.py
```

The script checks seven desktop pages at **1440×1000**, rendered Plotly SVGs,
interaction flows, and five mobile workspaces at **390×844**, including the corrected methodology table. It writes a
JSON receipt and screenshots to `/tmp/growthlab-studio-browser/` by default.
The final [small smoke summary](browser_smoke_summary.json) is included for review.
All checked views had document widths equal to viewport widths; there were no
browser page errors or Streamlit exceptions. Actual widget checks included:

- Logistic Regression selection displays AUC **0.8081**.
- RetailHero budget selection reaches the saved **10%** setting.
- Unequal allocation changes planning while saved A/B power stays **79.3%**.
- Zero reward recalculates net to **€600**; scenario and sensitivity tabs render.
- Ranking K=20 shows **22.69% macro**, then **18.85% micro** recall.

Screenshots were visually inspected, including desktop Overview, Purchase,
RetailHero, Ranking, Reward and Experiment pages and mobile Overview/Ranking.
Verified issues corrected: pale caption text caused by inherited opacity,
sidebar source-link contrast, tight navigation spacing, truncated metric labels
mobile header clearance, and browser checks that wait for updated policy results
and sidebar-transition completion before screenshots. Native input
labels, chart axes and mobile stacking were checked. This is a Chromium smoke
check, not a claim of exhaustive accessibility or cross-browser certification.

A fresh-process AppTest measurement (imports plus initial Overview render) took
**1.679 seconds** with **152,911,872 bytes (~146 MiB) peak process RSS** on this
machine. This excludes browser memory and is not a production load benchmark.
Startup performs small aggregate reads, not ETL, fitting or outcome evaluation.

## Preservation checks and files changed

The original 313-test baseline passed before implementation. Existing installed
research dependency versions remained unchanged after adding UI dependencies;
`pip check` found no broken requirements. Frozen Module 1 and RetailHero checks
passed, including **82** earlier data/artifact size-and-mtime states. Checksums
also matched all five original REES46 CSVs, all five cleaned monthly Parquets,
ranking development artifacts, final history, protocol, upstream source and
saved evaluation artifacts/figures. Hashing bytes verifies integrity without
parsing final labels or rerunning scoring.

The ranking model SHA-256 remains:
`3c48c0d645a690bb603bebede3732eb664f4df7dfd8c2012909b5260f3a6cadd`.

Only existing **README.md** and **pyproject.toml** were modified. New files are
the app entry point, six Studio package files, two test files, two UI dependency
locks, Streamlit configuration, browser-check script, and this documentation,
evidence map, manifest and browser receipt. Earlier research code/reports,
dependency locks, datasets, splits, predictions and model artifacts are unchanged.
No customer records or generated large artifacts were added or staged.

## Limitations and preservation

Results are frozen historical evidence, not a live scoring/targeting service.
The public app intentionally has no customer search, prediction API or raw-data
upload. Source links target the public repository, including the Phase 11 documentation
preserved with this application.

Fingerprints deliberately reject independently regenerated aggregate files.
An approved research version change would require an explicit evidence-manifest
review. Plotly charts cover saved endpoints only. Small tables may scroll within
their own component on narrow screens. Visual QA covers Chromium desktop and
five mobile workspaces and the expanded mobile sources; Safari/Firefox and a formal assistive-technology review remain
future release checks. No known blocking issue remained in the tested views.

The approved Phase 11 application and UI polish are preserved together. A separate
future stage can package the UI runtime and permitted aggregate files, check target-platform
dependency compatibility, and decide hosting/network settings. **No Docker,
cloud resources or deployment is included.**

Streamlit API references used: [AppTest](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest)
and [Plotly charts](https://docs.streamlit.io/develop/api-reference/charts/st.plotly_chart).

## Final approved UI polish

The final review requested five presentation corrections only:

1. Purchase Intelligence now describes **seven calendar days after the first
   observed customer event**, rather than seven observed shopping days. The
   underlying fixed 168-hour window and all calculations are unchanged.
2. The methodology summary uses a wrapping static table. Every description is
   shown in full; on narrow screens the table scrolls internally to reach all
   four columns without document overflow. A short scroll hint explains this.
3. The shared EUR formatter puts the minus sign before the currency symbol:
   **-€550.00**, also for negative scenario totals. Exact financial outputs are
   unchanged.
4. Ranking labels distinguish the **32.04% macro candidate ceiling** (average
   within future-purchasing customers) from **70.69% future purchased pairs
   missing** (micro, purchased-pair weighted). The selected micro ceiling remains
   **29.31%**.
5. Overview's raw aggregate links are collapsed inside **Evidence & Sources**.

The final full suite still passes **338 tests with no skips**. Existing tests
were strengthened to cover these labels, the complete table, the expander and
negative EUR formatting. Chromium checks cover all seven desktop pages and the
corrected elements on mobile; the small browser receipt records the final run.
Frozen research evidence, model checksums and prior data/artifact checks passed.
No analytical calculation, model or historical research result changed.
