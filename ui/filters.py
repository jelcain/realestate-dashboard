"""조회 조건 (R5)."""
from dataclasses import dataclass

import pandas as pd
import streamlit as st

from processing.metrics import bucket_names

ALL = "전체"


@dataclass
class Filters:
    sido: str
    sigungu: str
    dong: str
    years: int
    buckets: list[str]
    kinds: list[str]
    new_only: bool


def _opts(values) -> list[str]:
    return [ALL] + sorted({v for v in values if v})


def render(complexes: pd.DataFrame) -> Filters:
    c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
    sido = c1.selectbox("시/도", _opts(complexes["sido"]))
    sub = complexes if sido == ALL else complexes[complexes["sido"] == sido]
    sigungu = c2.selectbox("시군구", _opts(sub["sigungu"]))
    sub = sub if sigungu == ALL else sub[sub["sigungu"] == sigungu]
    dong = c3.selectbox("동", _opts(sub["dong"]))
    years = c4.radio("조회 기간", [1, 3, 5, 10], index=1, horizontal=True, format_func=lambda y: f"{y}년")

    c1, c2, c3 = st.columns([3, 2, 1.4])
    buckets = c1.pills("평형 구간 (전용면적 기준, 비우면 전체)", bucket_names(), selection_mode="multi", default=[])
    kinds = c2.pills("거래 유형", ["매매", "전세", "월세"], selection_mode="multi", default=["매매", "전세", "월세"])
    new_only = c3.radio("계약 구분", ["전체", "신규만"], horizontal=True,
                        help="전세·월세에만 적용. 국토부 자료에 신규/갱신 표시가 없는 거래는 '신규만'에서 빠집니다.") == "신규만"
    return Filters(sido, sigungu, dong, years, buckets or bucket_names(), kinds or [], new_only)


def apply_region(complexes: pd.DataFrame, f: Filters) -> pd.DataFrame:
    df = complexes
    if f.sido != ALL:
        df = df[df["sido"] == f.sido]
    if f.sigungu != ALL:
        df = df[df["sigungu"] == f.sigungu]
    if f.dong != ALL:
        df = df[df["dong"] == f.dong]
    return df
