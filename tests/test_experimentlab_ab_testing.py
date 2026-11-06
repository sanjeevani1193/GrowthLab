"""Synthetic A/B power tests; unchanged prior assignment and analysis methods."""
from dataclasses import replace
from pathlib import Path
import json
import math
import unittest
from unittest.mock import patch

import numpy as np
from scipy.stats import chi2_contingency

from growthlab.experimentlab import aa_testing, ab_testing
from growthlab.experimentlab.ab_testing import (
    ABStudyConfig, TRUE_CONTROL_RATE, TRUE_TREATMENT_RATE, TRUE_DIFFERENCE,
    draw_ab_outcomes, normal_approx_power, run_study,
)
from growthlab.experimentlab.design import ExperimentDesign, assign_customers, numerical_planning_crosscheck


class ABGenerationTests(unittest.TestCase):
    def test_true_rates_and_positive_effect(self):
        self.assertEqual(TRUE_CONTROL_RATE,.20)
        self.assertEqual(TRUE_TREATMENT_RATE,.23)
        self.assertGreater(TRUE_TREATMENT_RATE,TRUE_CONTROL_RATE)
        self.assertAlmostEqual(TRUE_TREATMENT_RATE-TRUE_CONTROL_RATE,TRUE_DIFFERENCE)

    def test_probabilities_are_applied_to_the_correct_customer_arms(self):
        mask=np.array([False,True,False,True])
        class CapturingRng:
            def binomial(self,n,p):
                self.n,self.p=n,p.copy()
                return np.zeros(len(p),dtype=int)
        rng=CapturingRng()
        with patch('growthlab.experimentlab.ab_testing.outcome_stream',return_value=rng):
            outcomes=draw_ab_outcomes(mask,123,0)
        self.assertEqual(rng.n,1)
        np.testing.assert_array_equal(rng.p,[.20,.23,.20,.23])
        self.assertEqual(outcomes.shape,(4,))

    def test_independent_numpy_generation_and_binary_values(self):
        mask=np.array([False,True]*50)
        rng=np.random.Generator(np.random.PCG64(np.random.SeedSequence(123,spawn_key=(2,))))
        expected=rng.binomial(1,np.where(mask,.23,.20))
        actual=draw_ab_outcomes(mask,123,2)
        np.testing.assert_array_equal(actual,expected)
        self.assertTrue(np.isin(actual,[0,1]).all())

    def test_reproducible_outcomes_and_distinct_streams(self):
        mask=np.array([False,True]*50)
        a=draw_ab_outcomes(mask,123,0)
        np.testing.assert_array_equal(a,draw_ab_outcomes(mask,123,0))
        self.assertFalse(np.array_equal(a,draw_ab_outcomes(mask,123,1)))

    def test_invalid_assignment_masks(self):
        for mask in [[],[0,1],[[False,True]],'control']:
            with self.subTest(mask=mask),self.assertRaises(ValueError):draw_ab_outcomes(mask,123,0)


class ABAnalysisTests(unittest.TestCase):
    def test_existing_statistics_and_rng_functions_are_reused_exactly(self):
        self.assertIs(ab_testing.analyze_counts,aa_testing.analyze_counts)
        self.assertIs(ab_testing.calibration_check,aa_testing.calibration_check)
        self.assertIs(ab_testing.outcome_stream,aa_testing.outcome_stream)

    def test_hand_worked_three_pp_estimate_with_finite_sample_uncertainty(self):
        row=ab_testing.analyze_counts(40,200,46,200)
        self.assertAlmostEqual(row['difference_pp'],3)
        self.assertFalse(row['significant'])  # positive estimated effect is not sufficient
        self.assertEqual(row['confidence_level'],.95)
        self.assertLess(row['difference_ci'][0],.03)
        self.assertGreater(row['difference_ci'][1],.03)
        _,p,_,_=chi2_contingency([[40,160],[46,154]],correction=False)
        self.assertAlmostEqual(row['p_value_two_sided'],p)

    def test_balanced_normal_power_matches_phase8a_independent_crosscheck(self):
        prior=numerical_planning_crosscheck(ExperimentDesign())
        self.assertAlmostEqual(normal_approx_power(2943,2943),prior['normal_power_at_rounded_n'],places=14)
        self.assertAlmostEqual(normal_approx_power(2943,2943),.8000560433949436)

    def test_realized_allocation_power_and_monotonicity(self):
        self.assertAlmostEqual(normal_approx_power(2950,2936),.8000726875513032)
        self.assertGreater(normal_approx_power(6000,6000),normal_approx_power(2943,2943))
        for nc,nt in [(0,100),(-1,100),(100,1.5)]:
            with self.subTest(nc=nc,nt=nt),self.assertRaises(ValueError):normal_approx_power(nc,nt)


class ABStudyTests(unittest.TestCase):
    def setUp(self):
        self.design=ExperimentDesign();self.config=ABStudyConfig(repetitions=20)

    def test_full_numerical_study_reproducibility(self):
        a,rows=run_study(self.design,self.config);b,again=run_study(self.design,self.config)
        self.assertEqual(a,b);self.assertEqual(rows,again)

    def test_longer_run_keeps_identical_prefix(self):
        _,short=run_study(self.design,replace(self.config,repetitions=5))
        _,long=run_study(self.design,self.config)
        self.assertEqual(short,long[:5])
        self.assertEqual([r['spawn_key'] for r in long],[[i] for i in range(20)])

    def test_assignment_counts_deviations_and_hash_match_phase8b(self):
        summary,_=run_study(self.design,self.config)
        a=summary['assignment']
        self.assertEqual((a['control_n'],a['treatment_n']),(2950,2936))
        self.assertEqual((a['control_delta_from_plan'],a['treatment_delta_from_plan']),(7,-7))
        self.assertEqual(a['assignment_sha256'],'0023e31634e472d5f1a03ea8f5cb0e317a63f44cc2cfed7467268032b165e507')

    def test_power_false_negatives_and_detection_direction_reconcile(self):
        s,rows=run_study(self.design,self.config)
        significant=sum(r['p_value_two_sided']<.05 for r in rows)
        self.assertEqual(s['empirical_power']['events'],significant)
        self.assertEqual(s['empirical_power']['empirical_rate'],significant/20)
        self.assertEqual(s['detection_direction']['false_negatives'],20-significant)
        self.assertEqual(s['detection_direction']['positive_significant']+s['detection_direction']['negative_significant'],significant)
        for r in rows:
            self.assertEqual(r['effect_detected'],r['significant'])
            self.assertEqual(r['detected_positive'],r['significant'] and r['difference']>0)

    def test_coverage_is_for_three_pp_not_zero(self):
        s,rows=run_study(self.design,self.config)
        covered=sum(r['difference_ci'][0]<=.03<=r['difference_ci'][1] for r in rows)
        self.assertEqual(s['interval_coverage']['events'],covered)
        for r in rows:
            self.assertEqual(r['covers_true_effect'],r['difference_ci'][0]<=.03<=r['difference_ci'][1])
            self.assertEqual(r['covers_true_zero'],r['difference_ci'][0]<=0<=r['difference_ci'][1])
        self.assertTrue(any(r['covers_true_effect']!=r['covers_true_zero'] for r in rows))

    def test_example_is_prespecified_not_chosen_by_success(self):
        s,rows=run_study(self.design,replace(self.config,example_index=3))
        self.assertEqual(s['example'],rows[3])

    def test_previous_assignment_and_aa_procedure_remain_unchanged(self):
        ids=[f'synthetic-customer-{i:06d}' for i in range(1,5887)]
        assignment=assign_customers(ids,self.design)
        aa_before=aa_testing.run_study(self.design,aa_testing.AAStudyConfig(repetitions=5))
        run_study(self.design,self.config)
        self.assertEqual(assignment,assign_customers(ids,self.design))
        self.assertEqual(aa_before,aa_testing.run_study(self.design,aa_testing.AAStudyConfig(repetitions=5)))

    def test_declared_config_uses_separate_seed_and_frozen_methods(self):
        root=Path(__file__).resolve().parents[1]
        cfg=ABStudyConfig(**json.loads((root/'docs/experiments/phase8c_config.json').read_text()))
        self.assertEqual(cfg.repetitions,1000)
        self.assertEqual(cfg.example_index,0)
        self.assertEqual(cfg.outcome_master_seed,2026110602)
        self.assertNotEqual(cfg.outcome_master_seed,aa_testing.AAStudyConfig().outcome_master_seed)

    def test_invalid_config_and_unsupported_alternative_rejected(self):
        for kwargs in [{'repetitions':0},{'outcome_master_seed':-1},{'example_index':1000}]:
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):ABStudyConfig(**kwargs)
        for override in [{'baseline_rate':.3},{'absolute_mde':.02},{'alpha':.01}]:
            with self.subTest(override=override),self.assertRaises(ValueError):run_study(replace(self.design,**override),self.config)

    def test_monte_carlo_power_check_does_not_require_exact_target(self):
        c=aa_testing.calibration_check(793,1000,normal_approx_power(2950,2936))
        self.assertFalse(c['flag_departure'])
        self.assertLess(c['wilson_95_interval'][0],.8)
        self.assertGreater(c['wilson_95_interval'][1],.8)
        self.assertTrue(aa_testing.calibration_check(500,1000,.8)['flag_departure'])


if __name__=='__main__':unittest.main()
