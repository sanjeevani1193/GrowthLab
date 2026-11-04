"""Frozen test PR/reliability figures; only called after the plan is frozen."""

import os

import numpy as np

from growthlab.acquire import digest


def plot_test_results(root,labels,predictions,result):
    cache=root/"data/models/phase4/plot-cache"
    cache.mkdir(parents=True,exist_ok=True)
    os.environ["MPLCONFIGDIR"]=str(cache)
    (cache/"xdg").mkdir(exist_ok=True)
    os.environ.setdefault("XDG_CACHE_HOME",str(cache/"xdg"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.metrics import precision_recall_curve
    names={"dummy":"Training-prior dummy","logistic_regression":"Logistic Regression",
           "xgboost":"XGBoost: primary raw","xgboost_calibrated":"XGBoost + validation sigmoid: secondary"}
    colors={"dummy":"#737373","logistic_regression":"#2363a8","xgboost":"#b65122","xgboost_calibrated":"#238455"}
    output=root/"docs/phase4/figures"
    output.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({"font.size":10,"axes.spines.top":False,"axes.spines.right":False})
    title=f"Frozen test · {int(np.sum(labels)):,} future purchasers / {len(labels):,} customers"
    fig,ax=plt.subplots(figsize=(8,5.5),layout="constrained")
    for name,p in predictions.items():
        precision,recall,_=precision_recall_curve(labels,p,drop_intermediate=True)
        ap=result["models"][name]["test"]["average_precision"]
        ax.step(recall[::-1],precision[::-1],where="pre",color=colors[name],
                linestyle="--" if name=="xgboost_calibrated" else "-",label=f"{names[name]} · AP {ap:.4f}")
    ax.axhline(float(np.mean(labels)),color="#999999",linestyle=":",label="Test prevalence")
    ax.set(xlabel="Recall: fraction of future purchasers found",ylabel="Precision: fraction of selected customers purchasing",
           title="Precision–recall\n"+title,xlim=(0,1),ylim=(0,1))
    ax.legend(fontsize=8)
    fig.savefig(output/"precision_recall.png",dpi=150)
    plt.close(fig)
    fig,(ax,hist)=plt.subplots(2,1,figsize=(8,7),height_ratios=[2.2,1],layout="constrained")
    limit=max(0.06,max(max(r["mean_predicted_probability"],r["observed_purchase_rate"])
                      for model in result["models"].values() for r in model["reliability"])*1.2)
    for name,p in predictions.items():
        rows=result["models"][name]["reliability"]
        ax.plot([r["mean_predicted_probability"] for r in rows],[r["observed_purchase_rate"] for r in rows],
                color=colors[name],marker="o",linestyle="--" if name=="xgboost_calibrated" else "-",label=names[name])
        hist.hist(p,bins=np.linspace(0,1,41),histtype="step",color=colors[name])
    ax.plot([0,limit],[0,limit],color="#555555",linestyle=":",label="Perfect binned calibration")
    ax.set(xlabel="Mean predicted purchase probability",ylabel="Observed purchase fraction",
           title="Reliability: up to 5 quantile bins\n"+title,xlim=(0,limit),ylim=(0,limit))
    ax.legend(fontsize=8)
    hist.set(xlabel="Predicted purchase probability",ylabel="Customers (log scale)",yscale="log",xlim=(0,1))
    fig.savefig(output/"calibration.png",dpi=150)
    plt.close(fig)
    result["figures"]={str(p.relative_to(root)):{"bytes":p.stat().st_size,"sha256":digest(p)} for p in sorted(output.glob("*.png"))}
