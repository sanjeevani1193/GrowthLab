"""Diagnostic/design contracts verified on tiny synthetic event histories."""

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from growthlab.audit import EARLIER_SPLITS, SPLITS, connect, records
from growthlab.design_review import duplicate_groups_sql, gap_cohort, overlap_sql, summarize_schedule


class DesignQueryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.con = connect(":memory:", Path(self.directory.name) / "spill", "256MB")

    def tearDown(self):
        self.con.close()
        self.directory.cleanup()

    def test_half_open_overlap_touching_endpoints_is_not_overlap(self):
        query = overlap_sql("a", "b", "2020-01-22 02:52:09", "2020-01-22 03:26:14")
        self.con.execute("CREATE TABLE windows(a TIMESTAMP,b TIMESTAMP)")
        self.con.executemany("INSERT INTO windows VALUES (?,?)", [
            ("2020-01-22 01:00:00", "2020-01-22 02:52:09"),
            ("2020-01-22 03:26:14", "2020-01-22 04:00:00"),
            ("2020-01-22 02:00:00", "2020-01-22 03:00:00"),
            ("2020-01-22 03:00:00", "2020-01-22 04:00:00"),
        ])
        self.assertEqual([r[0] for r in self.con.execute(f"SELECT {query} FROM windows").fetchall()], [False,False,True,True])

    def test_gap_can_overlap_both_windows_and_flags_are_metadata(self):
        self.con.execute("""CREATE TABLE cohort AS SELECT 1 AS user_key,
            TIMESTAMP '2020-01-15 03:00:00' AS t0,TIMESTAMP '2020-01-22 03:00:00' AS prediction_time,
            TIMESTAMP '2020-02-21 03:00:00' AS outcome_end,true AS eligible,false AS positive""")
        gap_cohort(self.con)
        self.assertEqual(self.con.execute("SELECT feature_gap,outcome_gap FROM gap_cohort").fetchone(),(True,True))
        retained=summarize_schedule(self.con,[("test","2020-01-22","2020-01-23")])
        excluded=summarize_schedule(self.con,[("test","2020-01-22","2020-01-23")],True)
        self.assertEqual(retained[0]["users"],1)
        self.assertEqual(excluded[0]["users"],0)

    def test_exact_duplicates_include_nulls_but_not_nearby_times(self):
        self.con.execute("""CREATE TABLE events(event_time VARCHAR,event_type VARCHAR,product_id VARCHAR,
            category_id VARCHAR,category_code VARCHAR,brand VARCHAR,price VARCHAR,user_id VARCHAR,
            user_session VARCHAR,user_key BIGINT)""")
        row=["2020-01-01 00:00:00 UTC","purchase","1","2",None,None,"0.00","3",None,3]
        self.con.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)",[row,row,["2020-01-01 00:00:01 UTC",*row[1:]]])
        duplicates=records(self.con,duplicate_groups_sql("events"))
        self.assertEqual(len(duplicates),1)
        self.assertEqual(duplicates[0]["n"],2)
        # Deduplication preserves first appearance and any-purchase label.
        self.assertEqual(self.con.execute("SELECT min(event_time),bool_or(event_type='purchase') FROM events").fetchone(),
                         self.con.execute("SELECT min(event_time),bool_or(event_type='purchase') FROM (SELECT DISTINCT * FROM events)").fetchone())

    def test_price_summary_excludes_negative_keeps_zero_and_never_reads_future(self):
        self.con.execute("CREATE TABLE e(ts TIMESTAMP,kind VARCHAR,price DOUBLE)")
        self.con.executemany("INSERT INTO e VALUES (?,?,?)",[
            ("2020-01-01","view",-5),("2020-01-02","view",0),
            ("2020-01-03","view",10),("2020-01-08","view",999),
        ])
        row=self.con.execute("""SELECT median(price) FILTER (WHERE kind='view' AND isfinite(price) AND price>=0),
            count(DISTINCT floor(date_diff('second',TIMESTAMP '2020-01-01',ts)/86400.0))
            FROM e WHERE ts>=TIMESTAMP '2020-01-01' AND ts<TIMESTAMP '2020-01-08'""").fetchone()
        self.assertEqual(row,(5.0,3))
        self.assertIsNone(self.con.execute("SELECT median(price) FROM e WHERE kind='cart'").fetchone()[0])

    def test_ratio_without_views_has_explicit_zero_convention(self):
        rows=self.con.execute("""SELECT CASE WHEN views>0 THEN carts::DOUBLE/views ELSE 0.0 END
            FROM (VALUES (0,0),(0,2),(2,3)) v(views,carts)""").fetchall()
        self.assertEqual(rows,[(0.0,),(0.0,),(1.5,)])

    def test_candidate_calendars_are_disjoint_and_labels_mature(self):
        for schedule in (SPLITS,EARLIER_SPLITS):
            for earlier,later in zip(schedule,schedule[1:]):
                previous_end=datetime.fromisoformat(earlier[2])
                next_start=datetime.fromisoformat(later[1])
                self.assertLessEqual(previous_end,next_start)
                self.assertLessEqual(previous_end+timedelta(days=30),next_start)
            self.assertLessEqual(datetime.fromisoformat(schedule[-1][2])+timedelta(days=30),datetime(2020,3,1))


if __name__ == "__main__":
    unittest.main()
