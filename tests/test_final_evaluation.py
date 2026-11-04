"""Pre-test synthetic contracts plus post-evaluation saved-record checks."""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np

from growthlab.audit import connect
from growthlab.calibration import apply_sigmoid,fit_validation_sigmoid,score_logits
from growthlab.evaluation_uncertainty import paired_bootstrap
from growthlab.features import FEATURE_COLUMNS,copy_parquet
from growthlab.final_evaluation import (claim_test_access,exclusive_json,frozen_predict,
                                       verify_freeze,verify_saved,verify_test_calendar)
from growthlab.modeling import evaluate,top_indices


def validation_fixture():
    return np.array([.05,.1,.2,.3,.4,.5,.6,.7,.8,.9]),np.array([0,0,1,0,0,1,0,1,1,1])


class FrozenEvaluationTests(unittest.TestCase):
    def test_calibration_fit_rejects_test_before_fitting(self):
        p,y=validation_fixture()
        with patch("sklearn.linear_model.LogisticRegression.fit",side_effect=AssertionError("must not fit")):
            with self.assertRaisesRegex(ValueError,"validation only"):
                fit_validation_sigmoid(p,y,source_split="test")

    def test_sigmoid_uses_one_score_and_preserves_order(self):
        p,y=validation_fixture()
        estimator=fit_validation_sigmoid(p,y,source_split="validation")
        self.assertEqual(estimator.n_features_in_,1)
        self.assertGreater(estimator.coef_[0,0],0)
        q=apply_sigmoid(estimator,p)
        self.assertTrue(np.all(np.diff(q)>0))
        self.assertEqual(evaluate(y,p)["average_precision"],evaluate(y,q)["average_precision"])
        np.testing.assert_equal(top_indices(p),top_indices(q))

    def test_test_prediction_cannot_refit_any_estimator(self):
        p,y=validation_fixture();cal=fit_validation_sigmoid(p,y,source_split="validation")
        coef=cal.coef_.copy();intercept=cal.intercept_.copy()
        class PredictOnly:
            def fit(self,*a,**kw):raise AssertionError("refitting forbidden")
            def predict_proba(self,x):return np.column_stack([1-x[:,0],x[:,0]])
        models={name:PredictOnly() for name in ("dummy","logistic_regression","xgboost")}
        with patch("sklearn.linear_model.LogisticRegression.fit",side_effect=AssertionError("test fit forbidden")):
            result=frozen_predict(models,cal,p.reshape(-1,1))
        self.assertEqual(set(result),{"dummy","logistic_regression","xgboost","xgboost_calibrated"})
        np.testing.assert_equal(coef,cal.coef_);np.testing.assert_equal(intercept,cal.intercept_)

    def test_sigmoid_fit_deterministic(self):
        p,y=validation_fixture()
        a=fit_validation_sigmoid(p,y,source_split="validation")
        b=fit_validation_sigmoid(p,y,source_split="validation")
        np.testing.assert_array_equal(apply_sigmoid(a,p),apply_sigmoid(b,p))

    def test_boundary_probabilities_have_finite_logits(self):
        self.assertTrue(np.isfinite(score_logits([0,1,.5])).all())

    def test_plan_and_access_ledger_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            exclusive_json(root/"plan.json",{"model":"xgboost"})
            with self.assertRaises(FileExistsError):exclusive_json(root/"plan.json",{"model":"other"})
            self.assertEqual(json.loads((root/"plan.json").read_text()),{"model":"xgboost"})
            claim_test_access(root,{"plan_sha256":"frozen"})
            with self.assertRaisesRegex(RuntimeError,"already claimed"):claim_test_access(root,{"plan_sha256":"frozen"})

    def test_modified_plan_rejected_before_data_access(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);docs=root/"docs/phase4";docs.mkdir(parents=True)
            (docs/"frozen_plan.json").write_text('{}')
            (docs/"freeze_receipt.json").write_text('{"plan_sha256":"wrong"}')
            with self.assertRaisesRegex(ValueError,"Frozen plan changed"):verify_freeze(root)

    def test_calendar_maturity_checked_without_any_target_column(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);con=connect(":memory:",root/"spill","256MB")
            try:
                master=root/"data/features/phase2/customers.parquet"
                test=root/"data/features/phase2/primary/test.parquet"
                con.execute("""CREATE TABLE metadata AS SELECT 1 AS user_id,TIMESTAMP '2019-12-10' AS first_seen,
                    TIMESTAMP '2019-12-17' AS prediction_time,TIMESTAMP '2020-01-16' AS outcome_end,
                    'test' AS primary_split,false AS feature_gap,false AS outcome_gap""")
                copy_parquet(con,"SELECT * FROM metadata",master)
                copy_parquet(con,"SELECT user_id FROM metadata",test)
                plan={"test_cohort":{"prediction_start_inclusive":"2019-12-17","prediction_end_exclusive":"2019-12-22",
                                     "evaluation_as_of_utc":"2020-01-21","expected_customers":1}}
                self.assertEqual(verify_test_calendar(con,root,plan)["customers"],1)
                con.execute("UPDATE metadata SET outcome_end=TIMESTAMP '2020-02-01'")
                copy_parquet(con,"SELECT * FROM metadata",master)
                with self.assertRaisesRegex(ValueError,"calendar"):verify_test_calendar(con,root,plan)
            finally:con.close()

    def test_paired_bootstrap_is_deterministic_and_rank_preserving(self):
        p,y=validation_fixture()
        predictions={"dummy":np.full(len(y),.5),"logistic_regression":p*.9,"xgboost":p,"xgboost_calibrated":p**.8}
        a,draws_a=paired_bootstrap(y,predictions,replicates=8,seed=7)
        b,draws_b=paired_bootstrap(y,predictions,replicates=8,seed=7)
        self.assertEqual(a,b)
        for name in predictions:np.testing.assert_equal(draws_a[name],draws_b[name])
        self.assertEqual(a["paired_differences"]["primary_ap_gain_xgboost_minus_logistic"]["lower"],0)
        self.assertEqual(a["paired_differences"]["primary_ap_gain_xgboost_minus_logistic"]["upper"],0)

    def test_frozen_feature_count_and_label_blind_top_k(self):
        self.assertEqual(len(FEATURE_COLUMNS),12)
        self.assertFalse(set(FEATURE_COLUMNS)&{"user_id","purchased_next_30d","feature_gap","outcome_gap"})
        p=np.full(51,.1)
        self.assertEqual(len(top_indices(p)),6)
        np.testing.assert_equal(top_indices(p),top_indices(p))


class FinalRecordTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parents[1]
        file=self.root/"docs/phase4/test_summary.json"
        if not file.exists():self.skipTest("Planned evaluation has not yet taken place")
        self.result=json.loads(file.read_text())

    def test_freeze_precedes_first_access_and_models_remain_fixed(self):
        plan,receipt=verify_freeze(self.root)
        access=datetime.fromisoformat(self.result["test_access"]["test_first_access_utc"])
        self.assertLess(datetime.fromisoformat(plan["frozen_at_utc"]),access)
        self.assertLess(datetime.fromisoformat(receipt["ready_for_test_at_utc"]),access)
        self.assertEqual(self.result["underlying_model_refits"],0)
        self.assertEqual(self.result["calibrator_refits_on_test"],0)
        self.assertEqual(self.result["calendar_checks"]["errors"],0)

    def test_saved_prediction_metrics_reproduce_without_scoring_models(self):
        if not (self.root/"data/models/phase4/test_predictions.npz").exists():self.skipTest("Local predictions unavailable")
        with patch("growthlab.final_evaluation.load_saved_models",side_effect=AssertionError("no model scoring")):
            verify_saved(self.root)

    def test_uncertainty_and_population_consistency(self):
        self.assertEqual((self.result["test_customers"],self.result["test_positive_labels"]),(51444,547))
        self.assertEqual(self.result["uncertainty"]["replicates"],500)
        for row in self.result["models"].values():
            self.assertEqual(row["test"]["top_10_percent_count"],5145)
        for metrics in self.result["uncertainty"]["intervals"].values():
            for interval in metrics.values():
                self.assertLessEqual(interval["lower"],interval["upper"])
                self.assertEqual(interval["valid_replicates"],500)


if __name__=="__main__":unittest.main()
