"""대시보드용 DB 조회 (캐시)."""
from datetime import date, timedelta
import json

import pandas as pd
import streamlit as st
from sqlalchemy import text

from db.models import Session, Watchlist, engine
from processing.mapping import EFFECTIVE_SQL


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
    return df


@st.cache_data(ttl=300)
def listings(complex_id: int) -> tuple[pd.DataFrame, str | None]:
    last = _q("SELECT MAX(collect_date) d FROM listing_snapshot WHERE complex_id = :cid", cid=complex_id)["d"][0]
    if not last:
        return pd.DataFrame(), None
    df = _q("SELECT * FROM listing_snapshot WHERE complex_id = :cid AND collect_date = :d", cid=complex_id, d=last)
    return df, str(last)


@st.cache_data(ttl=300)
def news(news_date: str | None = None) -> tuple[pd.DataFrame, list[str]]:
    dates = _q("SELECT DISTINCT news_date FROM news_daily ORDER BY news_date DESC LIMIT 60")["news_date"].astype(str).tolist()
    if not dates:
        return pd.DataFrame(), []
    d = news_date or dates[0]
    return _q("SELECT * FROM news_daily WHERE news_date = :d ORDER BY rank", d=d), dates


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
    with Session.begin() as s:
        w = s.get(Watchlist, complex_id)
        if w:
            s.delete(w)
    watched_complexes.clear()
    from ui.sync_ui import push_pc_background
    push_pc_background()


def clear_all():
    st.cache_data.clear()
