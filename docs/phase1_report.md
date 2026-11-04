# Phase 1 — data acquisition, quality audit, and prediction feasibility

Audit date: 2026-11-04. Actual aggregate results are in
[audit_summary.json](phase1/audit_summary.json); source provenance is in
[acquisition.json](phase1/acquisition.json). No models or customer features were
trained/built. Customer-level outcome tables exist only locally to count
eligibility and positives during this audit.

## Observed dataset statistics

The five official version-6 monthly files contain **20,692,840 events** from
**1,639,358 distinct observed user IDs**. Each event relates one user to one
product; purchase events are product-level interactions, not order counts.

| Month | Events | Distinct users within month | Purchase events |
| --- | ---: | ---: | ---: |
| October 2019 | 4,102,283 | 399,664 | 245,624 |
| November 2019 | 4,635,837 | 368,232 | 322,417 |
| December 2019 | 3,533,286 | 370,154 | 213,176 |
| January 2020 | 4,264,752 | 410,073 | 263,797 |
| February 2020 | 4,156,682 | 391,055 | 241,993 |

Monthly distinct-user counts must not be added to obtain unique users.
205,207 IDs appear in more than one month, supporting cross-month linkage
without proving stable real-world identity.

| Event type | Events | Percentage |
| --- | ---: | ---: |
| `view` | 9,657,821 | 46.672% |
| `cart` | 5,768,333 | 27.876% |
| `remove_from_cart` | 3,979,679 | 19.232% |
| `purchase` | 1,287,007 | 6.220% |

Daily event/user/purchase counts and monthly event-type counts are included in
the JSON report. Counts range from **31,096 events on December 31** to
**270,074 on November 22**. A low daily count could reflect shopping patterns
or logging changes; no cause is established by this audit.

## Quality findings and their consequences

| Column | Missing values | Percentage |
| --- | ---: | ---: |
| `category_code` | 20,339,246 | 98.291% |
| `brand` | 8,757,117 | 42.320% |
| `user_session` | 4,598 | 0.022% |
| Other six columns | 0 | 0% |

Missingness means an empty CSV field. Whitespace-only fields are separately
counted in the audit. Required timestamps, numeric identifiers, and prices all
parse successfully; no nonpositive identifiers, unexpected event types, or
events assigned to the wrong monthly file were found. All nonmissing session
strings match the UUID-shaped format. A matching format does not prove validity.

**Duplicates:** 1,045,762 sets of identical nine-field CSV records contain
2,154,860 rows. Retaining one row per set would remove **1,109,098 rows (5.360%)**;
the maximum multiplicity is 48. No rows have been removed. These may reflect
repeated instrumentation or real repeated actions at one-second resolution;
the data cannot distinguish them. Exact duplicates cannot change an any-purchase
binary label or first-event timestamp, but can inflate event-count features.
Recommendation for later feature design: retain immutable raw data, use an
explicit exact-duplicate policy for counts, and compare raw/deduplicated counts
as a sensitivity check. Near-duplicate actions are not automatically errors.
Excess duplicate rows are concentrated in removals (991,820) and carts (115,342),
with 1,031 views and 905 purchases. This strengthens the case for reviewing
interaction counts rather than interpreting every repeated row as new intent.

**Prices:** 131 events have negative prices and 104,157 have zero prices. The
observed range is **-79.37 to 327.78**, with currency unverified. Negative prices
are suspicious; refunds, adjustments and errors are possible explanations,
not observed facts. Do not discard their behavioral events or redefine purchase
labels by price without evidence. For future price features, exclude negative
values from monetary summaries and retain a negative-price indicator/count;
keep zero prices separately flagged. These policies are recommendations only.
126 of the negative-price events are purchases; one purchase has zero price.
The positive target remains event-based, not a claim of positive net revenue.
February accounts for 71,254 zero-price rows, an observable distribution change
whose cause is not established here.

**Catalog and session consistency:** 272 nonmissing session IDs occur under
multiple user IDs (maximum eight users). Count sessions within users and never
treat a session key as a globally unique customer. Of 54,571 products, 1,619
have multiple category IDs, 24 have multiple nonmissing brands, and 41,508 have
multiple prices. Updates and promotions can explain variation; it is not proof
of corruption. Use event-time attributes, not a future catalog mapping. Category
IDs exceed the exact-integer range of floating point: preserve int64/string keys.

**Activity is highly uneven:** median lifetime observed events per user is 2;
the 90th/95th/99th percentiles are 18/47/214, and the maximum is 26,752.
769,492 users (46.94%) have one event; 1,256,381 (76.64%) appear on one UTC date.
Median active dates is 1, with 90th/95th/99th percentiles of 3/4/12.
1,104 users exceed 1,000 events; one exceeds 10,000.
High activity warrants later review but does not establish bot behavior.
Do not require a return visit or day-seven activity: doing so would select a
different population and remove many legitimate negative examples.

## Coverage: observation versus assumption

Observed timestamps extend from **2019-10-01 00:00:00 UTC** through
**2020-02-29 23:59:59 UTC**. Every one of the 152 calendar dates and every
calendar hour has events. This supports using **March 1, 2020, 00:00 UTC** as
the exclusive coverage boundary at the source's one-second resolution.

There is nevertheless a **34-minute, 6-second inter-event gap** on January 22,
between 02:52:08 and 03:26:14 UTC. The next-largest gap is 390 seconds.
This could indicate a partial outage or genuinely absent activity. Nonempty
hours/days cannot prove continuous instrumentation. Baseline eligibility below
assumes no unobserved logging losses; a separate conservative sensitivity uses
a **30-minute gap threshold**, which is an explicit diagnostic assumption.
It excludes any customer whose full 37-day span intersects a flagged gap.
It is not a claim that this threshold identifies all real outages.

Under this stricter rule, **885,659 customers** remain eligible, with **19,497
positives (2.201%)**. The higher rate reflects a changed cohort, not better
prediction. The original training and validation counts are unchanged, but the
original test drops to **9,770 customers and 135 positives (1.382%)**. A
37-day span can intersect a short gap even when the customer's own last visit
was long before it. This deliberately conservative rule is costly and leaves
the original test less precise; it should not be silently adopted or ignored.

## Prediction contract and baseline eligibility

For each valid positive `user_id`, find the earliest valid event timestamp in
all five files: **`t0`**. This is first observed activity, not proven acquisition.

- Prediction time: **`p = t0 + 7 elapsed days`**.
- Inputs: only events in **`[t0, p)`**.
- Outcome: any `purchase` in **`[p, p + 30 days)`**.
- Eligibility: **`t0 + 37 days <= coverage_end`**, with no known zero-event
  logging day intersecting the 37-day span. No requirement for continued activity.
- Target: 1 if a purchase exists in that outcome interval; 0 otherwise, under
  the coverage assumption. Incomplete windows are excluded even if a positive
  purchase is already visible.

An event at exactly `p` belongs to the outcome. An event at exactly `p + 30 days`
does not. First-week purchasers remain eligible, so this is an **any subsequent
purchase** task, including repeat purchases; it is not exclusively first purchase.

Baseline eligibility produces **1,256,629 customers**, including **23,760
positive outcomes (1.891%)**. **382,729 customers** have incomplete horizons
and are excluded, including 2,249 with an already visible future purchase.
The theoretical latest eligible first-seen time is January 24 at 00:00 UTC;
the latest actually observed eligible first event is January 23 at 23:59:45.

| First-week behavior | Eligible customers | Future purchasers | Purchase rate |
| --- | ---: | ---: | ---: |
| No first-week purchase | 1,193,184 | 17,237 | 1.445% |
| At least one first-week purchase | 63,445 | 6,523 | 10.281% |

This shows why excluding early purchasers would materially change the question.
It does not demonstrate predictive performance or causation.

## Chronological evaluation proposal

Use one row per customer and split by prediction timestamp, preserving the
Phase 0 schedule. The gaps allow prior labels to mature before later scoring.

| Split | UTC scoring interval, end exclusive | Customers | Positives | Rate |
| --- | --- | ---: | ---: | ---: |
| Train | Oct 8–Nov 1, 2019 | 328,535 | 10,092 | 3.072% |
| Validation | Dec 1–Dec 16, 2019 | 157,349 | 1,985 | 1.262% |
| Test | Jan 15–Jan 30, 2020 | 167,822 | 2,140 | 1.275% |

Training outcomes finish before December 1; validation outcomes finish before
January 15; test outcomes finish before February 29. Freeze preprocessing,
feature choices, tuning and thresholds using training/validation only. Any
refit at January 15 may use only labels already mature then. Eligibility counts
were inspected for audit feasibility; no model or feature selection has used
test outcomes. Keep future model comparisons on this test set limited.

October scoring cohorts have a 3.072% purchase rate, November 2.067%, December
1.164%, and eligible January cohorts 1.197%. This is observed temporal drift;
seasonality, customer composition, and left truncation are possible explanations.
137,427 users first appear during the first dataset week, when prior history
is unknown. A later acquisition cohort/washout sensitivity would assess this
limitation but cannot prove a customer is truly new.

There are enough positive outcomes to attempt simple predictive baselines;
there is no universal minimum count that guarantees model utility. The outcome
is uncommon, so later report PR-AUC, calibration/Brier score and precision/recall
at a validation-selected contact budget, alongside prevalence and ROC-AUC.
Use resampling/time sensitivity for uncertainty. This five-month, one-retailer
study cannot establish future deployment performance or causal marketing impact.

The intended prediction question needs no change to its time horizons. It does
need explicit wording: first **observed** activity, **any subsequent observed
purchase**, and a declared coverage/duplicate policy. The original test plan
depends on the continuity assumption. A shorter, earlier conservative schedule
is also counted in the JSON, with all test outcomes ending before the suspected
January gap; its concrete counts and limitations are discussed below.

| Earlier conservative split | UTC scoring interval, end exclusive | Customers | Positives | Rate |
| --- | --- | ---: | ---: | ---: |
| Train | Oct 8–Oct 13, 2019 | 87,760 | 3,814 | 4.346% |
| Validation | Nov 12–Nov 17, 2019 | 53,089 | 1,150 | 2.166% |
| Test | Dec 17–Dec 22, 2019 | 51,444 | 547 | 1.063% |

All earlier test outcomes finish by January 20, before the suspicious gap;
earlier split labels also mature before the next split begins. This provides
more positives than the gap-filtered original test without assuming the pause
was harmless. The cost is five-day scoring cohorts and a training cohort
entirely first observed near the dataset's left boundary. **Recommendation:**
if continuous logging cannot be confirmed, prefer this earlier schedule for
an exploratory conservative study, retaining the original schedule as a clearly
labeled continuity-assuming sensitivity. Neither supports strong deployment
claims. Review and freeze the choice before any model comparison; more
continuous history would support a broader and less fragile evaluation.

## Recommended future inputs and leakage controls

Keep the first feature set small and interpretable:

- Four event counts: view, cart, removal, purchase, under the reviewed duplicate policy.
- Distinct products and category IDs; defer nearly empty category taxonomy text.
- Active UTC dates and distinct nonmissing sessions within each customer.
  Seven elapsed days can span eight UTC calendar dates; document this explicitly.
- Hours since last feature-window event at scoring time.
- Cart/view and removal/cart ratios with defined zero-denominator handling.
  These are interaction ratios, not order-level conversion probabilities.
- Mean/max nonnegative viewed-product price, with separate missing/no-view,
  zero-price and negative-price indicators. Avoid browsing-price sums called spend.

Do not use lifetime aggregates, future catalog mappings, post-scoring events,
or sessions extending beyond the scoring timestamp. User/session IDs are keys,
not model inputs. Compute any learned imputation, scaling, product statistics
or category selections using training data only. Labels must not influence
cohort inclusion except the predeclared coverage rules. Do not mistake the
event purchase rate (6.220%) for the customer target rate (1.891%).

## What the Python and SQL do, and why

[`acquire.py`](../src/growthlab/acquire.py) checks the public source/version,
free-use statement and file list, requires disk headroom, then downloads one
ZIP at a time. Extraction verifies the expected filename/expanded size and ZIP
CRC; SHA-256 hashes support repeat verification. Verified existing CSVs are
skipped; changed/unmanaged files cause a stop rather than silent replacement.
Tokens are not requested or stored. This makes provenance reviewable and avoids
accidental overwrites or duplicate large downloads.

[`audit.py`](../src/growthlab/audit.py) uses DuckDB SQL in these stages:

| Analysis | SQL/Python action | Why it matters |
| --- | --- | --- |
| Schema and parsing | Check exact header; read as VARCHAR; retain originals and use guarded int64 casts / `try_strptime` / numeric casts | Expose malformed fields without losing source values or rounding category IDs |
| Local Parquet | Stream one monthly CSV into ZSTD Parquet | Reduce subsequent I/O; avoid full-data pandas memory use |
| Counts and missingness | `count`, conditional counts, distinct users, null/blank checks | Establish population, class prevalence and usable fields |
| Duplicates | Group on all nine original fields and count excess rows | Quantify potential count inflation without blindly deleting events |
| Coverage | Generate a calendar, anti-join observed dates/hours, compare adjacent distinct timestamps | Reveal missing periods that a simple min/max would conceal |
| Identifier/catalog checks | Group sessions/products; count distinct attached attributes | Detect ambiguous grouping keys and changing catalog values |
| Activity distribution | Aggregate per-user counts/active dates and exact quantiles | Reveal sparse histories and extreme activity |
| Eligibility/outcomes | Global `min(event_ts)` per user; bounded purchase join; explicit horizon and gap filters | Count a valid cohort without treating censored users as negatives |
| Splits/sensitivity | Aggregate by scoring interval and apply conservative gap exclusion | Verify label maturity, positive counts and coverage sensitivity |

The local DuckDB customer/outcome tables support these aggregate counts only;
there is no reusable customer feature table or modeling pipeline. Only small
aggregate results are written under `docs/phase1/`; customer identifiers remain
in ignored local data. The original CSVs are never modified.

Reproduce from the repository root with the README commands. Tests use synthetic
data to verify parsing precision, missingness/duplicate preservation, timestamp
boundaries, censoring, cross-month first appearances, logging-gap intersection,
end-to-end count reconciliation, and acquisition safety. They do not assert
that the observed dataset must always have today's particular counts.

## Acquisition, resource use, and verification

The source is the official [Kaggle Cosmetics dataset](https://www.kaggle.com/datasets/mkechinov/ecommerce-events-history-in-cosmetics-shop),
linked by the [REES46 dataset catalog](https://rees46.com/en/datasets).
Version 6, its five filenames, the publisher's free-use statement, and its
attribution requirement were rechecked before downloading. Attribution links
are retained in the README and acquisition manifest. The license is
“Data files © Original Authors,” not CC0. No authentication, paid service,
cloud resources, or data redistribution was used.

The observed Mac has **8 GiB physical RAM** and initially about **143 GiB free
disk**; a system memory-pressure query reported 33% free. Rather than using all
nominal RAM, the audit uses **one thread, a 1 GB DuckDB memory limit, an 8 GB
temporary spill cap**, and a persistent local database. The memory limit is an
engine limit, not a whole-process limit.

Preflight measured the five ZIP sizes at **450,866,660 bytes** combined.
The disk guard required roughly **34.8 GiB free**, including a **20 GiB OS
reserve**, raw data, a conservative Parquet allowance, archives/headroom, and
8 GiB for temporary operations. Free space substantially exceeded this check.

| Storage item | Actual bytes after audit | Interpretation |
| --- | ---: | --- |
| Original CSVs | 2,434,277,452 | 2.43 GB expanded source |
| Original ZIPs | 450,866,660 | 451 MB downloaded, sequentially |
| Audit Parquet | 516,380,933 | 516 MB, including original fields and parsed audit fields |

The final complete run took **94.11 seconds** and peaked at **1,289,404,416 bytes
of process resident memory**, approximately **1.20 GiB**. These are observed
local-run measurements, not performance guarantees. The on-disk database size,
remaining disk space, and full resource snapshot are recorded in
[resources.json](phase1/resources.json). Peak temporary spill usage was not
measured; the explicit cap was 8 GB. Disk-backed execution does not imply that
the engine necessarily needed to spill in this run.

All monthly ZIP CRCs and official expanded byte sizes passed; CSV and ZIP
SHA-256 hashes were recorded. Re-running acquisition verified existing hashes
and skipped all five downloads. An independent calculation using each user's
earliest post-week-one purchase reproduced baseline eligible and positive
counts. Summary checks reconcile monthly, daily and event-type totals, acquired
file hashes, population counts and label-maturity boundaries. Thirteen automated
tests pass, the editable package/CLI install works, and dependency checks pass.

Only source, tests, documentation, and small aggregate JSON summaries belong in
Git. CSVs, ZIPs, Parquet, the DuckDB database, spill files, logs, environments and
local settings remain ignored. Phase 0 is preserved in commit `551c768` and was
pushed to `origin/main`. Phase 1 stops here for review of these actual findings.
