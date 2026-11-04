# Phase 1.5 — cleaning policies, temporal splits, and feature design

Status: **ready for review; recommendations await approval**. Date: 2026-11-04.
No models, full feature pipeline, cleaned event export, or cloud resources were
created. No commit or push was made. Phase 0/1 remain unchanged at `4c04d1c`.

## 1. Executive summary

The project remains feasible as a study of **observed future purchasing** by
first-observed user IDs. The first seven elapsed days provide inputs; the next
30 days provide a binary purchase label. These are not necessarily newly
acquired customers, and purchases are product events, not orders or net revenue.

Recommended design, subject to your review:

1. Keep raw files immutable. For the primary future feature calculation, retain
   one instance of each exact nine-field event; compare raw multiplicities as a
   sensitivity. This would reduce events from 20,692,840 to 19,583,742 without
   changing first appearances, customer eligibility, or any-purchase labels.
2. Keep events with missing brand/category text and unusual prices. Treat price
   validity separately from behavioral event validity; count sessions within users.
3. Keep gap-overlap customers in the available cohort with **audit metadata**.
   Do not delete all 370,970 overlapping histories or invent missing purchases.
4. Use the earlier, gap-free chronological schedule as the **primary experiment**:
   87,760 training, 53,089 validation, and 51,444 test customers. Its test has
   547 positives. Use the broader, overlap-retaining schedule as the **temporal
   robustness experiment**; its test has 2,140 positives but uncertain logging.
5. Start with **12 interpretable behavioral predictors** defined below. No
   preprocessing is fitted and no feature table is produced in this phase.

The primary schedule sacrifices breadth to avoid the known suspicious period.
Its five-day cohorts and left-truncated training population are real limitations.
The broader schedule has better sample size but cannot certify uninterrupted
logging. Neither provides a guarantee of deployment performance. These choices
are based on data quality, chronology, and sample sizes, not model performance.

## 2. Evidence and reproducibility

Reviewed the [Phase 0 plan](phase0_feasibility.md), [Phase 1 report](phase1_report.md),
existing acquisition/audit code and tests, and all Phase 1 JSON summaries. Git
started clean on `main`, synchronized with `origin/main` at `4c04d1c`.

All five official CSVs remain local. SHA-256 hashes and sizes match the Phase 1
acquisition manifest **both before and after** this investigation. Existing
Parquet hashes are also unchanged. There were no downloads or raw-file writes.
Phase 1 numbers remain raw-data statistics, not final cleaned-data results.

Reproduce from the repository root using the existing local environment:

```sh
PYTHONPATH=src .venv/bin/python -m growthlab.design_review
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

[`design_review.py`](../src/growthlab/design_review.py) groups duplicates one
month at a time, measures concentration, compares equal-duration time windows,
and recounts customer overlaps/splits. It reads existing Parquet with a **1 GB
DuckDB memory limit, one thread, and an 8 GB spill cap**. Only aggregate
[evidence.json](phase1_5/evidence.json) is exported; customer keys and diagnostic
tables stay under ignored `data/design/`. Raw hashes tie this investigation to
the acquired data; the existing Parquet was not regenerated. The Parquet
fingerprints identify the exact derived inputs used, not a fresh row-by-row
equivalence proof against the CSVs.

## 3. Exact duplicates

**Confirmed definition:** equality across all nine original fields after CSV
decoding: `event_time`, `event_type`, `product_id`, `category_id`, `category_code`,
`brand`, `price`, `user_id`, and `user_session`. NULLs group together. This is
not just equality on timestamp/user/product, numeric-price normalization, or
byte-identical CSV quoting. Parsed helper fields do not expand the key.

All events have valid timestamps in the correct monthly file, so an exact event
cannot appear in two different monthly partitions. Summing monthly duplicate
counts is valid for these files. The query retains raw field values and groups
on all nine fields; `n - 1` is the excess multiplicity.

| Month | Excess views | Excess carts | Excess removals | Excess purchases | Total excess |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2019-Oct | 114 | 28,167 | 184,531 | 343 | 213,155 |
| 2019-Nov | 139 | 22,175 | 224,231 | 148 | 246,693 |
| 2019-Dec | 110 | 15,483 | 168,157 | 110 | 183,860 |
| 2020-Jan | 107 | 19,661 | 205,140 | 192 | 225,100 |
| 2020-Feb | 561 | 29,856 | 209,761 | 112 | 240,290 |
| Total | 1,031 | 115,342 | 991,820 | 905 | 1,109,098 |

| Event type | Retaining all rows | Keeping one exact copy |
| --- | ---: | ---: |
| View | 9,657,821 | 9,656,790 |
| Cart | 5,768,333 | 5,652,991 |
| Removal | 3,979,679 | 2,987,859 |
| Purchase | 1,287,007 | 1,286,102 |
| All events | 20,692,840 | 19,583,742 |

These are **calculated policy effects**, not an exported cleaned dataset.
905 fewer purchase rows do not mean 905 fewer orders or purchasing customers.
An identical event has the same user, time, and type, so removing extra copies
cannot remove that user's last remaining purchase at that timestamp or move `t0`.
Consequently, the 1,256,629 baseline eligible users and 23,760 binary positives
remain unchanged under exact deduplication alone. A synthetic test verifies
this invariant; it does not justify approximate deduplication.

**Concentration:** 114,683 users (7.00% of all users) have duplicates. Among
affected users, excess-row percentiles p50/p90/p99 are 2/21/112; the maximum
is 3,422. The top 10/100/1,000 users account for 1.63%/7.26%/23.16% of excess
rows. Users with 100–999 total events account for 653,340 excess rows; those
with at least 1,000 account for 212,066. Thus duplicates are concentrated among
active shoppers but are not explained by one anomalous ID. Activity buckets
are descriptive and partly mechanically related to duplicated event counts.

**Interpretation:** repeated delivery/tracking is plausible, particularly for
removals. Legitimate identical actions within a second are also possible. There
is no unique event ID or finer timestamp to distinguish them. Neither bots nor
an instrumentation defect are proven.

**Recommendation:** use exact-distinct events for primary first-week counts;
preserve raw multiplicities for a predeclared sensitivity on the same customer
cohorts. Keep separate events with different timestamps, sessions, products or
other original fields. Do not merge near-duplicates, infer quantities, or remove
high-activity customers automatically. Freeze this policy before model selection.

## 4. Missing values, prices, and sessions

| Field / issue | Confirmed finding | Proposed policy and reason |
| --- | --- | --- |
| `category_code` | 20,339,246 missing, 98.291% | Preserve locally; exclude as an initial predictor. Deleting these rows would discard almost the whole study. |
| `brand` | 8,757,117 missing, 42.320% | Preserve missing; defer brand predictors. Do not invent an unknown brand or use future catalog values to fill history. |
| `category_id` | No missing/invalid values; values exceed floating-point exactness | Keep int64/string keys. Available for later diversity features, though not required in the first 12. |
| `user_id` / `event_time` | No missing or invalid values | Required for grouping and windows. Fail/quarantine future invalid inputs explicitly; no imputation. |
| `price` | No missing or invalid numeric values | Retain original and parsed price; no mean filling. A future customer with no valid view price gets NULL plus a missingness flag. |
| `user_session` | 4,598 missing event fields | Keep events; ignore NULL in distinct-session counts; retain a missing-session QA count. Do not make one shared synthetic session or one synthetic session per event. |
| Negative price | 131 events: 126 purchases, 3 removals, 2 views | Keep event counts and event-type targets; exclude negative values from monetary summaries. Retain a QA count. Refund/error/adjustment explanations are unverified. |
| Zero price | 104,157 events; only one purchase | Keep as observed zero in primary price summaries and flag for QA. Compare positive-only prices as a sensitivity; zero is not automatically missing or erroneous. |
| Shared session ID | 272 session IDs, 1,985 events, 591 users; up to 8 users per session | Group by user first and count distinct nonmissing session IDs within that user. Never link customers through a shared session ID. |

February has 71,254 zero-price rows. It could reflect catalog/promotion/tracking
changes; the cause is unknown. Do not learn a price correction from future
February behavior. In eligible outcome windows, requiring a strictly positive
purchase price still yields **23,760 positives**, the same as using purchase
event type alone. Thus nonpositive-price purchase events do not uniquely create
a positive label in this cohort. This check does not establish their meaning.

Use event-time product attributes rather than a full-history product lookup.
The Phase 1 multiple-category/brand mappings and changing prices could reflect
catalog updates. No user, product, or session identifiers are numerical predictors.
Knowing from future data that a session was shared must not become a model input.

## 5. January 22 gap: what is known

All times are UTC. The last observed event is **2020-01-22 02:52:08**; the next
is **03:26:14**. The inter-event separation is **2,046 seconds (34:06)**.
At one-second source resolution, unobserved timestamp slots form the half-open
interval **`[02:52:09, 03:26:14)`**, lasting **2,045 seconds (34:05)**. This is
the interval used in overlap SQL. The one-second difference is a convention
clarification, not a different gap from Phase 1.

Equal-length windows on January 22:

| UTC interval, end exclusive | Events | Users | Purchase events |
| --- | ---: | ---: | ---: |
| 02:18:04–02:52:09 | 705 | 165 | 67 |
| 02:52:09–03:26:14 | 0 | 0 | 0 |
| 03:26:14–04:00:19 | 992 | 258 | 32 |

Same clock interval on comparison dates:

| Date | Events | Purchase events | Comparison |
| --- | ---: | ---: | --- |
| Jan 8 | 772 | 35 | Same weekday |
| Jan 15 | 949 | 25 | Same weekday |
| Jan 20 | 1,111 | 75 | Nearby date |
| Jan 21 | 830 | 58 | Previous date |
| Jan 23 | 1,158 | 57 | Next date |
| Jan 24 | 1,317 | 112 | Nearby date |
| Jan 29 | 1,099 | 30 | Same weekday |
| Feb 5 | 1,182 | 25 | Same weekday |

Five-minute counts show six consecutive empty bins covering **[02:55, 03:25)**,
surrounded by activity. Traffic comparisons use raw event counts; duplicates
can change their magnitude but cannot explain the complete absence. Equal-duration controls and the abrupt stop/resumption
are **consistent with a site, tracking, or export interruption** and make an
ordinary low-traffic explanation less convincing. We lack server logs, tracking
health, or publisher confirmation: **a logging outage is not confirmed**. A site
outage could produce truly absent activity rather than missing labels. The
comparison counts are neither a reconstruction nor an upper bound on lost events.

### Customer overlap and its meaning

For any two half-open intervals, overlap means `start_a < end_b AND end_a > start_b`.
An endpoint merely touching the gap does not overlap. A prediction timestamp
inside the gap can cause **both** the feature and outcome intervals to overlap.

| Overlap class among 1,256,629 eligible users | Customers | Observed positives |
| --- | ---: | ---: |
| Feature only | 72,617 | 967 |
| Outcome only | 298,251 | 3,295 |
| Both | 102 | 1 |
| Neither | 885,659 | 19,497 |

Feature overlap totals **72,719**; outcome overlap totals **298,353**. Their union
is **370,970**, not their simple sum. Across all 1,639,358 observed users,
1,268,388 overlap neither window, including 382,729 ineligible users. All
gap-overlapping users happen to satisfy the baseline horizon rule.

Feature overlap could undercount views/carts/sessions, distort price exposure,
or inflate recency. Outcome overlap could hide purchases and turn a true positive
into an observed negative. Both are possibilities if logging was lost, not
established effects for every overlapping person. Users whose entire activity
was unlogged would be absent and cannot be counted here. The missing interval
is at most 0.338% of seven days or 0.079% of 30 days, but small time fractions
do not bound event or label bias.

| Strategy | Benefit | Cost / limitation |
| --- | --- | --- |
| A: exclude every overlapping history | Avoids the known suspicious interval | Removes 370,970 eligible users and 4,263 observed positives; changes calendar/cohort composition. Original test collapses to 9,770 users/135 positives, nearly one scoring day. |
| B: retain with QA flags | Preserves population and sample size | Flags do not repair missing inputs/outcomes or prove negatives correct. |
| C: gap-free primary experiment plus overlap-retaining temporal robustness | Avoids this interval in the primary test while keeping all records available for comparison | Changes dates and training cohorts, so differences cannot isolate a causal effect of the gap. |

**Recommendation: C.** Retain the available customers and add separate
`feature_gap`/`outcome_gap` metadata; use a gap-free primary calendar schedule.
Do not globally delete A's 370,970 customers. Report A as a diagnostic subset
within the broader experiment, not as evidence that those users were invalid.
**Neither gap flag is an initial predictor.** Outcome overlap describes future
logging and would leak future information. A finalized feature-gap interval can
also contain future information when scoring happens during the pause. Audit
metadata must remain outside the model matrix, preprocessing, and thresholds.

## 6. Target and eligibility contract

- `t0`: earliest observed valid event for a positive user ID across all months.
- `p = t0 + INTERVAL 7 DAY`; feature events satisfy `event_ts >= t0 AND event_ts < p`.
- Outcome events satisfy `event_ts >= p AND event_ts < t0 + INTERVAL 37 DAY`.
- `y = 1` iff an outcome event has `event_type = 'purchase'`; otherwise zero
  only for an eligible, fully available historical horizon under the stated
  logging assumptions. Price and first-week purchasing do not redefine the target.
- Baseline eligibility requires `t0 + 37 days <= 2020-03-01 00:00:00 UTC` and no
  known whole-day coverage gap. Include both first-week buyers and nonbuyers;
  do not require return visits, activity on day seven, or any minimum event count.
- Primary split dates avoid the suspicious January interval. Broader experiment
  retains overlap flags and calls eligibility **provisional** with respect to
  instrumentation. It has complete file-date horizons, not certified logging.

No event at `p` enters features, and no event at `t0 + 37 days` enters this
target. Late censored positives remain excluded like censored negatives. There
are 1,256,629 baseline eligible users and 23,760 positives; calendar selection
then defines experiments. Absence of other logging loss is an explicit
assumption even for the primary schedule. This log alone cannot certify every
retail purchase or fully identify newly acquired people.

## 7. Candidate chronological splits and recommendation

All boundaries below are **midnight UTC**, all intervals **`[start, end)`**.
Split by `p`, with one global `t0` per user. Tables specify exact allowed calendar
envelopes, not claims that every timestamp has a customer or that every customer
has activity throughout. Actual min/max timestamps are in the JSON evidence.

### Configuration A — recommended primary, earlier gap-free schedule

| Split | Prediction timestamps `p` | Customers | Positives | Positive % |
| --- | --- | ---: | ---: | ---: |
| Train | [2019-10-08, 2019-10-13) | 87,760 | 3,814 | 4.346% |
| Validation | [2019-11-12, 2019-11-17) | 53,089 | 1,150 | 2.166% |
| Test | [2019-12-17, 2019-12-22) | 51,444 | 547 | 1.063% |

| Split | First-seen timestamps | Feature-window calendar envelope | Outcome-window calendar envelope |
| --- | --- | --- | --- |
| Train | [2019-10-01, 2019-10-06) | [2019-10-01, 2019-10-13) | [2019-10-08, 2019-11-12) |
| Validation | [2019-11-05, 2019-11-10) | [2019-11-05, 2019-11-17) | [2019-11-12, 2019-12-17) |
| Test | [2019-12-10, 2019-12-15) | [2019-12-10, 2019-12-22) | [2019-12-17, 2020-01-21) |

Simulated initial training cutoff: **2019-11-12 00:00 UTC**. All training
outcomes finish by Nov 11 23:59:59, before validation starts. Final choices are
frozen at **2019-12-17 00:00 UTC**; validation outcomes finish by Dec 16 23:59:54.
All test outcomes finish by **Jan 20 23:57:38**, before the suspicious gap.
Keep the training fit frozen through validation. If a final refit on mature
training+validation rows is later chosen, predeclare it and fit preprocessing
only on those mature rows, never test inputs or outcomes.

This is feasible and prioritizes avoiding the identified coverage anomaly.
Its main weaknesses are only five scoring days per split and a training cohort
entirely first observed near the dataset boundary. That cohort can include
established customers with unseen earlier history. The strong rate shift is
not cured by strict chronology. Do not market it as an unbiased new-customer
acquisition or deployment experiment.

### Configuration B — recommended temporal robustness, broader schedule

| Split | Prediction timestamps `p` | Customers | Positives | Positive % |
| --- | --- | ---: | ---: | ---: |
| Train | [2019-10-08, 2019-11-01) | 328,535 | 10,092 | 3.072% |
| Validation | [2019-12-01, 2019-12-16) | 157,349 | 1,985 | 1.262% |
| Test | [2020-01-15, 2020-01-30) | 167,822 | 2,140 | 1.275% |

| Split | First-seen timestamps | Feature-window calendar envelope | Outcome-window calendar envelope |
| --- | --- | --- | --- |
| Train | [2019-10-01, 2019-10-25) | [2019-10-01, 2019-11-01) | [2019-10-08, 2019-12-01) |
| Validation | [2019-11-24, 2019-12-09) | [2019-11-24, 2019-12-16) | [2019-12-01, 2020-01-15) |
| Test | [2020-01-08, 2020-01-23) | [2020-01-08, 2020-01-30) | [2020-01-15, 2020-02-29) |

Simulated training cutoff: **2019-12-01 00:00 UTC**; last training outcome
ends Nov 30 23:59:57. Final choices/refit cutoff: **2020-01-15 00:00 UTC**;
last validation outcome ends Jan 14 23:59:06. Last test outcome ends
**Feb 28 23:59:54**, within the acquired coverage.

Training and validation have no gap overlap. The test has 72,719 feature-overlap
users and 85,435 outcome-overlap users (158,052 unique affected users). Retain
them for B with QA flags. Report performance by overlap class and on its
9,770-user/135-positive unaffected subset, while acknowledging weak precision
and a changed scoring-day mix. Do not use the subset to choose thresholds.

A and B are independent experimental schedules: some users appear in both
experiments, but within either schedule the three splits are disjoint. B fits
its own preprocessing only on its allowed training rows and respects its later
cutoffs. Lock A as primary before models; do not choose the winning schedule
after seeing test scores. B measures temporal/cohort robustness, not just the gap.

### Leakage, censoring, and shift are different problems

| Problem | Example | Safeguard |
| --- | --- | --- |
| Feature leakage | Lifetime purchases, end-of-session data after `p`, full-history catalog/brand fill, future-gap flags | Filter every event before `p`; use event-time attributes; exclude future QA metadata. |
| Label-availability leakage | Training on a customer's 30-day outcome before those 30 days pass | Enforce `max(training outcome_end) <= training cutoff`; same for validation before final decisions/refit. |
| Distribution shift | Training purchase rate 4.346%, test 1.063% in A | Report changing population/rates; assess calibration over time. Chronology does not eliminate shift. |
| Incomplete outcome window | Late January/February first appearances without 37 days of follow-up | Exclude independently of observed label. Treat logging uncertainty separately from file-end censoring. |

No random event splits; no recomputing first appearance within each month/split.
Global minimum appearance is valid as-of each scoring time because a later
timestamp cannot move an earlier minimum, assuming timestamped records were
available without late-arrival corrections. Ingestion latency is not supplied:
the calendar simulation assumes event-time availability. Real deployment needs
an ingestion-lag buffer. No scaler, imputer, learned category map, data-driven
feature selection, or decision threshold may be fitted with validation/test data
except validation's explicitly allowed tuning role. This fixed initial list
uses audit semantics and missingness, not test feature–label associations.

### Are test positives sufficient?

A's 547 positives permit exploratory PR-AUC, ROC-AUC and calibration assessment;
they do not justify fine model rankings or precise tail probabilities. B's
2,140 positives support more precise evaluation under its coverage assumption.
The strict B subset's 135 positives are weak evidence for small improvements.

For scale only, **if recall were 50%** and positive users were independent,
an approximate 95% binomial margin would be **±4.19 percentage points** for
547 positives, **±2.12** for 2,140, and **±8.43** for 135. These are hypothetical
uncertainty illustrations, not model results or PR-AUC/ROC-AUC intervals.
Actual precision depends on how many customers are selected and the threshold;
metric variance also depends on ranking quality and dependence between users.

Later report PR-AUC with its exact definition (e.g. average precision), ROC-AUC,
precision/recall at a validation-selected budget, and Brier score. Start reliability
plots with about five quantile bins and report each bin's count/positives; avoid
claims about sparsely populated high-score tails. Use sequential customer-level
bootstrap intervals, supplemented by scoring-day sensitivity. Five scoring days
in A provide few temporal clusters, so ordinary independent-user intervals
understate some temporal uncertainty. Calibration estimation/tuning belongs on
validation only; test plots are evaluation, not a refitting opportunity.

## 8. Initial feature contract: 12 predictors

The expressions below are **design SQL fragments**, not an implemented pipeline.
Assume `w` contains the reviewed exact-distinct events with
`event_ts >= c.t0 AND event_ts < c.p`, grouped by customer plus `t0,p`.
`n_views`, `n_carts`, and `n_purchases` denote aggregate aliases evaluated in a
subsequent projection for ratios. All counts include zero/negative-price events.

| Feature | Meaning and rationale | SQL expression | Missingness / leakage considerations |
| --- | --- | --- | --- |
| `n_views_7d` | Observed browsing intensity may indicate engagement. | `count(*) FILTER (WHERE event_type='view')` | Zero is real absence of recorded views; use windowed, deduplicated rows. |
| `n_carts_7d` | Cart additions may indicate intent. | `count(*) FILTER (WHERE event_type='cart')` | Not current cart size or item quantity. |
| `n_removals_7d` | Removals may show reconsideration/friction. | `count(*) FILTER (WHERE event_type='remove_from_cart')` | Most duplicate inflation is here; direction of association is unknown. |
| `n_purchases_7d` | Past purchasing may predict repeat purchasing. | `count(*) FILTER (WHERE event_type='purchase')` | Product purchase events, not orders. First-week purchases are legitimate inputs. |
| `n_viewed_products_7d` | Breadth of browsing may distinguish focused versus exploratory shopping. | `count(DISTINCT product_key) FILTER (WHERE event_type='view')` | Product keys are grouped, never fed as ordered numeric predictors. |
| `active_24h_bins_7d` | Persistence across observed days may indicate engagement. | `count(DISTINCT floor(date_diff('second',c.t0,event_ts)/86400.0))` | Exactly seven elapsed-day bins, values 1–7; avoids counting up to eight UTC calendar dates. |
| `n_sessions_7d` | Return sessions may indicate sustained interest. | `count(DISTINCT user_session)` | Within each user; ignore NULL. Zero means no session ID available, not no activity. Keep a separate missing-session QA count. |
| `hours_since_last_event` | Recent activity may indicate readiness to return. | `date_diff('second',max(event_ts),c.p)/3600.0` | Uses the fixed scoring time, never the audit date or future final activity. At least one feature event exists. |
| `cart_view_ratio_7d` | Cart actions relative to browsing may indicate intent. | `CASE WHEN n_views>0 THEN n_carts::DOUBLE/n_views ELSE 0.0 END` | Ratios can exceed 1; zero-denominator convention is explicit, and raw view count disambiguates it. Not a probability. |
| `purchase_view_ratio_7d` | Purchasing relative to browsing may distinguish repeat buyers. | `CASE WHEN n_views>0 THEN n_purchases::DOUBLE/n_views ELSE 0.0 END` | Not order conversion; never use outcome-window purchases in numerator. |
| `median_view_price_7d` | Typical viewed price may capture product mix. Median reduces sensitivity to the long price tail. | `median(price_value) FILTER (WHERE event_type='view' AND isfinite(price_value) AND price_value>=0)` | Include zero, exclude negative/nonfinite. No valid view price gives NULL; no imputation is applied now. Repeated distinct views weight exposure, not a unique-product basket. |
| `view_price_unavailable_7d` | Distinguishes absent price exposure from an observed zero median. | `(count(*) FILTER (WHERE event_type='view' AND isfinite(price_value) AND price_value>=0)=0)::INTEGER` | Computed solely from feature events; companion to nullable price. |

Reasons above are hypotheses about predictive value, not measured associations.
View-event prices have median 5.08, p95 52.22 and p99 137.78 in the raw audit;
this motivates a robust price summary, not a learned price cap. No currency
claim is made. Numerical means are not filled. Phase 2 should emit the nullable
price and its flag; model-specific missing handling is a later approved decision.

Keep `total_events_7d` as **QA**, not an additional predictor: it is exactly the
sum of the four event counts, so including all five gives deterministic linear
redundancy. Ratios also derive from counts; they encode interpretable nonlinear
relationships but require future redundancy/regularization review. A future
linear baseline may use a predeclared counts-only subset; no models are fitted here.
Negative-price, zero-price, missing-session, raw-minus-dedup counts, and gap
flags are separate QA columns rather than extra predictors in the initial 12.

## 9. Predeclared sensitivity and limitations

**One primary temporal configuration:** A, earlier gap-free. **One temporal
robustness configuration:** B, broader dates retaining QA flags. Within B,
report overlap strata and its unaffected subset without choosing the best result.
This is not a controlled comparison that can identify the effect of a logging gap.

Orthogonal cleaning diagnostics for later phases: raw versus exact-distinct
counts on the same users/labels/split; zero-inclusive versus strictly positive
view-price summaries. Do not combine arbitrary alternatives and select by test
performance. The confirmed positive-price target check changed no eligible label.

Known limits: one retailer, five months, unknown currency and price semantics,
no unique event/order IDs or quantities, missing catalog attributes, one-second
timestamps, uncertain instrumentation/ingestion latency, and pseudonymous IDs
that need not equal people. The January pause may hide activity or reflect no
shopping at all. First observed does not mean new; the primary early training
cohort has particularly strong left truncation. Chronology exposes substantial
rate shift rather than fixing it. No causal marketing/uplift conclusion follows.

## 10. Decisions requiring your approval before Phase 2

| Decision | Recommended choice | What approval would authorize later |
| --- | --- | --- |
| Duplicate policy | Exact-distinct primary; raw-count sensitivity | Build a derived deduplicated view/table, never overwrite raw CSVs. |
| Gap policy | Keep QA flags; A primary and B temporal robustness | Freeze cohorts and quality metadata; do not delete all overlap users or use future-gap flags as predictors. |
| Price/session policy | Keep behavioral events; nonnegative median-view price; sessions within user | Apply these rules in feature aggregation with explicit NULL/zero handling. |
| Feature/target contract | The 12 predictors and half-open 7+30-day windows | Implement and test the customer-level feature/label table, without training yet. |
| Temporal scope | Accept shorter cohorts, first-observed definition and zero-ingestion-lag simulation | Interpret subsequent results within these limitations; require more data for broader deployment claims. |

These are requested **review decisions**, not decisions already applied to a
production dataset. No commit or push is authorized in this phase.

## 11. Verification and Phase 2 implementation cost

19 automated tests pass: 13 existing plus six focused checks for exact duplicates
with NULLs and second-level differences, half-open overlap boundaries, a gap
straddling prediction time, price validity/future-event exclusion, ratio
zero denominators, and split-calendar maturity/disjointness. Full-data diagnostic reconciliation reproduces Phase 1
duplicate totals and both schedules' customer/positive counts. Raw hashes before
and after agree; all existing Parquet bytes agree with their starting hashes.

The first diagnostic attempt caught an SQL alias using the reserved word
`window`; it was corrected to `window_name` and the full investigation completed
successfully. The local environment no longer resolves the earlier editable
package install directly, so reproduction explicitly uses `PYTHONPATH=src`;
the existing DuckDB installation works and no dependency installation was needed.
Neither issue indicates a dataset inconsistency. The gap's 2,046-second
inter-event interval versus 2,045 unobserved timestamp slots is clarified above.

Changed/created files: this design document, `docs/phase1_5/evidence.json`,
`src/growthlab/design_review.py`, and `tests/test_design_review.py`. No Phase 1
source/statistics were overwritten. Local diagnostic database and logs are ignored.

**Phase 2 planning estimate (not measured runtime):** roughly 1–2 focused working
days for the feature/label SQL, split/QA metadata, provenance, boundary tests,
and reconciliation. Budget a few minutes per full aggregation attempt on this
Mac and allow 4–8 GB additional disk including intermediates/spill. The measured
diagnostic run took 39.35 seconds, but it did not compute the full feature set;
that is not a Phase 2 benchmark. Keep the 1 GB/one-worker strategy initially and
measure the actual customer-table size before adding dependencies or complexity.

Phase 1.5 is ready for your review. Git changes are uncommitted and unstaged;
`main` remains at `4c04d1c`. Stop here before Phase 2 implementation.
