"""Phase 10B1 past-only candidate retrieval and development coverage evaluation.

History/catalog/graph are built and fingerprinted before labels are read.
Only October/November histories and November/December development labels are
allowed. Candidate generation has no outcome argument. No final-test IO path.
"""
from collections import defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import resource
import shutil
import time

import duckdb

from .ranking_audit import digest, rows, WINDOWS


METHODS = ('global', 'personal_backfilled', 'item_backfilled', 'hybrid',
           'personal_global', 'item_global', 'personal_item')


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def configure(con, config, spill):
    con.execute(f"SET memory_limit={quote(config['memory_limit'])}")
    con.execute('SET threads=1')
    con.execute(f"SET max_temp_directory_size={quote(config['spill_cap'])}")
    con.execute(f"SET temp_directory={quote(spill)}")


def development_window(split):
    if split not in ('train', 'validation'):
        raise ValueError('Phase 10B1 permits train/validation only; final test is blocked')
    return next(w for w in WINDOWS if w[0] == split)


def validate_config(config):
    limits = {'graph_history_cap': 50, 'seed_cap': 10, 'neighbors_per_item': 50,
              'customer_batch_size': 1000, 'minimum_item_users': 1000, 'minimum_pair_users': 1000}
    for name, upper in limits.items():
        if type(config.get(name)) is not int or not 1 <= config[name] <= upper:
            raise ValueError(f'{name} must be an integer in 1..{upper}')
    budgets = config.get('budgets')
    if (not isinstance(budgets, list) or not budgets or
        any(type(b) is not int or not 1 <= b <= 200 for b in budgets) or
        budgets != sorted(set(budgets))):
        raise ValueError('budgets must be sorted unique integers in 1..200')
    if config['seed_cap'] > config['graph_history_cap']:
        raise ValueError('seed cap exceeds graph history cap')
    if config['positive_event_types'] != ['view', 'cart', 'purchase']:
        raise ValueError('positive event semantics are frozen')
    if config['personal_event_types'] != ['view', 'cart', 'purchase', 'remove_from_cart']:
        raise ValueError('personal event semantics are frozen')
    if config['hybrid_order'] != ['personal', 'item', 'global']:
        raise ValueError('hybrid order is frozen')


def build_history(con, split, config):
    """Expects history_events view; filters again so future rows cannot enter."""
    _, start, cutoff, _ = development_window(split)
    validate_config(config)
    cap, maximum = config['graph_history_cap'], max(config['budgets'])
    con.execute(f"""CREATE OR REPLACE TABLE hp AS SELECT user_key,product_key,
        max(event_ts) last_event,
        max(event_ts) FILTER(WHERE event_type IN ('view','cart','purchase')) last_positive,
        bool_or(event_type='purchase') bought
        FROM history_events WHERE event_ts>={quote(start)}::TIMESTAMP
        AND event_ts<{quote(cutoff)}::TIMESTAMP AND user_key>0 AND product_key>0
        AND event_type IN ('view','cart','purchase','remove_from_cart') GROUP BY 1,2""")
    con.execute('CREATE OR REPLACE TABLE eligible AS SELECT DISTINCT user_key FROM hp')
    con.execute(f"""CREATE OR REPLACE TABLE personal AS SELECT * FROM
        (SELECT user_key,product_key,row_number() OVER(PARTITION BY user_key
        ORDER BY last_event DESC,product_key) r FROM hp) WHERE r<={maximum}""")
    con.execute(f"""CREATE OR REPLACE TABLE popularity AS SELECT product_key,buyers,
        row_number() OVER(ORDER BY buyers DESC,product_key) r FROM
        (SELECT product_key,count(*) buyers FROM hp WHERE bought GROUP BY 1)
        QUALIFY r<={maximum}""")
    con.execute(f"""CREATE OR REPLACE TABLE capped AS SELECT * FROM
        (SELECT user_key,product_key,row_number() OVER(PARTITION BY user_key
        ORDER BY last_positive DESC,product_key) r FROM hp WHERE last_positive IS NOT NULL)
        WHERE r<={cap}""")
    con.execute(f"""CREATE OR REPLACE TABLE degree AS SELECT product_key,count(*) users
        FROM capped GROUP BY 1 HAVING count(*)>={config['minimum_item_users']}""")
    con.execute('CREATE OR REPLACE TABLE graph_inputs AS SELECT c.* FROM capped c JOIN degree USING(product_key)')
    # One row per user/product above: each user contributes at most once per pair.
    con.execute(f"""CREATE OR REPLACE TABLE pair_support AS SELECT a.product_key a,b.product_key b,
        count(*) support FROM graph_inputs a JOIN graph_inputs b
        ON a.user_key=b.user_key AND a.product_key<b.product_key GROUP BY 1,2
        HAVING count(*)>={config['minimum_pair_users']}""")
    con.execute(f"""CREATE OR REPLACE TABLE neighbors AS WITH directed AS
        (SELECT a,b,support FROM pair_support UNION ALL SELECT b,a,support FROM pair_support),
        scored AS (SELECT a,b,support,support/sqrt(da.users::DOUBLE*db.users) score
        FROM directed JOIN degree da ON a=da.product_key JOIN degree db ON b=db.product_key)
        SELECT *,row_number() OVER(PARTITION BY a ORDER BY score DESC,support DESC,b) r
        FROM scored QUALIFY r<={config['neighbors_per_item']}""")
    # Seeds use the same capped recency order; a graph-less seed contributes no neighbors.
    con.execute(f'CREATE OR REPLACE TABLE seeds AS SELECT * FROM capped WHERE r<={config["seed_cap"]}')
    stats = rows(con, """SELECT (SELECT count(*) FROM eligible) eligible_users,
        (SELECT count(*) FROM hp) historical_pairs,(SELECT count(*) FROM capped) capped_pairs,
        (SELECT count(*) FROM degree) graph_products,(SELECT count(*) FROM pair_support) supported_pairs,
        (SELECT count(*) FROM neighbors) directed_neighbors,
        (SELECT max(r) FROM capped) largest_graph_history,
        (SELECT max(r) FROM neighbors) largest_neighbor_list""")[0]
    stats['pair_emissions'] = rows(con, """SELECT sum(n*(n-1)/2) n FROM
        (SELECT user_key,count(*) n FROM graph_inputs GROUP BY 1)""")[0]['n']
    return stats


def unique(sequence):
    return list(dict.fromkeys(sequence))


def priority_with_fallback(primary, global_products, maximum):
    return unique([*primary, *global_products])[:maximum]


def interleave(sources, maximum):
    """Round-robin source ranks; first occurrence wins, no repeated products."""
    answer, seen = [], set()
    for rank in range(max(map(len, sources), default=0)):
        for source in sources:
            if rank < len(source) and source[rank] not in seen:
                product = source[rank]
                seen.add(product); answer.append(product)
                if len(answer) == maximum:
                    return answer
    return answer


def retrieve(personal, item, global_products, maximum):
    """Pure function: receives only past-only ordered lists, never labels.

    Both personalized methods and the hybrid use the same popularity fallback.
    Unknown customers supply empty personal/item lists and get popularity.
    """
    if type(maximum) is not int or not 1 <= maximum <= 200:
        raise ValueError('candidate budget must be in 1..200')
    personal, item, global_products = map(unique, (personal, item, global_products))
    return {'global': global_products[:maximum],
        'personal_backfilled': priority_with_fallback(personal, global_products, maximum),
        'item_backfilled': priority_with_fallback(item, global_products, maximum),
        'hybrid': interleave([personal, item, global_products], maximum),
        'personal_global': interleave([personal, global_products], maximum),
        'item_global': interleave([item, global_products], maximum),
        'personal_item': priority_with_fallback(interleave([personal, item], maximum), global_products, maximum)}


def batch_sources(con, lower, upper, maximum):
    """At most 1,000 customers × 10 seeds × 50 neighbors before aggregation."""
    personal, item = defaultdict(list), defaultdict(list)
    for user, product in con.execute('SELECT user_key,product_key FROM personal WHERE user_key>=? AND user_key<=? ORDER BY user_key,r', [lower, upper]).fetchall():
        personal[user].append(product)
    candidates = con.execute(f"""WITH scored AS
        (SELECT s.user_key,n.b product_key,max(n.score) score,max(n.support) support
        FROM seeds s JOIN neighbors n ON s.product_key=n.a
        WHERE s.user_key>=? AND s.user_key<=? GROUP BY 1,2)
        SELECT user_key,product_key FROM scored
        QUALIFY row_number() OVER(PARTITION BY user_key ORDER BY score DESC,support DESC,product_key)<={maximum}
        ORDER BY user_key,score DESC,support DESC,product_key""", [lower, upper]).fetchall()
    for user, product in candidates:
        item[user].append(product)
    return personal, item


def load_labels(con, label_path, split):
    """Separate label reader, called only after history artifacts are frozen."""
    _, _, cutoff, end = development_window(split)
    labels = defaultdict(set)
    for user, product in con.execute(f"""SELECT DISTINCT e.user_key,e.product_key FROM
        read_parquet({quote(label_path)}) e JOIN eligible u USING(user_key)
        WHERE e.event_type='purchase' AND e.event_ts>={quote(cutoff)}::TIMESTAMP
        AND e.event_ts<{quote(end)}::TIMESTAMP""").fetchall():
        labels[user].add(product)
    return labels


def empty_metrics():
    return {'hits': 0, 'user_recall_sum': 0., 'users_with_hits': 0,
            'users_with_candidates': 0, 'purchasing_users_with_candidates': 0,
            'candidate_count_histogram': defaultdict(int)}


def update_metrics(stats, candidates, relevant):
    if len(candidates) != len(set(candidates)):
        raise ValueError('duplicate candidates')
    stats['candidate_count_histogram'][len(candidates)] += 1
    stats['users_with_candidates'] += bool(candidates)
    if relevant:
        hits = len(set(candidates) & relevant)
        stats['hits'] += hits
        stats['user_recall_sum'] += hits / len(relevant)
        stats['users_with_hits'] += hits > 0
        stats['purchasing_users_with_candidates'] += bool(candidates)


def finish_metrics(stats, users, labels):
    pairs, buyers = sum(map(len, labels.values())), len(labels)
    histogram = stats['candidate_count_histogram']
    # Conventional median (mean of two middle observations when even).
    positions, middle, seen = ((users-1)//2, users//2), [], 0
    for count, frequency in sorted(histogram.items()):
        middle.extend(count for p in positions if seen <= p < seen+frequency)
        seen += frequency
    return {'relevant_pairs': pairs, 'purchasing_users': buyers, 'eligible_users': users,
        'hits': stats['hits'], 'pair_recall': stats['hits']/pairs if pairs else None,
        'mean_user_recall': stats['user_recall_sum']/buyers if buyers else None,
        'users_with_candidates': stats['users_with_candidates'],
        'eligible_user_coverage': stats['users_with_candidates']/users if users else None,
        'purchasing_user_coverage': stats['purchasing_users_with_candidates']/buyers if buyers else None,
        'purchasing_users_with_a_hit': stats['users_with_hits'],
        'purchasing_users_hit_rate': stats['users_with_hits']/buyers if buyers else None,
        'mean_candidates': sum(k*v for k,v in histogram.items())/users if users else None,
        'median_candidates': sum(middle)/2 if users else None,
        'min_candidates': min(histogram, default=0), 'max_candidates': max(histogram, default=0),
        'candidate_count_histogram': dict(sorted(histogram.items()))}


def evaluate(con, config, labels):
    maximum = max(config['budgets'])
    users = [r[0] for r in con.execute('SELECT user_key FROM eligible ORDER BY user_key').fetchall()]
    global_products = [r[0] for r in con.execute('SELECT product_key FROM popularity ORDER BY r').fetchall()]
    if len(global_products) < maximum:
        raise ValueError('Insufficient purchased catalog for exact-budget real-data comparison')
    metrics = {(method,b): empty_metrics() for method in METHODS for b in config['budgets']}
    natural = {(method,b): empty_metrics() for method in ('personal','item') for b in config['budgets']}
    # At matched budgets, compare complementary hits and losses against global.
    complements = {b: {'hybrid_hits_absent_from_global': 0, 'global_hits_absent_from_hybrid': 0} for b in config['budgets']}
    generation_seconds, metric_seconds = 0., 0.
    batch = config['customer_batch_size']
    for offset in range(0, len(users), batch):
        started = time.perf_counter()
        subset = users[offset:offset+batch]
        personal, item = batch_sources(con, subset[0], subset[-1], maximum)
        generation_seconds += time.perf_counter()-started
        for user in subset:
            started = time.perf_counter()
            generated = retrieve(personal[user], item[user], global_products, maximum)
            generation_seconds += time.perf_counter()-started
            started = time.perf_counter()
            relevant = labels.get(user, set())
            for b in config['budgets']:
                for method in METHODS:
                    candidate = generated[method][:b]
                    if len(candidate) != b: raise ValueError('Exact budget not met')
                    update_metrics(metrics[method,b], candidate, relevant)
                for method, source in [('personal', personal[user]), ('item', item[user])]:
                    update_metrics(natural[method,b], source[:b], relevant)
                if relevant:
                    hybrid_hits = set(generated['hybrid'][:b]) & relevant
                    global_hits = set(generated['global'][:b]) & relevant
                    complements[b]['hybrid_hits_absent_from_global'] += len(hybrid_hits-global_hits)
                    complements[b]['global_hits_absent_from_hybrid'] += len(global_hits-hybrid_hits)
            metric_seconds += time.perf_counter()-started
        if offset % (batch*50) == 0:
            print(f'  {min(offset+batch,len(users)):,}/{len(users):,} historical users', flush=True)
    return {'matched_budget': {m: {str(b): finish_metrics(metrics[m,b],len(users),labels)
        for b in config['budgets']} for m in METHODS},
        'without_backfill': {m: {str(b): finish_metrics(natural[m,b],len(users),labels)
        for b in config['budgets']} for m in ('personal','item')},
        'complementary_hits_at_equal_budget': complements,
        'candidate_generation_seconds': generation_seconds, 'metric_seconds': metric_seconds}


def main():
    root = Path.cwd()
    config_path = root/'docs/ranking/phase10b1_config.json'
    config = json.loads(config_path.read_text()); validate_config(config)
    if shutil.disk_usage(root).free < 20*1024**3:
        raise RuntimeError('Require 20 GiB free for OS reserve and bounded spill')
    source_summary = json.loads((root/'docs/phase2/summary.json').read_text())
    expected = {m['month']: m['sha256'] for m in source_summary['cleaned_months']}
    work = root/'data/ranking/phase10b1'; work.mkdir(parents=True, exist_ok=True)
    code_hash = digest(Path(__file__))
    result = {'configuration': config, 'source_code_sha256': code_hash,
        'config_sha256': digest(config_path), 'final_test_accessed': False, 'snapshots': {}}
    inputs = {}
    # There is no January partition or final-test snapshot in this IO allowlist.
    for split, history_month, label_month in [('train','2019-Oct','2019-Nov'), ('validation','2019-Nov','2019-Dec')]:
        started = time.perf_counter()
        history_path = root/f'data/features/phase2/cleaned/{history_month}.parquet'
        label_path = root/f'data/features/phase2/cleaned/{label_month}.parquet'
        for path, month in [(history_path,history_month),(label_path,label_month)]:
            if digest(path) != expected[month]: raise ValueError('Input fingerprint mismatch')
            inputs[str(path.relative_to(root))] = expected[month]
        db = work/f'{split}.duckdb'
        con = duckdb.connect(str(db))
        try:
            configure(con, config, work/(split+'_spill'))
            con.execute(f'CREATE OR REPLACE VIEW history_events AS SELECT * FROM read_parquet({quote(history_path)})')
            print(f'{split}: preparing history-only graph and retrieval sources', flush=True)
            build_started = time.perf_counter()
            stats = build_history(con, split, config)
            build_seconds = time.perf_counter()-build_started
            con.execute('CHECKPOINT')
        finally:
            con.close()
        freeze = {'history_database_sha256': digest(db), 'source_code_sha256': code_hash,
            'config_sha256': result['config_sha256'], 'history_sha256': expected[history_month],
            'label_accessed': False,
            'meaning': 'Deterministic candidate membership is frozen by closed history-only DB, code and configuration; candidates are generated lazily in batches, without outcome inputs.'}
        freeze_path = work/f'{split}_retrieval_freeze.json'
        freeze_path.write_text(json.dumps(freeze, indent=2)+'\n')
        print(f'{split}: sources frozen; now reading development labels', flush=True)
        con = duckdb.connect(str(db), read_only=True)
        try:
            configure(con, config, work/(split+'_spill'))
            labels = load_labels(con, label_path, split)
            metrics = evaluate(con, config, labels)
        finally:
            con.close()
        if digest(db) != freeze['history_database_sha256']:
            raise ValueError('Frozen retrieval artifacts changed during evaluation')
        result['snapshots'][split] = {'window': development_window(split), 'graph': stats,
            'freeze': freeze, 'history_build_seconds': build_seconds,
            **metrics, 'elapsed_seconds': time.perf_counter()-started,
            'process_peak_rss': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'rss_units': 'bytes on macOS; KiB on Linux', 'database_bytes': db.stat().st_size}
    for path, sha in inputs.items():
        if digest(root/path) != sha: raise ValueError('Source changed during retrieval')
    result['input_sha256'] = inputs
    result['duckdb_version'] = duckdb.__version__
    result['total_peak_process_rss'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    output = root/'docs/ranking/phase10b1_candidate_summary.json'
    output.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(f'Aggregate output: {output.relative_to(root)}', flush=True)


if __name__ == '__main__':
    main()
