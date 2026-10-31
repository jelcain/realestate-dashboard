"""네이버페이 부동산 매물 수집기 (관심 단지, 하루 1회).

네이버 API 구조가 바뀌면 이 모듈의 parse_article / fetch_articles 만 고친다.
"""
from datetime import date
import logging

from sqlalchemy import delete, select

from collectors.naver_client import Blocked, NaverClient
from db.models import ListingSnapshot, Session, Watchlist, log_collect
from processing.metrics import converted_price
from settings import config

log = logging.getLogger(__name__)

TRADE_TYPES = {"A1": "매매", "B1": "전세", "B2": "월세"}
DIRECTIONS = {"EE": "동", "WW": "서", "SS": "남", "NN": "북",
              "ES": "남동", "WS": "남서", "EN": "북동", "WN": "북서"}


def _manwon(won) -> int | None:
    return round(won / 10000) if won else None


def parse_article(item: dict) -> dict:
    a = item.get("representativeArticleInfo") or item
    dup = item.get("duplicatedArticleInfo") or {}
    price = a.get("priceInfo", {})
    space = a.get("spaceInfo", {})
    detail = a.get("articleDetail", {})
    trade = TRADE_TYPES.get(a.get("tradeType"), a.get("tradeType"))
    deposit, rent = _manwon(price.get("warrantyPrice")), _manwon(price.get("rentPrice"))
    if trade == "매매":
        deposit = rent = None
    return {
        "article_no": str(a["articleNumber"]),
        "trade_type": trade,
        "price": _manwon(price.get("dealPrice")) if trade == "매매" else None,
        "deposit": deposit,
        "monthly_rent": rent if trade == "월세" else None,
        "converted": (converted_price(deposit, rent) if trade == "월세" else deposit) if trade != "매매" else None,
        "dong": a.get("dongName"),
        "floor": detail.get("floorInfo"),
        "direction": DIRECTIONS.get(detail.get("direction"), detail.get("direction")),
        "exclusive_m2": space.get("exclusiveSpace"),
        "supply_m2": space.get("supplySpace"),
        "confirm_date": (a.get("verificationInfo") or {}).get("articleConfirmDate"),
        "broker": (a.get("brokerInfo") or {}).get("brokerageName"),
        "realtor_count": dup.get("realtorCount") or 1,
        "description": detail.get("articleFeatureDescription"),
    }


def fetch_articles(client: NaverClient, complex_id: int, trade_type: str) -> list[dict]:
    max_pages = config()["naver"]["max_pages_per_type"]
    out, last, seed = [], [], None
    for _ in range(max_pages):
        body = {"size": 30, "complexNumber": str(complex_id), "tradeTypes": [trade_type],
                "userChannelType": "PC", "lastInfo": last}
        if seed:
            body["seed"] = seed
        res = client.post("/complex/article/list", body) or {}
        out += [parse_article(it) for it in res.get("list", [])]
        if not res.get("hasNextPage"):
            break
        last, seed = res.get("lastInfo") or [], res.get("seed")
    return out


def collect_complex(client: NaverClient, complex_id: int, today: date | None = None) -> int:
    today = today or date.today()
    rows: dict[str, dict] = {}
    for tt in TRADE_TYPES:
        for r in fetch_articles(client, complex_id, tt):
            rows[r["article_no"]] = r
    with Session.begin() as s:
        s.execute(delete(ListingSnapshot).where(ListingSnapshot.collect_date == today,
                                                ListingSnapshot.complex_id == complex_id))
        s.add_all(ListingSnapshot(collect_date=today, complex_id=complex_id, **r) for r in rows.values())
    return len(rows)


def run(complex_ids: list[int] | None = None, client: NaverClient | None = None) -> int:
    # 전체 관심 단지 수집만 'naver_listing' 으로 기록한다 (자동 수집의 '하루 한 번' 판단과 수집 지연 경고에 쓰임)
    name = "naver_listing" if complex_ids is None else "naver_listing_complex"
    if complex_ids is None:
        with Session() as s:
            complex_ids = list(s.scalars(select(Watchlist.complex_id)))
    own = client is None
    client = client or NaverClient()
    total, done = 0, 0
    try:
        for cid in complex_ids:
            n = collect_complex(client, cid)
            total, done = total + n, done + 1
            log.info("매물 %s: %d건 (%d/%d)", cid, n, done, len(complex_ids))
        log_collect(name, "ok", total)
    except Blocked as e:
        log.warning("네이버 차단 응답 → 수집 중단 (%d/%d 단지 완료): %s", done, len(complex_ids), e)
        log_collect(name, "blocked", total, f"{done}/{len(complex_ids)} 단지 완료 후 중단: {e}")
    except Exception as e:  # noqa: BLE001
        log.exception("매물 수집 오류")
        log_collect(name, "error", total, f"{done}/{len(complex_ids)} 단지 완료 후 오류: {e}")
    finally:
        if own:
            client.close()
    return total
