"""뉴스 요약 (R6): 대시보드의 접이식 패널 + 별도 '부동산 뉴스' 화면. 하루 3회(05·11·17시) 회차별로 볼 수 있다."""
from datetime import date
import json

import streamlit as st

from ui import data

WEEKDAYS = "월화수목금토일"


def _esc(s: str) -> str:
    return s.replace("~", "\\~")  # '~' 가 취소선으로 바뀌지 않게


def edition_label(ed: tuple[str, int]) -> str:
    d = date.fromisoformat(ed[0])
    return f"{d:%m/%d}({WEEKDAYS[d.weekday()]}) {ed[1]:02d}시"


def _body(key: str):
    eds = data.news_editions()
    if not eds:
        st.caption("아직 수집된 뉴스가 없습니다. 사이드바 '🔄 수동 수집'에서 '뉴스'를 수집하세요.")
        return
    ed = st.selectbox("회차", eds, index=0, key=key, format_func=edition_label)
    df = data.news(*ed)
    for _, r in df.iterrows():
        st.markdown(f"**{r['rank']}. {_esc(r['title'])}**  "
                    f"<span style='color:#898781;font-size:0.85em'>· {r['source_count']}개 언론사 · "
                    f"{r['article_count']}건</span>", unsafe_allow_html=True)
        for line in (r["summary"] or "").splitlines():
            st.markdown(f"- {_esc(line)}")
        links = json.loads(r["urls"])[:5]
        st.markdown(" · ".join(f"[{l['source'] or '원문'}]({l['url']})" for l in links))


def render():
    eds = data.news_editions()
    label = (f"📰 부동산 뉴스 — 최신 {edition_label(eds[0])}" if eds else "📰 부동산 뉴스 (아직 수집 전)")
    with st.expander(label, expanded=False):
        _body("news_ed_panel")


def page():
    st.header("📰 부동산 뉴스")
    st.caption("매일 05·11·17시에 최근 24시간 기사를 모아, 여러 언론사가 함께 다룬 이슈 순서로 최대 10건을 요약합니다. "
               "회차를 바꿔 지난 뉴스도 볼 수 있습니다.")
    _body("news_ed_page")
