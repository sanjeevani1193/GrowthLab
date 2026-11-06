"""Hypothetical hand-calculated reward economics; no observed customer data."""
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, Inexact, ROUND_DOWN, localcontext
from fractions import Fraction
import json
from pathlib import Path
import unittest

from growthlab.rewards.economics import (
    RewardScenario, break_even, evaluate, finite_decimal, result_payload,
)


def reference(**changes):
    base=RewardScenario(1000,'0.20','0.23','20','5','1.0','0')
    return replace(base,**changes)


class ExpectedValueTests(unittest.TestCase):
    def test_verified_reference_example(self):
        r=evaluate(reference())
        self.assertEqual(r.expected_purchasers_without_intervention,200)
        self.assertEqual(r.expected_purchasers_with_intervention,230)
        self.assertEqual(r.expected_incremental_purchasers,30)
        self.assertEqual(r.incremental_conversion_effect_pp,3)
        self.assertEqual(r.expected_incremental_purchase_contribution_eur,600)
        self.assertEqual(r.expected_reward_redemptions,230)
        self.assertEqual(r.total_reward_expenditure_eur,1150)
        self.assertEqual(r.total_contact_expenditure_eur,0)
        self.assertEqual(r.net_incremental_contribution_eur,-550)

    def test_independent_total_cashflow_comparison(self):
        # Independent formulation: total modeled treatment contribution after
        # rewards/contact, minus total baseline contribution. Not only uplift.
        scenario=reference()
        baseline=Fraction(1000)*Fraction(1,5)*20
        treatment=Fraction(1000)*Fraction(23,100)*(20-5)
        self.assertEqual(treatment-baseline,-550)
        self.assertEqual(Fraction(evaluate(scenario).net_incremental_contribution_eur),treatment-baseline)

    def test_zero_voucher_cost(self):
        r=evaluate(reference(reward_per_redemption_eur=0))
        self.assertEqual(r.total_reward_expenditure_eur,0)
        self.assertEqual(r.net_incremental_contribution_eur,600)
        self.assertEqual(r.break_even.required_conversion_change_pp,0)

    def test_zero_effect_still_pays_rewards_on_treatment_purchasers(self):
        r=evaluate(reference(treatment_conversion='.20'))
        self.assertEqual(r.expected_incremental_purchasers,0)
        self.assertEqual(r.total_reward_expenditure_eur,1000)
        self.assertEqual(r.net_incremental_contribution_eur,-1000)

    def test_positive_and_negative_treatment_effects(self):
        positive=evaluate(reference(treatment_conversion='.30'))
        self.assertEqual(positive.incremental_conversion_effect_pp,10)
        self.assertEqual(positive.net_incremental_contribution_eur,500)
        negative=evaluate(reference(treatment_conversion='.15'))
        self.assertEqual(negative.incremental_conversion_effect_pp,-5)
        self.assertEqual(negative.expected_incremental_purchasers,-50)
        self.assertEqual(negative.net_incremental_contribution_eur,-1750)

    def test_partial_redemption_is_conditional_on_treatment_purchase(self):
        r=evaluate(reference(redemption_probability='.5'))
        self.assertEqual(r.expected_reward_redemptions,115)
        self.assertEqual(r.total_reward_expenditure_eur,575)
        self.assertEqual(r.net_incremental_contribution_eur,25)

    def test_no_redemption_means_no_reward_cost(self):
        r=evaluate(reference(redemption_probability=0))
        self.assertEqual(r.expected_reward_redemptions,0)
        self.assertEqual(r.total_reward_expenditure_eur,0)
        self.assertEqual(r.net_incremental_contribution_eur,600)

    def test_contact_cost_applies_to_every_contact(self):
        r=evaluate(reference(contact_cost_per_customer_eur='.20'))
        self.assertEqual(r.total_contact_expenditure_eur,200)
        self.assertEqual(r.net_incremental_contribution_eur,-750)

    def test_fractional_expected_customers_and_subcent_expected_money(self):
        r=evaluate(reference(contacted_customers=3,redemption_probability='.5'))
        self.assertEqual(r.expected_purchasers_without_intervention,Decimal('.6'))
        self.assertEqual(r.expected_purchasers_with_intervention,Decimal('.69'))
        self.assertEqual(r.expected_reward_redemptions,Decimal('.345'))
        self.assertEqual(r.net_incremental_contribution_eur,Decimal('.075'))

    def test_zero_treatment_purchases_no_reward_cost(self):
        r=evaluate(reference(treatment_conversion=0))
        self.assertEqual(r.total_reward_expenditure_eur,0)
        self.assertEqual(r.net_incremental_contribution_eur,-4000)

    def test_zero_customers(self):
        r=evaluate(reference(contacted_customers=0))
        for name,value in vars(r).items():
            if name not in ['break_even','incremental_conversion_effect_pp']:
                self.assertEqual(value,0,name)
        self.assertEqual(r.incremental_conversion_effect_pp,3)  # input probability contrast, not a count
        self.assertEqual(r.break_even.status,'no_customers')
        self.assertIsNone(r.break_even.attainable)


class BreakEvenTests(unittest.TestCase):
    def test_reference_exact_threshold_and_independent_substitution(self):
        b=break_even(reference())
        self.assertTrue(b.attainable)
        self.assertEqual(b.required_treatment_probability,Fraction(4,15))
        self.assertEqual(b.required_conversion_change_pp,Fraction(20,3))
        p=b.required_treatment_probability
        self.assertEqual(1000*p*(20-5)-1000*Fraction(1,5)*20,0)

    def test_net_changes_sign_around_threshold(self):
        self.assertEqual(evaluate(reference(treatment_conversion='.26')).net_incremental_contribution_eur,-100)
        self.assertEqual(evaluate(reference(treatment_conversion='.27')).net_incremental_contribution_eur,50)
        # Rounding the exact threshold to 26.67% is not exactly break-even.
        self.assertEqual(evaluate(reference(treatment_conversion='.2667')).net_incremental_contribution_eur,Decimal('.50'))

    def test_threshold_does_not_depend_on_positive_campaign_size(self):
        self.assertEqual(break_even(reference(contacted_customers=1)),break_even(reference(contacted_customers=100000)))

    def test_partial_redemption_and_contact_cost_thresholds(self):
        partial=break_even(reference(redemption_probability='.5'))
        self.assertEqual(partial.required_treatment_probability,Fraction(8,35))
        cost=break_even(reference(contact_cost_per_customer_eur='.20'))
        self.assertEqual(cost.required_treatment_probability,Fraction(7,25))
        self.assertEqual(cost.required_conversion_change_pp,8)

    def test_probability_above_one_is_unattainable(self):
        b=break_even(reference(baseline_conversion='.9'))
        self.assertFalse(b.attainable)
        self.assertEqual(b.unconstrained_threshold,Fraction(6,5))
        self.assertIsNone(b.required_treatment_probability)

    def test_nonpositive_purchase_margin_with_positive_hurdle(self):
        for margin in [5,4,0]:
            with self.subTest(margin=margin):
                b=break_even(reference(contribution_per_purchase_eur=margin,contact_cost_per_customer_eur='.1'))
                self.assertEqual(b.status,'unattainable')
                self.assertFalse(b.attainable)

    def test_all_rates_can_be_exactly_neutral(self):
        b=break_even(reference(baseline_conversion=0,contribution_per_purchase_eur=5))
        self.assertEqual(b.status,'all_rates_break_even')
        self.assertTrue(b.attainable)
        self.assertIsNone(b.required_treatment_probability)
        self.assertEqual(evaluate(reference(baseline_conversion=0,contribution_per_purchase_eur=5)).net_incremental_contribution_eur,0)

    def test_zero_conversion_only_is_not_a_profitable_improvement(self):
        b=break_even(reference(baseline_conversion=0,contribution_per_purchase_eur=4))
        self.assertEqual(b.status,'zero_conversion_only')
        self.assertEqual(b.required_treatment_probability,0)
        self.assertLess(evaluate(reference(baseline_conversion=0,contribution_per_purchase_eur=4)).net_incremental_contribution_eur,0)
        reduction=break_even(reference(contribution_per_purchase_eur=0))
        self.assertEqual(reduction.required_conversion_change_pp,-20)

    def test_exactly_100_percent_threshold_is_feasible_equality_only(self):
        scenario=reference(baseline_conversion='.75',treatment_conversion=1)
        b=break_even(scenario)
        self.assertTrue(b.attainable)
        self.assertEqual(b.required_treatment_probability,1)
        self.assertEqual(evaluate(scenario).net_incremental_contribution_eur,0)

    def test_zero_margin_zero_cost_all_rates_neutral(self):
        b=break_even(reference(contribution_per_purchase_eur=0,reward_per_redemption_eur=0))
        self.assertEqual(b.status,'all_rates_break_even')


class InputAndPrecisionTests(unittest.TestCase):
    def test_invalid_probabilities_and_nonfinite_inputs(self):
        for name in ['baseline_conversion','treatment_conversion','redemption_probability']:
            for value in ['-.01','1.01','NaN','Infinity',True,None]:
                with self.subTest(name=name,value=value),self.assertRaises(ValueError):reference(**{name:value})
        for value in [float('inf'),float('nan'),'not money']:
            with self.subTest(value=value),self.assertRaises(ValueError):reference(reward_per_redemption_eur=value)

    def test_negative_money_and_invalid_customer_counts(self):
        for name in ['contribution_per_purchase_eur','reward_per_redemption_eur','contact_cost_per_customer_eur']:
            with self.subTest(name=name),self.assertRaises(ValueError):reference(**{name:'-.01'})
        for n in [-1,1000.,'1000',True]:
            with self.subTest(n=n),self.assertRaises(ValueError):reference(contacted_customers=n)
        with self.assertRaises(ValueError):reference(contacted_customers=0,reward_per_redemption_eur=-1)

    def test_probability_endpoints_are_valid(self):
        self.assertEqual(evaluate(reference(baseline_conversion=0,treatment_conversion=1)).expected_incremental_purchasers,1000)

    def test_exact_results_are_independent_of_ambient_decimal_context(self):
        before=result_payload(reference())
        with localcontext() as context:
            context.prec=2; context.rounding=ROUND_DOWN; context.traps[Inexact]=True
            self.assertEqual(evaluate(reference()).net_incremental_contribution_eur,-550)
            self.assertEqual(result_payload(reference()),before)

    def test_large_inputs_do_not_silently_round_expected_totals(self):
        n=10**60+1
        r=evaluate(reference(contacted_customers=n))
        self.assertEqual(Fraction(r.net_incremental_contribution_eur),Fraction(-11,20)*n)

    def test_reproducibility_and_frozen_inputs(self):
        scenario=reference()
        self.assertEqual(evaluate(scenario),evaluate(scenario))
        self.assertEqual(result_payload(scenario),result_payload(scenario))
        with self.assertRaises(FrozenInstanceError):scenario.baseline_conversion=Decimal('.3')

    def test_json_configuration_and_exact_fraction_serialization(self):
        root=Path(__file__).resolve().parents[1]
        scenario=RewardScenario(**json.loads((root/'docs/rewards/phase9a_reference_config.json').read_text()))
        payload=result_payload(scenario)
        self.assertEqual(payload['expected_values']['net_incremental_contribution_eur'],'-550')
        self.assertEqual(payload['break_even']['required_treatment_probability']['exact_fraction'],'4/15')
        self.assertEqual(scenario,reference())

    def test_finite_fraction_conversion(self):
        for value in [Fraction(1,2),Fraction(1,5),Fraction(1,20),Fraction(-23,1000),Fraction(0)]:
            self.assertEqual(Fraction(finite_decimal(value)),value)
        with self.assertRaises(ValueError):finite_decimal(Fraction(1,3))


if __name__=='__main__':unittest.main()
