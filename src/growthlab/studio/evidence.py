"""Strict, repository-relative allowlist for the public aggregate-only app."""
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = 'docs/decision_studio/evidence_manifest.json'


class EvidenceError(ValueError):
    """An actionable evidence-loading error, safe to display in the app."""


def read_json(path):
    try:
        return json.loads(path.read_text(),parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (OSError,UnicodeError,ValueError) as error:
        raise EvidenceError(f'Cannot read valid aggregate evidence: {path.name}. Restore the committed file.') from error


def at(value, path):
    for key in path:value=value[key]
    return value


def manifest_entry(name,root=ROOT):
    manifest=read_json(root/MANIFEST)
    try:
        entry=manifest['sources'][name]
        if not isinstance(entry['path'],str) or not isinstance(entry['sha256'],str) or not isinstance(entry['required_paths'],list):raise TypeError('bad manifest')
    except (KeyError,TypeError) as error:raise EvidenceError(f'Unknown evidence source: {name}') from error
    return entry


def load_evidence(name, root=ROOT):
    entry=manifest_entry(name,root)
    path=(root/entry['path']).resolve()
    if not path.is_relative_to((root/'docs').resolve()) or path.suffix!='.json':
        raise EvidenceError('Evidence must be an allowlisted aggregate JSON under docs/.')
    value=read_json(path)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:
        raise EvidenceError(f'Aggregate fingerprint mismatch: {entry["path"]}. Restore the committed evidence; do not regenerate outcomes.')
    try:
        for field in entry['required_paths']:at(value,field)
        for field in entry.get('numeric_paths',[]):
            number=at(value,field)
            if isinstance(number,bool) or not isinstance(number,(float,int)) or not math.isfinite(number):raise ValueError('invalid number')
    except (KeyError,TypeError,IndexError,ValueError) as error:
        raise EvidenceError(f'Malformed aggregate structure: {entry["path"]}. Expected verified fields are missing or invalid.') from error
    return value


def source_path(name, root=ROOT):
    return manifest_entry(name,root)['path']


MODEL_NAMES={'dummy':'Training-prior dummy','logistic_regression':'Logistic Regression',
             'xgboost':'XGBoost','xgboost_calibrated':'XGBoost · calibrated'}
POLICY_NAMES={'constant':'Fixed-random','response':'Response propensity','s_learner':'S-Learner','t_learner':'T-Learner'}
RANK_NAMES={'global_popularity':'Global popularity','personal_recency':'Personalized recency','ml':'ML reranker'}


def purchase_rows(evidence):
    return [{'Model':MODEL_NAMES[m],**evidence['models'][m]['test']} for m in ('dummy','logistic_regression','xgboost')]


def policy_rows(evidence, budget):
    if budget not in (10,20,30):raise ValueError('Only evaluated contact budgets 10%, 20%, 30% are available.')
    answer=[]
    for policy,name in POLICY_NAMES.items():
        result=evidence['policies'][f'{policy}/{budget}%']
        low,high=result['incremental_value_ci95']
        answer.append({'Policy':name,'Estimate':result['incremental_per_1000'],
            'Lower':low*1000,'Upper':high*1000,'Contacted':result['selected_n'],
            'Contact fraction':result['contact_fraction']})
    return answer


def ranking_rows(evidence, k):
    if k not in (5,10,20):raise ValueError('Only evaluated list lengths 5, 10, 20 are available.')
    return [{'Method':name,**evidence['methods'][m][str(k)]} for m,name in RANK_NAMES.items()]


def ranking_difference(evidence,k):
    if k not in (5,10,20):raise ValueError('Unsupported ranking cutoff')
    index=(5,10,20).index(k)*2;stats=evidence['paired_uncertainty']
    return {metric:{'estimate':stats['mean_difference'][i],
            'lower':stats['lower_95'][i],'upper':stats['upper_95'][i]}
        for metric,i in [('Recall',index),('NDCG',index+1)]}
