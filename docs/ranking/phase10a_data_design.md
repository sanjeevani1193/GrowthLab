# Phase 10A — personalized product ranking: data audit and design

Audit date: **2026-11-09**. Status: design and aggregate audit complete,
awaiting review. **No ranking model trained, fitted preprocessing, final ranking
predictions, dependency installation, commit or push.** Earlier modules are
unchanged at `e7c214b7807f5ea14c07677cd37ea3dabaeddf7b`.

This is a new REES46 product-ranking study. It is separate from Module 1's
customer-level purchase prediction and from RetailHero's experimental study.
It does not join their customer populations or estimate incentive effects.

## 1. Sources, verification and audit scope

Reused the five existing **Phase 2 cleaned Parquet partitions**, verifying their
SHA-256 against [Phase 2](../phase2/summary.json) before and after processing.
No CSV conversion or deduplication was repeated. The original nine decoded CSV
fields define exact-row equality; parsing helper fields happens afterward.
Raw CSV fingerprints also still match the prior manifest. Both existing module
freeze checks and all 82 recorded prior data/artifact states passed. Git shows
no changes to any previously tracked file.

Source: REES46/Open CDP, published by Michael Kechinov as
[eCommerce Events History in Cosmetics Shop](https://www.kaggle.com/datasets/mkechinov/ecommerce-events-history-in-cosmetics-shop).
Attribution and the recorded “Data files © Original Authors” terms remain in
[source metadata](../dataset_source_metadata.json). No data is redistributed.
Reviewed [Phase 1](../phase1_report.md), [Phase 1.5](../phase1_5_design_decisions.md),
[Phase 2](../phase2_feature_engineering.md), their aggregate outputs, and existing
audit/feature code. These supply the duplicate definition and known logging risks.

[Aggregate audit evidence](phase10a_audit_summary.json) records inputs, queries'
outputs, source fingerprint and resource measurements. Full-period statistics
below are **descriptive**. Only the earlier training/development label windows
are inspected for ranking feasibility. Final-test history is counted, but no
final-test relevance table, candidate recall or ranking metric is computed.

This is not an assertion that January data has never been read: full-period
descriptive aggregates include it, and Module 1 already used overlapping dates
for another task. The ranking final evaluation remains unused for method
selection, but it is not a pristine external dataset independent of all project
exploration. Do not claim otherwise.

## 2. Actual interaction statistics and row grain

| Quantity | Observed value |
| --- | ---: |
| Original event rows | 20,692,840 |
| Exact duplicate excess removed by approved Phase 2 cleaning | 1,109,098 |
| Cleaned event rows | **19,583,742** |
| Unique observed customer IDs | **1,639,358** |
| Unique product IDs | **54,571** |
| Views | 9,656,790 |
| Cart additions | 5,652,991 |
| Cart removals | 2,987,859 |
| Purchase event rows | **1,286,102** |
| Distinct customer–product interaction pairs | **10,157,408** |
| Distinct purchased customer–product pairs | **1,225,886** |
| Customers with an observed purchase | 110,518 |
| Products with an observed purchase | 40,777 |
| Products with no observed purchase | 13,794 |

An event row means a customer ID interacted with one product at a timestamp.
It is **not an impression, rating, transaction, order, quantity or verified
person**. Multiple product purchase rows may belong to one basket. There is no
verified order identifier; counting orders from timestamps or sessions would
invent information. Distinct pairs remove repeated interactions between the
same two IDs; a binary relevance label counts a purchased product once per user.

Repeat behavior has several meanings:

- 4,514,189 pairs have at least two interaction rows; **648,528 customers**
  repeat an interaction with some product.
- 99,086 customers have multiple purchase rows. These need not be separate orders.
- **24,849 customers** have purchases at multiple timestamps; 22,738 purchase
  on multiple UTC dates. Neither is a verified transaction count.
- **11,898 customers** repurchase the same product at distinct timestamps,
  covering 51,041 pairs. Of these, 10,175 customers repurchase a product on
  multiple dates. This supports retaining repeat-product candidates rather
  than assuming recommendations must always be novel.

### Sparsity and usable historical support

There are **89,461,405,418 possible customer–product pairs**. Only **0.011354%**
have an observed interaction (99.988646% have none). Absence is not a negative
preference: the customer may never have seen the product.

The cleaned per-customer event median/p90/p95/p99 are **2/18/45/200**;
distinct-product quantiles are **1/11/24/93**. There are **769,703 single-event
customers**, and only 648,395 interact with multiple products. The largest
observed history has 26,098 events and 5,105 products. This unevenness favors
simple fallbacks and capped history processing; it does not establish bots.

Across the full period, 26,947 products have at least five distinct buyers and
12,006 have at least twenty. Buyer-count median/p90/p95/p99 are **4/48/93/293**;
the maximum is 7,049. Thresholds below describe support, not an eligibility
requirement chosen using future activity.

| Snapshot | Customers with history | With ≥2 products | With ≥5 events | With ≥2 active dates | Observed products | Products with ≥5 / ≥20 buyers |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Nov 1, using October | 399,664 | 149,395 | 92,519 | 70,874 | 41,899 | 10,479 / 2,673 |
| Dec 1, using November | 368,232 | 160,084 | 103,053 | 80,199 | 43,419 | 12,851 / 3,489 |
| Jan 1, using December, history only | 370,154 | 147,393 | 90,464 | 75,267 | 44,624 | 9,501 / 2,152 |

### Popularity and catalog quality

Sorting products by distinct buyers over the full dataset, the top 100 account
for **10.67%** of distinct purchased pairs; top 500 account for **25.18%**.
Top 1% of the catalog (546 items) account for **26.31%**, and top 10% (5,458)
for **68.72%**. This is a long tail: popularity is a useful baseline but cannot
cover everything. These full-period shares are not future prediction results
and must not become a scoring-time popularity lookup.

A concrete **past-only November** example: products `5809910`, `5854897` and
`5833330` have **2,057, 1,127 and 983 distinct buyers**, respectively. The first
is the November popularity leader. These are anonymous catalog keys, not product
names or evidence that another customer wants the same item.

Cleaned data has no missing category IDs, but **1,619 products change category
ID** over time. Numeric category keys can support a cautious past-only category
affinity experiment; an ID's presence does not establish a meaningful taxonomy.
Preserve int64 or strings, since these IDs exceed floating-point exactness.
Use the latest category known **before scoring**, deterministic ties, and a
missing/unresolved policy; never use a five-month future catalog mapping.

Category text is missing in **19,240,810 rows (98.25%)**, brand in **8,265,149
(42.20%)**; 24 products have multiple observed nonmissing brands. Defer category
text and brand from the first ranking benchmark. There are **124 negative-price
and 86,326 zero-price events** after deduplication. Keep their behavior and
event-based labels; exclude negative prices from any later monetary feature,
retain/flag zero, and do not infer currency, margin or revenue from this audit.
Existing audits found missing/shared session IDs: sessions remain nested within
customers, never order IDs or globally unique people.

## 3. Coverage and proposed ranking contract

Available timestamps span **2019-10-01 00:00:00 through 2020-02-29 23:59:59 UTC**;
all 152 dates have events. Earlier audit evidence identifies a **34m06s pause
on January 22, 02:52:08–03:26:14 UTC**. A nonempty day does not guarantee complete
logging. Causes and any lost purchases remain unknown. The primary schedule
below ends before this gap rather than imputing missing behavior.

**Proposed business task:** for a customer active in the previous calendar
month, order a past-available candidate set by future observed product purchase
relevance over the next fourteen elapsed days. Monthly snapshots give more
history than a new customer's seven days and a shorter, easier-to-mature product
outcome than thirty days. This is a design recommendation, not an empirically
optimal time horizon. Histories contain 30 or 31 days; they are calendar months,
not a claimed constant-day feature window.

One example is **(customer ID, prediction timestamp, candidate product ID)**.
The query/group being ranked is **(customer ID, timestamp)**. Its binary label
is 1 if at least one purchase of that product occurs in the future interval;
otherwise 0 for a fully observed interval. A zero label means **no logged
purchase within that window**, not dislike. Multiple purchases do not increase
relevance above 1. Views/carts are historical signals, not future purchase labels.

Eligibility uses only valid keys, complete timestamp coverage and at least one
event in the past month, including removal-only histories. It does not require
future activity, a purchase, five events or multiple products. Do not drop an
inactive future customer to make results look better. Unknown logging loss and
the dataset's left boundary remain limitations. Do not infer real acquisition
dates or stable identity from first observation.

**All intervals are UTC and end-exclusive:**

| Role | Historical inputs | Prediction time | Purchase label window |
| --- | --- | --- | --- |
| Training | [2019-10-01, 2019-11-01) | 2019-11-01 00:00 | [2019-11-01, 2019-11-15) |
| Validation | [2019-11-01, 2019-12-01) | 2019-12-01 00:00 | [2019-12-01, 2019-12-15) |
| Final test, proposed reserved evaluation | [2019-12-01, 2020-01-01) | 2020-01-01 00:00 | [2020-01-01, 2020-01-15) |

An event exactly at prediction time is a label event, never a feature. An event
at the outcome end is excluded. Training labels mature before validation;
validation labels mature before test. Events that served as earlier labels can
legitimately enter a later snapshot's history, since they are then in the past.
Customers/products may recur across snapshots, as in returning-customer
personalization; this is **temporal evaluation, not disjoint-customer generalization**.
Keep identifiers as join/group keys, not direct numeric predictors or labels.

| Development outcomes | Train | Validation |
| --- | ---: | ---: |
| Eligible historical customers | 399,664 | 368,232 |
| Eligible customers with a future purchase | 6,027 | 5,693 |
| Their distinct future purchased pairs | 66,018 | 59,298 |
| Previously interacted purchased pairs | 17,390 | 14,589 |
| Previously purchased pairs | 1,902 | 1,892 |
| Purchased pairs absent from the past-month catalog | 1,485 | 1,327 |
| All future purchasers, including window-cold customers | 13,627 | 12,938 |
| Future purchasers without past-month history | 7,600 | 7,245 |

Only **1.546%** of validation historical customers purchase in the outcome
window. Moreover, 7,245 of all 12,938 future purchasing users have no November
history. These are **window-cold** users, not necessarily truly new people;
earlier October history could exist. At a monthly batch scoring timestamp they
are outside the declared historical-customer cohort. Do not quietly count them
as successfully personalized, or relabel them as new acquisitions. Report this
scope gap; a future first-visit/session system would need its own design.

Products absent from the past-month catalog are similarly window-cold, not
proven newly launched. Keep those purchases in retrieval metric denominators.
The validation eligible-catalog recall ceiling is (59,298−1,327)/59,298 =
**97.76%** even with perfect retrieval from that catalog. Previously purchased
products stay eligible: 1,892 relevant pairs would otherwise be deliberately
unrecoverable. There is no stock/feed evidence; “eligible” means past-observed
and not known to be invalid, **not verified in stock or saleable at scoring**.

## 4. Candidate generation: measured options and recommendation

Candidate generation is a cheap shortlist step before detailed scoring. Scoring
all pairs creates almost 89.5 billion rows over all observed IDs. Even the
validation warm cohort times its past-month catalog is about 16 billion pairs.
A reranker can reorder a shortlist, but cannot recover a purchased product
that never entered it.

Investigated four practical approaches:

- **Global popularity:** count distinct past buyers per product, rather than
  allowing one repeat buyer to dominate. Break ties by product ID. It provides
  a fallback even when one customer's history is thin.
- **Recent personal products:** retain up to the 50 distinct products most
  recently interacted with before scoring, ties by product ID. The current
  diagnostic uses all four event types, including removals; being considered
  does not mean that a removal is a positive preference. Past views/carts can
  reappear; already purchased products are not automatically excluded.
- **Category popularity:** rank prior products within a customer's past category
  IDs, if category stability/affinity tests later support it. IDs are complete
  but mutable and semantically unverified; category text cannot rescue coverage.
  Not built or measured as a candidate generator here.
- **Item-to-item co-occurrence:** products connected by shoppers' past histories.
  For example, users interacting with A also interact with B. This is
  association, not similarity in product meaning or a causal effect. November
  contains **77,977,366** potential unordered within-user product-pair emissions;
  limiting each user's history to 50 products reduces this to **23,421,918**.
  These are workload estimates, not a computed neighbor table. A disk-backed
  capped distinct-user graph with small neighbor lists is plausible, but defer
  its implementation and coverage measurement to Phase 10B review.

### Actual development-only candidate coverage

For each November-active customer, union the top G November purchased products
with that customer's last 50 November products, deduplicating overlaps. All
candidate membership is fixed from history. Only afterward intersect with
December 1–14 purchases. No final-test purchases participate. A relevant product
outside candidates remains a miss; positives are never injected into candidates.

| G popular + ≤50 personal | Global-only pair recall | Union pair recall | Union mean user recall | Mean / maximum candidates | Candidate rows for all 368,232 users |
| --- | ---: | ---: | ---: | ---: | ---: |
| 20 + 50 | 4.92% | 24.47% | 28.27% | 25.14 / 70 | 9,257,144 |
| 50 + 50 | 7.81% | **26.58%** | **30.35%** | 55.02 / 100 | **20,258,719** |
| 100 + 50 | 11.13% | 29.05% | 32.77% | 104.88 / 150 | 38,619,183 |
| 200 + 50 | 16.04% | 32.61% | 36.37% | 204.67 / 250 | 75,365,432 |
| 500 + 50 | 25.08% | 39.38% | 43.08% | 504.24 / 550 | 185,675,640 |

Recent-personal-only pair recall is **21.12%**, mean user recall **24.56%**.
Pair recall divides hits by all **59,298** relevant pairs for the eligible
cohort. Mean user recall averages within each of its **5,693 purchasing
customers**, giving each customer equal weight rather than each purchased item.
The two averages answer different questions. Candidate row counts include
**all eligible customers**, including those with no outcome purchase; there is
no outcome-based cohort filtering to reduce the workload.

**Recommended first implementation:** G=50 with personal cap=50, at most 100
candidates, as a bounded baseline rather than a claimed optimal count. The
November product-history p95 is 29 and p99 is 84; a cap of 50 retains substantial
history while bounding prolific users. Under this configuration, candidate-count
median/p90/p95/p99 are **51/64/78/99**. Increasing G from 50 to 100 nearly
doubles total rows for only **2.47 percentage points** additional pair recall;
G=500 needs over nine times the rows of G=50. This supports starting small on
8GB and investigating targeted retrieval rather than blindly expanding globals.

The **26.58% recovery is weak**, not a successful recommender result. It is an
observed shortlist ceiling for pair Recall@K on that development window; any
reranker on this fixed pool has at most that micro recall even with perfect
ordering. Additional retrieval may be more valuable than a complex reranker.
Do not choose G, personal-history cap, weights or graph rules using the final
test. Cap 50 is a reasoned initial proposal, not an exhaustively optimized cap;
Phase 10B should compare a small predeclared cap grid on development only.

## 5. Baselines and conditional model option

Use the **same eligible customers and same frozen candidate union** for all
reranking comparisons. Otherwise a larger retrieved pool can masquerade as a
better ordering algorithm. Report candidate recall separately. A standalone
global top-K reference may additionally be shown, labeled as a different
retrieval policy, not the controlled reranker comparison.

**A. Global-popularity ordering:** score each candidate by distinct buyers in
the past month. Products with none score zero; ties use ID. It learns no
customer-specific pattern. It tests whether personalization adds value over
generally purchased items.

**B. Simple personalized ordering:** order candidates by the customer's latest
positive interaction time (view, cart or purchase), then past popularity and ID;
candidates with no positive history fall back to popularity. A removal does not
create a positive recency signal. This is a transparent heuristic, not a fitted
purchase probability. It can fail when historical interests are stale or when
the next desired product has never been viewed. Document and freeze the exact
tie/fallback order before implementation; do not claim it was evaluated here.

**C. Optional lightweight reranker, after candidate coverage review:** an
existing scikit-learn histogram gradient-boosted **binary classifier used to
sort candidate scores**, trained on training-window labels only. Potential
inputs are pre-score user–item recency/counts for views/carts/purchases, prior
removals as a separate signal, and past product buyer counts. This would be
pointwise scoring, **not** a pairwise/listwise learning-to-rank objective and
not automatically calibrated purchase probabilities. A small LightGBM
`LGBMRanker` could later directly learn ordering within customer-time groups
using a ranking objective; do not install or implement it now. Its documented
group structure is described in the
[official API](https://lightgbm.readthedocs.io/en/stable/pythonapi/lightgbm.LGBMRanker.html).

The 6,027 training purchasers and 66,018 distinct relevant training pairs provide
plausible exploratory signal, but candidate recall, imbalance and one training
snapshot limit learning. Complex models may fit sparse/noisy behavior or simply
relearn popularity. First measure A and B; defer C if retrieval remains the
bottleneck. This audit does not establish that C will outperform either baseline.

If training negatives must be sampled, sample only training candidate items
without a logged outcome purchase, reproducibly within customer-time groups,
preserving positives **already retrieved**. Call them unpurchased observations,
not known dislikes; document inclusion probabilities/weights and avoid claiming
sampled scores are calibrated. Never sample evaluation candidates or inject
missed positives; never use validation/test outcomes to select training negatives.
Stream customer batches rather than building a dense customer–catalog matrix.

## 6. Offline evaluation and concrete metric example

Predeclare K=5,10,20. For a purchasing eligible user, let R be the set of distinct
future purchased products, C the past-only candidates, and L the ordered top-K.

- **Recall@K:** |L∩R| / |R|. Compute equal-user mean as primary, micro pair recall
  as secondary. Keep purchases outside C in the denominator.
- **Candidate recall:** |C∩R| / |R| before ranking. It isolates retrieval loss.
- **NDCG@K:** sum binary relevance at rank i divided by log2(i+1), normalized by
  the ideal top-K sum for min(K,|R|) positives. Relevant items outside C still
  count toward this ideal; do not normalize only by retrieved positives, which
  would hide misses. This rewards putting relevant products near the top.
  See the [scikit-learn metric reference](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.ndcg_score.html).
- **User coverage:** fraction of all eligible historical customers receiving
  any recommendation and a full K-list. With G=50 and K≤20, this candidate design
  can provide all eligible customers a list, by construction. That is mechanical
  coverage, not relevance or coverage of customers who have no history.
- **Cold-start/subgroup reporting:** thin-history versus richer-history users,
  previously purchased versus new-to-user products, and products with no past
  buyers versus supported products. Separately show window-cold-user scope and
  window-cold-product misses; never silently drop them to inflate results.

**Synthetic numerical example (not a model result):** a user later purchases
A and B. Candidates are {A,X,Y}; the ordered top three are [X,A,Y]. Candidate
recall and Recall@3 are both 1/2. DCG=1/log2(3)=0.63093; ideal DCG is
1+1/log2(3)=1.63093; NDCG@3≈**0.38685**. Putting A first improves NDCG, but B is
still unrecoverable until retrieval changes. This is why retrieval and ordering
need separate assessment.

No-purchase users have empty R, so purchase recall/NDCG are undefined for them.
Report purchasing-user denominators explicitly, **without removing these users
from scoring or user-coverage reporting**. For validation, that means recall
over 5,693 purchasers and coverage over 368,232 historical users, alongside the
1.546% purchase frequency. Do not imply good conditional recall makes most
customers purchase. A future uncertainty analysis should resample entire users
with paired method differences, not treat dependent candidate rows as independent.

## 7. Leakage, implicit feedback and limits

Historical interaction is **implicit feedback**: behavior hints at interest
without explicit ratings. We have no verified impression/exposure logs, product
availability, inventory, price offers, organic search positions or deliberate
recommendation assignments. Unobserved products may be unseen rather than
disliked. Purchase labels reflect logged behavior under the original shop's
exposure policy, not all true preferences.

Only events strictly before each prediction timestamp may inform recency,
counts, categories, popularity, co-occurrence, imputation or candidate membership.
Fit learned transformations/model parameters using training only; choose rules
using validation; freeze before final evaluation. Updating declared past-only
catalog/popularity statistics at a later scoring timestamp is permitted and
must be consistent across baselines. It is not permissible to use that later
snapshot's outcome purchases. Never build one global five-month catalog graph
and reuse it across earlier snapshots.

Exact-row deduplication cannot distinguish instrumentation duplicates from valid
repeated actions in one second. Purchase events are not confirmed fulfilled/net
orders. Missing sessions, mutable categories, prices and the known gap remain
warnings. The proposed schedule avoids the known January pause, not every
possible unlogged event. One retailer, a short historical period and overlapping
IDs across time limit external validity. Offline recall/NDCG cannot establish
increased purchasing or causal business benefit; that would require a suitable
prospective experiment and exposure logging.

## 8. What the audit SQL does and resource feasibility

[`ranking_audit.py`](../../src/growthlab/ranking_audit.py) is an aggregate audit,
not a training feature pipeline:

1. Verify cleaned-file hashes against Phase 2. Reuse exact cleaned inputs.
2. Group events by customer/product into local `pairs`. This distinguishes
   repeated rows, purchased pairs and repeat purchases without inventing orders.
3. Aggregate pairs into customer/product support distributions. Count metadata
   missingness and catalog changes. Global descriptive aggregates are not a
   scoring-time feature lookup.
4. For each fixed date, create `history` with explicit half-open boundaries;
   aggregate customer/product histories and support without checking outcomes.
5. Only for training/validation, create distinct future purchased pairs and
   separate window-cold customers/products. This defines the task's reach.
6. Only for validation, compute past distinct-buyer popularity and per-user
   recent-product ranks. Join labels to these rank tables to count possible hits
   at five pool sizes; count unions without expanding all customer×global rows.
7. Return **before any label query for final_test**. Export only aggregates and
   fingerprints; no customer IDs, item score lists or predictions are exported.
8. Rehash cleaned inputs after execution. Large intermediate tables/database
   remain under ignored `data/ranking/phase10a/`.

Observed run: **56.58 seconds**, DuckDB **2.0.0**, **one thread**, **768MB engine
memory limit**, **4GB temporary spill cap**, and **1,092,288,512 bytes peak process
RSS (~1.02GiB)** on this Mac. The engine limit is not the full process limit.
Closed database size was **981,217,280 bytes (~0.91GiB)**. Free disk before the
audit was about **130GiB**; the guard requires 20GiB free. Peak spill usage was
not measured. These are local observations, not guaranteed performance.

For Phase 10B, avoid pandas over all events and avoid full candidate feature
materialization. Generate candidates in customer batches (for example ≤10,000
users × ≤100 items), project a few columns and write partitioned local Parquet
only if needed. The measured 20.3M candidate rows would still be substantial;
bounded batches and a predeclared training-negative sampling policy may be
needed before C. Co-occurrence must cap per-user products and per-item neighbors
and aggregate distinct-user support on disk. No new libraries are required
for this audit.

Reproduce the audit and tests from the repository root:

```sh
PYTHONPATH=src .venv/bin/python -m growthlab.ranking_audit
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

## 9. Checks, files and proposed Phase 10B review gate

**All 243 tests passed**, no skips: 235 existing plus 8 focused synthetic tests.
Tests cover event/pair/user grains, repeat definitions, sparsity, timestamp
boundaries, window-cold users/products, past-only candidates, unrecovered-label
denominators, unchanged results after later outcomes are added, reproducibility,
label maturity and the final-history-only branch.

An independent Python reconstruction of **12 actual development customer
histories** agreed with SQL recency membership, future distinct-product labels
and union hits. No customer identifiers or histories were exported. Global
event-type counts reconcile to 19,583,742. Both earlier modules' frozen source,
feature and model fingerprints passed; all five raw CSVs and cleaned files
remain unchanged. No model was loaded for ranking, trained or tuned.

New review files only:

- `src/growthlab/ranking_audit.py`
- `tests/test_ranking_audit.py`
- `docs/ranking/phase10a_audit_summary.json`
- This report: `docs/ranking/phase10a_data_design.md`.

Git: these four files are untracked and nothing is staged; no prior tracked
file is changed. The local audit database/spill files are ignored. No commit
or push is made.

**Recommendation:** product ranking is feasible as an exploratory study of
observed future purchases, but personalized history is sparse and candidate
recall is currently the key limitation. After approval, Phase 10B should:

1. Freeze the calendar/cohort/label contract and the candidate-recall and ranking
   metric denominators above, including repeat-product and cold-start policies.
2. Implement the measured small hybrid as a reproducible batched baseline;
   compare a small predeclared personal cap grid and bounded category/neighbor
   retrieval on development data if approved. Measure retrieval gains and costs
   before deciding whether learning-to-rank is worthwhile.
3. Compare global and simple personalized ordering on identical candidate pools.
   Preserve no-purchase users in scoring/coverage; retain missed products in
   recall denominators. Do not claim performance from this design audit.
4. Consider the lightweight model only after reviewing those results. Freeze
   the chosen method before a single final-test evaluation. Do not refit or
   select methods using final outcomes.

**Stop after Phase 10A.** No Phase 10B implementation, trained ranking model,
dashboard, Docker, deployment or unrelated enhancement is included.
