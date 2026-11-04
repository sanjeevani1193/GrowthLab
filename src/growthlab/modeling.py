"""Phase 3: three frozen initial baselines, evaluated on validation ONLY.

Test access is restricted to file integrity/schema and customer-key disjointness.
The model loader rejects 'test'. Missingness for test comes from Phase 2's frozen
aggregate report; no test predictions, curves or performance are computed.
"""

import argparse
import importlib.metadata
import json
import math
import resource
import sys
import time
import warnings
from pathlib import Path

import joblib
import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from growthlab.acquire import digest, save_json
from growthlab.audit import connect, literal
from growthlab.features import FEATURE_COLUMNS, PRIMARY, TARGET

SEED=42
CONFIG={
    "seed":SEED,"evaluated_split":"validation","feature_columns":list(FEATURE_COLUMNS),
    "top_fraction":0.10,"tie_break":"label-independent seeded random priorities, after sorting rows by user_id",
    "dummy":{"strategy":"prior","random_state":SEED},
    "logistic_regression":{"solver":"lbfgs","C":1.0,"l1_ratio":0.0,
                           "max_iter":2000,"tol":1e-6,"random_state":SEED,"class_weight":None},
    "xgboost":{"objective":"binary:logistic","tree_method":"hist","device":"cpu",
               "n_estimators":500,"max_depth":3,"learning_rate":0.05,"min_child_weight":10,
               "subsample":0.8,"colsample_bytree":0.9,"reg_lambda":5.0,"reg_alpha":0.0,
               "gamma":0.0,"max_bin":128,"scale_pos_weight":1.0,"n_jobs":1,
               "random_state":SEED,"eval_metric":"logloss","early_stopping_rounds":30},
}


def matrix_from_columns(columns):
    """Explicit, ordered allowlist: never infer predictors from numeric types."""
    expected={"user_id",TARGET,*FEATURE_COLUMNS}
    if set(columns)!=expected:
        raise ValueError("Export schema differs from approved key + 12 predictors + target")
    x=np.column_stack([np.ma.asarray(columns[name],dtype=np.float64).filled(np.nan) for name in FEATURE_COLUMNS])
    original_y=np.asarray(columns[TARGET])
    if not np.isin(original_y,[0,1]).all():raise ValueError("Nonbinary target")
    y=original_y.astype(np.int8)
    ids=np.asarray(columns["user_id"],dtype=np.int64)
    price=FEATURE_COLUMNS.index("median_view_price_7d")
    others=[i for i in range(len(FEATURE_COLUMNS)) if i!=price]
    if np.any(~np.isfinite(x[:,others])) or np.any(np.isinf(x[:,price])):
        raise ValueError("Unexpected nonfinite predictor")
    if not np.array_equal(np.isnan(x[:,price]).astype(int),x[:,FEATURE_COLUMNS.index("view_price_unavailable_7d")]):
        raise ValueError("Missing-price indicator disagrees with actual missingness")
    if len(np.unique(ids))!=len(ids) or not np.isin(y,[0,1]).all():
        raise ValueError("Duplicate customer or nonbinary target")
    return ids,x,y


def load_model_split(con,root,split):
    if split not in {"train","validation"}:
        raise ValueError("Phase 3 permits training and validation only; test prediction/evaluation is forbidden")
    path=root/"data/features/phase2/primary"/(split+".parquet")
    columns=con.execute(f"SELECT * FROM read_parquet({literal(path)}) ORDER BY user_id").fetchnumpy()
    return matrix_from_columns(columns)


def verify_inputs(con,root):
    phase2=json.loads((root/"docs/phase2/summary.json").read_text())
    spec=json.loads((root/"docs/phase2_specification.json").read_text())
    if spec["feature_columns"]!=list(FEATURE_COLUMNS) or phase2["feature_columns"]!=list(FEATURE_COLUMNS):
        raise ValueError("Approved feature allowlist changed")
    if phase2["specification_sha256"]!=digest(root/"docs/phase2_specification.json"):
        raise ValueError("Frozen Phase 2 specification changed")
    keys={}
    hashes={}
    for split,*_ in PRIMARY:
        relative="data/features/phase2/primary/"+split+".parquet"
        path=root/relative
        hashes[split]=digest(path)
        if hashes[split]!=phase2["export_files"][relative]["sha256"]:
            raise ValueError(f"Verified {split} file changed")
        # The only test data values read here are user IDs, for disjointness.
        ids=con.execute(f"SELECT user_id FROM read_parquet({literal(path)})").fetchnumpy()["user_id"]
        keys[split]=set(int(v) for v in ids)
        expected=next(s for s in PRIMARY if s[0]==split)
        if len(ids)!=len(keys[split]) or len(ids)!=expected[3]:
            raise ValueError("Split population changed")
        names=[r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({literal(path)})").fetchall()]
        if names!=["user_id",*FEATURE_COLUMNS,TARGET]:raise ValueError("Split export schema changed")
    for a,b in (("train","validation"),("train","test"),("validation","test")):
        if keys[a]&keys[b]:raise ValueError("Customer overlap between splits")
    return phase2,hashes


def logistic_model():
    # Existing view_price_unavailable_7d is the indicator; do not add a 13th input.
    return Pipeline([("impute",SimpleImputer(strategy="median",add_indicator=False)),
                     ("scale",StandardScaler()),
                     ("model",LogisticRegression(**CONFIG["logistic_regression"]))])


def xgboost_model(**overrides):
    from growthlab.openmp_runtime import preload_local_openmp
    preload_local_openmp()
    from xgboost import XGBClassifier
    return XGBClassifier(**(CONFIG["xgboost"]|overrides))


def valid_probabilities(probabilities,n=None):
    p=np.asarray(probabilities,dtype=np.float64)
    if p.ndim!=1 or (n is not None and len(p)!=n) or not np.isfinite(p).all() or np.any((p<0)|(p>1)):
        raise ValueError("Probabilities must be finite one-dimensional values in [0,1]")
    return p


def top_indices(probabilities,fraction=0.10,seed=SEED):
    p=valid_probabilities(probabilities)
    if not 0<fraction<=1 or not len(p):raise ValueError("Invalid contact fraction or empty population")
    # Random priorities break score ties without consulting labels or IDs.
    priority=np.random.default_rng(seed).permutation(len(p))
    return np.lexsort((priority,-p))[:math.ceil(fraction*len(p))]


def evaluate(y,probabilities):
    y=np.asarray(y,dtype=int)
    p=valid_probabilities(probabilities,len(y))
    if not len(y) or not np.isin(y,[0,1]).all():raise ValueError("Nonempty binary labels required")
    selected=top_indices(p,CONFIG["top_fraction"])
    positives=int(y.sum())
    true_positives=int(y[selected].sum())
    prevalence=float(y.mean())
    precision=true_positives/len(selected)
    return {"customers":len(y),"positive_labels":positives,"prevalence":prevalence,
            "average_precision":float(average_precision_score(y,p)) if positives else None,
            "roc_auc":float(roc_auc_score(y,p)) if len(np.unique(y))==2 else None,
            "brier_score":float(brier_score_loss(y,p)),"log_loss":float(log_loss(y,p,labels=[0,1])),
            "top_10_percent_count":len(selected),"top_10_percent_positive_labels":true_positives,
            "precision_at_top_10_percent":precision,
            "recall_at_top_10_percent":true_positives/positives if positives else None,
            "lift_at_top_10_percent":precision/prevalence if prevalence else None,
            "mean_predicted_probability":float(p.mean()),"minimum_probability":float(p.min()),
            "maximum_probability":float(p.max())}


def reliability_bins(y,probabilities,n_bins=5):
    p=valid_probabilities(probabilities,len(y))
    y=np.asarray(y,dtype=int)
    edges=np.unique(np.quantile(p,np.linspace(0,1,n_bins+1)))
    bin_ids=np.searchsorted(edges[1:-1],p)
    rows=[]
    for b in np.unique(bin_ids):
        mask=bin_ids==b
        rows.append({"customers":int(mask.sum()),"positives":int(y[mask].sum()),
                     "mean_predicted_probability":float(p[mask].mean()),"observed_purchase_rate":float(y[mask].mean()),
                     "minimum_probability":float(p[mask].min()),"maximum_probability":float(p[mask].max())})
    return rows


def run(root):
    root=root.resolve()
    started=time.monotonic()
    work=root/"data/models/phase3"
    work.mkdir(parents=True,exist_ok=True)
    con=connect(":memory:",work/"spill","256MB")
    try:
        phase2,hashes=verify_inputs(con,root)
        train_ids,x_train,y_train=load_model_split(con,root,"train")
        val_ids,x_val,y_val=load_model_split(con,root,"validation")
    finally:
        con.close()
    for name,y in (("train",y_train),("validation",y_val)):
        expected=next(s for s in PRIMARY if s[0]==name)
        assert (len(y),int(y.sum()))==(expected[3],expected[4])
    missing={split:{feature:phase2["feature_distributions"][split][feature]["missing"] for feature in FEATURE_COLUMNS}
             for split in ("train","validation","test")}
    assert {f:int(np.isnan(x_train[:,i]).sum()) for i,f in enumerate(FEATURE_COLUMNS)}==missing["train"]
    assert {f:int(np.isnan(x_val[:,i]).sum()) for i,f in enumerate(FEATURE_COLUMNS)}==missing["validation"]
    result={"configuration":CONFIG,"data_hashes":hashes,"feature_columns":list(FEATURE_COLUMNS),
            "missing_counts":missing,"models":{},"evaluated_splits":["validation"],
            "test_predictions_generated":False,"test_performance_computed":False,
            "test_access":"SHA256/schema/user_id-only disjointness; missingness and prevalence from frozen Phase 2 aggregates",
            "versions":{p:importlib.metadata.version(p) for p in
                ("numpy","scikit-learn","xgboost","matplotlib","scipy","joblib","threadpoolctl","duckdb")},
            "python_version":sys.version.split()[0]}
    predictions={}
    with threadpool_limits(limits=1):
        for name,model in (("dummy",DummyClassifier(**CONFIG["dummy"])),
                           ("logistic_regression",logistic_model()),("xgboost",xgboost_model())):
            print("Training one fixed configuration:",name,flush=True)
            before=time.monotonic()
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always",ConvergenceWarning)
                if name=="xgboost":
                    model.fit(x_train,y_train,eval_set=[(x_val,y_val)],verbose=False)
                else:
                    model.fit(x_train,y_train)
            if any(issubclass(w.category,ConvergenceWarning) for w in caught):
                raise RuntimeError("Logistic Regression failed to converge; do not publish unchecked results")
            probabilities=valid_probabilities(model.predict_proba(x_val)[:,1],len(y_val))
            row={"validation":evaluate(y_val,probabilities),"reliability":reliability_bins(y_val,probabilities),
                 "fit_seconds":round(time.monotonic()-before,3),"warnings":[str(w.message) for w in caught]}
            if name=="logistic_regression":
                row["training_imputation_statistics"]=dict(zip(FEATURE_COLUMNS,model.named_steps["impute"].statistics_.tolist()))
                row["training_scaler_means"]=model.named_steps["scale"].mean_.tolist()
                row["training_scaler_scales"]=model.named_steps["scale"].scale_.tolist()
                row["iterations"]=model.named_steps["model"].n_iter_.tolist()
                row["standardized_coefficients"]=dict(zip(FEATURE_COLUMNS,model.named_steps["model"].coef_[0].tolist()))
                artifact=work/(name+".joblib")
                joblib.dump(model,artifact)
                reloaded=joblib.load(artifact)
            elif name=="xgboost":
                row["best_iteration_zero_based"]=model.best_iteration
                row["best_validation_logloss"]=model.best_score
                row["rounds_trained"]=model.get_booster().num_boosted_rounds()
                row["validation_logloss_history"]=model.evals_result()["validation_0"]["logloss"]
                # Importance must exclude later patience trees unused in prediction.
                booster=model.get_booster()[:model.best_iteration+1]
                gain=booster.get_score(importance_type="total_gain")
                total=sum(gain.values()) or 1.0
                row["selected_tree_total_gain_share"]={f:float(gain.get("f"+str(i),0)/total) for i,f in enumerate(FEATURE_COLUMNS)}
                artifact=work/"xgboost.ubj"
                model.save_model(artifact)
                reloaded=xgboost_model()
                reloaded.load_model(artifact)
            else:
                row["training_positive_prior"]=float(model.class_prior_[1])
                artifact=work/"dummy.joblib"
                joblib.dump(model,artifact)
                reloaded=joblib.load(artifact)
            np.testing.assert_array_equal(probabilities,reloaded.predict_proba(x_val)[:,1])
            row["saved_model_roundtrip_predictions_identical"]=True
            result["models"][name]=row
            predictions[name]=probabilities
    price_index=FEATURE_COLUMNS.index("median_view_price_7d")
    assert result["models"]["logistic_regression"]["training_imputation_statistics"]["median_view_price_7d"]==float(np.nanmedian(x_train[:,price_index]))
    np.savez_compressed(work/"validation_predictions.npz",user_id=val_ids,target=y_val,**predictions)
    from growthlab.model_plots import plot_results
    plot_results(root,y_val,predictions,result)
    for split,h in hashes.items():assert digest(root/"data/features/phase2/primary"/(split+".parquet"))==h
    result["elapsed_seconds"]=round(time.monotonic()-started,3)
    rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result["peak_process_rss_bytes"]=rss if sys.platform=="darwin" else rss*1024
    result["array_storage_bytes"]=int(x_train.nbytes+x_val.nbytes+y_train.nbytes+y_val.nbytes+train_ids.nbytes+val_ids.nbytes)
    from growthlab.openmp_runtime import preload_local_openmp
    result["local_openmp_runtime"]=preload_local_openmp()
    result["source_sha256"]={str(p.relative_to(root)):digest(p) for p in
        [Path(__file__).resolve(),root/"src/growthlab/model_plots.py",root/"src/growthlab/features.py",root/"src/growthlab/openmp_runtime.py"]}
    result["phase2_summary_sha256"]=digest(root/"docs/phase2/summary.json")
    result["artifacts"]={str(p.relative_to(root)):{"bytes":p.stat().st_size,"sha256":digest(p)}
                         for p in (work/"dummy.joblib",work/"logistic_regression.joblib",work/"xgboost.ubj",work/"validation_predictions.npz")}
    save_json(root/"docs/phase3/validation_summary.json",result)
    save_json(work/"manifest.json",result)
    print(json.dumps({name:row["validation"] for name,row in result["models"].items()},indent=2),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path.cwd())
    run(parser.parse_args().root)


if __name__=="__main__":
    main()
