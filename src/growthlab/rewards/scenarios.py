"""Declared-comparability scenario tables and one-factor sensitivity.

All purchase contribution, reward/contact costs and break-even outputs come
from the unchanged Phase 9A engine. No fitted response curve or optimization.
"""
import argparse
from dataclasses import dataclass, replace
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
from pathlib import Path

from . import economics

SENSITIVITY_FIELDS = ('treatment_conversion','reward_per_redemption_eur',
    'redemption_probability','contribution_per_purchase_eur','contact_cost_per_customer_eur')


def label(name,value):
    if not isinstance(value,str) or not value or value!=value.strip():
        raise ValueError(f'{name} must be a nonempty string without outer whitespace')


@dataclass(frozen=True)
class ScenarioSpec:
    scenario_id: str
    population_id: str
    horizon_days: int
    financial_basis_id: str
    assumptions_note: str
    economics: economics.RewardScenario

    def __post_init__(self):
        for field in ['scenario_id','population_id','financial_basis_id','assumptions_note']:
            label(field,getattr(self,field))
        if type(self.horizon_days) is not int or self.horizon_days<=0:
            raise ValueError('horizon_days must be a positive integer')
        if not isinstance(self.economics,economics.RewardScenario):
            raise ValueError('economics must be a validated Phase 9A RewardScenario')


def scenario_from_dict(item):
    if not isinstance(item,dict):raise ValueError('scenario must be an object')
    try:
        return ScenarioSpec(**{**item,'economics':economics.RewardScenario(**item['economics'])})
    except (TypeError,KeyError) as error:
        raise ValueError('every scenario must explicitly supply metadata and all seven economics inputs') from error


def evaluate_scenario(spec):
    if not isinstance(spec,ScenarioSpec):raise ValueError('expected ScenarioSpec')
    # One call to the existing engine. Do not reimplement its money or threshold formulas.
    payload=economics.result_payload(spec.economics)
    net=Decimal(payload['expected_values']['net_incremental_contribution_eur'])
    n=spec.economics.contacted_customers
    per_contact=economics.finite_decimal(Fraction(net)/n) if n else None
    status='no_contacts' if not n else 'positive' if net>0 else 'negative' if net<0 else 'break_even'
    return {'scenario_id':spec.scenario_id,'population_id':spec.population_id,
        'horizon_days':spec.horizon_days,'financial_basis_id':spec.financial_basis_id,
        'assumptions_note':spec.assumptions_note,'engine_result':payload,
        'net_contribution_per_contact_eur':str(per_contact) if per_contact is not None else None,
        'profitable_under_assumptions':net>0,'financial_status':status}


def compare_scenarios(specifications):
    if isinstance(specifications,(str,bytes)):
        raise ValueError('expected a collection of scenarios')
    try:specs=list(specifications)
    except TypeError as error:raise ValueError('expected a collection of scenarios') from error
    if not specs or len(specs)>1000 or any(not isinstance(s,ScenarioSpec) for s in specs):
        raise ValueError('comparison requires 1..1000 validated ScenarioSpec objects')
    ids=[s.scenario_id for s in specs]
    if len(set(ids))!=len(ids):raise ValueError('duplicate scenario_id')
    specs.sort(key=lambda s:s.scenario_id)
    criteria={
        'population_id':[s.population_id for s in specs],
        'contacted_customers':[s.economics.contacted_customers for s in specs],
        'horizon_days':[s.horizon_days for s in specs],
        'financial_basis_id':[s.financial_basis_id for s in specs],
        'baseline_conversion':[s.economics.baseline_conversion for s in specs],
        'contribution_per_purchase_eur':[s.economics.contribution_per_purchase_eur for s in specs]}
    blocked=[name for name,values in criteria.items() if len(set(values))!=1]
    if any(s.economics.contacted_customers==0 for s in specs):blocked.append('zero_contacts')
    rows=[evaluate_scenario(s) for s in specs]
    ranking=None
    if not blocked:
        ordered=sorted(rows,key=lambda r:(-Fraction(r['engine_result']['expected_values']['net_incremental_contribution_eur']),r['scenario_id']))
        ranking=[];previous=None;rank=0
        for index,row in enumerate(ordered,1):
            net=Decimal(row['engine_result']['expected_values']['net_incremental_contribution_eur'])
            if previous is None or net!=previous:rank=index
            ranking.append({'rank':rank,'scenario_id':row['scenario_id'],
                'net_incremental_contribution_eur':str(net),
                'profitable_under_assumptions':row['profitable_under_assumptions']})
            previous=net
    return {'scope':'Hypothetical conditional comparison, not a real optimal reward or measured causal effect',
        'comparison_criteria':list(criteria),'comparable_by_declared_criteria':not blocked,
        'ranking_blocked_reasons':blocked,'ranking':ranking,'scenarios':rows,
        'ranking_rule':'Descending expected net incremental contribution; equal amounts share a rank and IDs order ties without preference. No ranking if comparability fails.'}


def sensitivity(base,field,values):
    if not isinstance(base,ScenarioSpec):raise ValueError('base must be ScenarioSpec')
    if field not in SENSITIVITY_FIELDS:raise ValueError('unsupported sensitivity field')
    if isinstance(values,(str,bytes)) or values is None:
        raise ValueError('sensitivity values must be a collection')
    try:values=list(values)
    except TypeError as error:raise ValueError('sensitivity values must be a collection') from error
    if not values or len(values)>1000:raise ValueError('sensitivity needs 1..1000 values')
    changed=[replace(base.economics,**{field:value}) for value in values]
    normalized=[getattr(s,field) for s in changed]
    if len(set(normalized))!=len(normalized):raise ValueError('duplicate sensitivity values')
    points=[]
    for index,scenario in enumerate(sorted(changed,key=lambda s:getattr(s,field))):
        spec=replace(base,scenario_id=f'{base.scenario_id}__{field}_{index:03d}',economics=scenario)
        points.append({'assumed_value':str(getattr(scenario,field)),'evaluation':evaluate_scenario(spec)})
    baseline=economics.result_payload(base.economics)['inputs']
    return {'base_scenario_id':base.scenario_id,'field':field,
        'held_constant_inputs':{k:v for k,v in baseline.items() if k!=field},
        'population_id':base.population_id,'horizon_days':base.horizon_days,
        'financial_basis_id':base.financial_basis_id,'points':points,
        'interpretation':'One assumption changes at a time. Other inputs, including conversion when reward changes, stay fixed. These points are not a response curve, confidence interval or optimization.',
        'ranking':None}


def run_examples(config):
    try:
        specs=[scenario_from_dict(item) for item in config['scenarios']]
        incompatible=[scenario_from_dict(item) for item in config['non_comparable_examples']]
        base_id=config['sensitivity_base_id']; grids=config['sensitivities']
    except (KeyError,TypeError) as error:raise ValueError('incomplete scenario-study configuration') from error
    comparison=compare_scenarios(specs)
    bases={s.scenario_id:s for s in specs}
    if base_id not in bases:raise ValueError('unknown sensitivity base scenario')
    if set(grids)!=set(SENSITIVITY_FIELDS):raise ValueError('explicit grids required for all five sensitivity fields')
    return {'comparison':comparison,
        'non_comparable_demonstration':compare_scenarios([bases[base_id],*incompatible]),
        'sensitivities':{field:sensitivity(bases[base_id],field,grids[field]) for field in SENSITIVITY_FIELDS}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path('docs/rewards/phase9b_scenario_config.json'))
    args=parser.parse_args()
    result=run_examples(json.loads(args.config.read_text(),parse_float=Decimal))
    paths=[args.config,Path(__file__),Path(economics.__file__)]
    result['input_sha256']={(str(p.relative_to(Path.cwd())) if p.is_absolute() and p.is_relative_to(Path.cwd()) else str(p)):
        hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    print(json.dumps(result,indent=2,allow_nan=False))


if __name__=='__main__':main()
