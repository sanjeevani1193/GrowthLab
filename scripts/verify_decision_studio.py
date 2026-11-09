"""Browser smoke checks against an already running, local-only Streamlit app.

Requires requirements-studio-test.lock and a Playwright Chromium installation.
Writes screenshots and a check receipt outside Git by default; never reads data.
"""
import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright, expect


PAGES = {
    'Overview': None,
    'Purchase Intelligence': 'Purchase Intelligence',
    'RetailHero Targeting': 'Experimentation & uplift',
    'Experiment Lab': 'A/B Experiment Design Lab',
    'Reward Economics': 'Reward Economics Simulator',
    'Product Ranking': 'Product Ranking Intelligence',
    'Methodology': 'Methodology & limitations',
}


def navigate(page, name):
    # Click the visible label: React Aria deliberately clips its native input.
    page.get_by_test_id('stSidebar').get_by_test_id('stRadioOption').filter(
        has=page.get_by_text(name, exact=True)).click()
    if PAGES[name]:
        expect(page.get_by_role('heading', name=PAGES[name], exact=True)).to_be_visible()
    else:
        expect(page.locator('.hero')).to_be_visible()
    page.wait_for_timeout(350)
    expect(page.get_by_test_id('stApp')).to_have_attribute('data-test-script-state','notRunning',timeout=15000)


def capture(page, name, output):
    expect(page.get_by_test_id('stException')).to_have_count(0)
    if name == 'Overview':
        expect(page.get_by_test_id('stAlert')).to_have_count(0)
    # Plotly renders asynchronously after Streamlit sends the chart spec.
    for plot in page.get_by_test_id('stPlotlyChart').all():
        if plot.is_visible():
            expect(plot.locator('.js-plotly-plot')).to_be_visible(timeout=15000)
            expect(plot.locator('.main-svg').first).to_be_visible(timeout=15000)
    page.get_by_test_id('stMain').evaluate('(e)=>e.scrollTo(0,0)')
    page.screenshot(path=str(output / (name.lower().replace(' ', '_')+'.png')), full_page=True)
    sizes=page.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth})')
    if sizes['scroll'] > sizes['width']+1:
        raise AssertionError(f'Document overflow: {name}: {sizes}')
    return {'page':name,'charts':page.get_by_test_id('stPlotlyChart').count(),
            'document_width':sizes['scroll'],'viewport':sizes['width']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8501')
    parser.add_argument('--output',type=Path,default=Path('/tmp/growthlab-studio-browser'))
    args=parser.parse_args()
    if not args.url.startswith(('http://127.0.0.1:','http://localhost:')):
        parser.error('Use an existing localhost Streamlit server.')
    args.output.mkdir(parents=True,exist_ok=True)
    receipt={'pages':[],'interactions':[],'browser_errors':[]}
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch()
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror',lambda error:receipt['browser_errors'].append(str(error)))
        page.goto(args.url)
        expect(page.locator('.hero')).to_be_visible(timeout=30000)
        for name in PAGES:
            navigate(page,name)
            receipt['pages'].append(capture(page,name,args.output))

        navigate(page,'Overview')
        evidence=page.get_by_role('link',name='docs/phase4/test_summary.json',exact=True)
        expect(evidence).not_to_be_visible()
        page.get_by_text('Evidence & Sources',exact=True).click()
        expect(evidence).to_be_visible()
        page.wait_for_timeout(350)
        capture(page,'Overview expanded evidence',args.output)
        evidence.scroll_into_view_if_needed()
        page.screenshot(path=str(args.output/'overview_sources.png'))
        receipt['interactions'].append('Overview evidence links expand from Evidence & Sources')

        navigate(page,'Purchase Intelligence')
        expect(page.get_by_text('Identify likely future purchasers using activity in the seven calendar days after their first observed customer event.',exact=True)).to_be_visible()
        page.get_by_test_id('stSelectbox').click()
        page.get_by_role('option',name='Logistic Regression',exact=True).click()
        expect(page.get_by_test_id('stMetricValue').filter(has_text='0.8081')).to_be_visible()
        receipt['interactions'].append('Purchase model: Logistic Regression AUC 0.8081')

        navigate(page,'RetailHero Targeting')
        page.get_by_role('tab',name='Final targeting policies').click()
        slider=page.get_by_role('slider');slider.focus();slider.press('Home')
        expect(slider).to_have_attribute('aria-valuetext','10')
        expect(page.get_by_text('Each budget-matched policy contacts 4,001.',exact=False)).to_be_visible()
        receipt['interactions'].append('RetailHero: 10% budget → 4,001 contacts and saved estimates')
        capture(page,'RetailHero policies',args.output)

        navigate(page,'Experiment Lab')
        share=page.get_by_test_id('stSlider').nth(1).get_by_role('slider')
        share.focus();share.press('Home');share.press('ArrowRight')
        expect(share).to_have_attribute('aria-valuetext','30')
        expect(page.get_by_test_id('stMetricValue').filter(has_text='6,949')).to_be_visible()
        expect(page.get_by_test_id('stMetricValue').filter(has_text='79.3%')).to_be_visible()
        receipt['interactions'].append('Unequal allocation selected; saved A/B power stays 79.3%')

        navigate(page,'Reward Economics')
        expect(page.get_by_test_id('stMetricValue').filter(has_text='-€550.00')).to_be_visible()
        reward=page.get_by_role('spinbutton',name='Reward / redemption (€)')
        reward.fill('0');reward.press('Enter')
        expect(page.get_by_test_id('stMetricValue').filter(has_text='€600.00')).to_be_visible()
        page.get_by_role('tab',name='Compare scenarios',exact=True).click()
        expect(page.get_by_test_id('stDataFrame')).to_be_visible()
        page.get_by_role('tab',name='Sensitivity',exact=True).click()
        expect(page.get_by_test_id('stPlotlyChart').last).to_be_visible()
        receipt['interactions'].append('Zero reward → €600 net; scenario and sensitivity tabs render')
        capture(page,'Reward sensitivity',args.output)

        navigate(page,'Product Ranking')
        expect(page.get_by_text('Macro candidate recall ceiling',exact=True)).to_be_visible()
        expect(page.get_by_text('Micro: purchased-pair weighted, not a customer average.',exact=True)).to_be_visible()
        slider=page.get_by_role('slider');slider.focus();slider.press('End')
        expect(page.get_by_test_id('stMetricValue').filter(has_text='22.69%')).to_be_visible()
        page.get_by_test_id('stRadioOption').filter(
            has=page.get_by_text('Per purchased pair (micro)',exact=True)).click()
        expect(page.get_by_test_id('stMetricValue').filter(has_text='18.85%')).to_be_visible()
        receipt['interactions'].append('Ranking K=20 macro 22.69% → micro 18.85%')
        capture(page,'Ranking micro20',args.output)

        mobile=browser.new_page(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
        mobile.on('pageerror',lambda error:receipt['browser_errors'].append(str(error)))
        mobile.goto(args.url)
        expect(mobile.locator('.hero')).to_be_visible(timeout=30000)
        receipt['pages'].append(capture(mobile,'Mobile overview',args.output))
        mobile.get_by_text('Evidence & Sources',exact=True).click()
        sources=mobile.get_by_role('link',name='docs/phase4/test_summary.json',exact=True)
        expect(sources).to_be_visible()
        mobile.wait_for_timeout(350)
        sources.scroll_into_view_if_needed()
        mobile.screenshot(path=str(args.output/'mobile_overview_sources.png'))
        receipt['pages'].append(capture(mobile,'Mobile overview expanded sources',args.output))
        mobile.get_by_test_id('stExpandSidebarButton').click()
        navigate(mobile,'Product Ranking')
        mobile.get_by_test_id('stSidebarCollapseButton').click()
        mobile.wait_for_timeout(500)
        receipt['pages'].append(capture(mobile,'Mobile ranking',args.output))
        mobile.get_by_test_id('stPlotlyChart').first.scroll_into_view_if_needed()
        mobile.screenshot(path=str(args.output/'mobile_ranking_chart.png'))
        for name in ('Purchase Intelligence','Reward Economics','Methodology'):
            mobile.get_by_test_id('stExpandSidebarButton').click()
            navigate(mobile,name)
            mobile.get_by_test_id('stSidebarCollapseButton').click()
            mobile.wait_for_timeout(500)
            receipt['pages'].append(capture(mobile,'Mobile '+name,args.output))
            if name=='Methodology':
                table=mobile.locator('.st-key-methodology_summary [data-testid="stTable"] > div')
                assert table.evaluate('(e)=>e.scrollWidth>e.clientWidth'), 'Expected internal table scrolling on mobile'
                table.evaluate('(e)=>e.scrollLeft=e.scrollWidth')
                expect(table.get_by_text('Assumption-dependent intervention estimates',exact=True)).to_be_visible()
                mobile.screenshot(path=str(args.output/'mobile_methodology_evidence.png'))
                receipt['interactions'].append('Methodology wraps full cell descriptions; mobile table scroll reaches Evidence column')
        browser.close()
    if receipt['browser_errors']:
        raise AssertionError(receipt['browser_errors'])
    (args.output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':
    main()
