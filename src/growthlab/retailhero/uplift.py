"""Fixed, modest uplift benchmarks; validation only, final-test loader denied."""
import argparse
import json
import platform
import resource
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import joblib
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score, average_precision_score
from threadpoolctl import threadpool_limits

from .acquire import sha256
from .experiment import experiment_statistics, quote, verify_inputs, verify_split, write_json
from .history import FEATURE_COLUMNS
from .uplift_metrics import (bootstrap_evaluation, gain_curve, interval, policy_mask,
                             policy_value, ranking)


def read_labels(path, allowed):
    """Parse outcomes only AFTER an ID is found in the permitted cohort.

    The source IDs/headers have already been verified in Phase 5. Final-test
    lines are traversed as bytes/text but their target field is never parsed.
    """
    labels={}
    with Path(path).open() as f:
        if f.readline().strip()!='client_id,treatment_flg,target':
            raise ValueError('unexpected label header')
        for line in f:
            client,_,rest=line.partition(',')
            if client not in allowed:
                continue
            if client in labels: raise ValueError('duplicate permitted label')
            t,y=map(int,rest.strip().split(','))
            if t not in (0,1) or y not in (0,1): raise ValueError('invalid development label')
            labels[client]=(t,y)
    if set(labels)!=set(allowed): raise ValueError('incomplete permitted labels')
    return labels


def load_cohort(root,cohort):
    if cohort not in ('train','validation'):
        raise ValueError('final holdout access is forbidden in Phase 6')
    docs=root/'docs/causal/phase6'
    features=json.loads((docs/'feature_summary.json').read_text())
    split=json.loads((root/'docs/causal/phase5/split_manifest.json').read_text())
    verify_split(root,split,verify_inputs(root))
    if features['features']!=list(FEATURE_COLUMNS) or features['split_sha256']!=split['sha256']:
        raise ValueError('feature specification/split mismatch')
    if sha256(root/features['feature_path'])!=features['feature_sha256']:
        raise ValueError('feature table changed')
    con=duckdb.connect()
    con.execute("SET memory_limit='256MB'")
    cols=','.join(FEATURE_COLUMNS)
    try:
        # Select only the explicitly permitted cohort; no final-test features fetched.
        data=con.execute(f"SELECT client_id,treatment_flg,{cols} FROM read_parquet({quote(root/features['feature_path'])}) WHERE split=? ORDER BY client_id",[cohort]).fetchnumpy()
    finally:
        con.close()
    ids=data['client_id'];t=data['treatment_flg'].astype(int)
    labels=read_labels(root/'data/retailhero/raw/uplift_train.csv',set(ids))
    y=np.array([labels[i][1] for i in ids],dtype=int)
    if not np.array_equal(t,np.array([labels[i][0] for i in ids])):
        raise ValueError('label/split treatment mismatch')
    expected=sum(r['n'] for r in split['counts'] if r['split']==cohort)
    if len(ids)!=expected or len(set(ids))!=len(ids): raise ValueError('cohort join/count mismatch')
    arrays=[]
    for name in FEATURE_COLUMNS:
        a=data[name]
        arrays.append(np.ma.filled(a.astype(float),np.nan))
    X=np.column_stack(arrays)
    if np.isinf(X).any() or np.any(X[np.isfinite(X)]<0): raise ValueError('invalid feature values')
    return ids,X,t,y


def fit_models(X,t,y,params,factory=HistGradientBoostingClassifier):
    if X.shape[1]!=len(FEATURE_COLUMNS) or len(X)!=len(t) or len(t)!=len(y):
        raise ValueError('training dimensions invalid')
    result={}
    for name,xx,yy in [('response',X,y),('s_learner',np.column_stack([X,t]),y),
                       ('t_control',X[t==0],y[t==0]),('t_treated',X[t==1],y[t==1])]:
        result[name]=factory(**params).fit(xx,yy)
    result['constant']=float(y[t==1].mean()-y[t==0].mean())
    return result


def predict_models(models,X):
    response=models['response'].predict_proba(X)[:,1]
    s1=models['s_learner'].predict_proba(np.column_stack([X,np.ones(len(X))]))[:,1]
    s0=models['s_learner'].predict_proba(np.column_stack([X,np.zeros(len(X))]))[:,1]
    t1=models['t_treated'].predict_proba(X)[:,1]
    t0=models['t_control'].predict_proba(X)[:,1]
    scores={'constant':np.full(len(X),models['constant']), 'response':response,
            's_learner':s1-s0,'t_learner':t1-t0}
    if any(not np.isfinite(a).all() for a in scores.values()) or any(np.any(np.abs(scores[n])>1) for n in ['s_learner','t_learner']):
        raise ValueError('invalid uplift predictions')
    return scores,{'s_treated':s1,'s_control':s0,'t_treated':t1,'t_control':t0}


def train(root=Path('.')):
    started=time.perf_counter();docs=root/'docs/causal/phase6'
    receipt=docs/'training_receipt.json'
    if receipt.exists(): raise FileExistsError('models already fitted; verify saved artifacts instead of silently replacing')
    plan_path=docs/'validation_plan.json';plan=json.loads(plan_path.read_text())
    params={k:v for k,v in plan['learner'].items() if k!='class'}
    ids,X,t,y=load_cohort(root,'train')
    with threadpool_limits(limits=1):
        models=fit_models(X,t,y,params)
    dest=root/'data/retailhero/phase6/models';dest.mkdir(parents=True,exist_ok=True)
    path=dest/'uplift_models.joblib';joblib.dump(models,path)
    features=json.loads((docs/'feature_summary.json').read_text())
    result={'trained_at_utc':datetime.now(timezone.utc).isoformat(),'plan_sha256':sha256(plan_path),
            'feature_sha256':features['feature_sha256'],'feature_names':list(FEATURE_COLUMNS),
            'model_path':str(path.relative_to(root)),'model_sha256':sha256(path),
            'train_n':len(ids),'train_control':int((t==0).sum()),'train_treated':int((t==1).sum()),
            'constant_uplift':models['constant'],'fit_counts':{'response':len(y),'s_learner':len(y),'t_control':int((t==0).sum()),'t_treated':int((t==1).sum())},
            'iterations':{k:int(models[k].n_iter_) for k in ['response','s_learner','t_control','t_treated']},
            'preprocessing':'Native train-fitted histogram bins and native missing handling; no data-fitted preprocessing outside training.',
            'versions':{'python':platform.python_version(),'sklearn':sklearn.__version__,'numpy':np.__version__,'duckdb':duckdb.__version__},
            'resources':{'elapsed_seconds':time.perf_counter()-started,'threads':1,'process_maxrss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if platform.system()=='Darwin' else 1024)},
            'source_sha256':{str(p.relative_to(root)):sha256(p) for p in (root/'src/growthlab/retailhero').glob('*.py')}}
    write_json(receipt,result)
    return result


def verify_models(root):
    docs=root/'docs/causal/phase6';r=json.loads((docs/'training_receipt.json').read_text())
    if sha256(docs/'validation_plan.json')!=r['plan_sha256'] or sha256(root/r['model_path'])!=r['model_sha256']:
        raise ValueError('training plan/model changed')
    if json.loads((docs/'feature_summary.json').read_text())['feature_sha256']!=r['feature_sha256']:
        raise ValueError('training features changed')
    return r


def evaluate(root=Path('.')):
    started=time.perf_counter();docs=root/'docs/causal/phase6'
    if (docs/'validation_summary.json').exists(): raise FileExistsError('validation results exist; use --verify')
    r=verify_models(root);plan=json.loads((docs/'validation_plan.json').read_text())
    ids,X,t,y=load_cohort(root,'validation')
    with threadpool_limits(limits=1):
        models=joblib.load(root/r['model_path']);scores,predictions=predict_models(models,X)
        orders={n:ranking(a,ids,plan['seed']) for n,a in scores.items()}
        curves={};metrics={};policies={}
        p=plan['propensity_primary'];budgets=plan['budgets']
        for name,order in orders.items():
            x,g,m=gain_curve(y,t,order,p);curves[name]=(x,g);metrics[name]=m
            metrics[name]['score_summary']={key:float(value) for key,value in zip(['min','p25','median','p75','max'],np.quantile(scores[name],[0,.25,.5,.75,1]))}
            for budget in budgets:
                mask=policy_mask(order,budget);selected=mask.astype(bool)
                k=f'{name}/{budget:.0%}'
                policies[k]=policy_value(y,t,mask,p)
                policies[k]['selected_n']=int(selected.sum())
                nt=int((selected&(t==1)).sum());nc=int((selected&(t==0)).sum())
                yt=int(y[selected&(t==1)].sum());yc=int(y[selected&(t==0)].sum())
                policies[k]['selected_group_comparison']=experiment_statistics(yt,nt,yc,nc)
        policies['none']=policy_value(y,t,np.zeros(len(y)),p);policies['none']['selected_n']=0
        policies['all']=policy_value(y,t,np.ones(len(y)),p);policies['all']['selected_n']=len(y)
        draws=bootstrap_evaluation(y,t,orders,tuple(budgets),draws=500,seed=20261106,propensity=p)
        for name in metrics:
            for metric in ['auuc','qini_area']:
                metrics[name][metric+'_ci95']=interval(draws[f'{name}/{metric}'])
        for k,row in policies.items():
            for metric in ['value','incremental_value']:
                row[metric+'_ci95']=interval(draws[f'{k}/{metric}'])
        paired={}
        for candidate in ['s_learner','t_learner','response']:
            for reference in ['constant','response']:
                if candidate==reference: continue
                for budget in budgets:
                    a=f'{candidate}/{budget:.0%}';b=f'{reference}/{budget:.0%}'
                    paired[f'{a} minus {b}']={'incremental_difference':policies[a]['incremental_value']-policies[b]['incremental_value'],
                        'ci95':interval(draws[f'{a}/incremental_value']-draws[f'{b}/incremental_value'])}
        best=max(['s_learner','t_learner'],key=lambda n:policies[f'{n}/30%']['incremental_value'])
        convincing=all(paired[f'{best}/30% minus {ref}/30%']['ci95'][0]>0 for ref in ['constant','response'])
        recommendation={'best_exploratory_uplift_model':best,'recommended_ranking':best if convincing else 'constant',
                        'budget':.3,'uplift_improvement_over_both_baselines_ci_excludes_zero':convincing,
                        'status':'Provisional validation selection; requires user review and separate Phase 7 freeze. 30% is a comparison budget, not economic optimization.'}
        sensitivity={}
        for ep in plan['propensity_sensitivity']+[float(t.mean())]:
            sensitivity[str(ep)]={}
            for name,order in orders.items():
                sensitivity[str(ep)][name]=policy_value(y,t,policy_mask(order,.3),ep)
        cost_sensitivity={k:{str(cost):v['incremental_value']-cost*v['contact_fraction'] for cost in [0,.005,.01,.02]} for k,v in policies.items()}
        dest=root/'data/retailhero/phase6';dest.mkdir(parents=True,exist_ok=True)
        predictions_path=dest/'validation_predictions.npz'
        np.savez_compressed(predictions_path,client_id=ids.astype(str),treatment=t,target=y,**scores,**predictions)
        boot_path=dest/'bootstrap_draws.npz';np.savez_compressed(boot_path,**draws)
        make_plots(docs,curves,metrics,policies,paired)
        result={'evaluated_at_utc':datetime.now(timezone.utc).isoformat(),'cohort':'validation','n':len(y),
                'treatment_n':int((t==1).sum()),'control_n':int((t==0).sum()),
                'treated_purchasers':int(y[t==1].sum()),'control_purchasers':int(y[t==0].sum()),
                'plan_sha256':r['plan_sha256'],'training_receipt_sha256':sha256(docs/'training_receipt.json'),
                'assumed_propensity':p,'metrics':metrics,'policies':policies,'paired_policy_differences':paired,
                'recommendation':recommendation,'propensity_sensitivity_30pct':sensitivity,
                'hypothetical_purchase_equivalent_penalties':cost_sensitivity,
                'response_classification':{'roc_auc':float(roc_auc_score(y,scores['response'])),'average_precision':float(average_precision_score(y,scores['response']))},
                'artifacts':{str(path.relative_to(root)):sha256(path) for path in [predictions_path,boot_path]},
                'figures':{str(path.relative_to(root)):sha256(path) for path in (docs/'figures').glob('*.png')},
                'bootstrap':{'draws':500,'seed':20261106,'design':'Paired, treatment-stratified customer resampling, exact budget reselection; fixed fitted models; percentile 95% intervals; no multiplicity adjustment.'},
                'resources':{'elapsed_seconds':time.perf_counter()-started,'threads':1,'process_maxrss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if platform.system()=='Darwin' else 1024)},
                'final_holdout_accessed':False}
        write_json(docs/'validation_summary.json',result)
        return result


def make_plots(docs,curves,metrics,policies,paired):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    dest=docs/'figures';dest.mkdir(parents=True,exist_ok=True)
    fig,axes=plt.subplots(1,2,figsize=(11,4))
    for name,(x,g) in curves.items():
        # Downsample only for plotting; metrics integrate every customer.
        at=np.unique(np.r_[np.arange(0,len(x),100),len(x)-1])
        axes[0].plot(x[at],1000*g[at],label=name)
        axes[1].plot(x[at],1000*(g-x*g[-1])[at],label=name)
    x,g=next(iter(curves.values()))
    axes[0].plot([0,1],[0,1000*g[-1]],'k--',label='random expectation')
    axes[1].axhline(0,color='black',linestyle='--')
    for ax in axes:
        ax.set_xlabel('Fraction contacted');ax.legend(fontsize=8);ax.grid(alpha=.2)
    axes[0].set_ylabel('IPW incremental purchasers / 1,000 population')
    axes[1].set_ylabel('Gain above random expectation / 1,000')
    fig.suptitle('Validation only; assumed random assignment e=0.5')
    fig.tight_layout();fig.savefig(dest/'uplift_qini.png',dpi=150);plt.close(fig)
    fig,ax=plt.subplots(figsize=(8,4))
    for i,name in enumerate(['constant','response','s_learner','t_learner']):
        rows=[policies[f'{name}/{b}%'] for b in [10,20,30]]
        yy=np.array([r['incremental_value'] for r in rows])*1000
        lo=np.array([r['incremental_value_ci95'][0] for r in rows])*1000
        hi=np.array([r['incremental_value_ci95'][1] for r in rows])*1000
        ax.errorbar(np.array([10,20,30])+(i-1.5)*.6,yy,yerr=[yy-lo,hi-yy],fmt='o-',label=name,capsize=3)
    ax.axhline(0,color='black',linestyle='--');ax.set_xlabel('Contact budget (%)')
    ax.set_ylabel('Incremental purchasers / 1,000 population')
    ax.set_title('Validation IPW policy estimates; paired stratified bootstrap 95% intervals')
    ax.legend();ax.grid(alpha=.2);fig.tight_layout();fig.savefig(dest/'policy_value.png',dpi=150);plt.close(fig)


def verify(root=Path('.')):
    docs=root/'docs/causal/phase6';r=verify_models(root)
    s=json.loads((docs/'validation_summary.json').read_text())
    if s['training_receipt_sha256']!=sha256(docs/'training_receipt.json'):
        raise ValueError('training receipt changed')
    for name,digest in {**s['artifacts'],**s['figures']}.items():
        if sha256(root/name)!=digest: raise ValueError('validation artifact changed')
    path=root/'data/retailhero/phase6/validation_predictions.npz'
    with np.load(path) as saved:
        y=saved['target'];t=saved['treatment'];ids=saved['client_id']
        for name in ['constant','response','s_learner','t_learner']:
            order=ranking(saved[name],ids,20261105)
            _,_,m=gain_curve(y,t,order)
            if any(not np.isclose(m[k],s['metrics'][name][k],rtol=0,atol=1e-14) for k in m):
                raise ValueError('saved ranking metrics disagree')
            for budget in [.1,.2,.3]:
                value=policy_value(y,t,policy_mask(order,budget))
                row=s['policies'][f'{name}/{budget:.0%}']
                if any(not np.isclose(value[k],row[k],rtol=0,atol=1e-14) for k in value):
                    raise ValueError('saved policy values disagree')
    return {'verified':True,'n':s['n'],'final_holdout_accessed':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--train',action='store_true');mode.add_argument('--evaluate',action='store_true');mode.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    print(json.dumps(train() if args.train else evaluate() if args.evaluate else verify(),indent=2))
