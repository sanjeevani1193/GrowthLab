"""Hypothetical two-arm planning, ID-only assignment, and allocation checks.

No outcomes are generated or analyzed. Existing REES46/RetailHero code is not
imported or modified. SciPy is reused from the existing local environment.
"""
import argparse
from dataclasses import asdict, dataclass
from fractions import Fraction
import hashlib
import json
import math
from numbers import Real
from pathlib import Path
from statistics import NormalDist

import scipy
from scipy.stats import binomtest

ASSIGNMENT_VERSION = 'growthlab-experimentlab-sha256-v1'


def probability(name, value):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) or not 0 < value < 1:
        raise ValueError(f'{name} must be a finite probability strictly between 0 and 1')


def identifier(name, value):
    # Do not silently strip, lowercase, coerce numbers, or lose leading zeros.
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f'{name} must be a nonempty string without outer whitespace')


def two_proportion_sample_size(baseline_rate, absolute_mde, alpha=.05, power=.8):
    """Equal-size, independent-arm normal approximation; no continuity correction.

    Uses pooled null variance and unpooled alternative variance. The closed
    form ignores the negligible remote rejection tail under the positive MDE;
    alpha/2 still gives a TWO-sided critical value. Verification independently
    integrates both normal tails; this is not an exact finite-binomial design.
    """
    probability('baseline_rate', baseline_rate)
    probability('alpha', alpha)
    probability('power', power)
    if power <= .5:
        raise ValueError('this planning approximation requires power > 0.5')
    if isinstance(absolute_mde, bool) or not isinstance(absolute_mde, Real) or not math.isfinite(absolute_mde) or absolute_mde <= 0:
        raise ValueError('absolute_mde must be finite and positive')
    treatment_rate = baseline_rate + absolute_mde
    probability('baseline_rate + absolute_mde', treatment_rate)
    if treatment_rate == baseline_rate:
        raise ValueError('absolute_mde is below floating-point resolution at this baseline')
    pooled = (baseline_rate + treatment_rate)/2
    variance_null = 2*pooled*(1-pooled)
    variance_alternative = baseline_rate*(1-baseline_rate)+treatment_rate*(1-treatment_rate)
    z_alpha = NormalDist().inv_cdf(1-alpha/2)
    z_power = NormalDist().inv_cdf(power)
    size_scale = (z_alpha*math.sqrt(variance_null)+z_power*math.sqrt(variance_alternative))/absolute_mde
    unrounded = size_scale*size_scale
    if not math.isfinite(unrounded):
        raise ValueError('required sample size exceeds supported numeric range')
    per_group = math.ceil(unrounded)
    return {'method':'equal-arm normal approximation, pooled null/unpooled alternative; no continuity correction',
            'baseline_rate':baseline_rate, 'planning_treatment_rate':treatment_rate,
            'absolute_mde':absolute_mde, 'alpha_two_sided':alpha, 'power':power,
            'pooled_rate':pooled, 'variance_null_coefficient':variance_null,
            'variance_alternative_coefficient':variance_alternative,
            'z_alpha':z_alpha, 'z_power':z_power,
            'unrounded_per_group':unrounded, 'control_n':per_group,
            'treatment_n':per_group, 'total_n':2*per_group}


@dataclass(frozen=True)
class ExperimentDesign:
    experiment_id: str = 'voucher_5eur_14d_v1'
    business_question: str = 'Does offering a EUR 5 voucher increase 14-day purchase probability?'
    control: str = 'No voucher'
    treatment: str = 'Offer a EUR 5 voucher'
    randomization_unit: str = 'unique customer'
    primary_metric: str = 'binary conversion within 14 days of assignment'
    baseline_rate: float = .20
    absolute_mde: float = .03
    alpha: float = .05
    power: float = .80
    treatment_probability: float = .50
    seed: int = 20261106
    srm_alpha: float = .01
    assumptions_are_hypothetical: bool = True

    def __post_init__(self):
        identifier('experiment_id', self.experiment_id)
        for name in ['business_question','control','treatment','randomization_unit','primary_metric']:
            identifier(name, getattr(self,name))
        if self.control == self.treatment:
            raise ValueError('control and treatment must differ')
        if type(self.seed) is not int or self.seed < 0:
            raise ValueError('seed must be a nonnegative integer')
        probability('treatment_probability', self.treatment_probability)
        # Keep the implemented sample-size formula honest: unequal-arm designs
        # would require a different variance/sample-size calculation.
        if self.treatment_probability != .5:
            raise ValueError('Phase 8A design supports balanced 50/50 allocation only')
        probability('srm_alpha', self.srm_alpha)
        if self.assumptions_are_hypothetical is not True:
            raise ValueError('Phase 8A planning assumptions must remain explicitly hypothetical')
        two_proportion_sample_size(self.baseline_rate,self.absolute_mde,self.alpha,self.power)

    def sample_size(self):
        return two_proportion_sample_size(self.baseline_rate,self.absolute_mde,self.alpha,self.power)


def assign_customers(customer_ids, design):
    """Return sorted ID -> group mapping; strict duplicate/missing-ID validation.

    Threshold assignment approximates independent Bernoulli allocation. It does
    not force an exact group size, rank IDs into quotas, or inspect outcomes.
    """
    if isinstance(customer_ids, (str, bytes)):
        raise ValueError('customer_ids must be an iterable of IDs, not one string')
    try:
        ids = list(customer_ids)
    except TypeError as error:
        raise ValueError('customer_ids must be an iterable of IDs') from error
    seen = set()
    for customer in ids:
        identifier('customer_id', customer)
        if customer in seen:
            raise ValueError(f'duplicate customer_id: {customer!r}')
        seen.add(customer)
    ratio = Fraction(str(design.treatment_probability))
    assignments = {}
    for customer in sorted(ids):
        payload = json.dumps([ASSIGNMENT_VERSION, design.experiment_id, design.seed, customer],
                             separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        value = int.from_bytes(hashlib.sha256(payload).digest(), 'big')
        treated = value*ratio.denominator < ratio.numerator*(1 << 256)
        assignments[customer] = 'treatment' if treated else 'control'
    return assignments


def sample_ratio_mismatch(control_n, treatment_n, treatment_probability=.5, significance_level=.01):
    """Two-sided exact binomial diagnostic against a declared Bernoulli split."""
    for name, count in [('control_n',control_n),('treatment_n',treatment_n)]:
        if type(count) is not int or count < 0:
            raise ValueError(f'{name} must be a nonnegative integer')
    total = control_n+treatment_n
    if total == 0:
        raise ValueError('at least one assigned customer is required for SRM')
    probability('treatment_probability', treatment_probability)
    probability('significance_level', significance_level)
    result = binomtest(treatment_n,total,p=treatment_probability,alternative='two-sided')
    return {'method':'two-sided exact binomial allocation test', 'control_n':control_n,
            'treatment_n':treatment_n,'total_n':total,
            'expected_control_n':total*(1-treatment_probability),
            'expected_treatment_n':total*treatment_probability,
            'observed_treatment_fraction':treatment_n/total,
            'planned_treatment_probability':treatment_probability,
            'p_value':float(result.pvalue),'significance_level':significance_level,
            'flag_srm':bool(result.pvalue < significance_level)}


def numerical_planning_crosscheck(design):
    """Independent two-tail normal integration/root solve, NOT outcome analysis.

    Uses SciPy quantiles/tail probabilities and numerical inversion rather than
    the closed-form sample-size function. No experimental observations enter.
    """
    from scipy.optimize import brentq
    from scipy.stats import norm
    p0,p1=design.baseline_rate,design.baseline_rate+design.absolute_mde
    def planning_power(n):
        null_se = math.sqrt(((p0+p1)/2)*(1-(p0+p1)/2)*(2/n))
        alternative_se = math.sqrt(p0*(1-p0)/n+p1*(1-p1)/n)
        threshold = norm.isf(design.alpha/2)*null_se
        return float(norm.sf((threshold-(p1-p0))/alternative_se)+
                     norm.cdf((-threshold-(p1-p0))/alternative_se))
    upper=2.
    while planning_power(upper) < design.power:
        upper *= 2
        if upper > 1e12:
            raise ValueError('numerical planning root outside supported range')
    root=brentq(lambda n:planning_power(n)-design.power,1e-8,upper,xtol=1e-9)
    rounded=math.ceil(root)
    return {'method':'numerical inversion of both normal rejection tails using SciPy, not finite-binomial exact power',
            'unrounded_per_group':root,'rounded_per_group':rounded,
            'normal_power_at_rounded_n':planning_power(rounded),
            'normal_power_at_one_less':planning_power(rounded-1) if rounded>1 else None}


def planning_example(design):
    sample=design.sample_size()
    if sample['total_n'] > 100_000:
        raise ValueError('assignment-only CLI example limited to 100,000 IDs; use the sample-size calculator without materializing that cohort')
    # This is an assignment-only example, with no conversion/voucher outcomes.
    ids=[f'synthetic-customer-{i:06d}' for i in range(1,sample['total_n']+1)]
    assigned=assign_customers(ids,design)
    treatment_n=sum(group=='treatment' for group in assigned.values())
    control_n=len(assigned)-treatment_n
    return {'scope':'Hypothetical design and synthetic-ID assignment only; no outcomes generated or analyzed',
            'configuration':asdict(design),'assignment_algorithm':ASSIGNMENT_VERSION,
            'sample_size':sample,'independent_normal_crosscheck':numerical_planning_crosscheck(design),
            'synthetic_example':{'id_format':'synthetic-customer-000001 through planned total, inclusive',
                'srm':sample_ratio_mismatch(control_n,treatment_n,design.treatment_probability,design.srm_alpha),
                'per_arm_planning_minimum_reached':{'control':control_n>=sample['control_n'],
                                                   'treatment':treatment_n>=sample['treatment_n']}},
            'scipy_version':scipy.__version__}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path('docs/experiments/phase8a_config.json'))
    args=parser.parse_args()
    design=ExperimentDesign(**json.loads(args.config.read_text()))
    print(json.dumps(planning_example(design),indent=2,allow_nan=False))


if __name__=='__main__':
    main()
