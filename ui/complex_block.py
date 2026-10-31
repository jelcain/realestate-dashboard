"""단지 블록: 실거래 추이 그래프 3개(R1) + 매물 요약·상세(R2) + 최근 실거래 내역."""
from datetime import date
import json

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from processing.metrics import area_bucket, area_label, fmt_money, fmt_range, monthly_series, snap_area, to_pyeong
from settings import config
from ui import collect, data
from ui.filters import Filters

# 범주형 색 (고정 순서, 평형마다 고정 배정)
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
MUTED = "#898781"
GRID = "rgba(137,135,129,0.25)"


def _area_info(at: pd.DataFrame, tr: pd.DataFrame) -> tuple[list[float], dict[float, float | None]]:
    """단지의 전용면적 목록(정렬)과 전용→공급 면적"""
    known = sorted({round(x, 2) for x in at["exclusive_m2"]})
    supply = {}
    for ex, grp in at.groupby(at["exclusive_m2"].round(2)):
        supply[ex] = grp["supply_m2"].max()
    if not tr.empty:
        tr["area"] = snap_area(tr["exclusive_m2"], known)
        for a in tr["area"].unique():
            if a not in supply:
                known.append(a)
                supply[a] = None
    return sorted(known), supply


def _short(a: float, supply: dict) -> str:
    s = f"{a:.2f}㎡({to_pyeong(a):.1f}평)"
    return s + (f"·공급{to_pyeong(supply[a]):.0f}평" if supply.get(a) else "")


def _layout(fig: go.Figure, title: str, n_series: int, y_title: str):
    fig.update_layout(
        title=dict(text=title, font=dict(size=15), x=0, xanchor="left"),
        height=360, margin=dict(l=8, r=8, t=40, b=8), hovermode="x unified", barmode="stack", bargap=0.2,
        showlegend=n_series >= 2, legend=dict(orientation="h", yanchor="bottom", y=1.0, x=1, xanchor="right",
                                              font=dict(size=11)),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    fig.update_xaxes(showgrid=False, linecolor=GRID, tickfont=dict(color=MUTED), tickformat="%y.%m")
    fig.update_yaxes(gridcolor=GRID, zeroline=False, tickfont=dict(color=MUTED))
    fig.update_yaxes(title_text=y_title, title_font=dict(color=MUTED, size=11), row=1, col=1)
    fig.update_yaxes(title_text="건수", title_font=dict(color=MUTED, size=11), row=2, col=1)


def _empty(title: str):
    st.markdown(f"**{title}**")
    st.caption("해당 기간·평형의 거래가 없습니다.")


def trend_chart(df: pd.DataFrame, kind: str, areas: list[float], colors: dict, supply: dict, key: str):
    """선: 월별 중위 가격 / 막대: 월별 거래 건수 (같은 x축, 위아래 두 패널)"""
    value = {"매매": "price", "전세": "deposit", "월세": "converted"}[kind]
    title = {"매매": "매매 추이", "전세": "전세 추이", "월세": "월세 추이 (전세 환산가)"}[kind]
    d = df[(df["kind"] == kind) & df["area"].isin(areas)]
    if d.empty:
        return _empty(title)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28], vertical_spacing=0.05)
    for a in areas:
        da = d[d["area"] == a].copy()
        if da.empty:
            continue
        da["month"] = da["contract_date"].dt.to_period("M").dt.to_timestamp()
        agg = {"median": (value, "median"), "count": (value, "count")}
        if kind == "월세":
            agg |= {"dep": ("deposit", "median"), "rent": ("monthly_rent", "median")}
        m = da.groupby("month").agg(**agg).reset_index()
        name = _short(a, supply)
        if kind == "월세":
            custom = list(zip(m["count"], m["dep"].map(fmt_money), m["rent"].map(lambda v: f"{v:,.0f}만")))
            ht = "%{y:.2f}억 (보증금 %{customdata[1]} / 월 %{customdata[2]}, %{customdata[0]}건)"
        else:
            custom = list(zip(m["count"]))
            ht = "%{y:.2f}억 (%{customdata[0]}건)"
        fig.add_trace(go.Scatter(x=m["month"], y=m["median"] / 10000, mode="lines+markers", name=name,
                                 line=dict(color=colors[a], width=2), marker=dict(size=7, color=colors[a],
                                 line=dict(width=1.5, color="white")), customdata=custom,
                                 hovertemplate=ht + f"<extra>{name}</extra>"), row=1, col=1)
        fig.add_trace(go.Bar(x=m["month"], y=m["count"], marker=dict(color=colors[a], opacity=0.55),
                             name=name, showlegend=False, hovertemplate="%{y}건<extra></extra>"), row=2, col=1)
    _layout(fig, title, len(areas), "중위가 (억)")
    st.plotly_chart(fig, width="stretch", key=key, config={"displayModeBar": False})


def rent_band_chart(df: pd.DataFrame, areas: list[float], key: str):
    """보조 보기: 보증금 구간별 월세 추이"""
    d = df[(df["kind"] == "월세") & df["area"].isin(areas)]
    title = "월세 추이 (보증금 구간별 월세)"
    if d.empty:
        return _empty(title)
    bands = config()["deposit_bands"]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28], vertical_spacing=0.05)
    for i, b in enumerate(bands):
        db = d[(d["deposit"] >= b["min"]) & (d["deposit"] < b["max"])]
        if db.empty:
            continue
        m = monthly_series(db, "monthly_rent")
        color = PALETTE[i]
        fig.add_trace(go.Scatter(x=m["month"], y=m["median"], mode="lines+markers", name=b["name"],
                                 line=dict(color=color, width=2), marker=dict(size=7, color=color),
                                 customdata=m["count"], hovertemplate="월 %{y:,.0f}만 (%{customdata}건)"),
                      row=1, col=1)
        fig.add_trace(go.Bar(x=m["month"], y=m["count"], marker=dict(color=color, opacity=0.55), name=b["name"],
                             showlegend=False, hovertemplate="%{y}건<extra></extra>"), row=2, col=1)
    _layout(fig, title, len(bands), "월세 중위 (만원)")
    st.plotly_chart(fig, width="stretch", key=key, config={"displayModeBar": False})


def _price_text(r) -> str:
    if r["kind"] == "매매":
        return fmt_money(r["price"])
    if r["kind"] == "전세":
        return fmt_money(r["deposit"])
    return f"{fmt_money(r['deposit'])} / {r['monthly_rent']:,.0f}만"


# 거래 유형 글자색 (표: 16진수, 요약 마크다운: Streamlit 색 이름)
KIND_COLORS = {"매매": "#d6402f", "전세": "#2a6fd6", "월세": "#1a8a3c"}
KIND_MD = {"매매": "red", "전세": "blue", "월세": "green"}
KIND_ORDER = {"매매": 0, "전세": 1, "월세": 2}


def kind_label(k: str) -> str:
    return f":{KIND_MD.get(k, 'gray')}[**{k}**]"


def color_by_kind(df: pd.DataFrame, cols: list[str]):
    """'유형' 값에 따라 지정한 열의 글자색을 바꾼 Styler"""
    def row_style(r):
        css = f"color: {KIND_COLORS.get(r['유형'], 'inherit')}; font-weight: 600"
        return [css if c in cols else "" for c in r.index]
    return df.style.apply(row_style, axis=1)


def listing_summary(L: pd.DataFrame, T: pd.DataFrame, kinds: list[str]) -> list[str]:
    lines = []
    for k in kinds:
        d = L[L["trade_type"] == k]
        if d.empty:
            lines.append(f"{kind_label(k)} 0건")
            continue
        if k == "매매":
            med = d["price"].median()
            s = f"{kind_label(k)} {len(d)}건 · {fmt_range(d['price'].min(), d['price'].max())} · 중위 {fmt_money(med)}"
            recent = T[(T["kind"] == "매매")].sort_values("contract_date", ascending=False)
            recent = recent[recent["contract_date"] >= recent["contract_date"].max() - pd.DateOffset(months=3)] \
                if not recent.empty else recent
            if not recent.empty:
                diff = (med / recent["price"].median() - 1) * 100
                s += f" · 최근 3개월 실거래 중위 대비 {diff:+.1f}%"
        elif k == "전세":
            s = (f"{kind_label(k)} {len(d)}건 · {fmt_range(d['deposit'].min(), d['deposit'].max())} · "
                 f"중위 {fmt_money(d['deposit'].median())}")
        else:
            s = (f"{kind_label(k)} {len(d)}건 · 보증금 {fmt_range(d['deposit'].min(), d['deposit'].max())} · "
                 f"월 {d['monthly_rent'].min():,.0f}만~{d['monthly_rent'].max():,.0f}만 · "
                 f"환산 {fmt_range(d['converted'].min(), d['converted'].max())}")
        lines.append(s)
    return lines


def listing_table(L: pd.DataFrame, supply: dict) -> pd.DataFrame:
    def price(r):
        if r["trade_type"] == "매매":
            return fmt_money(r["price"])
        if r["trade_type"] == "전세":
            return fmt_money(r["deposit"])
        return f"{fmt_money(r['deposit'])} / {r['monthly_rent']:,.0f}만"

    out = pd.DataFrame({
        "유형": L["trade_type"], "동": L["dong"], "층": L["floor"], "향": L["direction"],
        "전용": L["area"].map(lambda a: f"{a:.2f}㎡ ({to_pyeong(a):.1f}평)"),
        "가격 (보증금/월세)": L.apply(price, axis=1),
        "비교가(억)": (L["price"].fillna(L["converted"]) / 10000).round(2),
        "확인일": L["confirm_date"].fillna("").str[5:].str.replace("-", "/"),
        "중개사": L.apply(lambda r: (r["broker"] or "") + (f" 외 {r['realtor_count'] - 1}곳"
                                                         if (r["realtor_count"] or 1) > 1 else ""), axis=1),
        "특징": L["description"],
    })
    out["_o"] = out["유형"].map(KIND_ORDER)
    return out.sort_values(["_o", "비교가(억)"]).drop(columns="_o")


def trade_table(T: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "계약일": T["contract_date"].dt.strftime("%y/%m/%d"),
        "동·층": T.apply(lambda r: (f"{r['apt_dong']}동 " if isinstance(r["apt_dong"], str) else "")
                         + (f"{r['floor']:.0f}층" if pd.notna(r["floor"]) else ""), axis=1),
        "전용": T["area"].map(lambda a: f"{a:.2f}㎡ ({to_pyeong(a):.1f}평)"),
        "유형": T["kind"],
        "가격 (보증금/월세)": T.apply(_price_text, axis=1),
        "환산가": T["converted"].map(fmt_money).where(T["kind"] == "월세", ""),
        "구분": T.apply(lambda r: "해제" if r["canceled"] else (r["contract_type"] or ""), axis=1),
    })


def _on_area_change(complex_id: int, key: str):
    data.save_areas(complex_id, st.session_state[key])


def render(cx: pd.Series, f: Filters):
    cid = int(cx["complex_id"])
    at = data.area_types(cid)
    tr = data.trades(cid, f.years).copy()
    known, supply = _area_info(at, tr)
    options = [a for a in known if area_bucket(a) in f.buckets]
    colors = {a: PALETTE[i % len(PALETTE)] for i, a in enumerate(known)}

    raw = cx["areas"] if isinstance(cx["areas"], str) else "[]"  # 저장값 없으면 NULL→NaN
    saved = [a for a in json.loads(raw) if a in options]
    if not saved and options:
        counts = tr[tr["area"].isin(options)]["area"].value_counts() if not tr.empty else pd.Series(dtype=int)
        saved = [counts.index[0]] if len(counts) else [options[0]]

    built = f" · {cx['approval_date'][:4]}년" if cx["approval_date"] else ""
    with st.container(border=True):
        h1, h2, h3, h4 = st.columns([6, 1, 0.7, 1])
        h1.markdown(f"#### {cx['name']} <span style='font-size:0.8em;color:{MUTED}'>"
                    f"{cx['households'] or '-'}세대{built}</span>", unsafe_allow_html=True)
        show = h2.toggle("펼치기", value=True, key=f"open_{cid}")
        collect.complex_button(cid, cx["name"], h3)
        if h4.button("관심 해제", key=f"rm_{cid}"):
            data.remove_watch(cid)
            st.rerun()
        if not show:
            return
        if not options:
            st.info("선택한 평형 구간에 해당하는 평형이 없습니다.")
            return
        key = f"areas_{cid}"
        areas = st.multiselect("평형", options, default=saved, key=key,
                               format_func=lambda a: area_label(a, supply.get(a)),
                               on_change=_on_area_change, args=(cid, key))
        if not areas:
            st.caption("평형을 하나 이상 선택하세요.")
            return

        T = tr[tr["area"].isin(areas)] if not tr.empty else tr
        T_chart = T[~T["canceled"]] if not T.empty else T
        if f.new_only and not T_chart.empty:
            T_chart = T_chart[(T_chart["kind"] == "매매") | (T_chart["contract_type"] == "신규")]

        # R1: 그래프 가로 배치
        if f.kinds:
            cols = st.columns(len(f.kinds))
            for col, k in zip(cols, f.kinds):
                with col:
                    if T_chart.empty:
                        _empty(f"{k} 추이")
                    elif k == "월세" and st.session_state.get(f"band_{cid}"):
                        rent_band_chart(T_chart, areas, key=f"c_{cid}_band")
                    else:
                        trend_chart(T_chart, k, areas, colors, supply, key=f"c_{cid}_{k}")
            if "월세" in f.kinds:
                st.toggle("월세: 보증금 구간별 월세 보기", key=f"band_{cid}")

        # R2: 매물 요약 + 상세
        L, snap_date = data.listings(cid)
        if L.empty:
            st.caption("수집된 매물이 없습니다. (일일 배치 후 표시)")
        else:
            L = L.copy()
            L["area"] = snap_area(L["exclusive_m2"].fillna(0), known)
            L = L[L["area"].isin(areas) & L["trade_type"].isin(f.kinds)]
            left, right = st.columns([1, 2.2])
            with left:
                st.markdown(f"**매물 요약** <span style='color:{MUTED};font-size:0.85em'>({snap_date} 수집)</span>",
                            unsafe_allow_html=True)
                for line in listing_summary(L, T[~T["canceled"]] if not T.empty else T, f.kinds):
                    st.markdown(line.replace("~", r"\~"))  # '~' 가 취소선으로 바뀌지 않게
            with right:
                table = color_by_kind(listing_table(L, supply), ["유형", "가격 (보증금/월세)"])
                st.dataframe(table.format(precision=2, subset=["비교가(억)"]), hide_index=True,
                             width="stretch", height=260,
                             column_config={"비교가(억)": st.column_config.NumberColumn(
                                 format="%.2f", help="매매가 또는 전세 환산가. 정렬·비교용"),
                                 "특징": st.column_config.TextColumn(width="medium")})

        if st.toggle("최근 실거래 내역", key=f"tr_{cid}") and not T.empty:
            st.dataframe(color_by_kind(trade_table(T[T["kind"].isin(f.kinds)].head(200)),
                                       ["유형", "가격 (보증금/월세)"]), hide_index=True,
                         width="stretch", height=300)
