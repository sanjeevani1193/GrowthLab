# Phase 10B1 — candidate generation and development coverage

Status: implementation and development evaluation complete, awaiting review;
**no ranking-model training**. Evaluation date: 2026-11-09.
Study: REES46 product retrieval, separate from customer-level Module 1 and
RetailHero. All amounts of coverage below concern observed purchases, not
preferences, impressions, causal purchase improvements or business revenue.

## 1. Phase 10A preservation and scope

Reviewed the four approved Phase 10A files, ran **243 tests successfully**, and
verified both earlier module freezes, all 82 recorded prior data/artifact states,
five raw CSV hashes, and the five cleaned Parquet fingerprints. Only source,
tests, report and aggregate findings were staged. No customer-level records,
datasets, caches, models or credentials were included.

Phase 10A was committed and pushed to `origin/main` as
**`7768444e73e7aaf2ad0ea6d81d97b03e55196dad`**. Local HEAD matched origin and the
tree was clean before Phase 10B1 began. Earlier files remain unchanged.

This phase adds candidate retrieval, not a learned reranker. It uses the
[Phase 10A design](phase10a_data_design.md), existing exact-row-deduplicated
events, and their recorded hashes. It never opens the January event partition
for ranking outcomes. No final-test labels, final candidate evaluation, tuning
of ranking models, data acquisition or dependency installation is included.

## 2. Frozen temporal and population contract

| Role | Past-only history | Prediction timestamp | Labels, end-exclusive |
| --- | --- | --- | --- |
| Training development | [Oct 1, Nov 1, 2019) | Nov 1, 2019 00:00 UTC | [Nov 1, Nov 15, 2019) |
| Validation development | [Nov 1, Dec 1, 2019) | Dec 1, 2019 00:00 UTC | [Dec 1, Dec 15, 2019) |
| Final test, reserved | [Dec 1, 2019, Jan 1, 2020) | Jan 1, 2020 00:00 UTC | **Not accessed** |

The final reserved outcome contract remains [Jan 1, Jan 15, 2020), from Phase
10A. Both `development_window` and the label reader reject a final-test request
before touching an outcome path. Main's only input partitions are October,
November and December. History queries reapply half-open timestamp boundaries
even though inputs are monthly partitions.

Eligible customers have at least one valid event in the preceding calendar
month; no future activity requirement is added. Their history lengths are a
calendar month (30 or 31 days), not Module 1's seven-day window. Valid positive
integer user/product keys are required. Future binary relevance is a **distinct
customer–product purchase pair** within fourteen days. Repeated purchase rows
do not multiply the label. Missing future purchases are not dislikes. Purchase
events retain their event-based definition regardless of unusual price.

Train and validation historical-user populations remain **399,664 and 368,232**;
their future purchasing customers are **6,027 and 5,693**, and relevant pairs
**66,018 and 59,298**. Window-cold products remain misses in the recall
denominator; they are not removed to make retrieval look better.

As Phase 10A noted, this is temporal returning-customer evaluation, not disjoint
user-ID generalization. Earlier full-period descriptive exploration and Module
1 used overlapping dates; the final ranking evaluation is reserved, not a
claim that no prior study ever read January data. This phase does not read it.

## 3. What counts as historical evidence

Reuse verified exact-row deduplication across the nine original decoded CSV
fields; do not overwrite immutable raw files or repeat the expensive cleaning.
For retrieval, then collapse all remaining actions to one row per user/product,
retaining latest event time, latest positive-action time and whether a historical
purchase exists. This second aggregation defines binary support; it does not
erase raw records or pretend that repeated actions never happened.

**Personal history** uses all four observed types: view, cart, purchase and
remove_from_cart. This preserves the Phase 10A recent-attention interpretation.
Removal is allowed to put a product into consideration; it is not declared
positive interest or explicit negative feedback.

**Graph evidence and seeds** use views, cart additions and purchases. Removal-only
user/product pairs do not create graph votes. No event-type numeric weights
are used: each distinct customer votes once for an item and once for a pair.
This avoids arbitrary claims that, for example, a cart is worth three views,
and prevents repeated clicks from dominating. These are fixed simple choices,
not weights optimized against final outcomes.

Products previously purchased remain eligible. The task permits repeat purchases
and Phase 10A found real repeat-product activity. There is no verified inventory
feed; eligibility means observed in the historical inputs, not confirmed stocked.
No brand, category text, impression, order identifier or negative rating is invented.

## 4. Four retrieval strategies and exact budgets

The [configuration](phase10b1_config.json) fixes budgets **50, 100, 150, 200**,
graph caps, thresholds and source order before the new development run. The
same customers, outcome pairs and catalog convention are used for every method.
Lists are deterministic and deduplicated; product ID breaks final ties.

**A. Global popularity:** rank by distinct historical purchasers per product,
then product ID. Each user contributes one buyer vote, even if multiple purchase
rows exist. Top B products are shared by all users.

**B. Personal history with popularity backfill:** rank the user's distinct
products by latest event time, then product ID. Return personal products first,
then append unseen products from the common popularity list until B is met.
The primary comparison explicitly includes this fallback. It is not a claim
that a one-event user has B personal products.

**C. Item-to-item with popularity backfill:** use at most ten recent positive
products as seeds, gather their graph neighbors, and take each target's maximum
similarity across seeds. Sort by maximum similarity, then maximum supporting
pair count across seeds, then product ID. Backfill short lists from the same
popularity list. A previously seen target is allowed; graph self-edges are not.

**D. Simple hybrid:** interleave personal, item-to-item and global lists, one
source rank at a time, in that fixed order. First occurrence wins; skip duplicate
products and continue until B unique candidates are obtained. This equal-source
round-robin avoids comparing incompatible raw score scales. It is a retrieval
priority, not a learned product ranking. Source order has a small tie advantage
and is fixed rather than tuned on outcomes.

For example (synthetic): personal [A,B], item [B,C], global [A,D,E] produce
hybrid [A,B,C,D,E]. Duplicate A/B entries consume no budget. At budget three,
the candidate set is {A,B,C}. No missing positive is injected later.

In the real data, the purchased catalog exceeds 200 products at both snapshots.
Thus every primary method returns **exactly B unique candidates per eligible
customer**. This is stronger than comparing methods with the same maximum but
different actual list lengths. Natural personal-only and item-only lists are
also reported **without backfill**, including their actual lengths/coverage;
those auxiliary lists are not called exact-budget fair comparisons.

### Cold-start and short histories

If a caller has no personal history or graph seeds, the reusable retrieval
function accepts empty lists and returns popularity. No fictitious personalized
signal is created. Removal-only users have personal attention history but no
positive graph seeds. New/window-cold products cannot enter through future
outcomes. Unknown users arriving after the batch snapshot are not added to the
evaluation cohort; their actual future behavior does not establish personalization
coverage. Phase 10A counted 7,600/7,245 future purchasers without history in the
train/validation history months; those scope limits still apply.

## 5. Bounded graph construction and a real example

For each snapshot independently:

1. Sort each customer's positive user/product pairs by latest positive action,
   then product ID, retaining **at most 50**. Long histories cannot emit an
   unbounded quadratic number of item pairs. Keep the first **10** as retrieval
   seeds. Repeat actions do not give repeated pair votes.
2. Count distinct-user support per item in these capped histories. Retain items
   supported by **at least 5** users. These degrees are capped-history counts,
   not the unrestricted lifetime audience or purchase counts.
3. Join capped histories **within a customer**, emitting only pairs A<B. At most
   50×49/2=**1,225 unordered votes per customer** can be emitted; filtering
   low-support items reduces this further. Group and retain pairs supported
   by **at least 3 distinct users**. These conservative engineering thresholds
   remove singleton links; they do not establish statistical significance.
4. Define binary cosine association:

   `similarity(A,B) = pair_users(A,B) / sqrt(item_users(A) × item_users(B))`.

   This adjusts raw shared-user counts for item audience sizes. It is not the
   probability of buying B, not an exposure-adjusted effect and not proof of
   semantic product similarity. Max-over-seeds favors one strong association;
   it deliberately avoids accumulating scores simply because a customer has
   many seeds. No additional learned weights or shrinkage are introduced.
5. Expand each retained pair in both directions, rank by similarity, support
   and target ID, retaining **50 outgoing neighbors per item**. The untruncated
   score is symmetric; per-item top-50 truncation can make the retained graph
   asymmetric. Self-edges are excluded, but seeds can be one another's neighbors.

**Real October example:** globally popular product `5854897` has **672 distinct
historical purchasers**. In the capped positive-interaction graph it has **1,764
users**. Product `5746635` has **323** capped users, with **120** shared users.
Their cosine is `120/sqrt(1764×323) = 0.1589756812`. Two other top neighbors are
`5693501` (126 shared users, cosine 0.1159001114) and `5835859` (77 shared users,
cosine 0.1101543242). More shared users need not mean higher normalized similarity.
These are catalog IDs, not names or independently verified complementary goods.

Popular products do not trigger an item×catalog cross join. Every graph edge
comes from bounded within-user item pairs, and outgoing lists are truncated.
At retrieval, each batch has ≤1,000 customers ×10 seeds ×50 neighbors =
**500,000 neighbor emissions before target deduplication**. Each user has at
most 200 retained item targets for all budget comparisons. High-degree products
can still receive many votes in graph aggregation; DuckDB groups those on disk.

## 6. Freeze before labels and reproducibility

The code first builds only historical tables, closes/checkpoints the local
database, and fingerprints that closed file, source code, configuration and
history partition. A local `*_retrieval_freeze.json` records that no labels have
yet been read. Then the same database is reopened **read-only**, and the
development label reader opens its one allowed later monthly partition.

Candidate membership is **frozen by the deterministic recipe and immutable
inputs**, not by storing a vast full candidate table. Lists are generated lazily
in bounded batches. `retrieve` has no label argument; history SQL and batch
neighbor queries have no label joins. Each customer's lists are generated before
its relevance set is consulted. After evaluation, the closed history database
must still match its freeze SHA-256. Source inputs are rehashed at the end.

This design avoids persisting hundreds of millions of candidate rows. Labels
are only a small dictionary of development purchasing users/distinct products,
not all events in pandas. Customer-level intermediate tables, freeze receipts
and databases stay in ignored `data/ranking/phase10b1/`.

Reproduce from the repository root:

```sh
PYTHONPATH=src .venv/bin/python -m growthlab.candidates
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

The CLI runs **train and validation only**. Re-running overwrites only this new
phase's local derived database and aggregate summary; it does not download data,
edit older artifacts or evaluate the reserved test.

## 7. How the coverage calculations work

For each eligible customer u, R(u) is the set of distinct observed future
purchased products, and C(u) is that method's candidate set at budget B.

- **Pair recall (micro):** sum |C∩R| / sum |R| over eligible customers. Each
  purchased pair gets equal weight. Relevant cold products and missed candidates
  stay in the denominator.
- **Mean user recall (macro):** mean |C∩R|/|R| over purchasing eligible users.
  Each purchasing customer gets equal weight, regardless of basket breadth.
- **Eligible-user coverage:** customers with any candidates / all eligible
  historical customers. Candidate mean and median use this same full population.
- **Purchasing-user candidate coverage:** purchasers receiving a nonempty list /
  eligible purchasers. This can be 100% even with poor relevance.
- **Purchasing-user hit rate:** purchasers with ≥1 recovered purchased product /
  eligible purchasers. This distinguishes having a list from having a relevant
  item in that list.

For example (synthetic), one user buys {A,B} and another buys {C}. If candidates
recover A only, pair recall is 1/3, mean user recall is (1/2+0)/2=1/4, and
purchasing-user hit rate is 1/2. A third nonpurchasing user remains in candidate
coverage and length calculations, not the undefined purchase-recall average.

We also evaluate equal-budget two-source ablations: personal+global,
item+global, and personal+item (with popularity filling any remaining shortfall).
The two-source lists interleave their named sources rather than using arbitrary
score weighting. These show the **net effect of adding a source at fixed budget**:
newly covered purchases can be offset by purchases displaced from the list.
Hybrid-minus-global complementary-hit and lost-hit counts make this visible.
Such source gains are conditional on this interleaving rule, not universal or
additive feature importance. They are not causal effects.

## 8. Actual results and recommendation

All numbers below are actual development aggregates from the
[saved summary](phase10b1_candidate_summary.json), not final-test results.

### Training: matched-budget purchased-pair recall

Denominator: **66,018 future purchased pairs**, from **6,027** purchasing users
within **399,664** eligible historical users. Each primary method returns the
same exact budget B per customer.

| Candidates per customer | Global | Personal + backfill | Item + backfill | Hybrid |
| --- | ---: | ---: | ---: | ---: |
| 50 | 6.93% | **25.90%** | 9.72% | 21.05% |
| 100 | 10.59% | **30.73%** | 13.88% | 28.71% |
| 150 | 13.32% | **33.50%** | 16.92% | 32.77% |
| 200 | 15.52% | 35.47% | 19.60% | **35.64%** |

### Validation: matched-budget purchased-pair recall

Denominator: **59,298 future purchased pairs**, from **5,693** purchasing users
within **368,232** eligible historical users.

| Candidates per customer | Global | Personal + backfill | Item + backfill | Hybrid |
| --- | ---: | ---: | ---: | ---: |
| 50 | 7.81% | **24.30%** | 10.03% | 20.79% |
| 100 | 11.13% | **29.16%** | 14.22% | 27.71% |
| 150 | 13.99% | **31.99%** | 17.43% | 31.72% |
| 200 | 16.04% | 34.01% | 20.00% | **34.49%** |

**Finding:** the simple personal-priority approach wins pair recall at 50, 100
and 150 in both months. The hybrid wins numerically at 200 in both, but the
validation margin over personal at 200 is only **286 pairs / 59,298 = 0.4823 pp**.
No interval/test was calculated to call that small difference statistically
established or a real future business improvement.

At budget 100, personal recovers **17,292 pairs**, versus global **6,600**, item
**8,434**, and hybrid **16,430**. Thus the best primary pair-recall comparison at
that equal budget is **29.16% versus 27.71%** for personal versus hybrid, not a
hybrid victory. Adding a source can displace more useful candidates.

### Coverage and purchasing-user results at budget 100

All primary methods have **100% eligible-user candidate coverage and 100%
purchasing-user candidate coverage**, in both snapshots at every tested budget.
Their average, median, minimum and maximum list lengths are all exactly B
(50/100/150/200). This is achieved partly by fallback and is not relevance.

| Snapshot / method | Purchased-pair hits | Mean purchasing-user recall | Purchasers with ≥1 hit | Purchasing-user hit rate |
| --- | ---: | ---: | ---: | ---: |
| Train global | 6,989 | 10.60% | 3,152 / 6,027 | 52.30% |
| Train personal + backfill | 20,286 | 33.47% | 4,696 / 6,027 | 77.92% |
| Train item + backfill | 9,166 | 18.47% | 3,512 / 6,027 | 58.27% |
| Train hybrid | 18,955 | 34.41% | 4,738 / 6,027 | 78.61% |
| Validation global | 6,600 | 11.72% | 2,933 / 5,693 | 51.52% |
| Validation personal + backfill | 17,292 | 32.37% | 4,314 / 5,693 | 75.78% |
| Validation item + backfill | 8,434 | 19.15% | 3,262 / 5,693 | 57.30% |
| Validation hybrid | 16,430 | **33.63%** | 4,386 / 5,693 | **77.04%** |

The hybrid reaches **more distinct purchasers** and has higher macro recall at
100 even though it retrieves fewer total purchased pairs. Pair recall weights
large baskets more. This tradeoff is real; the recommendation prioritizes the
requested recovery of purchased pairs plus simplicity. A later decision to
prioritize equal-user recall would be a different explicit objective, not a
reason to conceal this table.

### Natural source lists without backfill

These lists are capped at 100, but do **not** have matched actual lengths.

| Snapshot / natural source | Pair recall | Users receiving candidates | Purchasers receiving candidates | Mean / median candidates |
| --- | ---: | ---: | ---: | ---: |
| Train personal only | 25.45% | 100% | 100% | 5.00 / 1 |
| Train item only | 13.16% | 93.98% | 99.15% | 53.81 / 50 |
| Validation personal only | 23.36% | 100% | 100% | 6.01 / 1 |
| Validation item only | 13.51% | 96.73% | 99.56% | 59.87 / 50 |

Most users have very few recent personal products; a larger cap alone cannot
give them a full list. Graph retrieval reaches many users but has lower pair
recall than personal history. Potential explanations include noisy view-based
associations, the inability to infer unobserved intent, and truncation; this
comparison does not identify which explanation causes the gap.

### Incremental recovery at the same budget

All values below are **validation net pair-recall differences in percentage
points** using equal actual B. They include both additional hits and displacement.
H=personal, I=item, G=global; two-source variants interleave their named lists.

| Conditional source comparison | B=100 net gain | B=200 net gain |
| --- | ---: | ---: |
| H+G versus G: adding personal to global | +16.87 pp (+10,002 pairs) | +17.53 pp (+10,395 pairs) |
| I+G versus G: adding item to global | +5.64 pp (+3,342 pairs) | +7.01 pp (+4,157 pairs) |
| H+I+G versus I+G: adding personal to item/global | +10.94 pp (+6,488 pairs) | +11.43 pp (+6,780 pairs) |
| H+I+G versus H+G: adding item to personal/global | **−0.29 pp (−172 pairs)** | **+0.91 pp (+542 pairs)** |
| H+I+G versus H+I with G fallback: promote global from fallback to interleaved source | +0.68 pp (+406 pairs) | +1.82 pp (+1,080 pairs) |

The last row is **not** a complete removal of global products: H+I retains G
as backfill to preserve the budget. It measures promoting G into regular
interleaving. The positive G-only comparison and the other rows are separate,
conditional contrasts, not additive source credit.

A concrete validation accounting example at B=100: hybrid retrieves **11,517
purchased pairs absent from global's list**, but loses **1,687 pairs global
would retrieve**. Net = 9,830 additional pairs, or **16.58 pp** above global.
That explains 27.71% versus 11.13%; reporting only the 11,517 additions would
overstate the gain. The summary also retains these counts for train and all B.

### Graph sizes and measured computational cost

| Snapshot | Capped positive pairs | Graph products (≥5 users) | Supported unordered edges (≥3 users) | Retained directed neighbors | Pair-vote emissions |
| --- | ---: | ---: | ---: | ---: | ---: |
| Train | 1,732,577 | 32,958 | 1,030,606 | 639,049 | 18,254,061 |
| Validation | 1,894,706 | 32,711 | 1,241,094 | 708,131 | 21,458,216 |

Both observed maximum graph histories and neighbor lists equal the declared
50 cap. Emissions above are construction votes before grouping, not saved
customer-level candidate rows and not independent observations.

The configuration uses **512MB DuckDB memory limit, one thread, 4GB spill cap,
and 1,000-user batches**, with a 20GiB free-disk guard. About 129GiB free disk
was observed during this run. Engine memory is not whole-process memory.

| Snapshot | Historical source/graph preparation | Candidate generation, all methods/ablations | Coverage calculations | Total elapsed | Process peak RSS | Local database |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Train | 5.80s | 116.38s | 56.32s | **179.79s** | 531.98MiB | 94.51MiB |
| Validation | 7.57s | 123.56s | 59.04s | **191.36s** | 575.00MiB | 104.51MiB |

Combined elapsed is **371.15 seconds (~6.19 minutes)**; peak process RSS is
**602,931,200 bytes (575MiB)**. `getrusage` peaks are cumulative in the same
process; the validation row is not an isolated fresh-process memory benchmark.
Source SQL and the graph are shared by the comparison, and timings include
all seven methods, four budgets and natural-source diagnostics. No isolated
per-method RSS/runtime experiment was run, so do not interpret the shared cost
as what global popularity alone would require. Graph-free personal/global
retrieval avoids the item graph and neighbor query costs in a later pipeline.
Peak temporary spill was not measured; the 4GB cap was enforced.

At B=100, the validation population corresponds to **36,823,200 candidate rows
per method** if fully materialized; B=200 would double that to **73,646,400**.
Here lists are discarded after bounded-batch aggregate evaluation. No complete
per-method candidate table or hundreds-of-millions-row union was written.
The largest bounded pre-aggregation neighbor expansion is 500,000 rows/batch,
and retained source lists are ≤200 per user. Graph/history intermediates remain
small local ignored databases, not committed artifacts.

### Recommended configuration for subsequent ranking work

Use **personal history, latest-event order, with distinct-buyer popularity
backfill to exactly 100 products**, previous-calendar-month history, keeping
previous purchases eligible. This is B above, not the three-source hybrid.
It gives **29.16% validation pair recall**, 100% list coverage, and a simpler
history-only recipe without needing the graph. It also leads at B=100 on train.
Its 29.16% is a **retrieval ceiling**, not a learned ranker's Recall@10.

The best numerical pair recall among all tested configurations is hybrid B=200
at **34.49%**, but it doubles the per-user reranking workload relative to B=100
and improves on personal B=200 by only 0.48 pp. Within personal retrieval,
increasing B=100→150 gives +2.83 pp for 50% more candidates; 150→200 gives
+2.02 pp for another 33% increase. The 100 choice is a practical initial
coverage/complexity compromise, not a discovered optimum. If equal-user recall
or broader coverage becomes the primary goal, revisit the documented tradeoff
on development only before freezing the final ranking approach.

Do not attribute the increase from Phase 10A's **26.58%** to item-to-item
retrieval. That earlier pool was 50 globals + ≤50 personal, with only **55.02
average candidates**. The recommended new personal-priority B=100 allows up to
100 personal products and always fills 100 slots. Different actual list size
and source priorities explain why those numbers are not a matched ablation.

Roughly 71% of relevant pairs are still missed by the recommended retrieval.
A complex reranker cannot fix those misses. This is a cautious baseline to
understand ordering performance, not evidence that retrieval is solved or that
an online recommendation system will increase purchasing.

## 9. Limitations and Phase 10B2 boundary

Shortlists cover logged future purchases under the shop's unknown exposure
policy. There are no impression logs, explicit negative preferences, stock
availability or randomized recommendation assignments. A co-occurrence link
can reflect popularity, browsing flows or shared baskets rather than preference.
Binary support, history/seed caps, item/pair thresholds and top-50 neighbor
truncation lose some long-tail information. No threshold grid is tuned here.
Cold-product purchases remain unreachable; unknown users receive generic fallback.

One train and one validation month cannot establish future-season reliability.
All compared candidate budgets/rules use validation, so their best validation
result is a development choice, not an independent performance estimate.
Exact backfill improves mechanical list coverage without proving personalization.
More candidates are not inherently better: compare recall at the same B and
consider reranking cost. The known January 22 gap remains outside proposed final
labels; it does not prove logging is otherwise complete.

Phase 10B2 is only a proposal: freeze the selected retrieval recipe, construct
past-only customer/item features in batches, compare global ordering with a
simple personalized ordering on **identical candidate sets**, and consider a
lightweight scorer only if justified. Do not inject missed positive labels into
evaluation candidates or treat sampled training nonpurchases as dislikes.
Do not evaluate January outcomes until the ranking approach is selected and
its final evaluation protocol is approved.

**Stop after Phase 10B1. No ranking model, dashboard, deployment, unrelated
development, Phase 10B1 commit or push is included.**

## 10. Verification and files for review

The full suite passes **262 tests, no skips**: all 243 prior tests plus **19 new
focused tests**. New checks exercise hand-counted co-occurrence votes/cosines,
repeat-action aggregation, history-start/prediction/outcome boundaries,
removal-only histories, history/seed/neighbor bounds, stable output under input
reordering, source interleaving/deduplication, exact list budgets, unknown-user
and insufficient-catalog behavior, final-test rejection, recall denominators,
full batch evaluation and identical metrics across customer batch sizes.

An independent Python reconstruction checked **24 actual history-only customers**
(12 per snapshot) against SQL personal/item retrieval and exact budget limits.
Ten actual graph edges matched independently counted shared-user sets and cosine
scores. Only aggregate verification counts were retained; no customer IDs or
histories were exported. These are focused cross-checks, not a claim that every
customer was independently reimplemented in Python.

Final aggregate checks also passed: populations reconcile to Phase 10A;
every primary list has the exact requested budget; hit counts are monotone
across nested budgets; complementary hits minus lost hits equals the matched
hybrid/global difference; both retrieval databases still match their pre-label
freeze hashes; all three input partitions and source/config fingerprints match.
Both previous module freezes, 82 prior artifact states, raw CSV hashes, Phase 7
final artifacts/figures and Phase 8 experiment input/aggregate hashes remain
unchanged. No final-test outcome query or January input partition is present.

New Phase 10B1 review files:

- [`candidates.py`](../../src/growthlab/candidates.py)
- [`test_candidates.py`](../../tests/test_candidates.py)
- [`phase10b1_config.json`](phase10b1_config.json)
- [`phase10b1_candidate_summary.json`](phase10b1_candidate_summary.json)
- This report: `phase10b1_candidate_generation.md`.

The summary contains aggregate metrics, histograms of list lengths, graph sizes,
resource observations and fingerprints, never customer-level candidates or
predictions. All large/local derived tables and freeze receipts stay under the
existing ignored data path. No earlier source, report, dependency or model is
changed. Phase 10B1 remains uncommitted and unstaged for review.
