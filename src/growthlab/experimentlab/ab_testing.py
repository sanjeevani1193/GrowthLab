"""Synthetic 20%-versus-23% A/B power check; unchanged Phase 8A/8B methods."""
import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import platform
import resource
import time
from pathlib import Path

import numpy as np
import scipy
from scipy.stats import norm

from .aa_testing import AAStudyConfig, analyze_counts, calibration_check, count_pair, outcome_stream
from .design import ExperimentDesign, assign_customers, probability, sample_ratio_mismatch

TRUE_CONTROL_RATE = .20
TRUE_TREATMENT_RATE = .23
TRUE_DIFFERENCE = .03


@dataclass(frozen=True)
class ABStudyConfig(AAStudyConfig):
    """Reuse Phase 8B validation, with a distinct predeclared outcome stream."""
    outcome_master_seed: int = 2026110602


def normal_approx_power(control_n, treatment_n, alpha=.05):
    """Phase 8A pooled-null/unpooled-alternative approximation, unequal n allowed.

    This integrates both normal rejection tails, not finite-binomial exact power.
    Inputs are the known synthetic rates and declared counts, never fitted rates.
    """
    count_pair(0,control_n); count_pair(0,treatment_n); probability('alpha',alpha)
    pc,pt=TRUE_CONTROL_RATE,TRUE_TREATMENT_RATE
    pool=(control_n*pc+treatment_n*pt)/(control_n+treatment_n)
    se_null=math.sqrt(pool*(1-pool)*(1/control_n+1/treatment_n))
    se_alternative=math.sqrt(pc*(1-pc)/control_n+pt*(1-pt)/treatment_n)
    critical=norm.isf(alpha/2)*se_null
    return float(norm.sf((critical-TRUE_DIFFERENCE)/se_alternative)+
                 norm.cdf((-critical-TRUE_DIFFERENCE)/se_alternative))


def draw_ab_outcomes(treatment_mask, master_seed, experiment_index):
    """One binary draw per customer with probabilities determined by fixed arm."""
    mask=np.asarray(treatment_mask)
    if mask.ndim!=1 or mask.dtype!=np.bool_ or not 1 <= len(mask) <= 100_000:
        raise ValueError('treatment_mask must be a nonempty boolean vector with at most 100000 customers')
    rates=np.where(mask,TRUE_TREATMENT_RATE,TRUE_CONTROL_RATE)
    # The identical Phase 8B child-stream constructor, with a new master seed.
    return outcome_stream(master_seed,experiment_index).binomial(1,rates).astype(np.int8)


def run_study(design, config):
    if design.baseline_rate!=.20 or design.absolute_mde!=.03 or design.alpha!=.05:
        raise ValueError('Phase 8C is fixed to 20% versus 23%, +3 pp and two-sided alpha=0.05')
    plan=design.sample_size(); n=plan['total_n']
    if n>100_000: raise ValueError('synthetic cohort limited to 100000 customers')
    ids=[f'synthetic-customer-{i:06d}' for i in range(1,n+1)]
    assignments=assign_customers(ids,design)
    mask=np.array([assignments[i]=='treatment' for i in sorted(assignments)],dtype=bool)
    nt=int(mask.sum()); nc=n-nt
    if not nc or not nt: raise ValueError('both assigned groups must contain customers')
    assignment_sha=hashlib.sha256(json.dumps(assignments,separators=(',',':')).encode()).hexdigest()
    rows=[]
    for index in range(config.repetitions):
        outcomes=draw_ab_outcomes(mask,config.outcome_master_seed,index)
        row=analyze_counts(int(outcomes[~mask].sum()),nc,int(outcomes[mask].sum()),nt,design.alpha)
        # Preserve the original helper's zero-coverage field; A/B coverage is
        # instead assessed against the known nonzero generating effect.
        row['covers_true_effect']=row['difference_ci'][0] <= TRUE_DIFFERENCE <= row['difference_ci'][1]
        row['effect_detected']=row['significant']
        row['detected_positive']=row['significant'] and row['difference']>0
        row['significant_wrong_direction']=row['significant'] and row['difference']<0
        rows.append({'experiment_index':index,'spawn_key':[index],**row})
    significant=sum(r['effect_detected'] for r in rows)
    positive=sum(r['detected_positive'] for r in rows)
    wrong_direction=sum(r['significant_wrong_direction'] for r in rows)
    covered=sum(r['covers_true_effect'] for r in rows)
    balanced_power=normal_approx_power(plan['control_n'],plan['treatment_n'],design.alpha)
    achieved_power=normal_approx_power(nc,nt,design.alpha)
    differences=np.array([r['difference_pp'] for r in rows])
    theoretical_sd=100*math.sqrt(.2*.8/nc+.23*.77/nt)
    summary={'scope':'Synthetic A/B power study, not real voucher effectiveness evidence',
        'study_configuration':asdict(config),'true_control_rate':.20,'true_treatment_rate':.23,'true_difference_pp':3.,
        'outcome_alpha_two_sided':design.alpha,
        'statistical_methods':'Unchanged Phase 8B analyze_counts: pooled two-proportion z-test; Newcombe/Wilson 95% difference CI; no continuity correction',
        'assignment':{'source':'Unchanged Phase 8A configuration and assign_customers',
            'seed':design.seed,'experiment_id_namespace':design.experiment_id,'total_n':n,'control_n':nc,'treatment_n':nt,
            'planned_control_n':plan['control_n'],'planned_treatment_n':plan['treatment_n'],
            'control_delta_from_plan':nc-plan['control_n'],'treatment_delta_from_plan':nt-plan['treatment_n'],
            'assignment_sha256':assignment_sha,'fixed_across_repetitions':True,
            'srm':sample_ratio_mismatch(nc,nt,design.treatment_probability,design.srm_alpha)},
        'theoretical_power':{'balanced_normal_approximation':balanced_power,'realized_allocation_normal_approximation':achieved_power,
            'method':'Two normal rejection tails, pooled expected null variance and unpooled alternative variance; not exact finite-sample power'},
        'empirical_power':calibration_check(significant,config.repetitions,achieved_power,config.calibration_alpha),
        'comparison_to_balanced_plan':calibration_check(significant,config.repetitions,balanced_power,config.calibration_alpha),
        'detection_direction':{'positive_significant':positive,'negative_significant':wrong_direction,
            'false_negatives':config.repetitions-significant,'false_negative_rate':(config.repetitions-significant)/config.repetitions,
            'definition':'Empirical two-sided power counts all p<0.05; report any wrong-direction significant result separately'},
        'interval_coverage':calibration_check(covered,config.repetitions,.95,config.calibration_alpha),
        'difference_diagnostics':{'mean_difference_pp':float(differences.mean()),
            'mean_estimation_error_pp':float(differences.mean()-3),
            'empirical_sd_pp':float(differences.std(ddof=1)) if config.repetitions>1 else None,
            'theoretical_alternative_sd_pp':theoretical_sd,'mean_monte_carlo_se_pp':theoretical_sd/math.sqrt(config.repetitions)},
        'random_streams':{'algorithm':'NumPy PCG64','construction':'Unchanged outcome_stream: SeedSequence(master_seed, spawn_key=(experiment_index,))',
            'independence':'Independent pseudo-random outcomes conditional on fixed synthetic roster and assignment; no persistent customer effects'},
        'example_selection':'Prespecified experiment index, not chosen by success or p-value',
        'example':rows[config.example_index],
        'versions':{'python':platform.python_version(),'numpy':np.__version__,'scipy':scipy.__version__}}
    return summary,rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path('docs/experiments/phase8c_config.json'))
    parser.add_argument('--output-dir',type=Path,default=Path('data/experiments/phase8c'))
    args=parser.parse_args();started=time.perf_counter()
    design_path=Path('docs/experiments/phase8a_config.json')
    design=ExperimentDesign(**json.loads(design_path.read_text()))
    config=ABStudyConfig(**json.loads(args.config.read_text()))
    summary,rows=run_study(design,config)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    path=args.output_dir/'replications.json';path.write_text(json.dumps(rows,indent=2,allow_nan=False)+'\n')
    summary['replication_aggregate_file']={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'rows':len(rows),'contains_customer_records':False}
    inputs=[design_path,args.config,Path(__file__),Path(__file__).with_name('design.py'),Path(__file__).with_name('aa_testing.py')]
    summary['input_sha256']={(str(p.relative_to(Path.cwd())) if p.is_absolute() and p.is_relative_to(Path.cwd()) else str(p)):
        hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    summary['resources']={'elapsed_seconds':time.perf_counter()-started,
        'peak_process_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if platform.system()=='Darwin' else 1024),
        'retention':'One binary synthetic-customer vector at a time; keep per-experiment aggregates only'}
    (args.output_dir/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
    print(json.dumps(summary,indent=2,allow_nan=False))


if __name__=='__main__':main()
