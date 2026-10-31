"""보조 화면: 단지 매핑(수동 보정), 수집 현황."""
import pandas as pd
import streamlit as st

from collectors import molit_trade
from processing.mapping import set_manual
import run_daily
from settings import cloud_mode, config
from ui import collect, data, sync_ui
from ui.data import _q

AUTO, NONE = "(자동 매핑)", "해당 없음"


def mapping_page():
    st.header("단지 매핑")
    st.caption("국토부 실거래 단지명 ↔ 네이버 단지 연결. 관심 단지가 있는 동의 국토부 단지만 표시합니다. "
               "자동 매핑이 틀렸거나 비어 있으면 '연결 단지'를 고른 뒤 저장하세요.")
    cx = data.watched_complexes()
    if cx.empty:
        st.info("관심 단지가 없습니다.")
        return
    rows = _q("""
        SELECT m.apt_key, m.umd_nm, m.jibun, m.apt_nm, m.complex_id AS auto_id, m.score, ca.name AS auto_name,
               mm.complex_id AS manual_id,
               (SELECT COUNT(*) FROM trade t WHERE t.apt_key = m.apt_key) AS n
        FROM apt_mapping m
        LEFT JOIN manual_mapping mm ON mm.apt_key = m.apt_key
        LEFT JOIN complex ca ON ca.complex_id = m.complex_id
        WHERE m.sgg_cd || '|' || m.umd_nm IN (
            SELECT substr(legal_code,1,5) || '|' || dong FROM complex WHERE complex_id IN (SELECT complex_id FROM watchlist))
        ORDER BY m.umd_nm, (COALESCE(mm.complex_id, m.complex_id) IS NULL), m.apt_nm""")
    if rows.empty:
        st.info("아직 실거래 자료가 없습니다. 수집 후 다시 확인하세요.")
        return
    only_mapped = st.toggle("연결된 단지만 보기", value=True)
    if only_mapped:
        rows = rows[rows["manual_id"].notna() | rows["auto_id"].notna()]
    names = {int(r.complex_id): f"{r['name']} ({r.dong})" for _, r in cx.iterrows()}
    choices = [AUTO, NONE] + list(names.values())

    def current(r):
        if pd.isna(r["manual_id"]):
            return AUTO
        return NONE if r["manual_id"] == -1 else names.get(int(r["manual_id"]), AUTO)

    view = pd.DataFrame({
        "apt_key": rows["apt_key"], "동": rows["umd_nm"], "지번": rows["jibun"], "국토부 단지명": rows["apt_nm"],
        "거래 수": rows["n"],
        "자동 결과": rows.apply(lambda r: f"{r['auto_name']} ({r['score']:.2f})" if isinstance(r["auto_name"], str)
                            else "-", axis=1),
        "연결 단지": rows.apply(current, axis=1),
    })
    edited = st.data_editor(view, hide_index=True, width="stretch", disabled=[c for c in view if c != "연결 단지"],
                            column_config={"apt_key": None,
                                           "연결 단지": st.column_config.SelectboxColumn(options=choices, required=True)})
    if st.button("저장", type="primary"):
        inv = {v: k for k, v in names.items()}
        changed = edited[edited["연결 단지"] != view["연결 단지"]]
        for _, r in changed.iterrows():
            v = r["연결 단지"]
            set_manual(r["apt_key"], None if v == AUTO else (-1 if v == NONE else inv[v]))
        data.clear_all()
        if len(changed):
            sync_ui.push_pc_background()
        st.success(f"{len(changed)}건 저장")
        st.rerun()


def status_page():
    st.header("수집 현황")
    if cloud_mode():
        st.info("☁️ 클라우드 분담 모드: 실거래·뉴스는 GitHub 이 매일 05:00 에 수집하고, "
                "단지 정보·매물은 이 PC 가 수집합니다. 자료는 MYBOX 에 보관됩니다.")
        cloud_runs()
    st.subheader("최근 실행")
    logs = _q("""SELECT substr(run_at, 1, 16) AS 실행시각, 'PC' AS 위치, collector AS 수집기, status AS 결과,
                        count AS 건수, COALESCE(error, '') AS 오류 FROM collect_log
                 UNION ALL
                 SELECT substr(run_at, 1, 16), '클라우드', collector, status, count, COALESCE(error, '') FROM cloud_log
                 ORDER BY 1 DESC LIMIT 50""")
    st.dataframe(logs, hide_index=True, width="stretch")
    st.subheader("국토부 실거래 적재 진행")
    prog = _q("""SELECT sgg_cd AS 시군구코드, api AS API, COUNT(*) AS 받은개월, MIN(deal_ym) AS 시작월,
                        MAX(deal_ym) AS 마지막월, SUM(rows) AS 건수
                 FROM molit_progress GROUP BY sgg_cd, api ORDER BY sgg_cd, api""")
    st.dataframe(prog, hide_index=True, width="stretch")
    sggs = molit_trade.target_sggs()
    st.caption(f"관심 단지 시군구: {', '.join(sggs) or '-'} · 목표 {config()['molit']['history_months']}개월")
    if st.button("실거래 지금 수집 (빠진 달 이어 받기)", disabled=run_daily.running() is not None):
        collect.start(["--only", "trade"], "실거래")
    collect.status()


def cloud_runs():
    from storage import cloud_run
    st.subheader("클라우드 수집 (GitHub Actions)")
    try:
        runs = cloud_run.recent_runs()
    except Exception as e:  # noqa: BLE001
        st.caption(f"실행 기록을 가져오지 못했습니다: {e}")
        return
    labels = {"completed": "끝남", "in_progress": "진행 중", "queued": "대기 중"}
    results = {"success": "✅ 성공", "failure": "❌ 실패", "cancelled": "취소", "": ""}
    st.dataframe(pd.DataFrame([{
        "시작": pd.to_datetime(r["createdAt"]).tz_convert("Asia/Seoul").strftime("%m/%d %H:%M"),
        "방식": "예약(매일)" if r["event"] == "schedule" else "수동",
        "상태": labels.get(r["status"], r["status"]),
        "결과": results.get(r.get("conclusion") or "", r.get("conclusion")),
        "링크": r["url"]} for r in runs]), hide_index=True, width="stretch",
        column_config={"링크": st.column_config.LinkColumn(display_text="열기")})
    st.caption(f"[GitHub 에서 전체 기록 보기]({cloud_run.actions_url()})")
