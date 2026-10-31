"""Streamlit 대시보드.  실행: streamlit run app.py  →  http://localhost:8501"""
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from ui import add_complex, collect, complex_block, data, filters, news_panel, pages

st.set_page_config(page_title="부동산 대시보드", page_icon="🏢", layout="wide")


def anchor(code: str) -> str:
    return f"r{code}"


def stale_warning():
    t = data.last_ok("naver_listing")
    status = data.collect_status()
    last = status[status["collector"] == "naver_listing"]
    if t is None:
        if not data.watched_complexes().empty:
            st.warning("매물이 아직 수집되지 않았습니다.")
        return
    if pd.to_datetime(t) < datetime.now() - timedelta(days=2):
        st.warning(f"마지막 매물 수집일: {str(t)[:16]} — 2일 넘게 수집되지 않았습니다. '수집 현황'을 확인하세요.")
    elif not last.empty and last.iloc[0]["status"] in ("blocked", "error"):
        st.warning(f"최근 매물 수집이 중단됨 ({last.iloc[0]['status']}): {last.iloc[0]['error']}")


def sidebar_tree(shown: pd.DataFrame):
    st.sidebar.markdown("### 지역")
    for (sido, sgg), g in shown.groupby(["sido", "sigungu"], sort=False):
        st.sidebar.markdown(f"**{sido} › {sgg}**")
        for dong, gd in g.groupby("dong", sort=False):
            st.sidebar.markdown(f"- [{dong} ({len(gd)})](#{anchor(gd.iloc[0]['legal_code'])})")
    t = data.last_ok("naver_listing")
    st.sidebar.caption(f"마지막 매물 수집: {str(t)[:16] if t else '-'}")


def dashboard():
    st.title("관심 단지 대시보드")
    stale_warning()
    collect.sidebar()
    cx = data.watched_complexes()
    f = filters.render(cx)
    add_complex.render()
    news_panel.render()
    if cx.empty:
        st.info("관심 단지를 추가하세요.")
        return
    shown = filters.apply_region(cx, f)
    sidebar_tree(shown)
    for (sido, sgg, dong, code), g in shown.groupby(["sido", "sigungu", "dong", "legal_code"], sort=False):
        st.subheader(f"■ {sido} › {sgg} › {dong} ({len(g)}개 단지)", anchor=anchor(code), divider="gray")
        for _, row in g.iterrows():
            complex_block.render(row, f)


nav = st.navigation([st.Page(dashboard, title="대시보드", icon="📊", default=True),
                     st.Page(news_panel.page, title="부동산 뉴스", icon="📰", url_path="news"),
                     st.Page(pages.mapping_page, title="단지 매핑", icon="🔗", url_path="mapping"),
                     st.Page(pages.status_page, title="수집 현황", icon="🗂️", url_path="status")])
nav.run()
