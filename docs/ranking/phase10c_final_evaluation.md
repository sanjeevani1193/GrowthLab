# Phase 10C — final held-out product ranking evaluation

Status: **final evaluation complete and verified; awaiting review**.
Evaluation date: **2026-11-09**. Study: REES46 product ranking, separate
from Module 1 customer purchase prediction and RetailHero experimentation.
No refitting, tuning, candidate changes or new features are authorized.

## 1. Preserving the selected validation model

The five Phase 10B2B files were reviewed; **all 299 tests passed**. A full replay
reproduced every validation ranking metric, paired-bootstrap interval,
candidate hash and purchaser metric vector **exactly**, with classifier fitting
explicitly blocked. Both earlier module freezes, 82 prior data/artifact states,
raw/cleaned data, frozen candidate databases and persisted model/arrays matched
their recorded fingerprints. No earlier module or candidate rule changed.

Only the five source/test/protocol/report/aggregate files were staged and pushed.
Phase 10B2B preservation commit:
**`7efc0311b9dc10c19bd494915548e92e7d291242`**. HEAD matched `origin/main`, and Git
was clean before Phase 10C work started. No datasets, customer records, fitted
weights, caches or credentials were included.

The selected existing model remains in **persistent, gitignored** local storage:
`data/ranking/phase10b2b/model.joblib`.
SHA-256: **`3c48c0d645a690bb603bebede3732eb664f4df7dfd8c2012909b5260f3a6cadd`**.
It is the original HistGradientBoostingClassifier: log loss, learning rate 0.08,
100 iterations, 15 leaves, minimum 50 retained samples/leaf, L2=1, 63 bins,
no early stopping, no categorical features/class weights, seed 20261109.
No model is refitted in Phase 10C. The earlier fit-only resource measurement
gap is documented in Phase 10B2B; it is not filled with invented timings.

## 2. Frozen final protocol, written before January outcomes

The [machine-readable protocol](phase10c_protocol.json) is written before any
new final-ranking outcome access. It pins model/configuration, exact feature
order, candidate construction, ties, metrics, seeds and interpretation. The
[pre-outcome freeze](phase10c_freeze.json) records the code, upstream files,
December input/database, trained model, complete candidate membership and a UTC
readiness timestamp before labels are opened.

The **validation-selected method remains ML**, regardless of final results.
The final comparison assesses that decision; it does not search for a new
model, feature set, candidate budget or threshold. Report conflicting or
inconclusive endpoints honestly. Both primary positive lower bounds would
support an advantage under the declared assumptions; a zero-crossing interval
is not an established improvement for that endpoint.

### Fixed windows, population and candidate recipe

- **History:** `[2019-12-01 00:00, 2020-01-01 00:00)` UTC.
- **Prediction:** `2020-01-01 00:00:00 UTC`.
- **Final labels:** `[2020-01-01 00:00, 2020-01-15 00:00)` UTC: fourteen elapsed
  days, January 1–14 inclusive calendar dates. January 15 events are excluded.
- **Eligibility:** positive valid user/product keys and at least one December
  event; no requirement for future activity, a purchase or multiple products.
- **Relevance:** distinct observed future purchased products for each eligible
  customer, binary per product regardless of repeated purchase rows or price.
- **Retrieval:** latest-event personal products first, descending timestamp and
  ascending product ID, then unseen products ordered by December distinct
  buyers/ID. Stop at **100 unique candidates**. Already purchased products stay
  eligible; no future positive is injected into the list.

Every method scores the same eligible customers and products. No evaluation
subsampling is allowed. Customers with no final purchase remain in scoring and
coverage; their undefined purchase recall/NDCG do not enter purchaser means.
The eligible cohort has historical activity by construction, so this is not a
true no-history/customer cold-start performance estimate.

The January 22 suspicious logging gap is outside both December history and
the January 1–15 label window. This does not certify continuous logging
elsewhere. Earlier audits described five-month aggregates and Module 1 used
overlapping dates for a different task: the claim is **previously unused final
ranking evaluation**, not that January raw bytes had never been read anywhere
in the project.

### Seven unchanged engineered features

| Feature | Exact meaning in the December history |
| --- | --- |
| `product_views` | Customer/product cleaned view-row count; zero if unseen. |
| `product_carts` | Customer/product cart-addition count; zero if unseen, not current cart quantity. |
| `product_purchases` | Customer/product purchase-row count; zero if unseen, not order count. |
| `hours_since_product_event` | Hours since latest of all four event types; positive for seen pairs, NaN for unseen. |
| `product_buyers` | Distinct December purchasers for the product across all historical products; missing count zero. |
| `customer_events` | All four event types across every product for the customer in December. |
| `from_personal_history` | One for a personally interacted candidate; zero for unseen popularity backfill. |

Use existing exact-row-deduplicated Phase 2 events without recleaning raw data.
Keep cart-removal behavior in recency/activity and source membership, without
calling it positive intent or dislike. No price, metadata, ID encoding, fitted
scaling or new imputation is introduced. January purchases cannot enter any
feature, popularity lookup or candidate source. The unchanged feature-vector
function supplies float32 model inputs and native NaN recency handling.

### Three unchanged orderings

1. **Global popularity within the frozen set:** December distinct purchaser
   count descending, then product ID. Products outside the old top-200 lookup
   still receive their full historical count; absence means zero buyers.
2. **Personalized recency:** personally interacted candidates first, latest
   historical event descending, then historical buyers descending and ID.
   All four types can set recency; there are no new type weights.
3. **Existing ML reranker:** unchanged classifier `decision_function` margin
   descending, then the frozen recency position and ID. Scores are not rounded
   or presented as calibrated purchase probabilities. No fitting API is called.

### Metrics, pairing and interpretation

Primary: **macro Recall@10**, **macro NDCG@10**, and paired ML-minus-recency
differences with pointwise 95% intervals. Secondary: macro Recall/NDCG@5 and
@20, micro Recall@K, candidate recall ceilings, customer coverage and compute.

Macro recall averages `recovered products / all future purchased products`
equally across eligible purchasers. Micro recall divides all recovered pairs
by all relevant purchased pairs, giving larger baskets more weight. Binary
NDCG uses `1/log2(rank+1)` discounts and an ideal containing
`min(K, number of all relevant products)`, including products missing from the
candidates. Do not renormalize around retrieved positives or drop users whose
future purchases were all missed.

Reuse the Phase 10B2B paired percentile bootstrap: **2,000** purchaser-level
draws, **95%**, seed **20261110**, draws processed **25 at a time**, the same
sampled indices for all six endpoints. Each user's ML/recency metric values
stay paired. No per-item independence assumption or refit bootstrap is used.
The intervals are conditional on the fixed trained model and this cohort;
they exclude training-sample/refit variance, shared-product dependence and
calendar transport uncertainty. Secondary intervals are exploratory and not
simultaneously corrected. No causal sales conclusion follows.

## 3. Pre-outcome preparation and access safeguards

`ranking_final.py prepare` reads **December only**, builds the same historical
customer/product aggregates, and groups those into customer activity and product
buyer tables. It creates personal-recency and popularity source lists with the
same ties as before. Earlier development-only functions keep their deliberate
final-test rejection; a separate fixed-date adapter implements the final
snapshot without weakening those old safeguards.

A full pass hashes the sorted 100-product membership for every historical
customer before labels. The closed disk-backed history database and candidate
hash are recorded in the readiness freeze with model/source/protocol hashes.
The expected January file hash comes from prior acquisition metadata; preparation
does not query January labels. The real label input is checksum-verified only
after readiness verification and an exclusive first-access ledger is written.

Actual readiness was recorded at **2026-11-09 13:23:02 UTC**, before January
label access. December contains **3,349,426 cleaned events**, **1,890,502
customer–product pairs**, and **44,624 products**. It yields **370,154 eligible
customers ×100 = 37,015,400 candidate rows** conceptually, processed in batches
rather than materialized. The frozen canonical candidate SHA-256 is
**`9c3e9fa5e7991f391de04ccf52c1e95f811402498f396e31e28aa363b03aa09c`**.
Protocol SHA-256 is
`a2d2fb67a8ecca241d1a89d752c34cbe349ccdaa305c400a51662d0f87098f97`.
The full readiness JSON records these values with `outcomes_read: false`.

The ledger prevents accidentally rerunning the outcome-reading entry point.
During evaluation, each method must return a permutation of the same input;
all full-population membership hashes must match the pre-label hash. Model
weights and inputs are rehashed afterward. The CLI blocks the classifier's
`fit` method for prepare/evaluate/verify stages. No test-driven model selection
or candidate update is performed.

## 4. Actual held-out results

The [saved aggregate result](phase10c_summary.json) is from the one frozen
evaluation. January label access began at **2026-11-09 13:23:52 UTC**, after the
**13:23:02 UTC** readiness freeze. The evaluation completed at **13:27:34 UTC**.
No model fit, feature/candidate update, threshold or seed change occurred.

### Population, candidates and coverage

| Quantity | Actual final value |
| --- | ---: |
| Eligible December-active customers | **370,154** |
| Unique candidates per customer, every method | **100** |
| Customer–candidate rows scored per method | **37,015,400** |
| Customers with January-window purchases | **4,947** |
| Eligible customers with no window purchase | **365,207** |
| Future-purchasing fraction of eligible customers | **1.3365%** |
| Distinct relevant purchased customer–product pairs | **48,915** |
| Relevant pairs retrieved in the candidate pools | **14,338** |
| Micro candidate recall ceiling | **29.31%** |
| Macro candidate recall ceiling | **32.04%** |
| Eligible-user list coverage / full top-20 coverage | **100% / 100%** |

All **4,947 purchasers** enter Recall/NDCG averages, including **1,121** whose
future purchases are entirely absent from their candidate lists. **3,826** have
at least one relevant candidate. This distinguishes mechanical 100% list
coverage from relevance coverage. Nonpurchasers remain in scoring and coverage.
Every eligible customer has prior-month personal history; empirical no-history
performance is not estimable from this cohort, and no new user cohort is added.

### Final ranking metrics

Macro Recall and NDCG give equal weight to each purchasing customer. Micro
Recall uses **all 48,915 relevant pairs**. Recall columns are percentages;
NDCG is on the 0–1 scale. Products absent from candidates remain in the metric
denominators. All three full-population candidate hashes match the pre-label
hash `9c3e9fa5…aa09c`.

| Ordering | K | Macro Recall@K | Micro Recall@K | Macro NDCG@K | Relevant pairs recovered |
| --- | ---: | ---: | ---: | ---: | ---: |
| Global popularity | 5 | 2.57% | 2.41% | 0.05421 | 1,180 |
| Global popularity | 10 | **4.08%** | **3.76%** | **0.05103** | 1,840 |
| Global popularity | 20 | 5.87% | 5.48% | 0.05460 | 2,679 |
| Personalized recency | 5 | 11.55% | 7.32% | 0.17321 | 3,581 |
| Personalized recency | 10 | **16.93%** | **12.13%** | **0.17971** | **5,931** |
| Personalized recency | 20 | 22.23% | 17.82% | 0.19480 | 8,717 |
| Frozen ML reranker | 5 | 13.69% | 9.31% | 0.22471 | 4,555 |
| Frozen ML reranker | 10 | **18.42%** | **13.98%** | **0.21625** | **6,840** |
| Frozen ML reranker | 20 | 22.69% | 18.85% | 0.22204 | 9,220 |

The ML reranker is numerically higher than recency at every reported cutoff
and metric. Both remain constrained by the same incomplete pools. A score is
a ranking margin, not a validated probability that the customer purchases.

### Paired ML-minus-recency differences

Use the prespecified **2,000-draw paired purchaser bootstrap**, unchanged seed
20261110, over the **4,947 purchasers**. Recall differences are **percentage
points**, not relative percentages. These are pointwise 95% intervals,
calculated from unrounded per-customer values rather than rounded table cells.

| Endpoint | Observed difference | 95% interval |
| --- | ---: | ---: |
| Macro Recall@5, secondary | +2.143 pp | [+1.786, +2.492] pp |
| Macro NDCG@5, secondary | +0.05150 | [+0.04589, +0.05690] |
| **Macro Recall@10, primary** | **+1.481 pp** | **[+1.137, +1.813] pp** |
| **Macro NDCG@10, primary** | **+0.03655** | **[+0.03218, +0.04056]** |
| Macro Recall@20, secondary | +0.454 pp | [+0.171, +0.729] pp |
| Macro NDCG@20, secondary | +0.02724 | [+0.02379, +0.03063] |

Both frozen primary intervals are wholly positive. **The final test supports
ML's advantage over personalized recency under this fixed-model,
purchaser-level bootstrap.** Secondary comparisons also have positive pointwise
intervals here; do not imply simultaneous significance for all six endpoints
or erase the declared limitations on user/product/time dependence.

At K=10, **4,832 relevant pairs** are recovered by both methods, **2,008 by ML
only**, and **1,099 by recency only**. Net additional recovery is therefore
**909 pairs**, not 2,008. Micro recall rises by **1.86 pp**. These are products
that were already observed to be purchased; they are not purchases or people
caused by presenting recommendations.

Purchaser-level Recall@10 improves for **841**, worsens for **391**, and is
unchanged for **3,715** customers. Average gains do not mean every customer
benefits. The practical magnitude is a modest +1.48 pp mean-user recall and
better early ordering; no financial or sales-value threshold was provided.

### Validation versus final test

Different snapshots have different users, basket sizes and periods. The table
compares the same frozen methods/metrics descriptively; it is **not a paired
statistical test of change between periods**.

| Measure | Validation: Dec 1 snapshot | Final: Jan 1 snapshot |
| --- | ---: | ---: |
| Eligible customers | 368,232 | 370,154 |
| Purchasers in metric averages | 5,693 | 4,947 |
| Relevant purchased pairs | 59,298 | 48,915 |
| Popularity macro Recall@10 | 4.22% | 4.08% |
| Recency macro Recall@10 | 16.75% | 16.93% |
| ML macro Recall@10 | 17.63% | 18.42% |
| Recency macro NDCG@10 | 0.17786 | 0.17971 |
| ML macro NDCG@10 | 0.20650 | 0.21625 |
| ML−recency macro Recall@10 | +0.882 pp [+0.529,+1.214] | +1.481 pp [+1.137,+1.813] |
| ML−recency NDCG@10 | +0.02864 [+0.02438,+0.03274] | +0.03655 [+0.03218,+0.04056] |
| Macro candidate recall ceiling | 32.37% | 32.04% |
| Micro candidate recall ceiling | 29.16% | 29.31% |

**The validation advantage generalized to the next held-out temporal cohort**:
the direction agrees and both final primary intervals exclude zero. The
observed final differences are larger, but no formal test establishes that
their magnitudes increased between months. Final secondary Recall@20 is
positive with a positive interval, whereas validation's interval crossed zero;
that is a different fixed-cohort finding, not a verification discrepancy or a
reason to change methods after looking at the test.

### Remaining retrieval and ranking limits

**34,577 of 48,915 relevant pairs (70.69%) are missing from the 100-candidate
pools**. A further **7,498 retrieved relevant pairs** sit outside ML's top ten.
Together they account for its **42,075 top-ten misses**. Retrieval absence and
ordering mistakes are separate problems: a stronger ordering model cannot
recover a product that is not a candidate. No candidate change is made here.

Large future baskets also limit top-K recall: the final purchaser's median
distinct future-product count is **7**, the 90th percentile **20**, and 99th
percentile **46**; **1,639 purchasers** buy more than ten distinct products.
Even perfect top-ten ordering cannot recover every product in those baskets.
These counts are diagnostics from the saved purchaser arrays, not a new
eligibility rule. Cold/window-cold products, sparse histories and unknown
stock/exposure further limit what the current past-only shortlist can retrieve.

### Computational performance

| Stage | Elapsed | Peak process RSS |
| --- | ---: | ---: |
| December history + full pre-label membership freeze | **28.89s** | **376.23MiB** |
| Final labels, all-candidate scoring, paired intervals and checks | **221.94s** | **266.77MiB** |

Total preparation plus final evaluation is **250.84 seconds (~4.18 minutes)**.
The stages run as separate processes; the maximum observed peak is
**394,510,336 bytes (~376.23MiB)**, not the sum of their peaks. The final
history database is **40,906,752 bytes (~39.01MiB)**.

DuckDB uses **256MB**, one thread and a **4GB temporary spill cap**, with
**1,000-customer batches**. NumPy/model/Python memory is additional to the
engine limit. The free-disk guard is 20GiB; about 129GiB free was observed
before preparation. Peak temporary spill was not measured. No full candidate
score table, pandas event table or new model weight file was materialized.
These local observations support use on this 8GB Mac, not a universal latency
or production-throughput guarantee. Verification/test/preflight replay costs
are separate from the measured final pass.

## 5. Reproducibility and verification plan

The existing 299 tests passed before preserving Phase 10B2B. Fourteen additional
synthetic tests pass before real final labels are accessed, including an
end-to-end export/verification run. They check December boundaries, customer
eligibility independent of future behavior, January end-exclusive labels,
purchase deduplication, authorization before label IO, exclusive access,
candidate hash stability, timestamp guards, all three universes, hand-counted
metrics/pairing, empty outcomes, unchanged-model enforcement, protocol tampering,
no training calls and verification that never reopens outcomes.

**All 313 tests pass, no skips.** Actual saved-evidence verification also passed:
model/input/code/protocol/artifact hashes match; every method used the frozen
candidate universe; purchaser hit counts and macro/micro metrics recompute;
paired differences and 95% intervals reproduce; and the unchanged model exactly
reproduces the saved inference margins. Verification did **not** reopen January
labels. The exclusive access ledger has one first-access entry only.

Earlier modules, both prior model freezes, all 82 recorded prior data/artifact
states, raw CSVs, original ML weights/arrays/feature databases, previous ranking
evidence, Phase 7 final artifacts and Phase 8 experiment aggregates remain
unchanged. No discrepancy in model configuration, candidate membership,
feature boundaries or metric reproduction was found. No exception/recovery or
new model fit was needed in this final evaluation.

Local paths under ignored `data/ranking/phase10c/` hold the history database,
access ledger, inference-check sample, purchaser-level metric arrays and a
completed checkpoint. Only aggregate report/JSON and source/tests belong in Git.
No full customer-level ranking or prediction file is exported. Source code and
protocol are fingerprinted before first label access and cannot change afterward.

Reproduce using the existing environment and persisted trained model:

```sh
LOKY_MAX_CPU_COUNT=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=src \
  .venv/bin/python -m growthlab.ranking_final prepare
# One outcome-reading evaluation, refuses a repeated first-access claim:
LOKY_MAX_CPU_COUNT=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=src \
  .venv/bin/python -m growthlab.ranking_final evaluate
# Subsequent reproduction uses saved evidence, not January outcomes:
LOKY_MAX_CPU_COUNT=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=src \
  .venv/bin/python -m growthlab.ranking_final verify
LOKY_MAX_CPU_COUNT=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=src \
  .venv/bin/python -m unittest discover -s tests -v
```

`verify` checks model, input/database, code/protocol and local artifact hashes;
recomputes macro/micro metrics and paired intervals from saved purchaser-level
arrays; and reproduces the saved inference margins using the unchanged model.
It does not read January outcomes. The trained weights remain deliberately
outside Git, so a source-only clone needs the existing local artifact; there
is no automatic retraining fallback.

No Streamlit, Docker, deployment or other module work is included.
Phase 10C remains uncommitted for review.

## 6. Conclusions and Decision Studio recommendation

**Recommend the existing validation-selected ML reranker as the offline
ranking method**, with personalized recency retained as a strong transparent
reference and simpler fallback. The held-out comparison supports the original
choice; it does not retune or replace the model based on the test. Do not
represent this result as proof of real-world sales improvement.

For the later Decision Studio, present this as a **REES46 offline ranking
study**, separate from customer purchase prediction and RetailHero's causal
experiment. Show the fixed calendar/cohort, all three methods, macro versus
micro metrics, the paired primary intervals and the shared candidate ceiling.
Distinguish 100% mechanical list coverage from relevant-product recovery, and
show that most relevant products are not retrieved. Do not label model margins
as purchase probabilities or translate the +1.48 pp ranking recall difference
into conversion uplift, SMS returns or causal revenue.

Observed future purchases reflect the shop's unknown exposure and availability
policy. We do not know what products were actually shown, what was in stock,
whether a missing purchase means dislike, or how recommendations would change
behavior. Same customer/product IDs can recur across months, so this is a
returning-customer temporal test, not unseen-person generalization. One retailer,
one final fortnight, possible unknown logging losses and conditional bootstrap
assumptions limit transport to new periods or shops. A prospective randomized
online experiment with appropriate exposure logging would be needed to assess
whether showing recommendations increases sales; none was conducted here.

Six new review files: `src/growthlab/ranking_final.py`,
`tests/test_ranking_final.py`, `docs/ranking/phase10c_protocol.json`,
`docs/ranking/phase10c_freeze.json`, `docs/ranking/phase10c_summary.json`, and this
report. Only these files are untracked; nothing is staged. HEAD remains the
pushed Phase 10B2B preservation commit. All local data/model/metric evidence is
ignored. **Stop after Phase 10C. No Phase 10C commit/push or application work.**
