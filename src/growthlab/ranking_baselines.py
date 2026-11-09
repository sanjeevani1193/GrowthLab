"""Phase 10B2A: two fixed orderings of identical Phase 10B1 candidate sets.

No training or January outcome reader. The old history-only databases are
verified and opened read-only. Candidate membership is hashed in a full pass
before development labels are read; evaluation must reproduce that hash.
"""
from collections import defaultdict
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import resource
import shutil
import time

import duckdb

from .candidates import configure, development_window, load_labels, priority_with_fallback
from .ranking_audit import digest


METHODS = ('global_popularity', 'personal_recency')
BUDGET = 100
CUTOFFS = (5, 10, 20)


def micros(timestamp):
    delta = timestamp - datetime(1970, 1, 1)
    return (delta.days*86400 + delta.seconds)*1000000 + delta.microseconds


def order_candidates(candidates, history, buyers):
    """No label argument. History maps product to latest UTC-naive event time."""
    if len(candidates) > BUDGET or len(candidates) != len(set(candidates)):
        raise ValueError('Candidates must be distinct, with maximum budget 100')
    popular = sorted(candidates, key=lambda p: (-buyers.get(p, 0), p))
    recent = sorted(candidates, key=lambda p: (
        p not in history, -micros(history[p]) if p in history else 0,
        -buyers.get(p, 0), p))
    return {'global_popularity': popular, 'personal_recency': recent}


def ranking_metrics(ordered, relevant, cutoffs=CUTOFFS):
    """Binary relevance; ideal denominator retains unreachable future products."""
    if len(ordered) != len(set(ordered)):
        raise ValueError('Ranking contains duplicate products')
    if any(type(k) is not int or k <= 0 for k in cutoffs):
        raise ValueError('Cutoffs must be positive integers')
    n = len(relevant)
    result = {}
    for k in cutoffs:
        gains = [int(p in relevant) for p in ordered[:k]]
        hits = sum(gains)
        ideal = sum(1/math.log2(i+2) for i in range(min(k, n)))
        dcg = sum(gain/math.log2(i+2) for i, gain in enumerate(gains))
        result[str(k)] = {'hits': hits, 'recall': hits/n if n else None,
            'ndcg': dcg/ideal if ideal else None}
    return result


def append_hash(hasher, user, candidates):
    hasher.update((str(user)+':'+','.join(map(str, sorted(candidates)))+'\n').encode())


def batches(con, split, batch_size=1000):
    _, start, cutoff, _ = development_window(split)
    start, cutoff = datetime.fromisoformat(start), datetime.fromisoformat(cutoff)
    users = [r[0] for r in con.execute('SELECT user_key FROM eligible ORDER BY user_key').fetchall()]
    global_products = [p for p, in con.execute('SELECT product_key FROM popularity WHERE r<=100 ORDER BY r').fetchall()]
    if len(global_products) < BUDGET:
        raise ValueError('Real-data purchased catalog cannot fill selected budget')
    for offset in range(0, len(users), batch_size):
        subset = users[offset:offset+batch_size]
        histories, personal = defaultdict(dict), defaultdict(list)
        records = con.execute('''SELECT p.user_key,p.product_key,h.last_event FROM personal p
            JOIN hp h USING(user_key,product_key) WHERE p.r<=100
            AND p.user_key>=? AND p.user_key<=? ORDER BY p.user_key,p.r''',
            [subset[0], subset[-1]]).fetchall()
        for user, product, latest in records:
            if not start <= latest < cutoff:
                raise ValueError('Feature timestamp outside frozen past window')
            personal[user].append(product); histories[user][product] = latest
        yield [(u, priority_with_fallback(personal[u], global_products, BUDGET), histories[u]) for u in subset]


def freeze_candidates(con, split, batch_size=1000):
    hasher = hashlib.sha256()
    users = no_history = 0
    for batch in batches(con, split, batch_size):
        for user, candidates, history in batch:
            if len(candidates) != BUDGET or len(set(candidates)) != BUDGET:
                raise ValueError('Selected real-data candidate budget changed')
            append_hash(hasher, user, candidates)
            users += 1; no_history += not bool(history)
    return {'canonical_candidate_sha256': hasher.hexdigest(), 'eligible_users': users,
            'without_personal_history': no_history, 'candidate_budget': BUDGET,
            'labels_read': False}


def empty_group():
    return {'users': 0, 'purchasers': 0, 'relevant_pairs': 0, 'candidate_hits': 0,
        'candidate_macro_sum': 0.,
        'method_sums': {m: {str(k): {'hits': 0, 'recall_sum': 0., 'ndcg_sum': 0.}
            for k in CUTOFFS} for m in METHODS}}


def finish_group(group):
    users, buyers, pairs = group['users'], group['purchasers'], group['relevant_pairs']
    return {'eligible_users': users, 'purchasing_users': buyers, 'relevant_pairs': pairs,
        'eligible_user_coverage': 1. if users else None,
        'full_top20_coverage': 1. if users else None,
        'mean_candidates': BUDGET if users else None,
        'candidate_hits': group['candidate_hits'],
        'candidate_recall_micro': group['candidate_hits']/pairs if pairs else None,
        'candidate_recall_macro': group['candidate_macro_sum']/buyers if buyers else None,
        'methods': {m: {str(k): {
            'hits': group['method_sums'][m][str(k)]['hits'],
            'recall_macro': group['method_sums'][m][str(k)]['recall_sum']/buyers if buyers else None,
            'recall_micro': group['method_sums'][m][str(k)]['hits']/pairs if pairs else None,
            'ndcg_macro': group['method_sums'][m][str(k)]['ndcg_sum']/buyers if buyers else None}
            for k in CUTOFFS} for m in METHODS}}


def evaluate(con, split, labels, frozen, batch_size=1000):
    # Full catalog popularity is essential: personal candidates may lie outside
    # the old top-200 retrieval list. A missing purchase count is really zero.
    buyers = dict(con.execute('SELECT product_key,count(*) FROM hp WHERE bought GROUP BY 1').fetchall())
    groups = {name: empty_group() for name in ('all', 'with_personal_history', 'without_personal_history')}
    hashes = {m: hashlib.sha256() for m in ('candidates', *METHODS)}
    count = 0
    for batch in batches(con, split, batch_size):
        for user, candidates, history in batch:
            ordered = order_candidates(candidates, history, buyers)
            for method in METHODS:
                if len(ordered[method]) != BUDGET or set(ordered[method]) != set(candidates):
                    raise ValueError('Rankers must use identical frozen candidate sets')
                append_hash(hashes[method], user, ordered[method])
            append_hash(hashes['candidates'], user, candidates)
            count += 1
            relevant = labels.get(user, set())
            scores = {m: ranking_metrics(ordered[m], relevant) for m in METHODS} if relevant else {}
            for name in ('all', 'with_personal_history' if history else 'without_personal_history'):
                group = groups[name]; group['users'] += 1
                if relevant:
                    group['purchasers'] += 1; group['relevant_pairs'] += len(relevant)
                    hits = len(set(candidates) & relevant)
                    group['candidate_hits'] += hits; group['candidate_macro_sum'] += hits/len(relevant)
                    for m in METHODS:
                        for k in CUTOFFS:
                            cell = group['method_sums'][m][str(k)]; score = scores[m][str(k)]
                            cell['hits'] += score['hits']; cell['recall_sum'] += score['recall']
                            cell['ndcg_sum'] += score['ndcg']
        if count % 100000 == 0:
            print(f'  ranked {count:,} historical customers', flush=True)
    if count != frozen['eligible_users'] or any(h.hexdigest() != frozen['canonical_candidate_sha256'] for h in hashes.values()):
        raise ValueError('Candidate membership changed after pre-label freeze')
    return {'groups': {n: finish_group(g) for n, g in groups.items()},
            'candidate_universe_sha256': {n: h.hexdigest() for n,h in hashes.items()},
            'customers_ranked': count}


def main():
    root = Path.cwd(); work = root/'data/ranking/phase10b2a'
    if shutil.disk_usage(root).free < 20*1024**3:
        raise RuntimeError('Require 20 GiB free for safe local processing')
    work.mkdir(parents=True, exist_ok=True)
    protocol_path = root/'docs/ranking/phase10b2a_protocol.json'
    protocol = json.loads(protocol_path.read_text())
    if protocol['candidate_budget'] != BUDGET or protocol['cutoffs'] != list(CUTOFFS):
        raise ValueError('Protocol disagrees with frozen implementation')
    old = json.loads((root/'docs/ranking/phase10b1_candidate_summary.json').read_text())
    if digest(root/'src/growthlab/candidates.py') != old['source_code_sha256']:
        raise ValueError('Prior candidate code changed')
    code_hash = digest(Path(__file__))
    result = {'protocol': protocol, 'protocol_sha256': digest(protocol_path),
        'source_sha256': code_hash, 'prior_candidate_summary_sha256': digest(root/'docs/ranking/phase10b1_candidate_summary.json'),
        'final_test_accessed': False, 'snapshots': {}}
    for split, label_month in [('train', '2019-Nov'), ('validation', '2019-Dec')]:
        started = time.perf_counter()
        db = root/f'data/ranking/phase10b1/{split}.duckdb'
        expected_db = old['snapshots'][split]['freeze']['history_database_sha256']
        if digest(db) != expected_db: raise ValueError('Prior history artifact changed')
        label_path = root/f'data/features/phase2/cleaned/{label_month}.parquet'
        label_sha = old['input_sha256'][str(label_path.relative_to(root))]
        if digest(label_path) != label_sha: raise ValueError('Label source changed')
        con = duckdb.connect(str(db), read_only=True)
        try:
            configure(con, protocol, work/(split+'_spill'))
            print(f'{split}: hashing all frozen candidates before label access', flush=True)
            freeze_started = time.perf_counter()
            frozen = freeze_candidates(con, split, protocol['customer_batch_size'])
            freeze_seconds = time.perf_counter()-freeze_started
            frozen.update({'protocol_sha256': result['protocol_sha256'], 'source_sha256': code_hash,
                'history_database_sha256': expected_db})
            (work/f'{split}_freeze.json').write_text(json.dumps(frozen,indent=2)+'\n')
            print(f'{split}: membership frozen; evaluating two fixed orderings', flush=True)
            labels = load_labels(con, label_path, split)
            evaluation_started = time.perf_counter()
            evaluation = evaluate(con, split, labels, frozen, protocol['customer_batch_size'])
            evaluation_seconds = time.perf_counter()-evaluation_started
            all_group = evaluation['groups']['all']
            previous = old['snapshots'][split]['matched_budget']['personal_backfilled']['100']
            if all_group['candidate_hits'] != previous['hits'] or all_group['relevant_pairs'] != previous['relevant_pairs']:
                raise ValueError('Candidate recall no longer reconciles to Phase 10B1')
        finally:
            con.close()
        if digest(db) != expected_db or digest(label_path) != label_sha:
            raise ValueError('Prior input changed during ranking evaluation')
        result['snapshots'][split] = {'window': development_window(split), 'freeze': frozen,
            'input_database_sha256': expected_db, 'label_sha256': label_sha,
            **evaluation, 'resources': {'candidate_freeze_seconds': freeze_seconds,
            'evaluation_seconds': evaluation_seconds, 'elapsed_seconds': time.perf_counter()-started,
            'peak_process_rss': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'rss_units': 'bytes on macOS; KiB on Linux'}}
    if code_hash != digest(Path(__file__)) or result['protocol_sha256'] != digest(protocol_path):
        raise ValueError('Frozen ranking code or protocol changed')
    result['duckdb_version'] = duckdb.__version__
    dest = root/'docs/ranking/phase10b2a_summary.json'
    dest.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(f'Aggregate results: {dest.relative_to(root)}',flush=True)


if __name__ == '__main__':
    main()
