"""Hand-checkable contracts for actual Phase 2 build functions, without models."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from growthlab.acquire import digest
from growthlab.audit import COLUMNS, connect, records
from growthlab.features import FEATURE_COLUMNS, TARGET, build_customers, clean_sql, copy_parquet, validate_customers
from growthlab.history_verification import python_customer
from growthlab.design_review import verify_raw


class CustomerFeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.con=connect(":memory:",self.root/"spill","256MB")
        self.con.execute("CREATE TABLE raw_events("+",".join(c+" VARCHAR" for c in COLUMNS)+")")

    def tearDown(self):
        self.con.close()
        self.temp.cleanup()

    def add(self,user,moment,kind="view",price="1",session="s",product="10",brand=None):
        if isinstance(moment,str): moment=datetime.fromisoformat(moment)
        row=[moment.strftime("%Y-%m-%d %H:%M:%S UTC"),kind,product,"1487580000000000001",None,brand,price,str(user),session]
        self.con.execute("INSERT INTO raw_events VALUES (?,?,?,?,?,?,?,?,?)",row)
        return row

    def build(self,end="2020-03-01",gaps=()):
        self.con.execute("CREATE OR REPLACE TABLE events AS "+clean_sql("raw_events","fixture"))
        build_customers(self.con,end,gaps)
        validate_customers(self.con,end)

    def customer(self,user):
        return records(self.con,f"SELECT * FROM customer_features WHERE user_id={user}")[0]

    def test_twelve_features_and_boundary_events_by_hand(self):
        t0=datetime(2019,10,1,6)
        first=self.add(1,t0,price="-5",session="shared",product="10")
        self.con.execute("INSERT INTO raw_events VALUES (?,?,?,?,?,?,?,?,?)",first)
        self.add(1,t0+timedelta(days=1),price="0",session="shared",product="11")
        self.add(1,t0+timedelta(days=2),price="10",session=None,product="12")
        self.add(1,t0+timedelta(days=7,seconds=-1),kind="purchase",session="buy")
        self.add(1,t0+timedelta(days=7),kind="view",price="999",session="future")
        self.add(1,t0+timedelta(days=7),kind="purchase")
        self.add(1,t0+timedelta(days=37),kind="purchase",price="999")
        self.build()
        c=self.customer(1)
        expected={"n_views_7d":3,"n_carts_7d":0,"n_removals_7d":0,"n_purchases_7d":1,
                  "n_viewed_products_7d":3,"active_24h_bins_7d":4,"n_sessions_7d":2,
                  "hours_since_last_event":1/3600,"cart_view_ratio_7d":0,"purchase_view_ratio_7d":1/3,
                  "median_view_price_7d":5,"view_price_unavailable_7d":0}
        self.assertEqual(set(expected),set(FEATURE_COLUMNS))
        for key,value in expected.items(): self.assertAlmostEqual(c[key],value,msg=key)
        self.assertEqual(c[TARGET],1)
        self.assertEqual(c["qa_total_events_7d"],4)
        self.assertEqual(c["qa_negative_price_events_7d"],1)
        self.assertEqual(c["qa_zero_price_events_7d"],1)
        self.assertEqual(c["qa_missing_session_events_7d"],1)

    def test_end_excluded_first_week_purchase_does_not_make_target_positive(self):
        t0=datetime(2019,10,1)
        self.add(1,t0,kind="purchase")
        self.add(1,t0+timedelta(days=7,seconds=-1),kind="purchase")
        self.add(1,t0+timedelta(days=37),kind="purchase")
        self.build()
        c=self.customer(1)
        self.assertEqual(c[TARGET],0)
        self.assertEqual(c["n_purchases_7d"],2)
        self.assertEqual(c["cart_view_ratio_7d"],0)
        self.assertEqual(c["purchase_view_ratio_7d"],0)
        self.assertIsNone(c["median_view_price_7d"])
        self.assertEqual(c["view_price_unavailable_7d"],1)

    def test_censoring_ignores_known_early_positive_and_accepts_equal_coverage_end(self):
        self.add(1,"2019-11-01")
        self.add(1,"2019-11-09",kind="purchase")
        self.add(2,"2019-10-14")  # +37 days equals Nov 20.
        self.build("2019-11-20")
        self.assertEqual(self.con.execute("SELECT user_id FROM customer_features").fetchall(),[(2,)])

    def test_dedup_uses_all_nine_raw_fields_not_parsed_values(self):
        r=self.add(1,"2019-10-01",price="1")
        self.con.execute("INSERT INTO raw_events VALUES (?,?,?,?,?,?,?,?,?)",r)
        self.add(1,"2019-10-01",price="1.0")
        self.add(1,"2019-10-01",price="1",brand="brand")
        self.add(1,"2019-10-01 00:00:01",price="1")
        self.build()
        self.assertEqual(self.customer(1)["n_views_7d"],4)

    def test_sessions_are_distinct_within_each_customer_missing_is_not_a_session(self):
        self.add(1,"2019-10-01",session="shared")
        self.add(1,"2019-10-02",session="other")
        self.add(2,"2019-10-01",session="shared")
        self.add(2,"2019-10-02",session=None)
        self.add(3,"2019-10-01",session=None)
        self.build()
        self.assertEqual([self.customer(i)["n_sessions_7d"] for i in (1,2,3)],[2,1,0])

    def test_zero_is_a_valid_price_negative_only_is_unavailable(self):
        self.add(1,"2019-10-01",price="0")
        self.add(2,"2019-10-01",price="-5")
        self.build()
        self.assertEqual(self.customer(1)["median_view_price_7d"],0)
        self.assertEqual(self.customer(1)["view_price_unavailable_7d"],0)
        self.assertIsNone(self.customer(2)["median_view_price_7d"])
        self.assertEqual(self.customer(2)["n_views_7d"],1)

    def test_midnight_utc_does_not_add_an_elapsed_day_bin(self):
        self.add(1,"2019-10-01 23:59:59")
        self.add(1,"2019-10-02 00:00:01")
        self.build()
        self.assertEqual(self.customer(1)["active_24h_bins_7d"],1)

    def test_splits_use_prediction_time_end_exclusive(self):
        for user,t0 in enumerate(["2019-10-01","2019-11-05","2019-12-10","2019-10-06","2019-11-10","2019-12-15"],1):
            self.add(user,t0)
        self.build()
        assignments=[self.customer(i)["primary_split"] for i in range(1,7)]
        self.assertEqual(assignments,["train","validation","test",None,None,None])
        self.assertEqual(self.con.execute("SELECT count(*),count(DISTINCT user_id) FROM customer_features").fetchone(),(6,6))

    def test_gap_flags_kept_but_not_predictors(self):
        self.add(1,"2020-01-15 03:00:00")
        self.build()
        self.assertTrue(self.customer(1)["feature_gap"])
        self.assertTrue(self.customer(1)["outcome_gap"])
        self.assertFalse(set(FEATURE_COLUMNS)&{"feature_gap","outcome_gap",TARGET,"user_id"})

    def test_declared_logging_gap_excludes_intersecting_horizon(self):
        self.add(1,"2019-10-01")
        self.add(2,"2019-11-01")
        self.build(gaps=("2019-10-05",))
        self.assertEqual(self.con.execute("SELECT user_id FROM customer_features").fetchall(),[(2,)])

    def test_adding_future_activity_cannot_change_features(self):
        self.add(1,"2019-10-01")
        self.build()
        before=self.customer(1)
        self.add(1,"2019-10-08",kind="purchase",price="999",session="future")
        self.add(1,"2019-10-20",kind="view",price="999",session="future2")
        self.build()
        after=self.customer(1)
        self.assertEqual([before[f] for f in FEATURE_COLUMNS],[after[f] for f in FEATURE_COLUMNS])
        self.assertEqual((before[TARGET],after[TARGET]),(0,1))

    def test_cleaning_export_does_not_modify_source(self):
        self.add(1,"2019-10-01")
        source=self.root/"input.parquet"
        copy_parquet(self.con,"SELECT * FROM raw_events",source)
        before=digest(source)
        copy_parquet(self.con,clean_sql(f"read_parquet('{source}')","fixture"),self.root/"cleaned.parquet")
        self.assertEqual(digest(source),before)

    def test_independent_reference_agrees_on_hand_fixture(self):
        rows=[self.add(1,"2019-10-01",price="0"),self.add(1,"2019-10-02",price="10"),
              self.add(1,"2019-10-08",kind="purchase")]
        self.build()
        reference=python_customer([tuple(v if v is not None else "" for v in r) for r in rows])
        actual=self.customer(1)
        for name,value in reference.items(): self.assertEqual(actual[name],value,name)

    def test_raw_csv_hash_guard_accepts_unchanged_and_rejects_mutation(self):
        raw=self.root/"data/raw"
        raw.mkdir(parents=True)
        path=raw/"fixture.csv"
        path.write_text(",".join(COLUMNS)+"\n")
        manifest={"files":[{"name":path.name,"csv_bytes":path.stat().st_size,"csv_sha256":digest(path)}]}
        self.assertEqual(verify_raw(self.root,manifest)[path.name],digest(path))
        # Deliberately mutate only a temporary synthetic file, never project data.
        path.write_text("changed fixture")
        with self.assertRaises(ValueError): verify_raw(self.root,manifest)


class PublishedFeatureTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parents[1]
        summary=self.root/"docs/phase2/summary.json"
        if not summary.exists(): self.skipTest("Phase 2 full-data build not available")
        self.summary=json.loads(summary.read_text())

    def test_provenance_and_frozen_population_counts(self):
        from growthlab.features import PRIMARY
        summary=self.summary
        manifest=json.loads((self.root/"docs/phase1/acquisition.json").read_text())
        original={f["name"]:f["csv_sha256"] for f in manifest["files"]}
        self.assertEqual(summary["raw_hashes_before"],original)
        self.assertEqual(summary["raw_hashes_after"],original)
        self.assertEqual(summary["feature_columns"],list(FEATURE_COLUMNS))
        for split,_,_,customers,positives in PRIMARY:
            row=next(r for r in summary["primary_splits"] if r["split"]==split)
            self.assertEqual((row["customers"],row["positives"]),(customers,positives))
            self.assertAlmostEqual(row["positive_rate"],positives/customers)
        self.assertEqual(summary["history_verification"]["mismatches"],0)
        self.assertEqual(summary["specification_sha256"],digest(self.root/"docs/phase2_specification.json"))
        for path,expected in summary["source_code_sha256"].items(): self.assertEqual(digest(self.root/path),expected)

    def test_local_exports_disjoint_unique_and_identical_to_master(self):
        from growthlab.audit import literal
        work=self.root/"data/features/phase2"
        if not (work/"customers.parquet").exists(): self.skipTest("Local ignored exports not available")
        with tempfile.TemporaryDirectory() as directory:
            con=connect(":memory:",Path(directory)/"spill","256MB")
            try:
                con.execute(f"CREATE VIEW master AS SELECT * FROM read_parquet({literal(work/'customers.parquet')})")
                self.assertEqual(con.execute("SELECT count(*),count(DISTINCT user_id) FROM master").fetchone(),(1256629,1256629))
                paths="["+",".join(literal(p) for p in sorted((work/"primary").glob("*.parquet")))+"]"
                duplicates=con.execute(f"SELECT count(*) FROM (SELECT user_id FROM read_parquet({paths}) GROUP BY 1 HAVING count(*)>1)").fetchone()[0]
                self.assertEqual(duplicates,0)
                projection=",".join(("user_id",*FEATURE_COLUMNS,TARGET))
                for split in ("train","validation","test"):
                    path=work/"primary"/(split+".parquet")
                    local=f"SELECT * FROM read_parquet({literal(path)})"
                    expected=f"SELECT {projection} FROM master WHERE primary_split={literal(split)}"
                    self.assertEqual(con.execute(f"SELECT count(*) FROM (({local} EXCEPT ALL {expected}) UNION ALL ({expected} EXCEPT ALL {local}))").fetchone()[0],0)
                    names=[r[0] for r in con.execute(f"DESCRIBE {local}").fetchall()]
                    self.assertEqual(names,["user_id",*FEATURE_COLUMNS,TARGET])
            finally:
                con.close()


if __name__=="__main__":
    unittest.main()
