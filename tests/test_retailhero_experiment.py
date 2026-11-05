"""Hand-checkable examples: synthetic fixtures test logic, never reported effects."""
import json
import math
import tempfile
import unittest
from pathlib import Path

import duckdb
from scipy.stats import chi2_contingency

from growthlab.retailhero.acquire import sha256
from growthlab.retailhero.experiment import (
    assignment_check, audit, build_splits, experiment_statistics,
    training_counts, training_view, verify_split, wilson,
)


class CalculationTests(unittest.TestCase):
    def test_hand_calculated_difference_and_units(self):
        s = experiment_statistics(60, 100, 50, 100)
        self.assertAlmostEqual(s['difference'], .1)
        self.assertAlmostEqual(s['difference_pp'], 10)
        self.assertAlmostEqual(s['incremental_purchasers_per_1000'], 100)
        self.assertLess(s['ci95'][0], .1)
        self.assertGreater(s['ci95'][1], .1)

    def test_z_test_independent_chi_square_identity(self):
        s = experiment_statistics(60, 100, 50, 100)
        chi, p, _, _ = chi2_contingency([[60,40],[50,50]], correction=False)
        self.assertAlmostEqual(s['z']**2, chi)
        self.assertAlmostEqual(s['p_two_sided'], p)

    def test_newcombe_independent_formula(self):
        # Separately evaluate score limits, then combine the appropriate tails.
        z = 1.959963984540054
        def score(x, n):
            p = x/n
            return tuple((2*n*p+z*z+sign*z*math.sqrt(z*z+4*n*p*(1-p)))/(2*(n+z*z)) for sign in [-1,1])
        lo1, hi1 = score(60,100)
        lo0, hi0 = score(50,100)
        s = experiment_statistics(60,100,50,100)
        self.assertAlmostEqual(s['ci95'][0], .1-math.sqrt((.6-lo1)**2+(hi0-.5)**2))
        self.assertAlmostEqual(s['ci95'][1], .1+math.sqrt((hi1-.6)**2+(.5-lo0)**2))

    def test_swap_arms_reverses_effect_and_interval(self):
        a = experiment_statistics(60,100,50,100)
        b = experiment_statistics(50,100,60,100)
        self.assertAlmostEqual(a['difference'], -b['difference'])
        self.assertAlmostEqual(a['ci95'][0], -b['ci95'][1])
        self.assertAlmostEqual(a['p_two_sided'], b['p_two_sided'])

    def test_zero_effect_and_all_zero_or_one(self):
        for x in [0, 5, 10]:
            s = experiment_statistics(x,10,x,10)
            self.assertEqual(s['difference'], 0)
            self.assertEqual(s['p_two_sided'], 1)
            self.assertLess(s['ci95'][0], 0)
            self.assertGreater(s['ci95'][1], 0)

    def test_invalid_counts_rejected(self):
        for x,n in [(-1,10),(11,10),(0,0),(1.5,10),(1,2.5)]:
            with self.subTest(x=x,n=n), self.assertRaises(ValueError):
                wilson(x,n)

    def test_extreme_effect_is_finite(self):
        s = experiment_statistics(10,10,0,10)
        self.assertEqual(s['difference'], 1)
        self.assertLessEqual(s['ci95'][1], 1)
        self.assertGreater(s['ci95'][0], 0)

    def test_assignment_check_balanced_and_mismatch(self):
        self.assertEqual(assignment_check(100,100)['two_sided_binomial_p'],1)
        self.assertLess(assignment_check(190,10)['two_sided_binomial_p'], 1e-20)


class SplitAndAuditTests(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect()
        self.con.execute("CREATE TABLE uplift_train(client_id VARCHAR,treatment_flg VARCHAR,target VARCHAR)")
        self.con.execute("CREATE TABLE clients(client_id VARCHAR,first_issue_date VARCHAR,first_redeem_date VARCHAR,age VARCHAR,gender VARCHAR)")
        rows = [(f'{arm*100+i:010x}',str(arm),str(i%2)) for arm in [0,1] for i in range(11)]
        self.con.executemany('INSERT INTO uplift_train VALUES (?,?,?)',rows)
        self.con.executemany('INSERT INTO clients VALUES (?,?,?,?,?)',[(r[0],'2019-01-01',None,'45','U') for r in rows])

    def tearDown(self):
        self.con.close()

    def assignments(self):
        return self.con.execute('SELECT * FROM splits ORDER BY client_id').fetchall()

    def test_exact_counts_disjoint_complete_and_outcome_free(self):
        build_splits(self.con,42)
        counts = self.con.execute('SELECT split,treatment_flg,count(*) FROM splits GROUP BY 1,2 ORDER BY 1,2').fetchall()
        self.assertEqual(counts,[('final_test',0,3),('final_test',1,3),('train',0,6),('train',1,6),('validation',0,2),('validation',1,2)])
        self.assertEqual(self.con.execute('SELECT count(DISTINCT client_id),count(*) FROM splits').fetchone(), (22,22))
        self.assertEqual([r[0] for r in self.con.execute('DESCRIBE splits').fetchall()],['client_id','treatment_flg','split'])

    def test_reproducibility_order_and_outcome_independence(self):
        build_splits(self.con,42)
        original = self.assignments()
        self.con.execute("UPDATE uplift_train SET target=cast(1-cast(target AS INTEGER) AS VARCHAR)")
        self.con.execute('CREATE OR REPLACE TABLE uplift_train AS SELECT * FROM uplift_train ORDER BY client_id DESC')
        build_splits(self.con,42)
        self.assertEqual(original,self.assignments())
        build_splits(self.con,43)
        self.assertNotEqual(original,self.assignments())

    def test_training_loader_excludes_holdouts_and_join_preserves_grain(self):
        build_splits(self.con,42)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'splits.parquet'
            self.con.execute('COPY splits TO ? (FORMAT PARQUET)',[str(path)])
            training_view(self.con,path)
            before=training_counts(self.con)
            self.con.execute("UPDATE uplift_train SET target='1' WHERE client_id IN (SELECT client_id FROM splits WHERE split!='train')")
            self.assertEqual(before,training_counts(self.con))
            self.assertEqual(sum(r['n'] for r in before),12)
            self.assertEqual(self.con.execute('SELECT count(DISTINCT client_id) FROM training').fetchone()[0],12)

    def test_audit_missing_demographics_do_not_exclude_customers(self):
        result=audit(self.con)
        self.assertEqual(result['clients']['missing']['first_redeem_date'],22)
        self.assertEqual(result['join']['matched'],22)
        self.assertNotIn('purchase_rate',json.dumps(result))

    def test_duplicate_ids_fail(self):
        self.con.execute('INSERT INTO clients SELECT * FROM clients LIMIT 1')
        with self.assertRaisesRegex(ValueError,'integrity failure'):
            audit(self.con)

    def test_unmatched_clients_fail(self):
        self.con.execute('DELETE FROM clients WHERE client_id=(SELECT min(client_id) FROM clients)')
        with self.assertRaisesRegex(ValueError,'integrity failure'):
            audit(self.con)

    def test_invalid_or_missing_treatment_target_fail(self):
        for col,value in [('target',None),('target','2'),('treatment_flg','-1')]:
            with self.subTest(col=col):
                self.con.execute(f'UPDATE uplift_train SET {col}=? WHERE client_id=(SELECT min(client_id) FROM clients)',[value])
                with self.assertRaisesRegex(ValueError,'integrity failure'):
                    audit(self.con)
                self.con.execute(f"UPDATE uplift_train SET {col}='0' WHERE client_id=(SELECT min(client_id) FROM clients)")

    def test_split_hash_and_frozen_design_enforced(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            docs=root/'docs/causal/phase5';docs.mkdir(parents=True)
            design=docs/'design.json';design.write_text('{}')
            ids=root/'ids';ids.write_text('fixed')
            m={'input_sha256':{'raw':'abc'},'design_sha256':sha256(design),'path':'ids','sha256':sha256(ids)}
            verify_split(root,m,{'raw':'abc'})
            for change in ['raw','design','ids']:
                with self.subTest(change=change):
                    if change=='design': design.write_text('{"changed":true}')
                    if change=='ids': ids.write_text('changed')
                    with self.assertRaisesRegex(ValueError,'integrity failure'):
                        verify_split(root,m,{'raw':'wrong'} if change=='raw' else {'raw':'abc'})
                    design.write_text('{}');ids.write_text('fixed')


if __name__=='__main__':
    unittest.main()
