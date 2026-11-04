"""Prespecified paired customer bootstrap; no model fitting or parameter search."""

import numpy as np

from growthlab.modeling import evaluate

METRICS=("average_precision","roc_auc","brier_score","log_loss",
         "precision_at_top_10_percent","recall_at_top_10_percent","lift_at_top_10_percent",
         "top_10_percent_positive_labels","mean_predicted_probability","prevalence")
BOOTSTRAP_CONFIG={"method":"paired ordinary customer bootstrap; percentile intervals",
    "replicates":500,"seed":20261104,"confidence_level":0.95,
    "resampling":"Sample N customer indices with replacement, sort indices to preserve key ordering, reuse for every variant",
    "model_refitting":False,"calibrator_refitting":False,
    "scope":"Conditional on frozen models/calibrator and this cohort; assumes independent customer sampling; excludes training/calibration and temporal-shift uncertainty"}

CONTRASTS=(
    ("primary_ap_gain_xgboost_minus_logistic","xgboost","logistic_regression","average_precision"),
    ("auc_gain_xgboost_minus_logistic","xgboost","logistic_regression","roc_auc"),
    ("recall_gain_xgboost_minus_logistic","xgboost","logistic_regression","recall_at_top_10_percent"),
    ("calibrated_minus_raw_brier","xgboost_calibrated","xgboost","brier_score"),
    ("calibrated_minus_raw_log_loss","xgboost_calibrated","xgboost","log_loss"),
)


def paired_bootstrap(labels,predictions,*,replicates=500,seed=20261104,progress=False):
    y=np.asarray(labels)
    if not len(y) or not np.isin(y,[0,1]).all():raise ValueError("Nonempty binary sample required")
    if set(predictions)!={"dummy","logistic_regression","xgboost","xgboost_calibrated"}:
        raise ValueError("The four frozen evaluation variants are required")
    if replicates<2:raise ValueError("At least two bootstrap replicates required")
    rng=np.random.default_rng(seed)
    draws={name:np.full((replicates,len(METRICS)),np.nan) for name in predictions}
    for rep in range(replicates):
        indices=np.sort(rng.integers(0,len(y),size=len(y)))
        for name,p in predictions.items():
            row=evaluate(y[indices],np.asarray(p)[indices])
            draws[name][rep]=[np.nan if row[k] is None else row[k] for k in METRICS]
        if progress and (rep+1)%100==0:print(f"Paired bootstrap {rep+1}/{replicates}",flush=True)
    intervals={}
    for name,values in draws.items():
        intervals[name]={}
        for index,metric in enumerate(METRICS):
            valid=values[np.isfinite(values[:,index]),index]
            bounds=np.quantile(valid,[0.025,0.975]) if len(valid) else [None,None]
            intervals[name][metric]={"lower":None if bounds[0] is None else float(bounds[0]),
                                      "upper":None if bounds[1] is None else float(bounds[1]),"valid_replicates":len(valid)}
    contrasts={}
    for name,a,b,metric in CONTRASTS:
        difference=draws[a][:,METRICS.index(metric)]-draws[b][:,METRICS.index(metric)]
        valid=difference[np.isfinite(difference)]
        bounds=np.quantile(valid,[0.025,0.975]) if len(valid) else [None,None]
        contrasts[name]={"lower":None if bounds[0] is None else float(bounds[0]),
                         "upper":None if bounds[1] is None else float(bounds[1]),"valid_replicates":len(valid)}
    return {"replicates":replicates,"seed":seed,"intervals":intervals,"paired_differences":contrasts},draws
