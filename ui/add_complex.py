"""관심 단지 추가: 이름 검색 또는 시/도 > 시군구 > 동 선택."""
import streamlit as st

from collectors import naver_complex
from collectors.naver_client import Blocked, NaverClient
from ui import collect, data


def _client() -> NaverClient:
    # 화면 조작용: 사람이 누르는 속도라 대기를 짧게 둔다
    return NaverClient(delay=(0.5, 1.0))


@st.cache_data(ttl=86400, show_spinner=False)
def _regions(level: int, parent: str | None) -> list[tuple[str, str]]:
    with _client() as c:
        rows = naver_complex.load_regions(c, level, parent)
    name = {1: lambda r: r.sido, 2: lambda r: r.sigungu, 3: lambda r: r.dong}[level]
    return [(r.code, name(r)) for r in rows]


@st.cache_data(ttl=86400, show_spinner=False)
def _dong_complexes(code: str) -> list[dict]:
    with _client() as c:
        return naver_complex.dong_complexes(c, code)


@st.cache_data(ttl=3600, show_spinner=False)
def _search(keyword: str) -> list[dict]:
    with _client() as c:
        return naver_complex.search(c, keyword)


def _add(ids: list[int], collect_now: bool):
    watched = set(data.watched_complexes()["complex_id"])
    ids = [i for i in ids if i not in watched]
    if not ids:
        st.info("이미 관심 단지에 있습니다.")
        return
    added = []
    try:
        with st.spinner(f"{len(ids)}개 단지를 등록하는 중..."), _client() as c:
            for cid in ids:
                added.append(naver_complex.add_to_watchlist(cid, client=c))
    except Blocked as e:
        st.error(f"네이버가 요청을 막았습니다. 잠시 후 다시 시도하세요. ({e})")
    data.clear_all()
    if not added:
        return
    names = ", ".join(cx.name for cx in added)
    st.session_state["add_msg"] = f"등록: {names}"
    if collect_now:
        # 단지 정보는 방금 받았으니 실거래·매물만 백그라운드로 수집
        if not collect.start(["--complex", ",".join(str(cx.complex_id) for cx in added),
                              "--only", "trade,listing"], names):
            st.session_state["add_msg"] += " — 다른 수집이 끝나면 단지 블록의 '수집' 단추를 누르세요."
    st.rerun()


def render():
    with st.expander("➕ 관심 단지 등록", expanded=data.watched_complexes().empty):
        if msg := st.session_state.pop("add_msg", None):
            st.success(msg)
        collect_now = st.checkbox("등록 후 바로 수집 (실거래·매물, 백그라운드)", value=True,
                                  help="새 시군구면 국토부 10년치 첫 적재가 함께 진행되어 몇 분 걸릴 수 있습니다.")
        t1, t2 = st.tabs(["이름 검색", "지역에서 선택"])
        with t1:
            c1, c2 = st.columns([3, 1])
            kw = c1.text_input("단지명", placeholder="예: 래미안대치팰리스", label_visibility="collapsed")
            if kw.strip():
                try:
                    res = [r for r in _search(kw.strip()) if r["type"] in naver_complex.APT_TYPES]
                except Blocked as e:
                    st.error(f"네이버 차단 응답: {e}")
                    res = []
                if res:
                    pick = st.selectbox("검색 결과", res, format_func=lambda r: f"{r['name']} · {r['address']}")
                    if c2.button("등록", key="add_search", type="primary"):
                        _add([pick["complex_id"]], collect_now)
                else:
                    st.caption("검색 결과가 없습니다.")
        with t2:
            try:
                c1, c2, c3 = st.columns(3)
                sidos = _regions(1, None)
                sido = c1.selectbox("시/도 ", sidos, format_func=lambda x: x[1], index=None, key="add_sido")
                sggs = _regions(2, sido[0]) if sido else []
                sgg = c2.selectbox("시군구 ", sggs, format_func=lambda x: x[1], index=None, key="add_sgg")
                dongs = _regions(3, sgg[0]) if sgg else []
                dong = c3.selectbox("동 ", dongs, format_func=lambda x: x[1], index=None, key="add_dong")
                if dong:
                    cands = _dong_complexes(dong[0])
                    picks = st.multiselect(
                        f"{dong[1]} 아파트 ({len(cands)}개, 세대수 순)", cands,
                        format_func=lambda r: f"{r['name']} · {r['households'] or '-'}세대"
                                              + (f" · {r['approval_date'][:4]}년" if r.get("approval_date") else ""))
                    if st.button("선택한 단지 등록", disabled=not picks, type="primary"):
                        _add([p["complex_id"] for p in picks], collect_now)
            except Blocked as e:
                st.error(f"네이버 차단 응답: {e}")
