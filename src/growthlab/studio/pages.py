"""Business-facing workspaces backed only by committed aggregate evidence."""
import json
from decimal import Decimal

import plotly.graph_objects as go
import streamlit as st

from .ui import (data,header,decision,source,chart,bars,intervals,style_figure,
                 pct,money,TEAL,NAVY,SLATE,RED,REPO)
from .evidence import (MODEL_NAMES,RANK_NAMES,purchase_rows,policy_rows,ranking_rows,ranking_difference)
from .calculations import (plan_experiment,scenario_from_inputs,result_payload,
                          compare_with_saved,sensitivity_points)

PAGES=('Overview','Purchase Intelligence','RetailHero Targeting','Experiment Lab',
       'Reward Economics','Product Ranking','Methodology')


def navigate(page):st.session_state['studio_page']=page


def overview():
    purchase=data('purchase');experiment=data('experiment');aa=data('aa');ab=data('ab');ranking=data('ranking')
    xgb=purchase['models']['xgboost']['test'];ml=ranking['methods']['ml']['10']
    st.markdown('''<div class="hero"><div class="eyebrow">GROWTHLAB DECISION STUDIO</div>
    <h1>From customer signals<br>to better decisions.</h1>
    <p>Explore who might buy, whether a campaign worked, what an incentive could cost,
    and which products belong at the top of the list.</p>
    <span class="pill">FROZEN EVIDENCE · INTERACTIVE PLANNING</span></div>''',unsafe_allow_html=True)
    cols=st.columns(4)
    with cols[0]:
        st.metric('Purchase prediction · ROC-AUC',f"{xgb['roc_auc']:.4f}")
        st.caption(f"REES46 · {xgb['lift_at_top_10_percent']:.2f}× top-decile predictive lift")
    with cols[1]:
        st.metric('SMS/control · observed gap',f"+{experiment['statistics']['difference_pp']:.2f} pp")
        st.caption('RetailHero training cohort · learned targeting superiority not established')
    with cols[2]:
        st.metric('Simulated A/B · empirical power',pct(ab['empirical_power']['empirical_rate'],1))
        st.caption(f"Synthetic experiments · {pct(aa['false_positives']['empirical_rate'],1)} A/A false-positive rate")
    with cols[3]:
        st.metric('Product ranking · Recall@10',pct(ml['recall_macro']))
        st.caption(f"REES46 final · {ml['ndcg_macro']:.5f} NDCG@10 · mean per purchaser")
    st.write('')
    st.subheader('Choose a business question')
    cards=[('Purchase Intelligence','Who is likely to purchase next?',
            'Compare observed purchase prediction, top-decile concentration and calibration.','REES46 · observed behavior'),
           ('RetailHero Targeting','Did learned targeting beat random?',
            'Inspect the held-out policy estimates, paired uncertainty and identification caveats.','RETAILHERO · separate population'),
           ('Reward Economics','Can an incentive pay for itself?',
            'Change hypothetical response and costs. Compare net contribution and break-even.','HYPOTHETICAL · expected values'),
           ('Product Ranking','Which products should come first?',
            'Explore three fixed methods, ranking metrics and the candidate-retrieval ceiling.','REES46 · offline ranking')]
    for offset in (0,2):
        columns=st.columns(2)
        for column,(page,title,body,tag) in zip(columns,cards[offset:offset+2]):
            with column,st.container(border=True):
                st.caption(tag);st.subheader(title);st.write(body)
                st.button(f'Explore {page}',key='go_'+page,on_click=navigate,args=(page,),width='stretch')
    st.button('Plan a hypothetical A/B experiment',key='go_Experiment Lab',on_click=navigate,args=('Experiment Lab',))
    decision('Predictive lift, experiment group differences, hypothetical profit and ranking recall answer different questions. They are not interchangeable measures of business impact.')
    with st.expander('Evidence & Sources'):
        source('purchase','experiment','uplift','aa','ab','ranking')


def purchase_intelligence():
    d=data('purchase');spec=data('purchase_spec')
    header('Purchase Intelligence','Identify likely future purchasers using activity in the seven calendar days after their first observed customer event.','REES46 · HELD-OUT BENCHMARK')
    st.caption('One observed customer ID · 7-day history → next 30-day purchase · chronological evaluation')
    selected=st.selectbox('Inspect a model',['xgboost','logistic_regression','dummy'],format_func=MODEL_NAMES.get,key='purchase_model')
    metrics=d['models'][selected]['test']
    columns=st.columns(4)
    for col,label,value in zip(columns,['ROC-AUC','Average precision','Top-10% recall','Predictive lift'],
            [f"{metrics['roc_auc']:.4f}",f"{metrics['average_precision']:.4f}",pct(metrics['recall_at_top_10_percent']),f"{metrics['lift_at_top_10_percent']:.2f}×"]):
        col.metric(label,value)
    st.subheader('What the top decile contains')
    left,right=st.columns([1.25,1])
    with left:
        captured=metrics['top_10_percent_positive_labels'];total=d['test_positive_labels']
        fig=go.Figure(go.Pie(labels=['Purchasers in top 10%','Other purchasers'],values=[captured,total-captured],
            hole=.72,marker_colors=[TEAL,'#DCE5EC'],textinfo='percent',sort=False))
        chart(style_figure(fig,height=320),'purchase_decile','Observed purchasers captured inside and outside the top decile.')
    with right:
        st.metric('Purchasers captured',f'{captured:,} / {total:,}')
        st.write(f"**{metrics['top_10_percent_count']:,} customers** in the top decile; **{pct(metrics['precision_at_top_10_percent'])} precision**.")
        st.write('Precision asks: of those selected, how many purchased? Recall asks: of all purchasers, how many did we find? Lift compares selected-group purchase frequency with the cohort average.')
        st.caption('Only the frozen 10% contact threshold is available. No performance is estimated at arbitrary budgets.')
    st.subheader('Compare models on the same held-out customers')
    measure=st.radio('Comparison metric',['ROC-AUC','Average precision','Top-10% recall'],horizontal=True,key='purchase_measure')
    field,scale={'ROC-AUC':('roc_auc',1),'Average precision':('average_precision',1),'Top-10% recall':('recall_at_top_10_percent',100)}[measure]
    records=purchase_rows(d)
    chart(bars([r['Model'] for r in records],[r[field] for r in records],measure+(' (%)' if scale==100 else ''),scale),'purchase_models','Frozen held-out model comparison.')
    decision('XGBoost was selected using validation before test scoring. Predictive lift describes purchaser concentration; it does not show that contacting those customers changes their behavior.')
    st.subheader('Calibration: useful ranking, imperfect probabilities')
    fig=go.Figure()
    for model,name,color in [('xgboost','Raw XGBoost',NAVY),('xgboost_calibrated','Validation-calibrated',TEAL)]:
        points=d['models'][model]['reliability']
        fig.add_trace(go.Scatter(x=[p['mean_predicted_probability']*100 for p in points],
            y=[p['observed_purchase_rate']*100 for p in points],mode='markers',name=name,marker={'size':11,'color':color}))
    fig.add_trace(go.Scatter(x=[0,12],y=[0,12],mode='lines',line={'dash':'dot','color':SLATE},name='Perfect calibration reference'))
    fig=style_figure(fig,'Observed purchase rate (%)');fig.update_layout(xaxis_title='Mean predicted probability (%)')
    chart(fig,'purchase_calibration','Saved reliability-bin points, with a mathematical perfect-calibration reference.')
    st.dataframe([{'Probability variant':MODEL_NAMES[m],
        'Brier score':f"{d['models'][m]['test']['brier_score']:.6f}",
        'Log loss':f"{d['models'][m]['test']['log_loss']:.6f}",
        'Mean prediction':pct(d['models'][m]['test']['mean_predicted_probability'],3),
        'Observed prevalence':pct(d['test_prevalence'],3)} for m in ('xgboost','xgboost_calibrated')],hide_index=True,width='stretch')
    st.info('Validation-only calibration reduced probability error but still overpredicted the held-out purchase rate. Ranking and selected customers were unchanged.')
    with st.expander('Methodology, features and limitations'):
        st.write(f"{d['test_customers']:,} held-out customers / {d['test_positive_labels']:,} purchasers. Twelve past-only behavioral predictors; first observed does not mean newly acquired.")
        st.write(spec['feature_columns'])
        st.write('Frozen prediction-time cohorts (UTC, end-exclusive):')
        st.dataframe([dict(zip(('Split','Start','End','Customers','Purchasers'),row)) for row in spec['primary_splits']],hide_index=True,width='stretch')
        st.markdown(f'[Full frozen evaluation report]({REPO}/blob/main/docs/phase4_final_evaluation.md)')
        st.write('Missing metadata, imperfect identity/order semantics, one retailer, temporal prevalence drift and unknown logging losses limit generalization. No ROC/PR curve was reconstructed from scalar metrics.')
    source('purchase','purchase_spec')


def retailhero():
    e=data('experiment');d=data('uplift');stats=e['statistics']
    header('Experimentation & uplift','Separate the overall SMS/control comparison from the question of whom to contact.','RETAILHERO · ASSUMPTION-DEPENDENT STUDY')
    observed,policies=st.tabs(['Observed experiment','Final targeting policies'])
    with observed:
        st.subheader('Observed training-cohort group difference')
        cols=st.columns(3)
        cols[0].metric('SMS group purchase rate',pct(stats['treated_rate']))
        cols[1].metric('Control group purchase rate',pct(stats['control_rate']))
        cols[2].metric('SMS minus control',f"{stats['difference_pp']:+.2f} pp")
        st.write(f"95% interval: **{stats['ci95_pp'][0]:+.2f} to {stats['ci95_pp'][1]:+.2f} pp**. Training customers: {stats['treated_n']+stats['control_n']:,}.")
        chart(bars(['Control','SMS'],[stats['control_rate'],stats['treated_rate']],'Observed purchase rate (%)',100,[SLATE,TEAL]),'sms_groups','Observed training-group purchase rates; not a targeting comparison.')
        st.warning('The original randomization/compliance protocol was not independently verified. This is an observed group difference; a causal interpretation requires additional assumptions.')
    with policies:
        st.subheader('Compare frozen policies at an evaluated contact budget')
        budget=st.select_slider('Contact budget (%)',options=[10,20,30],value=30,key='sms_budget')
        table=policy_rows(d,budget)
        chart(intervals([r['Policy'] for r in table],[r['Estimate'] for r in table],[r['Lower'] for r in table],[r['Upper'] for r in table],
            'Estimated incremental purchasers per 1,000 population customers'),'policy_intervals','Frozen inverse-propensity policy estimates with 95% intervals.')
        st.caption(f"Final holdout: {d['n']:,} customers. Each budget-matched policy contacts {table[0]['Contacted']:,}. Estimates assume treatment probability e=0.5.")
        st.dataframe([{'Policy':r['Policy'],'Contacted':r['Contacted'],
            'Estimate per 1,000':f"{r['Estimate']:.2f}",'95% interval':f"[{r['Lower']:.2f}, {r['Upper']:.2f}]"} for r in table],hide_index=True,width='stretch')
        paired=d['paired_policy_differences'][f's_learner/{budget}% minus constant/{budget}%']
        lo,hi=paired['ci95_per_1000']
        st.metric('Paired S-Learner minus fixed-random',f"{paired['difference_per_1000']:+.2f} / 1,000")
        st.write(f'Paired 95% interval: **[{lo:+.2f}, {hi:+.2f}]** per 1,000 population customers.')
        decision('No learned targeting policy established superiority over fixed-random targeting. Keep random as the cautious budget-matched reference; this does not prove it is optimal.')
        with st.expander('Contact-all / contact-none reference policies'):
            st.dataframe([{'Reference':name,'Contacted':d['policies'][key]['selected_n'],
                'Estimate per 1,000':f"{d['policies'][key]['incremental_per_1000']:.2f}",
                '95% interval':str([round(x*1000,2) for x in d['policies'][key]['incremental_value_ci95']])}
                for key,name in [('none','Contact nobody'),('all','Contact everybody')]],hide_index=True,width='stretch')
    with st.expander('Policy-value methodology and identification caveats'):
        st.write('Inverse-propensity policy value compares expected outcomes under a contact policy with contacting nobody, assuming constant assignment probability 0.5. It is not a comparison of raw purchase rates alone. Intervals use 500 paired treatment-stratified bootstrap draws with fixed fitted models.')
        st.write('Unknown assignment/compliance, exact outcome horizon, interference and propensity can change interpretation. These are assumption-dependent estimates, not verified causal effects or individual treatment benefits. No SMS cost or financial return is inferred.')
        st.markdown(f'[Frozen final policy evaluation]({REPO}/blob/main/docs/causal/phase7_final_evaluation.md)')
    source('experiment','uplift')


def experiment_lab():
    aa=data('aa');ab=data('ab');planning=data('planning')
    header('A/B Experiment Design Lab','Plan a hypothetical customer-level experiment, then inspect the saved statistical validation.','SIMULATED · NOT A REAL VOUCHER CAMPAIGN')
    st.subheader('Design assumptions')
    a,b,c=st.columns(3)
    baseline=a.number_input('Baseline conversion (%)',min_value=.1,max_value=99.0,value=20.,step=.1,key='design_baseline')
    mde=b.number_input('Minimum detectable effect (pp)',min_value=.1,max_value=30.,value=3.,step=.1,key='design_mde')
    alpha=c.number_input('Significance level (two-sided)',min_value=.001,max_value=.2,value=.05,step=.005,format='%.3f',key='design_alpha')
    a,b=st.columns(2)
    power=a.slider('Statistical power (%)',min_value=51,max_value=99,value=80,key='design_power')
    share=b.select_slider('Treatment allocation (%)',options=[20,30,40,50,60,70,80],value=50,key='design_share')
    try:
        result=plan_experiment(baseline/100,mde/100,alpha,power/100,share/100)
        cols=st.columns(3)
        cols[0].metric('Planned control customers',f"{result['control_n']:,}")
        cols[1].metric('Planned treatment customers',f"{result['treatment_n']:,}")
        cols[2].metric('Total required customers',f"{result['total_n']:,}")
        st.caption(result['allocation_method']+' · approximate independent two-proportion planning; no continuity correction.')
    except ValueError as error:st.error(str(error))
    st.write('The MDE is the smallest absolute improvement you plan to detect. Power is the chance of detecting that assumed effect; it is not the probability that an intervention works. Smaller effects usually need more customers.')
    st.subheader('Frozen simulation benchmarks')
    st.caption('These saved 1,000-run studies stay fixed when planning inputs change. No simulation jobs are launched.')
    columns=st.columns(2)
    columns[0].metric('A/A false-positive frequency',pct(aa['false_positives']['empirical_rate'],1))
    columns[1].metric('A/B empirical power',pct(ab['empirical_power']['empirical_rate'],1))
    diagnostics=[aa['false_positives'],ab['empirical_power']]
    chart(intervals(['A/A false positives','A/B detected effect'],[x['empirical_rate'] for x in diagnostics],
        [x['wilson_95_interval'][0] for x in diagnostics],[x['wilson_95_interval'][1] for x in diagnostics],
        'Frequency across 1,000 synthetic experiments (%)',100),'simulation_intervals','Saved simulation frequencies with Monte Carlo Wilson intervals.')
    st.write(f"A/A uses the same true conversion in both arms ({pct(aa['true_control_rate'],0)}). A/B assumes {pct(ab['true_control_rate'],0)} versus {pct(ab['true_treatment_rate'],0)}. These are hypothetical truths, not measured voucher effects.")
    choice=st.radio('Prespecified example',['A/A · zero effect','A/B · assumed effect'],horizontal=True,key='simulation_example')
    example=(aa if choice.startswith('A/A') else ab)['example']
    st.dataframe([{'Example index':example['experiment_index'],'Control conversion':pct(example['control_rate']),
        'Treatment conversion':pct(example['treatment_rate']),'Difference (pp)':f"{example['difference_pp']:+.3f}",
        'Two-sided p-value':f"{example['p_value_two_sided']:.4f}",
        '95% difference interval (pp)':str([round(v,3) for v in example['difference_ci_pp']])}],hide_index=True,width='stretch')
    with st.expander('Methods: formulas, false positives, allocation and Monte Carlo variation'):
        st.write('A false positive is a significant result when the true effect is zero. Random variation means the A/A frequency need not equal exactly 5%. An A/B false negative misses an effect that exists in the simulation. A single experiment may miss a real improvement even with an 80% power design.')
        st.write('Balanced planning calls the unchanged Phase 8A formula. Unequal allocation uses its explicit pooled-null/unpooled-alternative normal-approximation generalization, tested separately in Phase 11. It does not alter the earlier methodology or simulation results.')
        st.latex(r'n_C=\left(\frac{z_{1-\alpha/2}\sqrt{\bar p(1-\bar p)(1+1/r)}+z_{\mathrm{power}}\sqrt{p_C(1-p_C)+p_T(1-p_T)/r}}{p_T-p_C}\right)^2')
        st.write('Here r=nT/nC and p̄=(pC+r·pT)/(1+r); round each planned arm upward. The approximation is not exact binomial power or a guarantee for clustered, sequential or nonindependent experiments.')
        srm=planning['synthetic_example']['srm']
        st.write(f"The fixed Phase 8A synthetic assignment had SRM p={srm['p_value']:.4f}. SRM asks whether counts are implausible under the planned allocation; ordinary count differences alone do not invalidate randomization.")
        st.write(f"Saved interval coverage: A/A {pct(aa['interval_coverage']['empirical_rate'],1)}, A/B {pct(ab['interval_coverage']['empirical_rate'],1)}. These are Monte Carlo diagnostics, not campaign results.")
    source('planning','aa','ab')


def reward_economics():
    config=data('reward_config')
    header('Reward Economics Simulator','Explore whether assumed extra purchase contribution covers all reward and contact costs.','HYPOTHETICAL · EXPECTED VALUES')
    st.info('Every input here is hypothetical. Changing a reward does not establish a conversion effect. Fractional expected purchasers are mathematical expectations, not observed people.')
    a,b,c=st.columns(3)
    n=a.number_input('Customers contacted',min_value=0,max_value=10000000,value=1000,step=100,key='reward_n')
    p0=b.number_input('Baseline conversion (%)',min_value=0.,max_value=100.,value=20.,step=.5,key='reward_p0')
    p1=c.number_input('Assumed treatment conversion (%)',min_value=0.,max_value=100.,value=23.,step=.5,key='reward_p1')
    a,b,c,d=st.columns(4)
    contribution=a.number_input('Contribution / purchase (€)',min_value=0.,value=20.,step=1.,key='reward_contribution')
    reward=b.number_input('Reward / redemption (€)',min_value=0.,value=5.,step=.5,key='reward_value')
    redemption=c.number_input('Redemption among purchasers (%)',min_value=0.,max_value=100.,value=100.,step=5.,key='reward_redemption')
    contact=d.number_input('Cost / contact (€)',min_value=0.,value=0.,step=.05,format='%.2f',key='reward_contact')
    scenario=scenario_from_inputs(n,p0,p1,contribution,reward,redemption,contact)
    result=result_payload(scenario);values=result['expected_values'];be=result['break_even']
    economics,comparison,sens=st.tabs(['Campaign economics','Compare scenarios','Sensitivity'])
    with economics:
        cols=st.columns(4)
        cols[0].metric('Expected incremental purchasers',f"{float(values['expected_incremental_purchasers']):,.2f}")
        cols[1].metric('Extra purchase contribution',money(values['expected_incremental_purchase_contribution_eur']))
        cols[2].metric('Reward expenditure',money(values['total_reward_expenditure_eur']))
        cols[3].metric('Net incremental contribution',money(values['net_incremental_contribution_eur']))
        net=Decimal(values['net_incremental_contribution_eur'])
        status='No contacts' if n==0 else 'Positive net contribution' if net>0 else 'Negative net contribution' if net<0 else 'Break-even'
        st.write(f'**Status: {status} under these assumptions.** Contact expenditure: **{money(values["total_contact_expenditure_eur"])}**.')
        threshold=be['required_treatment_probability']
        if be['status']=='attainable' and threshold:
            st.metric('Break-even treatment conversion',pct(float(threshold['decimal_approximation'])))
        else:st.write('**Break-even:** '+be['explanation'])
        chart(bars(['Extra purchase contribution','Reward cost','Contact cost','Net'],
            [float(values[k]) for k in ('expected_incremental_purchase_contribution_eur','total_reward_expenditure_eur','total_contact_expenditure_eur','net_incremental_contribution_eur')],
            'Expected EUR',colors=[TEAL,SLATE,NAVY,TEAL if net>=0 else RED]),'reward_bridge','Hypothetical contribution and costs, calculated by the verified Phase 9A engine.')
        decision('Reward costs apply to all expected redemptions, including purchases that might have happened without the offer. A positive conversion assumption can still produce negative net contribution.')
        st.download_button('Download hypothetical calculation (JSON)',json.dumps(result,indent=2),file_name='hypothetical_reward_economics.json',mime='application/json',key='reward_download')
    with comparison:
        ids=[s['scenario_id'] for s in config['scenarios']]
        selected=st.multiselect('Compare current assumptions with saved hypothetical scenarios',ids,default=ids,key='reward_comparisons',format_func=lambda s:s.replace('_',' ').title())
        result_comparison=compare_with_saved(scenario,config,selected)
        if not result_comparison['comparable_by_declared_criteria']:
            st.warning('No ranking: these scenarios differ in '+', '.join(result_comparison['ranking_blocked_reasons'])+'. Totals remain available, but the contexts are not directly comparable.')
        rows=[]
        ranks={r['scenario_id']:r['rank'] for r in result_comparison['ranking'] or []}
        for row in result_comparison['scenarios']:
            x=row['engine_result'];ev=x['expected_values'];inp=x['inputs']
            rows.append({'Scenario':row['scenario_id'].replace('_',' ').title(),'Contacted':inp['contacted_customers'],
                'Assumed conversion':pct(float(inp['treatment_conversion'])),'Reward':money(inp['reward_per_redemption_eur']),
                'Net contribution':money(ev['net_incremental_contribution_eur']),'Conditional rank':ranks.get(row['scenario_id'],'Not comparable')})
        st.dataframe(rows,hide_index=True,width='stretch')
        st.caption('Ranks, when permitted, use expected net contribution only. Same population, horizon, baseline and purchase contribution are required. This is not an empirical optimal reward.')
    with sens:
        labels={'treatment_conversion':'Assumed treatment conversion','reward_per_redemption_eur':'Reward per redemption',
            'redemption_probability':'Redemption among purchasers','contribution_per_purchase_eur':'Contribution per purchase','contact_cost_per_customer_eur':'Contact cost'}
        field=st.selectbox('Vary one assumption',list(labels),format_func=labels.get,key='sensitivity_field')
        probability=field in ('treatment_conversion','redemption_probability')
        center=float(getattr(scenario,field));default_high=1. if probability else max(center*2,10. if field!='contact_cost_per_customer_eur' else .5)
        a,b,c=st.columns(3)
        low=a.number_input('Lower bound'+(' (%)' if probability else ' (€)'),min_value=0.,max_value=100. if probability else None,value=0.,key='sensitivity_low_'+field)
        high=b.number_input('Upper bound'+(' (%)' if probability else ' (€)'),min_value=0.,max_value=100. if probability else None,value=default_high*(100 if probability else 1),key='sensitivity_high_'+field)
        count=c.slider('Grid points',3,21,9,key='sensitivity_count')
        try:
            grid=sensitivity_points(scenario,field,str(Decimal(str(low))/100) if probability else low,str(Decimal(str(high))/100) if probability else high,count)
            xs=[float(p['assumed_value'])*(100 if probability else 1) for p in grid['points']]
            ys=[float(p['evaluation']['engine_result']['expected_values']['net_incremental_contribution_eur']) for p in grid['points']]
            fig=go.Figure(go.Scatter(x=xs,y=ys,mode='lines+markers',line_color=TEAL,marker_size=7))
            fig.add_hline(y=0,line_dash='dot',line_color=SLATE)
            fig=style_figure(fig,'Expected net contribution (€)');fig.update_layout(xaxis_title=labels[field]+(' (%)' if probability else ' (€)'))
            chart(fig,'reward_sensitivity','Deterministic hypothetical sensitivity, holding all other inputs fixed.')
        except ValueError as error:st.error(str(error))
        st.caption('One input changes at a time. Conversion stays fixed when reward changes. This is an expected-value calculation, not a measured response curve, optimization or statistical confidence interval.')
    with st.expander('Financial formulas and scope'):
        st.write('With N contacts, p0 baseline, p1 assumed response, M contribution, R reward, D redemption and K contact cost: net = N(p1−p0)M − Np1DR − NK. At most one purchase is rewarded per customer. The engine handles unattainable and degenerate break-even cases explicitly.')
        st.write('No repeat purchases, verified margins, actual incentive effect, fixed campaign costs, returns or lifetime value are inferred. Display amounts are rounded for readability; the download retains exact decimal outputs.')
    source('reward_reference','reward_config','reward_summary')


def product_ranking():
    d=data('ranking');protocol=data('ranking_protocol')
    header('Product Ranking Intelligence','Order the same shortlist more effectively, and see what retrieval still misses.','REES46 · FINAL TEMPORAL HOLDOUT')
    k=st.select_slider('Show top K products',options=[5,10,20],value=10,key='ranking_k')
    aggregation=st.radio('Recall averaging',['Per customer (macro)','Per purchased pair (micro)'],horizontal=True,key='ranking_aggregation')
    field='recall_macro' if aggregation.startswith('Per customer') else 'recall_micro'
    ceiling=d['candidate_recall_macro' if field=='recall_macro' else 'candidate_recall_micro']
    ml=d['methods']['ml'][str(k)];diff=ranking_difference(d,k)
    cols=st.columns(4)
    cols[0].metric(f'ML Recall@{k}',pct(ml[field]))
    cols[1].metric(f'ML NDCG@{k}',f"{ml['ndcg_macro']:.5f}")
    cols[2].metric(('Macro' if field=='recall_macro' else 'Micro')+' candidate recall ceiling',pct(ceiling))
    cols[2].caption('Mean fraction recovered per future-purchasing customer.' if field=='recall_macro' else 'Recovered future purchased pairs / all future purchased pairs.')
    cols[3].metric('Future purchased pairs missing',pct(d['errors']['absent_from_candidates']/d['relevant_pairs']))
    cols[3].caption('Micro: purchased-pair weighted, not a customer average.')
    records=ranking_rows(d,k);a,b=st.columns(2)
    with a:chart(bars([r['Method'] for r in records],[r[field] for r in records],f'Recall@{k} (%)',100),'ranking_recall','Three frozen methods on identical candidates; selected recall averaging.')
    with b:chart(bars([r['Method'] for r in records],[r['ndcg_macro'] for r in records],f'Mean-customer NDCG@{k}',digits=5),'ranking_ndcg','Three frozen methods, binary NDCG with the full relevance denominator.')
    st.subheader('Paired ML-minus-recency comparison')
    cols=st.columns(2)
    for col,name,scale,unit in [(cols[0],'Recall',100,'pp'),(cols[1],'NDCG',1,'')]:
        x=diff[name];col.metric(f'Macro {name}@{k} difference',f"{x['estimate']*scale:+.{'3' if name=='Recall' else '5'}f} {unit}")
        col.caption(f"95% paired interval: [{x['lower']*scale:+.5f}, {x['upper']*scale:+.5f}] {unit}")
    st.caption('Paired differences always use purchaser-level macro metrics, including when the recall chart is switched to micro averaging.')
    decision('The ML reranker is the preferred offline model: both frozen primary final-test comparisons at K=10 favor ML. This does not establish increased real-world sales.')
    st.dataframe([{'Method':r['Method'],'Macro recall':pct(r['recall_macro']),'Micro recall':pct(r['recall_micro']),
        'NDCG':f"{r['ndcg_macro']:.5f}",'Purchased-pair hits':r['hits']} for r in records],hide_index=True,width='stretch')
    st.subheader('A shortlist sets the ceiling')
    steps=st.columns(3)
    for col,title,body in zip(steps,['01 · Retrieve','02 · Order','03 · Evaluate'],[
        'Use past personal history and popularity backfill to retrieve 100 unique products.',
        'Sort those same 100 products using popularity, recency or the fixed ML model.',
        'Compare the top K with observed purchases in the next fourteen days.']):
        with col,st.container(border=True):st.subheader(title);st.write(body)
    st.write(f"{d['errors']['absent_from_candidates']:,} of {d['relevant_pairs']:,} future purchased pairs never entered the candidates. A better reranker cannot recover them. All {d['eligible_users']:,} eligible customers received lists, but list availability is not relevance.")
    with st.expander('Metrics, features and temporal methodology'):
        st.write(f"Recall/NDCG averages include {d['purchasing_users']:,} purchasing customers. Micro recall uses {d['relevant_pairs']:,} purchased pairs. Customers with no future purchase remain in coverage, not undefined purchase-recall means.")
        st.write('Recall@K is the fraction of future purchased products present near the top. NDCG additionally rewards placing them earlier. If A and B are purchased but only A is in the shortlist, even perfect ordering cannot recover B.')
        st.write(f"History: {protocol['history_start']} to {protocol['prediction_time']} UTC. Outcome end: {protocol['outcome_end']} UTC; end-exclusive. Candidate budget 100; no final-driven refit, feature or threshold changes.")
        st.write('Seven fixed model features: '+', '.join(protocol['features']))
        st.write('The 2,000-draw paired purchaser bootstrap holds model/retrieval fixed. Intervals exclude training-refit, temporal and shared-product uncertainty; secondary endpoints have no simultaneous correction. No impressions, stock availability or customer ratings are invented.')
    source('ranking','ranking_protocol')


def methodology():
    header('Methodology & limitations','A transparent chain from independent datasets to frozen evidence and hypothetical planning.','PROVENANCE · REPRODUCIBILITY')
    with st.container(key='methodology_summary'):
        st.table([
        {'Study':'REES46 purchase prediction','Unit':'Observed customer ID','Question':'Any purchase after 7 history days, within 30 future days','Evidence':'Observed temporal prediction'},
        {'Study':'RetailHero SMS','Unit':'Experimental customer','Question':'Group differences and targeting policy value','Evidence':'Assumption-dependent intervention estimates'},
        {'Study':'Experiment Lab','Unit':'Synthetic customer / experiment','Question':'Planning, false positives and detection power','Evidence':'Hypothetical planning and saved simulations'},
        {'Study':'Reward Economics','Unit':'Hypothetical campaign','Question':'Expected incremental contribution after costs','Evidence':'Deterministic assumptions, not measured effects'},
        {'Study':'REES46 product ranking','Unit':'Customer-time-product candidate','Question':'Order past-only candidates for future purchases','Evidence':'Frozen temporal offline ranking'}],hide_index=True,width='stretch')
        st.caption('On narrow screens, scroll the table horizontally to read every column.')
    st.subheader('Independent populations, different meanings')
    st.write('REES46 cosmetics browsing/purchasing events and RetailHero customer experimentation are separate datasets. Their customers are never joined. Predictive lift is not causal uplift, and neither establishes the assumed response of a hypothetical reward.')
    st.markdown('[REES46 source](https://www.kaggle.com/datasets/mkechinov/ecommerce-events-history-in-cosmetics-shop) · [REES46 catalog](https://rees46.com/en/datasets) · [RetailHero source](https://ods.ai/competitions/x5-retailhero-uplift-modeling/data)')
    sections={
        'Chronology, model selection and leakage':'Purchase and ranking models were selected on validation before final evaluation. Features use only past events. Labels mature before later snapshots. Product popularity is updated only from the appropriate past month. Final outcomes never choose candidates, weights, K or models.',
        'Causal identification':'RetailHero assignment/compliance and exact horizon were not independently verified. Policy estimates assume a constant treatment propensity. A group difference alone does not validate customer-level targeting or identify an individual causal benefit.',
        'Implicit feedback and retrieval':'REES46 has interaction events, not verified impression logs or ratings. Unpurchased products are not dislikes. Missing inventory/exposure and an incomplete shortlist limit offline ranking. Purchase events are not verified order counts.',
        'Simulation versus observation':'A/A and A/B outcomes are synthetic under specified probabilities. Changing planning inputs does not rerun those studies or prove a €5 voucher works. Reward economics is an expected-value what-if calculation, not empirical incentive optimization.',
        'Public app and reproducibility':'The app reads only allowlisted committed aggregate JSON with fingerprints. It does not import evaluation/training entry points, load models, query raw data or require customer-level predictions. Frozen research outputs stay unchanged. Local artifact-dependent research verification is separate from this public interface.'}
    for title,text in sections.items():
        with st.expander(title):st.write(text)
    st.subheader('Read the original methodology')
    reports=[('Purchase prediction','docs/phase4_final_evaluation.md'),('RetailHero experiment','docs/causal/phase5_experiment_analysis.md'),
        ('Final uplift evaluation','docs/causal/phase7_final_evaluation.md'),('Experiment design','docs/experiments/phase8a_design.md'),
        ('A/A testing','docs/experiments/phase8b_aa_testing.md'),('A/B testing','docs/experiments/phase8c_ab_testing.md'),
        ('Reward economics','docs/rewards/phase9a_economics.md'),('Scenario comparison','docs/rewards/phase9b_scenarios.md'),
        ('Final product ranking','docs/ranking/phase10c_final_evaluation.md')]
    for name,path in reports:st.markdown(f'[{name}]({REPO}/blob/main/{path})')
    st.link_button('GrowthLab on GitHub',REPO)
    st.caption('The UI-to-evidence mapping and dependency pins are documented in docs/decision_studio/. No cloud deployment is part of this release.')


RENDERERS=dict(zip(PAGES,(overview,purchase_intelligence,retailhero,experiment_lab,reward_economics,product_ranking,methodology)))
