# Phase 12B — free Streamlit Community Cloud preparation

Status: **release preparation verified and approved for preservation; not deployed**. The user cancelled
Google Cloud Run deployment. No GCP service, registry, API enablement, billing
change or CityPulse access is authorized. Only free Streamlit Community Cloud is
the proposed public host. The verified Docker implementation remains intact.

The previous uncommitted Cloud Run proposal is superseded and removed. Native
AMD64 Docker CI remains an optional free compatibility check, not a hosting or
registry-publishing pipeline. It is retained as a manual-only, public-repository-guarded portability check;
no native AMD64 run has been performed.

## 1. Phase 12A preservation — completed

Commit: **`c1e53694be8678b20184788179e34fe1b0ffb587`**
(`Package Phase 12A Decision Studio Docker runtime and local verification`).
The nine approved files were audited and pushed to `origin/main`; local HEAD and
GitHub main matched, and the working tree was clean before Phase 12B changes.

The full **344-test suite passed with no skips** before preservation. The ARM64
image identity/size matched the approved receipt; a fresh localhost-only container
was healthy, its health helper succeeded, and startup logs had no errors or
external-address discovery. All 33 recorded packaging/runtime fingerprints
matched. Frozen Module 1/RetailHero checks, 82 prior file states and additional
raw/cleaned/ranking hashes passed without another outcome evaluation.

Only README, Dockerfile, `.dockerignore`, the container lock, two container
helpers, packaging tests and two small documentation/evidence files were
committed. No datasets, models, predictions, credentials or generated large
artifacts were staged. The verification receipt retains its original phase-time
status; README/report now describe the approved preservation state.

## 2. Native AMD64 CI — prepared, not executed

### Existing configuration and optional execution

There was no existing GitHub Actions workflow to duplicate. Repository visibility
was confirmed public through GitHub's read-only API. AMD64 verification is **not
a Community Cloud deployment prerequisite**: it is only useful for preserving
Docker portability.

The workflow is **manual-only** (`workflow_dispatch`), with no push, PR or scheduled
trigger. Its job checks `github.event.repository.private == false` before any
runner is allocated, and uses the standard `ubuntu-24.04` runner. If the repository
becomes private, the job is skipped. Standard runners are free for public
repositories under the currently documented policy; no larger/self-hosted runner,
paid add-on, registry upload or cloud authentication is configured.
[GitHub runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)

**No native AMD64 run or Actions run URL exists, and no pass is claimed.** After
preservation, the optional job can remain unrun. Review the public-repo/free-runner
policy again before any manual dispatch; this release push does not trigger it.

### What the proposed job does

File: [`.github/workflows/studio-amd64.yml`](../../.github/workflows/studio-amd64.yml).

One job uses **`ubuntu-24.04`**, the standard GitHub-hosted x64 runner, with a
20-minute limit and cancellation of superseded runs. A native `uname -m` check
and the audit helper's architecture check prevent silently using emulation.
[GitHub runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)

The job:

1. Checks out source using an immutable official `actions/checkout` v6 commit,
   with `contents: read` and no persisted Git credentials.
2. Runs the standard-library container tests and builds the **existing**
   Dockerfile with `--platform linux/amd64`. No QEMU action, replacement base,
   dependency update, registry login, push or cloud authentication is added.
3. Starts the image with localhost port 8502, UID 10001, 1 CPU/512 MiB, read-only
   root filesystem, temporary `/tmp`, dropped capabilities and no privileges.
4. Requires HTTP **200 / `ok`** and Docker **healthy**, then verifies architecture,
   isolation, all 31 runtime file hashes, 36 pinned versions, twelve evidence
   sources, frozen headline metrics and exact planning/reward outputs.
5. Installs only Playwright/pyee/greenlet on the runner, taking their exact pins
   from the existing test lock. Scientific dependencies remain solely in the
   image. It reuses the existing browser smoke script for seven pages, desktop/
   mobile layouts, planning, reward, budget and ranking interactions.
6. Emits small runtime/browser summaries into the Actions job summary, inspects
   logs and post-browser memory, and always removes its own test container.

The image is ephemeral on the runner and is **never uploaded**, even as a build
artifact. No GCP secrets, OIDC token permissions, registry permissions or deployment
job exist. There are no automatic event triggers. This does not rerun the data-dependent
research suite in CI; the complete suite is verified in the existing local
research environment instead.

The helper [scripts/verify_container_runtime.py](../../scripts/verify_container_runtime.py)
uses the Python standard library and Docker CLI. Its default is AMD64 and it
fails before Docker access on a mismatched host. An explicit ARM64 argument is
available to check the harness locally; results identify that platform plainly.
It does not import a research fitting/evaluation entry point or open outcome
tables. Six additional tests cover native guards, localhost-only targets,
non-root/resource isolation, exact runtime files and workflow permissions.

### Checks actually performed locally

- Official checksum-verified **actionlint v1.7.12** reports no workflow errors.
- The twelve container test cases (six existing, six new) pass.
- The new runtime helper passes on **Linux ARM64**, with exact file/version/
  evidence checks and no dataset/model/Mac-path dependencies. This is harness
  validation, not AMD64 evidence.
- The existing browser harness passes against that local container: seven
  workspaces, 13 view checks and seven interaction checks, without browser errors.
- The initial harness-stage suite passed **350 tests**, no skips: the preserved
  344 plus six CI guard tests. The final hosting-release suite passes **353**
  after three additional hosting checks, as recorded below.

The [local checks receipt](phase12b_local_checks.json) explicitly records that
the AMD64 and GitHub Actions results are pending. The Dockerfile, dependency
locks, application, models and research outputs are unchanged from Phase 12A.

## 3. Free hosting preparation — not a deployment

[Streamlit Community Cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud)
is documented as free. No Google Cloud project, credit card, container registry,
billable infrastructure or application API key is part of this plan. Do not switch
to a paid host or paid workaround if the free service is insufficient; stop and
retain the local app instead. No hosting account, app or OAuth connection was
created in this phase.

The root **requirements.txt** contains only `-r requirements-container.lock`.
That file includes the unchanged dashboard lock plus the existing Linux-only
watchdog pin. Thus the host gets the same 36 Linux package versions as Docker,
without duplicating or updating any versions. A recognized requirements file
also prevents the host from falling back to the research-oriented pyproject.
No higher-priority uv.lock, Pipfile or environment.yml exists at the entry point.
[Dependency discovery](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies)

| Setting | Proposed value after explicit deployment approval |
| --- | --- |
| Hosting product | Free **Streamlit Community Cloud**, not Streamlit in Snowflake or a paid cloud service |
| Repository / branch | `sanjeevani1193/GrowthLab` / reviewed `main` revision containing the requirements wrapper |
| Main file | `streamlit_app.py` at the repository root |
| Python | Explicitly choose **3.14** in Advanced settings to match the verified runtime minor version; the host manages patch versions. If unavailable, stop for compatibility review rather than silently changing pins |
| Requirements | Root `requirements.txt` → existing container/Linux lock → existing Studio lock |
| Streamlit settings | Preserve the approved root `.streamlit/config.toml` |
| Secrets | None for the application; leave the application Secrets field empty |
| App URL | Request a suitable available `streamlit.app` subdomain; none has been reserved |
| Docker | Retain local image, Dockerfile, health probe and non-root verification; Community Cloud runs the Python entry point, not this Docker image |
| Data | Read only permitted committed aggregate evidence; no raw files, models, customer tables or downloads |

Python selection and repository/entry-point fields are described in the
[official deployment instructions](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy).
The published Python default is 3.12; do not assume it matches our tested 3.14.
No packages.txt or additional system package has been added without a demonstrated
need. Installing the local project with `pip install .` is unnecessary and would
bring in research dependencies.

## 4. Verification and free-service limitations

After the hosting change, **353 tests pass with no skips**: the previous 350
plus three free-host preparation checks. A local requirements dry run resolved
the wrapper without installing or changing packages. All 33 approved runtime/
Docker fingerprints still match. A Git-tracked-file audit found no datasets,
model weights, predictions, credential files or files above 10 MiB.

The application was already verified without any local data/model directory.
The unchanged Linux Docker runtime passes its aggregate fingerprints and planning/
reward calculations. These are preparation checks, **not proof that a Community
Cloud build or public WebSocket session has run**. Managed-host build logs, exact
installed versions and seven-page browser behavior must be verified after a
separately approved deployment.

Community Cloud uses its own Linux environment; the Docker base is not deployed
there. Supported Python selection, dependency installation and resource headroom
are therefore release gates. Preserve the pins if a managed build fails and
investigate before proposing any change.

The host controls resources, app sleeping/restarts and some settings. Do not
promise an always-on service or a fixed memory allowance based on old forum posts.
The local memory measurements do not establish the managed host's limits. Widget
state is temporary; a restart may reset hypothetical inputs. Resource exhaustion
must not trigger a paid-service fallback.

The provider's documentation states that hosting is in the United States and
that managed settings can override local configuration, including usage telemetry.
We cannot promise the Docker environment's exact region or telemetry behavior on
this host. Review GitHub authorization scopes before connecting; this repository
is public, and no private-repository access is needed for the proposed demo.
[Managed-platform limitations](https://docs.streamlit.io/deploy/streamlit-community-cloud/status)

The provider clones source from GitHub rather than using Docker's file allowlist.
Only approved source, aggregate reports and figures may be committed; raw data,
models, predictions and credentials must stay ignored. No app upload/search or
customer-scoring feature is introduced. Public result displays remain historical
prediction/assumption-dependent analysis, while simulations and reward scenarios
remain hypothetical.

## 5. Later approval, verification and withdrawal steps

Nothing below has been executed:

1. Preserve the reviewed hosting wrapper, optional CI and documentation. Do not
   dispatch the manual Docker job as part of deployment; it is not required.
2. Obtain separate approval to create the free Community Cloud app. Connect only
   the intended GitHub repository, verify the product is free Community Cloud,
   and enter the repository, branch, entry point and Python version above. Do not
   enter billing details or app secrets, enable GCP APIs or use CityPulse resources.
3. After an approved build, inspect installation logs for the exact pins. Verify
   all seven workspaces, frozen headline metrics, experiment design, negative-EUR
   reward calculations, saved policy budgets, ranking cutoffs and source links.
   Inspect desktop/mobile rendering, reconnects and wake-from-sleep behavior.
4. Review actual managed-host memory/errors and provider privacy settings before
   calling the public demo verified. No current public URL or launch date is claimed.

Once connected, source pushes on the deployment branch may update the public app.
Future commit/push approvals must account for that. For rollback, use a previous
**Community-Cloud-compatible** revision retaining the requirements wrapper and
approved evidence; a pre-wrapper research commit is not automatically a hosting
rollback. For a first-release failure, withdraw/delete the Community Cloud app
and keep local Docker available. Remove only the app connection/permissions that
belong to GrowthLab. No GCP cleanup, billing change or CityPulse action is needed
because none was created or accessed.

## 6. Community Cloud launch guide and troubleshooting

These are instructions for a **separately approved** deployment, not actions taken
by this release-preparation commit:

1. Visit **https://share.streamlit.io**, choose the free Community Cloud product,
   and review GitHub authorization for the public GrowthLab repository.
2. Select **Create app**, use an existing GitHub app, and enter repository
   **sanjeevani1193/GrowthLab**, branch **main**, main file **streamlit_app.py**.
3. In **Advanced settings**, select **Python 3.14**. The local tested interpreter
   is **3.14.7**; managed patch versions may differ. Leave app **Secrets empty**.
   If 3.14 is unavailable, stop for compatibility review without changing pins.
4. Only with deployment approval, choose an available subdomain and select
   **Deploy**. No GCP project, registry, card or paid upgrade is part of this flow.
5. Inspect dependency/build logs, then verify every workspace and widget using
   the checklist above before advertising the URL. After launch, pushes to main
   may update the live app; account for that in future preservation approvals.

### Public runtime evidence to keep tracked

The app reads the following twelve aggregate JSON files, with SHA-256 checks in
`docs/decision_studio/evidence_manifest.json` (also tracked). The manifest and
files have all been checked against the approved Phase 12A hashes.

| Source | Required tracked file |
| --- | --- |
| `purchase` | `docs/phase4/test_summary.json` |
| `purchase_spec` | `docs/phase2_specification.json` |
| `experiment` | `docs/causal/phase5/experiment_summary.json` |
| `uplift` | `docs/causal/phase7/final_summary.json` |
| `planning` | `docs/experiments/phase8a_planning_summary.json` |
| `aa` | `docs/experiments/phase8b_aa_summary.json` |
| `ab` | `docs/experiments/phase8c_ab_summary.json` |
| `reward_config` | `docs/rewards/phase9b_scenario_config.json` |
| `reward_summary` | `docs/rewards/phase9b_scenario_summary.json` |
| `reward_reference` | `docs/rewards/phase9a_reference_summary.json` |
| `ranking` | `docs/ranking/phase10c_summary.json` |
| `ranking_protocol` | `docs/ranking/phase10c_protocol.json` |

All files are aggregates/specifications, not customer-level datasets. The public
repository also retains approved methodology and small figures. The deployment
requires no ignored files or local absolute paths. The `src/` import path is
resolved relative to `streamlit_app.py`; Community Cloud starts at the repo root.

### Troubleshooting

- **Import/dependency error:** check root requirements.txt and both included locks
  are present on main. No higher-priority manager file should shadow them. Do not
  install the research project or add ML dependencies to fix a hosting error.
- **Python/wheel conflict:** confirm 3.14 and inspect the exact failing pin. Stop
  for review rather than upgrade/downgrade versions or buy a different host.
- **Missing evidence/fingerprint error:** restore the named approved aggregate
  and manifest from Git. Do not recreate test outcomes, retrain or regenerate
  research to make the dashboard start.
- **Sleeping/resource error:** wake/restart the free app as supported, inspect
  logs and profile within free limits. Do not promise permanent uptime or buy
  additional capacity. Return to local Docker if the free platform is unsuitable.
- **Display or reconnect issue:** compare with local seven-page verification and
  inspect provider settings. Do not disable XSRF/CORS or remove caveats to conceal
  an issue. Hypothetical widget state can reset after restart.

Rollback keeps the requirements wrapper: use the last known compatible hosted
revision plus its approved evidence. If no hosted release has succeeded, withdraw
or delete the Community Cloud app instead. Rollback/withdrawal itself requires
appropriate authorization; no hosted app exists to alter in this preparation.

## 7. Release preparation state

The Phase 12A preservation commit remains
`c1e53694be8678b20184788179e34fe1b0ffb587`. Dockerfile, Docker helpers, dependency
locks, Streamlit configuration, application source and research evidence remain
unchanged. The reviewed release files are approved for preservation; public
deployment remains a separate action.

Pending: separate permission for free public deployment and subsequent managed-
host verification. Native AMD64 CI is optional, remains unrun, and does not block
Community Cloud preparation. **No Google Cloud deployment or billable fallback is planned.**

### Final preservation verification

The final local run passed **353 tests, no skips**, in **16.398 seconds**. Chromium
verified the unchanged local app on port 8502: seven workspaces, thirteen desktop/
mobile views and seven interaction flows, with no browser errors. Requirements
dry-run, all twelve tracked source fingerprints plus the manifest, 33 approved
app/Docker fingerprints and frozen model/artifact checks passed. The optional
workflow passes actionlint and its tests require the exact manual-only trigger
and public-repository guard. This release is not a hosting deployment.
