"""Small publication-ready validation figures; no access to test data."""

import os
from pathlib import Path

import numpy as np


def plot_results(root,y,predictions,result):
    # Keep font caches local and ignored, including on restricted Mac environments.
    cache=root/"data/models/phase3/matplotlib-cache"
    cache.mkdir(parents=True,exist_ok=True)
    os.environ["MPLCONFIGDIR"]=str(cache)
    (cache/"xdg").mkdir(exist_ok=True)
    os.environ.setdefault("XDG_CACHE_HOME",str(cache/"xdg"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.metrics import precision_recall_curve,roc_curve

    output=root/"docs/phase3/figures"
    output.mkdir(parents=True,exist_ok=True)
    colors={"dummy":"#737373","logistic_regression":"#2363a8","xgboost":"#b65122"}
    labels={"dummy":"Training-prior dummy","logistic_regression":"Logistic Regression","xgboost":"XGBoost"}
    plt.rcParams.update({"font.size":10,"axes.spines.top":False,"axes.spines.right":False,"figure.dpi":130})
    title=f"Validation only · {int(y.sum()):,} future purchasers / {len(y):,} customers"

    fig,ax=plt.subplots(figsize=(7,5),layout="constrained")
    for name,p in predictions.items():
        precision,recall,_=precision_recall_curve(y,p,drop_intermediate=True)
        ap=result["models"][name]["validation"]["average_precision"]
        # Increasing recall: use the precision at the RIGHT endpoint, matching
        # AP's recall-increment weighting (especially important for constant scores).
        ax.step(recall[::-1],precision[::-1],where="pre",color=colors[name],label=f"{labels[name]} · AP {ap:.4f}")
    ax.axhline(float(np.mean(y)),color="#999999",linestyle=":",label="Validation prevalence")
    ax.set(xlabel="Recall: fraction of future purchasers found",ylabel="Precision: fraction of selected customers purchasing",
           title="Precision–recall\n"+title,xlim=(0,1),ylim=(0,1))
    ax.legend(fontsize=9)
    fig.savefig(output/"precision_recall.png",dpi=150)
    plt.close(fig)

    fig,ax=plt.subplots(figsize=(7,5),layout="constrained")
    for name,p in predictions.items():
        fpr,tpr,_=roc_curve(y,p,drop_intermediate=True)
        auc=result["models"][name]["validation"]["roc_auc"]
        ax.plot(fpr,tpr,color=colors[name],label=f"{labels[name]} · AUC {auc:.4f}")
    ax.plot([0,1],[0,1],color="#999999",linestyle=":")
    ax.set(xlabel="False-positive rate",ylabel="True-positive rate (recall)",title="ROC\n"+title,xlim=(0,1),ylim=(0,1))
    ax.legend(loc="lower right",fontsize=9)
    fig.savefig(output/"roc.png",dpi=150)
    plt.close(fig)

    fig,(ax,hist)=plt.subplots(2,1,figsize=(7,7),height_ratios=[2.2,1],layout="constrained")
    limit=max(0.06,max(max(r["mean_predicted_probability"],r["observed_purchase_rate"])
                      for model in result["models"].values() for r in model["reliability"])*1.2)
    for name,p in predictions.items():
        bins=result["models"][name]["reliability"]
        means=[r["mean_predicted_probability"] for r in bins]
        rates=[r["observed_purchase_rate"] for r in bins]
        ax.plot(means,rates,marker="o",color=colors[name],label=labels[name])
        hist.hist(p,bins=np.linspace(0,1,41),histtype="step",color=colors[name],label=labels[name])
    ax.plot([0,limit],[0,limit],color="#555555",linestyle=":",label="Perfect binned calibration")
    ax.set(xlabel="Mean predicted purchase probability",ylabel="Observed purchase fraction",
           title="Reliability: up to 5 quantile bins\n"+title,xlim=(0,limit),ylim=(0,limit))
    ax.legend(fontsize=9)
    hist.set(xlabel="Predicted purchase probability",ylabel="Customers (log scale)",yscale="log",xlim=(0,1))
    fig.savefig(output/"calibration.png",dpi=150)
    plt.close(fig)

    fig,axes=plt.subplots(1,2,figsize=(12,5.5),layout="constrained")
    coefficient=result["models"]["logistic_regression"]["standardized_coefficients"]
    names=sorted(coefficient,key=lambda key:abs(coefficient[key]))
    axes[0].barh(names,[coefficient[f] for f in names],color=["#2363a8" if coefficient[f]>=0 else "#b65122" for f in names])
    axes[0].axvline(0,color="#555555",linewidth=0.8)
    axes[0].set(title="Logistic Regression",xlabel="Coefficient per training standard deviation")
    gains=result["models"]["xgboost"]["selected_tree_total_gain_share"]
    names=sorted(gains,key=gains.get)
    axes[1].barh(names,[gains[f] for f in names],color="#b65122")
    axes[1].set(title="XGBoost: selected trees only",xlabel="Share of total training split gain")
    fig.suptitle("Descriptive model importance · correlated features share credit · not causal effects")
    fig.savefig(output/"feature_importance.png",dpi=150)
    plt.close(fig)
    from growthlab.acquire import digest
    result["figures"]={str(p.relative_to(root)):{"bytes":p.stat().st_size,"sha256":digest(p)}
                       for p in sorted(output.glob("*.png"))}
