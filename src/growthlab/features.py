"""Phase 2: frozen, memory-bounded event-to-customer feature engineering.

No preprocessing is fitted. Exactly twelve predictors are allowlisted. Other
columns describe identity, labels, chronology or QA and must not become inputs.
"""

import argparse
import json
import resource
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import duckdb

from growthlab.acquire import digest, save_json
from growthlab.audit import COLUMNS, connect, literal, records, typed_select
from growthlab.design_review import GAP_END, GAP_START, overlap_sql, verify_raw

FEATURE_COLUMNS = (
    "n_views_7d", "n_carts_7d", "n_removals_7d", "n_purchases_7d",
    "n_viewed_products_7d", "active_24h_bins_7d", "n_sessions_7d",
    "hours_since_last_event", "cart_view_ratio_7d", "purchase_view_ratio_7d",
    "median_view_price_7d", "view_price_unavailable_7d",
)
TARGET = "purchased_next_30d"
PRIMARY = (
    ("train", "2019-10-08", "2019-10-13", 87760, 3814),
    ("validation", "2019-11-12", "2019-11-17", 53089, 1150),
    ("test", "2019-12-17", "2019-12-22", 51444, 547),
)
BROADER = (
    ("train", "2019-10-08", "2019-11-01", 328535, 10092),
    ("validation", "2019-12-01", "2019-12-16", 157349, 1985),
    ("test", "2020-01-15", "2020-01-30", 167822, 2140),
)
COVERAGE_END = "2020-03-01 00:00:00"


def clean_sql(source, month):
    """Deduplicate the nine ORIGINAL fields before reparsing deterministic helpers."""
    distinct = f"(SELECT DISTINCT {', '.join(COLUMNS)} FROM {source})"
    return typed_select(distinct, month)


def copy_parquet(con, query, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".parquet.part")
    con.execute(f"COPY ({query}) TO {literal(temporary)} (FORMAT PARQUET, COMPRESSION ZSTD)")
    temporary.replace(destination)


def split_case(schedule):
    clauses = [f"WHEN prediction_time >= TIMESTAMP {literal(start)} AND prediction_time < TIMESTAMP {literal(end)} THEN {literal(name)}"
               for name, start, end, *_ in schedule]
    return "CASE " + " ".join(clauses) + " ELSE NULL END"


def build_customers(con, coverage_end=COVERAGE_END, coverage_gaps=()):
    """Stages 2–5. Expects an events view with the cleaned, typed event layer.

    Separate feature and purchase aggregates prevent a many-to-many join from
    multiplying events. Eligibility is decided without consulting target values.
    """
    con.execute("""CREATE OR REPLACE TABLE first_seen AS SELECT user_key AS user_id,
        min(event_ts) AS first_seen,min(event_ts)+INTERVAL 7 DAY AS prediction_time,
        min(event_ts)+INTERVAL 37 DAY AS outcome_end FROM events GROUP BY user_key""")
    con.execute("CREATE OR REPLACE TABLE coverage_gaps(day TIMESTAMP)")
    if coverage_gaps:
        con.executemany("INSERT INTO coverage_gaps VALUES (?)",[(day,) for day in coverage_gaps])
    con.execute(f"""CREATE OR REPLACE TABLE eligible AS SELECT * FROM first_seen c
        WHERE user_id>0 AND first_seen IS NOT NULL AND outcome_end<=TIMESTAMP {literal(coverage_end)}
        AND NOT EXISTS (SELECT 1 FROM coverage_gaps g
            WHERE g.day<c.outcome_end AND g.day+INTERVAL 1 DAY>c.first_seen)""")
    con.execute("""CREATE OR REPLACE TABLE feature_aggregates AS
        SELECT c.user_id,
            count(*) FILTER (WHERE e.event_type='view') AS n_views_7d,
            count(*) FILTER (WHERE e.event_type='cart') AS n_carts_7d,
            count(*) FILTER (WHERE e.event_type='remove_from_cart') AS n_removals_7d,
            count(*) FILTER (WHERE e.event_type='purchase') AS n_purchases_7d,
            count(DISTINCT e.product_key) FILTER (WHERE e.event_type='view') AS n_viewed_products_7d,
            count(DISTINCT floor(date_diff('second',c.first_seen,e.event_ts)/86400.0)) AS active_24h_bins_7d,
            count(DISTINCT e.user_session) AS n_sessions_7d,
            date_diff('second',max(e.event_ts),c.prediction_time)/3600.0 AS hours_since_last_event,
            median(e.price_value) FILTER (WHERE e.event_type='view' AND isfinite(e.price_value) AND e.price_value>=0) AS median_view_price_7d,
            (count(*) FILTER (WHERE e.event_type='view' AND isfinite(e.price_value) AND e.price_value>=0)=0)::INTEGER AS view_price_unavailable_7d,
            count(*) AS qa_total_events_7d,
            count(*) FILTER (WHERE e.price_value<0) AS qa_negative_price_events_7d,
            count(*) FILTER (WHERE e.price_value=0) AS qa_zero_price_events_7d,
            count(*) FILTER (WHERE e.user_session IS NULL) AS qa_missing_session_events_7d,
            min(e.event_ts) AS qa_first_feature_event,max(e.event_ts) AS qa_last_feature_event
        FROM eligible c JOIN events e ON e.user_key=c.user_id
            AND e.event_ts>=c.first_seen AND e.event_ts<c.prediction_time
        GROUP BY c.user_id,c.first_seen,c.prediction_time""")
    con.execute("""CREATE OR REPLACE TABLE target_aggregates AS SELECT c.user_id,
        count(*) AS purchase_events,min(e.event_ts) AS first_purchase,max(e.event_ts) AS last_purchase
        FROM eligible c JOIN events e ON e.user_key=c.user_id
            AND e.event_ts>=c.prediction_time AND e.event_ts<c.outcome_end
        WHERE e.event_type='purchase' GROUP BY c.user_id""")
    con.execute(f"""CREATE OR REPLACE TABLE customer_features AS SELECT c.*,f.* EXCLUDE(user_id),
        CASE WHEN f.n_views_7d>0 THEN f.n_carts_7d::DOUBLE/f.n_views_7d ELSE 0.0 END AS cart_view_ratio_7d,
        CASE WHEN f.n_views_7d>0 THEN f.n_purchases_7d::DOUBLE/f.n_views_7d ELSE 0.0 END AS purchase_view_ratio_7d,
        (coalesce(t.purchase_events,0)>0)::INTEGER AS {TARGET},
        {split_case(PRIMARY)} AS primary_split,{split_case(BROADER)} AS robustness_split,
        {overlap_sql('c.first_seen','c.prediction_time')} AS feature_gap,
        {overlap_sql('c.prediction_time','c.outcome_end')} AS outcome_gap
        FROM eligible c JOIN feature_aggregates f USING(user_id) LEFT JOIN target_aggregates t USING(user_id)""")


def validate_customers(con, coverage_end=COVERAGE_END):
    """Validate all rows, not only a sample. Fail before publishing exports."""
    checks = records(con,f"""SELECT count(*) AS customers,count(DISTINCT user_id) AS distinct_users,
        count(*) FILTER (WHERE outcome_end>TIMESTAMP {literal(coverage_end)}) AS censored,
        count(*) FILTER (WHERE qa_first_feature_event<>first_seen OR qa_last_feature_event>=prediction_time) AS feature_boundary_errors,
        count(*) FILTER (WHERE prediction_time<>first_seen+INTERVAL 7 DAY OR outcome_end<>first_seen+INTERVAL 37 DAY) AS window_errors,
        count(*) FILTER (WHERE active_24h_bins_7d<1 OR active_24h_bins_7d>7 OR hours_since_last_event<=0 OR hours_since_last_event>168) AS range_errors,
        count(*) FILTER (WHERE qa_total_events_7d<>n_views_7d+n_carts_7d+n_removals_7d+n_purchases_7d) AS event_sum_errors,
        count(*) FILTER (WHERE (median_view_price_7d IS NULL)<>(view_price_unavailable_7d=1)) AS price_missingness_errors,
        count(*) FILTER (WHERE median_view_price_7d<0 OR NOT isfinite(median_view_price_7d)) AS price_range_errors,
        count(*) FILTER (WHERE {TARGET} NOT IN (0,1)) AS target_errors
        FROM customer_features""")[0]
    assert checks["customers"]==checks["distinct_users"]==con.execute("SELECT count(*) FROM eligible").fetchone()[0]
    assert all(value==0 for name,value in checks.items() if name not in {"customers","distinct_users"}), checks
    target_errors=con.execute("""SELECT count(*) FROM target_aggregates t JOIN eligible c USING(user_id)
        WHERE t.first_purchase<c.prediction_time OR t.last_purchase>=c.outcome_end""").fetchone()[0]
    assert target_errors==0
    checks["target_boundary_errors"]=target_errors
    for feature in FEATURE_COLUMNS:
        condition=f"{feature} IS NULL OR {feature}<0 OR NOT isfinite({feature})"
        if feature=="median_view_price_7d":
            condition=f"{feature} IS NOT NULL AND ({feature}<0 OR NOT isfinite({feature}))"
        assert con.execute(f"SELECT count(*) FROM customer_features WHERE {condition}").fetchone()[0]==0,feature
    checks["feature_validity_passed"]=True
    return checks


def split_summary(con,column):
    return records(con,f"""SELECT {column} AS split,count(*) AS customers,sum({TARGET}) AS positives,
        avg({TARGET}) AS positive_rate,min(first_seen) AS earliest_first_seen,
        max(prediction_time) AS latest_prediction,max(outcome_end) AS latest_outcome_end,
        count(*) FILTER (WHERE feature_gap OR outcome_gap) AS gap_overlap_customers
        FROM customer_features GROUP BY 1 ORDER BY 1""")


def validate_frozen_counts(con,phase1):
    population=con.execute(f"SELECT count(*),sum({TARGET}) FROM customer_features").fetchone()
    assert population==(phase1["eligibility"]["eligible_users"],phase1["eligibility"]["eligible_positive_users"]),population
    for name,schedule in (("primary_split",PRIMARY),("robustness_split",BROADER)):
        for split,start,end,n,positives in schedule:
            actual=con.execute(f"SELECT count(*),sum({TARGET}) FROM customer_features WHERE {name}=?",[split]).fetchone()
            assert actual==(n,positives),(name,split,actual)
        for earlier,later in zip(schedule,schedule[1:]):
            latest=con.execute(f"SELECT max(outcome_end) FROM customer_features WHERE {name}=?",[earlier[0]]).fetchone()[0]
            assert latest<=datetime.fromisoformat(later[1])
    assert con.execute("SELECT count(*) FROM customer_features WHERE primary_split IS NOT NULL AND (feature_gap OR outcome_gap)").fetchone()[0]==0


def distribution_summary(con):
    output={}
    # Unconditional summaries only; no feature/target association or selection.
    for split in ("all_eligible","train","validation","test"):
        where="" if split=="all_eligible" else " WHERE primary_split="+literal(split)
        output[split]={}
        for feature in FEATURE_COLUMNS:
            output[split][feature]=records(con,f"""SELECT count(*) AS customers,
                count(*) FILTER (WHERE {feature} IS NULL) AS missing,
                count(*) FILTER (WHERE {feature}=0) AS zeros,
                min({feature}) AS minimum,max({feature}) AS maximum,avg({feature}) AS mean,
                quantile_cont({feature},[0.5,0.9,0.99]) AS p50_p90_p99
                FROM customer_features {where}""")[0]
    return output


def run(root):
    root=root.resolve()
    started=time.monotonic()
    if shutil.disk_usage(root).free < 30*1024**3:
        raise RuntimeError("Require 30 GiB free for build/spill plus OS safety margin")
    phase1=json.loads((root/"docs/phase1/audit_summary.json").read_text())
    evidence=json.loads((root/"docs/phase1_5/evidence.json").read_text())
    manifest=json.loads((root/"docs/phase1/acquisition.json").read_text())
    spec=json.loads((root/"docs/phase2_specification.json").read_text())
    assert spec["feature_columns"]==list(FEATURE_COLUMNS)
    assert spec["primary_splits"]==[list(s) for s in PRIMARY]
    assert spec["broader_splits"]==[list(s) for s in BROADER]
    print("Stage 0: verifying immutable source files and frozen specification",flush=True)
    raw_before=verify_raw(root,manifest)
    work=root/"data/features/phase2"
    work.mkdir(parents=True,exist_ok=True)
    con=connect(work/"build.duckdb",work/"spill","1GB")
    summary={"specification_sha256":digest(root/"docs/phase2_specification.json"),
             "feature_columns":list(FEATURE_COLUMNS),"target":TARGET,"raw_hashes_before":raw_before,
             "memory_limit":"1GB","threads":1,"max_spill":"8GB","cleaned_months":[]}
    inputs={}
    try:
        paths=[]
        for item in phase1["files"]:
            month=item["month"]
            path=root/"data/processed"/(month+".parquet")
            inputs[month]=digest(path)
            assert inputs[month]==evidence["parquet_sha256"][month],month
            print("Stage 1: exact-row deduplication:",month,flush=True)
            source=f"read_parquet({literal(path)})"
            dest=work/"cleaned"/(month+".parquet")
            copy_parquet(con,clean_sql(source,month),dest)
            paths.append(dest)
            stats=records(con,f"""SELECT count(*) AS events,count(*) FILTER (WHERE event_type='purchase') AS purchases,
                count(*) FILTER (WHERE event_ts IS NULL OR user_key IS NULL OR user_key<=0 OR product_key IS NULL
                    OR category_key IS NULL OR price_value IS NULL OR NOT isfinite(price_value)
                    OR event_type NOT IN ('view','cart','remove_from_cart','purchase') OR event_type IS NULL
                    OR strftime(event_ts,'%Y-%b')<>source_month) AS invalid_rows FROM read_parquet({literal(dest)})""")[0]
            expected=item["events"]-item["duplicates"]["excess_rows"]
            assert stats["events"]==expected and stats["invalid_rows"]==0,(month,stats)
            summary["cleaned_months"].append({"month":month,**stats,"bytes":dest.stat().st_size,"sha256":digest(dest)})
        con.execute("CREATE OR REPLACE VIEW events AS SELECT * FROM read_parquet(["+",".join(literal(p) for p in paths)+"])")
        dates=[row[0] for row in con.execute("SELECT DISTINCT event_ts::DATE FROM events ORDER BY 1").fetchall()]
        first=datetime(2019,10,1).date()
        expected_days=[first+timedelta(days=d) for d in range((datetime(2020,3,1).date()-first).days)]
        assert dates==expected_days,"Unexpected daily coverage; review eligibility before continuing"
        assert con.execute("SELECT count(*) FROM events WHERE event_ts>=TIMESTAMP '2020-03-01'").fetchone()[0]==0
        print("Stages 2–5: global first appearances, eligibility, disjoint feature/target aggregates, QA",flush=True)
        build_customers(con)
        summary["validation"]=validate_customers(con)
        validate_frozen_counts(con,phase1)
        summary["primary_splits"]=split_summary(con,"primary_split")
        summary["broader_assignments"]=split_summary(con,"robustness_split")
        summary["all_eligible"]=records(con,f"SELECT count(*) AS customers,sum({TARGET}) AS positives,avg({TARGET}) AS positive_rate FROM customer_features")[0]
        summary["qa"]=records(con,"""SELECT sum(qa_zero_price_events_7d) AS zero_price_events,
            count(*) FILTER (WHERE qa_zero_price_events_7d>0) AS zero_price_customers,
            sum(qa_negative_price_events_7d) AS negative_price_events,
            count(*) FILTER (WHERE qa_negative_price_events_7d>0) AS negative_price_customers,
            sum(qa_missing_session_events_7d) AS missing_session_events,
            count(*) FILTER (WHERE feature_gap) AS feature_gap_customers,
            count(*) FILTER (WHERE outcome_gap) AS outcome_gap_customers FROM customer_features""")[0]
        summary["feature_distributions"]=distribution_summary(con)
        print("Stage 6: exporting validated customer table and primary splits",flush=True)
        copy_parquet(con,"SELECT * FROM customer_features",work/"customers.parquet")
        projection=", ".join(("user_id",*FEATURE_COLUMNS,TARGET))
        for split,*_ in PRIMARY:
            copy_parquet(con,f"SELECT {projection} FROM customer_features WHERE primary_split={literal(split)}",work/"primary"/(split+".parquet"))
        # Export schema is an enforceable model/QA boundary; explicit feature allowlist
        # is still required to keep the numeric user_id out of modeling.
        summary["export_files"]={}
        for path in [work/"customers.parquet",*sorted((work/"primary").glob("*.parquet"))]:
            schema=records(con,f"DESCRIBE SELECT * FROM read_parquet({literal(path)})")
            if path.parent.name=="primary":
                assert [r["column_name"] for r in schema]==["user_id",*FEATURE_COLUMNS,TARGET]
                split=path.stem
                actual=con.execute(f"SELECT count(*),sum({TARGET}),count(DISTINCT user_id) FROM read_parquet({literal(path)})").fetchone()
                expected=next(s for s in PRIMARY if s[0]==split)
                assert actual==(expected[3],expected[4],expected[3]),actual
            summary["export_files"][str(path.relative_to(root))]={"bytes":path.stat().st_size,"sha256":digest(path),"schema":schema}
        print("Stage 7: independently checking selected real histories from raw CSVs",flush=True)
        from growthlab.history_verification import verify_histories
        summary["history_verification"]=verify_histories(con,root,work)
        summary["raw_hashes_after"]=verify_raw(root,manifest)
        assert summary["raw_hashes_after"]==raw_before
        assert all(digest(root/"data/processed"/(m+".parquet"))==h for m,h in inputs.items())
        summary["source_parquet_sha256"]=inputs
        summary["source_code_sha256"]={str(p.relative_to(root)):digest(p) for p in
            [Path(__file__).resolve(),root/"src/growthlab/history_verification.py",root/"src/growthlab/audit.py",root/"src/growthlab/design_review.py"]}
        summary["elapsed_seconds"]=round(time.monotonic()-started,2)
        rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        summary["peak_process_rss_bytes"]=rss if sys.platform=="darwin" else rss*1024
        summary["disk_free_after_bytes"]=shutil.disk_usage(root).free
        summary["peak_spill_usage_note"]="Not measured; engine spill capped at 8GB."
        save_json(root/"docs/phase2/summary.json",summary)
        save_json(work/"manifest.json",summary)
        print(json.dumps({"all_eligible":summary["all_eligible"],"primary_splits":summary["primary_splits"],
                          "history_verification":summary["history_verification"],"seconds":summary["elapsed_seconds"]},default=str,indent=2),flush=True)
        return summary
    finally:
        con.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path.cwd())
    run(parser.parse_args().root)


if __name__=="__main__":
    main()
