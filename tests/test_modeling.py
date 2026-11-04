"""Leakage/preprocessing/metric contracts on small known examples, no test-set prediction."""

import unittest
import json
import tempfile
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from growthlab.features import FEATURE_COLUMNS,TARGET
from growthlab.modeling import (evaluate,load_model_split,logistic_model,matrix_from_columns,
                               reliability_bins,top_indices,valid_probabilities,verify_inputs,xgboost_model)


def toy_columns():
    cols={f:np.array([0.0,1.0,2.0,3.0]) for f in FEATURE_COLUMNS}
    cols["user_id"]=np.array([111,222,333,444])
    cols[TARGET]=np.array([0,1,0,1])
    cols["median_view_price_7d"]=np.array([2.0,np.nan,4.0,6.0])
    cols["view_price_unavailable_7d"]=np.array([0.0,1.0,0.0,0.0])
    return cols


class ModelingContracts(unittest.TestCase):
    def test_model_loader_rejects_test_before_any_file_access(self):
        with self.assertRaisesRegex(ValueError,"forbidden"):
            load_model_split(None,Path('/nonexistent'),"test")

    def test_inputs_exclude_key_label_and_qa(self):
        columns=toy_columns()
        ids,x,y=matrix_from_columns(columns)
        self.assertEqual(x.shape,(4,12))
        self.assertFalse(np.isin(x,ids).any())
        self.assertEqual(ids.tolist(),[111,222,333,444])
        self.assertEqual(y.tolist(),[0,1,0,1])
        columns["outcome_gap"]=np.zeros(4)
        with self.assertRaises(ValueError):matrix_from_columns(columns)

    def test_feature_order_independent_of_source_column_order(self):
        columns=toy_columns()
        for i,f in enumerate(FEATURE_COLUMNS):
            if f not in {"median_view_price_7d","view_price_unavailable_7d"}:columns[f]=np.full(4,i)
        a=matrix_from_columns(columns)[1]
        b=matrix_from_columns(dict(reversed(list(columns.items()))))[1]
        np.testing.assert_equal(a,b)
        self.assertEqual(a[0,FEATURE_COLUMNS.index("n_sessions_7d")],6)

    def test_masked_price_stays_missing_not_zero(self):
        cols=toy_columns()
        cols["median_view_price_7d"]=np.ma.array([2.0,9999.0,4.0,6.0],mask=[False,True,False,False])
        x=matrix_from_columns(cols)[1]
        self.assertTrue(np.isnan(x[1,FEATURE_COLUMNS.index("median_view_price_7d")]))

    def test_nonbinary_target_cannot_be_silently_truncated(self):
        cols=toy_columns();cols[TARGET]=np.array([0,0.5,0,1])
        with self.assertRaises(ValueError):matrix_from_columns(cols)

    def test_imputer_and_scaler_fit_training_only(self):
        _,x,y=matrix_from_columns(toy_columns())
        with threadpool_limits(limits=1):model=logistic_model().fit(x,y)
        price=FEATURE_COLUMNS.index("median_view_price_7d")
        self.assertEqual(model.named_steps["impute"].statistics_[price],4.0)
        statistics=model.named_steps["impute"].statistics_.copy()
        means=model.named_steps["scale"].mean_.copy()
        validation=x.copy();validation[:,price]=[10000,np.nan,10000,10000]
        valid_probabilities(model.predict_proba(validation)[:,1])
        np.testing.assert_equal(statistics,model.named_steps["impute"].statistics_)
        np.testing.assert_equal(means,model.named_steps["scale"].mean_)
        transformed=model.named_steps["impute"].transform(validation)
        self.assertEqual(transformed[1,price],4.0)
        self.assertEqual(transformed.shape[1],12) # Existing missing indicator, no new input.

    def test_repeated_logistic_fit_predictions_identical(self):
        _,x,y=matrix_from_columns(toy_columns())
        with threadpool_limits(limits=1):
            first=logistic_model().fit(x,y).predict_proba(x)
            second=logistic_model().fit(x,y).predict_proba(x)
        np.testing.assert_array_equal(first,second)

    def test_xgboost_native_missing_and_deterministic_cpu_predictions(self):
        rng=np.random.default_rng(5)
        x=rng.uniform(0,10,size=(60,12));y=(x[:,0]>5).astype(int)
        x[::7,10]=np.nan
        with threadpool_limits(limits=1):
            first=xgboost_model(n_estimators=15,early_stopping_rounds=3,min_child_weight=1)
            second=xgboost_model(n_estimators=15,early_stopping_rounds=3,min_child_weight=1)
            first.fit(x,y,eval_set=[(x,y)],verbose=False)
            second.fit(x,y,eval_set=[(x,y)],verbose=False)
            a=valid_probabilities(first.predict_proba(x)[:,1])
            b=valid_probabilities(second.predict_proba(x)[:,1])
        np.testing.assert_array_equal(a,b)

    def test_probability_range_and_shape_guards(self):
        for invalid in ([np.nan],[np.inf],[-0.01],[1.01],[[0.5,0.5]]):
            with self.assertRaises(ValueError):valid_probabilities(invalid)
        np.testing.assert_equal(valid_probabilities([0.0,1.0]),[0.0,1.0])

    def test_metrics_on_known_perfect_ranking(self):
        result=evaluate([0,1,1,0],[0.1,0.8,0.6,0.2])
        self.assertEqual(result["average_precision"],1.0)
        self.assertEqual(result["roc_auc"],1.0)
        self.assertAlmostEqual(result["brier_score"],0.0625)
        self.assertAlmostEqual(result["log_loss"],-np.log([0.9,0.8,0.6,0.8]).mean())
        self.assertEqual(result["precision_at_top_10_percent"],1.0)
        self.assertEqual(result["recall_at_top_10_percent"],0.5)
        self.assertEqual(result["lift_at_top_10_percent"],2.0)

    def test_average_precision_uses_step_weighted_definition(self):
        result=evaluate([1,0,1,0],[0.9,0.8,0.2,0.1])
        self.assertAlmostEqual(result["average_precision"],5/6)
        self.assertEqual(result["roc_auc"],0.75)

    def test_ties_are_deterministic_and_need_no_labels(self):
        a=top_indices(np.full(101,0.5))
        b=top_indices(np.full(101,0.5))
        np.testing.assert_equal(a,b)
        self.assertEqual(len(a),11)
        self.assertNotEqual(a.tolist(),list(range(11)))

    def test_undefined_roc_and_recall_return_none(self):
        result=evaluate([0,0,0],[0.1,0.2,0.3])
        self.assertIsNone(result["roc_auc"])
        self.assertIsNone(result["recall_at_top_10_percent"])

    def test_constant_probability_reliability_has_one_bin(self):
        rows=reliability_bins([0,0,1,0],np.full(4,0.1))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["customers"],4)
        self.assertEqual(rows[0]["observed_purchase_rate"],0.25)


class PublishedModelingChecks(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parents[1]
        path=self.root/"docs/phase3/validation_summary.json"
        if not path.exists():self.skipTest("Validation experiment has not been run")
        self.result=json.loads(path.read_text())

    def test_validation_only_results_and_frozen_missingness(self):
        result=self.result
        self.assertEqual(result["evaluated_splits"],["validation"])
        self.assertFalse(result["test_predictions_generated"])
        self.assertFalse(result["test_performance_computed"])
        self.assertEqual(result["feature_columns"],list(FEATURE_COLUMNS))
        source=json.loads((self.root/"docs/phase2/summary.json").read_text())
        for split in ("train","validation","test"):
            self.assertEqual(result["missing_counts"][split],{f:source["feature_distributions"][split][f]["missing"] for f in FEATURE_COLUMNS})
        for row in result["models"].values():
            self.assertNotIn("test",row)
            self.assertEqual(row["validation"]["customers"],53089)
            self.assertEqual(row["validation"]["positive_labels"],1150)
            self.assertTrue(row["saved_model_roundtrip_predictions_identical"])

    def test_model_artifacts_and_source_fingerprints(self):
        from growthlab.acquire import digest
        for relative,expected in self.result["source_sha256"].items():self.assertEqual(digest(self.root/relative),expected)
        for relative,info in self.result["artifacts"].items():
            if not (self.root/relative).exists():self.skipTest("Ignored model artifacts not present")
            self.assertEqual(digest(self.root/relative),info["sha256"])

    def test_actual_split_keys_disjoint_without_loading_test_predictors(self):
        from growthlab.audit import connect
        if not (self.root/"data/features/phase2/primary/train.parquet").exists():self.skipTest("Local feature data unavailable")
        with tempfile.TemporaryDirectory() as directory:
            con=connect(":memory:",Path(directory)/"spill","256MB")
            try:
                _,hashes=verify_inputs(con,self.root)
                self.assertEqual(hashes,self.result["data_hashes"])
            finally:con.close()

    def test_saved_validation_probabilities_reconcile_with_report(self):
        path=self.root/"data/models/phase3/validation_predictions.npz"
        if not path.exists():self.skipTest("Ignored validation predictions unavailable")
        with np.load(path) as predictions:
            self.assertEqual(set(predictions.files),{"user_id","target","dummy","logistic_regression","xgboost"})
            self.assertEqual(len(np.unique(predictions["user_id"])),53089)
            for name in ("dummy","logistic_regression","xgboost"):
                recomputed=evaluate(predictions["target"],predictions[name])
                self.assertEqual(recomputed,self.result["models"][name]["validation"])


if __name__=="__main__":unittest.main()
