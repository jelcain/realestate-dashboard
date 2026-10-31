"""국토교통부 아파트 매매(상세)·전월세 실거래가 수집기.

- 관심 단지가 속한 시군구만 받는다.
- 매번 최근 N개월(refresh_months)을 다시 받아 늦은 신고와 해제 거래를 반영한다.
- 아직 받지 않은 과거 월은 호출 한도(max_calls_per_run) 안에서 최신 월부터 이어 받는다.
"""
from datetime import date, datetime
import logging
import time
import xml.etree.ElementTree as ET

import httpx
from sqlalchemy import delete, select

from db.models import Complex, MolitProgress, Session, Trade, Watchlist, log_collect
from processing.metrics import converted_price
from settings import config, molit_key

log = logging.getLogger(__name__)

APIS = {
    "trade": "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev",
    "rent": "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent",
}


class QuotaExceeded(Exception):
    pass


def _int(v):
    if v is None:
        return None
    v = v.replace(",", "").strip()
    if not v:
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def _str(v):
    v = (v or "").strip()
    return v or None


def apt_key(it: dict) -> str:
    return _str(it.get("aptSeq")) or "|".join(
        [it.get("sggCd", ""), (it.get("umdNm") or "").strip(), (it.get("jibun") or "").strip(),
         (it.get("aptNm") or "").strip()])


def fetch_month(client: httpx.Client, api: str, sgg: str, ym: str) -> tuple[list[dict], int]:
    """한 달치 전체 페이지. 반환: (항목 목록, 호출 수)"""
    rows = config()["molit"]["rows_per_page"]
    items, page, calls = [], 1, 0
    while True:
        r = client.get(APIS[api], params={"serviceKey": molit_key(api), "LAWD_CD": sgg, "DEAL_YMD": ym,
                                          "pageNo": page, "numOfRows": rows})
        calls += 1
        r.raise_for_status()
        root = ET.fromstring(r.content)
        code = (root.findtext(".//resultCode") or root.findtext(".//returnReasonCode") or "").strip()
        msg = (root.findtext(".//resultMsg") or root.findtext(".//returnAuthMsg") or "").strip()
        if code not in ("000", "00"):
            if code == "22" or "LIMITED" in msg:
                raise QuotaExceeded(msg)
            raise RuntimeError(f"국토부 API 오류 {code}: {msg}")
        for el in root.iter("item"):
            items.append({c.tag: (c.text or "") for c in el})
        total = _int(root.findtext(".//totalCount")) or 0
        if page * rows >= total:
            return items, calls
        page += 1
        time.sleep(0.2)


def to_trade(api: str, sgg: str, ym: str, it: dict) -> Trade | None:
    try:
        d = date(int(it["dealYear"]), int(it["dealMonth"]), int(it["dealDay"]))
        area = float(it["excluUseAr"])
    except (KeyError, ValueError):
        return None
    base = dict(api=api, sgg_cd=sgg, deal_ym=ym, umd_nm=_str(it.get("umdNm")), jibun=_str(it.get("jibun")),
                apt_nm=_str(it.get("aptNm")), apt_key=apt_key(it), contract_date=d, exclusive_m2=area,
                floor=_int(it.get("floor")), apt_dong=_str(it.get("aptDong")))
    if api == "trade":
        return Trade(**base, kind="매매", price=_int(it.get("dealAmount")),
                     canceled=_str(it.get("cdealType")) == "O", cancel_date=_str(it.get("cdealDay")))
    deposit, rent = _int(it.get("deposit")), _int(it.get("monthlyRent")) or 0
    return Trade(**base, kind="월세" if rent > 0 else "전세", deposit=deposit, monthly_rent=rent,
                 converted=converted_price(deposit, rent), contract_type=_str(it.get("contractType")))


def save_month(api: str, sgg: str, ym: str, items: list[dict]):
    with Session.begin() as s:
        s.execute(delete(Trade).where(Trade.api == api, Trade.sgg_cd == sgg, Trade.deal_ym == ym))
        s.add_all(t for t in (to_trade(api, sgg, ym, it) for it in items) if t)
        s.merge(MolitProgress(api=api, sgg_cd=sgg, deal_ym=ym, rows=len(items), fetched_at=datetime.now()))


def month_list(n: int, today: date | None = None) -> list[str]:
    today = today or date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def target_sggs() -> list[str]:
    with Session() as s:
        codes = s.scalars(select(Complex.legal_code).join(Watchlist, Watchlist.complex_id == Complex.complex_id))
        return sorted({c[:5] for c in codes if c})


def sggs_of(complex_ids: list[int]) -> list[str]:
    with Session() as s:
        codes = s.scalars(select(Complex.legal_code).where(Complex.complex_id.in_(complex_ids)))
        return sorted({c[:5] for c in codes if c})


def plan_months(api: str, sgg: str) -> list[str]:
    cfg = config()["molit"]
    months = month_list(cfg["history_months"])
    refresh = months[: cfg["refresh_months"]]
    with Session() as s:
        done = set(s.scalars(select(MolitProgress.deal_ym).where(MolitProgress.api == api,
                                                                 MolitProgress.sgg_cd == sgg)))
    return refresh + [m for m in months[cfg["refresh_months"]:] if m not in done]


def run(sggs: list[str] | None = None) -> int:
    """반환: 저장한 거래 건수"""
    from processing.mapping import apply_mappings

    if not molit_key("trade") and not molit_key("rent"):
        log_collect("molit", "skipped", error="MOLIT_SERVICE_KEY 미설정")
        log.warning("국토부 API 키가 없어 실거래 수집을 건너뜁니다 (.env 확인)")
        return 0
    sggs = sggs or target_sggs()
    if not sggs:
        log.info("관심 단지가 없어 실거래 수집을 건너뜁니다")
        return 0
    budget = config()["molit"]["max_calls_per_run"]
    total, status, err = 0, "ok", None
    with httpx.Client(timeout=60) as client:
        for api in ("trade", "rent"):
            if not molit_key(api):
                continue
            calls = 0
            try:
                for sgg in sggs:
                    plan = plan_months(api, sgg)
                    for ym in plan:
                        if calls >= budget:
                            status = "partial"
                            log.info("[%s] 호출 한도(%d) 도달, 다음 실행 때 이어 받음", api, budget)
                            break
                        for attempt in range(3):
                            try:
                                items, n = fetch_month(client, api, sgg, ym)
                                break
                            except (httpx.TransportError, httpx.HTTPStatusError, ET.ParseError) as e:
                                if attempt == 2:
                                    raise
                                log.warning("재시도 %s %s %s: %s", api, sgg, ym, e)
                                time.sleep(5)
                        calls += n
                        save_month(api, sgg, ym, items)
                        total += len(items)
                        log.info("[%s] %s %s: %d건", api, sgg, ym, len(items))
            except QuotaExceeded as e:
                status, err = "partial", f"{api}: 일일 한도 초과 ({e})"
                log.warning(err)
            except Exception as e:  # noqa: BLE001 - 수집 이력에 남기고 다음 API 진행
                status, err = "error", f"{api}: {e}"
                log.exception("국토부 수집 오류")
    apply_mappings()
    log_collect("molit", status, total, err)
    return total
