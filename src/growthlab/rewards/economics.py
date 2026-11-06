"""Single-campaign expected contribution, costs, and analytic break-even.

No observed data, simulations, causal estimates, reward optimization, or ranking.
Decimal inputs are evaluated with exact rational arithmetic; no cent rounding
or ambient Decimal-context rounding is applied to expected totals.
"""
import argparse
from dataclasses import asdict, dataclass
from decimal import Context, Decimal, InvalidOperation, localcontext
from fractions import Fraction
import json
import math
from pathlib import Path


def decimal_input(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError(f'{name} must be a finite decimal number')
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f'{name} must be finite')
    try:
        number=Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f'{name} must be a finite decimal number') from error
    if not number.is_finite():
        raise ValueError(f'{name} must be finite')
    return number


@dataclass(frozen=True)
class RewardScenario:
    contacted_customers: int
    baseline_conversion: Decimal
    treatment_conversion: Decimal
    contribution_per_purchase_eur: Decimal
    reward_per_redemption_eur: Decimal
    redemption_probability: Decimal
    contact_cost_per_customer_eur: Decimal

    def __post_init__(self):
        if type(self.contacted_customers) is not int or self.contacted_customers < 0:
            raise ValueError('contacted_customers must be a nonnegative integer')
        for name in ['baseline_conversion','treatment_conversion','contribution_per_purchase_eur',
                     'reward_per_redemption_eur','redemption_probability','contact_cost_per_customer_eur']:
            number=decimal_input(name,getattr(self,name))
            if number < 0:
                raise ValueError(f'{name} must be nonnegative')
            if name in ['baseline_conversion','treatment_conversion','redemption_probability'] and number > 1:
                raise ValueError(f'{name} must be in [0,1]')
            object.__setattr__(self,name,number)


def finite_decimal(number):
    """Convert a terminating Fraction to Decimal exactly, without division.

    Products/sums of the finite decimal scenario inputs always terminate.
    Only break-even ratios can repeat; those are retained as Fractions.
    """
    numerator,denominator=number.numerator,number.denominator
    twos=fives=0
    while denominator % 2 == 0:
        denominator//=2;twos+=1
    while denominator % 5 == 0:
        denominator//=5;fives+=1
    if denominator != 1:
        raise ValueError('nonterminating rational: keep the exact fraction instead')
    places=max(twos,fives)
    scaled=abs(numerator)*2**(places-twos)*5**(places-fives)
    digits=str(scaled).zfill(places+1)
    text=(digits[:-places]+'.'+digits[-places:]) if places else digits
    if numerator < 0: text='-'+text
    return Decimal(text)


@dataclass(frozen=True)
class BreakEven:
    status: str
    attainable: bool | None
    required_treatment_probability: Fraction | None
    required_conversion_change_pp: Fraction | None
    unconstrained_threshold: Fraction | None
    explanation: str


def break_even(scenario):
    """Nonnegative net contribution for p in [0,1], holding other inputs fixed.

    For N>0: net/N = p*(m-r*d) - (p0*m+k).
    This is one analytic threshold, not a search over scenarios/reward amounts.
    """
    p0=Fraction(scenario.baseline_conversion)
    m=Fraction(scenario.contribution_per_purchase_eur)
    r=Fraction(scenario.reward_per_redemption_eur)
    d=Fraction(scenario.redemption_probability)
    k=Fraction(scenario.contact_cost_per_customer_eur)
    slope=m-r*d; hurdle=p0*m+k
    if scenario.contacted_customers == 0:
        return BreakEven('no_customers',None,None,None,None,
            'All campaign totals are zero; no meaningful conversion threshold for an empty campaign.')
    if slope > 0:
        threshold=hurdle/slope
        if threshold <= 1:
            return BreakEven('attainable',True,threshold,100*(threshold-p0),threshold,
                'Equality at this threshold; nonnegative net contribution at or above it, within [0,1].')
        return BreakEven('unattainable',False,None,None,threshold,
            'Required treatment conversion exceeds 100%; no feasible probability covers the modeled costs.')
    if slope == 0 and hurdle == 0:
        return BreakEven('all_rates_break_even',True,None,None,None,
            'Net contribution is identically zero at every conversion probability; there is no unique threshold or positive profit.')
    if slope < 0 and hurdle == 0:
        return BreakEven('zero_conversion_only',True,Fraction(0),-100*p0,None,
            'Only zero treatment conversion breaks even; any positive conversion loses contribution. This is not a profitable improvement.')
    return BreakEven('unattainable',False,None,None,None,
        'Contribution after expected reward cost per purchase is nonpositive while the baseline/contact hurdle is positive.')


@dataclass(frozen=True)
class EconomicsResult:
    expected_purchasers_without_intervention: Decimal
    expected_purchasers_with_intervention: Decimal
    expected_incremental_purchasers: Decimal
    incremental_conversion_effect_pp: Decimal
    expected_incremental_purchase_contribution_eur: Decimal
    expected_reward_redemptions: Decimal
    total_reward_expenditure_eur: Decimal
    total_contact_expenditure_eur: Decimal
    net_incremental_contribution_eur: Decimal
    break_even: BreakEven


def evaluate(scenario):
    n=scenario.contacted_customers
    p0=Fraction(scenario.baseline_conversion); p1=Fraction(scenario.treatment_conversion)
    m=Fraction(scenario.contribution_per_purchase_eur)
    reward=Fraction(scenario.reward_per_redemption_eur)
    redemption=Fraction(scenario.redemption_probability)
    contact=Fraction(scenario.contact_cost_per_customer_eur)
    baseline=n*p0; treatment=n*p1; incremental=treatment-baseline
    purchase_contribution=incremental*m
    redemptions=treatment*redemption
    reward_cost=redemptions*reward; contact_cost=n*contact
    values=[baseline,treatment,incremental,100*(p1-p0),purchase_contribution,
            redemptions,reward_cost,contact_cost,purchase_contribution-reward_cost-contact_cost]
    return EconomicsResult(*(finite_decimal(v) for v in values),break_even(scenario))


def fraction_payload(number):
    if number is None: return None
    with localcontext(Context(prec=40)):
        approximation=Decimal(number.numerator)/Decimal(number.denominator)
    return {'exact_fraction':str(number),'decimal_approximation':str(approximation)}


def result_payload(scenario):
    result=evaluate(scenario)
    be=result.break_even
    return {'scope':'Hypothetical deterministic expected values; no observed campaign results or reward optimization',
        'inputs':{k:str(v) if isinstance(v,Decimal) else v for k,v in asdict(scenario).items()},
        'expected_values':{k:str(v) for k,v in vars(result).items() if k!='break_even'},
        'break_even':{'status':be.status,'attainable':be.attainable,
            'required_treatment_probability':fraction_payload(be.required_treatment_probability),
            'required_conversion_change_pp':fraction_payload(be.required_conversion_change_pp),
            'unconstrained_threshold':fraction_payload(be.unconstrained_threshold),'explanation':be.explanation},
        'precision':'Expected values are exact decimal strings; break-even fractions are exact and displayed decimal ratios are approximations.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path('docs/rewards/phase9a_reference_config.json'))
    args=parser.parse_args()
    scenario=RewardScenario(**json.loads(args.config.read_text(),parse_float=Decimal))
    print(json.dumps(result_payload(scenario),indent=2,allow_nan=False))


if __name__=='__main__':main()
