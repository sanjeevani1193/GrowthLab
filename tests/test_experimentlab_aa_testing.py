"""Synthetic A/A only: no real customers or nonzero generating effects."""
from dataclasses import replace
import math
import unittest

import numpy as np
from scipy.stats import binomtest, chi2_contingency

from growthlab.experimentlab.aa_testing import (
    AAStudyConfig, TRUE_PURCHASE_PROBABILITY, analyze_counts, calibration_check,
    draw_aa_outcomes, outcome_stream, run_study, wilson_interval,
)
from growthlab.experimentlab.design import ExperimentDesign, assign_customers


class CountAnalysisTests(unittest.TestCase):
    def test_hand_calculated_rates_difference_and_pooled_z(self):
        s=analyze_counts(50,100,60,100)
        self.assertEqual(s['control_rate'],.5)
        self.assertEqual(s['treatment_rate'],.6)
        self.assertAlmostEqual(s['difference_pp'],10)
        self.assertAlmostEqual(s['z_statistic'],.1/math.sqrt(.55*.45*(1/100+1/100)))
        self.assertFalse(s['significant'])

    def test_independent_chi_square_identity(self):
        s=analyze_counts(50,100,60,100)
        chi,p,_,_=chi2_contingency([[50,50],[60,40]],correction=False)
        self.assertAlmostEqual(s['z_statistic']**2,chi)
        self.assertAlmostEqual(s['p_value_two_sided'],p)

    def test_wilson_and_newcombe_against_independent_scipy_score_bounds(self):
        lc,uc=binomtest(50,100).proportion_ci(method='wilson')
        lt,ut=binomtest(60,100).proportion_ci(method='wilson')
        s=analyze_counts(50,100,60,100)
        self.assertAlmostEqual(s['difference_ci'][0],.1-math.sqrt((.6-lt)**2+(uc-.5)**2))
        self.assertAlmostEqual(s['difference_ci'][1],.1+math.sqrt((ut-.6)**2+(.5-lc)**2))
        self.assertEqual(s['confidence_level'],.95)

    def test_unequal_group_sizes_are_used_correctly(self):
        s=analyze_counts(590,2950,587,2936)
        self.assertAlmostEqual(s['difference'],587/2936-590/2950)
        chi,p,_,_=chi2_contingency([[590,2360],[587,2349]],correction=False)
        self.assertAlmostEqual(s['p_value_two_sided'],p)
        self.assertAlmostEqual(s['z_statistic']**2,chi)

    def test_arm_swap_reverses_estimate_and_ci_not_pvalue(self):
        a=analyze_counts(50,100,60,100);b=analyze_counts(60,100,50,100)
        self.assertAlmostEqual(a['difference'],-b['difference'])
        self.assertAlmostEqual(a['difference_ci'][0],-b['difference_ci'][1])
        self.assertEqual(a['p_value_two_sided'],b['p_value_two_sided'])

    def test_equal_rates_and_extreme_null_counts(self):
        for conversions in [0,20,100]:
            s=analyze_counts(conversions,100,conversions,100)
            self.assertEqual(s['difference'],0)
            self.assertEqual(s['p_value_two_sided'],1)
            self.assertFalse(s['significant'])
            self.assertTrue(s['covers_true_zero'])

    def test_synthetic_unequal_observed_counts_can_be_significant(self):
        # An arithmetic fixture, not a nonzero-treatment-effect data generator.
        s=analyze_counts(10,100,50,100)
        self.assertTrue(s['significant'])
        self.assertLess(s['p_value_two_sided'],.05)
        self.assertFalse(s['covers_true_zero'])

    def test_invalid_counts_and_alpha_rejected(self):
        for args in [(-1,10,1,10),(11,10,1,10),(1,0,1,10),(1.5,10,1,10),(True,10,1,10)]:
            with self.subTest(args=args),self.assertRaises(ValueError):analyze_counts(*args)
        for alpha in [0,1,float('nan')]:
            with self.subTest(alpha=alpha),self.assertRaises(ValueError):wilson_interval(5,10,alpha)


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.design=ExperimentDesign();self.config=AAStudyConfig(repetitions=25)

    def test_binary_outcomes_and_exact_20_percent_generating_probability(self):
        seed,index=2026110601,0
        expected=np.random.Generator(np.random.PCG64(np.random.SeedSequence(seed,spawn_key=(index,)))).binomial(1,.2,size=5886)
        actual=draw_aa_outcomes(5886,seed,index)
        np.testing.assert_array_equal(actual,expected)
        self.assertEqual(actual.shape,(5886,))
        self.assertTrue(np.isin(actual,[0,1]).all())
        self.assertEqual(TRUE_PURCHASE_PROBABILITY,.2)

    def test_outcome_reproducibility_and_distinct_child_streams(self):
        a=draw_aa_outcomes(100,123,0);b=draw_aa_outcomes(100,123,1)
        np.testing.assert_array_equal(a,draw_aa_outcomes(100,123,0))
        self.assertFalse(np.array_equal(a,b))

    def test_spawn_key_matches_numpy_spawn_and_is_request_order_independent(self):
        children=np.random.SeedSequence(123).spawn(3)
        expected=np.random.Generator(np.random.PCG64(children[2])).random(12)
        np.testing.assert_array_equal(outcome_stream(123,2).random(12),expected)
        outcome_stream(123,100).random(12)
        np.testing.assert_array_equal(outcome_stream(123,2).random(12),expected)

    def test_complete_study_reproducibility(self):
        a,rows=run_study(self.design,self.config)
        b,again=run_study(self.design,self.config)
        self.assertEqual(a,b);self.assertEqual(rows,again)

    def test_repetition_prefix_stable_and_seeds_not_reset_in_loop(self):
        _,short=run_study(self.design,replace(self.config,repetitions=5))
        _,long=run_study(self.design,self.config)
        self.assertEqual(short,long[:5])
        self.assertEqual([r['spawn_key'] for r in long],[[i] for i in range(25)])
        self.assertGreater(len({(r['control_conversions'],r['treatment_conversions']) for r in long}),1)

    def test_null_effect_assignment_and_no_phase8a_rebalancing(self):
        summary,rows=run_study(self.design,self.config)
        self.assertEqual(summary['true_control_rate'],.2)
        self.assertEqual(summary['true_treatment_rate'],.2)
        self.assertEqual(summary['true_difference_pp'],0)
        self.assertEqual(summary['assignment']['control_n'],2950)
        self.assertEqual(summary['assignment']['treatment_n'],2936)
        self.assertTrue(all(r['control_n']==2950 and r['treatment_n']==2936 for r in rows))
        ids=[f'synthetic-customer-{i:06d}' for i in range(1,5887)]
        before=assign_customers(ids,self.design)
        run_study(self.design,replace(self.config,repetitions=1))
        self.assertEqual(before,assign_customers(ids,self.design))

    def test_aggregation_and_coverage_reconcile_with_each_replication(self):
        summary,rows=run_study(self.design,self.config)
        self.assertEqual(summary['false_positives']['events'],sum(r['p_value_two_sided']<.05 for r in rows))
        self.assertEqual(summary['interval_coverage']['events'],sum(r['difference_ci'][0]<=0<=r['difference_ci'][1] for r in rows))
        self.assertEqual(sum(summary['p_value_diagnostics']['decile_counts']),self.config.repetitions)

    def test_prespecified_example_is_not_selected_by_significance(self):
        summary,rows=run_study(self.design,replace(self.config,example_index=3))
        self.assertEqual(summary['example'],rows[3])

    def test_invalid_study_config_and_non_aa_design_rejected(self):
        for kwargs in [{'repetitions':0},{'repetitions':10001},{'repetitions':True},
                       {'outcome_master_seed':-1},{'example_index':1000},{'calibration_alpha':0}]:
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):AAStudyConfig(**kwargs)
        with self.assertRaises(ValueError):run_study(replace(self.design,baseline_rate=.3),self.config)
        with self.assertRaises(ValueError):draw_aa_outcomes(0,123,0)


class CalibrationTests(unittest.TestCase):
    def test_expected_five_percent_is_not_required_exactly(self):
        c=calibration_check(50,1000,.05)
        self.assertEqual(c['empirical_rate'],.05)
        self.assertEqual(c['two_sided_binomial_p_value'],1)
        self.assertFalse(c['flag_departure'])
        self.assertFalse(calibration_check(43,1000,.05)['flag_departure'])

    def test_large_false_positive_excess_is_flagged(self):
        c=calibration_check(200,1000,.05)
        self.assertTrue(c['flag_departure'])
        self.assertLess(c['two_sided_binomial_p_value'],1e-20)

    def test_coverage_diagnostic_and_wilson_bounds(self):
        c=calibration_check(957,1000,.95)
        self.assertFalse(c['flag_departure'])
        expected=binomtest(957,1000).proportion_ci(method='wilson')
        np.testing.assert_allclose(c['wilson_95_interval'],expected,rtol=0,atol=1e-14)
        self.assertLess(c['wilson_95_interval'][0],.95)
        self.assertGreater(c['wilson_95_interval'][1],.95)


if __name__=='__main__':unittest.main()
