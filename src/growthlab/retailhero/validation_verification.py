"""Reproduce validation scores and all bootstrap draws, without refitting."""
import json
from pathlib import Path

import numpy as np
import joblib
from threadpoolctl import threadpool_limits

from .acquire import sha256
from .experiment import write_json
from .uplift import load_cohort, predict_models, verify, verify_models
from .uplift_metrics import bootstrap_evaluation, interval, ranking


def reproduce(root=Path('.')):
    verify(root)
    docs=root/'docs/causal/phase6';receipt=verify_models(root)
    for name,digest in receipt['source_sha256'].items():
        if sha256(root/name)!=digest: raise ValueError('training-time source changed')
    ids,X,t,y=load_cohort(root,'validation')
    with threadpool_limits(limits=1):
        scores,probabilities=predict_models(joblib.load(root/receipt['model_path']),X)
        with np.load(root/'data/retailhero/phase6/validation_predictions.npz') as saved:
            for name,actual in {'client_id':ids.astype(str),'treatment':t,'target':y,**scores,**probabilities}.items():
                np.testing.assert_array_equal(actual,saved[name],err_msg='saved validation prediction mismatch')
        orders={name:ranking(value,ids,20261105) for name,value in scores.items()}
        draws=bootstrap_evaluation(y,t,orders,draws=500,seed=20261106)
        with np.load(root/'data/retailhero/phase6/bootstrap_draws.npz') as saved:
            for name,actual in draws.items():
                np.testing.assert_array_equal(actual,saved[name],err_msg='bootstrap draw mismatch')
    summary=json.loads((docs/'validation_summary.json').read_text())
    for name in scores:
        for metric in ['auuc','qini_area']:
            if interval(draws[f'{name}/{metric}'])!=summary['metrics'][name][metric+'_ci95']:
                raise ValueError('curve confidence interval mismatch')
    for name,row in summary['policies'].items():
        for metric in ['value','incremental_value']:
            if interval(draws[f'{name}/{metric}'])!=row[metric+'_ci95']:
                raise ValueError('policy confidence interval mismatch')
    paired_curves={}
    for model in ['s_learner','t_learner']:
        for baseline in ['constant','response']:
            paired_curves[f'{model} minus {baseline}']={
                'auuc_difference':summary['metrics'][model]['auuc']-summary['metrics'][baseline]['auuc'],
                'ci95':interval(draws[f'{model}/auuc']-draws[f'{baseline}/auuc'])}
    result={'validation_n':len(ids),'predictions_identical':True,'all_500_bootstrap_draws_identical':True,
            'saved_metrics_and_intervals_match':True,'training_time_source_hashes_match':True,
            'no_refitting':True,'final_holdout_accessed':False,
            'paired_curve_comparisons':paired_curves,'validation_summary_sha256':sha256(docs/'validation_summary.json')}
    write_json(docs/'validation_verification.json',result)
    return result


if __name__=='__main__': print(json.dumps(reproduce(),indent=2))
