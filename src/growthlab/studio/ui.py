"""Reusable, accessible presentation components; static CSS, aggregate charts."""
from pathlib import Path
import html

import plotly.graph_objects as go
import streamlit as st

from .evidence import ROOT,load_evidence,source_path

TEAL='#087F78'
NAVY='#254B68'
SLATE='#7D91A5'
RED='#B44840'
COLORS=[SLATE,NAVY,TEAL,'#AC762C']
REPO='https://github.com/sanjeevani1193/GrowthLab'


@st.cache_data(show_spinner=False)
def _cached(name,root,stamp):return load_evidence(name,Path(root))


def data(name):
    path=ROOT/source_path(name)
    stamp=(path.stat().st_mtime_ns,path.stat().st_size) if path.exists() else None
    return _cached(name,str(ROOT),stamp)


def theme():
    st.markdown('''<style>
    .stApp {background:#F4F7FA;}
    .block-container {max-width:1420px;padding-top:2.4rem;padding-bottom:3rem;}
    h1,h2,h3 {letter-spacing:-.035em;color:#142C3B;}
    h1 {font-size:2.65rem!important;font-weight:750!important;}
    h2 {font-size:1.65rem!important;}
    h3 {font-size:1.13rem!important;letter-spacing:-.02em;}
    [data-testid="stSidebar"] {background:#112A3A;}
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
    [data-testid="stSidebar"] label,[data-testid="stSidebar"] p {color:#E5EFF4;}
    [data-testid="stSidebar"] hr {border-color:#355163;}
    [data-testid="stSidebar"] [data-testid="stLinkButton"] a,
    [data-testid="stSidebar"] [data-testid="stLinkButton"] p {color:#142C3B!important;}
    [data-testid="stSidebar"] [data-testid="stRadio"] label {padding:.5rem .35rem;border-radius:6px;}
    [data-testid="stSidebar"] [data-testid="stRadio"] label:hover {background:#203E50;}
    [data-testid="stMetric"] {background:white;border-radius:12px;padding:1.05rem 1.1rem;border:1px solid #DFE7ED;}
    [data-testid="stMetricValue"] {font-size:1.85rem;font-weight:700;color:#142C3B;}
    [data-testid="stMetricLabel"] {font-size:.84rem;color:#506879;}
    [data-testid="stVerticalBlockBorderWrapper"] {border-radius:12px;}
    .st-key-methodology_summary [data-testid="stTable"] {overflow-x:auto;}
    .st-key-methodology_summary table {table-layout:fixed;width:100%;min-width:680px;}
    .st-key-methodology_summary th,.st-key-methodology_summary td {white-space:normal;overflow-wrap:anywhere;vertical-align:top;}
    .eyebrow {font-size:.73rem;font-weight:750;letter-spacing:.16em;text-transform:uppercase;color:#087F78;margin-bottom:.7rem;}
    .hero {padding:2rem 2.2rem;border:1px solid #D8E8E8;border-radius:18px;background:linear-gradient(115deg,#E7F4F0 0%,#FFF 80%);margin-bottom:1.3rem;}
    .hero h1 {margin:0 0 .6rem!important;line-height:1.13;max-width:850px;}
    .hero p {max-width:760px;color:#415E6E;font-size:1.02rem;line-height:1.6;}
    .pill {display:inline-block;font-size:.72rem;font-weight:650;letter-spacing:.03em;color:#215A55;background:#DCEFE9;border:1px solid #B7D9CF;border-radius:30px;padding:.27rem .65rem;margin-bottom:.7rem;}
    .decision {padding:1.1rem 1.4rem;border-left:4px solid #087F78;border-radius:0 10px 10px 0;background:#E6F3EF;color:#163D38;line-height:1.6;margin:.6rem 0 1.2rem;}
    .brand {font-size:1.48rem;font-weight:800;letter-spacing:.08em;color:white;}
    .brand-sub {font-size:.72rem;letter-spacing:.16em;color:#ACC6D4;margin-bottom:1.8rem;}
    [data-testid="stCaptionContainer"],
    [data-testid="stCaptionContainer"] p {color:#536B7A;opacity:1;}
    [data-testid="stCaptionContainer"] a {color:#086C68;}
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {color:#ACC6D4;}
    @media(max-width:640px) {
      .block-container {padding:4.5rem .9rem 2rem;}
      h1 {font-size:1.9rem!important;}
      .hero {padding:1.2rem;}
      [data-testid="stHorizontalBlock"] {flex-wrap:wrap;}
      [data-testid="stColumn"] {min-width:min(100%,260px)!important;flex:1 1 260px!important;}
    }
    </style>''',unsafe_allow_html=True)


def header(title,subtitle,badge='VERIFIED RESEARCH'):
    st.markdown(f'<div class="pill">{html.escape(badge)}</div>',unsafe_allow_html=True)
    st.title(title);st.write(subtitle)


def decision(text):st.markdown(f'<div class="decision">{html.escape(text)}</div>',unsafe_allow_html=True)


def source(*names):
    links=[f'[{source_path(n)}]({REPO}/blob/main/{source_path(n)})' for n in names]
    st.caption('Evidence: '+' · '.join(links))


def style_figure(fig,ytitle='',height=350):
    fig.update_layout(template='plotly_white',height=height,font={'family':'Arial, sans-serif','size':13,'color':'#294658'},
        paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',margin={'l':16,'r':20,'t':28,'b':35},
        yaxis_title=ytitle,legend={'orientation':'h','y':1.12,'x':0},hoverlabel={'font_size':13})
    fig.update_xaxes(showgrid=False,automargin=True)
    fig.update_yaxes(gridcolor='#E0E8EE',zerolinecolor='#90A5B4',automargin=True)
    return fig


def bars(labels,values,ytitle,scale=1,colors=None,digits=2):
    fig=go.Figure(go.Bar(x=labels,y=[v*scale for v in values],marker_color=colors or COLORS[:len(labels)],
        text=[f'{v*scale:.{digits}f}' for v in values],textposition='outside',cliponaxis=False,
        hovertemplate='%{x}<br>%{y:.4f}<extra></extra>'))
    fig.update_yaxes(rangemode='tozero')
    return style_figure(fig,ytitle)


def intervals(labels,estimates,lower,upper,title,scale=1):
    fig=go.Figure(go.Scatter(x=[v*scale for v in estimates],y=labels,mode='markers',
        marker={'color':TEAL,'size':11},error_x={'type':'data','symmetric':False,
            'array':[(h-e)*scale for h,e in zip(upper,estimates)],
            'arrayminus':[(e-l)*scale for e,l in zip(estimates,lower)],'color':NAVY,'thickness':1.6},
        hovertemplate='%{y}<br>Estimate: %{x:.3f}<extra></extra>'))
    fig.add_vline(x=0,line_dash='dot',line_color=SLATE)
    fig=style_figure(fig,height=330);fig.update_layout(xaxis_title=title)
    return fig


def chart(fig,key,description):
    st.plotly_chart(fig,width='stretch',theme=None,key=key,alt=description,
        config={'displayModeBar':False,'responsive':True})


def pct(value,digits=2):return f'{value*100:.{digits}f}%'


def money(value):
    amount=f'{float(value):,.2f}'
    return '-€'+amount[1:] if amount.startswith('-') else '€'+amount
