"""Phase 4: prepare/freeze on validation, then one authorized primary test scoring.

The prepare command never loads test targets. The evaluate command requires
the frozen plan/calibration receipt and claims a one-use test-access ledger.
Saved-prediction verification never regenerates test predictions or refits models.
"""

import argparse
import importlib.metadata
import json
import resource
import subprocess
import sys
import time
from datetime import datetime,timezone
from pathlib import Path

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

from growthlab.acquire import digest,save_json
from growthlab.audit import connect,literal,records
from growthlab.calibration import CALIBRATION_CONFIG,apply_sigmoid,fit_validation_sigmoid
from growthlab.evaluation_uncertainty import BOOTSTRAP_CONFIG,CONTRASTS,METRICS,paired_bootstrap
from growthlab.features import FEATURE_COLUMNS,PRIMARY
from growthlab.modeling import CONFIG,evaluate,matrix_from_columns,reliability_bins,top_indices,xgboost_model

MODEL_NAMES=("dummy","logistic_regression","xgboost","xgboost_calibrated")
EVALUATION_AS_OF="2020-01-21 00:00:00"


def now_utc():return datetime.now(timezone.utc).isoformat()


def exclusive_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("x") as stream:stream.write(json.dumps(value,indent=2,default=str,allow_nan=False)+"\n")


def load_json(path):return json.loads(path.read_text())


def source_fingerprints(root):
    paths=("src/growthlab/final_evaluation.py","src/growthlab/calibration.py",
           "src/growthlab/evaluation_uncertainty.py","src/growthlab/final_plots.py",
           "src/growthlab/modeling.py","src/growthlab/features.py")
    return {p:digest(root/p) for p in paths}


def prepare(root):
    """Write the plan first; fit the sole authorized mapping from validation only."""
    root=root.resolve();folder=root/"docs/phase4";work=root/"data/models/phase4"
    work.mkdir(parents=True,exist_ok=True)
    if (folder/"frozen_plan.json").exists():raise RuntimeError("Plan already frozen; do not replace it")
    phase3=load_json(root/"docs/phase3/validation_summary.json")
    phase2=load_json(root/"docs/phase2/summary.json")
    assert not phase3["test_predictions_generated"] and not phase3["test_performance_computed"]
    for name,version in phase3["versions"].items():
        if importlib.metadata.version(name)!=version:raise ValueError("Model dependency version changed: "+name)
    for p,info in phase3["artifacts"].items():
        if digest(root/p)!=info["sha256"]:raise ValueError("Frozen Phase 3 artifact changed: "+p)
    data_hashes={}
    for split,*_ in PRIMARY:
        path="data/features/phase2/primary/"+split+".parquet"
        data_hashes[path]=digest(root/path)
        assert data_hashes[path]==phase2["export_files"][path]["sha256"]
    master="data/features/phase2/customers.parquet"
    data_hashes[master]=digest(root/master)
    assert data_hashes[master]==phase2["export_files"][master]["sha256"]
    assert phase3["feature_columns"]==list(FEATURE_COLUMNS)
    plan={"frozen_at_utc":now_utc(),"phase3_commit":subprocess.check_output(["git","rev-parse","HEAD"],cwd=root).decode().strip(),
          "primary_model":"xgboost","baselines":["dummy","logistic_regression"],
          "secondary_probability_variant":"xgboost_calibrated","feature_columns":list(FEATURE_COLUMNS),
          "model_configuration":phase3["configuration"],"selected_xgboost_iteration_zero_based":phase3["models"]["xgboost"]["best_iteration_zero_based"],
          "base_model_refitting":False,"preprocessing":"Saved training-fitted LR median imputer/scaler unchanged; XGBoost native NaN; approved missing indicator retained",
          "calibration_configuration":CALIBRATION_CONFIG,"calibration_validation_reuse_warning":"Validation was used for early stopping and will fit calibration; in-sample calibrated validation metrics are not independent evidence and will not be reported",
          "test_cohort":{"prediction_start_inclusive":"2019-12-17 00:00:00","prediction_end_exclusive":"2019-12-22 00:00:00",
                         "expected_customers":51444,"evaluation_as_of_utc":EVALUATION_AS_OF},
          "metrics":[*METRICS],"top_fraction":0.10,"top_count_rounding":"ceil(N*0.10)",
          "tie_policy":CONFIG["tie_break"],"random_seed":42,"reliability_bins":5,
          "uncertainty":BOOTSTRAP_CONFIG,"paired_contrasts":[list(c) for c in CONTRASTS],
          "versions":phase3["versions"],"human_plan_sha256":digest(root/"docs/phase4_frozen_evaluation_plan.md"),
          "phase2_specification_sha256":digest(root/"docs/phase2_specification.json"),
          "phase3_summary_sha256":digest(root/"docs/phase3/validation_summary.json"),
          "data_sha256":data_hashes,"phase3_artifacts":phase3["artifacts"],"source_sha256":source_fingerprints(root),
          "one_use_policy":"No alternative model/configuration is selected from test results; a ledger blocks a second scoring run. Verification may recompute metrics from the identical saved predictions."}
    exclusive_json(folder/"frozen_plan.json",plan)
    validation=root/"data/models/phase3/validation_predictions.npz"
    with np.load(validation) as data:
        if (len(data["target"]),int(data["target"].sum()))!=(53089,1150):raise ValueError("Validation calibration population changed")
        estimator=fit_validation_sigmoid(data["xgboost"],data["target"],source_split="validation")
        calibration_info={"fitted_at_utc":now_utc(),"fit_split":"validation","customers":len(data["target"]),
                          "positive_labels":int(data["target"].sum()),"validation_predictions_sha256":digest(validation),
                          "slope":float(estimator.coef_[0,0]),"intercept":float(estimator.intercept_[0]),
                          "iterations":estimator.n_iter_.tolist(),"in_sample_validation_metrics_reported":False,
                          "model":"q = sigmoid(slope * logit(clipped raw XGBoost p) + intercept)"}
    joblib.dump(estimator,work/"sigmoid_calibrator.joblib")
    exclusive_json(folder/"calibration_fit.json",calibration_info)
    receipt={"ready_for_test_at_utc":now_utc(),"plan_sha256":digest(folder/"frozen_plan.json"),
             "calibration_fit_sha256":digest(folder/"calibration_fit.json"),
             "calibrator_sha256":digest(work/"sigmoid_calibrator.joblib"),"test_labels_loaded":False}
    exclusive_json(folder/"freeze_receipt.json",receipt)
    print(json.dumps({"plan_frozen":receipt,"validation_only_calibration":calibration_info},indent=2),flush=True)
    return plan,receipt


def verify_freeze(root):
    folder=root/"docs/phase4";work=root/"data/models/phase4"
    plan=load_json(folder/"frozen_plan.json");receipt=load_json(folder/"freeze_receipt.json")
    if receipt["plan_sha256"]!=digest(folder/"frozen_plan.json"):raise ValueError("Frozen plan changed")
    if receipt["calibration_fit_sha256"]!=digest(folder/"calibration_fit.json"):raise ValueError("Calibration receipt changed")
    if receipt["calibrator_sha256"]!=digest(work/"sigmoid_calibrator.joblib"):raise ValueError("Frozen calibrator changed")
    if source_fingerprints(root)!=plan["source_sha256"]:raise ValueError("Evaluation source changed after freeze")
    if plan["feature_columns"]!=list(FEATURE_COLUMNS) or plan["model_configuration"]!=CONFIG:raise ValueError("Frozen feature/model configuration changed")
    if plan["calibration_configuration"]!=CALIBRATION_CONFIG or plan["uncertainty"]!=BOOTSTRAP_CONFIG:raise ValueError("Frozen calibration or uncertainty method changed")
    if digest(root/"docs/phase4_frozen_evaluation_plan.md")!=plan["human_plan_sha256"]:raise ValueError("Human-readable frozen plan changed")
    if digest(root/"docs/phase2_specification.json")!=plan["phase2_specification_sha256"]:raise ValueError("Feature specification changed")
    if digest(root/"docs/phase3/validation_summary.json")!=plan["phase3_summary_sha256"]:raise ValueError("Validation results changed")
    for name,version in plan["versions"].items():
        if importlib.metadata.version(name)!=version:raise ValueError("Frozen dependency version changed")
    for p,h in plan["data_sha256"].items():
        if digest(root/p)!=h:raise ValueError("Frozen feature data changed: "+p)
    for p,info in plan["phase3_artifacts"].items():
        if digest(root/p)!=info["sha256"]:raise ValueError("Frozen base model/validation predictions changed")
    return plan,receipt


def verify_test_calendar(con,root,plan):
    """Verify keys/timestamps from metadata only, before reading test labels."""
    master=root/"data/features/phase2/customers.parquet"
    test=root/"data/features/phase2/primary/test.parquet"
    cohort=plan["test_cohort"]
    row=records(con,f"""SELECT count(*) AS customers,count(DISTINCT m.user_id) AS unique_customers,
        min(m.prediction_time) AS first_prediction,max(m.prediction_time) AS last_prediction,
        max(m.outcome_end) AS last_outcome_end,
        count(*) FILTER (WHERE m.primary_split IS DISTINCT FROM 'test' OR m.prediction_time IS NULL OR m.outcome_end IS NULL
          OR m.prediction_time<TIMESTAMP {literal(cohort['prediction_start_inclusive'])}
          OR m.prediction_time>=TIMESTAMP {literal(cohort['prediction_end_exclusive'])}
          OR m.outcome_end>TIMESTAMP {literal(cohort['evaluation_as_of_utc'])}
          OR m.prediction_time<>m.first_seen+INTERVAL 7 DAY OR m.outcome_end<>m.prediction_time+INTERVAL 30 DAY
          OR m.feature_gap OR m.outcome_gap) AS errors
        FROM read_parquet({literal(master)}) m JOIN
          (SELECT user_id FROM read_parquet({literal(test)})) k USING(user_id)""")[0]
    if row["customers"]!=cohort["expected_customers"] or row["customers"]!=row["unique_customers"] or row["errors"]:
        raise ValueError("Test calendar/eligibility metadata mismatch")
    cutoff=datetime.fromisoformat(cohort["evaluation_as_of_utc"]).replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc)<cutoff:raise RuntimeError("Test outcomes not yet mature")
    return row


def claim_test_access(work,receipt):
    record={"test_first_access_utc":now_utc(),"plan_sha256":receipt["plan_sha256"],"status":"claimed; no second scoring run permitted"}
    try:exclusive_json(work/"test_access_ledger.json",record)
    except FileExistsError as exc:raise RuntimeError("The planned test scoring is already claimed; verify saved predictions instead of scoring again") from exc
    return record


def load_saved_models(root):
    models={"dummy":joblib.load(root/"data/models/phase3/dummy.joblib"),
            "logistic_regression":joblib.load(root/"data/models/phase3/logistic_regression.joblib"),"xgboost":xgboost_model()}
    models["xgboost"].load_model(root/"data/models/phase3/xgboost.ubj")
    return models


def frozen_predict(models,calibrator,x):
    predictions={name:model.predict_proba(x)[:,1] for name,model in models.items()}
    predictions["xgboost_calibrated"]=apply_sigmoid(calibrator,predictions["xgboost"])
    return predictions


def evaluate_once(root):
    root=root.resolve();started=time.monotonic();work=root/"data/models/phase4"
    plan,receipt=verify_freeze(root)
    con=connect(":memory:",work/"spill","256MB")
    try:
        calendar=verify_test_calendar(con,root,plan)
        # IDs only from training/validation; no features or labels from them are refitted.
        test=root/"data/features/phase2/primary/test.parquet"
        for split in ("train","validation"):
            path=root/"data/features/phase2/primary"/(split+".parquet")
            overlap=con.execute(f"""SELECT count(*) FROM (SELECT user_id FROM read_parquet({literal(test)})) t
                JOIN (SELECT user_id FROM read_parquet({literal(path)})) s USING(user_id)""").fetchone()[0]
            if overlap:raise ValueError("Customer overlap with test")
        access=claim_test_access(work,receipt)
        print("Frozen plan verified; claiming the single planned test scoring",flush=True)
        columns=con.execute(f"SELECT * FROM read_parquet({literal(test)}) ORDER BY user_id").fetchnumpy()
        ids,x,y=matrix_from_columns(columns)
    finally:con.close()
    if len(y)!=plan["test_cohort"]["expected_customers"]:raise ValueError("Unexpected test population")
    models=load_saved_models(root);calibrator=joblib.load(work/"sigmoid_calibrator.joblib")
    assert models["xgboost"].best_iteration==plan["selected_xgboost_iteration_zero_based"]
    with threadpool_limits(limits=1):
        predictions=frozen_predict(models,calibrator,x)
        # Save the one prediction set BEFORE uncertainty/figures so verification
        # can use this record without any further model scoring.
        np.savez_compressed(work/"test_predictions.npz",user_id=ids,target=y,**predictions)
        result={"plan_sha256":receipt["plan_sha256"],"test_access":access,"calendar_checks":calendar,
                "primary_model":"xgboost","underlying_model_refits":0,"calibrator_refits_on_test":0,
                "test_customers":len(y),"test_positive_labels":int(y.sum()),"test_prevalence":float(y.mean()),
                "models":{name:{"test":evaluate(y,p),"reliability":reliability_bins(y,p,5)} for name,p in predictions.items()}}
        result["calibration_ranking_preserved"]={
            "same_top_10_percent_customers":bool(np.array_equal(top_indices(predictions["xgboost"]),top_indices(predictions["xgboost_calibrated"]))),
            "ap_difference":result["models"]["xgboost_calibrated"]["test"]["average_precision"]-result["models"]["xgboost"]["test"]["average_precision"],
            "auc_difference":result["models"]["xgboost_calibrated"]["test"]["roc_auc"]-result["models"]["xgboost"]["test"]["roc_auc"]}
        uncertainty,draws=paired_bootstrap(y,predictions,replicates=plan["uncertainty"]["replicates"],
                                          seed=plan["uncertainty"]["seed"],progress=True)
        result["uncertainty"]=uncertainty
        np.savez_compressed(work/"bootstrap_draws.npz",**draws)
    from growthlab.final_plots import plot_test_results
    plot_test_results(root,y,predictions,result)
    # Freeze/data/model integrity must still hold after prediction/calibration.
    verify_freeze(root)
    result["elapsed_seconds"]=round(time.monotonic()-started,3)
    rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result["peak_process_rss_bytes"]=rss if sys.platform=="darwin" else rss*1024
    result["completed_at_utc"]=now_utc()
    result["evaluation_source_sha256"]=source_fingerprints(root)
    result["artifacts"]={str(p.relative_to(root)):{"bytes":p.stat().st_size,"sha256":digest(p)} for p in
                         (work/"sigmoid_calibrator.joblib",work/"test_predictions.npz",work/"bootstrap_draws.npz",work/"test_access_ledger.json")}
    save_json(root/"docs/phase4/test_summary.json",result)
    save_json(work/"manifest.json",result)
    print(json.dumps({name:row["test"] for name,row in result["models"].items()},indent=2),flush=True)
    return result


def verify_saved(root):
    root=root.resolve();verify_freeze(root)
    result=load_json(root/"docs/phase4/test_summary.json")
    for p,info in result["artifacts"].items():
        if digest(root/p)!=info["sha256"]:raise ValueError("Saved evaluation artifact changed")
    with np.load(root/"data/models/phase4/test_predictions.npz") as data:
        for name in MODEL_NAMES:
            if evaluate(data["target"],data[name])!=result["models"][name]["test"]:raise ValueError("Saved test metric mismatch")
    print("Verified the identical saved predictions and metrics; no model refitting or new test prediction",flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare",action="store_true");group.add_argument("--evaluate",action="store_true");group.add_argument("--verify-saved",action="store_true")
    parser.add_argument("--root",type=Path,default=Path.cwd())
    args=parser.parse_args()
    if args.prepare:prepare(args.root)
    elif args.evaluate:evaluate_once(args.root)
    else:verify_saved(args.root)


if __name__=="__main__":main()
