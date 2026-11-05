"""Pre-access synthetic tests for the frozen final RetailHero evaluation."""
import ast
import copy
import json
import platform
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb
import numpy as np
import sklearn
from threadpoolctl import threadpool_limits

from growthlab.retailhero.acquire import sha256
from growthlab.retailhero.final_evaluation import (
    CONFIG, calculate, check_prior_states, claim_access, evaluate, membership_metadata,
    predict_without_fit, verify, verify_freeze,
)
from growthlab.retailhero.uplift_metrics import policy_mask, ranking


class FinalCalculationTests(unittest.TestCase):
    def setUp(self):
        self.ids=np.array([f'{i:010x}' for i in range(24)])
        self.t=np.arange(24)%2; self.y=(np.arange(24)%3==0).astype(int)
        self.scores={'constant':np.full(24,.03),'response':np.linspace(.1,.9,24),
                     's_learner':np.linspace(.2,-.1,24),'t_learner':np.sin(np.arange(24))*.1}
        self.config=copy.deepcopy(CONFIG); self.config['bootstrap_draws']=30

    def run_example(self):
        with threadpool_limits(limits=1):
            return calculate(self.ids,self.t,self.y,self.scores,self.config)

    def test_primary_pair_is_fixed_even_if_a_secondary_has_better_value(self):
        result,_,_=self.run_example()
        self.assertEqual(result['primary']['comparison'],'s_learner/30% minus constant/30%')
        self.assertEqual(CONFIG['primary_challenger'],'s_learner')
        self.assertEqual(CONFIG['primary_budget'],.3)

    def test_policy_counts_and_contact_fractions(self):
        result,_,_=self.run_example()
        for name in self.scores:
            for percent,count in [(10,3),(20,5),(30,8)]:
                row=result['policies'][f'{name}/{percent}%']
                self.assertEqual(row['selected_n'],count)
                self.assertEqual(row['contact_fraction'],count/24)
        self.assertEqual(result['policies']['none']['selected_n'],0)
        self.assertEqual(result['policies']['all']['selected_n'],24)

    def test_exact_real_cohort_budget_counts_without_outcomes(self):
        for budget,n in [(.1,4001),(.2,8002),(.3,12003)]:
            self.assertEqual(policy_mask(np.arange(40009),budget).sum(),n)

    def test_incremental_value_matches_independent_direct_sum(self):
        result,_,_=self.run_example()
        order=ranking(self.scores['s_learner'],self.ids,CONFIG['ranking_seed'])
        chosen=set(order[:8]); total=0
        for i in range(24):
            if i in chosen: total += 2*self.y[i] if self.t[i] else -2*self.y[i]
        self.assertAlmostEqual(result['policies']['s_learner/30%']['incremental_value'],total/24)

    def test_paired_interval_uses_same_draws(self):
        result,draws,_=self.run_example()
        delta=draws['s_learner/30%/incremental_value']-draws['constant/30%/incremental_value']
        np.testing.assert_array_equal(result['primary']['ci95'],np.quantile(delta,[.025,.975]))
        self.assertAlmostEqual(result['primary']['difference_per_1000'],1000*result['primary']['difference'])

    def test_full_reproducibility(self):
        a,da,_=self.run_example(); b,db,_=self.run_example()
        self.assertEqual(a,b)
        for name in da: np.testing.assert_array_equal(da[name],db[name])

    def test_all_curve_endpoints_are_contact_all_gain(self):
        result,_,curves=self.run_example()
        for name,(x,g) in curves.items():
            self.assertEqual(x[-1],1)
            self.assertAlmostEqual(g[-1],result['policies']['all']['incremental_value'])
            self.assertAlmostEqual(result['metrics'][name]['qini_area'],result['metrics'][name]['auuc']-g[-1]/2)

    def test_constant_ties_equal_fixed_random_order(self):
        order=ranking(self.scores['constant'],self.ids,CONFIG['ranking_seed'])
        random=ranking(np.zeros(24),self.ids,CONFIG['ranking_seed'])
        np.testing.assert_array_equal(order,random)

    def test_all_none_and_propensity_sensitivity_exist(self):
        result,_,_=self.run_example()
        self.assertEqual(result['policies']['none']['incremental_value'],0)
        self.assertEqual(set(result['propensity_sensitivity']),{'0.45','0.55','0.5'})
        self.assertIn('s_learner/30% minus all',result['paired_policy_differences'])


class MembershipTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.split=self.root/'splits.parquet'; self.features=self.root/'features.parquet'
        self.con=duckdb.connect()
        self.con.execute("""CREATE TABLE members AS SELECT 'id'||cast(row_number() OVER() AS VARCHAR) AS client_id,
            treatment_flg,split FROM (VALUES ('final_test',0,20012),('final_test',1,19997),
            ('train',0,60034),('train',1,59988),('validation',0,20012),('validation',1,19996))
            v(split,treatment_flg,n),LATERAL range(n)""")
        self.con.execute('COPY members TO ? (FORMAT PARQUET)',[str(self.split)])
        self.con.execute('COPY members TO ? (FORMAT PARQUET)',[str(self.features)])

    def tearDown(self):
        self.con.close(); self.temp.cleanup()

    def test_exact_frozen_counts_unique_disjoint_membership_and_hash(self):
        m=membership_metadata(self.con,self.split,self.features)
        self.assertEqual(m['n'],40009)
        self.assertEqual(m['control_n'],20012)
        self.assertEqual(m['treated_n'],19997)
        self.assertEqual(sum(r['n'] for r in m['split_counts']),200039)
        self.assertEqual(len(m['sorted_final_id_treatment_sha256']),64)

    def test_changed_split_assignment_rejected(self):
        altered=self.root/'altered.parquet'
        self.con.execute("COPY (SELECT client_id,treatment_flg,CASE WHEN client_id='id1' THEN 'train' ELSE split END AS split FROM members) TO ? (FORMAT PARQUET)",[str(altered)])
        with self.assertRaisesRegex(ValueError,'assignment mismatch'):
            membership_metadata(self.con,self.split,altered)

    def test_overlap_or_duplicate_join_key_rejected(self):
        altered=self.root/'duplicated.parquet'
        self.con.execute('COPY (SELECT * FROM members UNION ALL SELECT * FROM members LIMIT 200040) TO ? (FORMAT PARQUET)',[str(altered)])
        with self.assertRaisesRegex(ValueError,'unique/complete'):
            membership_metadata(self.con,altered,self.features)


class FreezeAndIsolationTests(unittest.TestCase):
    def test_exclusive_access_ledger_blocks_second_evaluation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); path=root/'data/retailhero/phase7/final_access_ledger.json'
            claim_access(path,'abc')
            before=path.read_bytes()
            with self.assertRaises(FileExistsError): claim_access(path,'abc')
            self.assertEqual(before,path.read_bytes())
            with patch('growthlab.retailhero.final_evaluation.verify_freeze',return_value={}), \
                 patch('growthlab.retailhero.final_evaluation.load_final_features',side_effect=AssertionError('reload')):
                with self.assertRaisesRegex(FileExistsError,'already claimed'): evaluate(root)

    def test_no_fit_during_saved_model_prediction(self):
        class SavedEstimator:
            def predict_proba(self,X): return np.tile([.4,.6],(len(X),1))
            def fit(self,*args): raise AssertionError('fit called')
        models={name:SavedEstimator() for name in ['response','s_learner','t_control','t_treated']}
        models['constant']=.03
        scores,_=predict_without_fit(models,np.zeros((5,8)))
        np.testing.assert_array_equal(scores['s_learner'],np.zeros(5))
        np.testing.assert_array_equal(scores['t_learner'],np.zeros(5))

    def test_class_fit_is_actively_blocked(self):
        from sklearn.ensemble import HistGradientBoostingClassifier
        class MisbehavingEstimator:
            def predict_proba(self,X): return HistGradientBoostingClassifier().fit(X,np.zeros(len(X)))
        with self.assertRaisesRegex(RuntimeError,'refitting forbidden'):
            predict_without_fit({'response':MisbehavingEstimator()},np.zeros((5,8)))

    def test_verify_path_has_no_outcome_loader_or_prediction_call(self):
        import inspect
        tree=ast.parse(inspect.getsource(verify))
        names={node.id for node in ast.walk(tree) if isinstance(node,ast.Name)}
        self.assertTrue(names.isdisjoint({'read_labels','load_final_features','predict_without_fit','joblib'}))

    def test_changed_raw_or_model_input_hash_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); docs=root/'docs/causal/phase7'; docs.mkdir(parents=True)
            artifact=root/'immutable'; artifact.write_bytes(b'original')
            protocol={'config':CONFIG,'versions':{'python':platform.python_version(),'sklearn':sklearn.__version__,
                'numpy':np.__version__,'duckdb':duckdb.__version__},'inputs_sha256':{'immutable':sha256(artifact)},'cohort':{}}
            p=docs/'frozen_protocol.json'; p.write_text(json.dumps(protocol))
            (docs/'readiness_receipt.json').write_text(json.dumps({'protocol_sha256':sha256(p)}))
            with patch('growthlab.retailhero.final_evaluation.metadata',return_value={}):
                verify_freeze(root)
                artifact.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'frozen input changed'): verify_freeze(root)

    def test_prior_file_states_detect_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); local=root/'data/retailhero/phase7'; local.mkdir(parents=True)
            raw=root/'raw'; raw.write_bytes(b'fixed')
            (local/'prior_file_states.json').write_text(json.dumps({'raw':[raw.stat().st_size,raw.stat().st_mtime_ns]}))
            self.assertEqual(check_prior_states(root),1)
            raw.write_bytes(b'changed size')
            with self.assertRaisesRegex(ValueError,'prior data/artifact'): check_prior_states(root)


if __name__=='__main__': unittest.main()
