"""Bounded-memory RetailHero audit, frozen splits, and training-only analysis.

Run --prepare before --analyze. The split manifest contains no outcomes. The
analysis entry point has no validation/test outcome loader or model fitting.
"""
import argparse
import csv
import json
import math
import platform
import resource
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist

import duckdb
import scipy
from scipy.stats import binomtest

from .acquire import sha256


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def quote(path):
    return "'" + str(path).replace("'", "''") + "'"


def records(con, sql):
    result = con.execute(sql)
    names = [c[0] for c in result.description]
    return [dict(zip(names, row)) for row in result.fetchall()]


def connect(root):
    local = root / "data/retailhero/work"
    local.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(local / "audit.duckdb"))
    con.execute("SET memory_limit='256MB'")
    con.execute("SET threads=1")
    con.execute(f"SET temp_directory={quote(local / 'spill')}")
    con.execute("SET max_temp_directory_size='1GB'")
    for name in ("uplift_train", "clients"):
        path = root / f"data/retailhero/raw/{name}.csv"
        # Keep identifiers as text, and audit invalid values before typed use.
        con.execute(f"CREATE OR REPLACE TEMP VIEW {name} AS SELECT * FROM "
                    f"read_csv({quote(path)}, header=true, all_varchar=true)")
    return con


def verify_inputs(root):
    source = json.loads((root / "docs/causal/phase5/acquisition.json").read_text())
    for f in source["files"]:
        path = root / f["path"]
        if path.stat().st_size != f["bytes"] or sha256(path) != f["sha256"]:
            raise ValueError("raw RetailHero input changed")
    return {f["path"]: f["sha256"] for f in source["files"]}


def audit(con):
    """Structural audit only: no target sums or target-by-treatment summaries."""
    result = {}
    expected = {"uplift_train": ["client_id", "treatment_flg", "target"],
                "clients": ["client_id", "first_issue_date", "first_redeem_date", "age", "gender"]}
    for table, columns in expected.items():
        actual = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
        if actual != columns:
            raise ValueError(f"unexpected {table} schema: {actual}")
        result[table] = {
            "rows": con.execute(f"SELECT count(*) FROM {table}").fetchone()[0],
            "schema": records(con, f"DESCRIBE SELECT * FROM {table}"),
            "missing": {c: con.execute(f'SELECT count(*) FROM {table} WHERE "{c}" IS NULL').fetchone()[0]
                        for c in columns},
            "duplicate_id_excess": con.execute(f"SELECT count(*)-count(DISTINCT client_id) FROM {table}").fetchone()[0],
        }
    invalid = con.execute("""SELECT count(*) FROM uplift_train WHERE
        treatment_flg IS NULL OR treatment_flg NOT IN ('0','1') OR
        target IS NULL OR target NOT IN ('0','1') OR client_id IS NULL""").fetchone()[0]
    result["invalid_experimental_rows"] = invalid
    result["client_ids_not_10_hex"] = {table: con.execute(f"SELECT count(*) FROM {table} WHERE NOT regexp_full_match(client_id, '[0-9a-f]{{10}}')").fetchone()[0]
                                        for table in expected}
    result["join"] = records(con, """SELECT count(*) AS experimental_rows,
        count(c.client_id) AS matched, count(*) FILTER (WHERE c.client_id IS NULL) AS unmatched
        FROM uplift_train e LEFT JOIN clients c USING (client_id)""")[0]
    result["clients_not_in_experiment"] = con.execute("SELECT count(*) FROM clients c ANTI JOIN uplift_train e USING(client_id)").fetchone()[0]
    result["assignment_counts"] = records(con, "SELECT cast(treatment_flg AS INTEGER) AS treatment_flg, count(*) AS n FROM uplift_train GROUP BY 1 ORDER BY 1") if not invalid else []
    result["client_quality"] = records(con, """SELECT
        min(try_cast(age AS INTEGER)) AS min_age, max(try_cast(age AS INTEGER)) AS max_age,
        count(*) FILTER (WHERE age IS NOT NULL AND try_cast(age AS INTEGER) IS NULL) AS age_parse_failures,
        count(*) FILTER (WHERE try_cast(age AS INTEGER)<0 OR try_cast(age AS INTEGER)>120) AS age_outside_0_120,
        count(*) FILTER (WHERE gender NOT IN ('M','F','U')) AS unexpected_gender,
        count(*) FILTER (WHERE first_issue_date IS NOT NULL AND try_cast(first_issue_date AS TIMESTAMP) IS NULL) AS issue_parse_failures,
        count(*) FILTER (WHERE first_redeem_date IS NOT NULL AND try_cast(first_redeem_date AS TIMESTAMP) IS NULL) AS redeem_parse_failures,
        cast(min(try_cast(first_issue_date AS TIMESTAMP)) AS VARCHAR) AS earliest_issue,
        cast(max(try_cast(first_issue_date AS TIMESTAMP)) AS VARCHAR) AS latest_issue,
        cast(min(try_cast(first_redeem_date AS TIMESTAMP)) AS VARCHAR) AS earliest_redeem,
        cast(max(try_cast(first_redeem_date AS TIMESTAMP)) AS VARCHAR) AS latest_redeem,
        count(*) FILTER (WHERE try_cast(first_redeem_date AS TIMESTAMP)<try_cast(first_issue_date AS TIMESTAMP)) AS redeem_before_issue
        FROM clients""")[0]
    result["gender_counts"] = records(con, "SELECT gender, count(*) AS n FROM clients GROUP BY gender ORDER BY gender")
    if (invalid or any(result[t]["duplicate_id_excess"] or result[t]["missing"]["client_id"] for t in expected)
            or result["join"]["unmatched"]):
        raise ValueError("experimental integrity failure: " + json.dumps(result))
    return result


def build_splits(con, seed):
    """Outcome-blind stratified permutation; exact counts per treatment arm."""
    if type(seed) is not int:
        raise ValueError("integer seed required")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE splits AS
        WITH ranked AS (
          SELECT client_id, cast(treatment_flg AS INTEGER) AS treatment_flg,
            row_number() OVER (PARTITION BY treatment_flg ORDER BY
              sha256('{seed}:' || treatment_flg || ':' || client_id), client_id) AS r,
            count(*) OVER (PARTITION BY treatment_flg) AS n
          FROM uplift_train
        ) SELECT client_id, treatment_flg,
          CASE WHEN r<=floor(0.6*n) THEN 'train'
               WHEN r<=floor(0.8*n) THEN 'validation' ELSE 'final_test' END AS split
        FROM ranked""")


def prepare(root):
    inputs = verify_inputs(root)
    docs = root / "docs/causal/phase5"
    design_path = docs / "design.json"
    design = json.loads(design_path.read_text())
    manifest_path = docs / "split_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        verify_split(root, manifest, inputs)
        return manifest
    con = connect(root)
    try:
        structural = audit(con)
        build_splits(con, design["seed"])
        out = root / "data/retailhero/splits"
        out.mkdir(parents=True, exist_ok=True)
        path = out / "customer_assignments.parquet"
        if path.exists():
            raise FileExistsError("split IDs already exist without manifest; refusing replacement")
        con.execute(f"COPY (SELECT * FROM splits ORDER BY client_id) TO {quote(path)} (FORMAT PARQUET)")
        counts = records(con, "SELECT split, treatment_flg, count(*) AS n FROM splits GROUP BY 1,2 ORDER BY 1,2")
        manifest = {"created_at_utc": datetime.now(timezone.utc).isoformat(),
                    "design_sha256": sha256(design_path), "seed": design["seed"],
                    "input_sha256": inputs, "path": str(path.relative_to(root)),
                    "sha256": sha256(path), "rows": structural["uplift_train"]["rows"],
                    "counts": counts, "outcomes_in_manifest_or_split_file": False}
        write_json(docs / "audit.json", structural)
        write_json(manifest_path, manifest)
        return manifest
    finally:
        con.close()


def verify_split(root, manifest, inputs):
    if (manifest["input_sha256"] != inputs or
            manifest["design_sha256"] != sha256(root / "docs/causal/phase5/design.json") or
            manifest["sha256"] != sha256(root / manifest["path"])):
        raise ValueError("frozen split/design/input integrity failure")


def wilson(successes, n):
    if type(successes) is not int or type(n) is not int or n <= 0 or not 0 <= successes <= n:
        raise ValueError("require integer successes in [0,n], n>0")
    z = NormalDist().inv_cdf(0.975)
    p, z2 = successes / n, z*z
    center = (p + z2/(2*n))/(1+z2/n)
    half = z*math.sqrt(p*(1-p)/n + z2/(4*n*n))/(1+z2/n)
    return max(0., center-half), min(1., center+half)


def experiment_statistics(treated_successes, treated_n, control_successes, control_n):
    """Newcombe 95% risk-difference CI and pooled two-sided z test."""
    lt, ut = wilson(treated_successes, treated_n)
    lc, uc = wilson(control_successes, control_n)
    pt, pc = treated_successes/treated_n, control_successes/control_n
    effect = pt-pc
    interval = [effect-math.hypot(pt-lt, uc-pc), effect+math.hypot(ut-pt, pc-lc)]
    pooled = (treated_successes+control_successes)/(treated_n+control_n)
    se = math.sqrt(pooled*(1-pooled)*(1/treated_n+1/control_n))
    z = effect/se if se else 0.
    return {"treated_n": treated_n, "treated_purchasers": treated_successes, "treated_rate": pt,
            "control_n": control_n, "control_purchasers": control_successes, "control_rate": pc,
            "difference": effect, "difference_pp": 100*effect,
            "ci95": interval, "ci95_pp": [100*v for v in interval],
            "z": z, "p_two_sided": math.erfc(abs(z)/math.sqrt(2)),
            "incremental_purchasers_per_1000": effect*1000,
            "incremental_per_1000_ci95": [v*1000 for v in interval]}


def assignment_check(treated_n, control_n):
    return {"treated_n": treated_n, "control_n": control_n,
            "assumed_allocation_probability": 0.5,
            "two_sided_binomial_p": float(binomtest(treated_n, treated_n+control_n, p=0.5).pvalue),
            "caveat": "Assumed 1:1 Bernoulli allocation, not a recovered protocol. Balance does not establish randomization; stratification constrains training counts."}


def training_view(con, split_path):
    # The WHERE predicate is fixed, never caller-selected. No holdout aggregate.
    con.execute(f"""CREATE OR REPLACE TEMP VIEW training AS
        SELECT e.client_id, cast(e.treatment_flg AS INTEGER) AS treatment_flg,
          cast(e.target AS INTEGER) AS target, c.first_issue_date, c.first_redeem_date,
          try_cast(c.age AS INTEGER) AS age, c.gender
        FROM uplift_train e JOIN read_parquet({quote(split_path)}) s USING(client_id)
        JOIN clients c USING(client_id) WHERE s.split='train'""")


def training_counts(con):
    return records(con, "SELECT treatment_flg, count(*) AS n, sum(target)::BIGINT AS purchasers FROM training GROUP BY 1 ORDER BY 1")


def training_balance(con):
    # No outcome conditioning: retain customers with missing/invalid demographics.
    age = records(con, """SELECT treatment_flg, count(*) AS n,
        avg(age) FILTER (WHERE age BETWEEN 0 AND 120) AS valid_age_mean,
        var_samp(age) FILTER (WHERE age BETWEEN 0 AND 120) AS valid_age_variance,
        count(*) FILTER (WHERE age IS NULL OR age NOT BETWEEN 0 AND 120) AS unavailable_age
        FROM training GROUP BY 1 ORDER BY 1""")
    denom = math.sqrt((age[0]["valid_age_variance"]+age[1]["valid_age_variance"])/2) if all(r["valid_age_variance"] is not None for r in age) else 0
    age_smd = (age[1]["valid_age_mean"]-age[0]["valid_age_mean"])/denom if denom else None
    gender = records(con, "SELECT treatment_flg, coalesce(gender,'MISSING') AS gender, count(*) AS n FROM training GROUP BY 1,2 ORDER BY 1,2")
    categorical_smd = {}
    for level in sorted({r["gender"] for r in gender}):
        p = [sum(r["n"] for r in gender if r["gender"] == level and r["treatment_flg"] == arm)/age[arm]["n"] for arm in (0,1)]
        sd = math.sqrt(sum(v*(1-v) for v in p)/2)
        categorical_smd[level] = (p[1]-p[0])/sd if sd else None
    missing = {c: con.execute(f'SELECT count(*) FROM training WHERE "{c}" IS NULL').fetchone()[0]
               for c in ["first_issue_date", "first_redeem_date", "age", "gender"]}
    return {"age_by_arm": age, "age_smd_treated_minus_control": age_smd,
            "gender_by_arm": gender, "gender_level_smd": categorical_smd,
            "missing_in_training": missing,
            "caveat": "Descriptive assignment checks only, no subgroup effects. Age 0..120 is an audit plausibility range, not a final feature-cleaning rule; demographics have uncertain snapshot timing."}


def analyze(root):
    started = time.perf_counter()
    docs = root / "docs/causal/phase5"
    inputs = verify_inputs(root)
    manifest = json.loads((docs / "split_manifest.json").read_text())
    verify_split(root, manifest, inputs)
    con = connect(root)
    try:
        training_view(con, root / manifest["path"])
        arms = training_counts(con)
        if len(arms) != 2 or [r["treatment_flg"] for r in arms] != [0,1]:
            raise ValueError("need both treatment arms")
        expected = {r["treatment_flg"]: r["n"] for r in manifest["counts"] if r["split"] == "train"}
        if any(r["n"] != expected[r["treatment_flg"]] for r in arms):
            raise ValueError("training join count mismatch")
        stats = experiment_statistics(arms[1]["purchasers"], arms[1]["n"], arms[0]["purchasers"], arms[0]["n"])
        full_counts = json.loads((docs / "audit.json").read_text())["assignment_counts"]
        result = {"analysis_population": "train only", "analysis_at_utc": datetime.now(timezone.utc).isoformat(),
                  "split_manifest_sha256": sha256(docs / "split_manifest.json"),
                  "statistics": stats, "training_balance": training_balance(con),
                  "assignment_check_full_metadata": assignment_check(full_counts[1]["n"], full_counts[0]["n"]),
                  "assignment_check_training": assignment_check(arms[1]["n"], arms[0]["n"]),
                  "versions": {"python": platform.python_version(), "duckdb": duckdb.__version__, "scipy": scipy.__version__},
                  "resources": {"duckdb_memory_limit": "256MB", "threads": 1, "max_spill": "1GB",
                                "elapsed_seconds": time.perf_counter()-started,
                                "process_maxrss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if platform.system() == "Darwin" else 1024)},
                  "holdout_outcomes_analyzed": False}
        verify_inputs(root)
        write_json(docs / "experiment_summary.json", result)
        return result
    finally:
        con.close()


def verify_saved(root):
    """Independent CSV aggregation of training customers, with frozen hashes."""
    docs = root / "docs/causal/phase5"
    inputs = verify_inputs(root)
    manifest = json.loads((docs / "split_manifest.json").read_text())
    verify_split(root, manifest, inputs)
    con = connect(root)
    try:
        train_ids = {r[0] for r in con.execute(
            f"SELECT client_id FROM read_parquet({quote(root / manifest['path'])}) WHERE split='train'").fetchall()}
    finally:
        con.close()
    counts = {0: [0, 0], 1: [0, 0]}
    with (root / "data/retailhero/raw/uplift_train.csv").open(newline="") as f:
        for row in csv.DictReader(f):
            if row["client_id"] in train_ids:
                arm = int(row["treatment_flg"])
                counts[arm][0] += 1
                counts[arm][1] += int(row["target"])
    saved = json.loads((docs / "experiment_summary.json").read_text())
    if saved["split_manifest_sha256"] != sha256(docs / "split_manifest.json"):
        raise ValueError("saved analysis references a different split")
    s = saved["statistics"]
    if counts != {0: [s["control_n"], s["control_purchasers"]],
                  1: [s["treated_n"], s["treated_purchasers"]]}:
        raise ValueError("independent training counts disagree")
    recalculated = experiment_statistics(counts[1][1], counts[1][0], counts[0][1], counts[0][0])
    if recalculated != s:
        raise ValueError("saved statistics disagree")
    result = {"method": "Independent Python csv streaming aggregation, training ID membership only; no holdout outcome aggregation. Compared with DuckDB output.",
              "counts": {str(k): {"n": v[0], "purchasers": v[1]} for k, v in counts.items()},
              "matched": True}
    write_json(docs / "independent_verification.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--analyze", action="store_true")
    mode.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    result = prepare(args.root) if args.prepare else verify_saved(args.root) if args.verify else analyze(args.root)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
