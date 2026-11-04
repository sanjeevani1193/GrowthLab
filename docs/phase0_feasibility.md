# Phase 0 — setup and dataset feasibility

Inspection date: 2026-11-04. This stage stops at feasibility; there is no model
or feature/label pipeline and no performance result.

## Repository and files

Initial state: branch `main`, tracking `origin/main`, at `48f2c49` (initial
commit). The remote is `https://github.com/sanjeevani1193/GrowthLab.git`.
Tracked files were `README.md` and a general Python `.gitignore`; `.vscode/`
was untracked. No dataset, notebook, application, or existing Python package
was present. No applicable `AGENTS.md` was found in GrowthLab. CityPulse files
were not opened or modified. No commits or pushes were made.

| File | Purpose |
| --- | --- |
| `README.md` (updated) | Scope, completed versus planned work, setup, attribution |
| `.gitignore` (extended) | Preserve existing rules; exclude data, outputs, credentials, and local editor settings |
| `pyproject.toml` | Minimal Python 3.11+ package metadata, with no runtime dependencies |
| `src/growthlab/__init__.py` | Empty package scaffold; no pipeline logic |
| `data/README.md` | Local data policy and sample limitations |
| `docs/phase0_feasibility.md` | This report and the proposed prediction contract |
| `docs/dataset_source_metadata.json` | Public API provenance, publisher description, version and file sizes |
| `docs/sample_inspection.json` | Bounded sample provenance, hashes, columns and inspection summary |
| `data/sample/2019-Oct.head100.csv` (local, ignored) | 100 real events for schema inspection only |

The available interpreter was Python 3.14.7. No environment was created and no
dependencies were installed. Python 3.11+ is the intended project requirement;
future dependencies still need compatibility checks.

## Source, usage and coverage

The official [REES46 dataset catalog](https://rees46.com/en/datasets) links its
Cosmetics behavior dataset to Michael Kechinov's
[Kaggle dataset](https://www.kaggle.com/datasets/mkechinov/ecommerce-events-history-in-cosmetics-shop).
The publisher describes approximately 20 million events across five months,
October 2019–February 2020, from a cosmetics retailer. This is an advertised
count, not a locally verified row count. This is the Cosmetics dataset, not
the larger multi-category store dataset.

Kaggle's browser page did not expose readable content. The following public,
unauthenticated JSON endpoints supplied the publisher description and file list:

- [Dataset metadata](https://www.kaggle.com/api/v1/datasets/view/mkechinov/ecommerce-events-history-in-cosmetics-shop)
- [File metadata](https://www.kaggle.com/api/v1/datasets/list/mkechinov/ecommerce-events-history-in-cosmetics-shop)

The retrieved version is **6**, last updated **2020-03-16**. The publisher allows
free use in works and educational materials with links to both Kaggle and
REES46. Kaggle's license field is **Data files © Original Authors**. Preserve
those credits; do not describe the data as public domain or CC0. The description
does not specify a separate redistribution license. GrowthLab therefore keeps
raw data local and links readers to the official source.

| Official file | Uncompressed CSV bytes | Decimal MB |
| --- | ---: | ---: |
| `2019-Oct.csv` | 482,542,278 | 482.54 |
| `2019-Nov.csv` | 545,839,412 | 545.84 |
| `2019-Dec.csv` | 415,302,972 | 415.30 |
| `2020-Jan.csv` | 501,792,804 | 501.79 |
| `2020-Feb.csv` | 488,799,986 | 488.80 |
| **Total** | **2,434,277,452** | **2,434.28** |

These are API-reported CSV sizes: approximately **2.43 GB / 2.27 GiB** on disk,
not Python memory requirements or compressed network transfer sizes. The range
response reports **87,127,708 bytes** for the single-file October ZIP. Other
compressed sizes and a combined archive size have not been checked. Budget
roughly 6–10 GB of free disk as a planning allowance for archives, CSVs, derived
files, and spill space; actual requirements depend on the processing approach.

The advertised months are not proof of uninterrupted logging or precise
earliest/latest timestamps. Only the sample's start has been checked. Full-file
time bounds, daily coverage, row counts, and continuity remain audit tasks.

## What one row means and actual schema

One row records one user's interaction with one product at a timestamp in a
session. It is not one customer, session, or order. Several product-level
purchase events can belong to the same order/session. There is no explicit
order ID, quantity, treatment assignment, or demographic information.

The CSV header below was confirmed in real data. CSV has no stored Python
dtypes: the last column specifies the proposed explicit parse type, verified
where applicable against the 100 sampled events.

| Actual column | Meaning / observed representation | Proposed type |
| --- | --- | --- |
| `event_time` | UTC text, e.g. `2019-10-01 00:00:00 UTC` | UTC timestamp |
| `event_type` | Event name text | Categorical string |
| `product_id` | Integer-like product identifier | Signed int64; categorical meaning |
| `category_id` | Large integer-like category identifier | Nullable signed int64; categorical meaning |
| `category_code` | Taxonomy text or empty field | Nullable string |
| `brand` | Brand text or empty field | Nullable string |
| `price` | Decimal numeric text | Float64 for initial features; decimal if accounting is later needed |
| `user_id` | Integer-like persistent user identifier | Signed int64; grouping key |
| `user_session` | Session identifier text | Nullable string |

All 100 timestamps and prices parsed successfully, and all sampled IDs fit
signed int64. This does not establish full-file validity or nullability. Keep
large IDs out of float32/float64 conversions because they can lose precision;
IDs are keys, not numeric predictors. Currency is not established here.

The publisher lists `view`, `cart`, `remove_from_cart`, and `purchase`. Its
schema table also incorrectly says the event type is purchase only. The
dedicated event-type list and real sample contradict that entry. The sample
contains the first three types; **purchase was not observed in these 100 rows**.
All four types and their full-data counts still require verification.

## Real sample inspection and limits

An unauthenticated HTTP range request for bytes `0–65535` of version 6's October
single-file ZIP returned HTTP 206 with exactly **65,536 bytes**. The first ZIP
member was `2019-Oct.csv`. A bounded partial decompression provided the first
100 complete event rows; the full file was not downloaded. Hashes, request URL,
and response metadata are in `sample_inspection.json`. The full ZIP checksum
could not be validated from a prefix.

The sample covers **2019-10-01 00:00:00–00:02:57 UTC**. `category_code` is empty
in **99/100** rows and `brand` in **33/100**; other fields have no empty values
in this sample. These are head-sample observations, not estimates for the
dataset. They motivate missing-value handling and caution about taxonomy
features. The sample cannot establish purchase prevalence, customer counts,
class balance, stable identity, or model quality.

## Feasibility and prediction contract

**Provisionally feasible for observed purchase prediction**, subject to the
full-data audit. The documented timestamps, user keys, and purchase indicator
are sufficient to construct customer histories and future outcomes. No accuracy
or business-impact claim can be made yet.

For each user define:

- `t0`: their earliest event in the entire acquired history, across month boundaries.
- `p = t0 + 7 days`: the time the prediction is made.
- Feature window: **`[t0, p)`**, seven elapsed 24-hour days in UTC.
- Outcome window: **`[p, p + 30 days)`**.
- Target `y = 1`: at least one `purchase` event in the outcome window; otherwise
  `y = 0` only when all 30 days of logging coverage are available.

Thus a purchase at exactly `p` belongs to the target, not to the inputs. A
purchase at exactly `p + 30 days` is outside this target. Each eligible user
contributes one prediction row. Purchases during the first seven days can be
inputs: the target is any later purchase, including a repeat purchase, not
necessarily the customer's first purchase. Do not silently restrict the cohort
to first-week nonbuyers, returning users, or customers active on day seven.

If `T` is a verified exclusive coverage end, require **`t0 + 37 days <= T`**
for everyone, including users with an early positive outcome. Do not label
incomplete late windows as zero or retain only known late positives. Customers
need not personally remain active for 37 days: complete observation refers to
the retailer's logging coverage, not their individual last event.

For illustration only, if complete coverage ends at `2020-03-01 00:00 UTC`,
the latest eligible `t0` is `2020-01-24 00:00 UTC`. February events would still
be essential for those users' outcomes. Verify the real coverage end first.

Important limits and leakage controls:

- **Left truncation:** first observed does not mean newly acquired. Customers
  active at the October boundary can have earlier unseen histories. Describe
  the cohort honestly; later consider a washout sensitivity analysis without
  claiming it proves new-customer status.
- **Right censoring and logging gaps:** unavailable future events are unknown,
  not negatives. Audit global daily coverage and exclude affected windows.
- **Time leakage:** no lifetime aggregates, post-`p` sessions, future purchases,
  whole-month features, or features spanning across the scoring boundary. Filter
  individual events by time even when sessions cross the boundary.
- **Identity and data quality:** validate cross-month user persistence as far as
  possible, missing session IDs, duplicates, timestamp order, negative/zero prices,
  and unexpected event types. Do not blindly deduplicate legitimate repeated
  actions. Log any chosen duplicate policy.
- **Population bias:** one pseudonymous ID may not equal one person; purchases
  outside this retailer or unlogged activity are unavailable. The label means
  an observed purchase, not net retained revenue or general purchase intent.
- **Preprocessing:** any imputation, scaling, category selection, or learned
  product statistics must be fitted on training data only. Never predict from
  raw user/session IDs or use target-driven feature selection on the test set.

## Proposed small input set

Start with roughly 14 transparent customer aggregates, all restricted to the
seven-day feature window:

- Four counts: views, cart additions, removals, and purchase events.
- Number of active UTC dates, distinct sessions, distinct products, and distinct
  category IDs (ignoring missing values and recording their handling).
- Hours since the last observed event at scoring time.
- Cart-addition/view ratio and removal/cart-addition ratio, with an explicit
  zero-denominator policy; these are interaction ratios, not order conversion.
- Mean and maximum viewed-product price, plus an indicator that no view price
  was available. Missing-price and unusual-price policies follow the audit.

First-week purchase-event counts are not order counts. Avoid calling a sum of
prices across browsing/cart events “spend.” Sparse `category_code` and brand
features can wait until full-data missingness is known.

## Chronological evaluation proposal

Split customers by **prediction time `p`**, never randomly by raw events. Compute
each user's `t0` globally first so they cannot re-enter in another month/split.
Training labels must already have matured before validation scoring begins;
validation labels must mature before final test decisions. With a 30-day target,
adjacent monthly cohorts without a gap would violate that constraint.

A conservative candidate schedule, conditional on coverage and sufficient
eligible customers/positive labels, is:

| Role | UTC prediction times `p` | Label availability / decision time |
| --- | --- | --- |
| Training | `[2019-10-08, 2019-11-01)` | All outcomes mature before Dec 1 |
| Validation | `[2019-12-01, 2019-12-16)` | All outcomes mature before Jan 15 |
| Untouched test | `[2020-01-15, 2020-01-30)` | Outcomes end before Feb 29 |

The intervening gaps allow earlier labels to become observable. Choose features,
hyperparameters, and any decision threshold using training/validation only,
then freeze choices before the Jan 15 test period. If refitting at Jan 15, use
only labels already mature then. Full 2019-Oct–2020-Feb data is needed to find
global first appearances and support this candidate test horizon. Confirm exact
boundaries and cohort counts in the audit before fixing the split.

Later evaluation should include a prevalence baseline, PR-AUC for ranking,
ROC-AUC as a secondary view, Brier score/calibration for probabilities, and
precision/recall at a validation-selected contact budget. Report per-split
customer counts, purchase rates, and uncertainty before interpreting performance.
Seasonality, a short five-month history, and only one retailer limit generality.
Predictive lift would not establish causal marketing uplift. Causal inference
and uplift modeling are deferred; this event log alone does not establish
treatment assignment or identify an intervention's effect.

## 8 GB Mac plan and exact next step

Do not concatenate all monthly CSVs into pandas: strings and intermediate
copies can use substantially more RAM than the 2.43 GB raw text size. The
proposed later tool is DuckDB with a roughly 2 GB memory limit, one or two
threads, and a local spill directory. Read only necessary columns, parse explicit
types, audit one month at a time, and use disk-backed aggregation/columnar files.
Keep only the compact customer feature table in memory when modeling eventually
begins. Start with a deterministic user-ID subset across all months if needed;
random event sampling destroys customer histories. None of this is implemented.

**Required downloads:** for the full proposed study, acquire the five official
monthly CSVs listed above (2.43 GB expanded total), preferably version 6. A
smaller October+November pilot could support early cohorts only, not the stated
chronological validation/test plan. Full compressed transfer sizes remain to be
checked before acquisition. No large download or Kaggle authentication has been
performed or authorized by this report.

**Exact next implementation step, after download approval:** acquire the agreed
official files into `data/raw/`, record version/size/checksum provenance, and
implement a bounded read-only audit reporting schema, per-file row counts,
event types, missingness, duplicates, timestamp bounds, daily coverage, and
cross-month user overlap. Use that audit to verify label-window completeness
and count eligible users/positive outcomes for the proposed cohorts. Review
those findings before feature construction or model training.
