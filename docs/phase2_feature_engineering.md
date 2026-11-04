# Phase 2 — customer-level feature engineering

Status: **Phase 2 completed and verified; ready for user review**.
Specification: [phase2_specification.json](phase2_specification.json).
The user approved the Phase 1.5 policies and the conservative 2019 split dates
before this implementation. No models, hyperparameter tuning, fitted
preprocessing, API, cloud resources, or causal module are included.

## 1. Frozen specification and output grain

The [Phase 1.5 design](phase1_5_design_decisions.md), its diagnostic code/tests,
the [Phase 1 report](phase1_report.md), and their JSON evidence agree with the
approved specification. No contradiction was found. Train is in **2019**, not
2020. Exactly twelve predictors are authorized and explicitly allowlisted.

One customer-table row represents one eligible **observed user ID**, not one
session, person, order or purchase. Define global `first_seen` from all months:

- `prediction_time = first_seen + 7 elapsed UTC days`.
- Feature interval: **`[first_seen, prediction_time)`**.
- Outcome interval: **`[prediction_time, first_seen + 37 days)`**.
- Target `purchased_next_30d`: 1 if at least one `purchase` event occurs in that
  outcome interval; otherwise 0 for an eligible horizon.

Require `outcome_end <= 2020-03-01 00:00:00 UTC` and no declared whole-day
logging gap intersecting the history. Inclusion does not depend on purchasing,
number of events, continued activity, or a visit on day seven. Early-positive
but censored customers remain excluded. First-week purchases are permitted
predictors because the target includes any subsequent purchase, including repeats.

The master table retains all eligible customers, with NULL split assignments
for dates outside each experimental schedule. Gap overlaps remain QA metadata.
The primary calendar avoids the suspicious January interval; broader schedule
assignments are preserved for later robustness work, not used to train anything.

## 2. What each SQL stage does and why

Implementation: [`features.py`](../src/growthlab/features.py). The functions are
separate stages so their intermediate counts and constraints can be reviewed.

1. **Verify inputs and freeze the contract.** Match raw CSV sizes/SHA-256 to the
   acquisition manifest and the existing Parquet SHA-256 to Phase 1.5 evidence.
   Check the explicit feature allowlist and split definitions against the frozen
   JSON. A changed source or specification causes a failure before exports.
2. **Create the cleaned event layer month by month.** `SELECT DISTINCT` on all
   nine original decoded CSV fields removes extra exact copies. Only afterward
   are timestamp, numeric keys and numeric price parsed again. This avoids
   merging differently formatted raw values through numeric coercion. NULL
   categorical/session fields participate in duplicate equality. Brand and
   category text remain in the event layer solely to preserve the full key.
3. **Verify cleaned counts and coverage.** Reconcile monthly retained-event
   counts against Phase 1 raw counts minus duplicate excess, reject malformed
   required fields/types and wrong-month events, and verify all 152 UTC dates.
   Correct month assignment makes monthly exact deduplication equivalent to
   global exact deduplication for these inputs. Raw CSVs and prior Parquet files
   are read-only; new cleaned Parquet lives under ignored local storage.
4. **Find first appearance globally, then decide eligibility.** Group cleaned
   events by user and take `min(event_ts)`. Compute the seven-/37-day boundaries
   once, across month boundaries. Apply the horizon rule before inspecting the
   target so partially observed positives are not preferentially retained.
5. **Aggregate only first-week events.** Join eligible customers to events
   with explicit lower-inclusive and upper-exclusive timestamp predicates.
   Compute counts, browsing breadth, elapsed-day persistence, sessions, recency,
   and valid viewed-price median. Event prices do not determine whether an
   activity counts. Ratios are computed afterward from the windowed counts.
6. **Aggregate future purchases separately.** Join only purchase events in the
   30-day outcome interval, then reduce to a boolean target. A left join assigns
   zero to eligible customers with no purchase. Aggregating features and targets
   independently prevents a many-to-many join from multiplying either count.
7. **Assign chronology and QA metadata.** Use prediction time for the fixed
   primary and broader `CASE` assignments. Compute feature/outcome gap overlap
   separately. Keep counts of zero/negative prices, missing sessions, and feature
   timestamp bounds as QA, not additional model predictors.
8. **Validate, then export.** Check all rows, compare population/split counts to
   frozen counts, enforce label maturity, and export the master plus three primary
   split Parquet files. Each split export contains only `user_id`, the twelve
   predictors, and target; all other metadata stays in the master/local database.
9. **Independently recheck raw histories.** A separate Python implementation
   streams all five original CSVs and retains only selected customers in memory.
   It deduplicates original tuples, recomputes timestamps/features/labels without
   calling the feature SQL, and compares the results. Rehash inputs afterward.

Exact deduplication changes row multiplicities, not first appearances or the
existence of a purchase at a given user/timestamp. Any-purchase labels therefore
reconcile with the original audit even though purchase-event counts decrease.
Identical rows could still represent legitimate repeated actions within one
second; immutable raw files remain available for the approved later sensitivity.

## 3. The twelve predictors

| Final feature | Meaning and exact handling |
| --- | --- |
| `n_views_7d` | Number of distinct-row view events in the first seven days. |
| `n_carts_7d` | Cart-addition events; not quantity or current cart contents. |
| `n_removals_7d` | Cart-removal events after exact deduplication. |
| `n_purchases_7d` | Product-level purchase events before scoring; not order count. |
| `n_viewed_products_7d` | Distinct product IDs among first-week views. |
| `active_24h_bins_7d` | Distinct `floor(seconds_since_first_seen / 86400)` bins; 1–7, anchored to first appearance rather than calendar midnight. |
| `n_sessions_7d` | Distinct nonmissing session IDs within the customer/window. Shared session strings do not merge users. |
| `hours_since_last_event` | Hours from the last feature event to the fixed prediction timestamp; strictly positive and at most 168. |
| `cart_view_ratio_7d` | Cart count divided by view count; defined as 0 if no views. Not a probability and may exceed 1. |
| `purchase_view_ratio_7d` | First-week purchase count divided by first-week view count; 0 if no views. |
| `median_view_price_7d` | Median finite, nonnegative price among first-week view events. Includes zero; excludes negative prices. NULL if none exist. |
| `view_price_unavailable_7d` | 1 exactly when the viewed-price median has no valid input, otherwise 0. |

Negative- and zero-price events remain in behavioral counts. The master has
`qa_negative_price_events_7d` and `qa_zero_price_events_7d`; `> 0` gives the
corresponding presence flags. `qa_missing_session_events_7d` records unavailable
session fields. None is an added predictor. NULL prices are not mean-filled;
model-specific missing handling is deferred. Brand and `category_code` are
deferred as approved. No new predictor was introduced.

The fixed `FEATURE_COLUMNS` tuple and JSON allowlist are the model-input
contract. Do **not** select all numeric columns: `user_id` and the label are
numeric too. Never use split, timestamp, future-gap, target-purchase timestamps,
or QA columns as predictors. The split exports omit QA metadata to reinforce
this boundary. The master retains it for traceability.

## 4. Frozen chronology and label availability

All intervals are UTC and end-exclusive; split membership uses prediction time.

| Primary split | Prediction interval | Expected customers | Expected positives |
| --- | --- | ---: | ---: |
| Train | [2019-10-08, 2019-10-13) | 87,760 | 3,814 |
| Validation | [2019-11-12, 2019-11-17) | 53,089 | 1,150 |
| Test | [2019-12-17, 2019-12-22) | 51,444 | 547 |

Training outcomes finish before the simulated **2019-11-12** training cutoff.
Validation outcomes finish before the **2019-12-17** final decision/refit cutoff.
Test outcomes finish before **2020-01-21**, preceding the January 22 anomaly.
No customer can have two primary split values. The broader schedule has its own
separate assignment; membership in both schedules is expected and is not overlap
between train and test within one experiment.

Complete file-date horizons do not establish perfect instrumentation. Unknown
logging loss, pseudonymous identities, first-observed versus new-customer
status, catalog ambiguity and unmeasured ingestion latency remain assumptions.
The approved primary cohort has short scoring periods and strong left truncation
in training. Distribution shift is a limitation rather than a leakage error.

## 5. Observed results and feature distributions

The successful build's aggregate evidence, schemas, checks and file hashes are
in [summary.json](phase2/summary.json). No feature choice was changed after
looking at these results; summaries are unconditional, not feature/target
association analyses.

| Population / layer | Rows | Purchase events or positive labels |
| --- | ---: | ---: |
| Raw event source | 20,692,840 | 1,287,007 purchase events |
| Exact-distinct event layer | 19,583,742 | 1,286,102 purchase events |
| All eligible customer rows | 1,256,629 | 23,760 positive labels (1.891%) |
| All primary split rows combined | 192,293 | 5,511 positive labels |
| Eligible rows outside primary calendar intervals | 1,064,336 | 18,249 positive labels |

An unassigned eligible row is not an error and does not enter the three primary
datasets. The master deliberately retains it, rather than deleting customers
that may support future approved robustness studies.

| Actual primary split | Customers | Positives | Positive rate | Last outcome-window end (UTC) | Gap overlap |
| --- | ---: | ---: | ---: | --- | ---: |
| Train | 87,760 | 3,814 | 4.346% | 2019-11-11 23:59:59 | 0 |
| Validation | 53,089 | 1,150 | 2.166% | 2019-12-16 23:59:54 | 0 |
| Test | 51,444 | 547 | 1.063% | 2020-01-20 23:57:38 | 0 |

All counts and rates match the frozen design. Broader assignments also reconcile:
328,535/10,092 train users/positives, 157,349/1,985 validation, and 167,822/2,140
test. No broader split files were built: their assignments are preserved in the
master for later robustness evaluation as approved.

### Missingness and quality indicators

The only nullable predictor is `median_view_price_7d`. Missing here means no
valid first-week viewed price, rather than an empty raw price field.

| Population | Missing viewed-price median | Percentage | Zero available session IDs |
| --- | ---: | ---: | ---: |
| All eligible | 39,723 | 3.161% | 156 |
| Train | 2,546 | 2.901% | 4 |
| Validation | 1,776 | 3.345% | 8 |
| Test | 1,495 | 2.906% | 10 |

All other eleven predictors have zero missing values. The price-unavailable flag
agrees with the median's NULL status in every row. A zero session count means
the customer's observed events lacked a session key, not that the customer had
no activity. Session counts remain within-customer counts.

Eligible first-week histories contain **9,378 zero-price events in 5,110
customers**, **49 negative-price events in 49 customers**, and **2,505 missing
session fields**. Activity was retained for all these cases. These are
windowed, deduplicated counts and must not be confused with Phase 1's whole-log
104,157 zero-price / 131 negative-price raw-event totals.

The master retains 72,719 feature-gap and 298,353 outcome-gap flags. None of
the primary split rows has either flag. Flags are not model columns.

### Feature distributions: training only in this readable table

The JSON also contains unconditional validation/test and all-eligible summaries
for verification. They were not used to select predictors, impute missingness,
clip outliers, or fit any transformation. Price quantiles exclude NULLs.

| Training predictor | Median | p90 | p99 | Observed range |
| --- | ---: | ---: | ---: | --- |
| `n_views_7d` | 1 | 8 | 53 | 0–582 |
| `n_carts_7d` | 0 | 6 | 41 | 0–691 |
| `n_removals_7d` | 0 | 2 | 30 | 0–985 |
| `n_purchases_7d` | 0 | 0 | 16 | 0–135 |
| `n_viewed_products_7d` | 1 | 6 | 39 | 0–444 |
| `active_24h_bins_7d` | 1 | 2 | 5 | 1–7 |
| `n_sessions_7d` | 1 | 3 | 15 | 0–455 |
| `hours_since_last_event` | 167.995 | 168 | 168 | 0.000278–168 |
| `cart_view_ratio_7d` | 0 | 3 | 7.5 | 0–309.5 |
| `purchase_view_ratio_7d` | 0 | 0 | 2 | 0–82 |
| `median_view_price_7d` | 5.635 | 30.1585 | 137.78 | 0–299.81 |
| `view_price_unavailable_7d` | 0 | 0 | 1 | 0–1 |

The sparse counts and near-168-hour recency median show many customers have
brief early activity and little subsequent observed return in their first week.
Large ratios are valid under the approved definition: several cart/purchase
actions can follow very few recorded views. These are interaction ratios, not
probabilities. No value was automatically capped, transformed or removed.

## 6. Correctness checks and independent history verification

**35 tests passed:** the 19 existing acquisition/audit/design tests and 16 new
Phase 2 tests. Full-data validation also checks all 1,256,629 output rows.

| Requirement | Evidence |
| --- | --- |
| One row per eligible customer | Master count and distinct-user count both 1,256,629; equal to the independently calculated eligibility population. |
| No customer in multiple primary splits | Single prediction-time assignment plus a direct duplicate-key query across all three saved split files: zero duplicates. |
| Features precede prediction | Explicit half-open join, per-row first/last feature timestamp checks, and a mutation test adding future activity without changing predictors. |
| Target uses exactly the next 30 days | Separate bounded purchase aggregate; full-data first/last target timestamps; synthetic purchases immediately before, at, and after each boundary. |
| Censoring independent of label | Known early-positive censored fixture excluded; exact coverage-end equality accepted. No censored master rows. |
| Deduplication matches reviewed key | Synthetic NULL/brand/raw numeric-format/one-second differences and all monthly retained-count reconciliations. |
| Prices and sessions follow policy | Negative/zero/no-view fixtures; shared session key under different customers; all-NULL sessions; price NULL/flag identity over every output row. |
| Values valid | Zero violations for nonnegativity/finiteness, elapsed-day range, recency range, event-count totals and target 0/1. |
| Correct persisted exports | Split files checked in both directions with `EXCEPT ALL` against the master projections; no differing/missing/extra rows or columns. |
| Frozen counts and label maturity | All primary and broader counts reproduce approved evidence; preceding labels end before next cutoffs. |
| Immutable inputs | All raw hashes match acquisition before and after; all original Parquet hashes remain unchanged. |

[`history_verification.py`](../src/growthlab/history_verification.py) independently
streamed **20,692,840 raw events** and recomputed **20 fields for 18 customers**
with **zero mismatches**. Selection was deterministic: two positives and two
negatives per primary split, plus price/session/gap edge cases. Target strata
were used only to exercise correctness, not to select predictors or measure
model performance. The reference uses Python sets, `datetime`, and `statistics`,
not the production feature SQL or the cleaned events.

Details including customer keys remain in local ignored `history_checks.json`;
published evidence contains only aggregate verification results. This sample
does not independently recalculate every customer's feature values. Exhaustive
row constraints, exact count reconciliations, synthetic edge cases and sample
recalculation provide complementary checks.

## 7. Deviations, resource use, and files changed

**No deviation from the approved predictor, cleaning, target, or split contract.**
Zero/negative/session counts and timestamp bounds are approved audit metadata,
not new predictors. The twelve predictors are unchanged. No imputation, scaling,
outlier clipping, feature selection, class weighting, fitting or tuning occurred.

Measured on the existing 8 GiB Mac with Python 3.14.7 / DuckDB 2.0.0:

- Full build and raw-history verification: **121.73 seconds**.
- Peak process resident memory: **951,484,416 bytes, about 0.886 GiB**.
- DuckDB limit **1 GB**, one worker, temporary spill cap **8 GB**.
- At least **30 GiB free disk** required before starting; about **137.7 GiB**
  remained after the build. This leaves substantial OS/scratch headroom.
- Peak transient spill usage was not measured. No spill files remain after close.

| Generated artifact | Actual bytes |
| --- | ---: |
| Five cleaned event Parquet files combined | 902,381,410 |
| Customer master Parquet | 49,133,027 |
| Primary train Parquet | 946,717 |
| Primary validation Parquet | 551,434 |
| Primary test Parquet | 516,908 |
| Working DuckDB database after close | 156,250,112 |

Deduplication changes row order, which changes Parquet compression; fewer rows
need not mean a smaller file than the earlier time-ordered audit Parquet.
Intermediate/row order is not part of the data contract. Logical row values and
keys are reproducible; per-build file hashes identify the exported files and
are not a promise of byte-identical Parquet ordering across reruns. No raw
events were loaded into pandas; Python held only selected verification histories.

| Source/document file | Purpose |
| --- | --- |
| `docs/phase2_specification.json` | Frozen allowlist, policies, cutoffs, expected counts and design fingerprint. |
| `src/growthlab/features.py` | Bounded SQL build, exhaustive constraints, exports, provenance and aggregate summaries. |
| `src/growthlab/history_verification.py` | Independent raw-CSV Python reference/checks. |
| `tests/test_features.py` | Hand-checkable edge cases plus saved-artifact/provenance verification. |
| `docs/phase2/summary.json` | Small aggregate evidence, distributions, schemas and hashes; no customer identities. |
| `docs/phase2_feature_engineering.md` | This methodology and results report. |
| `README.md` and `data/README.md` | Current stage, reproduction command and local data layout. |

Phase 1.5 files remain present and unchanged from the preceding work. They were
already untracked before Phase 2. No raw/generated datasets, local settings,
credentials or scratch databases are staged. Nothing is committed or pushed.

## 8. Reproduction, artifacts, and next step

Run from the repository root; no download or new service is required:

```sh
PYTHONPATH=src .venv/bin/python -m growthlab.features
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

The build recomputes derived files under `data/features/phase2/` and writes small
aggregate evidence under `docs/phase2/`. It never modifies raw CSVs or Phase 1
Parquet. If verification fails, no successful summary is published for that run;
check the local run log before using files left by an interrupted build.

Generated local outputs:

- `cleaned/*.parquet`: exact-distinct event layer with original fields and parsed helpers.
- `build.duckdb` and `spill/`: bounded-memory working tables and temporary storage.
- `customers.parquet`: all eligible rows, twelve predictors, target, timestamps,
  both schedule assignments and approved QA metadata.
- `primary/train.parquet`, `validation.parquet`, `test.parquet`: key + twelve predictors + target.
- `history_checks.json`: selected customer identities and detailed independent
  verification, retained locally only.
- `manifest.json`: successful build's provenance, summaries, schemas and hashes.

After review, the recommended next stage is a simple predictive benchmark with
training-only preprocessing, a prevalence baseline, and an interpretable model.
Choose missing handling, metric definitions and validation thresholds before
evaluating the test set. Model fitting, regularization decisions and any approved
refit are separate work; none is performed in Phase 2.
