"""Phase 1.5 diagnostic queries; does not create cleaned events or model features.

Read existing Phase 1 Parquet; verify raw SHA-256 before and after. Only aggregate
evidence is exported. Local intermediate tables stay under ignored data/design/.
"""

import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from growthlab.acquire import digest, save_json
from growthlab.audit import COLUMNS, EARLIER_SPLITS, SPLITS, build_customers, connect, literal, records

GAP_LAST = "2020-01-22 02:52:08"
GAP_START = "2020-01-22 02:52:09"  # One-second source resolution.
GAP_END = "2020-01-22 03:26:14"    # First observed event after the pause.


def overlap_sql(start, end, gap_start=GAP_START, gap_end=GAP_END):
    """Nonempty intersection of two half-open timestamp intervals."""
    return f"({start} < TIMESTAMP {literal(gap_end)} AND {end} > TIMESTAMP {literal(gap_start)})"


def duplicate_groups_sql(source):
    # Includes NULL session/brand/category fields in grouping; derived fields are
    # functionally determined by originals, not added to the duplicate key.
    return f"""SELECT {', '.join(COLUMNS)}, any_value(user_key) AS user_key,
        count(*) AS n FROM {source} GROUP BY {', '.join(COLUMNS)} HAVING count(*) > 1"""


def gap_cohort(con):
    con.execute(f"""CREATE OR REPLACE VIEW gap_cohort AS SELECT *,
        {overlap_sql('t0', 'prediction_time')} AS feature_gap,
        {overlap_sql('prediction_time', 'outcome_end')} AS outcome_gap FROM cohort""")


def summarize_schedule(con, schedule, exclude_gap=False):
    output = []
    for name, start, end in schedule:
        clause = " AND NOT feature_gap AND NOT outcome_gap" if exclude_gap else ""
        row = records(con, f"""SELECT count(*) AS users,
            count(*) FILTER (WHERE positive) AS positives,
            avg(CAST(positive AS DOUBLE)) AS positive_rate,
            min(t0) AS earliest_first_seen, max(t0) AS latest_first_seen,
            min(prediction_time) AS earliest_prediction, max(prediction_time) AS latest_prediction,
            min(outcome_end) AS earliest_outcome_end, max(outcome_end) AS latest_outcome_end,
            count(*) FILTER (WHERE feature_gap) AS feature_gap_users,
            count(*) FILTER (WHERE outcome_gap) AS outcome_gap_users,
            count(*) FILTER (WHERE feature_gap OR outcome_gap) AS any_gap_users
            FROM gap_cohort WHERE eligible AND prediction_time >= TIMESTAMP {literal(start)}
            AND prediction_time < TIMESTAMP {literal(end)} {clause}""")[0]
        output.append({"split": name, "prediction_start": start, "prediction_end_exclusive": end, **row})
    return output


def verify_raw(root, manifest):
    verified = {}
    for entry in manifest["files"]:
        path = root / "data/raw" / entry["name"]
        if path.stat().st_size != entry["csv_bytes"] or digest(path) != entry["csv_sha256"]:
            raise ValueError(f"Raw source missing or changed: {entry['name']}")
        verified[entry["name"]] = entry["csv_sha256"]
    return verified


def run(root):
    root = root.resolve()
    started = time.monotonic()
    manifest = json.loads((root / "docs/phase1/acquisition.json").read_text())
    phase1 = json.loads((root / "docs/phase1/audit_summary.json").read_text())
    print("Verifying raw hashes; no downloads or raw writes", flush=True)
    before = verify_raw(root, manifest)
    work = root / "data/design"
    work.mkdir(parents=True, exist_ok=True)
    con = connect(work / "diagnostics.duckdb", work / "spill", "1GB")
    result = {"analysis_source_sha256": digest(Path(__file__)), "memory_limit": "1GB", "threads": 1,
              "raw_hashes_before": before, "duplicates_by_month_type": []}
    parquet_hashes = {}
    paths = []
    try:
        con.execute("CREATE OR REPLACE TABLE duplicate_user_parts(user_key BIGINT, excess BIGINT)")
        for f in phase1["files"]:
            month = f["month"]
            path = root / "data/processed" / (month + ".parquet")
            if path.stat().st_size != f["parquet_bytes"]:
                raise ValueError(f"Phase 1 Parquet changed: {month}")
            parquet_hashes[month] = digest(path)
            paths.append(path)
            print(f"Investigating duplicates: {month}", flush=True)
            con.execute(f"CREATE OR REPLACE VIEW monthly AS SELECT * FROM read_parquet({literal(path)})")
            con.execute("CREATE OR REPLACE TEMP TABLE duplicate_groups AS " + duplicate_groups_sql("monthly"))
            result["duplicates_by_month_type"] += records(con, f"""WITH raw AS
                (SELECT event_type,count(*) AS raw_events FROM monthly GROUP BY 1), duplicates AS
                (SELECT event_type,count(*) AS duplicate_groups,sum(n-1) AS excess FROM duplicate_groups GROUP BY 1)
                SELECT {literal(month)} AS month,event_type,raw_events,coalesce(duplicate_groups,0) AS duplicate_groups,
                    coalesce(excess,0) AS excess,raw_events-coalesce(excess,0) AS deduplicated_events
                FROM raw LEFT JOIN duplicates USING(event_type) ORDER BY event_type""")
            con.execute("INSERT INTO duplicate_user_parts SELECT user_key,sum(n-1) FROM duplicate_groups GROUP BY user_key")
        con.execute("""CREATE OR REPLACE TABLE duplicate_users AS SELECT user_key,sum(excess) AS excess
            FROM duplicate_user_parts GROUP BY user_key""")
        result["duplicate_user_concentration"] = records(con, """SELECT count(*) AS affected_users,
            sum(excess) AS total_excess,max(excess) AS maximum_excess_per_user,
            quantile_disc(excess,[0.5,0.9,0.99]) AS affected_user_excess_p50_p90_p99
            FROM duplicate_users""")[0]
        result["duplicate_user_concentration"]["top_shares"] = records(con, """WITH ranked AS
            (SELECT excess,row_number() OVER (ORDER BY excess DESC,user_key) AS rank FROM duplicate_users)
            SELECT sum(excess) FILTER (WHERE rank<=10) AS top_10_excess,
                sum(excess) FILTER (WHERE rank<=100) AS top_100_excess,
                sum(excess) FILTER (WHERE rank<=1000) AS top_1000_excess FROM ranked""")[0]
        path_list = "[" + ",".join(literal(p) for p in paths) + "]"
        con.execute(f"CREATE OR REPLACE VIEW events AS SELECT * FROM read_parquet({path_list})")
        observed_bounds = con.execute(f"""SELECT
            max(event_ts) FILTER (WHERE event_ts < TIMESTAMP {literal(GAP_START)}),
            min(event_ts) FILTER (WHERE event_ts >= TIMESTAMP {literal(GAP_START)}) FROM events""").fetchone()
        if observed_bounds != (datetime.fromisoformat(GAP_LAST), datetime.fromisoformat(GAP_END)):
            raise ValueError("January gap boundaries no longer match Phase 1; review the input")
        result["duplicate_user_concentration"]["activity_buckets"] = records(con, """WITH users AS
            (SELECT user_key,count(*) AS events FROM events GROUP BY 1)
            SELECT CASE WHEN events<10 THEN '1-9' WHEN events<100 THEN '10-99'
                WHEN events<1000 THEN '100-999' ELSE '1000+' END AS raw_event_bucket,
                count(*) AS users,count(d.user_key) AS duplicate_affected_users,sum(coalesce(d.excess,0)) AS excess
            FROM users u LEFT JOIN duplicate_users d USING(user_key) GROUP BY 1 ORDER BY 1""")
        result["price_and_session_details"] = records(con, """SELECT source_month,event_type,
            count(*) FILTER (WHERE price_value<0) AS negative_price,
            count(DISTINCT user_key) FILTER (WHERE price_value<0) AS negative_price_users,
            count(*) FILTER (WHERE price_value=0) AS zero_price,
            count(DISTINCT product_key) FILTER (WHERE price_value=0) AS zero_price_products,
            count(*) FILTER (WHERE user_session IS NULL) AS missing_session_events
            FROM events GROUP BY 1,2 ORDER BY 1,2""")
        result["shared_sessions"] = records(con, """WITH shared AS
            (SELECT user_session,count(DISTINCT user_key) AS users FROM events
                WHERE user_session IS NOT NULL GROUP BY 1 HAVING count(DISTINCT user_key)>1)
            SELECT count(*) AS affected_events,count(DISTINCT e.user_key) AS affected_users,
                count(DISTINCT e.user_session) AS shared_session_ids
            FROM events e JOIN shared s USING(user_session)""")[0]
        # Nearby dates and same-weekday controls: identical UTC clock interval.
        g0, g1 = datetime.fromisoformat(GAP_START), datetime.fromisoformat(GAP_END)
        duration = g1 - g0
        comparisons = []
        for offset in (-14,-7,-2,-1,0,1,2,7,14):
            for label, a, b in (("before",g0-duration,g0),("gap_clock_interval",g0,g1),("after",g1,g1+duration)):
                a, b = a + timedelta(days=offset), b + timedelta(days=offset)
                comparisons.append(f"({literal(str(a))}::TIMESTAMP,{literal(str(b))}::TIMESTAMP,{offset},{literal(label)})")
        con.execute("CREATE OR REPLACE TABLE comparison_intervals AS SELECT * FROM (VALUES " + ",".join(comparisons) + ") AS v(start_time,end_time,day_offset,window_name)")
        result["gap"] = {"last_event_before": GAP_LAST, "first_event_after": GAP_END,
                         "unobserved_start_inclusive": GAP_START,"unobserved_end_exclusive": GAP_END,
                         "inter_event_seconds": 2046,"unobserved_timestamp_seconds": int(duration.total_seconds())}
        result["gap"]["comparisons"] = records(con, """SELECT i.day_offset,i.window_name,i.start_time,i.end_time,
            count(e.event_ts) AS events,count(DISTINCT e.user_key) AS users,
            count(*) FILTER (WHERE e.event_type='purchase') AS purchase_events
            FROM comparison_intervals i LEFT JOIN events e ON e.event_ts>=i.start_time AND e.event_ts<i.end_time
            GROUP BY ALL ORDER BY day_offset,start_time""")
        result["gap"]["five_minute_counts"] = records(con, """WITH bins AS
            (SELECT ts FROM generate_series(TIMESTAMP '2020-01-22 02:00:00',
                TIMESTAMP '2020-01-22 03:55:00', INTERVAL 5 MINUTE) AS v(ts))
            SELECT b.ts AS start_time,count(e.event_ts) AS events FROM bins b LEFT JOIN events e
            ON e.event_ts>=b.ts AND e.event_ts<b.ts+INTERVAL 5 MINUTE GROUP BY 1 ORDER BY 1""")
        con.execute("CREATE OR REPLACE TABLE coverage_gaps(day TIMESTAMP)")
        build_customers(con, "2020-03-01 00:00:00")
        gap_cohort(con)
        result["gap"]["customer_overlap"] = records(con, """SELECT eligible,feature_gap,outcome_gap,
            count(*) AS users,count(*) FILTER (WHERE positive) AS positives
            FROM gap_cohort GROUP BY ALL ORDER BY eligible,feature_gap,outcome_gap""")
        result["gap"]["overlap_totals"] = records(con, """SELECT count(*) AS users,
            count(*) FILTER (WHERE eligible) AS eligible_users,
            count(*) FILTER (WHERE feature_gap) AS feature_overlap,
            count(*) FILTER (WHERE outcome_gap) AS outcome_overlap,
            count(*) FILTER (WHERE feature_gap AND outcome_gap) AS both_overlap,
            count(*) FILTER (WHERE NOT feature_gap AND NOT outcome_gap) AS neither_overlap
            FROM gap_cohort""")[0]
        result["schedules"] = {"broad_retain": summarize_schedule(con,SPLITS),
                               "broad_exclude_gap": summarize_schedule(con,SPLITS,True),
                               "earlier_gap_free": summarize_schedule(con,EARLIER_SPLITS,True)}
        result["price_target_sensitivity"] = records(con, """WITH positive_price AS
            (SELECT DISTINCT e.user_key FROM events e JOIN customers c USING(user_key)
             WHERE e.event_type='purchase' AND e.price_value>0 AND e.event_ts>=c.prediction_time
               AND e.event_ts<c.outcome_end)
            SELECT count(*) AS eligible_users,count(*) FILTER (WHERE c.positive) AS event_type_positives,
                count(p.user_key) AS positive_price_positives FROM cohort c LEFT JOIN positive_price p USING(user_key)
            WHERE c.eligible""")[0]
        print("Verifying input preservation and summary reconciliation", flush=True)
        result["raw_hashes_after"] = verify_raw(root, manifest)
        assert result["raw_hashes_after"] == before
        assert all(digest(root/"data/processed"/(m+".parquet"))==h for m,h in parquet_hashes.items())
        result["parquet_sha256"] = parquet_hashes
        result["elapsed_seconds"] = round(time.monotonic()-started,2)
        validate_result(result,phase1)
        save_json(root / "docs/phase1_5/evidence.json",result)
        print(json.dumps({"duplicates":result["duplicate_user_concentration"],"gap":result["gap"]["overlap_totals"],
                          "price_target":result["price_target_sensitivity"]},indent=2),flush=True)
        return result
    finally:
        con.close()


def validate_result(result,phase1):
    assert sum(r["raw_events"] for r in result["duplicates_by_month_type"]) == phase1["totals"]["events"]
    assert sum(r["excess"] for r in result["duplicates_by_month_type"]) == phase1["duplicates"]["excess_rows"]
    overlap=result["gap"]["overlap_totals"]
    assert overlap["feature_overlap"]+overlap["outcome_overlap"]-overlap["both_overlap"]+overlap["neither_overlap"]==overlap["users"]
    for schedule, key in [("broad_retain","splits"),("earlier_gap_free","earlier_conservative_splits")]:
        for actual,previous in zip(result["schedules"][schedule],phase1[key]):
            assert actual["users"]==previous["users"] and actual["positives"]==previous["positive_users"]
            assert actual["latest_outcome_end"]==datetime.fromisoformat(previous["latest_outcome_end"])
        for previous, following in zip(result["schedules"][schedule],result["schedules"][schedule][1:]):
            assert previous["latest_outcome_end"] <= datetime.fromisoformat(following["prediction_start"])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path.cwd())
    run(parser.parse_args().root)


if __name__=="__main__":
    main()
