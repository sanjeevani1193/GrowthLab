# Multi-architecture index pinned to the verified official Python 3.14.7 image.
FROM python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    HOME=/tmp/growthlab-studio \
    XDG_CACHE_HOME=/tmp/growthlab-studio/.cache \
    PORT=8080

WORKDIR /app
COPY requirements-studio.lock requirements-container.lock ./
RUN python -m pip install --no-cache-dir --no-compile --only-binary=:all: -r requirements-container.lock \
    && python -m pip check \
    && groupadd --gid 10001 studio \
    && useradd --uid 10001 --gid studio --no-create-home --home-dir /tmp/growthlab-studio studio

# Cache bytecode for actual UI imports, without compiling unused library modules.
RUN PYTHONDONTWRITEBYTECODE=0 python -c "import streamlit, pandas, pyarrow, scipy.stats; import plotly.graph_objects as go; go.Figure([go.Bar(), go.Scatter(), go.Pie()])"

# Deliberate runtime allowlist: no editable project install or research packages.
COPY streamlit_app.py ./
COPY .streamlit/config.toml ./.streamlit/config.toml
COPY docker/entrypoint.py docker/healthcheck.py ./docker/
COPY src/growthlab/__init__.py ./src/growthlab/
COPY src/growthlab/studio/ ./src/growthlab/studio/
COPY src/growthlab/experimentlab/__init__.py src/growthlab/experimentlab/design.py ./src/growthlab/experimentlab/
COPY src/growthlab/rewards/__init__.py src/growthlab/rewards/economics.py src/growthlab/rewards/scenarios.py ./src/growthlab/rewards/
COPY docs/decision_studio/evidence_manifest.json ./docs/decision_studio/
COPY docs/phase4/test_summary.json ./docs/phase4/
COPY docs/phase2_specification.json ./docs/
COPY docs/causal/phase5/experiment_summary.json ./docs/causal/phase5/
COPY docs/causal/phase7/final_summary.json ./docs/causal/phase7/
COPY docs/experiments/phase8a_planning_summary.json docs/experiments/phase8b_aa_summary.json docs/experiments/phase8c_ab_summary.json ./docs/experiments/
COPY docs/rewards/phase9a_reference_summary.json docs/rewards/phase9b_scenario_config.json docs/rewards/phase9b_scenario_summary.json ./docs/rewards/
COPY docs/ranking/phase10c_summary.json docs/ranking/phase10c_protocol.json ./docs/ranking/

# Avoid external-IP discovery/logging locally; a future host can override this env.
ENV STREAMLIT_BROWSER_SERVER_ADDRESS=localhost
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "docker/healthcheck.py"]
ENTRYPOINT ["python", "docker/entrypoint.py"]
