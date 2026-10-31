"""대시보드용 DB 조회 (캐시)."""
from datetime import date, datetime, timedelta
import json

import pandas as pd
import streamlit as st
from sqlalchemy import text

from db.models import Session, Unwatched, Watchlist, engine
from processing.mapping import EFFECTIVE_SQL
from settings import config


def _q(sql: str, **params) -> pd.DataFrame:
    with engine.connect() as c:
        return pd.read_sql(text(sql), c, params=params)


@st.cache_data(ttl=300)
def watched_complexes() -> pd.DataFrame:
    return _q("""
        SELECT c.*, w.areas, w.added_at FROM watchlist w JOIN complex c ON c.complex_id = w.complex_id
        ORDER BY c.legal_code, c.name""")


@st.cache_data(ttl=300)
def area_types(complex_id: int) -> pd.DataFrame:
    return _q("SELECT * FROM area_type WHERE complex_id = :cid ORDER BY exclusive_m2", cid=complex_id)


@st.cache_data(ttl=300)
def trades(complex_id: int, years: int) -> pd.DataFrame:
    since = date.today().replace(day=1) - timedelta(days=365 * years)
    df = _q(f"""SELECT kind, contract_date, exclusive_m2, price, deposit, monthly_rent, converted, floor, apt_dong,
                      contract_type, canceled
               FROM trade WHERE contract_date >= :since AND apt_key IN (
                   SELECT apt_key FROM ({EFFECTIVE_SQL}) WHERE complex_id = :cid)
               ORDER BY contract_date DESC""", cid=complex_id, since=since)
    df["contract_date"] = pd.to_datetime(df["contract_date"])
    df["canceled"] = df["canceled"].fillna(0).astype(bool)
    return _reconvert(df, "kind")


def _reconvert(df: pd.DataFrame, kind_col: str) -> pd.DataFrame:
    """전세 환산가를 지금 설정(config conversion_rate)으로 다시 계산한다.
    저장된 값은 수집 당시 전환율이라, 전환율을 바꾸면 과거 자료까지 바로 반영되게 화면에서 계산한다."""
    if df.empty:
        return df
    rate = config()["conversion_rate"] / 100
    wolse = df[kind_col] == "월세"
    df.loc[wolse, "converted"] = df.loc[wolse, "deposit"] + df.loc[wolse, "monthly_rent"].fillna(0) * 12 / rate
    jeonse = df[kind_col] == "전세"
    df.loc[jeonse, "converted"] = df.loc[jeonse, "deposit"]
    return df


@st.cache_data(ttl=300)
def listings(complex_id: int) -> tuple[pd.DataFrame, str | None]:
    last = _q("SELECT MAX(collect_date) d FROM listing_snapshot WHERE complex_id = :cid", cid=complex_id)["d"][0]
    if not last:
        return pd.DataFrame(), None
    df = _q("SELECT * FROM listing_snapshot WHERE complex_id = :cid AND collect_date = :d", cid=complex_id, d=last)
    return _reconvert(df, "trade_type"), str(last)


@st.cache_data(ttl=300)
def news_editions() -> list[tuple[str, int]]:
    """[(날짜, 회차 시)] 최신순. 회차 = 수집 시각의 시 (05·11·17)"""
    df = _q("""SELECT DISTINCT news_date, edition FROM news_daily
               ORDER BY news_date DESC, edition DESC LIMIT 300""")
    return [(str(r.news_date), int(r.edition)) for r in df.itertuples()]


@st.cache_data(ttl=300)
def news(news_date: str, edition: int) -> pd.DataFrame:
    return _q("SELECT * FROM news_daily WHERE news_date = :d AND edition = :e ORDER BY rank", d=news_date, e=edition)


@st.cache_data(ttl=120)
def collect_status() -> pd.DataFrame:
    return _q("""SELECT collector, status, count, error, MAX(run_at) AS run_at FROM collect_log GROUP BY collector""")


@st.cache_data(ttl=120)
def last_ok(collector: str) -> str | None:
    return _q("SELECT MAX(run_at) t FROM collect_log WHERE collector = :c AND status IN ('ok','partial')",
              c=collector)["t"][0]


@st.cache_data(ttl=3600)
def regions(level: int, parent: str | None = None) -> pd.DataFrame:
    if parent:
        return _q("SELECT * FROM region WHERE level = :l AND parent = :p ORDER BY code", l=level, p=parent)
    return _q("SELECT * FROM region WHERE level = :l ORDER BY code", l=level)


def save_areas(complex_id: int, areas: list[float]):
    with Session.begin() as s:
        w = s.get(Watchlist, complex_id)
        if w:
            w.areas = json.dumps(areas)
    watched_complexes.clear()


def remove_watch(complex_id: int):
    """관심 해제: 바로 지우지 않고 '해제 대기'로 옮긴다 (보관 기간이 지나면 수집 때 정리)"""
    with Session.begin() as s:
        w = s.get(Watchlist, complex_id)
        if w:
            s.merge(Unwatched(complex_id=complex_id, areas=w.areas, removed_at=datetime.now()))
            s.delete(w)
    watched_complexes.clear()
    unwatched.clear()
    from ui.sync_ui import push_pc_background
    push_pc_background()


def restore_watch(complex_id: int):
    """해제 대기 단지를 다시 관심 단지로 (고른 평형도 복원)"""
    with Session.begin() as s:
        u = s.get(Unwatched, complex_id)
        if u:
            s.merge(Watchlist(complex_id=complex_id, areas=u.areas))
            s.delete(u)
    watched_complexes.clear()
    unwatched.clear()
    from ui.sync_ui import push_pc_background
    push_pc_background()


@st.cache_data(ttl=300)
def unwatched() -> pd.DataFrame:
    return _q("""SELECT u.complex_id, c.name, c.sido, c.sigungu, c.dong, u.removed_at
                 FROM unwatched u LEFT JOIN complex c USING (complex_id) ORDER BY u.removed_at DESC""")


def clear_all():
    st.cache_data.clear()
