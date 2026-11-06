# Phase 8B — Synthetic A/A calibration

Completed locally for review on 2026-11-06. **Synthetic data only; both arms have
true 14-day purchase probability 20%, and the true difference is zero.** No real
voucher outcome, A/B treatment effect, reward, ranking, dashboard, or deployment
is implemented. Phase 8B is not committed or pushed.

## Phase 8A preservation

Before development, the six Phase 8A files were reviewed; all **145 tests passed**,
and the planning summary reproduced exactly. Prior frozen inputs, 82 prior
data/artifact file states, and Phase 7 final predictions/draws/figures verified
unchanged. The staged allowlist contained only the six source/test/config/report
and small planning-summary files; no raw data, private records, credentials, or
large artifacts were staged.

Phase 8A was committed and pushed as
**`317ff37b51bb9f789b39f214f61cab6b64b1fdbf`**, titled
`Complete Phase 8A ExperimentLab design, sample-size planning and randomization`.
Local `main` matched `origin/main`, and the working tree was clean before Phase 8B.
The Phase 8A assignment implementation and configuration remain unchanged.

## What an A/A study tests

An A/A experiment gives two randomly labeled groups the **same underlying
experience**. Here the labels remain `control` and `treatment` for compatibility
with the assignment API, but the simulator gives every customer the identical
20% purchase probability. It does not offer vouchers, simulate redemption,
introduce a 3 pp benefit, or use the 23% planning alternative from Phase 8A.

We know the truth in this synthetic setting: the population rate difference is
zero. Therefore, any significant difference is a **false positive**. Repeating
this scenario tests whether the statistical procedure falsely reports
differences roughly as often as its nominal 5% significance level predicts.
It is a software/statistical calibration exercise, not evidence about an actual
retailer, voucher campaign, or deployment pipeline.

Observed rates will still vary: individual purchases are random draws. One group
can have more purchasers by luck even when its true probability is identical.
The hypothesis test compares the difference with the variation expected from
that sampling, rather than treating every nonzero difference as a real effect.

## Prespecified simulation design

The [configuration](phase8b_config.json) declares **1,000 replications**, master
outcome seed **2026110601**, calibration diagnostic alpha **0.05**, and the example
index **0**. These choices were set before viewing the output; neither seeds nor
replications were selected to make the false-positive rate look attractive.

The existing Phase 8A roster uses `synthetic-customer-000001` through
`synthetic-customer-005886`. Its unchanged SHA-256 assignment, seed **20261106**,
produces **2,950 controls and 2,936 treatments**. The one-time assignment SRM
p-value remains **0.865447**. There is no rebalancing to 2,943/2,943, no customer
discarding, and no repeated identical SRM result interpreted as 1,000 independent
randomization diagnostics. The unequal achieved arm sizes are explicitly used
in each test's standard error.

Assignments and roster are held fixed while outcome streams change. Replications
are independent **conditional on that fixed roster/assignment**: no persistent
customer propensity, shared customer effect, or temporal dependence is simulated.
This isolates analysis calibration; it does not test every aspect of production
randomization. The short treatment arm relative to the balanced Phase 8A power
target is not concealed, and no 80% power claim is made for this null study. Under
a true null, the relevant rejection rate is alpha, not alternative-hypothesis
power.

For repetition i, create a NumPy PCG64 generator initialized from
`SeedSequence(2026110601, spawn_key=(i,))`. This matches NumPy child-stream spawning
and permits reconstructing any repetition without depending on execution order.
The [NumPy documentation](https://numpy.org/doc/stable/reference/random/parallel.html)
describes spawning pseudo-random streams with high-probability independence.
Reusing the same RNG seed inside every loop would instead create identical
experiments and exaggerate the amount of independent evidence; that is tested
against here.

Draw **one Bernoulli(0.20) value per customer** for the complete 14-day window,
then split that vector by the fixed assignment mask. A value of one represents
at least one hypothetical purchase during `[assignment, assignment + 14 days)`.
No daily history or event times are simulated; complete follow-up is assumed.
Only one binary vector is retained at a time. Per-experiment aggregates are
saved locally, never the individual synthetic customer outcomes.

## Statistical procedure for each repetition

Let x_C/x_T be conversion counts, n_C/n_T group sizes, and
`p̂_C=x_C/n_C`, `p̂_T=x_T/n_T`. The reported effect is
`d=p̂_T−p̂_C`; multiplying by 100 gives **percentage points**.

### Two-sided pooled two-proportion z-test

The null is `p_T=p_C`; the alternative is `p_T≠p_C`.

```text
p̂_pool = (x_C + x_T)/(n_C + n_T)
SE₀ = sqrt[p̂_pool(1 − p̂_pool) × (1/n_C + 1/n_T)]
z = (p̂_T − p̂_C)/SE₀
p_value = 2 × P[standard normal ≥ |z|]
significant = p_value < 0.05
```

Pooling estimates the shared probability assumed by the null; unequal arm sizes
enter through both reciprocal sample sizes. There is no continuity correction.
The [statsmodels z-test documentation](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.proportions_ztest.html)
describes this standard proportion test. We implement the explicit formula with
`math.erfc` and independently test its identity with an uncorrected Pearson
2×2 chi-square test. Statsmodels itself is not installed or added.

Both all-zero or all-one groups have zero pooled variance and zero difference;
we return z=0 and p=1 for those edge cases rather than divide by zero. At the
actual 20% rate and roughly 3,000 customers per arm, expected success and failure
counts are large, supporting the normal approximation. This is not an exact
finite-sample hypothesis test and is not a sequential/optional-stopping test.

### 95% Newcombe/Wilson difference interval

A simple symmetric Wald interval can behave badly near probability boundaries.
We instead compute a Wilson score interval `[L,U]` for each arm, then combine
the two arms' bounds into the Newcombe difference interval. This is the
independent-proportions difference method documented in the
[statsmodels interval reference](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.confint_proportions_2indep.html).

With q=1.9599639845, the 97.5th standard-normal percentile, each arm uses:

```text
denominator = 1 + q²/n
center = (p̂ + q²/(2n))/denominator
half = q × sqrt[p̂(1−p̂)/n + q²/(4n²)]/denominator
[L,U] = [center−half, center+half], bounded to [0,1]

d_lower = d − sqrt[(p̂_T−L_T)² + (U_C−p̂_C)²]
d_upper = d + sqrt[(U_T−p̂_T)² + (p̂_C−L_C)²]
```

The difference interval is bounded to [−1,1] in probability units; multiply its
bounds by 100 for percentage points. Each simulated interval is marked as
covering the truth when `lower≤0≤upper`.

This interval is **not exactly the inversion of the pooled z-test**. A p-value
above 0.05 and an interval covering zero will generally agree here but are not
assumed mathematically identical for all data. We record disagreement counts.
Tests independently compare the Wilson bounds with SciPy's score intervals and
then verify the Newcombe combination.

## Actual synthetic results: 1,000 replications

| Diagnostic | Calculated output |
| --- | ---: |
| True control probability | 20% |
| True treatment probability | 20% |
| True difference | 0 pp |
| Significant results at alpha=0.05 | **43 / 1,000** |
| Empirical false-positive rate | **4.3%** |
| 95% Wilson interval for false-positive frequency | **3.2079%–5.7419%** |
| Exact-binomial check against 5% rejection probability | **p=0.345349** |
| Intervals covering the true zero difference | **957 / 1,000** |
| Empirical interval coverage | **95.7%** |
| 95% Wilson interval for coverage frequency | **94.2581%–96.7921%** |
| Exact-binomial check against 95% coverage | **p=0.345349** |
| Significance-versus-interval-exclusion disagreements | 0 |

The false-positive rate is **43/1000**, not a purchase rate or a voucher effect.
Because every generated population has zero effect, all 43 rejections are false
positives even if an individual run's p-value is small.

### Is 4.3% compatible with 5%?

If each independent experiment rejects with probability 0.05, the false-positive
count K has reference distribution `Binomial(1000,0.05)`. Its expected count is
**50**, with standard deviation **6.892**. A central 95% count range is **37–64**.
Forty-three is ordinary finite-repetition variation; exactly 50 is not required.

We use a **two-sided exact binomial test** of this rejection frequency, with a
separate diagnostic threshold of 0.05. Its p=0.345349 does not flag departure.
The [SciPy binomial-test documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.binomtest.html)
supports this count-based check. The binomial diagnostic is exact for the stated
reference probability, while the underlying two-proportion test is a normal
approximation whose true finite-sample size need not be exactly 5%.

The Monte Carlo standard deviation of the estimated rejection fraction under
that reference is `sqrt(0.05×0.95/1000)=0.006892`, or **0.6892 percentage points**.
One thousand runs therefore cannot establish the false-positive rate to arbitrary
precision. The Wilson interval includes 5%; this is compatibility, not proof of
perfect calibration. Both unexpectedly high and unexpectedly low rejection
frequencies can be signs to investigate.

Coverage is assessed similarly against nominal 95%. Its compatible result is
reassuring, but it is **not independent confirmation** of the false-positive
result: in this particular set of 1,000 runs the z-test and interval-exclusion
flags agree, so 957 covered intervals complement the 43 rejections.

### Other finite-simulation diagnostics

The mean observed treatment-minus-control difference is **−0.0680093 pp**. Its
theoretical Monte Carlo standard error is **0.0329747 pp**, so this mean is about
**−2.06 standard errors** from zero. That is somewhat unusual, but it is not
hidden or repaired by changing the seed. The exact generating mean is zero by
construction; a finite simulation average is not required to equal it. This
single deviation does not prove an implementation bias, nor should it be
described as exact agreement with every theoretical diagnostic.

The empirical standard deviation of differences is **1.004449 pp**, compared with
theoretical `100×sqrt[0.2×0.8×(1/2950+1/2936)] = 1.042752 pp`. Mean p-value is
**0.512099**. P-value decile counts, from [0,0.1) through the final bin including
one, are **82, 100, 108, 99, 96, 99, 89, 127, 85, 115**. Null p-values for a
continuous exact test would be uniform; discreteness, approximation, and finite
Monte Carlo variation can change the observed shape here. We do not add an
unplanned uniformity test or call these bins proof of full calibration.

The prespecified false-positive/coverage checks find no clear calibration
departure in this scenario. That statement is narrower than claiming the
implementation is guaranteed reliable for every sample size, probability,
missingness mechanism, or production process. Repeating the same seed would
reproduce the same 1,000 runs, not add new independent evidence.

## Prespecified example: experiment index 0

Index 0 was chosen in the configuration before inspecting significance; it was
not selected as the most interesting run.

| Synthetic example output | Value |
| --- | ---: |
| Control conversions / customers | 625 / 2,950 |
| Control conversion rate | 21.1864% |
| Treatment conversions / customers | 572 / 2,936 |
| Treatment conversion rate | 19.4823% |
| Treatment-minus-control difference | **−1.70415 pp** |
| z statistic | −1.62413 |
| Two-sided p-value | **0.104348** |
| Significant at 0.05? | No |
| 95% Newcombe/Wilson difference interval | **[−3.75928, 0.35280] pp** |
| Covers the true zero difference? | Yes |

Even though the treatment-labeled group converted less often in this draw, its
true probability was still 20%, identical to control. The negative difference
is sampling noise, not evidence that a voucher harms customers. No voucher
effect was generated.

## What might indicate an unreliable procedure?

Unexpectedly inflated false positives, substantial undercoverage, consistently
biased differences beyond Monte Carlo uncertainty, seed reuse across runs,
incorrect arm joins, sign/unit errors, or incorrect standard errors warrant
investigation. A statistically unusual diagnostic can itself occur by chance;
one flag is not an automatic proof of invalidity. Do not pick another seed until
the results look good. Independently checked arithmetic and several transparent
diagnostics are more informative than insisting on exactly 5% significant runs.

This simulator assumes independent customers, identical 20% probabilities,
complete follow-up, fixed sample size, a single prespecified metric, and one
final test per replication. It does not validate real-world instrumentation,
attrition, noncompliance, shared household effects, or repeated peeking. More
settings or real pipeline checks would be separate reviewed work; none are
implemented in Phase 8B.

## Implementation, tests, files, and reproduction

`growthlab.experimentlab.aa_testing` contains validated study configuration,
count-based z-test and difference interval helpers, a zero-effect outcome
generator, independent child RNG streams, and repetition-level calibration
summaries. It imports Phase 8A's design/assignment unchanged and has no imports
from REES46 or RetailHero. True probability is a single constant **0.20** for
every customer; there is no treatment-effect parameter. The study rejects a
non-20% design baseline or an outcome alpha other than 0.05 in this phase.

Every replication retains group sizes/counts, both conversion rates, difference
and interval in probability/pp units, z statistic, two-sided p-value, significance
flag, zero-coverage flag, index, and spawn key. The 1,000-row replication table
stays under ignored `data/experiments/phase8b/replications.json`. It is per-run
aggregate data, not customer-level records. The small reviewable
[summary](phase8b_aa_summary.json) records actual results, provenance hashes,
NumPy/SciPy versions, a predetermined example, and resource measurements.

Reproduce with the existing pinned environment:

```sh
PYTHONPATH=src .venv/bin/python -m growthlab.experimentlab.aa_testing
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

The default study configuration is `docs/experiments/phase8b_config.json`; the
default output directory is ignored `data/experiments/phase8b/`. Re-execution with
the same inputs reproduces the numerical study and per-replication table; runtime
and peak RSS may vary. NumPy 2.5.4 and SciPy 1.18.1 are already installed/pinned;
no dependency file or existing module was changed. Only one 5,886-customer binary
vector is held at a time, alongside 1,000 small aggregate records. Main-study
runtime and peak process RSS are recorded in the summary; resource usage remains
modest for an 8 GB Mac.

The recorded CLI work after imports took **0.214 seconds**, with **93.0 MiB peak
process RSS**. Startup/import time and the full test suite are not included in
that elapsed measurement. A second deterministic calculation reproduced all
1,000 replication records and numerical summary fields exactly. Independently
computed uncorrected chi-square p-values and SciPy Wilson/Newcombe bounds also
matched every replication. Prior frozen inputs, 82 prior data/artifact file
states, final-study artifacts, and the Phase 8A planning summary verify unchanged.

**All 165 tests pass, with no skips:** the previous 145 plus 20 new A/A tests.
New tests verify hand-calculated rates/pooled z values, independent uncorrected
chi-square equivalence, independent SciPy Wilson bounds/Newcombe combination,
unequal sample sizes, arm reversal, all-zero/all-one cases, significant synthetic
count fixtures, validation, binary 20% draws, seed/child-stream reproducibility,
NumPy spawn equivalence and request-order independence, repetition-prefix
stability, unchanged Phase 8A assignments, null-effect configuration, aggregation
and coverage reconciliation, prespecified example selection, and known
calibration examples. They do **not** require a random study to yield exactly
5% rejections or force a favorable calibration result. Hand-count fixtures are
arithmetic examples, not nonzero-effect data generators.

Files added in Phase 8B:

- `src/growthlab/experimentlab/aa_testing.py`
- `tests/test_experimentlab_aa_testing.py`
- `docs/experiments/phase8b_config.json`
- `docs/experiments/phase8b_aa_summary.json`
- This report, `docs/experiments/phase8b_aa_testing.md`.

No existing tracked source, test, configuration, report, or model was modified.
Phase 8A is committed/pushed at `317ff37`; Phase 8B has five new untracked review
files and ignored local synthetic aggregates. Nothing from Phase 8B is staged,
committed, or pushed. Stop after this A/A review: no A/B effect simulation,
rewards, product ranking, dashboard, or deployment has begun.
