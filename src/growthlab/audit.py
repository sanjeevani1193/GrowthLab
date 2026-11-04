"""Disk-backed quality audit, not a customer feature/modeling pipeline.

Raw text is retained in local Parquet so exact duplicate and parsing diagnostics
do not disappear during conversion. Only aggregate summaries leave data/.
All naive SQL timestamps in this module represent UTC, matching the source.
"""

import argparse
import csv
import json
import resource
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import duckdb

from growthlab.acquire import MONTHS, RESERVE, digest, save_json

COLUMNS = ("event_time", "event_type", "product_id", "category_id", "category_code",
           "brand", "price", "user_id", "user_session")
SPLITS = (
    ("train", "2019-10-08", "2019-11-01"),
    ("validation", "2019-12-01", "2019-12-16"),
    ("test", "2020-01-15", "2020-01-30"),
)
EARLIER_SPLITS = (
    ("train", "2019-10-08", "2019-10-13"),
    ("validation", "2019-11-12", "2019-11-17"),
    ("test", "2019-12-17", "2019-12-22"),
)


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def records(con, sql):
    result = con.execute(sql)
    names = [d[0] for d in result.description]
    return [dict(zip(names, row)) for row in result.fetchall()]


def connect(path, spill, memory="1GB"):
    if memory not in {"256MB", "512MB", "1GB", "2GB"}:
        raise ValueError("Memory must be 256MB, 512MB, 1GB or 2GB")
    spill.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path), config={"memory_limit": memory, "threads": 1})
    con.execute("SET TimeZone = 'UTC'")
    con.execute("SET preserve_insertion_order = false")
    con.execute("SET temp_directory = " + literal(spill))
    con.execute("SET max_temp_directory_size = '8GB'")
    return con


def typed_select(source, month):
    ids = []
    for raw, parsed in [("product_id", "product_key"), ("category_id", "category_key"), ("user_id", "user_key")]:
        ids.append(f"CASE WHEN regexp_full_match({raw}, '[0-9]+') THEN try_cast({raw} AS BIGINT) END AS {parsed}")
    return f"""SELECT *, try_strptime(event_time, '%Y-%m-%d %H:%M:%S UTC') AS event_ts,
        {', '.join(ids)}, try_cast(price AS DOUBLE) AS price_value,
        {literal(month)} AS source_month FROM {source}"""


def convert(con, source, destination, month):
    with source.open(newline="") as stream:
        if tuple(next(csv.reader(stream))) != COLUMNS:
            raise ValueError(f"Unexpected header: {source.name}")
    raw = f"read_csv({literal(source)}, header=true, all_varchar=true, nullstr='', strict_mode=true, parallel=false)"
    temporary = destination.with_suffix(".parquet.part")
    con.execute(f"COPY ({typed_select(raw, month)}) TO {literal(temporary)} (FORMAT PARQUET, COMPRESSION ZSTD)")
    temporary.replace(destination)


def build_customers(con, coverage_end):
    """One row per valid observed user, including censored users for denominators.

    Positive labels are calculated for everyone, then masked by eligibility.
    Incomplete early-positive histories must not enter the eligible cohort.
    """
    con.execute("""CREATE OR REPLACE TABLE customers AS
        SELECT user_key, min(event_ts) AS t0, max(event_ts) AS last_event,
               count(*) AS events, count(DISTINCT CAST(event_ts AS DATE)) AS active_days,
               min(event_ts) + INTERVAL 7 DAY AS prediction_time,
               min(event_ts) + INTERVAL 37 DAY AS outcome_end
        FROM events WHERE user_key IS NOT NULL AND user_key > 0 AND event_ts IS NOT NULL
        GROUP BY user_key""")
    con.execute(f"""CREATE OR REPLACE TABLE outcomes AS
        SELECT c.user_key, count(*) AS purchase_events
        FROM events e JOIN customers c ON e.user_key=c.user_key
        WHERE e.event_type='purchase' AND e.event_ts >= c.prediction_time
          AND e.event_ts < c.outcome_end GROUP BY c.user_key""")
    # Exclude any customer whose feature/outcome span intersects a zero-event day.
    # Nonzero days do NOT prove complete instrumentation; that remains an assumption.
    con.execute(f"""CREATE OR REPLACE VIEW cohort AS
        SELECT c.*, coalesce(o.purchase_events, 0) AS future_purchase_events,
          c.outcome_end <= TIMESTAMP {literal(coverage_end)}
          AND NOT EXISTS (SELECT 1 FROM coverage_gaps g
            WHERE g.day < c.outcome_end AND g.day + INTERVAL 1 DAY > c.t0) AS eligible,
          coalesce(o.purchase_events, 0) > 0 AS positive
        FROM customers c LEFT JOIN outcomes o USING(user_key)""")


def run_audit(root, months=MONTHS, coverage_end="2020-03-01 00:00:00", memory="1GB"):
    started = time.monotonic()
    root = root.resolve()
    raw, processed, work = root / "data/raw", root / "data/processed", root / "data/audit"
    for directory in (processed, work):
        directory.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < RESERVE + 8 * 1024**3:
        raise RuntimeError("Insufficient disk for audit spill plus safety reserve")
    con = connect(work / "audit.duckdb", work / "spill", memory)
    output = {"duckdb_version": duckdb.__version__, "python_version": sys.version.split()[0],
              "audit_source_sha256": digest(Path(__file__)), "memory_limit": memory, "threads": 1,
              "max_spill": "8GB", "coverage_end_assumed_exclusive_utc": coverage_end,
              "assumptions": ["Nonempty days are assumed logged; partial logging outages cannot be ruled out.",
                              "A user_id is treated as persistent across months, not proven to identify a person."],
              "files": [], "daily": [], "events_by_type": [], "missing": {}, "parsing": {}}
    paths = []
    try:
        for month in months:
            source, destination = raw / (month + ".csv"), processed / (month + ".parquet")
            print(f"Converting/auditing {month}", flush=True)
            # Reconvert deliberately: source fingerprints are recorded, not used as unverified cache keys.
            convert(con, source, destination, month)
            paths.append(destination)
            con.execute(f"CREATE OR REPLACE VIEW month_events AS SELECT * FROM read_parquet({literal(destination)})")
            stats = records(con, """SELECT count(*) AS events, count(DISTINCT user_key) AS users,
                min(event_ts) AS first_event, max(event_ts) AS last_event,
                count(*) FILTER (WHERE event_type='purchase') AS purchase_events,
                count(*) FILTER (WHERE strftime(event_ts, '%Y-%b') <> source_month) AS wrong_month
                FROM month_events""")[0]
            stats.update({"month": month, "csv_bytes": source.stat().st_size, "csv_sha256": digest(source),
                          "parquet_bytes": destination.stat().st_size})
            # Exact duplicate source records after CSV decoding; no deduplication is performed.
            con.execute(f"""CREATE OR REPLACE TEMP TABLE duplicate_groups AS SELECT event_type, count(*) AS n
                FROM month_events GROUP BY {', '.join(COLUMNS)} HAVING count(*)>1""")
            dup = records(con, """SELECT count(*) AS duplicate_groups, coalesce(sum(n-1),0) AS excess_rows,
                coalesce(sum(n),0) AS rows_in_duplicate_groups, coalesce(max(n),0) AS largest_multiplicity
                FROM duplicate_groups""")[0]
            stats["duplicates"] = dup
            stats["duplicates_by_type"] = records(con, """SELECT event_type, sum(n-1) AS excess_rows
                FROM duplicate_groups GROUP BY 1 ORDER BY 1""")
            output["files"].append(stats)
            output["daily"] += records(con, """SELECT CAST(event_ts AS DATE) AS day, count(*) AS events,
                count(DISTINCT user_key) AS users, count(*) FILTER (WHERE event_type='purchase') AS purchase_events
                FROM month_events GROUP BY 1 ORDER BY 1""")
            output["events_by_type"] += records(con, """SELECT source_month AS month, event_type, count(*) AS events
                FROM month_events GROUP BY 1,2 ORDER BY 2""")
            for col in COLUMNS:
                missing = records(con, f"""SELECT count(*) FILTER (WHERE {col} IS NULL) AS missing,
                    count(*) FILTER (WHERE {col} IS NOT NULL AND trim({col})='') AS whitespace_only
                    FROM month_events""")[0]
                output["missing"].setdefault(col, []).append({"month": month, **missing})
            invalid = records(con, """SELECT
                count(*) FILTER (WHERE event_time IS NOT NULL AND event_ts IS NULL) AS invalid_timestamp,
                count(*) FILTER (WHERE product_id IS NOT NULL AND product_key IS NULL) AS invalid_product_id,
                count(*) FILTER (WHERE category_id IS NOT NULL AND category_key IS NULL) AS invalid_category_id,
                count(*) FILTER (WHERE user_id IS NOT NULL AND user_key IS NULL) AS invalid_user_id,
                count(*) FILTER (WHERE price IS NOT NULL AND (price_value IS NULL OR NOT isfinite(price_value))) AS invalid_price,
                count(*) FILTER (WHERE product_key<=0 OR category_key<=0 OR user_key<=0) AS nonpositive_id,
                count(*) FILTER (WHERE event_type IS NULL OR event_type NOT IN ('view','cart','remove_from_cart','purchase')) AS unknown_event_type,
                count(*) FILTER (WHERE price_value < 0) AS negative_price,
                count(*) FILTER (WHERE price_value = 0) AS zero_price,
                min(price_value) AS minimum_price, max(price_value) AS maximum_price,
                max(category_key) > 9007199254740992 AS category_exceeds_float64_exact_integer
                FROM month_events""")[0]
            output["parsing"][month] = invalid

        path_list = "[" + ",".join(literal(p) for p in paths) + "]"
        con.execute(f"CREATE OR REPLACE VIEW events AS SELECT * FROM read_parquet({path_list})")
        output["totals"] = records(con, """SELECT count(*) AS events, count(DISTINCT user_key) AS users,
            min(event_ts) AS first_event, max(event_ts) AS last_event,
            count(*) FILTER (WHERE event_type='purchase') AS purchase_events FROM events""")[0]
        output["event_types"] = records(con, "SELECT event_type, count(*) AS events FROM events GROUP BY 1 ORDER BY 1")
        if any(f["wrong_month"] for f in output["files"]) or any(p["invalid_timestamp"] for p in output["parsing"].values()):
            output["duplicates"] = records(con, f"""SELECT count(*) AS duplicate_groups,
                coalesce(sum(n-1),0) AS excess_rows, coalesce(sum(n),0) AS rows_in_duplicate_groups,
                coalesce(max(n),0) AS largest_multiplicity FROM
                (SELECT count(*) AS n FROM events GROUP BY {', '.join(COLUMNS)} HAVING count(*)>1)""")[0]
        else:
            output["duplicates"] = {key: (max(f["duplicates"][key] for f in output["files"])
                if key == "largest_multiplicity" else sum(f["duplicates"][key] for f in output["files"]))
                for key in output["files"][0]["duplicates"]}
        output["duplicate_definition"] = "Equal values in all nine original CSV fields after CSV decoding; no rows removed."
        # Generate a calendar rather than only listing dates that happen to have events.
        first = output["totals"]["first_event"].date()
        last = datetime.fromisoformat(coverage_end).date()
        if output["totals"]["last_event"] >= datetime.fromisoformat(coverage_end):
            raise ValueError("Coverage end must be after every event")
        daily = {row["day"]: row for row in output["daily"]}
        missing_days = []
        for offset in range((last - first).days):
            day = first + timedelta(days=offset)
            if day not in daily:
                missing_days.append(day)
        con.execute("CREATE OR REPLACE TABLE coverage_gaps(day TIMESTAMP)")
        if missing_days:
            con.executemany("INSERT INTO coverage_gaps VALUES (?)", [(d,) for d in missing_days])
        output["coverage"] = {"zero_event_days": missing_days, "expected_days": (last-first).days,
                              "observed_days": len(daily), "minimum_daily_events": min(r["events"] for r in daily.values())}
        output["coverage"]["largest_timestamp_gaps"] = records(con, """SELECT previous_event, event_ts,
            date_diff('second', previous_event, event_ts) AS seconds
            FROM (SELECT event_ts, lag(event_ts) OVER (ORDER BY event_ts) AS previous_event
                  FROM (SELECT DISTINCT event_ts FROM events WHERE event_ts IS NOT NULL))
            WHERE previous_event IS NOT NULL ORDER BY seconds DESC, event_ts LIMIT 10""")
        output["coverage"]["zero_event_hours"] = records(con, f"""SELECT hour FROM
            generate_series(TIMESTAMP {literal(first)}, TIMESTAMP {literal(coverage_end)} - INTERVAL 1 HOUR,
                            INTERVAL 1 HOUR) AS calendar(hour)
            ANTI JOIN (SELECT DISTINCT date_trunc('hour',event_ts) AS hour FROM events) actual USING(hour)
            ORDER BY hour""")
        output["identifiers"] = records(con, """SELECT
            count(*) FILTER (WHERE user_key > 9007199254740992) AS user_ids_above_float64_exact_range,
            count(*) FILTER (WHERE category_key > 9007199254740992) AS category_ids_above_float64_exact_range,
            count(*) FILTER (WHERE product_key > 9007199254740992) AS product_ids_above_float64_exact_range,
            count(*) FILTER (WHERE user_session IS NOT NULL AND NOT regexp_full_match(user_session,
                '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')) AS non_uuid_session_rows
            FROM events""")[0]
        output["prices_by_event_type"] = records(con, """SELECT event_type, count(*) AS events,
            count(*) FILTER (WHERE price_value < 0) AS negative_price,
            count(*) FILTER (WHERE price_value = 0) AS zero_price,
            quantile_cont(price_value, [0.5,0.95,0.99]) AS price_quantiles_p50_p95_p99
            FROM events GROUP BY 1 ORDER BY 1""")
        output["session_consistency"] = records(con, """SELECT count(*) AS sessions,
            count(*) FILTER (WHERE users>1) AS sessions_with_multiple_users,
            max(users) AS maximum_users_per_session FROM
            (SELECT user_session, count(DISTINCT user_key) AS users FROM events
             WHERE user_session IS NOT NULL GROUP BY user_session)""")[0]
        output["product_consistency"] = records(con, """SELECT count(*) AS products,
            count(*) FILTER (WHERE categories>1) AS products_with_multiple_category_ids,
            count(*) FILTER (WHERE brands>1) AS products_with_multiple_nonmissing_brands,
            count(*) FILTER (WHERE prices>1) AS products_with_multiple_prices
            FROM (SELECT product_key, count(DISTINCT category_key) AS categories,
                  count(DISTINCT brand) AS brands, count(DISTINCT price_value) AS prices
                  FROM events WHERE product_key IS NOT NULL GROUP BY product_key)""")[0]
        build_customers(con, coverage_end)
        output["customer_activity"] = records(con, """SELECT count(*) AS users,
            min(events) AS minimum_events, max(events) AS maximum_events, avg(events) AS mean_events,
            quantile_disc(events, [0.5,0.9,0.95,0.99]) AS event_quantiles_p50_p90_p95_p99,
            quantile_disc(active_days, [0.5,0.9,0.95,0.99]) AS active_day_quantiles_p50_p90_p95_p99,
            count(*) FILTER (WHERE events=1) AS single_event_users,
            count(*) FILTER (WHERE active_days=1) AS single_day_users,
            count(*) FILTER (WHERE events>1000) AS users_above_1000_events,
            count(*) FILTER (WHERE events>10000) AS users_above_10000_events,
            count(*) FILTER (WHERE t0 < TIMESTAMP '2019-10-08') AS first_week_first_seen_users
            FROM customers""")[0]
        output["cross_month_users"] = records(con, """SELECT months_observed, count(*) AS users FROM
            (SELECT user_key, count(DISTINCT source_month) AS months_observed FROM events
             WHERE user_key IS NOT NULL GROUP BY user_key) GROUP BY 1 ORDER BY 1""")
        output["eligibility"] = records(con, """SELECT count(*) AS users,
            count(*) FILTER (WHERE eligible) AS eligible_users,
            count(*) FILTER (WHERE NOT eligible) AS ineligible_users,
            count(*) FILTER (WHERE eligible AND positive) AS eligible_positive_users,
            count(*) FILTER (WHERE NOT eligible AND positive) AS censored_observed_positive_users,
            avg(CAST(positive AS DOUBLE)) FILTER (WHERE eligible) AS eligible_purchase_rate,
            max(t0) FILTER (WHERE eligible) AS latest_eligible_first_seen
            FROM cohort""")[0]
        # A 30-minute inter-event gap is a diagnostic heuristic, not proof of an outage.
        # Measure the cost of excluding every intersecting 37-day history conservatively.
        con.execute("""CREATE OR REPLACE TABLE suspected_gaps AS SELECT previous_event + INTERVAL 1 SECOND AS gap_start,
            event_ts AS gap_end FROM (SELECT event_ts, lag(event_ts) OVER (ORDER BY event_ts) AS previous_event
                FROM (SELECT DISTINCT event_ts FROM events WHERE event_ts IS NOT NULL))
            WHERE date_diff('second',previous_event,event_ts) >= 1800""")
        con.execute("""CREATE OR REPLACE VIEW conservative_cohort AS SELECT * FROM cohort c WHERE eligible
            AND NOT EXISTS (SELECT 1 FROM suspected_gaps g WHERE c.t0 < g.gap_end AND c.outcome_end > g.gap_start)""")
        output["gap_sensitivity"] = {
            "threshold_seconds_assumed": 1800,
            "suspected_gaps": records(con, "SELECT * FROM suspected_gaps ORDER BY gap_start"),
            **records(con, """SELECT count(*) AS eligible_users, count(*) FILTER (WHERE positive) AS positive_users,
                avg(CAST(positive AS DOUBLE)) AS purchase_rate FROM conservative_cohort""")[0]}
        output["first_week_purchase_subgroups"] = records(con, """WITH early_buyers AS
            (SELECT DISTINCT e.user_key FROM events e JOIN customers c USING(user_key)
             WHERE e.event_type='purchase' AND e.event_ts < c.prediction_time)
            SELECT b.user_key IS NOT NULL AS purchased_in_first_week, count(*) AS eligible_users,
                count(*) FILTER (WHERE c.positive) AS positive_users, avg(CAST(c.positive AS DOUBLE)) AS purchase_rate
            FROM cohort c LEFT JOIN early_buyers b USING(user_key) WHERE c.eligible GROUP BY 1 ORDER BY 1""")
        output["cohorts_by_prediction_month"] = records(con, """SELECT strftime(prediction_time,'%Y-%m') AS prediction_month,
            count(*) AS users, count(*) FILTER (WHERE eligible) AS eligible_users,
            count(*) FILTER (WHERE eligible AND positive) AS positive_users,
            avg(CAST(positive AS DOUBLE)) FILTER (WHERE eligible) AS purchase_rate
            FROM cohort GROUP BY 1 ORDER BY 1""")
        output["splits"] = []
        output["conservative_splits"] = []
        for name, start, end in SPLITS:
            row = records(con, f"""SELECT count(*) AS users, count(*) FILTER (WHERE positive) AS positive_users,
                avg(CAST(positive AS DOUBLE)) AS purchase_rate, max(outcome_end) AS latest_outcome_end
                FROM cohort WHERE eligible AND prediction_time >= TIMESTAMP {literal(start)}
                  AND prediction_time < TIMESTAMP {literal(end)}""")[0]
            output["splits"].append({"split": name, "prediction_start": start, "prediction_end_exclusive": end, **row})
            conservative = records(con, f"""SELECT count(*) AS users, count(*) FILTER (WHERE positive) AS positive_users,
                avg(CAST(positive AS DOUBLE)) AS purchase_rate FROM conservative_cohort
                WHERE prediction_time >= TIMESTAMP {literal(start)} AND prediction_time < TIMESTAMP {literal(end)}""")[0]
            output["conservative_splits"].append({"split": name, **conservative})
        output["earlier_conservative_splits"] = []
        for name, start, end in EARLIER_SPLITS:
            row = records(con, f"""SELECT count(*) AS users, count(*) FILTER (WHERE positive) AS positive_users,
                avg(CAST(positive AS DOUBLE)) AS purchase_rate, max(outcome_end) AS latest_outcome_end
                FROM conservative_cohort WHERE prediction_time >= TIMESTAMP {literal(start)}
                  AND prediction_time < TIMESTAMP {literal(end)}""")[0]
            output["earlier_conservative_splits"].append({"split": name, "prediction_start": start,
                                                        "prediction_end_exclusive": end, **row})
        output["totals"]["purchase_event_rate"] = output["totals"]["purchase_events"] / output["totals"]["events"]
        output["elapsed_seconds"] = round(time.monotonic() - started, 2)
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        output["peak_process_rss_bytes"] = rss if sys.platform == "darwin" else rss * 1024
        output["storage_bytes"] = {"csv": sum(f["csv_bytes"] for f in output["files"]),
                                   "parquet": sum(f["parquet_bytes"] for f in output["files"])}
        save_json(root / "docs/phase1/audit_summary.json", output)
        print(json.dumps({"totals": output["totals"], "eligibility": output["eligibility"], "splits": output["splits"]}, indent=2, default=str), flush=True)
        return output
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--memory", choices=["256MB", "512MB", "1GB", "2GB"], default="1GB")
    parser.add_argument("--coverage-end", default="2020-03-01 00:00:00",
                        help="Assumed exclusive logging end in UTC; independently inspect the coverage diagnostics")
    args = parser.parse_args()
    run_audit(args.root, coverage_end=args.coverage_end, memory=args.memory)


if __name__ == "__main__":
    main()
