"""Synthetic final-evaluation checks; never open real held-out outcomes."""
import ast
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb
import numpy as np

from growthlab.ranking_final import (
    build_history, final_batches, membership, load_final_labels, claim_access,
    score_final, evaluate_once, verify_saved, verify_ready, save_json,
)
from growthlab.ranking_audit import digest


class FakeModel:
    def decision_function(self,x):return x[:,0]
    def fit(self,*args,**kwargs):raise AssertionError('No final-data fitting')


class FinalFixture(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.root=Path(self.folder.name)
        self.work=self.root/'data/ranking/phase10c';self.work.mkdir(parents=True)
        self.db=self.work/'history.duckdb';self.con=duckdb.connect(str(self.db))
        self.con.execute('CREATE TABLE history_events(user_key BIGINT,product_key BIGINT,event_ts TIMESTAMP,event_type VARCHAR)')
        values=[(1000+p,p,'2019-12-01','purchase') for p in range(1,101)]
        values += [(1,999,'2019-12-31','view'),(2,2,'2019-12-03','purchase'),
                   (1,888,'2020-01-01','cart'),(3,887,'2019-11-30 23:59:59','view')]
        self.con.executemany('INSERT INTO history_events VALUES(?,?,?,?)',values)
        self.stats=build_history(self.con);self.members=membership(self.con,17)
        self.path=self.work/'outcomes.parquet'
        c=duckdb.connect()
        c.execute('CREATE TABLE e(user_key BIGINT,product_key BIGINT,event_ts TIMESTAMP,event_type VARCHAR)')
        c.executemany('INSERT INTO e VALUES(?,?,?,?)',[(1,999,'2020-01-01','purchase'),
            (1,888,'2020-01-14 23:59:59','purchase'),(1,887,'2020-01-15','purchase'),
            (2,2,'2020-01-03','purchase'),(2,2,'2020-01-03','purchase'),
            (9999,1,'2020-01-01','purchase')])
        c.execute(f"COPY e TO '{self.path}' (FORMAT PARQUET)");c.close()
        self.receipt={'labels_authorized':True,'freeze_sha256':'fixed'}
        self.protocol={'customer_batch_size':17,'memory_limit':'64MB','spill_cap':'128MB',
            'uncertainty':{'replications':30,'seed':20261110,'replication_batch':7,'confidence_level':.95},
            'model_path':'model.joblib','model_sha256':hashlib.sha256(b'unchanged model').hexdigest()}
        (self.root/'model.joblib').write_bytes(b'unchanged model')

    def tearDown(self):
        if self.con is not None:self.con.close()
        self.folder.cleanup()

    def test_history_start_inclusive_prediction_exclusive(self):
        self.assertEqual(self.stats['eligible_customers'],102)
        self.assertEqual(self.stats['historical_events'],102)
        self.assertEqual(self.con.execute('SELECT count(*) FROM ui WHERE product_key IN (887,888)').fetchone()[0],0)

    def test_eligibility_not_selected_using_future_behavior(self):
        self.assertEqual(self.members['eligible_users'],102)
        self.assertEqual(self.members['candidate_rows'],10200)
        labels=load_final_labels(self.con,self.path,self.receipt)
        self.assertEqual(dict(labels),{1:{999,888},2:{2}})
        self.assertNotIn(9999,labels)

    def test_authorization_required_before_outcome_io(self):
        with self.assertRaisesRegex(ValueError,'prior frozen'):
            load_final_labels(self.con,'nonexistent.parquet',None)

    def test_end_exclusive_and_duplicate_purchase_label_handling(self):
        labels=load_final_labels(self.con,self.path,self.receipt)
        self.assertNotIn(887,labels[1]);self.assertEqual(len(labels[2]),1)

    def test_candidate_hash_reproduces_across_batch_sizes(self):
        self.assertEqual(self.members,membership(self.con,29))
        for batch,_,_ in final_batches(self.con,17):
            for _,candidates,_ in batch:self.assertEqual(len(candidates),len(set(candidates)))

    def test_future_history_metadata_is_rejected(self):
        self.con.execute("UPDATE ui SET latest='2020-01-01' WHERE user_key=1")
        with self.assertRaisesRegex(ValueError,'past-only'):membership(self.con)

    def test_all_three_methods_use_same_frozen_universe_and_correct_metrics(self):
        labels=load_final_labels(self.con,self.path,self.receipt)
        result=score_final(self.con,labels,FakeModel(),self.protocol,self.members,self.work)
        self.assertEqual(set(result['method_universe_sha256'].values()),{self.members['candidate_sha256']})
        self.assertEqual(result['eligible_users'],102)
        self.assertEqual(result['purchasing_users'],2)
        self.assertEqual(result['relevant_pairs'],3)
        self.assertAlmostEqual(result['candidate_recall_micro'],2/3)
        self.assertEqual(result['methods']['personal_recency']['10']['recall_macro'],.75)
        self.assertEqual(result['methods']['global_popularity']['10']['recall_macro'],.5)
        self.assertEqual(result['paired_uncertainty']['mean_difference'],[0.]*6)
        self.assertEqual(result['preselected_method'],'ml')

    def test_membership_change_is_rejected(self):
        bad={**self.members,'candidate_sha256':'wrong'}
        with self.assertRaisesRegex(ValueError,'membership changed'):
            score_final(self.con,{},FakeModel(),self.protocol,bad,self.work)

    def test_empty_outcomes_are_not_invented_zero_recall(self):
        r=score_final(self.con,{},FakeModel(),self.protocol,self.members,self.work)
        self.assertIsNone(r['candidate_recall_micro'])
        self.assertIsNone(r['methods']['ml']['10']['recall_macro'])
        self.assertIsNone(r['paired_uncertainty'])

    def test_final_access_is_exclusive(self):
        path=self.work/'access_ledger.json'
        first=claim_access(path,'p','f')
        self.assertTrue(first['labels_authorized'])
        with self.assertRaises(FileExistsError):claim_access(path,'p','f')

    def test_end_to_end_exports_and_verify_never_reopens_outcomes(self):
        self.con.execute('CHECKPOINT');self.con.close();self.con=None
        docs=self.root/'docs/ranking';docs.mkdir(parents=True)
        save_json(docs/'phase10c_freeze.json',{'unit_test':'frozen before fake outcomes'})
        frozen={'history_database_path':str(self.db.relative_to(self.root)),
            'expected_outcome_path':str(self.path.relative_to(self.root)),
            'expected_outcome_sha256':digest(self.path),'protocol_sha256':'p','membership':self.members}
        with patch('growthlab.ranking_final.verify_ready',return_value=(self.protocol,frozen,FakeModel())):
            evaluate_once(self.root)
            self.assertTrue((docs/'phase10c_summary.json').exists())
            self.assertTrue((self.work/'completed_evaluation.json').exists())
            with patch('growthlab.ranking_final.load_final_labels',side_effect=AssertionError('No reopening')):
                verify_saved(self.root)
            with self.assertRaises(FileExistsError):evaluate_once(self.root)

    def test_model_change_is_rejected_by_saved_verification(self):
        self.con.execute('CHECKPOINT');self.con.close();self.con=None
        docs=self.root/'docs/ranking';docs.mkdir(parents=True)
        save_json(docs/'phase10c_freeze.json',{'unit_test':'frozen'})
        frozen={'history_database_path':str(self.db.relative_to(self.root)),
            'expected_outcome_path':str(self.path.relative_to(self.root)),
            'expected_outcome_sha256':digest(self.path),'protocol_sha256':'p','membership':self.members}
        with patch('growthlab.ranking_final.verify_ready',return_value=(self.protocol,frozen,FakeModel())):
            evaluate_once(self.root)
            (self.root/'model.joblib').write_bytes(b'changed model')
            with self.assertRaisesRegex(ValueError,'weights changed'):verify_saved(self.root)

    def test_protocol_change_rejected_before_any_label_reader(self):
        docs=self.root/'docs/ranking';docs.mkdir(parents=True)
        save_json(docs/'phase10c_protocol.json',{'changed':True})
        save_json(docs/'phase10c_freeze.json',{'protocol_sha256':'not the current protocol'})
        with self.assertRaisesRegex(ValueError,'protocol changed'):verify_ready(self.root)

    def test_no_training_api_calls_exist_in_final_module(self):
        source=Path(__file__).resolve().parents[1]/'src/growthlab/ranking_final.py'
        calls=[n.func.attr for n in ast.walk(ast.parse(source.read_text()))
               if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)]
        self.assertNotIn('fit',calls);self.assertNotIn('partial_fit',calls)


if __name__=='__main__':unittest.main()
