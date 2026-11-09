"""Synthetic, hand-counted tests for bounded retrieval; no customer exports."""
from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile
import unittest

import duckdb

from growthlab.candidates import (
    build_history, batch_sources, development_window, empty_metrics, evaluate,
    finish_metrics, interleave, load_labels, retrieve, update_metrics, validate_config,
)


def configuration():
    return json.loads((Path(__file__).resolve().parents[1]/'docs/ranking/phase10b1_config.json').read_text())


class PureRetrievalTests(unittest.TestCase):
    def test_exact_budget_and_no_duplicates(self):
        for budget in (1,50,100,150,200):
            for result in retrieve([2,2,1,3],[3,5,5,2],list(range(1,201)),budget).values():
                self.assertEqual(len(result),budget)
                self.assertEqual(len(set(result)),budget)

    def test_cold_start_falls_back_without_imagined_history(self):
        for value in retrieve([],[],[10,20,30],3).values():
            self.assertEqual(value,[10,20,30])

    def test_small_catalog_not_padded_with_fake_products(self):
        self.assertEqual(retrieve([],[],[10,20],50)['hybrid'],[10,20])

    def test_round_robin_and_first_occurrence(self):
        self.assertEqual(interleave([[1,2,3],[2,4],[1,5,6]],6),[1,2,4,5,3,6])

    def test_deterministic_and_nested_budget_prefixes(self):
        a=retrieve([3,2,1],[4,2,8],list(range(1,201)),200)
        self.assertEqual(a,retrieve([3,2,1],[4,2,8],list(range(1,201)),200))
        b=retrieve([3,2,1],[4,2,8],list(range(1,201)),50)
        for method in a:self.assertEqual(a[method][:50],b[method])

    def test_invalid_budgets_and_config(self):
        for value in (0,201,True,1.5):
            with self.assertRaises(ValueError):retrieve([],[],[],value)
        for name,value in [('budgets',[100,50]),('budgets',[201]),('seed_cap',11),
                           ('graph_history_cap',51),('customer_batch_size',1001),('minimum_pair_users',0)]:
            c=configuration();c[name]=value
            with self.assertRaises(ValueError):validate_config(c)

    def test_final_snapshot_blocked(self):
        with self.assertRaisesRegex(ValueError,'final test'):development_window('final_test')

    def test_recall_denominator_keeps_unrecoverable_products(self):
        stats=empty_metrics()
        update_metrics(stats,[1,2],{2,999})
        update_metrics(stats,[],{5})
        update_metrics(stats,[3],set())
        result=finish_metrics(stats,3,{10:{2,999},20:{5}})
        self.assertAlmostEqual(result['pair_recall'],1/3)
        self.assertEqual(result['mean_user_recall'],.25)
        self.assertEqual(result['median_candidates'],1)
        self.assertAlmostEqual(result['eligible_user_coverage'],2/3)
        self.assertEqual(result['purchasing_user_coverage'],.5)

    def test_empty_outcomes_have_no_invented_recall(self):
        stats=empty_metrics();update_metrics(stats,[1],set())
        self.assertIsNone(finish_metrics(stats,1,{})['pair_recall'])


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.con=duckdb.connect()
        self.con.execute('CREATE TABLE history_events(user_key BIGINT,product_key BIGINT,event_ts TIMESTAMP,event_type VARCHAR)')
        history=[(1,10,'2019-11-01','view'),(1,20,'2019-11-02','cart'),
            (2,10,'2019-11-01','view'),(2,20,'2019-11-02','purchase'),
            (3,10,'2019-11-01','purchase'),(3,20,'2019-11-02','view'),
            (4,10,'2019-11-01','view'),(4,30,'2019-11-02','view'),
            (5,10,'2019-11-01','view'),(5,30,'2019-11-02','cart'),
            (6,20,'2019-11-01','view'),(6,30,'2019-11-02','purchase'),
            (7,40,'2019-11-01','remove_from_cart'),
            (1,999,'2019-12-01','purchase'),(1,998,'2019-10-31 23:59:59','view')]
        self.con.executemany('INSERT INTO history_events VALUES(?,?,?,?)',history)
        self.cfg=configuration();self.cfg.update(minimum_item_users=2,minimum_pair_users=2)

    def tearDown(self):
        self.con.close()

    def build(self):return build_history(self.con,'validation',self.cfg)

    def test_pair_support_and_cosine_hand_calculation(self):
        self.build()
        self.assertEqual(self.con.execute('SELECT a,b,support FROM pair_support ORDER BY a,b').fetchall(),[(10,20,3),(10,30,2)])
        self.assertAlmostEqual(self.con.execute('SELECT score FROM neighbors WHERE a=10 AND b=20').fetchone()[0],3/math.sqrt(5*4))
        self.assertEqual(self.con.execute('SELECT b FROM neighbors WHERE a=10 ORDER BY r').fetchall(),[(20,),(30,)])

    def test_future_and_prior_window_rows_excluded(self):
        stats=self.build()
        self.assertEqual(stats['eligible_users'],7)
        self.assertEqual(self.con.execute('SELECT count(*) FROM hp WHERE product_key IN (998,999)').fetchone()[0],0)

    def test_repeated_actions_do_not_increase_pair_votes(self):
        self.build();before=self.con.execute('SELECT * FROM neighbors ORDER BY a,b').fetchall()
        self.con.execute("INSERT INTO history_events VALUES(1,10,'2019-11-01','view')")
        self.build();self.assertEqual(before,self.con.execute('SELECT * FROM neighbors ORDER BY a,b').fetchall())

    def test_removal_only_history_not_positive_graph_signal(self):
        self.build()
        self.assertEqual(self.con.execute('SELECT product_key FROM personal WHERE user_key=7').fetchone()[0],40)
        self.assertEqual(self.con.execute('SELECT count(*) FROM capped WHERE user_key=7').fetchone()[0],0)

    def test_history_seed_and_neighbor_caps(self):
        self.cfg.update(graph_history_cap=1,seed_cap=1,neighbors_per_item=1)
        stats=self.build()
        self.assertLessEqual(stats['largest_graph_history'],1)
        self.assertEqual(stats['supported_pairs'],0)

    def test_order_and_input_order_reproducibility(self):
        self.build();before=batch_sources(self.con,1,7,200)
        self.con.execute('CREATE OR REPLACE TABLE history_events AS SELECT * FROM history_events ORDER BY user_key DESC,product_key DESC')
        self.build();self.assertEqual(before,batch_sources(self.con,1,7,200))

    def test_label_boundaries_and_no_outcome_leakage_into_retrieval(self):
        self.build();before=batch_sources(self.con,1,7,200)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'labels.parquet'
            self.con.execute("CREATE TABLE outcomes AS SELECT * FROM history_events WHERE false")
            self.con.execute("INSERT INTO outcomes VALUES(1,20,'2019-12-01','purchase'),(1,999,'2019-12-14 23:59:59','purchase'),(1,998,'2019-12-15','purchase'),(99,20,'2019-12-02','purchase')")
            self.con.execute(f"COPY outcomes TO '{path}' (FORMAT PARQUET)")
            self.assertEqual(dict(load_labels(self.con,path,'validation')),{1:{20,999}})
        self.assertEqual(before,batch_sources(self.con,1,7,200))

    def test_label_reader_blocks_final_before_touching_path(self):
        with self.assertRaises(ValueError):load_labels(self.con,'nonexistent.parquet','final_test')

    def test_full_batch_evaluation_matches_manual_global_hits(self):
        self.cfg['budgets']=[1,2];self.cfg['customer_batch_size']=2
        self.build()
        labels={1:{20,999},4:{30}}
        result=evaluate(self.con,self.cfg,labels)
        # Products 10,20,30 each have one buyer: ID tie-break puts 10,20 first.
        self.assertEqual(result['matched_budget']['global']['1']['hits'],0)
        self.assertEqual(result['matched_budget']['global']['2']['hits'],1)
        self.assertAlmostEqual(result['matched_budget']['global']['2']['pair_recall'],1/3)
        for method in result['matched_budget'].values():
            self.assertEqual(method['2']['mean_candidates'],2)
            self.assertEqual(method['2']['eligible_user_coverage'],1)

    def test_metrics_reproduce_across_customer_batch_sizes(self):
        self.cfg['budgets']=[1,2];self.cfg['customer_batch_size']=2
        self.build();labels={1:{20,999},4:{30}}
        first=evaluate(self.con,self.cfg,labels)
        self.cfg['customer_batch_size']=3
        second=evaluate(self.con,self.cfg,dict(reversed(list(labels.items()))))
        for field in ('matched_budget','without_backfill','complementary_hits_at_equal_budget'):
            self.assertEqual(first[field],second[field])


if __name__=='__main__':
    unittest.main()
