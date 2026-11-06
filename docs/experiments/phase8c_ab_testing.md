# Phase 8C — Synthetic A/B power and interval coverage

Completed locally for review on 2026-11-06. **Synthetic data only.** The simulator
programs a 20% control probability and 23% treatment probability: a real +3
percentage-point difference **inside this simulation**, not evidence that any
actual voucher works. No previous models, results, assignment logic, or
statistical method was changed. Phase 8C is not committed or pushed.

## Phase 8B preservation completed first

The five approved Phase 8B files were reviewed. All **165 tests passed**, all
1,000 stored A/A results and numerical summaries reproduced exactly, and prior
frozen inputs, 82 prior data/artifact states, and final-study artifacts verified
unchanged. The staged allowlist contained only the A/A source, tests,
configuration, report, and small aggregate summary. Datasets, credentials, and
large generated artifacts were excluded.

Phase 8B was committed and pushed as
**`717b222d492fd3131db029c7f9d93064468e41f6`**, titled
`Complete Phase 8B synthetic A/A calibration and statistical verification`.
Local HEAD matched `origin/main`, and Git was clean before Phase 8C development.
The previous A/A results remain 43/1,000 false positives and 957/1,000 zero-effect
interval coverage; they have not been replaced by this A/B study.

## What power means

Statistical power is the probability that a prespecified test rejects its null
hypothesis when a particular alternative is true. Here the null is equal
conversion probabilities, while the simulator's alternative is **20% versus
23%**. The test is still **two-sided at alpha=0.05**: we did not switch to a
one-sided test just because the programmed effect is positive.

About 80% planning power means roughly eight of ten comparable experiments are
expected to find a statistically significant difference under those assumptions.
It does not mean an 80% probability that a real voucher works, an 80% chance each
customer benefits, or a guarantee that one experiment will succeed.

A **false negative** is a run that fails to reject equality even though the true
probabilities differ. Purchases are random, so an estimated effect may be too
small relative to its standard error to cross the significance threshold. A
nonsignificant result does not prove the underlying effect is zero. Conversely,
an estimated positive difference alone is not enough to call a result detected.

The 14-day outcome is one binary draw representing any purchase during the
complete follow-up window, as in Phase 8B. We do not simulate purchase times,
voucher redemption, costs, financial rewards, or actual customers.

## Prespecified design and unchanged assignments

The [Phase 8C configuration](phase8c_config.json) fixes:

- **1,000 independent outcome replications**.
- Master outcome seed **2026110602**, distinct from Phase 8B's 2026110601.
- Calibration-diagnostic alpha **0.05**.
- Example index **0**, chosen before seeing whether it succeeds.

The underlying [Phase 8A configuration](phase8a_config.json), synthetic roster,
and SHA-256 assignment are reused **without modification**. Assignment seed
remains **20261106**; roster IDs are `synthetic-customer-000001` through
`synthetic-customer-005886`. No balancing, resampling of assignments, exclusion,
or seed shopping is performed.

| Quantity | Balanced planning design | Actual deterministic cohort | Actual minus plan |
| --- | ---: | ---: | ---: |
| Control | 2,943 | **2,950** | **+7** |
| Treatment | 2,943 | **2,936** | **−7** |
| Total | 5,886 | **5,886** | 0 |

The assignment hash remains
`0023e31634e472d5f1a03ea8f5cb0e317a63f44cc2cfed7467268032b165e507`,
identical to Phase 8B. Assignment SRM remains p=0.865447. The test and power
calculation use the **actual** two arm sizes rather than pretending both equal
2,943. A treatment arm below the balanced per-arm target is not hidden, and an
unflagged SRM is not proof of exact balance or experimental validity.

For repetition i, the unchanged Phase 8B `outcome_stream` uses PCG64 with
`SeedSequence(2026110602, spawn_key=(i,))`. Each synthetic customer receives a
fresh Bernoulli draw with probability selected by its fixed arm: **0.20 for
control, 0.23 for treatment**. The existing stream-spawning method and pinned
NumPy version are preserved; only the data-generating arm probabilities and
master outcome seed differ from A/A. Repetition prefixes remain stable when
requesting more runs.

Replications are independent conditional on the fixed roster/assignment. No
persistent customer effect, temporal correlation, attrition, or shared household
effect is simulated. This is equivalent to repeatedly drawing fresh synthetic
outcomes for the same array positions, not repeatedly experimenting on real
customers.

## Unchanged statistical analysis

Every repetition calls **the existing Phase 8B `analyze_counts` function directly**.
There is no copied replacement or changed formula. With conversion counts x and
group sizes n:

```text
p̂_C = x_C/n_C; p̂_T = x_T/n_T
d = p̂_T − p̂_C
d_pp = 100d
p̂_pool = (x_C+x_T)/(n_C+n_T)
SE₀ = sqrt[p̂_pool(1−p̂_pool)(1/n_C+1/n_T)]
z = d/SE₀
p_value = 2 × P[standard normal ≥ |z|]
detected = p_value < 0.05
```

The 95% difference interval is the same **Newcombe combination of independent
Wilson score bounds**, with no continuity correction. Its exact formulas,
boundary handling, and independent library checks remain documented in
[Phase 8B](phase8b_aa_testing.md). This interval is not exactly the inversion of
the pooled z-test; significance is defined by the p-value, not substituted by
interval exclusion.

For this A/B study, **coverage checks whether the interval contains 0.03**, not
zero. The original helper's `covers_true_zero` field retains its original
meaning; a new `covers_true_effect` field checks +3 pp. A test confirms that these
two questions are not accidentally conflated.

Per the requested definition, empirical two-sided power is
`number of p-values below 0.05 / number of experiments`. A significant result in
the wrong direction would still reject equality but would not demonstrate a
positive improvement, so direction is reported separately. There were **zero**
wrong-direction significant results in this study.

## Theory with the achieved arm sizes

The Phase 8A equal-arm sample-size calculation remains **2,943 per group**. Its
independent two-normal-tail power at those integer sizes is **80.005604%**.

To account for the realized allocation, use the **same pooled-null and
unpooled-alternative normal approximation**, substituting n_C=2,950 and n_T=2,936.
This uses known synthetic probabilities, not fitted rates from the simulations:

```text
p̄ = (n_C p_C + n_T p_T)/(n_C+n_T)
SE₀ = sqrt[p̄(1−p̄)(1/n_C+1/n_T)]
SE₁ = sqrt[p_C(1−p_C)/n_C + p_T(1−p_T)/n_T]
critical = z_(0.975) × SE₀

approximate_power =
  P[Normal(0.03, SE₁²) > critical]
  + P[Normal(0.03, SE₁²) < −critical]
```

This yields **80.007269%** for the actual allocation. The small change is about
**+0.0017 percentage points of power**, negligible for this comparison. Unequal
allocation does not automatically imply a particular rounded power loss: the
pooled and alternative variance terms both depend on the arm sizes/rates. We
report the calculation rather than assuming its direction. This remains an
approximation, not exact finite-binomial power or a revision of Phase 8A's
methodology.

## Actual synthetic A/B results

| Diagnostic | Calculated result |
| --- | ---: |
| Replications | **1,000** |
| True control / treatment probability | **20% / 23%** |
| True difference | **+3 pp** |
| Significant results | **793 / 1,000** |
| Empirical two-sided power | **79.3%** |
| Positive-direction significant results | 793 |
| Negative-direction significant results | 0 |
| False negatives | **207 / 1,000 = 20.7%** |
| 95% Wilson interval for empirical power | **76.6790%–81.6967%** |
| Exact-binomial comparison with actual-allocation normal power | **p=0.579915** |
| Exact-binomial comparison with balanced Phase 8A normal power | **p=0.579934** |
| Intervals containing the true +3 pp effect | **955 / 1,000** |
| Empirical 95% interval coverage | **95.5%** |
| 95% Wilson interval for coverage frequency | **94.0317%–96.6200%** |
| Coverage diagnostic against nominal 95% | **p=0.513846** |

### Does 79.3% agree with approximately 80% planning power?

Yes, within the uncertainty of 1,000 runs. If the actual rejection probability
were approximately 0.800073, the significant-count reference distribution would
be `Binomial(1000,0.800073)`. Its expected count is about **800.073** and standard
deviation **12.647**. A central 95% count range is **775–825**; the observed **793**
is ordinary finite-simulation variation.

The Monte Carlo standard deviation of the estimated power fraction is about
`sqrt(0.800073×0.199927/1000)=0.012647`, or **1.265 percentage points**. The observed
79.3% is about 0.71 pp below the normal reference, well within that precision.
The Wilson interval includes approximately 80%, and the two-sided exact-binomial
diagnostic does not flag a departure at its declared 5% threshold.

We reuse Phase 8B's `calibration_check` for this count-level comparison. An exact
binomial test here checks compatibility with a **specified approximate** power;
it does not make the original normal approximation exact. A flagged discrepancy
could reflect Monte Carlo chance, approximation limits, or an implementation
issue and would need investigation. We do not require exactly 800 successes or
change the seed until the empirical result equals 80%.

### Why do 207 runs miss the true effect?

The true population difference is fixed at +3 pp, but each run's estimated
difference varies. The theoretical standard deviation of an estimate is about
**1.070315 pp**. Randomly fewer treatment purchases or more control purchases can
make the estimate too small relative to its uncertainty to reach p<0.05. Planned
power near 80% explicitly anticipates a miss rate near 20%.

The mean estimated effect across runs is **3.017953 pp**, only **0.017953 pp**
above the programmed truth. Its theoretical Monte Carlo standard error is
**0.033846 pp**. The empirical across-run standard deviation is **1.069614 pp**,
close to the theoretical 1.070315 pp. These diagnostics support the intended
simulation behavior without asserting an exactly zero estimation error.

### Coverage is not power

Power asks whether the procedure rejects **zero difference**. Coverage asks
whether an interval contains the **true +3 pp difference**. A wide interval can
contain both zero and +3 pp, giving coverage without detection. Conversely, an
interval can reject zero while missing the exact true effect. Thus 95.5%
coverage and 79.3% power are different properties, not contradictory numbers.
The two diagnostics also use the same runs and should not be treated as
independent proofs of correctness.

Coverage is compatible with nominal 95% within Monte Carlo uncertainty. This
does not guarantee coverage at every probability, sample size, or data-quality
condition; the z-test and interval remain approximate procedures.

## Prespecified example: experiment index 0

The example index was fixed in the configuration before viewing its outcome. It
happened to be significant; it was not chosen from the 793 successful runs.

| Example output | Value |
| --- | ---: |
| Control conversions / assigned customers | 562 / 2,950 |
| Control conversion rate | **19.0508%** |
| Treatment conversions / assigned customers | 654 / 2,936 |
| Treatment conversion rate | **22.2752%** |
| Estimated difference | **+3.22436 pp** |
| z statistic | 3.05504 |
| Two-sided p-value | **0.00225030** |
| Significant at alpha=0.05? | Yes |
| 95% Newcombe/Wilson difference interval | **[1.15584, 5.29044] pp** |
| Interval covers the true +3 pp effect? | Yes |

This one success illustrates detection, while the full 1,000-run power estimate
shows why success is not guaranteed for any one new experiment. None of these
counts are observed customer evidence.

## Why this does not prove a real voucher works

The 23% treatment probability is an **input** to this simulator. It was not
discovered from data. The exercise shows that the assigned sample sizes and
unchanged statistical procedure can detect that programmed difference at the
expected frequency under idealized assumptions. It cannot establish a real
voucher's effect, generalize to a retailer, or identify financial value.

The simulation assumes independent customers, constant probabilities within
arms, complete follow-up, fixed sample size, a single primary outcome, and no
interference, attrition, noncompliance, or repeated peeking. Actual experiments
could violate these assumptions. No real experiment, subgroup model, reward
optimization, product ranking, or deployment has been implemented.

## Implementation, tests, and reproducibility

The new `growthlab.experimentlab.ab_testing` module imports the existing Phase
8A assignment and Phase 8B analysis, RNG-stream, validation, and calibration
helpers. Those prior files are unchanged. `ABStudyConfig` reuses the validated
study configuration with a distinct outcome seed. The simulator is restricted
to the requested 20%/23%, +3 pp, alpha=0.05 scenario; it does not search for an
effect size, seed, or threshold that gives favorable results.

Each of the 1,000 stored replication rows contains arm sizes/counts, rates,
estimated difference, p-value, confidence interval, significance/direction
indicators, and coverage of +3 pp. The table is an ignored **per-experiment
aggregate**, not customer-level data:
`data/experiments/phase8c/replications.json`. The small reviewable
[summary](phase8c_ab_summary.json) records all reported results, source/config
hashes, versions, theoretical references, and resource measurements. Only one
synthetic-customer vector is held at a time, not a full replication-by-customer
matrix; no customer outcomes are written to disk.

Reproduce in the existing pinned environment:

```sh
PYTHONPATH=src .venv/bin/python -m growthlab.experimentlab.ab_testing
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

The default study config is `docs/experiments/phase8c_config.json`, and outputs
stay under ignored `data/experiments/phase8c/`. NumPy 2.5.4 and SciPy 1.18.1 are
already installed and pinned; no dependency changes are needed. The recorded CLI
work after imports took **0.394 seconds**, with **93.3 MiB peak process RSS**.
Startup/import time and the full test-suite time are not part of that elapsed
measurement. No real dataset or trained model is loaded by this simulator.

**All 184 tests pass, with no skips:** 165 prior tests plus 19 new A/B tests.
New tests verify the exact arm-specific probabilities and direction, independent
NumPy generation, binary values, reproducible child streams, invalid masks,
identity of the reused Phase 8B functions, hand-calculated effect/test examples,
balanced power against Phase 8A's independent cross-check, unequal-arm power,
replication-prefix stability, unchanged assignment hash, detection/false-negative
accounting, coverage of +3 pp rather than zero, prespecified example selection,
unchanged A/A behavior, fixed seed/scenario validation, and Monte Carlo
compatibility checks. Tests do not require exactly 80% empirical power or every
run to estimate a positive significant effect.

A second deterministic calculation reproduced all **1,000 A/B rows and numerical
summary fields exactly**. Independent uncorrected chi-square p-values and SciPy
Wilson/Newcombe difference bounds matched every row. The previous A/A outputs,
Phase 8A planning summary, prior frozen inputs, 82 prior data/artifact file states,
and final-study artifacts also verified unchanged.

Files added in Phase 8C:

- `src/growthlab/experimentlab/ab_testing.py`
- `tests/test_experimentlab_ab_testing.py`
- `docs/experiments/phase8c_config.json`
- `docs/experiments/phase8c_ab_summary.json`
- This report, `docs/experiments/phase8c_ab_testing.md`.

Git status: five new untracked review files, no existing tracked-file changes,
and no staged changes. Phase 8B is pushed at `717b222`; Phase 8C is not committed
or pushed. Earlier modules, experimental outputs, and model artifacts remain
unchanged. Stop for review after Phase 8C; no rewards, ranking, dashboard,
Docker, or deployment work has begun.
