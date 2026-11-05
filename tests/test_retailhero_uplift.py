"""Small explicit examples for history, isolation, uplift curves, and policies."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb
import numpy as np
from threadpoolctl import threadpool_limits

from growthlab.retailhero.acquire import sha256
from growthlab.retailhero.history import FEATURE_COLUMNS, aggregate_features, audit_history, load_history
from growthlab.retailhero.uplift import fit_models, load_cohort, predict_models, read_labels
from growthlab.retailhero.uplift_metrics import (bootstrap_evaluation, gain_curve,
                                               policy_mask, policy_value, ranking)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.y=np.array([1,0,0,1]);self.t=np.array([1,0,1,0]);self.order=np.arange(4)

    def test_hand_worked_gain_and_qini(self):
        x,g,m=gain_curve(self.y,self.t,self.order)
        np.testing.assert_allclose(x,[0,.25,.5,.75,1])
        np.testing.assert_allclose(g,[0,.5,.5,.5,0])
        self.assertEqual(m['auuc'],.375)
        self.assertEqual(m['qini_area'],.375)

    def test_hand_worked_policy_values(self):
        none=policy_value(self.y,self.t,np.zeros(4))
        all_=policy_value(self.y,self.t,np.ones(4))
        top=policy_value(self.y,self.t,np.array([1,0,0,0]))
        self.assertEqual(none['value'],.5)
        self.assertEqual(none['incremental_value'],0)
        self.assertEqual(all_['value'],.5)
        self.assertEqual(top['value'],1)
        self.assertEqual(top['incremental_value'],.5)

    def test_ipw_uses_control_outcomes_for_selected_customers(self):
        result=policy_value(self.y,self.t,np.array([0,0,0,1]))
        self.assertEqual(result['incremental_value'],-.5)
        self.assertEqual(result['value'],0)

    def test_stochastic_random_expected_policy_identity(self):
        full=policy_value(self.y,self.t,np.ones(4))
        random=policy_value(self.y,self.t,np.full(4,.3))
        self.assertAlmostEqual(random['incremental_value'],.3*full['incremental_value'])

    def test_unequal_propensity_hand_example(self):
        v=policy_value([1,1],[1,0],[1,1],.25)
        self.assertAlmostEqual(v['value'],2)
        self.assertAlmostEqual(v['incremental_value'],(4-1/.75)/2)

    def test_budget_counts_and_nested_membership(self):
        n=40008;order=np.arange(n)[::-1]
        previous=np.zeros(n)
        for budget,count in [(.1,4001),(.2,8002),(.3,12003),(1,40008)]:
            mask=policy_mask(order,budget)
            self.assertEqual(mask.sum(),count)
            self.assertTrue((mask>=previous).all());previous=mask
        self.assertEqual(policy_mask(order,0).sum(),0)

    def test_ties_are_reproducible_and_label_blind(self):
        ids=np.array(['a','b','c','d'])
        a=ranking(np.zeros(4),ids,42);b=ranking(np.ones(4),ids,42)
        np.testing.assert_array_equal(a,b)
        self.assertNotEqual(ranking(np.zeros(4),ids,43).tolist(),a.tolist())
        np.testing.assert_array_equal(ranking(np.arange(4),ids,42),[3,2,1,0])

    def test_invalid_metric_inputs_rejected(self):
        for y,t,p in [([2],[1],.5),([1],[2],.5),([1],[1],0),([1],[1],1),([] ,[],.5)]:
            with self.subTest(y=y,t=t,p=p),self.assertRaises(ValueError):
                gain_curve(y,t,np.arange(len(y)),p)
        with self.assertRaises(ValueError): policy_mask([0,0],.5)
        with self.assertRaises(ValueError): ranking([np.nan],['a'],42)
        with self.assertRaises(ValueError): policy_value([1],[1],[2])

    def test_paired_bootstrap_identical_policy_difference_zero(self):
        a=bootstrap_evaluation(self.y,self.t,{'a':self.order,'b':self.order},draws=20,seed=4)
        b=bootstrap_evaluation(self.y,self.t,{'a':self.order,'b':self.order},draws=20,seed=4)
        for k in a: np.testing.assert_array_equal(a[k],b[k])
        np.testing.assert_array_equal(a['a/30%/value'],a['b/30%/value'])
        np.testing.assert_array_equal(a['none/incremental_value'],np.zeros(20))

    def test_bootstrap_curve_weighting_equals_explicit_resampling(self):
        seed=8
        a=bootstrap_evaluation(self.y,self.t,{'a':self.order},draws=1,seed=seed)
        rng=np.random.default_rng(seed)
        sampled=np.r_[rng.choice([1,3],2,replace=True),rng.choice([0,2],2,replace=True)]
        sampled.sort()  # original order is the score ranking here
        _,_,m=gain_curve(self.y[sampled],self.t[sampled],np.arange(4))
        self.assertAlmostEqual(a['a/auuc'][0],m['auuc'])
        explicit=policy_value(self.y[sampled],self.t[sampled],policy_mask(np.arange(4),.3))
        self.assertAlmostEqual(a['a/30%/value'][0],explicit['value'])


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.path=self.root/'history.csv'
        header='client_id,transaction_id,transaction_datetime,regular_points_received,express_points_received,regular_points_spent,express_points_spent,purchase_sum,store_id,product_id,product_quantity,trn_sum_from_iss,trn_sum_from_red\n'
        rows=[('000000000a','a','2019-01-01 12:00:00','10','p1'),
              ('000000000a','a','2019-01-01 12:00:00','10','p2'),
              ('000000000a','b','2019-01-03 12:00:00','20','p3'),
              ('000000000b','c','2019-01-02 12:00:00','-5','p1'),
              ('000000000c','d','2019-01-02 12:00:00','0','p1'),
              ('000000000d','e','2019-01-02 12:00:00','30','p1'),
              ('000000000d','e','2019-01-02 12:00:00','31','p2'),
              ('000000000e','f','2019-01-04 00:00:00','100','p1')]
        self.path.write_text(header+''.join(f'{u},{tx},{ts},0,0,0,0,{amount},s,{product},1,0,0\n' for u,tx,ts,amount,product in rows))
        self.con=duckdb.connect();load_history(self.con,self.path)
        self.audit=audit_history(self.con)

    def tearDown(self):
        self.con.close();self.temp.cleanup()

    def features(self):
        aggregate_features(self.con,'2019-01-04 00:00:00')
        names=['client_id',*FEATURE_COLUMNS]
        rows=self.con.execute('SELECT '+','.join(names)+' FROM customer_features ORDER BY client_id').fetchall()
        return {r[0]:dict(zip(names[1:],r[1:])) for r in rows}

    def test_transaction_totals_not_summed_per_product(self):
        a=self.features()['000000000a']
        self.assertEqual(a['transaction_count'],2)
        self.assertEqual(a['historical_spend'],30)
        self.assertEqual(a['mean_transaction_value'],15)
        self.assertEqual(a['active_shopping_days'],2)
        self.assertEqual(a['distinct_products'],3)
        self.assertEqual(a['days_since_last_purchase'],.5)

    def test_negative_zero_and_inconsistent_money_preserve_activity(self):
        f=self.features()
        self.assertEqual(f['000000000b']['transaction_count'],1)
        self.assertIsNone(f['000000000b']['historical_spend'])
        self.assertEqual(f['000000000c']['historical_spend'],0)
        self.assertEqual(f['000000000d']['transaction_count'],1)
        self.assertIsNone(f['000000000d']['historical_spend'])
        self.assertEqual(self.audit['transaction_quality']['inconsistent_amounts'],1)

    def test_cutoff_is_exclusive(self):
        f=self.features();self.assertNotIn('000000000e',f)
        self.assertTrue(all(v['days_since_last_purchase']>=0 for v in f.values()))

    def test_raw_unchanged_by_sql(self):
        before=sha256(self.path);self.features()
        self.assertEqual(before,sha256(self.path))

    def test_duplicate_item_rows_do_not_inflate_transaction_features(self):
        before=self.features()
        self.con.execute('INSERT INTO history SELECT * FROM history LIMIT 1')
        result=audit_history(self.con)
        self.assertEqual(result['typed_duplicate_row_excess'],1)
        self.assertEqual(before,self.features())

    def test_inconsistent_transaction_timestamps_rejected(self):
        self.con.execute("UPDATE history SET transaction_datetime='2019-01-02' WHERE product_id='p2' AND transaction_id='a'")
        with self.assertRaisesRegex(ValueError,'consistency failed'): audit_history(self.con)


class ModelIsolationTests(unittest.TestCase):
    def test_final_holdout_denied_before_any_file_access(self):
        with patch('pathlib.Path.read_text',side_effect=AssertionError('file access')):
            with self.assertRaisesRegex(ValueError,'forbidden'): load_cohort(Path('/absent'),'final_test')

    def test_disallowed_labels_never_parsed(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'labels.csv'
            path.write_text('client_id,treatment_flg,target\ntrain,1,1\nholdout,INVALID,FORBIDDEN\n')
            self.assertEqual(read_labels(path,{'train'}),{'train':(1,1)})

    def test_treatment_models_fit_only_their_arm(self):
        calls=[]
        class Spy:
            def __init__(self,**kwargs): pass
            def fit(self,X,y): calls.append((X.copy(),y.copy()));return self
        X=np.arange(8*20).reshape(20,8);t=np.arange(20)%2;y=(np.arange(20)%3==0).astype(int)
        fit_models(X,t,y,{},factory=Spy)
        np.testing.assert_array_equal(calls[0][0],X)
        np.testing.assert_array_equal(calls[1][0][:,-1],t)
        np.testing.assert_array_equal(calls[2][0],X[t==0])
        np.testing.assert_array_equal(calls[2][1],y[t==0])
        np.testing.assert_array_equal(calls[3][0],X[t==1])
        np.testing.assert_array_equal(calls[3][1],y[t==1])

    def test_native_preprocessing_train_only_valid_predictions_and_reproducibility(self):
        rng=np.random.default_rng(42);X=rng.normal(size=(80,8));X[0,0]=np.nan
        t=np.arange(80)%2;y=rng.integers(0,2,80)
        params={'max_iter':5,'max_depth':2,'min_samples_leaf':5,'early_stopping':False,'random_state':42}
        with threadpool_limits(limits=1):
            a=fit_models(X,t,y,params);b=fit_models(X,t,y,params)
            thresholds=a['response']._bin_mapper.bin_thresholds_[0].copy()
            future=np.full((5,8),1e6);future[0,0]=np.nan
            scores,_=predict_models(a,future);again,_=predict_models(b,future)
        np.testing.assert_array_equal(thresholds,a['response']._bin_mapper.bin_thresholds_[0])
        for n in scores:
            np.testing.assert_array_equal(scores[n],again[n])
            self.assertTrue(np.isfinite(scores[n]).all())
        self.assertTrue((np.abs(scores['t_learner'])<=1).all())


if __name__=='__main__': unittest.main()
