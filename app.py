"""Streamlit 대시보드.  실행: streamlit run app.py  →  http://localhost:8501

웹(Streamlit Community Cloud)에서는 Secrets 의 WEB_MODE="1" 로 보기 전용 모드가 되고, APP_PASSWORD 로 잠근다.
"""
from datetime import datetime, timedelta
import hmac
import os
import time

import streamlit as st

st.set_page_config(page_title="부동산 대시보드", page_icon="🏢", layout="wide")

# Streamlit Secrets(웹) → 환경변수. DB·설정 모듈을 불러오기 전에 해야 한다
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, (str, int, float)):
            os.environ.setdefault(_k, str(_v))
except Exception:  # noqa: BLE001 - 로컬에는 secrets 파일이 없다
    pass

import pandas as pd  # noqa: E402

from settings import app_version, web_mode  # noqa: E402
from ui import add_complex, collect, complex_block, data, filters, news_panel, pages, sync_ui  # noqa: E402


def login() -> bool:
    """웹 모드 비밀번호 확인. 비밀번호가 설정되지 않았으면 아예 열지 않는다"""
    if not web_mode() or st.session_state.get("authed"):
        return True
    expected = os.getenv("APP_PASSWORD", "")
    st.title("🏢 부동산 대시보드")
    if not expected:
        st.error("APP_PASSWORD 가 설정되지 않아 열 수 없습니다. Streamlit 앱 설정의 Secrets 에 추가하세요.")
        return False
    with st.form("login"):
        pw = st.text_input("비밀번호", type="password")
        if st.form_submit_button("들어가기", type="primary"):
            if hmac.compare_digest(pw.encode(), expected.encode()):
                st.session_state["authed"] = True
                st.rerun()
            time.sleep(2)  # 비밀번호 무작위 대입을 느리게
            st.error("비밀번호가 틀렸습니다.")
    return False


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
    if web_mode():
        st.caption("🌐 웹 보기 전용 — 단지 등록·수집·관심 해제는 집 PC 의 대시보드에서 합니다.")
    else:
        collect.sidebar()
    cx = data.watched_complexes()
    f = filters.render(cx)
    if not web_mode():
        add_complex.render()
    news_panel.render()
    if cx.empty:
        st.info("관심 단지가 없습니다." if web_mode() else "관심 단지를 추가하세요.")
        return
    shown = filters.apply_region(cx, f)
    sidebar_tree(shown)
    for (sido, sgg, dong, code), g in shown.groupby(["sido", "sigungu", "dong", "legal_code"], sort=False):
        st.subheader(f"■ {sido} › {sgg} › {dong} ({len(g)}개 단지)", anchor=anchor(code), divider="gray")
        for _, row in g.iterrows():
            complex_block.render(row, f)


if login():
    sync_ui.refresh()  # 클라우드 분담 모드·웹 모드면 MYBOX 에서 새 자료를 받는다
    page_list = [st.Page(dashboard, title="대시보드", icon="📊", default=True),
                 st.Page(news_panel.page, title="부동산 뉴스", icon="📰", url_path="news")]
    if not web_mode():
        page_list.append(st.Page(pages.mapping_page, title="단지 매핑", icon="🔗", url_path="mapping"))
    page_list.append(st.Page(pages.status_page, title="수집 현황", icon="🗂️", url_path="status"))
    st.navigation(page_list).run()
    st.sidebar.caption(f"프로그램 버전: {app_version()}")
