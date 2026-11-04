"""Small synthetic fixtures verify semantics; they are not dataset findings."""

import csv
import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from growthlab.audit import COLUMNS, build_customers, connect, convert, literal, records, run_audit


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.con = connect(":memory:", self.root / "spill", "256MB")
        self.con.execute("CREATE TABLE events(user_key BIGINT, event_ts TIMESTAMP, event_type VARCHAR)")
        self.con.execute("CREATE TABLE coverage_gaps(day TIMESTAMP)")

    def tearDown(self):
        self.con.close()
        self.temp.cleanup()

    def add(self, user, timestamp, kind="view"):
        self.con.execute("INSERT INTO events VALUES (?, ?, ?)", [user, timestamp, kind])

    def test_half_open_outcome_and_full_horizon_eligibility(self):
        for user in range(1, 6):
            self.add(user, "2020-01-01")
        self.add(1, "2020-01-07 23:59:59", "purchase")  # First week: not target.
        self.add(2, "2020-01-08", "purchase")  # Exact scoring instant: positive.
        self.add(3, "2020-02-07", "purchase")  # Exact end: excluded.
        self.add(4, "2020-02-06 23:59:59", "purchase")
        # A customer with no return visit remains eligible when logging covers the horizon.
        build_customers(self.con, "2020-02-07")
        rows = records(self.con, "SELECT user_key, eligible, positive FROM cohort ORDER BY user_key")
        self.assertEqual([r["positive"] for r in rows], [False, True, False, True, False])
        self.assertTrue(all(r["eligible"] for r in rows))

    def test_censored_early_positive_not_selected(self):
        self.add(1, "2020-02-01")
        self.add(1, "2020-02-09", "purchase")
        build_customers(self.con, "2020-03-01")
        row = records(self.con, "SELECT eligible, positive FROM cohort")[0]
        self.assertTrue(row["positive"])
        self.assertFalse(row["eligible"])

    def test_global_first_seen_crosses_month_boundary(self):
        self.add(1, "2019-10-30")
        self.add(1, "2019-11-06", "purchase")
        self.add(1, "2019-12-10", "purchase")
        build_customers(self.con, "2020-01-01")
        row = records(self.con, "SELECT count(*) AS n, sum(future_purchase_events) AS purchases FROM cohort")[0]
        self.assertEqual(row, {"n": 1, "purchases": 1})

    def test_gap_overlapping_window_excludes_customer(self):
        self.add(1, "2020-01-01")
        self.add(2, "2020-02-01")
        self.con.execute("INSERT INTO coverage_gaps VALUES ('2020-01-05')")
        build_customers(self.con, "2020-04-01")
        rows = records(self.con, "SELECT eligible FROM cohort ORDER BY user_key")
        self.assertEqual([r["eligible"] for r in rows], [False, True])

    def test_invalid_user_and_timestamp_excluded(self):
        self.add(None, "2020-01-01")
        self.add(0, "2020-01-01")
        self.add(1, None)
        self.add(2, "2020-01-01")
        build_customers(self.con, "2020-04-01")
        self.assertEqual(self.con.execute("SELECT user_key FROM cohort").fetchall(), [(2,)])

    def test_gap_exactly_at_window_end_is_outside(self):
        self.add(1, "2020-01-01")
        self.con.execute("INSERT INTO coverage_gaps VALUES ('2020-02-07')")
        build_customers(self.con, "2020-04-01")
        self.assertTrue(self.con.execute("SELECT eligible FROM cohort").fetchone()[0])


class ParsingTests(unittest.TestCase):
    def test_raw_values_preserved_duplicates_missing_and_large_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, destination = root / "sample.csv", root / "sample.parquet"
            row = ["2019-10-01 00:00:00 UTC", "view", "1", "1487580000000000001", "", "", "1.25", "10", "session"]
            invalid = ["bad time", "other", "1.5", "oops", "", "", "bad price", "-1", ""]
            with source.open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(COLUMNS)
                writer.writerows([row, row, invalid])
            con = connect(":memory:", root / "spill", "256MB")
            try:
                convert(con, source, destination, "2019-Oct")
                con.execute(f"CREATE VIEW parsed AS SELECT * FROM read_parquet({literal(destination)})")
                valid = records(con, "SELECT * FROM parsed WHERE event_type='view'")[0]
                self.assertEqual(valid["category_key"], 1487580000000000001)
                self.assertIsNone(valid["brand"])
                self.assertEqual(valid["price_value"], 1.25)
                invalid_parsed = records(con, "SELECT * FROM parsed WHERE event_type='other'")[0]
                for column in ("event_ts", "product_key", "category_key", "user_key", "price_value"):
                    self.assertIsNone(invalid_parsed[column])
                self.assertEqual(invalid_parsed["price"], "bad price")
                self.assertEqual(con.execute("SELECT count(*) FROM (SELECT count(*) n FROM parsed GROUP BY ALL HAVING n>1)").fetchone()[0], 1)
            finally:
                con.close()

    def test_reordered_header_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.csv"
            source.write_text(",".join(reversed(COLUMNS)) + "\n")
            con = connect(":memory:", root / "spill", "256MB")
            try:
                with self.assertRaisesRegex(ValueError, "Unexpected header"):
                    convert(con, source, root / "out.parquet", "2019-Oct")
            finally:
                con.close()


class EndToEndTests(unittest.TestCase):
    def test_two_month_audit_reconciles_known_population(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data/raw").mkdir(parents=True)
            start = datetime(2019, 10, 1)
            for month in ("2019-Oct", "2019-Nov"):
                with (root / "data/raw" / (month + ".csv")).open("w", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(COLUMNS)
                    for offset in range(61):
                        moment = start + timedelta(days=offset)
                        if moment.strftime("%Y-%b") != month:
                            continue
                        writer.writerow([moment.strftime("%Y-%m-%d %H:%M:%S UTC"), "view", "1",
                                         "1487580000000000001", "", "", "1.25", offset+1, f"session-{offset}"])
                    if month == "2019-Oct":
                        writer.writerow(["2019-10-08 00:00:00 UTC", "purchase", "1",
                                         "1487580000000000001", "", "", "1.25", "1", "buy-session"])
            with contextlib.redirect_stdout(io.StringIO()):
                summary = run_audit(root, months=("2019-Oct", "2019-Nov"),
                                    coverage_end="2019-12-01", memory="256MB")
            self.assertEqual(summary["totals"]["events"], 62)
            self.assertEqual(summary["totals"]["users"], 61)
            self.assertEqual(summary["eligibility"]["eligible_users"], 25)
            self.assertEqual(summary["eligibility"]["eligible_positive_users"], 1)
            self.assertEqual(summary["duplicates"]["excess_rows"], 0)
            self.assertEqual(summary["coverage"]["zero_event_days"], [])
            self.assertEqual(sum(day["events"] for day in summary["daily"]), 62)
            self.assertEqual(summary["splits"][0]["users"], 24)
            # Daily-only synthetic events have 24-hour gaps: the diagnostic rule
            # conservatively excludes their spans even though no calendar day is empty.
            self.assertEqual(summary["gap_sensitivity"]["eligible_users"], 0)


class PublishedSummaryTests(unittest.TestCase):
    def test_aggregate_report_reconciles_and_matches_acquired_files(self):
        docs = Path(__file__).resolve().parents[1] / "docs/phase1"
        if not (docs / "audit_summary.json").exists():
            self.skipTest("Full-data report has not been generated")
        summary = json.loads((docs / "audit_summary.json").read_text())
        manifest = json.loads((docs / "acquisition.json").read_text())
        events = summary["totals"]["events"]
        for group in ("files", "daily", "event_types", "events_by_type"):
            self.assertEqual(sum(row["events"] for row in summary[group]), events)
        self.assertEqual(sum(row["purchase_events"] for row in summary["daily"]), summary["totals"]["purchase_events"])
        eligibility = summary["eligibility"]
        self.assertEqual(eligibility["eligible_users"] + eligibility["ineligible_users"], summary["totals"]["users"])
        self.assertLessEqual(eligibility["eligible_positive_users"], eligibility["eligible_users"])
        self.assertEqual(sum(row["users"] for row in summary["cross_month_users"]), summary["totals"]["users"])
        for column in summary["missing"].values():
            self.assertLessEqual(sum(row["missing"] + row["whitespace_only"] for row in column), events)
        for source in manifest["files"]:
            audited = next(row for row in summary["files"] if row["month"] + ".csv" == source["name"])
            self.assertEqual(audited["csv_sha256"], source["csv_sha256"])
            self.assertEqual(audited["csv_bytes"], source["csv_bytes"])
        for schedule in ("splits", "earlier_conservative_splits"):
            for earlier, later in zip(summary[schedule], summary[schedule][1:]):
                self.assertLessEqual(earlier["latest_outcome_end"], later["prediction_start"])


if __name__ == "__main__":
    unittest.main()
