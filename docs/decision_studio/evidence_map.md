# Decision Studio evidence map

Research baseline: `cf97aca9ca95d7e5ee754dec0717dae815cf657b` (Phases 0–10C).
All paths below are relative to the repository root. The app never queries
customer records, loads fitted models, or accesses sealed outcome labels.

The [manifest](evidence_manifest.json) pins twelve permitted JSON sources by
SHA-256. It is an integrity record, not a new research evaluation. The loader
checks fingerprints and required fields before caching the decoded aggregate.
Unknown sources and paths outside `docs/` are rejected. A missing, modified or
malformed file produces an actionable in-app error instead of substitute numbers.

## Source registry

| App alias | Authoritative file | Meaning |
| --- | --- | --- |
| `purchase` | [Phase 4 summary](../phase4/test_summary.json) | Frozen purchase-prediction test metrics, calibration bins and counts |
| `purchase_spec` | [Phase 2 specification](../phase2_specification.json) | Twelve predictors and primary chronological cohorts |
| `experiment` | [Phase 5 summary](../causal/phase5/experiment_summary.json) | RetailHero **training-cohort** observed group comparison |
| `uplift` | [Phase 7 summary](../causal/phase7/final_summary.json) | Frozen final-holdout policy values and paired intervals |
| `planning` | [Phase 8A summary](../experiments/phase8a_planning_summary.json) | Balanced sample-size reference and synthetic assignment/SRM |
| `aa` | [Phase 8B summary](../experiments/phase8b_aa_summary.json) | Saved zero-effect simulations and calibration diagnostics |
| `ab` | [Phase 8C summary](../experiments/phase8c_ab_summary.json) | Saved assumed-effect simulations and calibration diagnostics |
| `reward_reference` | [Phase 9A summary](../rewards/phase9a_reference_summary.json) | Verified hypothetical reference calculation |
| `reward_config` | [Phase 9B configuration](../rewards/phase9b_scenario_config.json) | Explicit hypothetical scenario inputs |
| `reward_summary` | [Phase 9B summary](../rewards/phase9b_scenario_summary.json) | Reference comparison and sensitivity calculations |
| `ranking` | [Phase 10C summary](../ranking/phase10c_summary.json) | Final ranking metrics, candidate ceiling, paired bootstrap |
| `ranking_protocol` | [Phase 10C protocol](../ranking/phase10c_protocol.json) | Frozen features, temporal boundaries and ranking configuration |

## Every displayed research metric and chart

Paths use dot notation below; `{model}`, `{budget}` and `{K}` are the selected
**existing** model/budget/cutoff, not arbitrary research recomputations. Formatting
rounds values only for display. Probabilities multiply by 100 for percentages;
policy-value interval probabilities multiply by 1,000 for population-normalized
purchaser counts. Percentage-point differences already stored in pp are not
multiplied a second time.

| Page / component | Source and exact field(s) or transformation |
| --- | --- |
| Overview purchase AUC / lift | `purchase.models.xgboost.test.roc_auc`, `lift_at_top_10_percent` → **0.8487 / 5.92×** |
| Overview SMS/control difference | `experiment.statistics.difference_pp` → **+3.39 pp**, explicitly training cohort; not the Phase 7 final group difference |
| Overview targeting conclusion | `uplift.primary.difference_per_1000`, `ci95_per_1000` and original Phase 7 report; interval includes zero |
| Overview A/A / A/B | `aa.false_positives.empirical_rate` / `ab.empirical_power.empirical_rate` → **4.3% / 79.3%**, synthetic |
| Overview ranking | `ranking.methods.ml.10.recall_macro`, `ndcg_macro` → **18.42% / 0.21625** |
| Purchase four KPI cards | `purchase.models.{model}.test`: `roc_auc`, `average_precision`, `recall_at_top_10_percent`, `lift_at_top_10_percent` |
| Purchase decile donut / captured count | `models.{model}.test.top_10_percent_positive_labels`; other slice = `test_positive_labels` minus captured; XGBoost **324 / 547** |
| Purchase selected population / precision | `models.{model}.test.top_10_percent_count`, `precision_at_top_10_percent`; no extra thresholds |
| Purchase model-comparison bar chart | `models.{model}.test` for `dummy`, `logistic_regression`, `xgboost`; radio chooses `roc_auc`, `average_precision` or `recall_at_top_10_percent` |
| Purchase calibration scatter | `models.xgboost.reliability` and `models.xgboost_calibrated.reliability`: `mean_predicted_probability`, `observed_purchase_rate`; only stored bin points |
| Calibration diagonal | Mathematical equality line `observed = predicted`, explicitly a reference, not experimental points |
| Calibration table | Raw/calibrated `test.brier_score`, `test.log_loss`, `test.mean_predicted_probability`; `purchase.test_prevalence` |
| Purchase dataset / feature / split summary | `purchase.test_customers`, `test_positive_labels`; `purchase_spec.feature_columns`, `primary_splits` (UTC, end-exclusive) |
| RetailHero group cards / bars | `experiment.statistics.treated_rate`, `control_rate`, `difference_pp`, `ci95_pp`; N = `treated_n + control_n` |
| RetailHero policy interval chart / table | `uplift.policies.{policy}/{budget}%`: `incremental_per_1000`, `incremental_value_ci95 × 1000`, `selected_n`; policies `constant`, `response`, `s_learner`, `t_learner`; budgets **10, 20, 30 only** |
| Policy population / assumptions | `uplift.n` = 40,009; propensity and bootstrap assumptions from original Phase 7 protocol/report |
| Paired S-minus-random card / interval | `uplift.paired_policy_differences["s_learner/{budget}% minus constant/{budget}%"]`: `difference_per_1000`, `ci95_per_1000` |
| Contact-all / none table | `uplift.policies.all` / `.none`: `selected_n`, `incremental_per_1000`, `incremental_value_ci95 × 1000` |
| Saved simulation cards / interval chart | `aa.false_positives` / `ab.empirical_power`: `empirical_rate`, `wilson_95_interval`; intervals describe Monte Carlo frequencies, not campaign effects |
| Simulation assumptions | `aa` / `ab`: `true_control_rate`, `true_treatment_rate`; both studies have 1,000 runs |
| Prespecified simulation example table | Chosen `aa.example` / `ab.example`: `experiment_index`, `control_rate`, `treatment_rate`, `difference_pp`, `p_value_two_sided`, `difference_ci_pp` |
| Coverage / SRM explanation | `aa.interval_coverage.empirical_rate`, `ab.interval_coverage.empirical_rate`; `planning.synthetic_example.srm.p_value` → **0.8654** |
| Ranking four cards | `ranking.methods.ml.{K}.recall_macro` or `recall_micro`, `ndcg_macro`; `candidate_recall_macro` or `candidate_recall_micro`; `errors.absent_from_candidates / relevant_pairs` → **70.69%** missing pairs |
| Ranking recall / NDCG bar charts and table | `ranking.methods.{method}.{K}`: `recall_macro`, `recall_micro`, `ndcg_macro`, `hits`; methods `global_popularity`, `personal_recency`, `ml`; **K = 5, 10, 20 only** |
| Ranking paired comparison cards | `ranking.paired_uncertainty.mean_difference`, `lower_95`, `upper_95`: endpoint order Recall@5, NDCG@5, Recall@10, NDCG@10, Recall@20, NDCG@20; always macro purchaser-level differences |
| Ranking population / retrieved coverage | `ranking.eligible_users`, `purchasing_users`, `relevant_pairs`, `errors.absent_from_candidates`; all eligible users receive the same 100-candidate universe across methods |
| Ranking feature / history explanation | `ranking_protocol.features`, `history_start`, `prediction_time`, `outcome_end`; seven features preserved |
| Methodology | Original linked Phase 4–10C reports and protocols; no additional performance results |

No ROC/PR curve is inferred from scalar metrics. Calibration points are not
interpolated. No new uplift/Qini curve is reconstructed, and no new thresholds,
outcomes, confidence intervals or customer-level predictions are generated.

## Interactive calculations (not research observations)

| UI calculation | Reused function / output binding |
| --- | --- |
| Balanced experiment planning | `experimentlab.design.two_proportion_sample_size` unchanged; `control_n`, `treatment_n`, `total_n`. Default **2,943 / 2,943 / 5,886** agrees with `planning.sample_size` |
| Unequal allocation | `studio.calculations.plan_experiment`: documented normal-approximation generalization; see implementation report. New hypothetical design only, not a change to Phase 8 simulations |
| Reward cards and contribution/cost bars | `rewards.economics.result_payload`: `expected_values.expected_incremental_purchasers`, `expected_incremental_purchase_contribution_eur`, `total_reward_expenditure_eur`, `total_contact_expenditure_eur`, `net_incremental_contribution_eur` |
| Reward break-even / status | Same engine's `break_even.status`, `explanation`, `required_treatment_probability.decimal_approximation`; net sign determines displayed status, with zero contacts handled explicitly |
| Scenario comparison table | `rewards.scenarios.compare_scenarios`; current scenario plus selected `reward_config.scenarios`; use original engine output, ranking and comparability guard |
| Sensitivity line | `rewards.scenarios.sensitivity`; 3–21 deterministic grid points, one selected input varies, all others remain fixed; mathematical line, not estimated response or a statistical interval |
| Reward JSON download | Exact current `result_payload`, labeled hypothetical; no customer-level data or predictions |

Defaults reproduce the saved Phase 9A reference: **30 expected extra purchasers,
€600 extra purchase contribution, €1,150 reward cost, €0 contact cost, −€550 net**.
The saved Phase 9B summaries are provenance references; live calculations invoke
the unchanged engines, rather than pretending their output is measured evidence.
