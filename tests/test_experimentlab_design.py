"""Synthetic IDs and planning mathematics only; no experiment outcomes."""
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import math
from pathlib import Path
import unittest

from scipy.optimize import brentq
from scipy.stats import norm

from growthlab.experimentlab.design import (
    ASSIGNMENT_VERSION, ExperimentDesign, assign_customers,
    numerical_planning_crosscheck, planning_example,
    sample_ratio_mismatch, two_proportion_sample_size,
)


class PlanningTests(unittest.TestCase):
    def test_default_sample_size_and_absolute_effect(self):
        result=two_proportion_sample_size(.20,.03)
        self.assertAlmostEqual(result['planning_treatment_rate'],.23)
        self.assertAlmostEqual(result['unrounded_per_group'],2942.5867373842148)
        self.assertEqual(result['control_n'],2943)
        self.assertEqual(result['treatment_n'],2943)
        self.assertEqual(result['total_n'],5886)

    def test_independent_two_tail_normal_inversion(self):
        # Derive a rejection threshold and integrate BOTH tails, independently
        # of the implemented closed-form sample-size formula / quantile helper.
        def power(n):
            cutoff=norm.ppf(.975)*math.sqrt(2*.215*.785/n)
            sd=math.sqrt(.20*.80/n+.23*.77/n)
            return norm.sf((cutoff-.03)/sd)+norm.cdf((-cutoff-.03)/sd)
        root=brentq(lambda n:power(n)-.80,100,10000)
        self.assertAlmostEqual(root,2942.5796259934195,places=6)
        self.assertEqual(math.ceil(root),2943)
        self.assertGreaterEqual(power(2943),.8)
        self.assertLess(power(2942),.8)
        self.assertAlmostEqual(numerical_planning_crosscheck(ExperimentDesign())['unrounded_per_group'],root,places=6)

    def test_sample_size_monotonicity(self):
        n=two_proportion_sample_size(.2,.03)['total_n']
        self.assertGreater(two_proportion_sample_size(.2,.02)['total_n'],n)
        self.assertGreater(two_proportion_sample_size(.2,.03,power=.9)['total_n'],n)
        self.assertGreater(two_proportion_sample_size(.2,.03,alpha=.01)['total_n'],n)

    def test_ceil_is_applied_per_arm(self):
        s=two_proportion_sample_size(.2,.03)
        self.assertEqual(s['total_n'],2*math.ceil(s['unrounded_per_group']))
        self.assertEqual(s['total_n']%2,0)

    def test_invalid_planning_inputs(self):
        for p0,delta,alpha,power in [(0,.03,.05,.8),(1,.03,.05,.8),(.99,.03,.05,.8),
            (.2,0,.05,.8),(.2,-.03,.05,.8),(.2,float('nan'),.05,.8),
            (.2,.03,0,.8),(.2,.03,1,.8),(.2,.03,.05,.5),(.2,.03,.05,1),
            (True,.03,.05,.8),(.2,.03,.05,True),('0.2',.03,.05,.8),(.2,1e-300,.05,.8)]:
            with self.subTest(args=(p0,delta,alpha,power)),self.assertRaises(ValueError):
                two_proportion_sample_size(p0,delta,alpha,power)

    def test_config_matches_reviewed_scenario(self):
        root=Path(__file__).resolve().parents[1]
        config=json.loads((root/'docs/experiments/phase8a_config.json').read_text())
        d=ExperimentDesign(**config)
        self.assertEqual(d,ExperimentDesign())
        self.assertEqual(d.treatment_probability,.5)
        self.assertTrue(d.assumptions_are_hypothetical)

    def test_frozen_config_and_unsupported_allocation_rejected(self):
        d=ExperimentDesign()
        with self.assertRaises(FrozenInstanceError):d.seed=1
        for overrides in [{'treatment_probability':.6},{'seed':True},{'seed':-1},
                          {'assumptions_are_hypothetical':False},{'experiment_id':' '},
                          {'treatment':'No voucher'}]:
            with self.subTest(overrides=overrides),self.assertRaises(ValueError):replace(d,**overrides)
        with self.assertRaisesRegex(ValueError,'limited to 100,000'):
            planning_example(replace(d,absolute_mde=.001))


class AssignmentTests(unittest.TestCase):
    def setUp(self):
        self.design=ExperimentDesign()
        self.ids=[f'synthetic-customer-{i:06d}' for i in range(1,101)]

    def test_reproducibility(self):
        self.assertEqual(assign_customers(self.ids,self.design),assign_customers(self.ids,self.design))

    def test_input_order_and_serialization_independence(self):
        a=assign_customers(self.ids,self.design)
        b=assign_customers(reversed(self.ids),self.design)
        self.assertEqual(list(a.items()),list(b.items()))
        self.assertEqual(json.dumps(a),json.dumps(b))

    def test_one_assignment_and_no_cross_group_overlap(self):
        a=assign_customers(self.ids,self.design)
        control={i for i,g in a.items() if g=='control'}
        treatment={i for i,g in a.items() if g=='treatment'}
        self.assertEqual(len(a),len(self.ids))
        self.assertFalse(control&treatment)
        self.assertEqual(control|treatment,set(self.ids))

    def test_customer_assignments_stable_when_cohort_grows(self):
        original=assign_customers(self.ids,self.design)
        grown=assign_customers(self.ids+['synthetic-new-customer'],self.design)
        self.assertEqual(original,{i:grown[i] for i in self.ids})

    def test_seed_and_experiment_namespace_change_assignment(self):
        original=assign_customers(self.ids,self.design)
        self.assertNotEqual(original,assign_customers(self.ids,replace(self.design,seed=17)))
        self.assertNotEqual(original,assign_customers(self.ids,replace(self.design,experiment_id='separate-hypothetical-test')))

    def test_independent_sha256_threshold_contract(self):
        # At allocation 1/2, the first digest bit alone determines the arm.
        a=assign_customers(self.ids,self.design)
        for customer in self.ids:
            payload=json.dumps([ASSIGNMENT_VERSION,self.design.experiment_id,20261106,customer],
                               ensure_ascii=False,separators=(',',':')).encode()
            expected='treatment' if hashlib.sha256(payload).digest()[0]<128 else 'control'
            self.assertEqual(a[customer],expected)

    def test_exact_documented_example_counts(self):
        ids=[f'synthetic-customer-{i:06d}' for i in range(1,5887)]
        a=assign_customers(ids,self.design)
        self.assertEqual(sum(g=='control' for g in a.values()),2950)
        self.assertEqual(sum(g=='treatment' for g in a.values()),2936)
        self.assertLess(abs(sum(g=='treatment' for g in a.values())/len(a)-.5),.02)

    def test_duplicate_ids_rejected_instead_of_silently_dropped(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):assign_customers(['synthetic-1','synthetic-1'],self.design)

    def test_missing_or_malformed_ids_rejected(self):
        for bad in [None,'',' ',' padded','padded ',float('nan'),123,True]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):assign_customers(['synthetic-valid',bad],self.design)
        for bad in [None,'one-string',b'one-string']:
            with self.subTest(collection=bad),self.assertRaises(ValueError):assign_customers(bad,self.design)

    def test_ids_not_normalized_and_empty_input_allowed(self):
        ids=['synthetic-001','synthetic-1','synthetic-X','synthetic-x','synthetic-ü']
        self.assertEqual(set(assign_customers(ids,self.design)),set(ids))
        self.assertEqual(assign_customers([],self.design),{})


class SRMTests(unittest.TestCase):
    def test_balanced_counts(self):
        s=sample_ratio_mismatch(50,50)
        self.assertEqual(s['p_value'],1)
        self.assertFalse(s['flag_srm'])
        self.assertEqual(s['expected_treatment_n'],50)

    def test_hand_enumerated_exact_binomial_examples(self):
        # n=10, all in one arm: both tails total 2*(1/2)^10.
        s=sample_ratio_mismatch(0,10)
        self.assertAlmostEqual(s['p_value'],2/2**10)
        self.assertTrue(s['flag_srm'])
        # n=10, 9 treated: both tails sum probabilities for 0,1,9,10.
        self.assertAlmostEqual(sample_ratio_mismatch(1,9)['p_value'],22/2**10)

    def test_ordinary_imbalance_is_not_automatically_srm(self):
        s=sample_ratio_mismatch(40,60)
        expected=sum(math.comb(100,k) for k in list(range(41))+list(range(60,101)))/2**100
        self.assertAlmostEqual(s['p_value'],expected,places=12)
        self.assertFalse(s['flag_srm'])  # p about .0569 > declared .01

    def test_declared_srm_threshold_is_separate_from_outcome_alpha(self):
        s=sample_ratio_mismatch(1,9,significance_level=.01)
        self.assertFalse(s['flag_srm'])
        self.assertTrue(sample_ratio_mismatch(1,9,significance_level=.05)['flag_srm'])

    def test_extreme_mismatch_and_arm_symmetry(self):
        a=sample_ratio_mismatch(10,190);b=sample_ratio_mismatch(190,10)
        self.assertEqual(a['p_value'],b['p_value'])
        self.assertLess(a['p_value'],1e-20)
        self.assertTrue(a['flag_srm'])

    def test_planned_probability_controls_expected_counts(self):
        s=sample_ratio_mismatch(80,20,treatment_probability=.2)
        self.assertEqual(s['expected_treatment_n'],20)
        self.assertEqual(s['p_value'],1)

    def test_invalid_srm_inputs(self):
        for c,t in [(-1,2),(1,-2),(0,0),(1.5,2),(True,2)]:
            with self.subTest(c=c,t=t),self.assertRaises(ValueError):sample_ratio_mismatch(c,t)
        for value in [0,1,float('nan'),True]:
            with self.subTest(value=value),self.assertRaises(ValueError):sample_ratio_mismatch(5,5,treatment_probability=value)

    def test_planning_summary_has_no_outcomes_and_reports_short_arm(self):
        result=planning_example(ExperimentDesign())
        self.assertEqual(result['synthetic_example']['srm']['total_n'],5886)
        self.assertAlmostEqual(result['synthetic_example']['srm']['p_value'],.8654470932079597)
        self.assertFalse(result['synthetic_example']['per_arm_planning_minimum_reached']['treatment'])
        self.assertNotIn('observed_conversion_rate',result)
        self.assertNotIn('outcomes',result)


if __name__=='__main__':unittest.main()
