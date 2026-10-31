"""수동 수집 단추와 진행 상태 (수집은 run_daily.py 를 백그라운드로 실행)."""
from collections import deque

import streamlit as st

import run_daily
from settings import cloud_mode
from ui import data

STEP_LABELS = {"complex": "단지 정보", "trade": "실거래 (국토부)", "listing": "매물 (네이버)", "news": "뉴스"}


def start(args: list[str], what: str) -> bool:
    if run_daily.start_background(args):
        st.session_state["collect_running"] = True
        st.toast(f"수집 시작: {what}")
        return True
    st.warning("이미 수집이 실행 중입니다. 끝난 뒤 다시 누르세요.")
    return False


def _tail(n: int = 6) -> list[str]:
    try:
        with open(run_daily.LOG, encoding="utf-8") as f:
            return [line.rstrip() for line in deque(f, n)]
    except OSError:
        return []


@st.fragment(run_every=5)
def status():
    info = run_daily.running()
    if info:
        st.session_state["collect_running"] = True
        st.info(f"⏳ 수집 중 ({info['started']} 시작)\n\n" + "  \n".join(
            f"`{line[11:19]}` {line.split(': ', 1)[-1]}" for line in _tail()))
    elif st.session_state.pop("collect_running", False):
        # 방금 끝남 → 새 데이터로 화면 전체를 다시 그린다
        data.clear_all()
        st.rerun(scope="app")


def sidebar():
    with st.sidebar:
        st.markdown("### 🔄 수동 수집")
        steps = st.multiselect("수집할 항목", list(STEP_LABELS), default=list(STEP_LABELS),
                               format_func=STEP_LABELS.get, label_visibility="collapsed")
        busy = run_daily.running() is not None
        if st.button("전체 관심 단지 지금 수집", type="primary", disabled=busy or not steps, width="stretch"):
            args = [] if len(steps) == len(STEP_LABELS) else ["--only", ",".join(steps)]
            start(args, ", ".join(STEP_LABELS[s] for s in steps))
            st.rerun()
        if cloud_mode():
            st.caption("단지 정보·매물은 이 PC 에서, 실거래·뉴스는 클라우드(GitHub)에서 수집합니다. "
                       "클라우드 결과는 몇 분 뒤 '클라우드 자료 지금 받기'로 가져옵니다.")
        else:
            st.caption("관심 단지가 많으면 매물 수집에 오래 걸립니다 (단지당 약 10~60초).")
        status()


def complex_button(complex_id: int, name: str, col):
    busy = run_daily.running() is not None
    if col.button("수집", key=f"collect_{complex_id}", disabled=busy,
                  help="이 단지의 단지 정보·실거래·매물을 지금 수집"):
        start(["--complex", str(complex_id)], name)
        st.rerun()
