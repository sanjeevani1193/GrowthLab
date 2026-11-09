"""Streamlit entry orchestration; only aggregate evidence and pure calculators."""
import streamlit as st

from .evidence import EvidenceError
from .ui import theme,REPO
from .pages import PAGES,RENDERERS


def main():
    st.set_page_config(page_title='GrowthLab Decision Studio',page_icon='◈',layout='wide',initial_sidebar_state='auto')
    theme()
    with st.sidebar:
        st.markdown('<div class="brand">◈ GROWTHLAB</div><div class="brand-sub">DECISION STUDIO</div>',unsafe_allow_html=True)
        page=st.radio('Workspace',PAGES,key='studio_page',label_visibility='collapsed')
        st.divider()
        st.caption('EVIDENCE, NOT ASSUMPTION')
        st.write('Frozen research findings. Explicit uncertainty. Transparent planning.')
        st.caption('REES46 and RetailHero are independent studies. Reward and voucher simulations are hypothetical.')
        st.link_button('Source & research',REPO,width='stretch')
    try:
        RENDERERS[page]()
    except EvidenceError as error:
        st.error(str(error))
        st.info('This workspace needs its committed aggregate evidence. Restore the named file from the repository. Other workspaces remain available; raw data or model retraining is not required.')
    st.divider();st.caption('GROWTHLAB DECISION STUDIO · Offline evidence and hypothetical planning · No customer-level records exposed')
