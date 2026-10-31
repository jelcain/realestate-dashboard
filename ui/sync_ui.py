"""대시보드의 MYBOX 동기화 (클라우드 분담 모드에서만 동작)."""
from datetime import datetime
import logging
import threading

import streamlit as st

from settings import cloud_mode, web_mode
from ui import data

log = logging.getLogger(__name__)
_push_lock = threading.Lock()


def push_pc_background():
    """관심 단지·매핑을 바꾼 뒤 pc.db 를 올린다 (화면을 막지 않게 백그라운드). 웹 보기 전용에선 절대 올리지 않는다"""
    if not cloud_mode() or web_mode():
        return

    def job():
        from storage import sync
        with _push_lock:
            try:
                sync.push("pc")
            except Exception as e:  # noqa: BLE001 - 다음 수집 때 다시 올라간다
                log.warning("pc.db 업로드 실패: %s", e)

    threading.Thread(target=job, daemon=True).start()


def _has_watchlist() -> bool:
    from sqlalchemy import func, select
    from db.models import Session, Watchlist
    with Session() as s:
        return bool(s.scalar(select(func.count()).select_from(Watchlist)))


@st.cache_data(ttl=600, show_spinner="클라우드 자료(MYBOX) 확인 중...")
def _pull() -> dict:
    from storage import sync
    out = {"checked": datetime.now().strftime("%m/%d %H:%M"), "changed": False, "error": None}
    try:
        if web_mode():
            out["changed"] |= sync.pull("pc")  # 웹: 매물·관심 단지도 PC 가 올린 최신본을 받는다
        elif not _has_watchlist() and sync.remote_info("pc"):
            sync.pull("pc", force=True)  # 새 PC 에서 처음 열 때: 관심 단지 목록부터 받는다
            out["changed"] = True
        out["changed"] |= sync.pull("cloud")
    except PermissionError:
        out["error"] = "다른 작업이 DB 를 쓰는 중이라 다음에 다시 받습니다"
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:200]
    return out


def refresh():
    """새 클라우드 자료가 있으면 받고, 받았으면 화면 캐시를 비운다. 사이드바에 상태 표시"""
    if not cloud_mode():
        return
    info = _pull()
    if info["changed"] and st.session_state.get("pulled_at") != info["checked"]:
        st.session_state["pulled_at"] = info["checked"]
        for fn in (data.watched_complexes, data.area_types, data.trades, data.news, data.news_editions,
                   data.collect_status,
                   data.last_ok, data.listings, data.unwatched):
            fn.clear()
    with st.sidebar:
        if info["error"]:
            st.caption(f"☁️ 클라우드 자료 받기 실패: {info['error']}")
        else:
            st.caption(f"☁️ 클라우드 자료 확인: {info['checked']}")
        if st.button("최신 자료 지금 받기" if web_mode() else "클라우드 자료 지금 받기", key="pull_now"):
            _pull.clear()
            st.rerun()
