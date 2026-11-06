# Phase 9B — Hypothetical reward comparisons and sensitivity

Completed locally for review on 2026-11-06. **Deterministic hypothetical
assumptions, not measured campaign effects or an optimal-reward discovery.**
No statistical confidence intervals, response model, customer/product ranking,
Streamlit, Docker, deployment, or other module is implemented. Phase 9B is not
committed or pushed.

## Phase 9A was verified and preserved first

The six Phase 9A files were reviewed, all **213 tests passed**, and the exact
reference output reproduced. Prior frozen inputs, results, and 82 prior
data/artifact file states verified unchanged. The staged allowlist excluded
datasets, sensitive records, caches, and credentials.

Phase 9A was committed and pushed as
**`12af12a3245966188286fabade8d5cfe162ccb79`**, titled
`Complete Phase 9A deterministic reward economics and exact break-even calculations`.
Local HEAD matched `origin/main`, and Git was clean before Phase 9B development.
The verified economics engine remains unchanged.

## What this layer adds

The new module wraps each Phase 9A `RewardScenario` with explicit scenario ID,
population ID, outcome horizon in days, financial-accounting-basis ID, and a note
describing its hypothetical assumptions. Every scenario in the
[example configuration](phase9b_scenario_config.json) explicitly supplies **all
seven financial inputs**, including contact count and both conversion rates.
There are no silently inherited financial defaults.

`evaluate_scenario` calls the existing **`economics.result_payload`**; all
purchaser, contribution, redemption, expenditure and break-even calculations
therefore come from the original engine. The wrapper adds only metadata, net
contribution per contact, and classification of the resulting net amount.
`compare_scenarios` decides whether sorting totals is meaningful; `sensitivity`
changes one declared input at a time and invokes the same engine.

There are no real customer IDs or records. Population labels such as
`hypothetical-cohort-A` are declarations for illustrative comparability, not
identities imported from REES46 or RetailHero. Their populations are never
linked, pooled, or used as evidence for the assumed conversion rates.

## Financial calculations, all inherited from Phase 9A

Let N be contacts, p₀/p₁ baseline/assumed treatment conversion, M contribution
per purchase before incentives, R reward value/cost per redemption, D redemption
probability **among treatment purchasers**, and K cost per contacted customer.
The unchanged model assumes binary conversion, one modeled purchase per
converter, at most one redemption, the same M in both conditions, and no
baseline reward/contact cost.

```text
Baseline expected purchasers       = N p₀
Treatment expected purchasers      = N p₁
Expected incremental conversions   = N(p₁−p₀)
Incremental purchase contribution  = N(p₁−p₀) M
Expected redemptions               = N p₁ D
Reward expenditure                = N p₁ D R
Contact expenditure               = N K
Net incremental contribution      = incremental contribution − reward − contact
Net per contacted customer        = net / N, when N>0
```

Rewards are paid on **all qualifying redemptions**, not just incremental
purchases. Contact costs apply to every contact, not only purchasers. For zero
contacts, totals are zero and net per contact is **null**, not an invented zero
rate obtained by dividing zero by zero.

For positive N and `M−DR>0`, the inherited break-even conversion threshold is
`p₁*=(p₀M+K)/(M−DR)`, subject to [0,1]. The original engine's exact fractions and
all special cases—unattainable thresholds, zero contacts, all-rate neutrality,
and zero-conversion-only neutrality—are passed through unchanged. A feasible
threshold is mathematical feasibility, not evidence that an offer can achieve
that response.

The requested profitability flag means **net incremental contribution > 0 under
the supplied assumptions**. Zero is labeled break-even and is not called
profitable; zero contacts are labeled separately. This is not a statement about
complete accounting profit, ROI, or observed financial returns. Fixed costs,
tax, returns, repeat purchases and unprovided cost items remain excluded.

## When scenario totals can be ranked

The comparison guard requires equality of these declared attributes:

1. Population ID: the same hypothetical eligible customer population/context.
2. Number of contacted customers: equal scale, so total contribution is comparable.
3. Horizon days: the same conversion window.
4. Financial-basis ID: a common accounting/currency/cost-inclusion convention.
5. Baseline conversion probability: the same counterfactual without intervention.
6. Contribution per purchase before incentives: the same purchase-contribution basis.

All examples use EUR and one-purchase contribution with no fixed costs, as
required by Phase 9A. Metadata consistency is a **guard**, not proof that real
campaign contexts are identical. The caller must ensure, for example, that a
shared 14-day horizon actually represents a common decision window rather than
different seasonal contexts. Mislabeling two populations as the same would not
be detected from arithmetic alone.

Within a comparable set, assumed treatment conversion, reward, redemption, and
campaign-specific contact cost may differ. Those explicitly stated intervention
assumptions are the alternatives being compared. Changing the common margin or
baseline instead changes the evaluation setting; the guard conservatively
blocks ranking those scenarios together. Margin sensitivity is still shown,
but never promoted into an offer ranking.

If any criterion differs, rows remain available but **ranking is null** and the
mismatched criteria are listed. Zero-contact sets also receive no ranking.
The per-contact display does not silently authorize ranking different
populations or horizons.

Comparable rows are ordered by **descending expected net incremental
contribution only**. Equal amounts share a competition rank (for example
1,1,3); scenario IDs stabilize the displayed order of ties without expressing a
financial preference. Results and ranking are input-order independent. If every
scenario loses money, the first-ranked one is merely the least negative of that
provided set, not a profitable recommendation.

## Worked comparable examples

All four scenarios share hypothetical cohort A, **1,000 contacts**, **14 days**,
baseline **20%**, purchase contribution **€20**, and financial basis
`EUR-single-purchase-no-fixed-costs-v1`. Their complete individual inputs are in
the configuration; the varying assumptions are:

| Scenario | Assumed treatment conversion | Reward per redemption | Redemption among treatment purchasers | Cost per contact |
| --- | ---: | ---: | ---: | ---: |
| Reference full redemption | 23% | €5 | 100% | €0 |
| Partial redemption | 23% | €5 | 50% | €0 |
| Higher assumed conversion | 30% | €5 | 100% | €0 |
| Lower reward assumption | 23% | €2 | 100% | €0.10 |

**None of these conversion/redemption assumptions is an estimated offer effect.**
In particular, the €2 row does not assert that reducing a reward preserves 23%
conversion. The 30% row assumes a more favorable response; it does not discover
that a €5 reward causes it.

Actual outputs of the deterministic comparison:

| Scenario | Incremental conversions | Reward expenditure | Contact expenditure | Net contribution | Net/contact | Break-even treatment conversion | Positive net? |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Reference full redemption | 30 | €1,150 | €0 | **−€550** | −€0.55 | 4/15 ≈ 26.6667% | No |
| Partial redemption | 30 | €575 | €0 | **€25** | €0.025 | 8/35 ≈ 22.8571% | Yes |
| Higher assumed conversion | 100 | €1,500 | €0 | **€500** | €0.50 | 4/15 ≈ 26.6667% | Yes |
| Lower reward assumption | 30 | €460 | €100 | **€40** | €0.04 | 41/180 ≈ 22.7778% | Yes |

How each net is calculated:

- **Reference:** 30×€20 = €600 incremental purchase contribution. All 230
  expected treatment purchasers redeem €5, costing €1,150. Net = €600−€1,150 =
  **−€550**, exactly the Phase 9A reference.
- **Partial redemption:** the same €600 contribution, but 230×50%=115
  expected redemptions cost €575. Net = €600−€575 = **€25**.
- **Higher assumed conversion:** 300−200=100 incremental purchases contribute
  €2,000. All 300 expected treatment purchasers redeem €5, costing €1,500.
  Net = €2,000−€1,500 = **€500**.
- **Lower reward assumption:** 30 incremental purchases contribute €600.
  Reward cost = 230×€2 = €460. Contact cost = 1,000×€0.10 = €100.
  Net = €600−€460−€100 = **€40**.

Their conditional order is **higher assumed conversion (€500), lower reward
assumption (€40), partial redemption (€25), reference (−€550)**. This is an
ordering of supplied hypotheses, not a statistically established policy winner
or an optimal reward amount. All counts are expectations, not observed people.

### Non-comparable example

The second demonstration pairs the reference with a different hypothetical
cohort B: **2,000 contacts, 30 days, baseline 20%, assumed treatment 23%, reward
€5, redemption 50%, contribution €25, contact cost €0**. Every input is explicit.
It produces 60 incremental conversions, €1,500 incremental purchase contribution,
€1,150 reward cost and **€350 net**, or **€0.175 per contact**.

It is **not ranked** against cohort A. The actual blocked reasons are
`population_id`, `contacted_customers`, `horizon_days`, and
`contribution_per_purchase_eur`. The larger total is not evidence of a better
reward offer; the scale and evaluation setting changed.

## One-assumption-at-a-time sensitivity

Each table starts from the full-redemption reference and changes only the named
input; every other financial input and context attribute remains fixed. There
is no Cartesian-product search, fitted reward-response curve, or recommendation
to choose a grid endpoint. Points appear in increasing parameter-value order,
**not ranked by their net contribution**. Their ranges are not confidence
intervals or probability distributions over uncertain assumptions.

| Assumed treatment conversion | Expected net contribution |
| --- | ---: |
| 20% | −€1,000 |
| 23% | −€550 |
| 26% | −€100 |
| 27% | €50 |
| 30% | €500 |

Changing only conversion leaves the break-even threshold at 26⅔%; the net
crosses zero between 26% and 27%. A positive +3 pp conversion assumption can
still lose contribution. The threshold is not inferred from a response model.

| Assumed reward per redemption | Expected net, holding conversion at 23% |
| --- | ---: |
| €0 | €600 |
| €2 | €140 |
| €5 | −€550 |
| €8 | −€1,240 |

Higher rewards mechanically cost more **when conversion and redemption stay
fixed**. The zero-reward point does not establish that no reward could achieve
23% conversion. No causal relationship from reward amount to conversion has
been invented; that relationship is precisely what is unknown here.

| Assumed redemption probability among treatment purchasers | Expected net |
| --- | ---: |
| 0% | €600 |
| 50% | €25 |
| 100% | −€550 |

The conclusion changes from positive to negative as redemption rises with the
assumed conversion held fixed. This is a what-if accounting result, not evidence
that lower redemption would preserve purchase response or be operationally
desirable.

| Assumed contribution per purchase | Expected net |
| --- | ---: |
| €10 | −€850 |
| €20 | −€550 |
| €40 | €50 |

Here the same 30 incremental purchases are worth more as M rises, while reward
cost remains €1,150. This changes the financial basis, so these margin points
are **not ranked as competing offers**. No actual margin or customer lifetime
value was estimated.

| Assumed contact cost per customer | Expected net |
| --- | ---: |
| €0 | −€550 |
| €0.05 | −€600 |
| €0.20 | −€750 |

Every contact incurs K, so €0.05 across 1,000 contacts subtracts €50, not just
€0.05 per incremental converter. There is no extra cost measurement behind
these hypothetical rates.

## Precision, invalid inputs and edge cases

Phase 9A's validated decimal inputs, exact rational arithmetic and break-even
fractions are preserved. The comparison layer does not recompute those
financial formulas. The only new financial ratio is **existing exact net / N**,
converted using the engine's existing exact-decimal helper. For example, €25 per
1,000 contacts is exactly €0.025 per contact; rounding it to €0.03 before
comparison would be misleading. Approximate percentages in the tables do not
replace exact break-even fractions in the output.

Metadata must be nonempty, horizons positive integer days, and scenario IDs
unique within a comparison. Missing economic fields, invalid probabilities,
negative money, unsupported sensitivity fields and duplicate grid values are
rejected. The scenario and per-field grid sizes are limited to 1,000 items.
The API supports zero-contact calculations but returns null per-contact values
and withholds rankings. Profitability is strict positivity; a zero net amount
is not called profitable. All Phase 9A break-even statuses remain available,
including unattainable and degenerate cases, rather than being silently
converted to a percentage.

## Implementation, tests and reproduction

`ScenarioSpec` supplies context around the existing `RewardScenario`.
`scenario_from_dict` requires all financial inputs. `evaluate_scenario` delegates
to Phase 9A; `compare_scenarios` validates declared comparability before sorting;
`sensitivity` constructs separate frozen input objects with just one field
changed and does not mutate the base scenario. `run_examples` executes the
reviewable configuration, including a deliberately non-comparable set.

Reproduce from the repository root:

```sh
PYTHONPATH=src .venv/bin/python -m growthlab.rewards.scenarios
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

The CLI prints a small JSON result. It does not read customer data, generate
customer-level records, write large artifacts, or require additional packages.
The [aggregate summary](phase9b_scenario_summary.json) includes complete scenario
inputs and outputs, held-constant sensitivity assumptions, comparability
decisions, exact thresholds, and source/config fingerprints. All results are
deterministic; no statistical confidence intervals or artificial uncertainty
bands are created for hypothetical assumptions.

**All 235 tests pass, with no skips:** 213 prior tests plus 22 scenario tests.

A separate final verification reproduced the saved scenario summary exactly
and matched its source/config SHA-256 fingerprints. Prior frozen inputs,
all 82 recorded prior data/artifact file states, Phase 7 final artifacts/figures,
and Phase 8B/8C aggregate and input hashes passed their existing integrity
checks. The Phase 9A reference output also reproduced unchanged. Git confirms
no previously tracked file changed and nothing is staged; the five new files
contain only code, synthetic assumptions, tests and aggregate documentation.

New tests cover multi-scenario outputs/order, direct reuse of the unchanged
engine, exact break-even consistency, net per contact, positive/negative/neutral
results, shared-rank ties, all-negative sets, population/horizon/accounting/count/
baseline/margin mismatches, zero contacts, reproducibility and input-order
independence, all five sensitivity fields, held-constant conversion when reward
changes, threshold invariance when only treatment conversion changes, unranked
margin sensitivity, strict input validation and Decimal-context independence.

Files created in Phase 9B:

- `src/growthlab/rewards/scenarios.py`
- `tests/test_reward_scenarios.py`
- `docs/rewards/phase9b_scenario_config.json`
- `docs/rewards/phase9b_scenario_summary.json`
- This report, `docs/rewards/phase9b_scenarios.md`.

No prior tracked file or dependency lock is changed. Phase 9B has five new
untracked review files, nothing staged, and no commit/push. HEAD remains the
pushed Phase 9A commit `12af12a`.

## Limitations and stopping point

Scenarios can be compared arithmetically without their assumptions being true.
Ranking an optimistic hypothetical response first does not establish its
feasibility or causal effect. In particular, no Phase 8C simulated +3 pp is
treated as observed voucher evidence, and REES46 and RetailHero populations are
not merged or used in this study.

The inherited engine still excludes repeat purchases, heterogeneous margins,
fixed campaign costs, timing/discounting, tax, returns, and settlement rules.
Redemption may change with conversion or reward value in reality; one-factor
sensitivity deliberately holds it fixed when varying another input. Interactions
or real reward-response functions are not modeled. No financial inputs or
customer lifetime values are presented as measured quantities.

Stop after Phase 9B for review. No real optimal reward has been discovered, and
no product ranking, Streamlit, Docker, deployment, or other module has begun.
