# GrowthLab

A staged Customer Intelligence & Causal Decision Science portfolio project.

**Current stage: Phase 0 — setup and dataset feasibility completed.**

The first planned module predicts whether a customer purchases in the next
30 days using their first seven observed days of activity. The prediction is
made at the end of those seven days. A separate causal inference and uplift
modeling module is a later project stage; it has not been implemented.

Completed: repository inspection, minimal Python scaffold, dataset source and
usage checks, a bounded inspection of 100 real events, and a documented window
definition and evaluation proposal. No models, feature/label pipeline, API,
dashboard, or cloud resources have been built. No full dataset was downloaded.

Read [the Phase 0 feasibility report](docs/phase0_feasibility.md) for the schema,
evidence, limitations, resource plan, and exact next step.

## Data and attribution

Source: Michael Kechinov's
[eCommerce Events History in Cosmetics Shop on Kaggle](https://www.kaggle.com/datasets/mkechinov/ecommerce-events-history-in-cosmetics-shop),
provided by [REES46 Marketing Platform](https://rees46.com), whose
[dataset catalog](https://rees46.com/en/datasets) identifies the Cosmetics data.
The publisher permits free use with links to Kaggle and REES46. Kaggle labels
the license “Data files © Original Authors”; this is not a CC0 declaration.
Raw data stays outside Git. See [data handling](data/README.md).

## Local setup

Python 3.11 or newer; no runtime dependencies are needed for Phase 0.

```sh
python3 -m venv .venv
source .venv/bin/activate
```

`src/growthlab/` is the future Python package; `docs/` contains the feasibility
report and source evidence. No dependency installation or data download is
required to review this stage.

Next, after approval of the download scope: acquire the official monthly files
and implement a bounded, read-only data audit before creating features or labels.
