# Phase 5 — RetailHero experiment audit and training-cohort analysis

Status: completed locally for review on 2026-11-05. No Phase 5 commit or push. No response or uplift models fitted. Module 1 remains at `6f92c31`; its implementation, data, frozen models, and reported metrics are preserved.

## Finding and business interpretation

In our frozen **training cohort**, customers marked as contacted purchased more often:

| Arm | Customers | Purchasers | Purchase rate |
| --- | ---: | ---: | ---: |
| Control (`treatment_flg=0`) | 60,034 | 36,174 | 60.2559% |
| Communication (`treatment_flg=1`) | 59,988 | 38,180 | 63.6461% |

The unadjusted difference is **+3.3902 percentage points**, with a **95% Newcombe/Wilson interval of +2.8411 to +3.9391 points**. The two-sided pooled two-proportion test gives **z=12.0957, p=1.1135×10⁻³³**. Under the experimental assumptions below, contacting 1,000 comparable customers instead of contacting none would produce an estimated **33.90 additional purchasers**, with interval **28.41–39.39**.

This counts people with at least one purchase, not additional transactions or revenue. No contact cost, margin, revenue effect, or profit is estimated. The interval excludes zero by a substantial margin under the stated independent-customer analysis. Statistical significance does not establish that assignment was random or that the effect transports to another campaign.

A positive average difference does not imply that every customer benefits. Some would purchase either way, some may respond only to contact, and some could be discouraged. We observe one outcome per person, so we cannot identify each person's two potential outcomes from these records.

## Source, provenance, attribution, and usage uncertainty

The [official ODS.AI RetailHero data page](https://ods.ai/competitions/x5-retailhero-uplift-modeling/data) supplied the data. The [competition description](https://ods.ai/competitions/x5-retailhero-uplift-modeling) identifies advertising SMS as the intervention. Attribution: **X5 Retail Group / RetailHero, hosted by ODS.AI**.

The official page links to [retailhero-uplift.zip](https://storage.yandexcloud.net/datasouls-ods/materials/9c6913e5/retailhero-uplift.zip), observed size **625,190,754 bytes**. We used HTTP byte ranges to extract only the two requested complete data members, sequentially, with ZIP CRC verification. Initial acquisition transferred **8,822,004 bytes**, including ZIP directory/header reads and small supplied documentation. The complete archive, competition test labels, products, and purchase history were not downloaded.

| Official member | Expanded bytes | Compressed member bytes | Local SHA-256 |
| --- | ---: | ---: | --- |
| `data/uplift_train.csv` | 3,000,616 | 1,181,714 | `ae3dc4c17e98426fa4233fa03421328d259b8720e56ad0380b260ca2edd19bd4` |
| `data/clients.csv` | 21,736,219 | 7,637,725 | `0135e7a3dfb2174c0fff4033cc895c070794e3c19bf5a6b2a685f4acde32e7ba` |

The [PyTorch-Lifestream mirror](https://huggingface.co/datasets/pytorch-lifestream/retailhero-uplift) was inspected as a fallback, at revision `7744156a4f89f4828607921e8c9668f04801f4de`. Its file listing and small description/baseline were inspected; **its data files were not used**. The official source was accessible and preferred. Official and mirror compression formats differ; their compressed-file checksums should not be compared as though they were identical files.

No explicit dataset reuse license was found in the inspected official data page, official README, or mirrored dataset card. Public accessibility and attribution do not grant unrestricted redistribution or commercial rights. This analysis keeps data local and does not assert a permissive license. Obtain clarification before redistributing data or using it commercially. The dataset's rights are separate from software licenses.

Machine-readable provenance is in [acquisition.json](phase5/acquisition.json). Raw data are under ignored `data/retailhero/raw/`; source-page snapshots and source documentation are ignored under `data/retailhero/source/`.

## Row grain, schema, and timing

One `uplift_train.csv` row is one labeled experimental customer, with one communication indicator and one binary subsequent-purchase outcome. One `clients.csv` row is one customer profile. The labeled competition training file becomes our source experimental population; it is split again for our own evaluation. The official competition `uplift_test` has no observed outcomes for our evaluation and is not used.

CSV has no inherent physical type. The audit initially reads **all columns as VARCHAR**, preserving identifier strings and allowing invalid values to be reported before casting. These are the verified analytical types:

| File | Column | Analytical type and meaning |
| --- | --- | --- |
| uplift_train | `client_id` | VARCHAR, ten-character hexadecimal identifier; join/split key only |
| uplift_train | `treatment_flg` | INTEGER, valid values 0/1; communication recorded as performed |
| uplift_train | `target` | INTEGER, valid values 0/1; purchase afterward |
| clients | `client_id` | VARCHAR, same join key |
| clients | `first_issue_date` | Parses as TIMESTAMP, first card-issue date by field interpretation |
| clients | `first_redeem_date` | Nullable TIMESTAMP, first redemption date by field interpretation |
| clients | `age` | Parses as INTEGER, with implausible values described below |
| clients | `gender` | VARCHAR, observed categories F/M/U; U is treated as unknown |

The exact campaign date, time zone, outcome horizon, delivery/open status, and profile snapshot time are **not documented in the inspected source**. These are not REES46's 7/30-day windows. The source calls purchases historical and preceding communication, but that does not establish that every field in `clients` was captured before treatment. Age/gender are plausible baseline covariates, conditional on snapshot confirmation. Card-issue time is a plausible prior lifecycle field. Redemption time can change following a promotion and is deferred until its timing can be verified. Do not turn an unverified missing-redemption indicator into a predictor either.

## Actual audit

| Check | Observed result |
| --- | ---: |
| Labeled experimental customers | 200,039 |
| All client profiles | 400,162 |
| Communication customers, all assignment metadata | 99,981 |
| Control customers, all assignment metadata | 100,058 |
| Duplicate client-ID excess, experimental file | 0 |
| Duplicate client-ID excess, profiles | 0 |
| Missing IDs, treatment flags, or outcomes | 0 |
| Invalid treatment/outcome values | 0 |
| Non-ten-character-hex IDs, either file | 0 |
| Experimental customers matching exactly one profile | 200,039 |
| Unmatched experimental customers | 0 |
| Profiles outside labeled experimental population | 200,123 |

Missing profile values across all 400,162 profiles: `client_id=0`, `first_issue_date=0`, `first_redeem_date=35,469`, `age=0`, `gender=0`. Gender counts are F=147,649, M=66,807, U=185,706; U is a recorded unknown category, not a null.

All nonmissing age/date strings parse successfully, but parsing does not imply validity. Age ranges from **−7,491 to 1,901**; **313** values lie outside the deliberately broad audit range 0–120. No customers are removed for this. Final age-cleaning rules require review before modeling.

Issue dates span **2017-04-04 18:24:18–2019-03-15 21:50:56**; nonmissing redemption dates span **2017-04-11 09:42:20–2019-11-20 01:14:10**. **536** profiles have redemption before issue. These deserve source clarification; we do not silently correct them. The late redemption dates strengthen the need to establish a pre-campaign snapshot before using redemption features; they do not establish the campaign date.

See [audit.json](phase5/audit.json). Structural checks examine missingness and permitted target values across the source, but do **not** calculate full-source, validation, or final-test outcome rates.

## Frozen evaluation design

The [design](phase5/design.json) was written before training outcome analysis. Split creation completed at **2026-11-05 11:44:23 UTC**, and first training analysis at **11:45:34 UTC**. The seed is **20261105**.

Within each treatment arm, customers are ordered by SHA-256 of `seed:treatment_flg:client_id`, with client ID breaking any digest tie. This is a reproducible pseudo-random permutation independent of the outcome and source-row order. The first `floor(0.6*n)` customers go to train, the next through `floor(0.8*n)` to validation, and the remainder to final test. Stratification uses **treatment only**, not target or subgroups.

| Cohort | Control | Communication | Total |
| --- | ---: | ---: | ---: |
| Training/development | 60,034 | 59,988 | 120,022 |
| Validation | 20,012 | 19,996 | 40,008 |
| Final holdout | 20,012 | 19,997 | 40,009 |

Each customer occurs once and in exactly one split. Split assignments contain only `client_id`, `treatment_flg`, and `split`, at ignored `data/retailhero/splits/customer_assignments.parquet`. File SHA-256: `f38834e436b38b6483af7e4adfafda695bb2ffc9a178cf050b7f6c00a1d34169`. [split_manifest.json](phase5/split_manifest.json) records counts, input hashes, and the design hash; reruns reject changed inputs/design/assignments.

`client_id` will never be a predictor. Treatment is a design variable and may enter an S-Learner as its treatment input; it is not an ordinary response-propensity predictor. Target is never a predictor.

Only training outcomes are aggregated or analyzed here. Validation will support model/policy selection; final-test outcomes stay unused until a later frozen evaluation. This is a **procedural seal**, not encryption: the public raw file still contains all labels locally. Structural target validation scans the file, and does not make this a physically unread holdout. No validation/test effect, prediction, purchase rate, or subgroup result is produced. Public benchmark summaries must not guide tuning or imply that these data are a secret experiment.

## Statistics and causal assumptions

For each training arm, SQL calculates the number of customers and sum of the binary purchase flag. The difference `p_treatment − p_control` is the observed comparison. A 95% Newcombe interval combines the two arms' Wilson score bounds, without continuity correction. This avoids the poor boundary behavior of a simple Wald interval. The predeclared two-sided pooled z test tests equal group purchase probabilities at alpha 0.05; large event/non-event counts support its approximation. These calculations assume independent customer observations and do not account for unknown household/store clustering.

The conditional causal estimand is the average change in purchase probability from SMS contact versus no contact for customers represented by this experiment. Interpreting our **3.3902-point observed difference as an ATE estimate** requires:

1. Random assignment, or another credible reason for treatment to be independent of potential outcomes. The official material describes contact and subsequent purchase but does not expose allocation code, the protocol, assignment probabilities, or blocking.
2. The recorded treatment flag faithfully represents the intervention under study. The source says communication was performed, not explicitly randomized assignment. Without assignment/compliance logs, do not call this a verified intention-to-treat estimate or a treatment-on-the-treated estimate.
3. Comparable outcome capture and follow-up in both groups; no selective filtering of customers/outcomes after assignment. Complete binary labels in this extract do not prove absence of selection before release.
4. A sufficiently consistent SMS intervention, no material interference between customers, and both treatment possibilities available in the population.

The [scikit-uplift authors' RetailHero tutorial](https://github.com/maks-sh/scikit-uplift/blob/master/notebooks/RetailHero_EN.ipynb) explains the randomized-pilot framework and assumes equal assignment probability for its modeling discussion. That supports the intended framework, but does not supply an auditable assignment protocol for this released extract. **Randomization is not independently verified here.** Without these assumptions, the result remains a treatment-associated difference.

For the full assignment metadata, a two-sided exact binomial check against an **assumed** 50% assignment probability gives **p=0.86507**. There is no detectable sample-ratio mismatch under that assumed Bernoulli allocation. The protocol ratio is unknown; if allocation used fixed quotas or blocks this reference model is not exact for that design. Training counts give p=0.89665, but the stratified split constrains those counts, so that is not an independent randomization diagnostic.

Training-only descriptive balance: valid-age means are 46.4561 (control) and 46.5677 (treated), with standardized difference **0.00687**. Ages outside 0–120 occur for 63 controls and 48 treated customers. Gender-indicator standardized differences are F=0.00328, M=0.00141, U=−0.00424. Training redemption missingness is 10,580. These small measured differences are reassuring descriptions; they cannot establish balance on unobserved factors or prove causality. No subgroup effects were examined.

Limitations include undocumented assignment/compliance and follow-up, uncertain profile timing, invalid demographic records, possible interference/clustering, unknown selection into the released sample, and transport to other customers/campaigns. No cost, revenue, long-term effect, or customer-level benefit has been identified. Full-precision results are in [experiment_summary.json](phase5/experiment_summary.json).

## Purchase-history inspection and feature recommendations

The official documentation and supplied README describe purchase history **before the SMS campaign**. The archive records `purchases.csv` as **4,463,775,504 expanded bytes**, **611,056,980 compressed bytes**. We inspected only an **8,192-byte prefix** by ranged access (9,220 network bytes per prefix inspection). No full-history row count, date coverage, or cutoff was measured.

Observed header:

```text
client_id,transaction_id,transaction_datetime,regular_points_received,
express_points_received,regular_points_spent,express_points_spent,
purchase_sum,store_id,product_id,product_quantity,
trn_sum_from_iss,trn_sum_from_red
```

The prefix has 82 complete records across 11 customer/transaction pairs, and multiple product rows repeat a transaction's `purchase_sum`. This indicates an item-level grain in the prefix. Before monetary aggregation, verify the full file's transaction keys and the meaning/consistency of totals. Summing repeated `purchase_sum` across product rows would inflate spend. The prefix is ordered and unrepresentative, so its transaction patterns are not full-file statistics. See [purchases_schema.json](phase5/purchases_schema.json).

A compact future feature set, subject to a pre-treatment cutoff and full history audit:

| Candidate | Pre-treatment construction and condition |
| --- | --- |
| Transaction frequency | Distinct customer/transaction pairs during a fixed historical window |
| Purchase recency | Days from last historical transaction to a documented shared scoring cutoff |
| Historical spend | Sum one verified transaction total per customer/transaction, after monetary QA |
| Average basket value | Historical spend divided by distinct transactions, with missing-history flag |
| Product breadth | Distinct historical product IDs |
| Store breadth | Distinct historical store IDs |
| Age and unknown flag | Plausibility rule fitted/selected on development data; snapshot timing confirmed |
| Gender/unknown category | Profile snapshot verified pre-treatment; retain unknown explicitly |
| Card tenure | Cutoff minus issue date, only when chronology and timing are valid |

Do not engineer these features yet. Establish a campaign/scoring cutoff before recency, tenure, or fixed-window features. If source clarification is unavailable, explicitly document any proxy cutoff and the resulting limits. Do not use future redemptions, post-contact purchases, target, or identifiers as predictors. Defer redemption and point-derived predictors while timing/semantics are unresolved. Retain all experimental customers; missing history should create missing/zero-history indicators rather than outcome-dependent exclusions.

## Next modeling milestone, after review

1. Audit purchase history with bounded-memory DuckDB and agree on timing, transaction grain, and feature definitions. Preserve this split and exclude IDs from predictors.
2. Fit a **response-propensity baseline** on training only: estimate purchase probability from baseline features under the experiment's observed treatment mixture. This ranks likely buyers, not incremental beneficiaries.
3. Fit an **S-Learner**: one response model for `P(Y=1 | X,T)`, evaluated twice per customer at treatment 1 and 0. Their difference estimates conditional uplift under the causal assumptions. Model regularization can suppress treatment interactions.
4. Fit a **T-Learner**: separate treated/control response models; subtract their predicted probabilities. It permits distinct response patterns but may have greater variance. Neither approach reveals an individual's true causal effect.
5. Use validation for uplift/ranking comparisons, budgets, and policy selection. Freeze features/models/policy before a single final holdout evaluation. Include uncertainty and comparisons with treat-none, treat-all, and a response-ranked policy at matching budgets.
6. Estimate policy value with randomized-assignment estimators, not observed conversion among selected contacted customers. For a preselected policy `pi(X)` and known assignment probability `e(X)`, an inverse-probability value estimator averages `pi*T*Y/e + (1-pi)*(1-T)*Y/(1-e)`. Incremental value over treat-none averages `pi*(T*Y/e − (1-T)*Y/(1-e))`. Confirm assignment probabilities before calling these randomization-unbiased; a guessed e=0.5 is a sensitivity assumption here. Cross-fitted augmented estimators may improve precision later.
7. Compare contact-budget curves and clearly labeled **hypothetical** cost scenarios. Binary purchase outcomes alone cannot identify financial ROI. Cost/revenue assumptions must be supplied or declared, never invented as facts.

No models or policies in this milestone have been trained/evaluated in Phase 5.

## What the Python and SQL do

`growthlab.retailhero.acquire` reads the ZIP central directory through a seekable HTTP-range reader. It rejects servers ignoring byte ranges, binds requests to the archive ETag, checks member sizes and ZIP CRCs, records raw-file SHA-256, and refuses unmanifested file replacement. An existing acquisition manifest permits local hash verification without another download. `--inspect-history` reads the small prefix separately and caches/verifies its hash.

`growthlab.retailhero.experiment --prepare` verifies raw hashes, opens a disk-backed DuckDB database, and creates string-preserving CSV views. The structural audit counts nulls, malformed flags, duplicate keys, invalid demographics, and unmatched joins. A one-to-one join prevents accidental replication of customers. No missing demographic value causes removal. Window functions rank customers inside treatment arms; the CASE expression assigns the 60/20/20 split. The sorted ID-only assignment table is exported locally, and the manifest binds it to source hashes and the design before outcome analysis.

`--analyze` verifies that frozen manifest, then defines a view whose SQL predicate is fixed to `split='train'`. It joins profiles and sums target only inside that view. Python computes the difference, Wilson/Newcombe bounds, pooled test, and conditional interpretation units. Additional training-only demographic checks assess measured assignment balance without looking at subgroup effects. There is no validation/test outcome analysis mode.

`--verify` uses a separate Python CSV streaming calculation to count training-arm customers and purchasers, compares those results with DuckDB's saved output, and recalculates the statistics. Although CSV parsing traverses the source, labels are aggregated only when an ID belongs to training. No full events table is loaded into pandas; pandas is not imported.

## Reproduction, checks, resources, and files

From the repository root, in the existing environment (or a separate environment with `requirements-causal.lock` installed):

```bash
PYTHONPATH=src .venv/bin/python -m growthlab.retailhero.acquire
PYTHONPATH=src .venv/bin/python -m growthlab.retailhero.acquire --inspect-history
PYTHONPATH=src .venv/bin/python -m growthlab.retailhero.experiment --prepare
PYTHONPATH=src .venv/bin/python -m growthlab.retailhero.experiment --analyze
PYTHONPATH=src .venv/bin/python -m growthlab.retailhero.experiment --verify
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
PYTHONPATH=src .venv/bin/python -m growthlab.final_evaluation --verify-saved
```

Acquisition and preparation reuse existing verified local files. A fresh checkout containing the manifests but no ignored data must restore the exact local files or reproduce in a separate workspace with generated acquisition/split receipts archived there; do not delete this project's frozen split records to experiment with alternative splits. Minimal dependencies suffice for Phase 5 commands/tests; the complete repository suite also needs the existing Module 1 modeling environment. `--analyze` reproduces training results and refreshes runtime/timestamp metadata, not holdout analysis. Never run Module 1 `--evaluate` again; `--verify-saved` verifies the already-frozen evaluation.

**82 tests passed**, including all 66 previous tests and 16 new RetailHero tests. New tests cover hand-calculated effects/units, an independent chi-square check of the z test, Wilson/Newcombe formulas, arm reversal, zero/extreme outcomes, invalid counts, assignment mismatch, deterministic outcome-independent splits, exact proportions/disjointness, holdout-label perturbation, join integrity, missing demographics, duplicate IDs, invalid flags, and frozen-design/input/assignment checks. Synthetic fixtures exist only to test logic; every reported experiment result comes from real RetailHero data.

Independent real-data CSV aggregation agrees exactly with both arm sizes and purchaser counts; see [independent_verification.json](phase5/independent_verification.json). Module 1's saved predictions and metrics verify unchanged. Its existing local file sizes/modification times are also compared before/after; no old tracked file was edited.

DuckDB uses **256 MB**, **one thread**, a local disk-backed database, and at most **1 GB** of spill. Observed training-analysis runtime was **1.37 seconds**, peak process RSS **196,067,328 bytes (~187 MiB)**. This is the analysis process, not a measurement of every preceding acquisition/preparation operation. Local RetailHero files occupy about **26 MiB** at verification. About **141 GiB** was free before acquisition. No full purchase-history download, pandas-wide load, paid API, cloud resource, or model fitting occurred.

New reviewable files:

- `src/growthlab/retailhero/{__init__,acquire,experiment}.py`: separate Module 2 namespace, selective acquisition, audit/split/statistical logic.
- `tests/test_retailhero_experiment.py`: 16 automated logic tests.
- `requirements-causal.lock`: minimal pinned Phase 5 dependencies already present in the local environment.
- This report and `docs/causal/phase5/{design,acquisition,audit,split_manifest,purchases_schema,experiment_summary,independent_verification}.json`: methodology and small aggregate/provenance records, with no customer IDs/rows.

Ignored outputs: the two raw CSV files, source snapshots/prefix, DuckDB working files, spill files if any, and customer-level split assignments, all under `data/retailhero/`. Existing `.gitignore` already covers them; it was not changed. No files have been staged, committed, or pushed. Phase 5 stops here for review; uplift modeling and decision-policy evaluation remain future work.
