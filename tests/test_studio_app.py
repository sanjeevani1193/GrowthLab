"""Actual Streamlit AppTest startup, pages, controls and no-data portability."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

try:
    from streamlit.testing.v1 import AppTest
    AVAILABLE=True
except ImportError:
    AVAILABLE=False

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(AVAILABLE,'Install requirements-studio.lock to run UI tests')
class StudioAppTests(unittest.TestCase):
    def app(self,page='Overview'):
        app=AppTest.from_file(str(ROOT/'streamlit_app.py'),default_timeout=30).run()
        if page!='Overview':app.sidebar.radio(key='studio_page').set_value(page).run()
        return app

    def assert_clean(self,app):
        self.assertFalse(list(app.exception),[x.message for x in app.exception])
        self.assertFalse(list(app.error),[x.value for x in app.error])

    def test_startup_and_all_seven_pages(self):
        app=self.app()
        for page in ('Overview','Purchase Intelligence','RetailHero Targeting','Experiment Lab','Reward Economics','Product Ranking','Methodology'):
            with self.subTest(page=page):
                app.sidebar.radio(key='studio_page').set_value(page).run();self.assert_clean(app)
                if page=='Methodology':
                    self.assertEqual(len(app.table),1)
                    self.assertEqual(app.table[0].value.shape,(5,4))
                    self.assertIn('Assumption-dependent intervention estimates',app.table[0].value['Evidence'].tolist())

    def test_headline_displays(self):
        app=self.app();values=[m.value for m in app.metric]
        self.assertIn('0.8487',values);self.assertIn('+3.39 pp',values)
        self.assertIn('79.3%',values);self.assertIn('18.42%',values)
        self.assertIn('Evidence & Sources',[e.label for e in app.expander])

    def test_overview_navigation_button(self):
        app=self.app();app.button(key='go_Product Ranking').click().run()
        self.assertEqual(app.sidebar.radio(key='studio_page').value,'Product Ranking');self.assert_clean(app)

    def test_purchase_model_changes_displayed_results(self):
        app=self.app('Purchase Intelligence')
        app.selectbox(key='purchase_model').set_value('logistic_regression').run()
        self.assertIn('0.8081',[x.value for x in app.metric]);self.assert_clean(app)
        self.assertTrue(any('seven calendar days after their first observed customer event' in x.value for x in app.markdown))

    def test_contact_budget_uses_saved_choices(self):
        app=self.app('RetailHero Targeting')
        for budget in (10,20,30):
            app.select_slider(key='sms_budget').set_value(budget).run();self.assert_clean(app)
            self.assertEqual(app.select_slider(key='sms_budget').value,budget)
            self.assertEqual(int(app.dataframe[0].value.iloc[0]['Contacted']),{10:4001,20:8002,30:12003}[budget])

    def test_ranking_k_and_aggregation_change_actual_metrics(self):
        app=self.app('Product Ranking')
        app.select_slider(key='ranking_k').set_value(20).run()
        self.assertIn('22.69%',[m.value for m in app.metric])
        app.radio(key='ranking_aggregation').set_value('Per purchased pair (micro)').run()
        self.assertIn('18.85%',[m.value for m in app.metric]);self.assert_clean(app)
        self.assertIn('Micro candidate recall ceiling',[m.label for m in app.metric])
        self.assertTrue(any('purchased-pair weighted' in c.value for c in app.caption))

    def test_reward_input_recalculates_net(self):
        from growthlab.studio.ui import money
        for value,expected in [(-550,'-€550.00'),(-1234.5,'-€1,234.50'),(0,'€0.00'),(600,'€600.00')]:
            self.assertEqual(money(value),expected)
        app=self.app('Reward Economics');self.assertIn('-€550.00',[m.value for m in app.metric])
        app.number_input(key='reward_value').set_value(0.).run()
        self.assertIn('€600.00',[m.value for m in app.metric]);self.assert_clean(app)

    def test_unequal_experiment_design_works_and_simulations_stay_fixed(self):
        app=self.app('Experiment Lab');self.assertIn('5,886',[m.value for m in app.metric])
        app.select_slider(key='design_share').set_value(30).run();self.assert_clean(app)
        self.assertNotIn('5,886',[m.value for m in app.metric])
        self.assertIn('4.3%',[m.value for m in app.metric]);self.assertIn('79.3%',[m.value for m in app.metric])

    def test_invalid_design_is_readable_error(self):
        app=self.app('Experiment Lab');app.number_input(key='design_baseline').set_value(99.).run()
        self.assertFalse(list(app.exception));self.assertTrue(list(app.error))

    def test_missing_evidence_does_not_raise_app_exception(self):
        from growthlab.studio.evidence import EvidenceError
        with patch('growthlab.studio.pages.data',side_effect=EvidenceError('Missing aggregate evidence: unit-test.json')):
            app=self.app()
        self.assertFalse(list(app.exception));self.assertTrue(list(app.error))

    def test_public_app_runs_in_fresh_copy_without_data_or_models(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)
            shutil.copy(ROOT/'streamlit_app.py',target/'streamlit_app.py')
            shutil.copytree(ROOT/'src',target/'src',ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copytree(ROOT/'docs',target/'docs')
            self.assertFalse((target/'data').exists())
            code="""from streamlit.testing.v1 import AppTest
app=AppTest.from_file('streamlit_app.py',default_timeout=30).run()
for page in ('Overview','Purchase Intelligence','RetailHero Targeting','Experiment Lab','Reward Economics','Product Ranking','Methodology'):
 app.sidebar.radio(key='studio_page').set_value(page).run()
 assert not app.exception and not app.error,page
print('PASS: seven pages without a data directory or trained artifacts')
"""
            result=subprocess.run([sys.executable,'-c',code],cwd=target,capture_output=True,text=True,timeout=120)
            self.assertEqual(result.returncode,0,result.stderr+result.stdout)


if __name__=='__main__':unittest.main()
