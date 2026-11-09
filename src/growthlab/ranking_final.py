"""Phase 10C: prepare, evaluate once, and verify frozen product ranking.

January outcomes are opened only after a disk-backed December history and
complete candidate membership have been fingerprinted. No fitting API is used.
"""
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import resource
import shutil
import time
from unittest.mock import patch

import duckdb
import numpy as np

from .ml_reranking import (
    FEATURES, METHODS, feature_vector, ml_order, paired_bootstrap,
    joblib, sklearn, HistGradientBoostingClassifier, threadpool_limits,
)
from .candidates import configure, priority_with_fallback, quote
from .ranking_audit import digest, rows
from .ranking_baselines import append_hash, order_candidates, ranking_metrics, CUTOFFS


START = datetime(2019,12,1)
CUTOFF = datetime(2020,1,1)
END = datetime(2020,1,15)
BUDGET = 100
UPSTREAM = ('src/growthlab/ml_reranking.py','src/growthlab/ranking_baselines.py',
            'src/growthlab/candidates.py','docs/ranking/phase10b2b_summary.json')


def save_json(path, value, exclusive=False):
    # Serialize completely before opening the output; no partial JSON on failure.
    payload=json.dumps(value,indent=2,default=str,allow_nan=False)+'\n'
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x' if exclusive else 'w') as stream:stream.write(payload)


def now():return datetime.now(timezone.utc).isoformat()


def model_from_protocol(root, protocol):
    path=root/protocol['model_path']
    if digest(path)!=protocol['model_sha256']:raise ValueError('Frozen trained model changed')
    model=joblib.load(path)
    if not isinstance(model,HistGradientBoostingClassifier):raise ValueError('Wrong saved model class')
    if model.n_features_in_!=len(FEATURES) or model.n_iter_!=100:raise ValueError('Model schema/iterations changed')
    if any(model.get_params()[k]!=v for k,v in protocol['model_parameters'].items()):raise ValueError('Model configuration changed')
    return model


def build_history(con):
    """Final-snapshot adapter: same Phase 10B2B aggregates, fixed December dates.

    Earlier development-only functions intentionally reject the final snapshot;
    this separate adapter preserves them without weakening their safeguards.
    """
    con.execute(f"""CREATE OR REPLACE TABLE ui AS SELECT user_key,product_key,
        count(*) FILTER(WHERE event_type='view') views,
        count(*) FILTER(WHERE event_type='cart') carts,
        count(*) FILTER(WHERE event_type='purchase') purchases,
        max(event_ts) latest,count(*) events FROM history_events
        WHERE event_ts>={quote(START)}::TIMESTAMP AND event_ts<{quote(CUTOFF)}::TIMESTAMP
        AND user_key>0 AND product_key>0
        AND event_type IN ('view','cart','purchase','remove_from_cart') GROUP BY 1,2""")
    con.execute('CREATE OR REPLACE TABLE customers AS SELECT user_key,sum(events) events FROM ui GROUP BY 1')
    con.execute('CREATE OR REPLACE TABLE products AS SELECT product_key,count(*) buyers FROM ui WHERE purchases>0 GROUP BY 1')
    con.execute('''CREATE OR REPLACE TABLE personal AS SELECT user_key,product_key,
        row_number() OVER(PARTITION BY user_key ORDER BY latest DESC,product_key) r
        FROM ui QUALIFY r<=100''')
    con.execute('''CREATE OR REPLACE TABLE popularity AS SELECT product_key,buyers,
        row_number() OVER(ORDER BY buyers DESC,product_key) r FROM products QUALIFY r<=100''')
    return rows(con, '''SELECT count(*) historical_pairs,sum(events) historical_events,
        min(latest) earliest_pair_latest,max(latest) latest_pair_event,
        count(DISTINCT product_key) historical_products,
        (SELECT count(*) FROM customers) eligible_customers FROM ui''')[0]


def final_batches(con, batch_size=1000):
    users=[u for u, in con.execute('SELECT user_key FROM customers ORDER BY user_key').fetchall()]
    popular=[p for p, in con.execute('SELECT product_key FROM popularity ORDER BY r').fetchall()]
    buyers=dict(con.execute('SELECT product_key,buyers FROM products').fetchall())
    if len(popular)!=BUDGET:raise ValueError('Historical catalog cannot fill the frozen 100 budget')
    for offset in range(0,len(users),batch_size):
        selected=users[offset:offset+batch_size];low,high=selected[0],selected[-1]
        histories=defaultdict(dict);personal=defaultdict(list)
        for u,p,v,c,n,t,e in con.execute('SELECT * FROM ui WHERE user_key>=? AND user_key<=? ORDER BY user_key,product_key',[low,high]).fetchall():
            if not START<=t<CUTOFF:raise ValueError('Feature outside past-only final history')
            histories[u][p]=(v,c,n,t,e)
        for u,p in con.execute('SELECT user_key,product_key FROM personal WHERE user_key>=? AND user_key<=? ORDER BY user_key,r',[low,high]).fetchall():personal[u].append(p)
        activity=dict(con.execute('SELECT user_key,events FROM customers WHERE user_key>=? AND user_key<=?',[low,high]).fetchall())
        batch=[]
        for u in selected:
            candidates=priority_with_fallback(personal[u],popular,BUDGET)
            if len(candidates)!=BUDGET or len(set(candidates))!=BUDGET:raise ValueError('Candidate budget/uniqueness changed')
            batch.append((u,candidates,histories[u]))
        yield batch,activity,buyers


def membership(con, batch_size=1000):
    hasher=hashlib.sha256();users=0
    for batch,_,_ in final_batches(con,batch_size):
        for u,candidates,_ in batch:append_hash(hasher,u,candidates);users+=1
    return {'eligible_users':users,'candidate_rows':users*BUDGET,
            'candidate_sha256':hasher.hexdigest(),'candidate_budget':BUDGET}


def verify_ready(root):
    docs=root/'docs/ranking';protocol=json.loads((docs/'phase10c_protocol.json').read_text())
    freeze=json.loads((docs/'phase10c_freeze.json').read_text())
    if digest(docs/'phase10c_protocol.json')!=freeze['protocol_sha256']:raise ValueError('Final protocol changed after freeze')
    if digest(Path(__file__))!=freeze['code_sha256']:raise ValueError('Final evaluation source changed after freeze')
    if protocol['features']!=list(FEATURES) or protocol['candidate_budget']!=BUDGET:raise ValueError('Frozen feature/candidate contract changed')
    for p,h in freeze['upstream_sha256'].items():
        if digest(root/p)!=h:raise ValueError('Upstream input changed: '+p)
    if digest(root/freeze['history_database_path'])!=freeze['history_database_sha256']:raise ValueError('Final history changed')
    if digest(root/freeze['history_source_path'])!=freeze['history_source_sha256']:raise ValueError('December source changed')
    if protocol['versions']!={'python':__import__('platform').python_version(),'numpy':np.__version__,'sklearn':sklearn.__version__,'duckdb':duckdb.__version__}:raise ValueError('Frozen dependency versions changed')
    model=model_from_protocol(root,protocol)
    return protocol,freeze,model


def claim_access(path, protocol_sha, freeze_sha):
    receipt={'first_access_at_utc':now(),'protocol_sha256':protocol_sha,
        'freeze_sha256':freeze_sha,'labels_authorized':True,
        'purpose':'One final Jan 1 inclusive to Jan 15 exclusive ranking evaluation; no fit/tuning'}
    save_json(path,receipt,exclusive=True)
    return receipt


def load_final_labels(con, path, receipt):
    if not receipt or not receipt.get('labels_authorized') or not receipt.get('freeze_sha256'):
        raise ValueError('Final outcomes require a prior frozen protocol/access receipt')
    labels=defaultdict(set)
    for u,p in con.execute(f"""SELECT DISTINCT e.user_key,e.product_key FROM
        read_parquet({quote(path)}) e JOIN customers c USING(user_key)
        WHERE e.event_type='purchase' AND e.event_ts>={quote(CUTOFF)}::TIMESTAMP
        AND e.event_ts<{quote(END)}::TIMESTAMP""").fetchall():labels[u].add(p)
    return labels


def score_final(con, labels, model, protocol, frozen_membership, work):
    sums={m:{str(k):[0,0.,0.] for k in CUTOFFS} for m in METHODS}
    hashes={m:hashlib.sha256() for m in METHODS};canonical=hashlib.sha256()
    vectors=[];differences=[];hit_rows=[];label_sizes=[];retrieved=[];users=0
    errors={'absent_from_candidates':0,'retrieved_not_top10_ml':0,
        'top10_ml_only':0,'top10_recency_only':0,'top10_both':0}
    for batch,activity,buyers in final_batches(con,protocol['customer_batch_size']):
        x=np.asarray([feature_vector(p,h,activity[u],buyers,CUTOFF)
            for u,candidates,h in batch for p in candidates],dtype=np.float32)
        with threadpool_limits(limits=1):margins=model.decision_function(x)
        if users==0:
            with threadpool_limits(limits=1):
                if not np.array_equal(margins[:1000],model.decision_function(x[:1000])):raise ValueError('Nondeterministic frozen model scores')
            np.savez_compressed(work/'inference_check.npz',features=x[:1000],margins=margins[:1000])
        offset=0
        for u,candidates,h in batch:
            append_hash(canonical,u,candidates);users+=1
            latest={p:row[3] for p,row in h.items()}
            orders=order_candidates(candidates,latest,buyers)
            orders['ml']=ml_order(candidates,margins[offset:offset+BUDGET],orders['personal_recency']);offset+=BUDGET
            for m in METHODS:
                if len(orders[m])!=BUDGET or set(orders[m])!=set(candidates):raise ValueError('Methods do not share identical candidate universe')
                append_hash(hashes[m],u,orders[m])
            relevant=labels.get(u,set())
            if not relevant:continue
            metrics={m:ranking_metrics(orders[m],relevant) for m in METHODS}
            vector=[];delta=[];hits=[]
            for k in CUTOFFS:
                delta.extend(metrics['ml'][str(k)][e]-metrics['personal_recency'][str(k)][e] for e in ('recall','ndcg'))
                for m in METHODS:
                    score=metrics[m][str(k)];cell=sums[m][str(k)]
                    cell[0]+=score['hits'];cell[1]+=score['recall'];cell[2]+=score['ndcg']
                    vector.extend((score['recall'],score['ndcg']));hits.append(score['hits'])
            vectors.append(vector);differences.append(delta);hit_rows.append(hits)
            label_sizes.append(len(relevant));retrieved.append(len(set(candidates)&relevant))
            ml=set(orders['ml'][:10])&relevant;rec=set(orders['personal_recency'][:10])&relevant
            errors['absent_from_candidates']+=len(relevant-set(candidates))
            errors['retrieved_not_top10_ml']+=len((relevant&set(candidates))-ml)
            errors['top10_ml_only']+=len(ml-rec);errors['top10_recency_only']+=len(rec-ml);errors['top10_both']+=len(ml&rec)
        if users%100000==0:print(f'  final: {users:,} customers scored with all 100 candidates',flush=True)
    if users!=frozen_membership['eligible_users'] or canonical.hexdigest()!=frozen_membership['candidate_sha256']:
        raise ValueError('Final cohort/candidate membership changed after label access')
    if any(h.hexdigest()!=canonical.hexdigest() for h in hashes.values()):raise ValueError('Candidate hashes differ across methods')
    n=len(labels);pairs=sum(map(len,labels.values()))
    if n!=len(vectors):raise ValueError('Not every eligible purchaser was evaluated')
    result={'preselected_method':'ml','eligible_users':users,'candidate_rows':users*BUDGET,
        'purchasing_users':n,'relevant_pairs':pairs,'candidate_hits':sum(retrieved),
        'candidate_recall_micro':sum(retrieved)/pairs if pairs else None,
        'candidate_recall_macro':sum(h/r for h,r in zip(retrieved,label_sizes))/n if n else None,
        'eligible_user_coverage':1. if users else None,'full_top20_coverage':1. if users else None,
        'candidate_sha256':canonical.hexdigest(),'method_universe_sha256':{m:h.hexdigest() for m,h in hashes.items()},
        'methods':{m:{str(k):{'hits':sums[m][str(k)][0],
            'recall_macro':sums[m][str(k)][1]/n if n else None,
            'recall_micro':sums[m][str(k)][0]/pairs if pairs else None,
            'ndcg_macro':sums[m][str(k)][2]/n if n else None} for k in CUTOFFS} for m in METHODS},
        'paired_uncertainty':paired_bootstrap(differences,protocol['uncertainty']) if n else None,
        'errors':errors}
    if result['paired_uncertainty'] is not None:
        result['paired_uncertainty']['endpoints']=[f'{e}@{k}' for k in CUTOFFS for e in ('recall_macro','ndcg_macro')]
    np.savez_compressed(work/'purchaser_metrics.npz',metrics=np.asarray(vectors).reshape(-1,18),
        paired_differences=np.asarray(differences).reshape(-1,6),hits=np.asarray(hit_rows,dtype=np.int64).reshape(-1,9),
        relevant_counts=np.asarray(label_sizes,dtype=np.int64),candidate_hits=np.asarray(retrieved,dtype=np.int64))
    return result


def prepare(root):
    docs=root/'docs/ranking';work=root/'data/ranking/phase10c';work.mkdir(parents=True,exist_ok=True)
    if (docs/'phase10c_freeze.json').exists():
        verify_ready(root);print('Existing final freeze verified; not rebuilding.',flush=True);return
    if (work/'access_ledger.json').exists():raise ValueError('Final labels already accessed; cannot prepare a different experiment')
    if shutil.disk_usage(root).free<20*1024**3:raise RuntimeError('Require 20 GiB free for bounded processing')
    started=time.perf_counter();p=json.loads((docs/'phase10c_protocol.json').read_text())
    prior=json.loads((docs/'phase10b2b_summary.json').read_text())
    if digest(docs/'phase10b2b_summary.json')!=p['prior_summary_sha256']:raise ValueError('Selected validation evidence changed')
    if p['features']!=list(FEATURES) or prior['validation']['selected_method']!='ml':raise ValueError('Feature/selection contract changed')
    model_from_protocol(root,p)  # Confirm class, configuration, persistent weights.
    expected={x['month']:x for x in json.loads((root/'docs/phase2/summary.json').read_text())['cleaned_months']}
    history=root/'data/features/phase2/cleaned/2019-Dec.parquet'
    if digest(history)!=expected['2019-Dec']['sha256']:raise ValueError('December cleaned input changed')
    db=work/'history.duckdb';con=duckdb.connect(str(db))
    try:
        configure(con,p,work/'prepare_spill')
        con.execute(f'CREATE OR REPLACE VIEW history_events AS SELECT * FROM read_parquet({quote(history)})')
        stats=build_history(con)
        if stats['historical_events']!=expected['2019-Dec']['events']:raise ValueError('December cleaning/history counts do not reconcile')
        frozen=membership(con,p['customer_batch_size']);con.execute('CHECKPOINT')
    finally:con.close()
    freeze={'prepared_at_utc':now(),'outcomes_read':False,
        'protocol_sha256':digest(docs/'phase10c_protocol.json'),'code_sha256':digest(Path(__file__)),
        'upstream_sha256':{path:digest(root/path) for path in UPSTREAM},
        'model_path':p['model_path'],'model_sha256':p['model_sha256'],'model_parameters':p['model_parameters'],
        'history_source_path':str(history.relative_to(root)),'history_source_sha256':digest(history),
        'history_database_path':str(db.relative_to(root)),'history_database_sha256':digest(db),
        'expected_outcome_path':'data/features/phase2/cleaned/2020-Jan.parquet',
        'expected_outcome_sha256':expected['2020-Jan']['sha256'],
        'history_statistics':stats,'membership':frozen,
        'resources':{'elapsed_seconds':time.perf_counter()-started,'peak_process_rss':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'rss_units':'bytes on macOS; KiB on Linux','database_bytes':db.stat().st_size}}
    save_json(docs/'phase10c_freeze.json',freeze,exclusive=True)
    verify_ready(root)
    print('Final protocol, trained model, December features and complete candidate membership frozen BEFORE January label access.',flush=True)


def evaluate_once(root):
    docs=root/'docs/ranking';work=root/'data/ranking/phase10c';started=time.perf_counter()
    p,frozen,model=verify_ready(root)
    receipt=claim_access(work/'access_ledger.json',frozen['protocol_sha256'],digest(docs/'phase10c_freeze.json'))
    outcomes=root/frozen['expected_outcome_path']
    if digest(outcomes)!=frozen['expected_outcome_sha256']:raise ValueError('January input fingerprint changed')
    con=duckdb.connect(str(root/frozen['history_database_path']),read_only=True)
    try:
        configure(con,p,work/'evaluate_spill')
        labels=load_final_labels(con,outcomes,receipt)
        print(f'Final outcomes opened under frozen protocol; {len(labels):,} eligible purchasers',flush=True)
        result=score_final(con,labels,model,p,frozen['membership'],work)
    finally:con.close()
    verify_ready(root)
    if digest(outcomes)!=frozen['expected_outcome_sha256']:raise ValueError('January source changed during evaluation')
    result.update({'completed_at_utc':now(),'protocol_sha256':frozen['protocol_sha256'],
        'freeze_sha256':digest(docs/'phase10c_freeze.json'),'source_sha256':digest(Path(__file__)),
        'model_sha256_before':p['model_sha256'],'model_sha256_after':digest(root/p['model_path']),
        'artifacts':{str(path.relative_to(root)):digest(path) for path in (work/'access_ledger.json',work/'purchaser_metrics.npz',work/'inference_check.npz')},
        'resources':{'evaluation_seconds':time.perf_counter()-started,'peak_process_rss':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'rss_units':'bytes on macOS; KiB on Linux'}})
    # Local completed checkpoint precedes the small public aggregate export.
    save_json(work/'completed_evaluation.json',result,exclusive=True)
    save_json(docs/'phase10c_summary.json',result,exclusive=True)
    print('Final aggregate result saved; use verify for checks without reopening January labels.',flush=True)


def verify_saved(root):
    docs=root/'docs/ranking';p,frozen,model=verify_ready(root)
    result=json.loads((docs/'phase10c_summary.json').read_text())
    if result['protocol_sha256']!=frozen['protocol_sha256'] or result['freeze_sha256']!=digest(docs/'phase10c_freeze.json'):
        raise ValueError('Final result/protocol provenance mismatch')
    for path,h in result['artifacts'].items():
        if digest(root/path)!=h:raise ValueError('Saved final artifact changed: '+path)
    if result['model_sha256_before']!=result['model_sha256_after'] or result['model_sha256_after']!=digest(root/p['model_path']):raise ValueError('Model weights changed')
    if set(result['method_universe_sha256'].values())!={frozen['membership']['candidate_sha256']}:raise ValueError('Saved methods used different candidates')
    with np.load(root/'data/ranking/phase10c/purchaser_metrics.npz') as data:
        metrics=data['metrics'];hits=data['hits'];counts=data['relevant_counts'];retrieved=data['candidate_hits']
        n=len(counts);pairs=int(counts.sum())
        if n!=result['purchasing_users'] or pairs!=result['relevant_pairs']:raise ValueError('Purchaser metric counts changed')
        for ki,k in enumerate(CUTOFFS):
            for mi,m in enumerate(METHODS):
                c=result['methods'][m][str(k)];col=ki*6+mi*2;hit_col=ki*3+mi
                if int(hits[:,hit_col].sum())!=c['hits']:raise ValueError('Final hit calculation mismatch')
                if n and not np.allclose([metrics[:,col].mean(),metrics[:,col+1].mean(),hits[:,hit_col].sum()/pairs],
                    [c['recall_macro'],c['ndcg_macro'],c['recall_micro']],rtol=0,atol=1e-12):raise ValueError('Final metric calculations changed')
        if n:
            if not np.allclose([retrieved.sum()/pairs,np.mean(retrieved/counts)],
                [result['candidate_recall_micro'],result['candidate_recall_macro']],rtol=0,atol=1e-12):raise ValueError('Candidate ceiling changed')
            delta=np.column_stack([metrics[:,ki*6+4+e]-metrics[:,ki*6+2+e] for ki in range(3) for e in range(2)])
            if not np.array_equal(delta,data['paired_differences']):raise ValueError('Comparison pairing changed')
            recomputed=paired_bootstrap(delta,p['uncertainty'])
            for key in ('mean_difference','lower_95','upper_95'):
                if not np.allclose(recomputed[key],result['paired_uncertainty'][key],rtol=0,atol=1e-12):raise ValueError('Final paired interval changed')
    with np.load(root/'data/ranking/phase10c/inference_check.npz') as check, threadpool_limits(limits=1):
        if not np.array_equal(model.decision_function(check['features']),check['margins']):raise ValueError('Frozen model inference not reproducible')
    print('PASS: saved final metrics, pairing/bootstrap, candidate provenance and unchanged model reproduce; NO January labels reopened.',flush=True)


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('stage',choices=['prepare','evaluate','verify'])
    args=parser.parse_args();root=Path.cwd()
    # Explicit runtime guard applies to every CLI stage; no real refit permitted.
    with patch.object(HistGradientBoostingClassifier,'fit',side_effect=RuntimeError('Final evaluation may not fit or refit')):
        {'prepare':prepare,'evaluate':evaluate_once,'verify':verify_saved}[args.stage](root)


if __name__=='__main__':main()
