"""One bounded pointwise reranker on fixed candidates; development only."""
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import resource
import shutil
import time

import duckdb
import numpy as np

from .openmp_runtime import preload_local_openmp
preload_local_openmp()  # Existing local runtime only; never installs/downloads.
import joblib
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from threadpoolctl import threadpool_limits

from .candidates import configure, development_window, load_labels, quote
from .ranking_audit import digest, rows
from .ranking_baselines import (
    batches, append_hash, order_candidates, ranking_metrics, CUTOFFS, BUDGET,
)


FEATURES = ('product_views', 'product_carts', 'product_purchases',
    'hours_since_product_event', 'product_buyers', 'customer_events', 'from_personal_history')
METHODS = ('global_popularity', 'personal_recency', 'ml')


def prepare_features(con, history_path, split):
    """Only genuinely pre-score events enter numeric customer/product aggregates."""
    _, start, cutoff, _ = development_window(split)
    con.execute(f"""CREATE OR REPLACE TABLE ui AS SELECT user_key,product_key,
        count(*) FILTER(WHERE event_type='view') views,
        count(*) FILTER(WHERE event_type='cart') carts,
        count(*) FILTER(WHERE event_type='purchase') purchases,
        max(event_ts) latest,count(*) events
        FROM read_parquet({quote(history_path)})
        WHERE event_ts>={quote(start)}::TIMESTAMP AND event_ts<{quote(cutoff)}::TIMESTAMP
        AND user_key>0 AND product_key>0
        AND event_type IN ('view','cart','purchase','remove_from_cart') GROUP BY 1,2""")
    con.execute('CREATE OR REPLACE TABLE customers AS SELECT user_key,sum(events) events FROM ui GROUP BY 1')
    con.execute('CREATE OR REPLACE TABLE products AS SELECT product_key,count(*) buyers FROM ui WHERE purchases>0 GROUP BY 1')
    return rows(con, '''SELECT count(*) historical_pairs,sum(events) historical_events,
        min(latest) earliest_pair_latest,max(latest) latest_pair_event,
        (SELECT count(*) FROM customers) historical_customers FROM ui''')[0]


def feature_vector(product, item_history, customer_events, buyers, cutoff):
    """item_history maps product to (views,carts,purchases,latest,events)."""
    row = item_history.get(product)
    if row is not None:
        views, carts, purchases, latest, _ = row
        if latest >= cutoff:
            raise ValueError('Feature includes an event at/after prediction')
        hours = (cutoff-latest).total_seconds()/3600
    else:
        views = carts = purchases = 0; hours = np.nan
    return (views, carts, purchases, hours, buyers.get(product, 0), customer_events, int(row is not None))


def feature_batches(old_con, feature_con, split, batch_size=1000):
    from datetime import datetime
    _, start, cutoff, _ = development_window(split)
    start, cutoff = datetime.fromisoformat(start), datetime.fromisoformat(cutoff)
    buyers = dict(feature_con.execute('SELECT product_key,buyers FROM products').fetchall())
    for batch in batches(old_con, split, batch_size):
        lower, upper = batch[0][0], batch[-1][0]
        histories = defaultdict(dict)
        for user, product, views, carts, purchases, latest, events in feature_con.execute(
            'SELECT * FROM ui WHERE user_key>=? AND user_key<=? ORDER BY user_key,product_key',
            [lower,upper]).fetchall():
            if not start <= latest < cutoff: raise ValueError('Historical feature window changed')
            histories[user][product] = (views,carts,purchases,latest,events)
        activity = dict(feature_con.execute('SELECT user_key,events FROM customers WHERE user_key>=? AND user_key<=?',
            [lower,upper]).fetchall())
        yield batch, histories, activity, buyers, cutoff


def retained_negative(user, product, seed=20261109):
    value = hashlib.sha256(f'growthlab-10b2b:{seed}:{user}:{product}'.encode()).digest()
    return int.from_bytes(value[:8], 'big') < (2**64)//50


def training_arrays(old_con, feature_con, labels, frozen_hash, protocol, split='train'):
    if split != 'train': raise ValueError('Only training snapshot may generate fitting examples')
    chunks, targets, weights = [], [], []
    identity, selected_identity = hashlib.sha256(), hashlib.sha256()
    seen = positives = retained = 0
    for batch, histories, activity, buyers, cutoff in feature_batches(old_con,feature_con,split,protocol['customer_batch_size']):
        values, ys, ws = [], [], []
        for user, candidates, _ in batch:
            append_hash(identity,user,candidates)
            relevant = labels.get(user,set())
            for product in candidates:
                y = int(product in relevant); seen += 1; positives += y
                if y or retained_negative(user,product,protocol['training_sampling']['seed']):
                    values.append(feature_vector(product,histories[user],activity[user],buyers,cutoff))
                    ys.append(y); ws.append(1. if y else 50.)
                    selected_identity.update(f'{user}:{product}:{y}\n'.encode())
        if values:
            chunks.append(np.asarray(values,dtype=np.float32));targets.append(np.asarray(ys,dtype=np.uint8))
            weights.append(np.asarray(ws,dtype=np.float64));retained += len(values)
        if retained > protocol['training_sampling']['maximum_retained_rows']:
            raise RuntimeError('Training sample exceeds frozen memory guard')
    if identity.hexdigest() != frozen_hash: raise ValueError('Training candidate membership changed')
    x,y,w = np.concatenate(chunks),np.concatenate(targets),np.concatenate(weights)
    if int(y.sum()) != positives: raise ValueError('Training positives lost in sampling')
    return x,y,w,{'full_candidate_rows':seen,'full_positive_rows':positives,
        'full_negative_rows':seen-positives,'retained_rows':len(y),
        'retained_positive_rows':int(y.sum()),'retained_negative_rows':int((y==0).sum()),
        'full_positive_rate':positives/seen,'sample_positive_rate':float(y.mean()),
        'weighted_positive_rate':float(np.dot(y,w)/w.sum()),
        'weighted_total_rows':float(w.sum()),'sample_identity_sha256':selected_identity.hexdigest(),
        'candidate_sha256':identity.hexdigest(),'array_bytes':x.nbytes+y.nbytes+w.nbytes}


def fit_model(x,y,weights,protocol,split='train'):
    if split != 'train': raise ValueError('Validation/final data cannot fit model')
    if x.shape != (len(y),len(FEATURES)) or len(weights) != len(y):
        raise ValueError('Training feature schema or dimensions changed')
    model = HistGradientBoostingClassifier(**protocol['model_parameters'])
    with threadpool_limits(limits=1):
        model.fit(x,y,sample_weight=weights)
    return model


def ml_order(candidates, scores, recency):
    if len(candidates)!=len(scores) or set(candidates)!=set(recency) or len(set(candidates))!=len(candidates):
        raise ValueError('ML must reorder the same unique candidates')
    if not np.isfinite(scores).all(): raise ValueError('Nonfinite ML margins')
    positions = {p:r for r,p in enumerate(recency)}
    margins = dict(zip(candidates,scores))
    return sorted(candidates,key=lambda p:(-margins[p],positions[p],p))


def paired_bootstrap(differences, spec):
    values = np.asarray(differences,dtype=np.float64)
    if values.ndim!=2 or len(values)==0 or not np.isfinite(values).all():
        raise ValueError('Need finite paired purchaser differences')
    rng = np.random.default_rng(spec['seed'])
    draws = np.empty((spec['replications'],values.shape[1]),dtype=np.float64)
    for offset in range(0,len(draws),spec['replication_batch']):
        n=min(spec['replication_batch'],len(draws)-offset)
        indices=rng.integers(0,len(values),size=(n,len(values)))
        draws[offset:offset+n]=values[indices].mean(axis=1)
    alpha=1-spec['confidence_level']
    lower,upper=np.quantile(draws,[alpha/2,1-alpha/2],axis=0)
    return {'mean_difference':values.mean(axis=0).tolist(),
        'lower_95':lower.tolist(),'upper_95':upper.tolist(),
        'purchasers':len(values),'replications':len(draws),'seed':spec['seed']}


def validation_evaluation(old_con, feature_con, labels, model, baseline, protocol):
    sums={m:{str(k):{'hits':0,'recall_sum':0.,'ndcg_sum':0.} for k in CUTOFFS} for m in METHODS}
    identities={m:hashlib.sha256() for m in METHODS}
    identity=hashlib.sha256();users=0;candidate_hits=0;candidate_macro=0.
    purchaser_vectors=[];differences=[]
    mistakes={'relevant_pairs':0,'absent_from_candidates':0,'retrieved_not_top10_ml':0,
        'top10_ml_only':0,'top10_recency_only':0,'top10_both':0,
        'relevant_personal_candidates':0,'relevant_backfill_candidates':0}
    for batch, histories, activity, buyers, cutoff in feature_batches(old_con,feature_con,'validation',protocol['customer_batch_size']):
        x=np.asarray([feature_vector(p,histories[u],activity[u],buyers,cutoff)
            for u,candidates,_ in batch for p in candidates],dtype=np.float32)
        with threadpool_limits(limits=1):scores=model.decision_function(x)
        # Repeat an initial bounded sample; all evaluation candidates are scored.
        if users == 0:
            with threadpool_limits(limits=1):
                if not np.array_equal(scores[:1000],model.decision_function(x[:1000])):
                    raise ValueError('ML scores not deterministic')
        offset=0
        for user,candidates,history in batch:
            if len(candidates)!=BUDGET: raise ValueError('Validation candidate budget changed')
            append_hash(identity,user,candidates);users+=1
            ordered=order_candidates(candidates,history,buyers)
            ordered['ml']=ml_order(candidates,scores[offset:offset+BUDGET],ordered['personal_recency']);offset+=BUDGET
            for m in METHODS:
                if len(ordered[m])!=BUDGET or set(ordered[m])!=set(candidates):raise ValueError('Candidate universes differ')
                append_hash(identities[m],user,ordered[m])
            relevant=labels.get(user,set())
            if not relevant:continue
            metrics={m:ranking_metrics(ordered[m],relevant) for m in METHODS}
            hits=len(set(candidates)&relevant);candidate_hits+=hits;candidate_macro+=hits/len(relevant)
            vector=[];delta=[]
            for k in CUTOFFS:
                for endpoint in ('recall','ndcg'):
                    delta.append(metrics['ml'][str(k)][endpoint]-metrics['personal_recency'][str(k)][endpoint])
                for m in METHODS:
                    cell=sums[m][str(k)];score=metrics[m][str(k)]
                    cell['hits']+=score['hits'];cell['recall_sum']+=score['recall'];cell['ndcg_sum']+=score['ndcg']
                    vector.extend([score['recall'],score['ndcg']])
            differences.append(delta);purchaser_vectors.append(vector)
            ml_hits=set(ordered['ml'][:10])&relevant;recent_hits=set(ordered['personal_recency'][:10])&relevant
            mistakes['relevant_pairs']+=len(relevant);mistakes['absent_from_candidates']+=len(relevant-set(candidates))
            mistakes['retrieved_not_top10_ml']+=len(relevant&set(candidates)-ml_hits)
            mistakes['top10_ml_only']+=len(ml_hits-recent_hits);mistakes['top10_recency_only']+=len(recent_hits-ml_hits)
            mistakes['top10_both']+=len(ml_hits&recent_hits)
            mistakes['relevant_personal_candidates']+=sum(p in history for p in relevant&set(candidates))
            mistakes['relevant_backfill_candidates']+=sum(p not in history for p in relevant&set(candidates))
        if users%100000==0:print(f'  ML validation: {users:,} users, full 100 candidates each',flush=True)
    frozen=baseline['freeze']['canonical_candidate_sha256']
    if identity.hexdigest()!=frozen or any(h.hexdigest()!=frozen for h in identities.values()):
        raise ValueError('Validation universe no longer matches frozen baseline')
    pairs=sum(map(len,labels.values()));n=len(labels)
    metrics={m:{str(k):{'hits':sums[m][str(k)]['hits'],
        'recall_macro':sums[m][str(k)]['recall_sum']/n,'recall_micro':sums[m][str(k)]['hits']/pairs,
        'ndcg_macro':sums[m][str(k)]['ndcg_sum']/n} for k in CUTOFFS} for m in METHODS}
    for m in ('global_popularity','personal_recency'):
        if metrics[m]!=baseline['groups']['all']['methods'][m]:raise ValueError('Prior ranking metrics changed')
    if candidate_hits!=baseline['groups']['all']['candidate_hits']:raise ValueError('Candidate ceiling changed')
    uncertainty=paired_bootstrap(differences,protocol['uncertainty'])
    uncertainty['endpoints']=[f'{e}@{k}' for k in CUTOFFS for e in ('recall_macro','ndcg_macro')]
    prefer_ml=uncertainty['lower_95'][2]>0 and uncertainty['lower_95'][3]>0
    return {'eligible_users':users,'purchasing_users':n,'relevant_pairs':pairs,
        'candidate_hits':candidate_hits,'candidate_recall_micro':candidate_hits/pairs,
        'candidate_recall_macro':candidate_macro/n,'eligible_user_coverage':1.,
        'methods':metrics,'candidate_sha256':identity.hexdigest(),
        'method_universe_sha256':{m:h.hexdigest() for m,h in identities.items()},
        'paired_uncertainty':uncertainty,'mistakes':mistakes,
        'selected_method':'ml' if prefer_ml else 'personal_recency'},np.asarray(purchaser_vectors),np.asarray(differences)


def feature_storage_bytes(root, layers):
    return sum((root / layer['path']).stat().st_size for layer in layers.values())


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evaluate-saved',action='store_true',help='Verify sampled arrays and evaluate an already frozen model; never fit')
    resume=parser.parse_args().evaluate_saved
    root=Path.cwd();work=root/'data/ranking/phase10b2b';work.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(root).free<20*1024**3:raise RuntimeError('Require 20 GiB free')
    started=time.perf_counter()
    protocol_path=root/'docs/ranking/phase10b2b_protocol.json'
    protocol=json.loads(protocol_path.read_text())
    if protocol['features']!=list(FEATURES):raise ValueError('Feature contract changed')
    protocol_sha=digest(protocol_path);code_sha=digest(Path(__file__))
    old=json.loads((root/'docs/ranking/phase10b2a_summary.json').read_text())
    prior=json.loads((root/'docs/ranking/phase10b1_candidate_summary.json').read_text())
    result={'protocol':protocol,'protocol_sha256':protocol_sha,'source_sha256':code_sha,
        'prior_baseline_summary_sha256':digest(root/'docs/ranking/phase10b2a_summary.json'),
        'versions':{'python':__import__('platform').python_version(),'numpy':np.__version__,'sklearn':sklearn.__version__,'duckdb':duckdb.__version__},
        'final_test_accessed':False,'feature_layers':{}}
    if resume:
        frozen=json.loads((work/'experiment_freeze.json').read_text())
        if frozen['protocol_sha256']!=protocol_sha:raise ValueError('Saved model protocol changed')
        if digest(work/'original_fit_source.py')!=frozen['source_sha256']:raise ValueError('Original fit source changed')
        result['feature_layers']=frozen['feature_layers']
        result['original_fit_source_sha256']=frozen['source_sha256']
        result['recovery_note']='Original fit and full validation completed; final resource-summary export failed on Path subscripting. Export fixed; saved sampled arrays reconstructed and saved model evaluated without fitting. Original fit duration/peak was not retained; resources describe this verification run.'
        result['saved_model_sha256_before']=digest(work/'model.joblib')
        for layer in result['feature_layers'].values():
            if digest(root/layer['path'])!=layer['sha256']:raise ValueError('Saved feature layer changed')
    for split,month in ([] if resume else [('train','2019-Oct'),('validation','2019-Nov')]):
        path=root/f'data/features/phase2/cleaned/{month}.parquet'
        expected=prior['input_sha256'][str(path.relative_to(root))]
        if digest(path)!=expected:raise ValueError('Historical source changed')
        db=work/f'{split}_features.duckdb';con=duckdb.connect(str(db))
        try:
            configure(con,protocol,work/(split+'_spill'))
            print(f'{split}: creating seven past-only features before label access',flush=True)
            stats=prepare_features(con,path,split);con.execute('CHECKPOINT')
        finally:con.close()
        result['feature_layers'][split]={'path':str(db.relative_to(root)),'sha256':digest(db),
            'source_sha256':expected,'stats':{k:str(v) if hasattr(v,'isoformat') else v for k,v in stats.items()}}
    # Freeze implementation and both feature layers before any fitting or labels.
    if not resume:(work/'experiment_freeze.json').write_text(json.dumps(result,indent=2)+'\n')
    def open_pair(split):
        old_path=root/f'data/ranking/phase10b1/{split}.duckdb'
        if digest(old_path)!=old['snapshots'][split]['input_database_sha256']:raise ValueError('Frozen retrieval DB changed')
        a=duckdb.connect(str(old_path),read_only=True)
        b=duckdb.connect(str(root/result['feature_layers'][split]['path']),read_only=True)
        configure(a,protocol,work/(split+'_old_spill'));configure(b,protocol,work/(split+'_feature_spill'))
        return a,b
    train_old,train_features=open_pair('train')
    try:
        label_path=root/'data/features/phase2/cleaned/2019-Nov.parquet'
        if digest(label_path)!=old['snapshots']['train']['label_sha256']:raise ValueError('Training labels changed')
        labels=load_labels(train_old,label_path,'train')
        sampling_start=time.perf_counter()
        print('train: retaining all retrieved positives and deterministic 2% nonpurchases',flush=True)
        x,y,w,stats=training_arrays(train_old,train_features,labels,old['snapshots']['train']['freeze']['canonical_candidate_sha256'],protocol)
        if stats['full_positive_rows']!=old['snapshots']['train']['groups']['all']['candidate_hits']:raise ValueError('Training label reconciliation failed')
        if resume:
            with np.load(work/'training_arrays.npz') as saved:
                if not (np.array_equal(x,saved['x'],equal_nan=True) and np.array_equal(y,saved['y']) and np.array_equal(w,saved['weights'])):
                    raise ValueError('Reconstructed training arrays differ from original fit')
        else:np.savez_compressed(work/'training_arrays.npz',x=x,y=y,weights=w)
        result['training']={**stats,'sampling_seconds':time.perf_counter()-sampling_start}
        if resume:
            print('Verified sampled arrays; loading unchanged saved model (no fit)',flush=True)
            model=joblib.load(work/'model.joblib')
            if any(model.get_params()[k]!=v for k,v in protocol['model_parameters'].items()):raise ValueError('Saved model configuration changed')
            result['training']['fit_seconds']=None
        else:
            fit_started=time.perf_counter();print(f'Fitting one fixed model on {len(y):,} sampled rows',flush=True)
            model=fit_model(x,y,w,protocol)
            result['training']['fit_seconds']=time.perf_counter()-fit_started
        result['training']['iterations']=int(model.n_iter_)
        result['training']['fit_performed_this_run']=not resume
        if not resume:joblib.dump(model,work/'model.joblib')
        # Reload stability, not a second fitted model.
        reloaded=joblib.load(work/'model.joblib')
        with threadpool_limits(limits=1):
            if not np.array_equal(model.decision_function(x[:1000]),reloaded.decision_function(x[:1000])):raise ValueError('Model serialization changed scores')
        del x,y,w,labels
    finally:train_old.close();train_features.close()
    valid_old,valid_features=open_pair('validation')
    try:
        label_path=root/'data/features/phase2/cleaned/2019-Dec.parquet'
        if digest(label_path)!=old['snapshots']['validation']['label_sha256']:raise ValueError('Validation label source changed')
        labels=load_labels(valid_old,label_path,'validation')
        evaluation_started=time.perf_counter();print('validation: scoring every frozen candidate; no sampling',flush=True)
        evaluation,vectors,deltas=validation_evaluation(valid_old,valid_features,labels,model,old['snapshots']['validation'],protocol)
        result['validation']={**evaluation,'elapsed_seconds':time.perf_counter()-evaluation_started}
        if resume:
            with np.load(work/'purchaser_metrics.npz') as saved:
                if not (np.array_equal(vectors,saved['metrics']) and np.array_equal(deltas,saved['paired_differences'])):
                    raise ValueError('Repeated validation metrics differ from original completed evaluation')
        else:np.savez_compressed(work/'purchaser_metrics.npz',metrics=vectors,paired_differences=deltas)
    finally:valid_old.close();valid_features.close()
    for split,layer in result['feature_layers'].items():
        if digest(root/layer['path'])!=layer['sha256']:raise ValueError('Frozen feature layer changed')
        if digest(root/f'data/ranking/phase10b1/{split}.duckdb')!=old['snapshots'][split]['input_database_sha256']:raise ValueError('Prior database changed')
    if digest(protocol_path)!=protocol_sha or digest(Path(__file__))!=code_sha:raise ValueError('Frozen experiment changed during execution')
    if resume and digest(work/'model.joblib')!=result['saved_model_sha256_before']:raise ValueError('Saved model was modified')
    result['local_artifacts']={str(p.relative_to(root)):digest(p) for p in [work/'model.joblib',work/'training_arrays.npz',work/'purchaser_metrics.npz',work/'experiment_freeze.json']}
    result['resources']={'elapsed_seconds':time.perf_counter()-started,'peak_process_rss':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'rss_units':'bytes on macOS; KiB on Linux','feature_database_bytes':feature_storage_bytes(root,result['feature_layers'])}
    dest=root/'docs/ranking/phase10b2b_summary.json'
    dest.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(f'Aggregate output: {dest.relative_to(root)}',flush=True)


if __name__=='__main__':main()
