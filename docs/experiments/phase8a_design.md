# Phase 8A — A/B Experimentation Lab: design and randomization

Completed locally for review on 2026-11-06. **Hypothetical planning assumptions
and synthetic customer identifiers only. No outcomes, A/A experiment, A/B outcome
analysis, optimization, ranking, dashboard, Docker, deployment, commit, or push.**

## What was inspected and preserved

Git was clean at `c760110b84e6a07fac132b6be1fc53c9525e6589`, the completed Phase 7
preservation commit; local `main` matched `origin/main`. The existing project has
customer prediction, RetailHero experiment/feature/model evaluation, and tests,
but no general ExperimentLab or sample-size planning utility.

RetailHero's `experiment.assignment_check` uses a two-sided exact binomial test
against assumed 50/50 allocation. Its frozen customer split is treatment-stratified
and quota-based, which serves a different purpose from assigning a new customer
experiment. We reuse the statistical idea and the already installed SciPy
dependency, rather than import or alter that study's code. New functionality is
isolated under `growthlab.experimentlab`. No existing tracked file is changed.
Module 1 and RetailHero source, protocols, splits, artifacts, and conclusions
remain unchanged.

## Documented experiment configuration

The [configuration](phase8a_config.json) is a small JSON file, loaded into a
validated, frozen Python `ExperimentDesign` dataclass. Frozen means fields cannot
be accidentally mutated on that object; this is not a claim of a production
preregistration or access-control system. The reusable functions accept explicit
planning inputs; this phase's design supports only balanced 50/50 experiments.
Unequal allocation is rejected rather than silently applying an equal-arm formula.

| Item | Prespecified hypothetical design |
| --- | --- |
| Experiment ID | `voucher_5eur_14d_v1` |
| Business question | Does offering a €5 voucher increase purchase probability within 14 days? |
| Control | No voucher |
| Treatment | Offer a €5 voucher |
| Randomization unit | One unique customer ID |
| Primary metric | Binary 14-day conversion: at least one recorded purchase, regardless of voucher redemption |
| Baseline planning probability | 0.20 (20%) |
| Target treatment planning probability | 0.23 (23%) |
| Absolute MDE | 0.03, or +3 percentage points |
| Outcome-test alpha | 0.05, two-sided |
| Planning power | 0.80 |
| Planned allocation | 50% control / 50% treatment |
| Assignment seed | `20261106` |
| SRM diagnostic significance threshold | 0.01, separately declared from outcome alpha |

The null hypothesis is **H₀: p_treatment = p_control**. The two-sided alternative
is **H₁: p_treatment ≠ p_control**. Although the business hopes for an increase,
the design reserves false-positive probability for either direction; we do not
quietly switch to a one-sided test to lower sample size.

The planned outcome window is `[assignment_time, assignment_time + 14 days)`,
using a common declared clock such as UTC. Each assigned customer contributes
one binary outcome after complete follow-up, rather than one row per purchase
or one row per voucher use. This is a definition for the design, **not an outcome
implementation**: no timestamps, purchases, redemptions, or labels are generated
in Phase 8A. Future tracking would need consistent coverage in both arms; missing
follow-up should not automatically become a non-conversion.

For a concrete interpretation, a hypothetical 20% baseline corresponds to an
expected 200 purchasers per 1,000 comparable customers; 23% corresponds to 230.
The planning difference is 30 per 1,000, **not a measured voucher benefit**.
Three percentage points is a 15% relative increase because 0.03/0.20=0.15. It is
not a 3% relative increase, which would only take 20% to 20.6%.

Alpha 0.05 means that, under the null and valid test assumptions, a prespecified
test would falsely reject in about 5% of repeated experiments. It is not the
probability that this null is true. Power 80% means about 80% detection at the
specified 20%-versus-23% alternative under the planning approximation. It does
not mean an 80% chance that the voucher works. Smaller effects may sometimes be
detected and the MDE is not a hard threshold for significance.

These values were provided for illustration. They are **not** inferred from
REES46, RetailHero, or actual voucher customers. The €5 face value defines the
intervention; no spend, redemption cost, revenue, or ROI is calculated.

## Sample-size formula and actual calculated output

Use the usual independent two-proportion **normal approximation**, with equal
sample sizes n in each arm, pooled variance under the null and separate arm
variances under the planning alternative. There is no continuity correction.
This is a planning approximation, not a finite-binomial exact power calculation.

Let `p_C=0.20`, `p_T=0.23`, `δ=p_T−p_C=0.03`, and
`p̄=(p_C+p_T)/2=0.215`. Let z_q be the standard-normal quantile at probability q.

```text
V₀ = 2 p̄(1 − p̄)                    = 0.33755
V₁ = p_C(1 − p_C) + p_T(1 − p_T)    = 0.33710
z_(1−α/2)                          = 1.9599639845400534
z_power                            = 0.8416212335729144

n = [z_(1−α/2) √V₀ + z_power √V₁]² / δ²
  = 2942.5867373842148 per arm, before rounding
```

The first term makes the expected signal large enough to pass a two-sided
significance cutoff; the second provides the margin needed to reach the desired
power despite sampling variation. Dividing by δ² explains why smaller target
effects can require many more customers.

Round **up in each arm**:

- **Control: 2,943 customers.**
- **Treatment: 2,943 customers.**
- **Total: 5,886 customers with complete follow-up, under balanced allocation.**

This closed form uses the two-sided alpha/2 critical value but neglects the
remote rejection tail under the positive alternative. The same normal-planning
convention is described in the [statsmodels sample-size documentation](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.samplesize_proportions_2indep_onetail.html).
Statsmodels is not installed or added here, and no claim of executing that
library is made.

### Independent verification without another dependency

Rather than verify the formula by rewriting the same arithmetic, independently
calculate the probability of rejection from **both normal tails**, then solve
for n numerically with SciPy's `brentq`:

```text
c(n)  = z_(1−α/2) × √(V₀/n)
SE(n) = √(V₁/n)

approximate_power(n) =
  P[Normal(δ, SE(n)²) > c(n)] + P[Normal(δ, SE(n)²) < −c(n)]
```

This yields **2942.57962599342** per arm before rounding, independently returning
**2,943 per arm**. The 0.0071-customer difference comes from including the remote
tail; it does not change the integer recommendation. Approximate two-tail power
is **0.8000560434** at 2,943 per arm and **0.7999227034** at 2,942. Thus the
rounded recommendation crosses the 80% threshold in the independently inverted
normal model. This is mathematical planning verification, not simulation of
conversion outcomes or analysis of an A/B result.

For this scenario the expected per-arm conversion and non-conversion counts are
large, making a normal approximation reasonable. Rare outcomes or tiny groups,
clustering, incomplete follow-up, noncompliance, multiple primary metrics,
repeated peeking, or incorrect baseline/effect assumptions could require a
different design or more customers. No attrition buffer, sequential monitoring
rule, or outcome analysis is implemented here.

## Customer-level assignment

`assign_customers(customer_ids, design)` accepts only customer IDs and the
declared design. No outcome, purchase history, demographics, or future behavior
is an input. It returns a dictionary mapping each unique ID to one of the two
literal groups `control` and `treatment`, in sorted ID order.

For each ID:

1. Validate a nonempty string without outer whitespace. Preserve case, Unicode,
   and leading zeros. Reject missing/non-string IDs; do not turn missing values
   into a literal identifier such as `"None"`.
2. Reject duplicate IDs, instead of silently deduplicating a potentially faulty
   join or assigning two rows independently. An empty input can return an empty
   mapping, but zero customers cannot produce a meaningful SRM test.
3. Canonically encode the UTF-8 JSON array
   `[algorithm_version, experiment_id, seed, customer_id]`, with fixed separators.
   Algorithm version: `growthlab-experimentlab-sha256-v1`.
4. SHA-256 hash that payload and interpret all 256 digest bits as a nonnegative
   integer h. Assign treatment when `h < 2²⁵⁶ × 0.5`; otherwise control. The
   implementation compares integer products using a rational threshold to avoid
   floating-point bucket-boundary ambiguity.

The expected allocation is 50/50, but sizes are not forced to match. Unlike
sorting hashes and taking an exact half, this threshold method leaves an existing
customer's assignment unchanged when another customer is added. Changing input
order likewise leaves both assignment and serialized ordering unchanged. The
experiment ID separates hypothetical experiments; the same customer can have a
different assignment in a different experiment without being in both groups
within one experiment. Tests verify these properties.

This is a **reproducible simulation/design assignment mechanism**, not a
security-grade production randomization service. SHA-256 being a cryptographic
primitive does not make a public seed secret or prevent someone from choosing
IDs to manipulate membership. The binomial interpretation treats hash outputs
as effectively uniform and independent for non-adversarial IDs. Actual production
assignment would need its own reviewed, protected, auditable mechanism; for
example, a secret-keyed service could prevent users predicting/manipulating their
arm. No production service or experiment execution is built here.

## Assignment-only example and SRM

The example uses only synthetic IDs from `synthetic-customer-000001` through
`synthetic-customer-005886`, inclusive, with the seed fixed **before** examining
counts. It creates no customer outcomes or customer-level data files.

| Assignment-only quantity | Calculated result |
| --- | ---: |
| Synthetic customer IDs | 5,886 |
| Control | 2,950 (50.118926%) |
| Treatment | 2,936 (49.881074%) |
| Expected under planned 50/50 allocation | 2,943 in each arm |
| SRM two-sided exact-binomial p-value | **0.8654470932079597** |
| Predeclared SRM threshold | 0.01 |
| SRM flag | **False** |

These are calculated properties of one deterministic synthetic assignment
example, **not empirical conversion evidence or an A/A experiment**.

The treatment group is seven below the balanced per-arm target, despite the
total equaling 5,886. This is not hidden by reporting just total N: the generated
summary explicitly flags that the treatment per-arm planning minimum is not
reached. Approximate 50/50 assignment does **not** guarantee the two exact planned
arm sizes. Before any future execution, recruitment/sample-size handling would
need to be declared so the achieved allocation supports the desired power (for
example, a prospective buffer or a different prespecified allocation design).
Do not change the seed, discard customers, or rebalance retrospectively to make
the example look perfect. No recruitment or stopping algorithm is implemented
in Phase 8A, and no achieved outcome-test power is claimed for these realized
unequal groups.

### What the SRM test asks

If independent customers are assigned to treatment with planned probability q,
the treatment count K has the binomial reference distribution `Binomial(N,q)`.
The two-sided exact test sums probabilities of counts at least as inconsistent
with that null as the observed count (probability no greater than the observed
count's probability). It checks the **allocation**, not whether vouchers work.
SciPy's [binomtest documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.binomtest.html)
describes this exact binomial test; we call it with `alternative='two-sided'`.

For a simple hand-checkable case, if 10 customers all land in one arm under q=0.5,
the probability of either extreme is `2 × (1/2)^10 = 0.001953125`, which triggers
the declared 1% diagnostic. A 60/40 count split out of 100 has p≈0.056888 and does
not. For the actual synthetic-ID example, the expected treatment count is 2,943
and its binomial standard deviation is about 38.36; a seven-customer deviation is
ordinary variation, not automatically a faulty randomizer.

SRM uses a separately declared **1% investigation threshold**; it does not change
the planned 5% conversion-test alpha. A flag suggests investigating allocation,
eligibility, logging, or filtering. It does not prove the randomization is
invalid, and an unflagged result does not prove assignments were random or
independent. Even a correct randomizer can occasionally flag by chance. Fixed
quota/block randomization would have a different count reference distribution;
this check is appropriate to the threshold/Bernoulli-style design, not a test of
exact-quota allocation. Repeated monitoring would also need its own treatment;
only one declared count check is demonstrated here.

## Implementation, tests, and reproducibility

The small design module contains:

- An immutable, validated configuration.
- The closed-form equal-arm sample-size calculator using standard-library normal
  quantiles, with explicit rounding and assumptions.
- An independent SciPy two-tail planning cross-check and numerical root solve.
- Deterministic ID-only assignment with strict ID/duplicate validation.
- A reusable count-only SRM function with input validation and a declared null
  allocation probability. This function can check a non-50/50 declared ratio,
  but the Phase 8A **design/sample-size API remains balanced-only**.
- A CLI that prints one small hypothetical planning/assignment summary. It
  neither downloads data nor saves a customer-level assignment table.

Reproduce from the repository root in the existing environment:

```sh
PYTHONPATH=src .venv/bin/python -m growthlab.experimentlab.design
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

The default config path is `docs/experiments/phase8a_config.json`; `--config`
accepts another reviewed configuration. SciPy **1.18.1** is already pinned in
`requirements-causal.lock` and installed. No package was added/upgraded, and no
prior dependency file was changed. The experiment module has no imports from
Module 1 or RetailHero. It processes just 5,886 synthetic IDs in memory; no large
event dataset, real customer file, or trained model is loaded for this phase.
The CLI rejects examples above 100,000 IDs before allocating the list; the
sample-size function can still calculate larger plans without creating customer
records. This prevents a tiny MDE in an alternate configuration from allocating
an unnecessarily large synthetic cohort on the 8 GB Mac.

**All 145 tests pass, with no skips:** 120 prior tests plus 25 new tests. New
tests cover the sample size and independent normal-tail inversion, per-arm
rounding, expected monotonicity, invalid planning/configuration values,
immutable configuration, repeated assignment, stable ordering, disjoint arms,
cohort growth, seed/experiment namespaces, independent first-hash-bit checking,
exact example counts, duplicate/missing IDs, preserved identifiers, empty input,
balanced and hand-enumerated binomial examples, ordinary/extreme imbalances,
separate diagnostic thresholds, arbitrary SRM null probability, invalid counts,
and explicit reporting of the short treatment arm. Only synthetic identifiers
appear in the new tests; no conversion outcomes are used in them. The required
full suite includes the existing prior-module tests without changing those
modules.

The [planning summary](phase8a_planning_summary.json) contains full-precision
calculated numbers and explicit hypothetical scope, not customer-level records.
No expected outcome count is presented as an observation.

Files added:

- `src/growthlab/experimentlab/__init__.py`
- `src/growthlab/experimentlab/design.py`
- `tests/test_experimentlab_design.py`
- `docs/experiments/phase8a_config.json`
- `docs/experiments/phase8a_planning_summary.json`
- This report, `docs/experiments/phase8a_design.md`.

Git status: six new, untracked review files; no existing tracked-file changes,
nothing staged, and no commit/push. Phase 8A stops here for review. No outcome
simulation, A/A test, A/B outcome analysis, reward optimization, ranking, dashboard,
Docker, or deployment has begun.
