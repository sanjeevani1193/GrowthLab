"""Phase 10A aggregate data audit only: no fitted models or final-test labels.

Reuses Phase 2 exact-row-deduplicated Parquet. Customer-level intermediate
tables stay in the ignored, disk-backed DuckDB database. Only aggregates leave it.
"""
import hashlib
import json
from pathlib import Path
import resource
import shutil
import time

import duckdb


WINDOWS = (
    ('train', '2019-10-01', '2019-11-01', '2019-11-15'),
    ('validation', '2019-11-01', '2019-12-01', '2019-12-15'),
    ('final_test', '2019-12-01', '2020-01-01', '2020-01-15'),
)
GLOBAL_CAPS = (20, 50, 100, 200, 500)
PERSONAL_CAP = 50


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def rows(con, sql):
    cursor = con.execute(sql)
    return [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]


def global_audit(con):
    """All-period descriptive counts; these do not select/tune ranking rules."""
    result = {'totals': rows(con, """SELECT count(*) events,
        count(DISTINCT user_key) customers, count(DISTINCT product_key) products,
        min(event_ts) first_event, max(event_ts) last_event FROM events""")[0],
        'event_types': rows(con, 'SELECT event_type,count(*) events FROM events GROUP BY 1 ORDER BY 1')}
    con.execute("""CREATE OR REPLACE TABLE pairs AS SELECT user_key,product_key,
        count(*) events, count(*) FILTER(WHERE event_type='purchase') purchases,
        count(DISTINCT event_ts) FILTER(WHERE event_type='purchase') purchase_times,
        count(DISTINCT CAST(event_ts AS DATE)) FILTER(WHERE event_type='purchase') purchase_days
        FROM events GROUP BY 1,2""")
    result['pairs'] = rows(con, """SELECT count(*) distinct_customer_product_pairs,
        count(*) FILTER(WHERE events>=2) repeated_pairs,
        count(DISTINCT user_key) FILTER(WHERE events>=2) customers_repeating_product,
        count(*) FILTER(WHERE purchases>0) purchased_pairs,
        count(*) FILTER(WHERE purchase_times>=2) pairs_bought_at_multiple_times,
        count(DISTINCT user_key) FILTER(WHERE purchase_times>=2) customers_rebuying_product,
        count(DISTINCT user_key) FILTER(WHERE purchase_days>=2) customers_rebuying_product_on_multiple_dates
        FROM pairs""")[0]
    con.execute("""CREATE OR REPLACE TABLE users AS SELECT user_key,sum(events) events,
        count(*) products,sum(purchases) purchases FROM pairs GROUP BY 1""")
    result['users'] = rows(con, """SELECT count(*) customers,
        count(*) FILTER(WHERE events=1) single_event_customers,
        count(*) FILTER(WHERE products>=2) customers_with_multiple_products,
        count(*) FILTER(WHERE purchases>0) purchasers,
        count(*) FILTER(WHERE purchases>=2) customers_with_multiple_purchase_rows,
        quantile_disc(events,[0.5,0.9,0.95,0.99]) event_quantiles,
        quantile_disc(products,[0.5,0.9,0.95,0.99]) product_quantiles,
        max(events) max_events,max(products) max_products FROM users""")[0]
    result['purchase_occasions'] = rows(con, """WITH u AS (SELECT user_key,
        count(DISTINCT event_ts) occasions, count(DISTINCT CAST(event_ts AS DATE)) AS active_dates
        FROM events WHERE event_type='purchase' GROUP BY 1)
        SELECT count(*) FILTER(WHERE occasions>=2) customers_with_multiple_purchase_times,
        count(*) FILTER(WHERE active_dates>=2) customers_with_multiple_purchase_dates FROM u""")[0]
    con.execute("""CREATE OR REPLACE TABLE products AS SELECT product_key,sum(events) events,
        count(*) customers,sum(purchases) purchases,
        count(*) FILTER(WHERE purchases>0) buyers FROM pairs GROUP BY 1""")
    result['products'] = rows(con, """SELECT count(*) products,
        count(*) FILTER(WHERE buyers>0) products_with_purchases,
        count(*) FILTER(WHERE buyers>=5) products_with_at_least_5_buyers,
        count(*) FILTER(WHERE buyers>=20) products_with_at_least_20_buyers,
        count(*) FILTER(WHERE buyers=0) products_without_purchases,
        quantile_disc(buyers,[0.5,0.9,0.95,0.99]) buyer_quantiles,
        max(buyers) max_buyers FROM products""")[0]
    result['popularity'] = rows(con, """WITH p AS (SELECT *,row_number() OVER
        (ORDER BY buyers DESC,product_key) r FROM products), totals AS
        (SELECT count(*) n,sum(buyers) buyers,sum(purchases) purchases FROM products)
        SELECT cutoff,count(*) products,sum(p.buyers) distinct_buyer_product_pairs,
        sum(p.purchases) purchase_rows,sum(p.buyers)::DOUBLE/any_value(totals.buyers) pair_share,
        sum(p.purchases)::DOUBLE/any_value(totals.purchases) purchase_row_share
        FROM p CROSS JOIN totals CROSS JOIN (VALUES (100),(500),
        (CAST(ceil((SELECT count(*) FROM products)*.01) AS INTEGER)),
        (CAST(ceil((SELECT count(*) FROM products)*.10) AS INTEGER))) caps(cutoff)
        WHERE r<=cutoff GROUP BY cutoff ORDER BY cutoff""")
    result['metadata'] = rows(con, """SELECT count(*) events,
        count(*) FILTER(WHERE category_key IS NULL) missing_category_id,
        count(*) FILTER(WHERE category_code IS NULL OR category_code='') missing_category_code,
        count(*) FILTER(WHERE brand IS NULL OR brand='') missing_brand,
        count(*) FILTER(WHERE price_value<0) negative_prices,
        count(*) FILTER(WHERE price_value=0) zero_prices FROM events""")[0]
    result['catalog_changes'] = rows(con, """WITH p AS (SELECT product_key,
        count(DISTINCT category_key) categories,count(DISTINCT brand) brands FROM events GROUP BY 1)
        SELECT count(*) FILTER(WHERE categories>1) products_with_multiple_category_ids,
        count(*) FILTER(WHERE brands>1) products_with_multiple_brands FROM p""")[0]
    n = result['totals']
    result['observed_pair_density'] = result['pairs']['distinct_customer_product_pairs'] / (n['customers'] * n['products'])
    return result


def snapshot_audit(con, split, start, cutoff, end):
    """Only past events build history. Final-test function never queries labels."""
    # Dates are from the internal constant schedule, not external SQL fragments.
    con.execute(f"""CREATE OR REPLACE TABLE history AS SELECT * FROM events
        WHERE event_ts>=TIMESTAMP '{start}' AND event_ts<TIMESTAMP '{cutoff}'""")
    con.execute("""CREATE OR REPLACE TABLE hp AS SELECT user_key,product_key,
        max(event_ts) last_event, count(*) events,
        count(*) FILTER(WHERE event_type='purchase') purchases FROM history GROUP BY 1,2""")
    con.execute("""CREATE OR REPLACE TABLE hu AS SELECT user_key,count(*) products,
        sum(events) events FROM hp GROUP BY 1""")
    result = {'split': split, 'history_start': start, 'prediction_time': cutoff, 'outcome_end': end,
        'history': rows(con, """SELECT count(*) customers,
        count(*) FILTER(WHERE products>=2) customers_with_2_products,
        count(*) FILTER(WHERE events>=5) customers_with_5_events,
        quantile_disc(products,[.5,.9,.95,.99]) unique_product_quantiles,
        max(products) max_products FROM hu""")[0]}
    result['catalog'] = rows(con, """WITH p AS (SELECT product_key,
        count(*) customers,count(*) FILTER(WHERE purchases>0) buyers FROM hp GROUP BY 1)
        SELECT count(*) observed_products,count(*) FILTER(WHERE buyers>0) purchased_products,
        count(*) FILTER(WHERE buyers>=5) products_with_5_buyers,
        count(*) FILTER(WHERE buyers>=20) products_with_20_buyers FROM p""")[0]
    result['active_days'] = rows(con, """WITH u AS (SELECT user_key,
        count(DISTINCT CAST(event_ts AS DATE)) AS active_dates FROM history GROUP BY 1)
        SELECT count(*) FILTER(WHERE active_dates>=2) customers_with_2_active_dates FROM u""")[0]
    result['cooccurrence_work'] = rows(con, """SELECT sum(products*(products-1)/2) uncapped_user_pair_emissions,
        sum(least(products,50)*(least(products,50)-1)/2) capped_50_user_pair_emissions FROM hu""")[0]
    if split == 'final_test':
        result['outcomes_accessed'] = False
        return result
    con.execute(f"""CREATE OR REPLACE TABLE relevant AS SELECT DISTINCT user_key,product_key
        FROM events WHERE event_type='purchase' AND event_ts>=TIMESTAMP '{cutoff}'
        AND event_ts<TIMESTAMP '{end}'""")
    result['future_population'] = rows(con, """SELECT count(*) purchased_pairs,
        count(DISTINCT r.user_key) purchasers,
        count(*) FILTER(WHERE u.user_key IS NULL) pairs_from_customers_without_window_history,
        count(DISTINCT r.user_key) FILTER(WHERE u.user_key IS NULL) purchasers_without_window_history,
        count(*) FILTER(WHERE c.product_key IS NULL) pairs_for_products_absent_from_window_history
        FROM relevant r LEFT JOIN hu u USING(user_key)
        LEFT JOIN (SELECT DISTINCT product_key FROM hp) c USING(product_key)""")[0]
    con.execute("""CREATE OR REPLACE TABLE labels AS SELECT r.* FROM relevant r JOIN hu USING(user_key)""")
    result['warm_outcomes'] = rows(con, """SELECT count(*) purchased_pairs,count(DISTINCT l.user_key) purchasers,
        count(*) FILTER(WHERE h.product_key IS NOT NULL) previously_interacted_pairs,
        count(*) FILTER(WHERE h.purchases>0) previously_purchased_pairs,
        count(*) FILTER(WHERE c.product_key IS NULL) new_product_pairs FROM labels l
        LEFT JOIN hp h USING(user_key,product_key)
        LEFT JOIN (SELECT DISTINCT product_key FROM hp) c USING(product_key)""")[0]
    result['outcomes_accessed'] = True
    if split == 'validation':
        result['candidate_diagnostics'] = candidate_diagnostics(con)
    return result


def candidate_diagnostics(con):
    """Past-only ranks, then label-only coverage checks; no final rankings exported."""
    con.execute("""CREATE OR REPLACE TABLE popularity AS SELECT product_key,
        row_number() OVER(ORDER BY buyers DESC,product_key) r FROM
        (SELECT product_key,count(*) buyers FROM hp WHERE purchases>0 GROUP BY 1)""")
    con.execute("""CREATE OR REPLACE TABLE recent AS SELECT user_key,product_key,
        row_number() OVER(PARTITION BY user_key ORDER BY last_event DESC,product_key) r FROM hp""")
    result = []
    for cap in GLOBAL_CAPS:
        actual_global = con.execute('SELECT count(*) FROM popularity WHERE r<=?', [cap]).fetchone()[0]
        metrics = rows(con, f"""WITH hits AS (SELECT l.*, p.r global_rank,h.r personal_rank
            FROM labels l LEFT JOIN popularity p USING(product_key)
            LEFT JOIN recent h USING(user_key,product_key)), u AS
            (SELECT user_key,count(*) relevant,
            count(*) FILTER(WHERE global_rank<={cap}) global_hits,
            count(*) FILTER(WHERE personal_rank<={PERSONAL_CAP}) personal_hits,
            count(*) FILTER(WHERE global_rank<={cap} OR personal_rank<={PERSONAL_CAP}) union_hits
            FROM hits GROUP BY 1)
            SELECT sum(relevant) relevant_pairs,count(*) purchasing_customers,
            sum(global_hits) global_hits,sum(personal_hits) personal_hits,sum(union_hits) union_hits,
            avg(global_hits::DOUBLE/relevant) global_macro_recall,
            avg(personal_hits::DOUBLE/relevant) personal_macro_recall,
            avg(union_hits::DOUBLE/relevant) union_macro_recall FROM u""")[0]
        sizes = rows(con, f"""WITH u AS (SELECT h.user_key,least(h.products,{PERSONAL_CAP})+
            {actual_global}-(SELECT count(*) FROM recent r JOIN popularity p USING(product_key)
            WHERE r.user_key=h.user_key AND r.r<={PERSONAL_CAP} AND p.r<={cap}) n FROM hu h)
            SELECT min(n) min_candidates,avg(n) mean_candidates,max(n) max_candidates,
            quantile_disc(n,[.5,.9,.95,.99]) candidate_quantiles,sum(n) candidate_rows FROM u""")[0]
        result.append({'global_cap': cap, 'actual_global_products': actual_global,
            'personal_cap': PERSONAL_CAP, **metrics, **sizes})
    return result


def main():
    root = Path.cwd()
    work = root / 'data/ranking/phase10a'
    if shutil.disk_usage(root).free < 20 * 1024**3:
        raise RuntimeError('Require 20 GiB free for OS reserve and bounded spill')
    summary = json.loads((root/'docs/phase2/summary.json').read_text())
    files = {root/'data/features/phase2/cleaned'/f"{m['month']}.parquet": m['sha256']
             for m in summary['cleaned_months']}
    for p, expected in files.items():
        if digest(p) != expected: raise ValueError(f'Cleaned input fingerprint mismatch: {p.name}')
    work.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    con = duckdb.connect(str(work/'audit.duckdb'))
    try:
        con.execute("SET memory_limit='768MB'")
        con.execute('SET threads=1')
        con.execute("SET max_temp_directory_size='4GB'")
        con.execute(f"SET temp_directory='{work/'spill'}'")
        paths = ','.join("'"+str(p).replace("'", "''")+"'" for p in files)
        con.execute(f'CREATE OR REPLACE VIEW events AS SELECT * FROM read_parquet([{paths}])')
        result = {'scope': 'Descriptive audit; development candidate coverage only; no final-test evaluation',
                  'source_sha256': {str(p.relative_to(root)): h for p,h in files.items()}}
        print('Auditing global interactions', flush=True)
        result['global'] = global_audit(con)
        result['snapshots'] = []
        for window in WINDOWS:
            print(f'Auditing {window[0]} (final outcomes blocked)', flush=True)
            result['snapshots'].append(snapshot_audit(con, *window))
        result['resources'] = {'memory_limit': '768MB', 'threads': 1, 'spill_cap': '4GB',
            'elapsed_seconds': time.perf_counter()-started,
            'process_maxrss': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'maxrss_units': 'bytes on macOS; KiB on Linux', 'duckdb_version': duckdb.__version__}
    finally:
        con.close()
    for p, expected in files.items():
        if digest(p) != expected: raise ValueError('Input changed during audit')
    result['audit_source_sha256'] = digest(Path(__file__))
    dest = root/'docs/ranking/phase10a_audit_summary.json'
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, indent=2, default=str, allow_nan=False)+'\n')
    print(f'Aggregate results: {dest.relative_to(root)}', flush=True)


if __name__ == '__main__':
    main()
