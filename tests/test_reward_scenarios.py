"""Hypothetical scenario comparisons; financial calculations stay in Phase 9A."""
from dataclasses import replace
from decimal import Decimal, Inexact, ROUND_DOWN, localcontext
from fractions import Fraction
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from growthlab.rewards import economics
from growthlab.rewards.scenarios import (
    ScenarioSpec, compare_scenarios, evaluate_scenario, scenario_from_dict,
    sensitivity, run_examples,
)


def scenario(scenario_id='reference',**changes):
    inputs=economics.RewardScenario(1000,'.20','.23','20','5','1','0')
    return ScenarioSpec(scenario_id,'hypothetical-pop-A',14,'eur-accounting-v1',
                        'Hypothetical assumptions only.',replace(inputs,**changes))


def net(row):
    return Decimal(row['engine_result']['expected_values']['net_incremental_contribution_eur'])


class ComparisonTests(unittest.TestCase):
    def test_multi_scenario_expected_outputs_and_ordering(self):
        specs=[scenario(),scenario('partial',redemption_probability='.5'),
               scenario('higher',treatment_conversion='.30'),
               scenario('lower_reward',reward_per_redemption_eur=2,contact_cost_per_customer_eur='.10')]
        result=compare_scenarios(specs)
        self.assertTrue(result['comparable_by_declared_criteria'])
        self.assertEqual([r['scenario_id'] for r in result['ranking']],['higher','lower_reward','partial','reference'])
        self.assertEqual([r['net_incremental_contribution_eur'] for r in result['ranking']],['500','40','25','-550'])

    def test_uses_unmodified_engine_for_every_scenario(self):
        specs=[scenario(),scenario('other',treatment_conversion='.30')]
        original=economics.evaluate
        with patch.object(economics,'evaluate',wraps=original) as called:
            result=compare_scenarios(specs)
            self.assertEqual(called.call_count,len(specs))
        for row in result['scenarios']:
            spec=next(s for s in specs if s.scenario_id==row['scenario_id'])
            self.assertEqual(row['engine_result'],economics.result_payload(spec.economics))

    def test_reference_outputs_and_per_contact_contribution(self):
        row=evaluate_scenario(scenario())
        expected=row['engine_result']['expected_values']
        self.assertEqual(expected['expected_incremental_purchasers'],'30')
        self.assertEqual(expected['total_reward_expenditure_eur'],'1150')
        self.assertEqual(expected['total_contact_expenditure_eur'],'0')
        self.assertEqual(net(row),-550)
        self.assertEqual(row['net_contribution_per_contact_eur'],'-0.55')

    def test_break_even_outputs_match_phase9a_exactly(self):
        spec=scenario();row=evaluate_scenario(spec)
        self.assertEqual(row['engine_result']['break_even'],economics.result_payload(spec.economics)['break_even'])
        self.assertEqual(row['engine_result']['break_even']['required_treatment_probability']['exact_fraction'],'4/15')

    def test_profitable_unprofitable_and_neutral_are_distinct(self):
        self.assertFalse(evaluate_scenario(scenario())['profitable_under_assumptions'])
        self.assertTrue(evaluate_scenario(scenario(treatment_conversion='.30'))['profitable_under_assumptions'])
        neutral=evaluate_scenario(scenario(treatment_conversion='.20',reward_per_redemption_eur=0))
        self.assertFalse(neutral['profitable_under_assumptions'])
        self.assertEqual(neutral['financial_status'],'break_even')

    def test_equal_net_values_share_rank_without_financial_tie_preference(self):
        result=compare_scenarios([scenario('b'),scenario('a'),scenario('c',treatment_conversion='.20')])
        self.assertEqual([(r['scenario_id'],r['rank']) for r in result['ranking']],[('a',1),('b',1),('c',3)])

    def test_all_negative_ranking_is_not_a_profit_recommendation(self):
        result=compare_scenarios([scenario('a'),scenario('b',treatment_conversion='.20')])
        self.assertEqual(result['ranking'][0]['scenario_id'],'a')
        self.assertFalse(any(r['profitable_under_assumptions'] for r in result['ranking']))

    def test_non_comparable_populations_horizons_and_accounting_block_ranking(self):
        for field,value in [('population_id','different-population'),('horizon_days',30),('financial_basis_id','other-accounting')]:
            with self.subTest(field=field):
                other=replace(scenario('other'),**{field:value})
                result=compare_scenarios([scenario(),other])
                self.assertFalse(result['comparable_by_declared_criteria'])
                self.assertIsNone(result['ranking'])
                self.assertIn(field,result['ranking_blocked_reasons'])
                self.assertEqual(len(result['scenarios']),2)

    def test_different_counts_baselines_and_margins_block_total_ranking(self):
        for field,value in [('contacted_customers',2000),('baseline_conversion','.10'),('contribution_per_purchase_eur',40)]:
            with self.subTest(field=field):
                result=compare_scenarios([scenario(),scenario('other',**{field:value})])
                self.assertIsNone(result['ranking'])
                self.assertIn(field,result['ranking_blocked_reasons'])

    def test_zero_contacts_have_no_per_contact_value_or_ranking(self):
        spec=scenario(contacted_customers=0)
        row=evaluate_scenario(spec)
        self.assertEqual(net(row),0)
        self.assertIsNone(row['net_contribution_per_contact_eur'])
        self.assertEqual(row['financial_status'],'no_contacts')
        self.assertIsNone(compare_scenarios([spec])['ranking'])

    def test_comparison_reproducibility_and_input_order_independence(self):
        specs=[scenario('b'),scenario('a',redemption_probability='.5')]
        self.assertEqual(compare_scenarios(specs),compare_scenarios(reversed(specs)))


class SensitivityTests(unittest.TestCase):
    def test_all_five_requested_sensitivity_calculations(self):
        examples={
            'treatment_conversion':(['.20','.23','.26','.27','.30'],[-1000,-550,-100,50,500]),
            'reward_per_redemption_eur':([0,2,5,8],[600,140,-550,-1240]),
            'redemption_probability':([0,'.5',1],[600,25,-550]),
            'contribution_per_purchase_eur':([10,20,40],[-850,-550,50]),
            'contact_cost_per_customer_eur':([0,'.05','.20'],[-550,-600,-750])}
        for field,(values,expected) in examples.items():
            with self.subTest(field=field):
                result=sensitivity(scenario(),field,values)
                self.assertEqual([net(p['evaluation']) for p in result['points']],expected)
                self.assertIsNone(result['ranking'])

    def test_exactly_one_assumption_changes_and_no_reward_response_is_invented(self):
        result=sensitivity(scenario(),'reward_per_redemption_eur',[0,5])
        for point in result['points']:
            inputs=point['evaluation']['engine_result']['inputs']
            self.assertEqual(inputs['treatment_conversion'],'0.23')
            for k,v in result['held_constant_inputs'].items():self.assertEqual(inputs[k],v)

    def test_treatment_sensitivity_keeps_break_even_constant(self):
        points=sensitivity(scenario(),'treatment_conversion',['.20','.30'])['points']
        self.assertEqual(points[0]['evaluation']['engine_result']['break_even'],points[1]['evaluation']['engine_result']['break_even'])

    def test_margin_sensitivity_is_reported_without_comparability_claim(self):
        result=sensitivity(scenario(),'contribution_per_purchase_eur',[20,40])
        self.assertIsNone(result['ranking'])
        self.assertEqual(result['points'][1]['evaluation']['engine_result']['break_even']['required_treatment_probability']['exact_fraction'],'8/35')

    def test_sensitivity_order_and_results_reproducible_without_mutating_base(self):
        base=scenario()
        before=economics.result_payload(base.economics)
        self.assertEqual(sensitivity(base,'reward_per_redemption_eur',[5,2,0]),sensitivity(base,'reward_per_redemption_eur',[0,2,5]))
        self.assertEqual(before,economics.result_payload(base.economics))


class ValidationTests(unittest.TestCase):
    def test_invalid_or_duplicate_comparison_inputs(self):
        for value in [None,[], 'one-scenario',[{}]]:
            with self.subTest(value=value),self.assertRaises(ValueError):compare_scenarios(value)
        with self.assertRaisesRegex(ValueError,'duplicate'):compare_scenarios([scenario(),scenario()])

    def test_metadata_validation(self):
        for values in [{'scenario_id':''},{'population_id':' '},{'financial_basis_id':None},
                       {'assumptions_note':''},{'horizon_days':0},{'horizon_days':True},{'economics':{}}]:
            with self.subTest(values=values),self.assertRaises(ValueError):replace(scenario(),**values)

    def test_every_scenario_has_explicit_economic_inputs(self):
        with self.assertRaises(ValueError):scenario_from_dict({'scenario_id':'missing'})
        raw={'scenario_id':'bad','population_id':'p','horizon_days':14,'financial_basis_id':'f','assumptions_note':'hypothetical',
             'economics':{'contacted_customers':1000,'baseline_conversion':'.2','treatment_conversion':'1.1',
                          'contribution_per_purchase_eur':20,'reward_per_redemption_eur':5,
                          'redemption_probability':1,'contact_cost_per_customer_eur':0}}
        with self.assertRaises(ValueError):scenario_from_dict(raw)

    def test_invalid_sensitivity_inputs_and_duplicate_numeric_values(self):
        for field,values in [('baseline_conversion',[.2]),('reward_per_redemption_eur',[]),
              ('reward_per_redemption_eur','5'),('reward_per_redemption_eur',[2,'2.0']),
              ('redemption_probability',['1.1']),('reward_per_redemption_eur',[-1])]:
            with self.subTest(field=field,values=values),self.assertRaises(ValueError):sensitivity(scenario(),field,values)

    def test_precision_independent_of_external_decimal_context(self):
        specs=[scenario('a'),scenario('b',contacted_customers=1000,redemption_probability='.5')]
        expected=compare_scenarios(specs)
        with localcontext() as ctx:
            ctx.prec=2;ctx.rounding=ROUND_DOWN;ctx.traps[Inexact]=True
            self.assertEqual(compare_scenarios(specs),expected)

    def test_configured_examples_reproduce_and_non_comparable_set_is_unranked(self):
        root=Path(__file__).resolve().parents[1]
        cfg=json.loads((root/'docs/rewards/phase9b_scenario_config.json').read_text())
        a=run_examples(cfg);b=run_examples(cfg)
        self.assertEqual(a,b)
        self.assertIsNone(a['non_comparable_demonstration']['ranking'])
        self.assertEqual(len(a['sensitivities']),5)


if __name__=='__main__':unittest.main()
