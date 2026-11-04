"""Frozen two-parameter Platt scaling on validation logits, never test fitting."""

import warnings

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

from growthlab.modeling import valid_probabilities

CALIBRATION_CONFIG={"method":"sigmoid of raw XGBoost log-odds",
    "fit_split":"validation","probability_clip_epsilon":1e-15,
    "solver":"lbfgs","C":"infinity (unpenalized)","l1_ratio":0.0,
    "tol":1e-10,"max_iter":1000,"random_state":42,"class_weight":None,
    "role":"secondary probability variant; raw XGBoost remains primary ranking model"}


def score_logits(probabilities):
    p=valid_probabilities(probabilities)
    p=np.clip(p,CALIBRATION_CONFIG["probability_clip_epsilon"],1-CALIBRATION_CONFIG["probability_clip_epsilon"])
    return (np.log(p)-np.log1p(-p)).reshape(-1,1)


def fit_validation_sigmoid(probabilities,labels,*,source_split):
    if source_split!="validation":raise ValueError("Calibration fitting is permitted on validation only")
    y=np.asarray(labels)
    if not np.isin(y,[0,1]).all() or len(np.unique(y))!=2:raise ValueError("Two binary validation classes required")
    x=score_logits(probabilities)
    if len(x)!=len(y):raise ValueError("Calibration score/label mismatch")
    estimator=LogisticRegression(C=np.inf,l1_ratio=0.0,solver="lbfgs",tol=1e-10,
                                 max_iter=1000,random_state=42,class_weight=None)
    with warnings.catch_warnings(record=True) as caught,threadpool_limits(limits=1):
        warnings.simplefilter("always",ConvergenceWarning)
        estimator.fit(x,y)
    if any(issubclass(w.category,ConvergenceWarning) for w in caught):raise RuntimeError("Sigmoid calibration failed to converge")
    if estimator.coef_[0,0]<=0:
        raise RuntimeError("Nonpositive validation calibration slope; stop before test and review the ranking policy")
    return estimator


def apply_sigmoid(estimator,probabilities):
    return valid_probabilities(estimator.predict_proba(score_logits(probabilities))[:,1],len(probabilities))
