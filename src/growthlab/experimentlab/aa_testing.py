"""Synthetic zero-effect A/A calibration; no real data or treatment effects."""
import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import platform
import resource
import time
from pathlib import Path
from statistics import NormalDist

import numpy as np
import scipy
from scipy.stats import binom, binomtest

from .design import ExperimentDesign, assign_customers, probability, sample_ratio_mismatch

TRUE_PURCHASE_PROBABILITY = .20


@dataclass(frozen=True)
class AAStudyConfig:
    repetitions: int = 1000
    outcome_master_seed: int = 2026110601
    calibration_alpha: float = .05
    example_index: int = 0

    def __post_init__(self):
        if type(self.repetitions) is not int or not 1 <= self.repetitions <= 10_000:
            raise ValueError('repetitions must be an integer in [1,10000]')
        if type(self.outcome_master_seed) is not int or self.outcome_master_seed < 0:
            raise ValueError('outcome_master_seed must be a nonnegative integer')
        probability('calibration_alpha',self.calibration_alpha)
        if type(self.example_index) is not int or not 0 <= self.example_index < self.repetitions:
            raise ValueError('example_index must identify an existing repetition')


def count_pair(conversions, n):
    if type(n) is not int or n <= 0 or type(conversions) is not int or not 0 <= conversions <= n:
        raise ValueError('conversions/n must be integer counts with 0<=conversions<=n and n>0')


def wilson_interval(conversions, n, alpha=.05):
    """Score interval for ONE probability; used to form Newcombe differences."""
    count_pair(conversions,n); probability('alpha',alpha)
    z=NormalDist().inv_cdf(1-alpha/2); p=conversions/n
    denominator=1+z*z/n
    center=(p+z*z/(2*n))/denominator
    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/denominator
    return [max(0.,center-half),min(1.,center+half)]


def analyze_counts(control_conversions, control_n, treatment_conversions, treatment_n, alpha=.05):
    """Pooled, two-sided z-test and Newcombe/Wilson treatment-control CI.

    No continuity correction. The confidence interval is not exactly the
    inversion of the pooled z-test; agreement is measured, not assumed.
    """
    count_pair(control_conversions,control_n); count_pair(treatment_conversions,treatment_n)
    probability('alpha',alpha)
    pc=control_conversions/control_n; pt=treatment_conversions/treatment_n
    difference=pt-pc
    pooled=(control_conversions+treatment_conversions)/(control_n+treatment_n)
    se=math.sqrt(pooled*(1-pooled)*(1/control_n+1/treatment_n))
    # SE is zero only when both groups are all-zero or all-one; difference=0.
    z=difference/se if se else 0.
    p_value=math.erfc(abs(z)/math.sqrt(2))
    lc,uc=wilson_interval(control_conversions,control_n,alpha)
    lt,ut=wilson_interval(treatment_conversions,treatment_n,alpha)
    ci=[max(-1.,difference-math.hypot(pt-lt,uc-pc)),
        min(1.,difference+math.hypot(ut-pt,pc-lc))]
    covers_zero=ci[0] <= 0 <= ci[1]
    return {'control_n':control_n,'treatment_n':treatment_n,
            'control_conversions':control_conversions,'treatment_conversions':treatment_conversions,
            'control_rate':pc,'treatment_rate':pt,'difference':difference,'difference_pp':100*difference,
            'z_statistic':z,'p_value_two_sided':p_value,'significant':p_value < alpha,
            'confidence_level':1-alpha,'difference_ci':ci,'difference_ci_pp':[100*x for x in ci],
            'covers_true_zero':covers_zero}


def outcome_stream(master_seed, experiment_index):
    if type(master_seed) is not int or master_seed < 0 or type(experiment_index) is not int or experiment_index < 0:
        raise ValueError('master seed and experiment index must be nonnegative integers')
    # Direct spawn-key addressing equals parent.spawn(...)[index], but is also
    # independent of the order in which repetition indices are requested.
    child=np.random.SeedSequence(master_seed,spawn_key=(experiment_index,))
    return np.random.Generator(np.random.PCG64(child))


def draw_aa_outcomes(n_customers, master_seed, experiment_index):
    """One Bernoulli(0.20) per synthetic customer; arm cannot affect generation."""
    if type(n_customers) is not int or not 1 <= n_customers <= 100_000:
        raise ValueError('synthetic cohort size must be an integer in [1,100000]')
    return outcome_stream(master_seed,experiment_index).binomial(1,TRUE_PURCHASE_PROBABILITY,size=n_customers).astype(np.int8)


def calibration_check(events, trials, expected_rate, significance_level=.05):
    """Binomial diagnostic for false positives or coverage across independent runs."""
    count_pair(events,trials); probability('expected_rate',expected_rate)
    probability('significance_level',significance_level)
    p=float(binomtest(events,trials,p=expected_rate,alternative='two-sided').pvalue)
    return {'events':events,'trials':trials,'empirical_rate':events/trials,
            'expected_rate':expected_rate,'wilson_95_interval':wilson_interval(events,trials),
            'expected_count':trials*expected_rate,
            'null_count_sd':math.sqrt(trials*expected_rate*(1-expected_rate)),
            'null_central_95_count_range':[int(binom.ppf(.025,trials,expected_rate)),int(binom.ppf(.975,trials,expected_rate))],
            'two_sided_binomial_p_value':p,'diagnostic_alpha':significance_level,
            'flag_departure':p < significance_level}


def run_study(design, config):
    if design.baseline_rate != TRUE_PURCHASE_PROBABILITY or design.alpha != .05:
        raise ValueError('Phase 8B is fixed to a 20% null in both arms and two-sided alpha=0.05')
    n=design.sample_size()['total_n']
    if n > 100_000: raise ValueError('synthetic cohort limited to 100000 customers')
    ids=[f'synthetic-customer-{i:06d}' for i in range(1,n+1)]
    assignment=assign_customers(ids,design)
    sorted_ids=sorted(assignment)
    treated=np.array([assignment[i]=='treatment' for i in sorted_ids],dtype=bool)
    nt=int(treated.sum()); nc=n-nt
    if not nt or not nc: raise ValueError('both assigned groups must contain customers')
    assignment_sha=hashlib.sha256(json.dumps(assignment,separators=(',',':')).encode()).hexdigest()
    rows=[]
    for index in range(config.repetitions):
        outcomes=draw_aa_outcomes(n,config.outcome_master_seed,index)
        row=analyze_counts(int(outcomes[~treated].sum()),nc,int(outcomes[treated].sum()),nt,design.alpha)
        rows.append({'experiment_index':index,'spawn_key':[index],**row})
    significant=sum(row['significant'] for row in rows)
    covered=sum(row['covers_true_zero'] for row in rows)
    differences=np.array([row['difference_pp'] for row in rows])
    p_values=np.array([row['p_value_two_sided'] for row in rows])
    empirical_sd=float(np.std(differences,ddof=1)) if config.repetitions>1 else None
    theoretical_sd=100*math.sqrt(.2*.8*(1/nc+1/nt))
    summary={'scope':'Synthetic A/A calibration only; true treatment effect exactly zero, not empirical voucher evidence',
        'study_configuration':asdict(config),'true_control_rate':.2,'true_treatment_rate':.2,'true_difference_pp':0.,
        'outcome_alpha_two_sided':design.alpha,'confidence_interval_method':'95% Newcombe difference of independent Wilson score intervals; no continuity correction',
        'assignment':{'source':'Unchanged Phase 8A configuration and assign_customers function',
            'seed':design.seed,'experiment_id_namespace':design.experiment_id,'total_n':n,'control_n':nc,'treatment_n':nt,
            'assignment_sha256':assignment_sha,'fixed_across_repetitions':True,
            'srm':sample_ratio_mismatch(nc,nt,design.treatment_probability,design.srm_alpha)},
        'random_streams':{'algorithm':'NumPy PCG64','construction':'SeedSequence(master_seed, spawn_key=(experiment_index,))',
                          'independence':'Independent pseudo-random outcome streams conditional on the fixed roster/assignment; no persistent customer effects'},
        'false_positives':calibration_check(significant,config.repetitions,design.alpha,config.calibration_alpha),
        'interval_coverage':calibration_check(covered,config.repetitions,.95,config.calibration_alpha),
        'difference_diagnostics':{'mean_difference_pp':float(np.mean(differences)),
            'empirical_sd_pp':empirical_sd,'theoretical_null_sd_pp':theoretical_sd,
            'mean_difference_monte_carlo_se_pp':theoretical_sd/math.sqrt(config.repetitions)},
        'p_value_diagnostics':{'mean':float(p_values.mean()),'decile_counts':np.histogram(p_values,bins=np.linspace(0,1,11))[0].tolist(),
            'significance_vs_ci_exclusion_disagreements':sum(row['significant'] != (not row['covers_true_zero']) for row in rows)},
        'example_selection':'Prespecified experiment_index, not selected by p-value',
        'example':rows[config.example_index],
        'versions':{'python':platform.python_version(),'numpy':np.__version__,'scipy':scipy.__version__}}
    return summary,rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path('docs/experiments/phase8b_config.json'))
    parser.add_argument('--output-dir',type=Path,default=Path('data/experiments/phase8b'))
    args=parser.parse_args(); started=time.perf_counter()
    design_path=Path('docs/experiments/phase8a_config.json')
    design=ExperimentDesign(**json.loads(design_path.read_text()))
    config=AAStudyConfig(**json.loads(args.config.read_text()))
    summary,rows=run_study(design,config)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    results_path=args.output_dir/'replications.json'
    results_path.write_text(json.dumps(rows,indent=2,allow_nan=False)+'\n')
    summary['replication_aggregate_file']={'path':str(results_path),'sha256':hashlib.sha256(results_path.read_bytes()).hexdigest(),
        'rows':len(rows),'contains_customer_records':False}
    summary['input_sha256']={(str(p.relative_to(Path.cwd())) if p.is_absolute() and p.is_relative_to(Path.cwd()) else str(p)):
        hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [design_path,args.config,Path(__file__),Path(__file__).with_name('design.py')]}
    summary['resources']={'elapsed_seconds':time.perf_counter()-started,
        'peak_process_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if platform.system()=='Darwin' else 1024),
        'retention':'One binary customer vector at a time; retain per-experiment aggregates only'}
    (args.output_dir/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
    print(json.dumps(summary,indent=2,allow_nan=False))


if __name__=='__main__':main()
