"""One-use frozen RetailHero final evaluation; verification never reloads labels."""
import argparse
import hashlib
import json
import os
import platform
import resource
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import duckdb
import joblib
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from threadpoolctl import threadpool_limits

from .acquire import sha256
from .experiment import experiment_statistics, quote, write_json
from .history import FEATURE_COLUMNS
from .uplift import predict_models, read_labels, verify_models
from .uplift_metrics import bootstrap_evaluation, gain_curve, interval, policy_mask, policy_value, ranking

PHASE6_COMMIT = 'ce0c851d58e5c9c783ce841f61f5851bf85423b0'
CONFIG = {'ranking_seed': 20261105, 'bootstrap_seed': 20261106, 'bootstrap_draws': 500,
          'budgets': [.1, .2, .3], 'propensity': .5, 'sensitivity': [.45, .55],
          'primary_challenger': 's_learner', 'primary_reference': 'constant', 'primary_budget': .3}


def now():
    return datetime.now(timezone.utc).isoformat()


def exclusive_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as out:
        out.write(json.dumps(value, indent=2, allow_nan=False)+'\n')


def membership_metadata(con, split_path, feature_path):
    """IDs, arms and features only: no outcome source is opened."""
    s, f = quote(split_path), quote(feature_path)
    if con.execute(f'SELECT count(*),count(DISTINCT client_id) FROM read_parquet({s})').fetchone() != (200039, 200039):
        raise ValueError('split membership is not unique/complete')
    if con.execute(f'SELECT count(*),count(DISTINCT client_id) FROM read_parquet({f})').fetchone() != (200039, 200039):
        raise ValueError('feature membership is not unique/complete')
    mismatches = con.execute(f'''SELECT count(*) FROM read_parquet({s}) s FULL OUTER JOIN
        read_parquet({f}) f USING(client_id) WHERE s.client_id IS NULL OR f.client_id IS NULL
        OR s.split!=f.split OR s.treatment_flg!=f.treatment_flg''').fetchone()[0]
    if mismatches:
        raise ValueError('frozen split/feature assignment mismatch')
    counts = con.execute(f'SELECT split,treatment_flg,count(*) FROM read_parquet({s}) GROUP BY 1,2 ORDER BY 1,2').fetchall()
    expected = [('final_test',0,20012),('final_test',1,19997),('train',0,60034),
                ('train',1,59988),('validation',0,20012),('validation',1,19996)]
    if counts != expected:
        raise ValueError('unexpected frozen split counts')
    rows = con.execute(f"SELECT client_id,treatment_flg FROM read_parquet({s}) WHERE split='final_test' ORDER BY client_id").fetchall()
    digest = hashlib.sha256('\n'.join(f'{i}:{t}' for i,t in rows).encode()).hexdigest()
    return {'n':len(rows), 'control_n':20012, 'treated_n':19997,
            'sorted_final_id_treatment_sha256':digest,
            'split_counts':[{'split':a,'treatment_flg':b,'n':c} for a,b,c in counts]}


def metadata(root):
    features = json.loads((root/'docs/causal/phase6/feature_summary.json').read_text())
    split = json.loads((root/'docs/causal/phase5/split_manifest.json').read_text())
    if features['features'] != list(FEATURE_COLUMNS) or features['split_sha256'] != split['sha256']:
        raise ValueError('feature allowlist/split mismatch')
    con = duckdb.connect()
    con.execute("SET memory_limit='256MB'")
    con.execute('SET threads=1')
    try:
        return membership_metadata(con, root/split['path'], root/features['feature_path'])
    finally:
        con.close()


def prepare(root=Path('.')):
    docs = root/'docs/causal/phase7'
    if (docs/'frozen_protocol.json').exists():
        raise FileExistsError('protocol already frozen; use --verify')
    head = subprocess.check_output(['git','rev-parse','HEAD'], cwd=root).decode().strip()
    if head != PHASE6_COMMIT:
        raise ValueError('expected approved Phase 6 baseline commit')
    r = verify_models(root)
    versions={'python':platform.python_version(),'sklearn':sklearn.__version__,
              'numpy':np.__version__,'duckdb':duckdb.__version__}
    if versions!=r['versions']:
        raise ValueError('Phase 6 fitting dependency versions changed')
    for path,digest in r['source_sha256'].items():
        if sha256(root/path) != digest:
            raise ValueError('Phase 6 training source changed')
    inputs = {}
    for folder in ['docs/causal/phase5','docs/causal/phase6','src/growthlab/retailhero']:
        for path in sorted((root/folder).glob('*')):
            if path.is_file(): inputs[str(path.relative_to(root))] = sha256(path)
    for name in ['docs/causal/phase5_experiment_analysis.md','docs/causal/phase6_uplift_modeling.md',
                 'docs/causal/phase7_frozen_protocol.md','tests/test_retailhero_final_evaluation.py',
                 'requirements-causal.lock']:
        inputs[name] = sha256(root/name)
    acquisition = json.loads((root/'docs/causal/phase5/acquisition.json').read_text())
    for entry in acquisition['files']:
        inputs[entry['path']] = entry['sha256']
    history = json.loads((root/'docs/causal/phase6/history_acquisition.json').read_text())
    inputs[history['path']] = history['sha256']
    split = json.loads((root/'docs/causal/phase5/split_manifest.json').read_text())
    features = json.loads((root/'docs/causal/phase6/feature_summary.json').read_text())
    inputs[split['path']] = split['sha256']
    inputs[features['feature_path']] = features['feature_sha256']
    inputs[r['model_path']] = r['model_sha256']
    validation = json.loads((root/'docs/causal/phase6/validation_summary.json').read_text())
    inputs.update(validation['artifacts']); inputs.update(validation['figures'])
    for path,digest in inputs.items():
        if sha256(root/path) != digest: raise ValueError('frozen input mismatch: '+path)
    cohort = metadata(root)
    states = {str(p.relative_to(root)):[p.stat().st_size,p.stat().st_mtime_ns]
              for p in (root/'data').rglob('*') if p.is_file() and 'phase7' not in p.parts}
    local = root/'data/retailhero/phase7'
    exclusive_json(local/'prior_file_states.json', states)
    inputs[str((local/'prior_file_states.json').relative_to(root))] = sha256(local/'prior_file_states.json')
    protocol = {'frozen_at_utc':now(), 'baseline_commit':head,
                'human_protocol':'docs/causal/phase7_frozen_protocol.md', 'config':CONFIG,
                'cohort':cohort, 'feature_names':list(FEATURE_COLUMNS), 'inputs_sha256':inputs, 'versions':versions,
                'final_outcomes_accessed':False}
    exclusive_json(docs/'frozen_protocol.json', protocol)
    exclusive_json(docs/'readiness_receipt.json', {'ready_at_utc':now(),
        'protocol_sha256':sha256(docs/'frozen_protocol.json'), 'cohort':cohort,
        'final_outcomes_accessed':False})
    return protocol


def verify_freeze(root):
    docs = root/'docs/causal/phase7'
    protocol = json.loads((docs/'frozen_protocol.json').read_text())
    ready = json.loads((docs/'readiness_receipt.json').read_text())
    if ready['protocol_sha256'] != sha256(docs/'frozen_protocol.json') or protocol['config'] != CONFIG:
        raise ValueError('frozen protocol changed')
    if protocol['versions']!={'python':platform.python_version(),'sklearn':sklearn.__version__,
                             'numpy':np.__version__,'duckdb':duckdb.__version__}:
        raise ValueError('frozen dependency versions changed')
    for path,digest in protocol['inputs_sha256'].items():
        if sha256(root/path) != digest: raise ValueError('frozen input changed: '+path)
    if metadata(root) != protocol['cohort']:
        raise ValueError('final membership changed')
    return protocol


def check_prior_states(root):
    prior = json.loads((root/'data/retailhero/phase7/prior_file_states.json').read_text())
    for path,state in prior.items():
        p = root/path
        if not p.exists() or [p.stat().st_size,p.stat().st_mtime_ns] != state:
            raise ValueError('prior data/artifact file changed: '+path)
    return len(prior)


def load_final_features(root):
    features = json.loads((root/'docs/causal/phase6/feature_summary.json').read_text())
    con = duckdb.connect()
    con.execute("SET memory_limit='256MB'"); con.execute('SET threads=1')
    try:
        data = con.execute(f"SELECT client_id,treatment_flg,{','.join(FEATURE_COLUMNS)} FROM read_parquet({quote(root/features['feature_path'])}) WHERE split='final_test' ORDER BY client_id").fetchnumpy()
    finally:
        con.close()
    ids = data['client_id'].astype(str); t = data['treatment_flg'].astype(int)
    X = np.column_stack([np.ma.filled(data[c].astype(float),np.nan) for c in FEATURE_COLUMNS])
    if len(ids) != 40009 or len(set(ids)) != len(ids) or np.isinf(X).any():
        raise ValueError('invalid final feature cohort')
    return ids,X,t


def claim_access(path, protocol_digest):
    exclusive_json(path, {'first_access_at_utc':now(),'protocol_sha256':protocol_digest,
                          'scope':'One final cohort label extraction and frozen model evaluation'})


def predict_without_fit(models, X):
    with patch.object(HistGradientBoostingClassifier, 'fit', side_effect=RuntimeError('refitting forbidden')):
        return predict_models(models,X)


def calculate(ids, t, y, scores, config=CONFIG):
    """Pure calculation on supplied cohort: unchanged Phase 6 estimators."""
    budgets = config['budgets']; propensity = config['propensity']
    orders = {name:ranking(score,ids,config['ranking_seed']) for name,score in scores.items()}
    metrics = {}; curves = {}; policies = {}
    for name,order in orders.items():
        x,g,m = gain_curve(y,t,order,propensity); curves[name]=(x,g); metrics[name]=m
        for budget in budgets:
            mask=policy_mask(order,budget); row=policy_value(y,t,mask,propensity)
            row['selected_n']=int(mask.sum()); policies[f'{name}/{budget:.0%}']=row
    for name,mask in [('none',np.zeros(len(y))),('all',np.ones(len(y)))]:
        policies[name]=policy_value(y,t,mask,propensity)
        policies[name]['selected_n']=int(mask.sum())
    draws=bootstrap_evaluation(y,t,orders,tuple(budgets),draws=config['bootstrap_draws'],
                               seed=config['bootstrap_seed'],propensity=propensity)
    for name,row in metrics.items():
        for metric in ['auuc','qini_area']:
            row[metric+'_ci95']=interval(draws[f'{name}/{metric}'])
    for name,row in policies.items():
        for metric in ['value','incremental_value']:
            row[metric+'_ci95']=interval(draws[f'{name}/{metric}'])
    pairs={}
    for a,b in [('s_learner','constant'),('s_learner','response'),('s_learner','t_learner'),
                ('t_learner','constant'),('t_learner','response'),('response','constant')]:
        for budget in budgets:
            aa=f'{a}/{budget:.0%}'; bb=f'{b}/{budget:.0%}'
            pairs[f'{aa} minus {bb}'] = paired_result(aa,bb,policies,draws)
    for budget in budgets:
        for reference in ['none','all']:
            a=f's_learner/{budget:.0%}'
            pairs[f'{a} minus {reference}']=paired_result(a,reference,policies,draws)
    primary_key='s_learner/30% minus constant/30%'
    primary={**pairs[primary_key],'comparison':primary_key,
             'numerical_advantage':pairs[primary_key]['difference']>0,
             'ci_excludes_zero_in_favor_of_s':pairs[primary_key]['ci95'][0]>0}
    paired_curves={}
    for a,b in [('s_learner','constant'),('s_learner','response'),('s_learner','t_learner'),('t_learner','constant')]:
        paired_curves[f'{a} minus {b}']={'auuc_difference':metrics[a]['auuc']-metrics[b]['auuc'],
            'ci95':interval(draws[f'{a}/auuc']-draws[f'{b}/auuc'])}
    sensitivity={}
    for e in [*config['sensitivity'],float(np.mean(t))]:
        sensitivity[str(e)]={}
        for name,order in orders.items():
            for budget in budgets:
                sensitivity[str(e)][f'{name}/{budget:.0%}']=policy_value(y,t,policy_mask(order,budget),e)
        sensitivity[str(e)]['all']=policy_value(y,t,np.ones(len(y)),e)
        sensitivity[str(e)]['none']=policy_value(y,t,np.zeros(len(y)),e)
    group=experiment_statistics(int(y[t==1].sum()),int((t==1).sum()),int(y[t==0].sum()),int((t==0).sum()))
    result={'n':len(y),'metrics':metrics,'policies':policies,'paired_policy_differences':pairs,
            'primary':primary,'paired_curve_comparisons':paired_curves,
            'propensity_sensitivity':sensitivity,'observed_group_difference':group}
    return result,draws,curves


def paired_result(a,b,policies,draws):
    difference=policies[a]['incremental_value']-policies[b]['incremental_value']
    ci=interval(draws[f'{a}/incremental_value']-draws[f'{b}/incremental_value'])
    return {'difference':difference,'difference_per_1000':1000*difference,
            'ci95':ci,'ci95_per_1000':[1000*v for v in ci]}


def plots(root, curves, policies):
    dest=root/'docs/causal/phase7/figures'; dest.mkdir(parents=True,exist_ok=True)
    os.environ.setdefault('MPLCONFIGDIR',str((root/'data/retailhero/phase7/matplotlib').resolve()))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(11,4))
    for name,(x,g) in curves.items():
        at=np.unique(np.r_[np.arange(0,len(x),100),len(x)-1])
        axes[0].plot(x[at],1000*g[at],label=name)
        axes[1].plot(x[at],1000*(g-x*g[-1])[at],label=name)
    x,g=next(iter(curves.values()))
    axes[0].plot([0,1],[0,1000*g[-1]],'k--',label='random expectation')
    axes[1].axhline(0,color='black',linestyle='--')
    for ax in axes:
        ax.set_xlabel('Fraction contacted'); ax.legend(fontsize=8); ax.grid(alpha=.2)
    axes[0].set_ylabel('IPW incremental purchasers / 1,000 population')
    axes[1].set_ylabel('Gain above random expectation / 1,000')
    fig.suptitle('Final holdout; assumed random assignment e=0.5')
    fig.tight_layout(); fig.savefig(dest/'uplift_qini.png',dpi=150); plt.close(fig)
    fig,ax=plt.subplots(figsize=(8,4))
    for i,name in enumerate(['constant','response','s_learner','t_learner']):
        rows=[policies[f'{name}/{b}%'] for b in [10,20,30]]
        yy=np.array([r['incremental_per_1000'] for r in rows])
        lo=np.array([r['incremental_value_ci95'][0]*1000 for r in rows])
        hi=np.array([r['incremental_value_ci95'][1]*1000 for r in rows])
        xx=np.array([10,20,30])+(i-1.5)*.6
        line,=ax.plot(xx,yy,'o-',label=name)
        ax.vlines(xx,lo,hi,color=line.get_color())
        ax.hlines(lo,xx-.15,xx+.15,color=line.get_color())
        ax.hlines(hi,xx-.15,xx+.15,color=line.get_color())
    ax.axhline(0,color='black',linestyle='--'); ax.set_xlabel('Contact budget (%)')
    ax.set_ylabel('Incremental purchasers / 1,000 population')
    ax.set_title('Final holdout: 95% paired stratified-bootstrap intervals')
    ax.legend(); ax.grid(alpha=.2); fig.tight_layout(); fig.savefig(dest/'policy_value.png',dpi=150); plt.close(fig)


def evaluate(root=Path('.')):
    started=time.perf_counter(); docs=root/'docs/causal/phase7'; local=root/'data/retailhero/phase7'
    protocol=verify_freeze(root)
    if (local/'final_access_ledger.json').exists():
        raise FileExistsError('final evaluation already claimed; use --verify, never delete the ledger')
    ids,X,t=load_final_features(root)
    claim_access(local/'final_access_ledger.json',sha256(docs/'frozen_protocol.json'))
    labels=read_labels(root/'data/retailhero/raw/uplift_train.csv',set(ids))
    if not np.array_equal(t,np.array([labels[i][0] for i in ids])):
        raise ValueError('final treatment alignment failure')
    y=np.array([labels[i][1] for i in ids],dtype=int)
    r=json.loads((root/'docs/causal/phase6/training_receipt.json').read_text())
    with threadpool_limits(limits=1):
        scores,probabilities=predict_without_fit(joblib.load(root/r['model_path']),X)
        prediction_path=local/'final_predictions.npz'
        np.savez_compressed(prediction_path,client_id=ids,treatment=t,target=y,**scores,**probabilities)
        result,draws,curves=calculate(ids,t,y,scores,protocol['config'])
        draw_path=local/'bootstrap_draws.npz'; np.savez_compressed(draw_path,**draws)
        plots(root,curves,result['policies'])
    verify_freeze(root); prior_n=check_prior_states(root)
    result.update({'completed_at_utc':now(),'cohort':'final_test','protocol_sha256':sha256(docs/'frozen_protocol.json'),
        'artifacts':{str(p.relative_to(root)):sha256(p) for p in [prediction_path,draw_path,local/'final_access_ledger.json']},
        'figures':{str(p.relative_to(root)):sha256(p) for p in (docs/'figures').glob('*.png')},
        'prior_file_states_unchanged':prior_n,'no_refitting':True,
        'resources':{'elapsed_seconds':time.perf_counter()-started,'threads':1,'duckdb_memory_limit':'256MB',
                     'process_maxrss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if platform.system()=='Darwin' else 1024)}})
    exclusive_json(docs/'final_summary.json',result)
    return result


def verify(root=Path('.')):
    protocol=verify_freeze(root); docs=root/'docs/causal/phase7'; local=root/'data/retailhero/phase7'
    summary=json.loads((docs/'final_summary.json').read_text())
    if summary['protocol_sha256']!=sha256(docs/'frozen_protocol.json'):
        raise ValueError('result protocol mismatch')
    for name,digest in {**summary['artifacts'],**summary['figures']}.items():
        if sha256(root/name)!=digest: raise ValueError('saved final artifact changed: '+name)
    with np.load(local/'final_predictions.npz') as saved, threadpool_limits(limits=1):
        scores={name:saved[name] for name in ['constant','response','s_learner','t_learner']}
        result,draws,_=calculate(saved['client_id'],saved['treatment'],saved['target'],scores,protocol['config'])
    for key,value in result.items():
        if value!=summary[key]: raise ValueError('saved final statistics differ: '+key)
    with np.load(local/'bootstrap_draws.npz') as saved:
        for name,values in draws.items(): np.testing.assert_array_equal(values,saved[name])
    count=check_prior_states(root)
    ready=json.loads((docs/'readiness_receipt.json').read_text())
    ledger=json.loads((local/'final_access_ledger.json').read_text())
    if not protocol['frozen_at_utc']<=ready['ready_at_utc']<ledger['first_access_at_utc']<summary['completed_at_utc']:
        raise ValueError('invalid freeze/access chronology')
    result={'verified_at_utc':now(),'protocol_sha256':summary['protocol_sha256'],
            'final_summary_sha256':sha256(docs/'final_summary.json'),'n':summary['n'],
            'all_final_statistics_identical':True,'all_500_paired_bootstrap_draws_identical':True,
            'prior_file_states_unchanged':count,'no_refitting_or_new_outcome_access':True}
    write_json(docs/'verification.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    for name in ['prepare','evaluate','verify']: mode.add_argument('--'+name,action='store_true')
    args=parser.parse_args()
    print(json.dumps(prepare() if args.prepare else evaluate() if args.evaluate else verify(),indent=2))
