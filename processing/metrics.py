"""환산가, 평형 구간, 표시 형식, 월별 집계."""
import pandas as pd

from settings import config

M2_PER_PYEONG = 3.3058


def converted_price(deposit, monthly_rent, rate: float | None = None):
    """전세 환산가(만원) = 보증금 + 월세 × 12 ÷ 전환율"""
    if deposit is None:
        return None
    rate = rate or config()["conversion_rate"]
    return deposit + (monthly_rent or 0) * 12 / (rate / 100)


def area_bucket(exclusive_m2: float | None) -> str | None:
    if exclusive_m2 is None:
        return None
    for b in config()["area_buckets"]:
        if b["min"] <= exclusive_m2 < b["max"]:
            return b["name"]
    return None


def bucket_names() -> list[str]:
    return [b["name"] for b in config()["area_buckets"]]


def to_pyeong(m2: float) -> float:
    return m2 / M2_PER_PYEONG


def area_label(exclusive_m2: float, supply_m2: float | None = None) -> str:
    s = f"{exclusive_m2:.2f}㎡ ({to_pyeong(exclusive_m2):.1f}평)"
    if supply_m2:
        s += f" · 공급 {to_pyeong(supply_m2):.0f}평"
    return s


def fmt_money(manwon) -> str:
    """만원 → '30.5억' / '8,500만'"""
    if manwon is None or pd.isna(manwon):
        return "-"
    v = float(manwon)
    if abs(v) >= 10000:
        eok = v / 10000
        return f"{eok:.1f}억".replace(".0억", "억") if eok < 100 else f"{eok:,.0f}억"
    return f"{v:,.0f}만"


def fmt_range(lo, hi) -> str:
    if lo is None or pd.isna(lo):
        return "-"
    if lo == hi:
        return fmt_money(lo)
    return f"{fmt_money(lo)}~{fmt_money(hi)}"


def monthly_series(df: pd.DataFrame, value_col: str, group_col: str | None = None) -> pd.DataFrame:
    """월별 중위값 + 건수. df: contract_date, value_col, (group_col)"""
    if df.empty:
        return pd.DataFrame(columns=["month", "median", "count"] + ([group_col] if group_col else []))
    d = df.copy()
    d["month"] = pd.to_datetime(d["contract_date"]).dt.to_period("M").dt.to_timestamp()
    keys = ["month"] + ([group_col] if group_col else [])
    out = d.groupby(keys)[value_col].agg(median="median", count="count").reset_index()
    return out


def snap_area(values: pd.Series, known: list[float], tol: float = 1.0) -> pd.Series:
    """실거래 전용면적을 단지 평형 목록의 가장 가까운 값으로 맞춘다 (tol ㎡ 이내)."""
    if not known:
        return values.round(2)

    def f(v):
        best = min(known, key=lambda k: abs(k - v))
        return best if abs(best - v) <= tol else round(v, 2)
    return values.map(f)
