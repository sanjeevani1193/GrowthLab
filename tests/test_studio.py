"""Aggregate-only app adapters, real evidence and hypothetical calculations."""
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile
import unittest

from scipy.stats import norm

from growthlab.studio.evidence import (
    ROOT,MANIFEST,EvidenceError,load_evidence,policy_rows,ranking_rows,ranking_difference,
)
from growthlab.studio.calculations import (
    plan_experiment,scenario_from_inputs,result_payload,compare_with_saved,sensitivity_points,
)
from growthlab.experimentlab.design import two_proportion_sample_size


class EvidenceTests(unittest.TestCase):
    def test_every_allowlisted_source_loads(self):
        manifest=json.loads((ROOT/MANIFEST).read_text())
        self.assertEqual(len(manifest['sources']),12)
        for name in manifest['sources']:
            with self.subTest(source=name):self.assertIsInstance(load_evidence(name),dict)

    def test_all_requested_headlines_match_frozen_sources(self):
        p=load_evidence('purchase')['models']['xgboost']['test']
        self.assertAlmostEqual(p['roc_auc'],.8486584854187539)
        self.assertAlmostEqual(p['lift_at_top_10_percent'],5.9225267960409544)
        self.assertAlmostEqual(load_evidence('experiment')['statistics']['difference_pp'],3.3902075303512746)
        self.assertEqual(load_evidence('aa')['false_positives']['empirical_rate'],.043)
        self.assertEqual(load_evidence('ab')['empirical_power']['empirical_rate'],.793)
        r=load_evidence('ranking')['methods']['ml']['10']
        self.assertAlmostEqual(r['recall_macro'],.18416251862368846)
        self.assertAlmostEqual(r['ndcg_macro'],.2162532599833091)

    def test_budget_selection_uses_exact_saved_estimates(self):
        d=load_evidence('uplift')
        for b in (10,20,30):
            rows=policy_rows(d,b)
            self.assertEqual(len(rows),4)
            self.assertAlmostEqual(rows[2]['Estimate'],d['policies'][f's_learner/{b}%']['incremental_per_1000'])
            self.assertAlmostEqual(rows[2]['Lower'],1000*d['policies'][f's_learner/{b}%']['incremental_value_ci95'][0])
        with self.assertRaises(ValueError):policy_rows(d,15)

    def test_ranking_selection_and_macro_micro_differences(self):
        d=load_evidence('ranking')
        for k in (5,10,20):
            rows=ranking_rows(d,k)
            self.assertEqual(rows[2]['hits'],d['methods']['ml'][str(k)]['hits'])
            delta=ranking_difference(d,k)['Recall']
            self.assertAlmostEqual(delta['estimate'],rows[2]['recall_macro']-rows[1]['recall_macro'])
        self.assertNotEqual(rows[2]['recall_macro'],rows[2]['recall_micro'])
        with self.assertRaises(ValueError):ranking_rows(d,15)

    def temporary_evidence(self):
        folder=tempfile.TemporaryDirectory();root=Path(folder.name)
        target=root/MANIFEST;target.parent.mkdir(parents=True)
        target.write_text((ROOT/MANIFEST).read_text())
        path=root/'docs/phase4/test_summary.json';path.parent.mkdir(parents=True)
        path.write_bytes((ROOT/'docs/phase4/test_summary.json').read_bytes())
        return folder,root,path

    def test_missing_and_malformed_data_raise_actionable_errors(self):
        folder,root,path=self.temporary_evidence()
        try:
            path.unlink()
            with self.assertRaises(EvidenceError):load_evidence('purchase',root)
            path.write_text('{bad')
            with self.assertRaises(EvidenceError):load_evidence('purchase',root)
            path.write_text('{"models":{}}')
            with self.assertRaises(EvidenceError):load_evidence('purchase',root)
        finally:folder.cleanup()

    def test_valid_json_wrong_structure_and_nonfinite_numbers(self):
        folder,root,path=self.temporary_evidence()
        try:
            path.write_text('{}');manifest=json.loads((root/MANIFEST).read_text())
            manifest['sources']['purchase']['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
            (root/MANIFEST).write_text(json.dumps(manifest))
            with self.assertRaisesRegex(EvidenceError,'structure'):load_evidence('purchase',root)
            path.write_text('{"x": NaN}')
            with self.assertRaises(EvidenceError):load_evidence('purchase',root)
        finally:folder.cleanup()

    def test_allowlist_cannot_escape_docs(self):
        folder,root,path=self.temporary_evidence()
        try:
            m=json.loads((root/MANIFEST).read_text());m['sources']['purchase']['path']='docs/../data/private.json'
            (root/MANIFEST).write_text(json.dumps(m))
            with self.assertRaisesRegex(EvidenceError,'allowlisted'):load_evidence('purchase',root)
            with self.assertRaises(EvidenceError):load_evidence('unknown',root)
        finally:folder.cleanup()


class CalculatorTests(unittest.TestCase):
    def test_balanced_design_reuses_verified_phase8_result(self):
        r=plan_experiment(.2,.03,.05,.8,.5)
        old=two_proportion_sample_size(.2,.03,.05,.8)
        self.assertEqual((r['control_n'],r['treatment_n'],r['total_n']),(2943,2943,5886))
        for k in old:self.assertEqual(r[k],old[k])

    def test_unequal_design_independent_two_tail_power_check(self):
        for q in (.2,.3,.7,.8):
            r=plan_experiment(.2,.03,.05,.8,q);nc,nt=r['control_n'],r['treatment_n']
            pooled=(nc*.2+nt*.23)/(nc+nt)
            threshold=norm.isf(.05/2)*math.sqrt(pooled*(1-pooled)*(1/nc+1/nt))
            se=math.sqrt(.2*.8/nc+.23*.77/nt)
            power=norm.sf((threshold-.03)/se)+norm.cdf((-threshold-.03)/se)
            self.assertAlmostEqual(power,.8,delta=.001)
            self.assertAlmostEqual(nt/(nc+nt),q,delta=.001)
            self.assertAlmostEqual(r['pooled_rate'],(.2+(q/(1-q))*.23)/(1+q/(1-q)))
            self.assertTrue(r['method'].startswith('unequal-arm'))

    def test_invalid_design_not_silently_planned(self):
        for args in [(.99,.03,.05,.8,.5),(.2,.03,.05,.8,0),(.2,-.03,.05,.8,.5)]:
            with self.assertRaises(ValueError):plan_experiment(*args)

    def test_interactive_reference_economics_exact(self):
        d=result_payload(scenario_from_inputs(1000,20,23,20,5,100,0))
        self.assertEqual(d['expected_values']['expected_incremental_purchasers'],'30')
        self.assertEqual(d['expected_values']['total_reward_expenditure_eur'],'1150')
        self.assertEqual(d['expected_values']['net_incremental_contribution_eur'],'-550')
        self.assertEqual(d['break_even']['required_treatment_probability']['exact_fraction'],'4/15')

    def test_reward_input_changes_and_zero_contacts(self):
        self.assertEqual(result_payload(scenario_from_inputs(1000,20,23,20,0,100,0))['expected_values']['net_incremental_contribution_eur'],'600')
        self.assertEqual(result_payload(scenario_from_inputs(0,20,23,20,5,100,0))['break_even']['status'],'no_customers')

    def test_scenario_comparability_and_source_reuse(self):
        config=load_evidence('reward_config');ids=[s['scenario_id'] for s in config['scenarios']]
        r=compare_with_saved(scenario_from_inputs(1000,20,23,20,5,100,0),config,ids)
        self.assertTrue(r['comparable_by_declared_criteria'])
        self.assertEqual(r['ranking'][0]['net_incremental_contribution_eur'],'500')
        changed=compare_with_saved(scenario_from_inputs(2000,20,23,20,5,100,0),config,ids)
        self.assertIsNone(changed['ranking'])

    def test_sensitivity_changes_only_declared_assumption(self):
        r=sensitivity_points(scenario_from_inputs(1000,20,23,20,5,100,0),'reward_per_redemption_eur',0,10,3)
        values=[p['evaluation']['engine_result'] for p in r['points']]
        self.assertEqual([v['expected_values']['net_incremental_contribution_eur'] for v in values],['600','-550','-1700'])
        self.assertTrue(all(v['inputs']['treatment_conversion']=='0.23' for v in values))
        with self.assertRaises(ValueError):sensitivity_points(scenario_from_inputs(1,20,23,20,5,100,0),'redemption_probability',0,2,3)


if __name__=='__main__':unittest.main()
