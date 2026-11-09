"""Synthetic tests for past-only features, one fixed fit and paired inference."""
from datetime import datetime
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb
import numpy as np
from threadpoolctl import threadpool_limits

from growthlab.ml_reranking import (
    FEATURES, feature_vector, prepare_features, retained_negative,
    training_arrays, fit_model, ml_order, paired_bootstrap, validation_evaluation, feature_storage_bytes,
)


def protocol():
    return json.loads((Path(__file__).resolve().parents[1]/'docs/ranking/phase10b2b_protocol.json').read_text())


class FeatureTests(unittest.TestCase):
    def test_resource_summary_joins_path_instead_of_subscripting_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'a').write_bytes(b'abc');(root/'b').write_bytes(b'12345')
            self.assertEqual(feature_storage_bytes(root,{'train':{'path':'a'},'validation':{'path':'b'}}),8)

    def test_hand_computable_seen_product(self):
        cutoff=datetime(2019,12,1)
        history={10:(2,1,1,datetime(2019,11,30,12),5)}
        self.assertEqual(feature_vector(10,history,8,{10:7},cutoff),(2,1,1,12.,7,8,1))

    def test_backfill_has_zero_counts_missing_recency_and_source_flag(self):
        vector=feature_vector(20,{},8,{20:7},datetime(2019,12,1))
        self.assertEqual(vector[:3],(0,0,0));self.assertTrue(math.isnan(vector[3]))
        self.assertEqual(vector[4:],(7,8,0))

    def test_future_and_prediction_time_forbidden(self):
        for t in [datetime(2019,12,1),datetime(2019,12,2)]:
            with self.assertRaises(ValueError):feature_vector(10,{10:(1,0,0,t,1)},1,{},datetime(2019,12,1))

    def test_removal_only_activity_not_mislabeled_as_views(self):
        v=feature_vector(10,{10:(0,0,0,datetime(2019,11,30),2)},2,{},datetime(2019,12,1))
        self.assertEqual(v,(0,0,0,24.,0,2,1))

    def test_sql_boundaries_counts_buyers_and_total_activity(self):
        with tempfile.TemporaryDirectory() as temp:
            c=duckdb.connect()
            c.execute('CREATE TABLE events(user_key BIGINT,product_key BIGINT,event_ts TIMESTAMP,event_type VARCHAR)')
            c.executemany('INSERT INTO events VALUES(?,?,?,?)',[
                (1,10,'2019-11-01','view'),(1,10,'2019-11-02','view'),
                (1,10,'2019-11-03','cart'),(1,10,'2019-11-04','purchase'),
                (1,10,'2019-11-05','purchase'),(1,20,'2019-11-06','remove_from_cart'),
                (2,10,'2019-11-07','purchase'),(1,10,'2019-12-01','view'),
                (1,99,'2019-10-31 23:59:59','cart')])
            path=Path(temp)/'events.parquet';c.execute(f"COPY events TO '{path}' (FORMAT PARQUET)")
            stats=prepare_features(c,path,'validation')
            self.assertEqual(stats['historical_events'],7)
            self.assertEqual(c.execute('SELECT views,carts,purchases,events FROM ui WHERE user_key=1 AND product_key=10').fetchone(),(2,1,2,5))
            self.assertEqual(c.execute('SELECT buyers FROM products WHERE product_key=10').fetchone()[0],2)
            self.assertEqual(c.execute('SELECT events FROM customers WHERE user_key=1').fetchone()[0],6)
            self.assertEqual(c.execute('SELECT count(*) FROM ui WHERE product_key=99').fetchone()[0],0)
            c.close()

    def test_final_feature_snapshot_blocked_before_io(self):
        with self.assertRaises(ValueError):prepare_features(duckdb.connect(),'missing.parquet','final_test')


class SamplingAndTrainingTests(unittest.TestCase):
    def test_sampling_reproducible_and_seed_sensitive(self):
        a=[retained_negative(1,p,7) for p in range(5000)]
        self.assertEqual(a,[retained_negative(1,p,7) for p in range(5000)])
        self.assertNotEqual(a,[retained_negative(1,p,8) for p in range(5000)])
        self.assertTrue(60<sum(a)<150)

    def test_all_positives_retained_weights_and_label_assignment(self):
        candidates=list(range(100))
        batch=[(1,candidates,{})]
        history={1:{10:(1,0,0,datetime(2019,10,30),1)}}
        synthetic=[(batch,history,{1:1},{},datetime(2019,11,1))]
        from growthlab.ranking_baselines import append_hash
        import hashlib
        h=hashlib.sha256();append_hash(h,1,candidates)
        with patch('growthlab.ml_reranking.feature_batches',return_value=synthetic):
            x,y,w,stats=training_arrays(None,None,{1:{10,999}},h.hexdigest(),protocol())
        self.assertEqual(stats['full_positive_rows'],1)
        self.assertEqual(int(y.sum()),1)
        self.assertTrue(np.all(w[y==1]==1))
        self.assertTrue(np.all(w[y==0]==50))
        self.assertEqual(x.shape[1],len(FEATURES))
        self.assertEqual(x[y==1][0,0],1)

    def test_validation_cannot_be_sampled_for_training(self):
        with self.assertRaisesRegex(ValueError,'Only training'):training_arrays(None,None,{},'',protocol(),'validation')

    def test_validation_and_final_cannot_fit(self):
        for split in ['validation','final_test']:
            with self.assertRaises(ValueError):fit_model(None,None,None,protocol(),split)

    def test_feature_schema_guard(self):
        with self.assertRaises(ValueError):fit_model(np.zeros((2,2)),np.array([0,1]),np.ones(2),protocol())

    def test_reproducible_small_fit_and_scores(self):
        rng=np.random.default_rng(9)
        x=rng.normal(size=(300,len(FEATURES))).astype(np.float32)
        y=(x[:,0]+x[:,1]>0).astype(np.uint8);w=np.ones(300)
        p=protocol();p['model_parameters'].update(max_iter=8,min_samples_leaf=10)
        a=fit_model(x,y,w,p);b=fit_model(x,y,w,p)
        with threadpool_limits(limits=1):
            self.assertTrue(np.array_equal(a.decision_function(x),b.decision_function(x)))


class OrderingAndUncertaintyTests(unittest.TestCase):
    def test_all_evaluation_candidates_scored_and_selection_needs_both_primary_bounds(self):
        import hashlib
        from unittest.mock import MagicMock
        from growthlab.ranking_baselines import append_hash, order_candidates, ranking_metrics
        candidates=list(range(100));now=datetime(2019,12,1)
        histories={1:{10:(1,0,0,datetime(2019,11,30),1)},2:{}}
        batch=[(1,candidates,{10:datetime(2019,11,30)}),(2,candidates,{})]
        sources=[(batch,histories,{1:1,2:0},{1:5},now)]
        h=hashlib.sha256()
        for u,c,_ in batch:append_hash(h,u,c)
        labels={1:{10,999}}
        ordered=order_candidates(candidates,batch[0][2],{1:5})
        baseline={'freeze':{'canonical_candidate_sha256':h.hexdigest()},
            'groups':{'all':{'candidate_hits':1,'methods':{
                m:{k:{'hits':v['hits'],'recall_macro':v['recall'],'recall_micro':v['recall'],'ndcg_macro':v['ndcg']}
                for k,v in ranking_metrics(order,labels[1]).items()} for m,order in ordered.items()}}}}
        class FakeModel:
            def __init__(self):self.shapes=[]
            def decision_function(self,x):
                self.shapes.append(x.shape)
                return x[:,0]  # deterministic view-count score
        for lower,expected in [([0,0,.01,.01,0,0],'ml'),([0,0,.01,-.01,0,0],'personal_recency')]:
            model=FakeModel();p=protocol()
            with patch('growthlab.ml_reranking.feature_batches',return_value=sources),patch('growthlab.ml_reranking.paired_bootstrap',return_value={'lower_95':lower}):
                result,_,_=validation_evaluation(None,None,labels,model,baseline,p)
            self.assertEqual(model.shapes[0],(200,len(FEATURES)))
            self.assertEqual(result['eligible_users'],2)
            self.assertEqual(result['purchasing_users'],1)
            self.assertEqual(result['selected_method'],expected)
            self.assertEqual(set(result['method_universe_sha256'].values()),{h.hexdigest()})

    def test_ml_reorders_same_candidates_and_recency_breaks_ties(self):
        candidates=[1,2,3];recent=[3,1,2]
        self.assertEqual(ml_order(candidates,np.array([.5,.5,.2]),recent),[1,2,3])
        self.assertEqual(ml_order(candidates,np.zeros(3),recent),recent)

    def test_invalid_universe_or_scores_rejected(self):
        for candidates,scores,recent in [([1,1],[0,0],[1,1]),([1,2],[0],[1,2]),([1,2],[0,1],[1,3]),([1,2],[0,np.nan],[1,2])]:
            with self.assertRaises(ValueError):ml_order(candidates,np.asarray(scores),recent)

    def test_paired_bootstrap_constant_shift_exact(self):
        spec=protocol()['uncertainty'];spec.update(replications=50,replication_batch=7)
        result=paired_bootstrap(np.tile([.1,-.2],(20,1)),spec)
        np.testing.assert_allclose(result['mean_difference'],[.1,-.2])
        np.testing.assert_allclose(result['lower_95'],[.1,-.2])
        np.testing.assert_allclose(result['upper_95'],[.1,-.2])

    def test_paired_bootstrap_reproducible_and_no_shuffle_pairing(self):
        values=np.array([[.2,-.1],[0,.2],[-.1,0],[.4,.3]])
        spec=protocol()['uncertainty'];spec['replications']=40
        self.assertEqual(paired_bootstrap(values,spec),paired_bootstrap(values,spec))
        np.testing.assert_allclose(paired_bootstrap(values,spec)['mean_difference'],values.mean(axis=0))

    def test_zero_difference_and_invalid_samples(self):
        spec=protocol()['uncertainty'];spec['replications']=20
        self.assertEqual(paired_bootstrap(np.zeros((10,2)),spec)['lower_95'],[0.,0.])
        for values in [[],[1,2],[[np.nan]]]:
            with self.assertRaises(ValueError):paired_bootstrap(values,spec)


if __name__=='__main__':unittest.main()
