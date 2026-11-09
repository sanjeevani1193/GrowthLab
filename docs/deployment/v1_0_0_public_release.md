# GrowthLab v1.0.0 — public portfolio release

**Live demo:** https://growthlab-decision-studio.streamlit.app/

The user deployed the application to **free Streamlit Community Cloud**. Public
verification was performed on **2026-11-09 (Europe/Berlin)** using Chromium. The
application baseline is `0fd072c009c2da59ad1807cab05ab418a797ee76`; this release
adds documentation and existing screenshots, with no application, dependency,
model, research-result or statistical-method change.

## Public verification

The URL returned **HTTP 200**. Browser checks entered the actual Streamlit app
inside the Community Cloud hosting frame, rather than treating a successful
response from the outer hosting shell as proof of application readiness.

| Workspace | Observed result |
| --- | --- |
| Overview | Loaded; AUC 0.8487, observed training SMS/control difference +3.39 pp, simulated power 79.3%, macro Recall@10 18.42% |
| Purchase Intelligence | Loaded; AP 0.1025, top-decile recall 59.23%, lift 5.92×, 324/547 purchasers |
| RetailHero Targeting | Loaded with observed training rates and causal limitations; saved 10% budget selected 4,001 contacts |
| Experiment Lab | Loaded; balanced plan 5,886 customers; changing treatment allocation to 30% produced 6,949 while saved simulation power stayed 79.3% |
| Reward Economics | Loaded; default hypothetical net -€550.00; zero reward changed hypothetical net to €600.00 |
| Product Ranking | Loaded; NDCG@10 0.21625, macro ceiling 32.04%, missing purchased pairs 70.69%; K=20 macro/micro recall changed to 22.69% / 18.85% |
| Methodology | Loaded with study descriptions, provenance and limitations |

All seven workspaces and four additional interaction flows passed, without browser
page errors or Streamlit exception displays. Visible charts rendered. The
[small verification receipt](v1_0_0_public_verification.json) records observations.
These checks read public aggregate findings or session-local hypothetical
calculations; they did not refit models, evaluate raw outcome tables or change
the deployment's settings.

The generic web reader could not access the dynamic site, but actual Chromium
verification succeeded. No login, administrative deployment action, registry
upload or paid resource was required. No optional CI job was dispatched.

## Local tests and preserved evidence

The full local suite passed **353 tests, no skips**, in **16.883 seconds**.
The existing headline-metrics block and all methodology/research sections after
the completed-study table remain byte-identical in README. Original reports,
aggregate JSON, dependency locks, Docker configuration, source code, data and
models remain unchanged. Integrity checks verify the approved runtime fingerprints
and frozen research artifacts without recomputing conclusions.

The public interface presents frozen predictive/ranking evidence and explicitly
assumption-dependent RetailHero analysis. A/A and A/B results remain synthetic;
reward economics remains hypothetical. No online conversion, revenue or causal
improvement is inferred from the public release.

## Screenshots and privacy

README includes two **existing local Chromium screenshots**, copied without
editing: Overview and Product Ranking. They show the same approved application,
not mockups or invented outcomes. They are labeled local captures because public
hosting controls may differ. Their hashes/provenance are in the receipt.

Screenshots and documentation were reviewed for customer-level records, secrets,
local paths and model artifacts. Only aggregate figures are visible. No raw data,
prediction tables, model weights, credentials or caches belong in this release.

## Scope and remaining limitations

This is a functional desktop Chromium verification, not a multi-user load test,
an uptime guarantee or a managed-host backend inspection. The reviewed Python
target remains 3.14, tested locally with 3.14.7; the provider's backend patch and
resource limits were not independently read from the public UI.

Free hosting can sleep or restart and reset temporary widget state. The original
analytical limitations remain in the application and methodology reports.
Optional native AMD64 Docker CI remains manual-only, public-repository guarded
and **unrun**; it is not required by Community Cloud. No blocking functional issue
was found in the checks above.

After final documentation/privacy review and matching GitHub main verification,
the annotated **v1.0.0** tag identifies this documentation release. No Google Cloud
Run, billable service or CityPulse infrastructure is used or changed.
