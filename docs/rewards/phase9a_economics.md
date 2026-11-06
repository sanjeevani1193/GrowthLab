# Phase 9A — Deterministic reward economics engine

Completed locally for review on 2026-11-06. **Hypothetical expected values only.**
No actual reward effect, margin, redemption rate, customer lifetime value, or
campaign cost was measured or inferred. No optimization, ranking, dashboard,
Docker, deployment, commit, or push is included.

## Repository review and scope

Git was clean at the committed Phase 8C baseline
`bc2cffb371dcd4318ee9df9953e37de76b597fc6`; local `main` matched `origin/main`.
All **184 existing tests passed** before implementation. The repository contained
prediction, RetailHero causal/uplift evaluation, and synthetic experimentation
utilities, but no reusable reward-economics engine.

The new `growthlab.rewards` package uses only the Python standard library. It
does not import the prediction, RetailHero, A/A, or A/B modules, read their
results, or join their customer populations. Existing tracked files and
dependency locks are unchanged. The 20%/23% inputs below are the user's
**hypothetical reference case**, not empirical voucher evidence from Phase 8C.

## Business objective and inputs

Question: for the same customers, is the campaign's **expected incremental
purchase contribution** enough to cover its expected reward and contact costs?

The comparator is **no intervention for the same N customers**, not a second
observed sample of N customers. Baseline is assumed to have no additional reward
or contact cost. All amounts are EUR; no currency conversion is implemented.

| Input | Meaning and allowed values |
| --- | --- |
| `contacted_customers` (N) | Nonnegative integer number contacted in the intervention; booleans/fractional counts are rejected |
| `baseline_conversion` (p₀) | Hypothetical probability of a purchase without intervention, in [0,1] |
| `treatment_conversion` (p₁) | Hypothetical probability with intervention, in [0,1]; may be less than p₀ |
| `contribution_per_purchase_eur` (M) | Nonnegative contribution from one modeled purchase **before reward/contact costs**, equal in both conditions |
| `reward_per_redemption_eur` (R) | Nonnegative cost/value charged to the campaign for one redemption |
| `redemption_probability` (D) | Probability of redemption **among treatment purchasers**, in [0,1], not among all contacts |
| `contact_cost_per_customer_eur` (K) | Nonnegative cost incurred for every contacted customer, including non-purchasers |

Contribution is not gross sales revenue. In a future real application, M would
need to reflect the appropriate purchase contribution after ordinary purchase
costs; this engine does not estimate it or include unspecified costs. Here the
€20 value is supplied for illustration only. Likewise, reward value R is assumed
to equal the campaign's cost per redemption in this version; actual reward
accounting can differ and is not inferred.

## Assumptions

- Binary conversion: each customer either makes one modeled qualifying purchase
  or does not. Additional transactions, repeat-purchase behavior and lifetime
  value are not represented. There is at most one rewarded purchase and one
  redemption per converted customer.
- A non-purchaser cannot redeem a reward in this model. Reward redemptions are
  conditional on treatment purchase, so their expected number is `N×p₁×D`.
- All redeeming treatment purchasers receive the reward, not just the
  incremental purchasers. The engine does not identify which individual
  purchases would or would not have happened anyway.
- M is the same per purchase with and without intervention. Basket size,
  contribution mix, returns, timing shifts, spillovers, and future purchases
  do not change except through the two assumed conversion probabilities.
- Contact cost is paid for all N intervention contacts. There is no extra
  baseline campaign cost to subtract. Fixed campaign costs, tax effects,
  discounting, delivery costs beyond K, and other unprovided costs are excluded.
- For break-even, M, R, D and K remain fixed as p₁ varies. This is an algebraic
  threshold, not an estimate of how redemption or conversion responds to reward
  amount and not an optimization of reward value.
- All outputs are expectations. Fractional expected purchasers/redemptions and
  sub-cent expected financial totals are legitimate; they are not observed
  fractional people or a claim about actual cash settlement.

## Formulas and interpretation

```text
Expected purchasers without intervention = N p₀
Expected purchasers with intervention    = N p₁
Expected incremental purchasers          = N(p₁ − p₀)
Conversion effect in percentage points   = 100(p₁ − p₀)

Incremental purchase contribution        = N(p₁ − p₀) M
Expected reward redemptions              = N p₁ D
Reward expenditure                      = N p₁ D R
Contact expenditure                     = N K

Net incremental contribution            = N(p₁ − p₀)M − N p₁ D R − N K
```

For example, 50% redemption with 230 expected treatment purchasers means
**115 expected redemptions**, not 500 redemptions among 1,000 contacts. The
conditional denominator matters. A positive conversion effect is not sufficient
for positive economics because all redeemed rewards must be funded.

The output is named **net incremental contribution**, not profit, ROI, or total
revenue. A negative result means the specified incremental purchase contribution
does not cover the specified incremental campaign costs under these assumptions.
It is not an observed loss or a general verdict about vouchers.

## Verified hypothetical reference example

The [reference configuration](phase9a_reference_config.json) specifies:

| Input | Hypothetical value |
| --- | ---: |
| Contacts | 1,000 |
| Baseline conversion | 20% |
| Treatment conversion | 23% |
| Contribution per purchase before incentive costs | €20 |
| Reward per redemption | €5 |
| Redemption probability among treatment purchasers | 100% |
| Contact cost per customer | €0 |

The calculated output is:

| Expected quantity | Calculation | Exact result |
| --- | --- | ---: |
| Purchasers without intervention | 1,000 × 0.20 | **200** |
| Purchasers with intervention | 1,000 × 0.23 | **230** |
| Incremental purchasers | 230 − 200 | **30** |
| Conversion effect | 100 × (0.23 − 0.20) | **+3 pp** |
| Incremental purchase contribution before campaign costs | 30 × €20 | **€600** |
| Reward redemptions | 230 × 1.0 | **230** |
| Reward expenditure | 230 × €5 | **€1,150** |
| Contact expenditure | 1,000 × €0 | **€0** |
| Net incremental contribution | €600 − €1,150 − €0 | **−€550** |

The economic insight is the difference between paying for **230 expected
redemptions** and earning incremental purchase contribution from **30 expected
additional purchases**. Paying rewards only on the 30 incremental purchasers
would incorrectly make this case look profitable. Their identities are not
available here, and the stipulated reward is paid on every qualifying redemption.

### Independent verification

Use a separate total-contribution comparison instead of the incremental formula:

```text
Baseline purchase contribution:       200 × €20              = €4,000
Treatment purchase contribution:      230 × €20              = €4,600
Treatment after reward/contact costs: €4,600 − €1,150 − €0    = €3,450
Incremental comparison:               €3,450 − €4,000         = −€550
```

The independent hand calculation is also verified with exact fractions in the
automated tests. The [reference summary](phase9a_reference_summary.json) contains
the full computed output, not a real campaign result.

## Break-even conversion improvement

For N>0, divide net contribution by N and collect p₁:

```text
Net/N = p₁(M − D R) − (p₀ M + K)
```

Let `A=M−DR`, the contribution left per treatment purchase after expected reward
cost, and `B=p₀M+K`, the per-contact baseline contribution/contact-cost hurdle.

For the ordinary case **A>0**:

```text
p₁* = B/A = (p₀ M + K)/(M − D R)
Required conversion change in pp = 100(p₁* − p₀)
```

If p₁*≤1, equality is mathematically feasible and net contribution is nonnegative
at or above that threshold. If p₁*>1, no valid conversion probability can cover
the specified costs. A threshold equal to one is feasible equality at 100%
conversion, not evidence that positive contribution can be achieved beyond it.

For the reference example:

```text
A = €20 − 1.0 × €5 = €15 per treatment purchase
B = 0.20 × €20 + €0 = €4 per contact
p₁* = 4/15 = 0.266666… = 26.666666…%
Required increase = 1/15 in probability = 20/3 pp = 6.666666… pp
```

Therefore **break-even treatment conversion is 26⅔%, requiring +6⅔ pp over
baseline**, holding everything else fixed. At that exact threshold the net is
zero; above it the modeled net becomes positive. The supplied +3 pp assumption
falls below this threshold. “Attainable” means **within the mathematical [0,1]
probability range**, not that a €5 offer can actually cause that conversion rate.
No causal response to reward amount was estimated.

An independent exact substitution checks
`1000×(4/15)×(20−5) − 1000×(1/5)×20 = 0`.
The sign also brackets the threshold: treatment conversion 26% gives **−€100**,
and 27% gives **+€50**, under the same hypothetical inputs. These are fixed
arithmetic checks, not a scenario optimizer or evidence of observed effects.

### Degenerate and impossible conditions

The implementation handles the full nonnegative-input domain without dividing
by a nonpositive denominator or manufacturing an impossible probability:

| Condition | Status and meaning |
| --- | --- |
| N=0 | `no_customers`: financial totals are zero; no meaningful campaign threshold, with `attainable=null` |
| A>0 and B/A≤1 | `attainable`: the reported threshold and signed conversion change are feasible |
| A>0 and B/A>1 | `unattainable`: feasible threshold fields are null; the unconstrained ratio is retained for explanation |
| A≤0 and B>0 | `unattainable`: purchases cannot add positive contribution after rewards, and a positive hurdle remains |
| A=0 and B=0 | `all_rates_break_even`: net is zero for every rate; no unique threshold and no positive modeled gain |
| A<0 and B=0 | `zero_conversion_only`: only p₁=0 is neutral; every positive conversion loses contribution |

The final case is not described as profitable conversion improvement. The
required change can be negative in such a degenerate zero-margin setting; the
field is explicitly named `required_conversion_change_pp`. For example, when
purchase contribution is zero but reward costs are positive and contacts are
free, avoiding all treatment conversions is the only neutral point. This is
algebraic boundary handling, not a recommendation to reduce sales.

For any positive N, per-customer assumptions make N cancel from the break-even
threshold. This would no longer hold with an unmodeled fixed campaign cost.
For N=0, the input probability contrast remains p₁−p₀ (for example +3 pp), but
expected counts and all contribution/cost totals are zero. That contrast is a
configured assumption, not an effect estimated from an empty campaign.

## Precision and deterministic implementation

Inputs accept finite decimal strings, `Decimal`, integers, or floats, with
booleans rejected. Probabilities must be in [0,1], monetary inputs nonnegative,
and contacts a nonnegative integer. Zero endpoints and negative conversion
effects are allowed; negative monetary inputs and NaN/infinite values are not.

Decimal strings are recommended for precise money. Floats are interpreted via
their shortest decimal string representation; the engine cannot recover a
user's intended number after an earlier floating-point calculation has already
introduced an artifact.

The frozen input dataclass normalizes numbers to `Decimal`. Internally, finite
decimals are converted to **exact rational numbers** for products/sums and then
back to terminating decimal outputs without rounded division. This avoids binary
floating-point money errors, premature cent rounding, and dependence on the
caller's Decimal precision. No external dependency is required.

Break-even ratios can repeat, so they are retained as exact `Fraction` values.
The JSON output presents an exact fraction plus a separately labeled 40-digit
decimal approximation. Reference threshold `4/15` and change `20/3 pp` remain
exact; expected counts and money are encoded as exact decimal strings.

No rounding is applied between model steps. For example, the expected net with
three contacts and 50% redemption in this hypothetical case is **€0.075**, which
is not silently rounded to €0.08 or €0.07. Actual payout/settlement rounding is a
different problem and is not implemented. Likewise, using a displayed rounded
break-even rate of 26.67% instead of exact 26⅔% produces **+€0.50**, not exactly
zero, at 1,000 contacts. Display rounding must not be treated as an exact target.

## Tests and reproduction

**All 213 tests pass, with no skips:** 184 prior tests plus 29 reward-economics
tests. New tests cover the required reference and an independent total-cashflow
calculation, zero reward cost, zero treatment effect, positive/negative effects,
partial/no redemption, contact costs, fractional expected counts/sub-cent money,
zero purchasers, zero contacts, exact break-even substitution and sign changes,
campaign-size invariance, partial-redemption/contact thresholds, probabilities
above 100%, zero/negative post-reward contribution, neutral/zero-only boundary
cases, invalid probabilities/counts/money, deterministic frozen inputs, large
exact totals, and independence from a deliberately low-precision Decimal context.

Reproduce the supplied reference from the repository root:

```sh
PYTHONPATH=src .venv/bin/python -m growthlab.rewards.economics
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

The default config is `docs/rewards/phase9a_reference_config.json`; `--config`
accepts a single alternative scenario file. The CLI prints one calculation; it
does not generate customer records or write model/data artifacts. A Python caller
can construct `RewardScenario` and call `evaluate`; `result_payload` provides the
JSON-friendly representation. No batch runner, search, ranking, or optimizer is
provided.

Files created:

- `src/growthlab/rewards/__init__.py`
- `src/growthlab/rewards/economics.py`
- `tests/test_reward_economics.py`
- `docs/rewards/phase9a_reference_config.json`
- `docs/rewards/phase9a_reference_summary.json`
- This report, `docs/rewards/phase9a_economics.md`.

Git status: these six new files are untracked, with no existing tracked-file
changes or staged files. HEAD remains `bc2cffb`; nothing is committed or pushed.
Prior studies and results remain unchanged.

## Limitations and stopping point

Conversion and redemption probabilities, contribution, and costs are supplied
assumptions, not estimates. The engine has no uncertainty intervals and makes no
claim that observed causal effects equal its inputs. Phase 8C's simulated +3 pp
is not empirical evidence for a €5 voucher, and neither REES46 nor RetailHero
customer populations are linked or used here.

Real applications could require credible causal conversion estimates, appropriate
contribution measures, reliable redemption/cost information, heterogeneous
customers, multiple purchases, returns, fixed costs, and cash-settlement rules.
Those are limitations of this version, not components silently inferred or built.
No actual lifetime value, margin, redemption rate, campaign cost, or financial
return is invented. This model does not discover how rewards affect conversion
and does not choose a reward amount.

Stop after this single-scenario economics engine for review. No multi-scenario
optimization, product ranking, Streamlit dashboard, Docker, or deployment has begun.
