"""Explicit IPW gain curves and targeting values; no individual effect labels."""
import hashlib
import math

import numpy as np


def validate(y, treatment, propensity):
    y=np.asarray(y,dtype=float);treatment=np.asarray(treatment,dtype=float)
    if y.ndim!=1 or y.shape!=treatment.shape or not len(y):
        raise ValueError('matching nonempty vectors required')
    if not np.isin(y,[0,1]).all() or not np.isin(treatment,[0,1]).all() or not 0<propensity<1:
        raise ValueError('binary outcomes/treatments and propensity in (0,1) required')
    return y,treatment


def ranking(scores, ids, seed):
    scores=np.asarray(scores,dtype=float)
    if scores.ndim!=1 or not np.isfinite(scores).all() or len(scores)!=len(ids) or len(set(ids))!=len(ids):
        raise ValueError('finite scores with unique IDs required')
    # Label/treatment-independent tie priorities; identical across models.
    tie=np.array([hashlib.sha256(f'{seed}:policy:{i}'.encode()).hexdigest() for i in ids])
    return np.lexsort((np.asarray(ids),tie,-scores))


def policy_mask(order, budget):
    if not 0<=budget<=1 or sorted(np.asarray(order).tolist())!=list(range(len(order))):
        raise ValueError('budget in [0,1], order a permutation')
    mask=np.zeros(len(order),dtype=float)
    mask[np.asarray(order)[:math.ceil(budget*len(order))]]=1
    return mask


def ipw_components(y, treatment, propensity=.5):
    y,t=validate(y,treatment,propensity)
    control=(1-t)*y/(1-propensity)
    return control,t*y/propensity-control


def policy_value(y,treatment,policy,propensity=.5):
    control,z=ipw_components(y,treatment,propensity)
    policy=np.asarray(policy,dtype=float)
    if policy.shape!=z.shape or not np.isfinite(policy).all() or np.any((policy<0)|(policy>1)):
        raise ValueError('policy probabilities in [0,1] required')
    return {'value':float(np.mean(control+policy*z)),
            'incremental_value':float(np.mean(policy*z)),
            'contact_fraction':float(np.mean(policy)),
            'incremental_per_1000':float(1000*np.mean(policy*z))}


def gain_curve(y,treatment,order,propensity=.5):
    _,z=ipw_components(y,treatment,propensity)
    if sorted(np.asarray(order).tolist())!=list(range(len(z))):
        raise ValueError('order must be a permutation')
    x=np.arange(len(z)+1)/len(z)
    gain=np.r_[0,np.cumsum(z[order])/len(z)]
    auuc=float(np.trapezoid(gain,x))
    # Population-normalized HT gain; not sklift's perfect-curve normalization.
    return x,gain,{'auuc':auuc,'qini_area':auuc-.5*float(gain[-1]),'all_contact_gain':float(gain[-1])}


def bootstrap_evaluation(y,treatment,orders,budgets=(.1,.2,.3),draws=500,seed=20261105,propensity=.5):
    """Paired treatment-stratified customer bootstrap, reselecting each top-k.

    Integer multiplicities avoid constructing repeated customer rows. Curves
    are integrated exactly across each original customer's weighted segment.
    """
    y,t=validate(y,treatment,propensity)
    control,z=ipw_components(y,t,propensity)
    n=len(y);arms=[np.flatnonzero(t==a) for a in (0,1)]
    if any(len(a)==0 for a in arms): raise ValueError('both arms needed')
    rng=np.random.default_rng(seed)
    result={}
    for name in orders:
        for metric in ['auuc','qini_area']:
            result[f'{name}/{metric}']=np.empty(draws)
        for budget in budgets:
            for metric in ['value','incremental_value']:
                result[f'{name}/{budget:.0%}/{metric}']=np.empty(draws)
    for name in ['none','all']:
        for metric in ['value','incremental_value']:
            result[f'{name}/{metric}']=np.empty(draws)
    for b in range(draws):
        weights=np.bincount(np.concatenate([rng.choice(a,len(a),replace=True) for a in arms]),minlength=n)
        base=float(np.dot(weights,control)/n);full=float(np.dot(weights,z)/n)
        result['none/value'][b]=base;result['none/incremental_value'][b]=0
        result['all/value'][b]=base+full;result['all/incremental_value'][b]=full
        for name,order in orders.items():
            w=weights[order];sz=z[order]
            xs=np.r_[0,np.cumsum(w)/n];g=np.r_[0,np.cumsum(w*sz)/n]
            area=float(np.trapezoid(g,xs))
            result[f'{name}/auuc'][b]=area
            result[f'{name}/qini_area'][b]=area-.5*full
            preceding=np.cumsum(w)-w
            for budget in budgets:
                selected=np.clip(math.ceil(budget*n)-preceding,0,w)
                incremental=float(np.dot(selected,sz)/n)
                result[f'{name}/{budget:.0%}/incremental_value'][b]=incremental
                result[f'{name}/{budget:.0%}/value'][b]=base+incremental
    return result


def interval(draws):
    return np.quantile(draws,[.025,.975]).tolist()
