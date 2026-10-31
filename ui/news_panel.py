"""일일 뉴스 요약 (R6): 대시보드의 접이식 패널 + 별도 '부동산 뉴스' 화면."""
import json

import streamlit as st

from ui import data


def _esc(s: str) -> str:
    return s.replace("~", "\\~")  # '~' 가 취소선으로 바뀌지 않게


def _body(key: str):
    df, dates = data.news()
    if not dates:
        st.caption("아직 수집된 뉴스가 없습니다. 사이드바 '🔄 수동 수집'에서 '뉴스'를 수집하세요.")
        return
    d = st.selectbox("날짜", dates, index=0, key=key)
    if d != dates[0]:
        df, _ = data.news(d)
    for _, r in df.iterrows():
        st.markdown(f"**{r['rank']}. {_esc(r['title'])}**  "
                    f"<span style='color:#898781;font-size:0.85em'>· {r['source_count']}개 언론사 · "
                    f"{r['article_count']}건</span>", unsafe_allow_html=True)
        for line in (r["summary"] or "").splitlines():
            st.markdown(f"- {_esc(line)}")
        links = json.loads(r["urls"])[:5]
        st.markdown(" · ".join(f"[{l['source'] or '원문'}]({l['url']})" for l in links))


def render():
    df, dates = data.news()
    label = f"📰 오늘의 부동산 뉴스 ({len(df)})" if dates else "📰 부동산 뉴스 (아직 수집 전)"
    with st.expander(label, expanded=False):
        _body("news_date_panel")


def page():
    st.header("📰 부동산 뉴스")
    st.caption("여러 언론사가 함께 다룬 이슈 순서로 최대 10건. 매일 뉴스 수집 때 갱신됩니다.")
    _body("news_date_page")
