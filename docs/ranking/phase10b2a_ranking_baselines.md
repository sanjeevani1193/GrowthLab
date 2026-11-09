# Phase 10B2A — fixed-candidate product ranking baselines

Status: baseline implementation and development evaluation complete, awaiting
review; **no ML training**. Evaluation date: 2026-11-09.
Study: REES46 product ranking, separate from Module 1 purchase prediction and
RetailHero causal/uplift analysis. This report evaluates ordering of observed
future purchased products, not causal purchase gains or customer preferences.

## 1. Preservation and frozen decisions

Reviewed the five approved Phase 10B1 files and ran **all 262 tests successfully**.
Both previous module freezes, all 82 recorded prior data/artifact states, raw
CSV and cleaned input hashes, both history databases and source/config hashes
passed checks. Only the five reviewed source, test, configuration, aggregate
summary and report files were staged; no raw data, customer records, model,
prediction file, cache, large artifact or credential was included.

Phase 10B1 was committed and pushed as
**`39e050e77ef44c92ba8bc5ba121bea36a7390b7d`**. HEAD matched `origin/main` and Git
was clean before this phase began. No earlier module is modified here.

The selected retrieval remains **personal history + popularity backfill,
100 products**, exactly as approved. Both methods receive each customer's
**same candidate set**. There is no candidate-source or budget change after
ranking results. The [frozen protocol](phase10b2a_protocol.json) defines the
ordering, tie rules, K values and metric denominators before evaluation.
No interaction-type weights, fitted parameters or ranking thresholds are used.

Primary development comparison: **validation mean-per-purchasing-customer
Recall@10 and NDCG@10**, reporting any disagreement rather than changing the
rules. Micro purchased-pair recall is a separately labeled secondary view.
This differs from silently choosing the averaging convention that looks best.

## 2. Temporal and eligibility contract

| Snapshot | Historical inputs, UTC | Prediction time | Observed purchase labels, UTC |
| --- | --- | --- | --- |
| Train development | [Oct 1, Nov 1, 2019) | Nov 1, 2019 00:00 | [Nov 1, Nov 15, 2019) |
| Validation development | [Nov 1, Dec 1, 2019) | Dec 1, 2019 00:00 | [Dec 1, Dec 15, 2019) |
| Reserved final test | [Dec 1, 2019, Jan 1, 2020) | Jan 1, 2020 00:00 | **Not accessed** |

All intervals are start-inclusive, end-exclusive. The final reserved label
contract remains [Jan 1, Jan 15, 2020); no January partition is opened by this
ranking program. The shared development-window and label-reader functions
reject final-test requests before accessing an outcome path.

Eligible customers have at least one valid historical interaction in the
previous calendar month. Keep nonpurchasers in scoring/coverage. Do not add
customers based on later purchases or drop them because their shortlist misses
the outcome. Future relevance is one binary label per distinct customer/product
purchased within fourteen days, regardless of repeated purchase rows or price.
These product purchase events are not verified fulfilled orders or ratings.

Events exactly at prediction time cannot create history. Events exactly at the
label end cannot create relevance. The previous-month windows are 30/31 days,
not Module 1's seven-day history. The known January 22 logging gap falls outside
these development windows and the reserved final label contract. Unknown
logging loss and prior project exploration of overlapping dates remain limitations.

## 3. Retrieval is frozen and shared

Reuses the prior read-only local history databases, rather than repeating CSV
cleaning or graph construction. Their full SHA-256 hashes must match Phase 10B1.
Historical tables contain one row per customer/product, latest event time,
latest positive-action time and whether a past purchase occurred.

For each customer:

1. Take the first 100 historical products ordered by **latest event descending,
   product ID ascending**. Event types are view, cart, purchase and cart removal,
   preserving the selected retrieval definition.
2. Append unseen products from the historical distinct-buyer popularity list,
   with product ID breaking popularity ties.
3. Deduplicate and stop at 100. In this real dataset the historical purchased
   catalog can fill every list. Previously purchased products remain eligible.

The program calls the unchanged Phase 10B1 `priority_with_fallback` helper.
Using only the first 100 entries of the stored 200-entry source lists produces
the same selected 100-product set; no graph/item-to-item retrieval is used.
Retrieval order is not automatically the final display order.

Before reading each development label window, the program makes a **complete
pass over all eligible users**, hashing the sorted candidate IDs with their user
keys and verifying exactly 100 unique products. A local freeze receipt records
that hash, code/protocol hashes and the old database hash. Customer-level lists
are not persisted.

During evaluation, candidates are generated once per customer and passed to
both ordering methods. Each output must be an exact permutation of the input.
Canonical membership hashes for **both methods and retrieval** must equal the
pre-label freeze hash. Thus candidate equality is checked for the full population,
not assumed from matching recall numbers or checked only on a sample.

## 4. Precisely defined baseline scores

### A. Global popularity ordering within the frozen set

For a product p, `buyers(p)` is the number of distinct customers with a purchase
of p during the historical month. Repeated rows or purchases by one customer
count once. Its score is that integer buyer count. Sort the customer's candidate
products by **buyer count descending, product ID ascending**. A product with no
past purchase has score zero.

Buyer counts are calculated from **all past historical products**, not only
the prior top-200 popularity list: some personal-history candidates lie outside
that list but still have real historical buyers. Treating those counts as zero
would incorrectly penalize them. This lookup never uses future purchases.

Real historical example from October: products `5854897`, `5700037`, and
`5751422` have **672, 671, and 619** distinct purchasers. If present in the same
candidate list, global popularity orders them in that sequence. The counts are
not personalized probabilities or estimates of future purchases.

This baseline is **global scoring on a customer-specific candidate set**, not
the unrestricted global top-100 retrieval baseline from Phase 10B1. Its
top-K items can differ across customers because their candidate sets differ.

### B. Personalized recency ordering within the same set

Sort lexicographically by:

1. A personally interacted product ahead of one with no personal interaction.
2. **Latest historical event timestamp descending** among personal products.
3. Historical distinct-buyer count descending for timestamp ties.
4. Product ID ascending for the remaining ties.

Products with no personal history use popularity then ID. All four historical
event types can set recency, including removal, exactly as predeclared. This is
a simple recent-attention baseline; a removal is not claimed to be positive
intent, and counts are not converted to weighted preference scores. Recency
is not a fitted purchase probability. Type-sensitive alternatives would need
a separately approved future comparison, not a change after these results.

Internally the sort key is `(no_personal_history, -latest_UTC_microseconds,
-past_buyers, product_id)`; absent-history products have a constant timestamp
key so their fallback is purely popularity. Timestamp integers are computed
without local-time/DST conversions or float rounding.

**Synthetic example:** candidates are [A,B,C]. A has 10 historical buyers,
B has 5, C has none. The customer recently interacted with C only. Popularity
orders [A,B,C]; recency orders [C,A,B]. Both return exactly the same three
products. Changing order can improve top-K recovery without changing the
candidate recall ceiling. No future relevance is consulted by either sort.

## 5. Metric definitions and worked calculations

Evaluate K=**5, 10, 20**. Let R be the customer's full set of distinct future
purchased products, and L the first K ranked candidates.

**Per-customer Recall@K** = `|L ∩ R| / |R|`.
The primary macro average gives each purchasing eligible customer equal weight.
**Micro Recall@K** = total recovered purchased pairs / total relevant purchased
pairs across those same users. It gives more weight to customers buying many
distinct products. Both are reported explicitly.

**NDCG@K**, with binary gains:

```
DCG@K  = sum(relevant_at_rank_i / log2(i+1)), for ranks i=1..K
IDCG@K = sum(1 / log2(i+1)), for i=1..min(K, |R|)
NDCG@K = DCG@K / IDCG@K
```

Average NDCG per purchasing customer. The ideal denominator uses **all future
purchased products**, including ones outside the candidates, rather than only
retrieved positives. Thus perfect ordering of an incomplete pool need not give
NDCG=1. Ranking scores are strictly ordered by the frozen tie rules; there are
no unresolved score ties requiring averaged permutations.

**Synthetic hand example:** R={A,B}, and the top three are [X,A,Y]. Recall@3=1/2.
DCG=1/log2(3)=0.63093; ideal=1+1/log2(3)=1.63093; NDCG@3≈**0.38685**. A at rank
one improves NDCG, but B remains a miss. For two purchasers with relevant sets
{A,B} and {C}, recovering A only gives macro recall=(1/2+0)/2=**25%**, while
micro recall=1/3=**33.33%**. They are not interchangeable statistics.

**Candidate recall ceiling:** replace L with all 100 candidate products. Report
both its macro and micro versions. A reranker cannot recover an absent product.
Recall@K cannot exceed its corresponding ceiling. The NDCG denominator likewise
does not excuse retrieval misses.

Customers with R empty have undefined purchase recall/NDCG, so they do not
enter those means. They **still receive both rankings** and remain in coverage.
Coverage means the percentage of eligible customers receiving a list (and a
full top-20); it is not the fraction buying or finding the list useful.

## 6. Development results

Actual aggregates are in [phase10b2a_summary.json](phase10b2a_summary.json).
The membership hashes for retrieval and both methods agree for **every**
historical customer, and both candidate-hit counts reconcile to Phase 10B1.

| Snapshot | Eligible customers scored by both methods | Future purchasers in metric averages | Relevant purchased pairs | Candidate hits | Micro candidate ceiling | Macro candidate ceiling |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Train | 399,664 | 6,027 | 66,018 | 20,286 | **30.73%** | **33.47%** |
| Validation | 368,232 | 5,693 | 59,298 | 17,292 | **29.16%** | **32.37%** |

Every scored customer receives **100 unique candidates** and full top-5,
top-10 and top-20 lists under both methods. Eligible-user coverage is **100%**
in both snapshots. This says nothing about satisfaction or whether a customer
purchases. The 393,637 train and 362,539 validation customers with no future
purchase remain in coverage and are excluded only from undefined purchase
Recall/NDCG means.

### Training ranking metrics

Recall columns are percentages; NDCG is on the **0–1** scale. Macro Recall and
NDCG are averages across the same 6,027 purchasing customers. Micro Recall
divides the hit count by the same 66,018 relevant pairs.

| Ordering | K | Macro Recall@K | Micro Recall@K | Macro NDCG@K | Purchased-pair hits |
| --- | ---: | ---: | ---: | ---: | ---: |
| Popularity | 5 | 1.68% | 1.75% | 0.03999 | 1,158 |
| Popularity | 10 | 3.04% | 3.11% | 0.03992 | 2,055 |
| Popularity | 20 | 5.32% | 5.43% | 0.04545 | 3,586 |
| Personalized recency | 5 | 11.49% | 6.77% | 0.17718 | 4,467 |
| Personalized recency | 10 | **16.95%** | **11.45%** | **0.18500** | 7,562 |
| Personalized recency | 20 | 23.13% | 17.81% | 0.20255 | 11,756 |

### Validation ranking metrics

Macro means use the same **5,693 purchasers**; micro recall uses the same
**59,298 relevant pairs** for both methods. Products outside the frozen pool
remain in those denominators.

| Ordering | K | Macro Recall@K | Micro Recall@K | Macro NDCG@K | Purchased-pair hits |
| --- | ---: | ---: | ---: | ---: | ---: |
| Popularity | 5 | 2.69% | 2.41% | 0.05868 | 1,427 |
| Popularity | 10 | **4.22%** | **3.94%** | **0.05624** | 2,338 |
| Popularity | 20 | 6.13% | 5.97% | 0.05927 | 3,542 |
| Personalized recency | 5 | 11.55% | 6.68% | 0.16993 | 3,964 |
| Personalized recency | 10 | **16.75%** | **11.11%** | **0.17786** | 6,587 |
| Personalized recency | 20 | 22.19% | 16.77% | 0.19368 | 9,942 |

On the prespecified validation comparison, recency exceeds popularity by
**12.53 percentage points macro Recall@10**, **7.17 pp micro Recall@10**, and
**0.12162 NDCG@10**. At K=10, it retrieves **6,587 versus 2,338** observed
purchased pairs. It is numerically higher for every reported K and metric in
both development snapshots. No confidence interval/significance test was run;
these are observed development differences, not established online benefits.

Higher macro than micro recency recall means the equal-user result is more
favorable than the item-weighted result. Customers purchasing many distinct
products contribute proportionally more to micro recall, and their large
future baskets can exceed the top-K list. Both views should remain visible.

NDCG need not increase with K: its ideal denominator also grows. For example,
validation popularity NDCG@5 is 0.05868 while NDCG@10 is 0.05624. This is not a
hit-count inconsistency; Recall@K/hits are monotone, while normalized ranking
quality can decrease when additional ranks fail to match the growing ideal.

### Recommendation

Use **personalized recency as the main baseline for a future ML reranker**,
retaining popularity as a simpler reference. It leads on both frozen primary
validation metrics and the training comparison. Do not compare an ML model
only against the much weaker popularity ordering and call that sufficient.

At validation K=20, recency recovers only **16.77% of all purchased pairs**;
the candidate ceiling is still 29.16%. Better ordering could recover more of
the shortlisted positives, but cannot recover products absent from the pool.
No recommendation is made to change retrieval from these ranking results.
No coefficients, interaction-type weights or tie rules were tuned after evaluation.

### Measured resource use

| Snapshot | Full pre-label membership freeze | Evaluation of both orderings | Total elapsed | Peak process RSS |
| --- | ---: | ---: | ---: | ---: |
| Train | 25.06s | 65.01s | **91.39s** | **160.47MiB** |
| Validation | 19.24s | 57.35s | **77.42s** | **194.19MiB** |

Combined elapsed is **168.81 seconds (~2.81 minutes)**. Maximum measured RSS is
**203,620,352 bytes (~194.19MiB)**. Memory readings are cumulative process peaks
on this Mac, not isolated per-method benchmarks. Both methods share retrieval,
historical lookups, hashing and metric evaluation. No separate per-ordering
runtime or peak-memory experiment was performed; the table reports the actual
combined local workload. Engine limits remain 512MB, one thread and 4GB spill;
peak temporary spill usage was not measured. About 127GiB free disk was observed.

No new full event table, graph, score database, candidate dataset or customer-level
ranked output was written. Only two small local freeze receipts and the aggregate
summary were added. Existing databases remain unchanged. Local measurements
support feasibility on this 8GB Mac, not a universal performance guarantee.

## 7. Cold-start interpretation

The cohort requires historical activity. Therefore every eligible customer has
some personal history; the observed **without-personal-history subgroup has
zero customers** in each snapshot. Its Recall/NDCG are **null/not estimable**,
not zero, and no cold-start empirical performance is claimed. The with-history
results equal the full-cohort results by construction.

For a truly empty history supplied to the reusable ordering function, both
baselines reduce to the same historical popularity order. Synthetic tests check
that behavior. This does not establish performance for real new arrivals.
Including later-arriving/window-cold users based on their purchases would change
the selected cohort and create a misleading comparison; it is not done here.
Phase 10A's counts of future purchasers without prior-month history remain a
scope warning rather than customers silently added to evaluation.

## 8. Implementation, tests and reproducibility

[`ranking_baselines.py`](../../src/growthlab/ranking_baselines.py) performs these
reviewable steps:

1. Verify the previous candidate source, summary, history databases and allowed
   development label partition fingerprints. Require 20GiB free disk.
2. Open each existing history database **read-only**, with a **512MB DuckDB
   memory limit, one thread, 4GB spill cap** and **1,000-customer batches**.
3. Reuse the fixed candidate sources, join only historical timestamps, and
   reject any timestamp outside the declared past window.
4. Freeze complete candidate membership before labels, with protocol/source
   fingerprints. Receipt files stay under ignored `data/ranking/phase10b2a/`.
5. Load only train/validation binary purchase labels with the unchanged shared
   label reader. Do not read January outcomes or build a final-test ranking.
6. Generate one candidate list, create its two fixed permutations, and accumulate
   aggregate metrics. Keep all customers for coverage, with label denominators
   confined to purchasers. Check all membership hashes against the pre-label
   freeze and reconcile candidate hits with Phase 10B1.
7. Rehash the old databases and label partitions afterward. Save only aggregate
   summaries; customer IDs, ranked lists and prediction files are not exported.

No graph is rebuilt, no full raw/event table is loaded into pandas, and no full
customer×candidate score table is materialized. Both methods score the same
eligible users and keep all missed relevant products in the denominators.

Reproduce from the repository root:

```sh
PYTHONPATH=src .venv/bin/python -m growthlab.ranking_baselines
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

**All 280 tests pass, no skips:** the 262 preserved tests plus **18 new tests**.
New checks cover identical candidate universes, exact budget and deduplication,
unchanged retrieval membership, timestamp bounds, final-test rejection,
deterministic input-order-independent sorting, popularity and recency ties,
empty-history fallback, hand-calculated Recall/NDCG, unreachable relevance in
IDCG, undefined empty-outcome metrics, macro/micro differences, pre-label
membership hashes and unchanged candidate membership under different labels.

A separate independent check reconstructed **all 6,027 train and all 5,693
validation purchasing customers directly from the cleaned monthly event files**,
rather than the stored customer/product history tables. It rebuilt latest-event
histories, distinct-buyer counts, the candidate sets and both orderings with
native timestamp stable sorts. Recall was counted from set intersections and
NDCG discounts summed over relevant-product positions without calling the new
ranking/metric helpers. Candidate hits and every reported Recall/NDCG aggregate
agreed (floating-point means within 1e-12). This verifies purchaser metrics;
full-population scoring/coverage and identical universes are separately checked
by the complete pre-label and per-method membership hashes. No customer details
were exported by the reference calculation.

## 9. Limitations and stopping point

These are observed development ranking metrics under the shop's unknown
exposure policy. We have no verified impressions, stock, explicit dislikes,
fulfilled order IDs or causal recommendation assignments. Missing labels do
not prove disinterest. All-row exact deduplication and the existing missing,
price/session/catalog and logging warnings remain applicable. Scoring and
retrieval use behavior only, not unverified monetary profit assumptions.

Recency may favor already bought, stale or removed items. Popularity may
overemphasize a small catalog subset and ignore specific interests. The selected
pool remains incomplete, and no ordering can fix missing candidates. One train
and one validation snapshot, recurring customer IDs and prior development
selection limit generalization. Offline differences are not causal purchase
increases, and no significance claim is made without an appropriate paired
uncertainty analysis.

An eventual ML reranker must be compared on these **same frozen candidate sets**
and denominators. Fit only from training labels, select on validation, then
freeze the entire approach before any approved January final-test evaluation.
No ML training, candidate-rule change, dashboard, Docker, deployment, unrelated
module, commit or push of Phase 10B2A occurs here.

New review files: `src/growthlab/ranking_baselines.py`,
`tests/test_ranking_baselines.py`, `docs/ranking/phase10b2a_protocol.json`,
`docs/ranking/phase10b2a_summary.json`, and this report. Earlier tracked files
remain unchanged; all Phase 10B2A files remain unstaged and uncommitted.

**Stop after Phase 10B2A for review.**
