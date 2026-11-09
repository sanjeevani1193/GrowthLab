"""Hand-checkable synthetic interactions; no real customer histories."""
import unittest

import duckdb

from growthlab.ranking_audit import global_audit, snapshot_audit, WINDOWS


class RankingAuditTests(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect()
        self.con.execute('''CREATE TABLE events(user_key BIGINT,product_key BIGINT,
            event_ts TIMESTAMP,event_type VARCHAR,category_key BIGINT,
            category_code VARCHAR,brand VARCHAR,price_value DOUBLE)''')
        self.data = [
            (1,10,'2019-11-01','view'),(1,10,'2019-11-02','cart'),
            (1,10,'2019-11-03','purchase'),(1,10,'2019-11-04','purchase'),
            (1,20,'2019-11-30 23:59:59','view'),(2,20,'2019-11-05','view'),
            (2,30,'2019-11-06','purchase'),(3,40,'2019-12-01','view'),
            (3,40,'2019-12-02','purchase'),(1,20,'2019-12-01','purchase'),
            (1,50,'2019-12-14','purchase'),(2,30,'2019-12-15','purchase'),
            (2,30,'2019-12-02','purchase'),(1,10,'2020-01-01','purchase')]
        self.con.executemany('INSERT INTO events VALUES (?,?,?,?,1,NULL,NULL,5)', self.data)

    def tearDown(self):
        self.con.close()

    def validation(self):
        return snapshot_audit(self.con, *WINDOWS[1])

    def test_global_grains_repeats_and_sparsity(self):
        r = global_audit(self.con)
        self.assertEqual(r['totals']['events'],14)
        self.assertEqual(r['totals']['customers'],3)
        self.assertEqual(r['totals']['products'],5)
        self.assertEqual(r['pairs']['distinct_customer_product_pairs'],6)
        self.assertEqual(r['pairs']['purchased_pairs'],5)
        self.assertEqual(r['pairs']['customers_rebuying_product'],2)
        self.assertAlmostEqual(r['observed_pair_density'],6/15)

    def test_half_open_history_and_outcome_boundaries(self):
        r = self.validation()
        self.assertEqual(r['history']['customers'],2)
        self.assertEqual(r['warm_outcomes']['purchased_pairs'],3)
        self.assertEqual(self.con.execute('SELECT count(*) FROM history').fetchone()[0],7)
        # Exactly December 1 is a label, exactly December 15 is not.
        self.assertEqual(self.con.execute('SELECT count(*) FROM relevant WHERE user_key=2').fetchone()[0],1)

    def test_cold_users_products_and_repeat_labels(self):
        r = self.validation()
        self.assertEqual(r['future_population']['purchasers_without_window_history'],1)
        self.assertEqual(r['warm_outcomes']['new_product_pairs'],1)
        self.assertEqual(r['warm_outcomes']['previously_interacted_pairs'],2)
        self.assertEqual(r['warm_outcomes']['previously_purchased_pairs'],1)

    def test_candidates_use_past_only_and_keep_unrecoverable_labels_in_denominator(self):
        row = self.validation()['candidate_diagnostics'][0]
        self.assertEqual(row['actual_global_products'],2)
        self.assertEqual(row['relevant_pairs'],3)
        self.assertEqual(row['global_hits'],1)
        self.assertEqual(row['personal_hits'],2)
        self.assertEqual(row['union_hits'],2)
        self.assertAlmostEqual(row['union_macro_recall'],.75)
        self.assertEqual(row['candidate_rows'],6)

    def test_future_only_product_never_enters_past_popularity(self):
        self.validation()
        self.assertEqual(self.con.execute('SELECT count(*) FROM popularity WHERE product_key=50').fetchone()[0],0)

    def test_final_test_only_reads_history(self):
        result = snapshot_audit(self.con, *WINDOWS[2])
        self.assertFalse(result['outcomes_accessed'])
        self.assertNotIn('warm_outcomes',result)
        self.assertNotIn('candidate_diagnostics',result)
        self.assertEqual(self.con.execute('SELECT count(*) FROM information_schema.tables WHERE table_name=\'relevant\'').fetchone()[0],0)
        self.assertLess(str(self.con.execute('SELECT max(event_ts) FROM history').fetchone()[0]),'2020-01-01')

    def test_reproducible_and_unchanged_by_later_outcomes(self):
        before = self.validation()
        self.con.execute("INSERT INTO events VALUES(99,999,'2020-01-02','purchase',1,NULL,NULL,5)")
        self.assertEqual(before,self.validation())

    def test_schedule_maturity_and_gap_avoidance(self):
        self.assertLessEqual(WINDOWS[0][3],WINDOWS[1][2])
        self.assertLessEqual(WINDOWS[1][3],WINDOWS[2][2])
        self.assertLess(WINDOWS[2][3],'2020-01-22')


if __name__ == '__main__':
    unittest.main()
