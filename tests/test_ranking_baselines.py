"""Synthetic ranking examples with explicit, hand-computable relevance."""
from datetime import datetime
import json
import math
from pathlib import Path
import unittest

import duckdb

from growthlab.candidates import build_history, development_window, priority_with_fallback
from growthlab.ranking_baselines import (
    batches, empty_group, evaluate, finish_group, freeze_candidates,
    order_candidates, ranking_metrics,
)


class OrderingTests(unittest.TestCase):
    def test_identical_universe_with_different_orders(self):
        candidates=[1,2,3]
        ranked=order_candidates(candidates,{3:datetime(2019,11,1)},{1:10,2:5})
        self.assertEqual(ranked['global_popularity'],[1,2,3])
        self.assertEqual(ranked['personal_recency'],[3,1,2])
        for result in ranked.values():self.assertEqual(set(result),set(candidates))

    def test_recency_then_popularity_then_id_ties(self):
        recent=datetime(2019,11,2);old=datetime(2019,11,1)
        result=order_candidates([5,4,3,2,1],{1:old,2:recent,3:recent,4:recent},{1:999,2:5,3:10,4:10,5:999})
        self.assertEqual(result['personal_recency'],[3,4,2,1,5])

    def test_missing_popularity_is_zero_not_unknown_top_rank(self):
        result=order_candidates([9,2,1],{},{2:1})
        self.assertEqual(result['global_popularity'],[2,1,9])

    def test_empty_personal_history_reduces_to_popularity(self):
        result=order_candidates([3,1,2],{},{2:5,3:1})
        self.assertEqual(result['global_popularity'],result['personal_recency'])

    def test_order_independence_and_determinism(self):
        history={2:datetime(2019,11,3)}
        self.assertEqual(order_candidates([3,1,2],history,{1:4}),order_candidates([2,1,3],history,{1:4}))

    def test_budget_and_deduplication_guards(self):
        for candidates in ([1,1],list(range(101))):
            with self.assertRaises(ValueError):order_candidates(candidates,{},{})
        self.assertEqual(len(order_candidates(list(range(100)),{},{})['personal_recency']),100)


class MetricTests(unittest.TestCase):
    def test_recall_and_ndcg_small_example(self):
        metrics=ranking_metrics([9,1,8],{1,2},[3])['3']
        self.assertEqual(metrics['hits'],1)
        self.assertEqual(metrics['recall'],.5)
        self.assertAlmostEqual(metrics['ndcg'],(1/math.log2(3))/(1+1/math.log2(3)))

    def test_perfect_and_completely_wrong_order(self):
        self.assertEqual(ranking_metrics([1,2,3],{1,2},[2])['2']['ndcg'],1)
        self.assertEqual(ranking_metrics([8,9,10],{1,2},[2])['2']['ndcg'],0)

    def test_unretrieved_products_stay_in_ideal_denominator(self):
        m=ranking_metrics([1,2],{1,2,999},[5])['5']
        self.assertEqual(m['recall'],2/3)
        self.assertAlmostEqual(m['ndcg'],(1+1/math.log2(3))/(1+1/math.log2(3)+.5))
        self.assertLess(m['ndcg'],1)

    def test_empty_outcome_is_undefined_not_zero(self):
        m=ranking_metrics([1,2],set())
        self.assertTrue(all(r['recall'] is None and r['ndcg'] is None for r in m.values()))

    def test_metric_input_guards(self):
        with self.assertRaises(ValueError):ranking_metrics([1,1],{1})
        with self.assertRaises(ValueError):ranking_metrics([1],{1},[0])

    def test_no_history_group_has_no_invented_empirical_metrics(self):
        g=finish_group(empty_group())
        self.assertEqual(g['eligible_users'],0)
        self.assertIsNone(g['candidate_recall_micro'])
        self.assertIsNone(g['methods']['personal_recency']['10']['ndcg_macro'])


class FrozenPipelineTests(unittest.TestCase):
    def setUp(self):
        self.con=duckdb.connect()
        self.con.execute('CREATE TABLE history_events(user_key BIGINT,product_key BIGINT,event_ts TIMESTAMP,event_type VARCHAR)')
        values=[(1000+p,p,'2019-11-01','purchase') for p in range(1,101)]
        values += [(1,999,'2019-11-03','view'),(2,2,'2019-11-04','purchase'),
                   (1,888,'2019-12-01','purchase'),(1,887,'2019-10-31','view')]
        self.con.executemany('INSERT INTO history_events VALUES(?,?,?,?)',values)
        cfg=json.loads((Path(__file__).resolve().parents[1]/'docs/ranking/phase10b1_config.json').read_text())
        build_history(self.con,'validation',cfg)

    def tearDown(self):self.con.close()

    def test_candidate_membership_matches_previous_selected_recipe(self):
        frozen=freeze_candidates(self.con,'validation')
        self.assertEqual(frozen['eligible_users'],102)
        self.assertEqual(frozen['without_personal_history'],0)
        g=[p for p, in self.con.execute('SELECT product_key FROM popularity WHERE r<=100 ORDER BY r').fetchall()]
        for batch in batches(self.con,'validation',17):
            for u,candidates,history in batch:
                personal=[p for p, in self.con.execute('SELECT product_key FROM personal WHERE user_key=? AND r<=100 ORDER BY r',[u]).fetchall()]
                self.assertEqual(candidates,priority_with_fallback(personal,g,100))
                self.assertNotIn(888,history);self.assertNotIn(887,history)

    def test_actual_candidate_hashes_identical_for_both_methods(self):
        frozen=freeze_candidates(self.con,'validation',17)
        result=evaluate(self.con,'validation',{1:{999,999999},2:{2}},frozen,17)
        self.assertEqual(set(result['candidate_universe_sha256'].values()),{frozen['canonical_candidate_sha256']})
        group=result['groups']['all']
        self.assertAlmostEqual(group['candidate_recall_micro'],2/3)
        self.assertEqual(group['candidate_recall_macro'],.75)
        recent=group['methods']['personal_recency']['5']
        global_=group['methods']['global_popularity']['5']
        self.assertEqual(recent['recall_macro'],.75)
        self.assertAlmostEqual(recent['recall_micro'],2/3)
        self.assertEqual(global_['recall_macro'],.5)
        self.assertAlmostEqual(global_['recall_micro'],1/3)

    def test_timestamp_guard_rejects_future_metadata(self):
        self.con.execute("UPDATE hp SET last_event='2019-12-01' WHERE user_key=1")
        with self.assertRaisesRegex(ValueError,'outside frozen past'):freeze_candidates(self.con,'validation')

    def test_candidate_freeze_hash_rejects_membership_changes(self):
        frozen=freeze_candidates(self.con,'validation')
        frozen['canonical_candidate_sha256']='changed'
        with self.assertRaisesRegex(ValueError,'membership changed'):evaluate(self.con,'validation',{},frozen)

    def test_labels_do_not_change_order_or_universe(self):
        frozen=freeze_candidates(self.con,'validation',23)
        a=evaluate(self.con,'validation',{},frozen,23)
        b=evaluate(self.con,'validation',{1:{999},2:{2}},frozen,17)
        self.assertEqual(a['candidate_universe_sha256'],b['candidate_universe_sha256'])

    def test_final_snapshot_rejected(self):
        with self.assertRaises(ValueError):list(batches(self.con,'final_test'))


if __name__=='__main__':unittest.main()
