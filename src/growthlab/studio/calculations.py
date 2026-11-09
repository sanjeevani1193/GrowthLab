"""Small presentation calculations, delegating financial math to Phase 9."""
import math
from decimal import Decimal
from statistics import NormalDist

from growthlab.experimentlab.design import two_proportion_sample_size
from growthlab.rewards.economics import RewardScenario, result_payload
from growthlab.rewards.scenarios import ScenarioSpec,compare_scenarios,scenario_from_dict,sensitivity


def plan_experiment(baseline,mde,alpha,power,treatment_share=.5):
    # Keep Phase 8A's verified balanced calculation exactly.
    balanced=two_proportion_sample_size(baseline,mde,alpha,power)
    if not isinstance(treatment_share,(int,float)) or isinstance(treatment_share,bool) or not 0<treatment_share<1:
        raise ValueError('Treatment allocation must lie strictly between 0 and 1.')
    if treatment_share==.5:return {**balanced,'allocation_method':'Verified Phase 8A balanced planner'}
    # New UI-only generalization: n_treatment / n_control = r. Same pooled-null /
    # unpooled-alternative normal approximation; r=1 reduces to Phase 8A.
    r=treatment_share/(1-treatment_share);p1=baseline+mde
    pooled=(baseline+r*p1)/(1+r)
    v0=pooled*(1-pooled)*(1+1/r)
    v1=baseline*(1-baseline)+p1*(1-p1)/r
    z0=NormalDist().inv_cdf(1-alpha/2);z1=NormalDist().inv_cdf(power)
    unrounded=((z0*math.sqrt(v0)+z1*math.sqrt(v1))/mde)**2
    if not math.isfinite(unrounded) or unrounded>1e12:raise ValueError('Sample size exceeds the supported planning range.')
    control=math.ceil(unrounded);treated=math.ceil(r*control)
    metadata={k:v for k,v in balanced.items() if k!='unrounded_per_group'}
    return {**metadata,'method':'unequal-arm normal approximation, pooled null/unpooled alternative; no continuity correction',
        'pooled_rate':pooled,'variance_null_coefficient':v0,'variance_alternative_coefficient':v1,'control_n':control,'treatment_n':treated,'total_n':control+treated,
        'unrounded_control_n':unrounded,'unrounded_treatment_n':r*unrounded,
        'allocation_method':'Unequal-arm normal-approximation extension (Phase 11); not a rerun of saved simulations'}


def scenario_from_inputs(n,p0_percent,p1_percent,contribution,reward,redemption_percent,contact):
    pct=lambda x:Decimal(str(x))/Decimal(100)
    return RewardScenario(int(n),pct(p0_percent),pct(p1_percent),str(contribution),str(reward),pct(redemption_percent),str(contact))


def interactive_spec(scenario):
    return ScenarioSpec('interactive_scenario','hypothetical-cohort-A',14,
        'EUR-single-purchase-no-fixed-costs-v1','User-supplied hypothetical assumptions; no measured reward response.',scenario)


def compare_with_saved(scenario,config,selected):
    saved=[scenario_from_dict(s) for s in config['scenarios'] if s['scenario_id'] in selected]
    return compare_scenarios([interactive_spec(scenario),*saved])


def sensitivity_points(scenario,field,lower,upper,count):
    lo,hi=Decimal(str(lower)),Decimal(str(upper))
    if lo>=hi:raise ValueError('Upper bound must exceed lower bound.')
    if not 3<=count<=21:raise ValueError('Use 3–21 sensitivity points.')
    values=[lo+(hi-lo)*i/(count-1) for i in range(count)]
    return sensitivity(interactive_spec(scenario),field,values)


__all__=['plan_experiment','scenario_from_inputs','result_payload','compare_with_saved','sensitivity_points']
