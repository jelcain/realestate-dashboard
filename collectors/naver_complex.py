"""네이버 단지 정보·평형, 단지 검색, 지역(법정동) 목록."""
from datetime import datetime, timedelta
import logging

from sqlalchemy import delete, select

from collectors.naver_client import Blocked, NaverClient
from db.models import AreaType, Complex, Region, Session, Watchlist, log_collect
from processing.metrics import area_bucket
from settings import cloud_mode, config

log = logging.getLogger(__name__)

# 법정동 단계 (네이버 LegalDivisionLevelType)
LEVELS = {1: "SI", 2: "GUN", 3: "EUP"}


def search(client: NaverClient, keyword: str, size: int = 20) -> list[dict]:
    res = client.get("/search/autocomplete/complexes", keyword=keyword, size=size) or {}
    return [{"complex_id": it["complexNumber"], "name": it["complexName"], "type": it.get("type"),
             "address": it.get("legalDivisionName"), "legal_code": it.get("legalDivisionNumber")}
            for it in res.get("list", [])]


def _region_row(it: dict, level: int, parent: str | None) -> Region:
    code = str(it.get("legalDivisionNumber"))
    city, div, sec = it.get("cityName"), it.get("divisionName"), it.get("sectorName")
    name = it.get("legalDivisionName") or it.get("name")
    if level == 1:
        city = city or name
    elif level == 2:
        div = div or name
    else:
        sec = sec or name
    return Region(code=code, sido=city or "", sigungu=div, dong=sec, level=level, parent=parent)


def load_regions(client: NaverClient, level: int, parent: str | None = None) -> list[Region]:
    """지역 목록을 네이버에서 받아 region 테이블에 캐시한다. level 1 은 parent 없이 전체 시/도."""
    if level == 1:
        res = client.get("/legalDivision/infoListByLevel", regionLevelType=LEVELS[1])
    else:
        res = client.get("/legalDivision/subInfoList", legalDivisionLevelType=LEVELS[level],
                         legalDivisionNumber=parent)
    items = res if isinstance(res, list) else (res or {}).get("list", [])
    rows = [_region_row(it, level, parent) for it in items]
    if level > 1 and rows:
        # 하위 목록에 상위 이름이 없으면 부모 행에서 채운다
        with Session() as s:
            p = s.get(Region, parent)
        for r in rows:
            r.sido = r.sido or (p.sido if p else "")
            if level == 3:
                r.sigungu = r.sigungu or (p.sigungu if p else None)
    with Session.begin() as s:
        for r in rows:
            s.merge(r)
    return rows


# 아파트(A01), 재건축(A04)
APT_TYPES = ["A01", "A04"]
_COMPLEX_FILTER = {"tradeTypes": ["A1", "B1", "B2"], "realEstateTypes": APT_TYPES, "roomCount": [],
                   "bathRoomCount": [], "optionTypes": [], "oneRoomShapeTypes": [], "moveInTypes": [],
                   "filtersExclusiveSpace": False, "floorTypes": [], "directionTypes": [], "hasArticlePhoto": False,
                   "isAuthorizedByOwner": False, "parkingTypes": [], "entranceTypes": [], "hasArticle": False}


def dong_complexes(client: NaverClient, legal_code: str, max_pages: int = 5) -> list[dict]:
    """동(법정동) 안의 아파트 단지 목록 (세대수 많은 순)"""
    out, last, seed = [], [], None
    for _ in range(max_pages):
        paging = {"size": 30, "userChannelType": "PC", "complexSortType": "HOUSEHOLD_NUMBER_DESC", "lastInfo": last}
        if seed:
            paging["seed"] = seed
        res = client.post("/complex/legalDivisionComplexList", {
            "filter": {**_COMPLEX_FILTER, "legalDivisionNumbers": [legal_code], "legalDivisionType": LEVELS[3]},
            "complexPagingRequest": paging}) or {}
        for it in res.get("list", []):
            info = (it.get("complex") or {}).get("complexInfo") or it.get("complexInfo") or {}
            out.append({"complex_id": info.get("complexNumber"), "name": info.get("name"),
                        "type": info.get("type"), "households": info.get("totalHouseholdNumber"),
                        "approval_date": info.get("useApprovalDate")})
        if not res.get("hasNextPage"):
            break
        last, seed = res.get("lastInfo") or [], res.get("seed")
    return [c for c in out if c["complex_id"]]


def fetch_complex(client: NaverClient, complex_id: int) -> Complex:
    """단지 기본 정보 + 평형 목록을 받아 저장"""
    info = client.get("/complex", complexNumber=complex_id)
    pyeongs = client.get("/complex/pyeongList", complexNumber=complex_id) or []
    addr = info.get("address", {})
    code = str(addr.get("legalDivisionNumber") or "")
    cx = Complex(complex_id=complex_id, name=info.get("name"), legal_code=code, sido=addr.get("city"),
                 sigungu=addr.get("division"), dong=addr.get("sector"), jibun=addr.get("jibun"),
                 road_address=addr.get("roadName"), households=info.get("totalHouseholdNumber"),
                 approval_date=info.get("useApprovalDate"), updated_at=datetime.now())
    with Session.begin() as s:
        s.merge(cx)
        s.execute(delete(AreaType).where(AreaType.complex_id == complex_id))
        for p in pyeongs:
            ex = p.get("exclusiveArea")
            if not ex:
                continue
            s.add(AreaType(complex_id=complex_id, pyeong_no=p["number"], name=p.get("name"),
                           exclusive_m2=float(ex), supply_m2=p.get("supplyArea"),
                           households=p.get("householdCount"), bucket=area_bucket(float(ex))))
        if code:
            # 지역 계층 (시도 / 시군구 / 동)
            s.merge(Region(code=code[:2] + "0" * 8, sido=cx.sido or "", sigungu=None, dong=None, level=1, parent=None))
            s.merge(Region(code=code[:5] + "0" * 5, sido=cx.sido or "", sigungu=cx.sigungu, dong=None, level=2,
                           parent=code[:2] + "0" * 8))
            s.merge(Region(code=code, sido=cx.sido or "", sigungu=cx.sigungu, dong=cx.dong, level=3,
                           parent=code[:5] + "0" * 5))
    return cx


def add_to_watchlist(complex_id: int, client: NaverClient | None = None) -> Complex:
    from processing.mapping import apply_mappings

    own = client is None
    client = client or NaverClient(delay=(0.5, 1.0))
    try:
        cx = fetch_complex(client, complex_id)
    finally:
        if own:
            client.close()
    with Session.begin() as s:
        if not s.get(Watchlist, complex_id):
            s.add(Watchlist(complex_id=complex_id))
    if not cloud_mode():  # 클라우드 분담 모드에선 실거래 쪽(클라우드)이 매핑을 계산한다
        apply_mappings()
    return cx


def refresh_watchlist(client: NaverClient, force: bool = False, ids: list[int] | None = None) -> int:
    """관심 단지 정보를 주기(complex_refresh_days)마다 갱신. ids 를 주면 그 단지만"""
    days = config()["naver"]["complex_refresh_days"]
    with Session() as s:
        rows = s.execute(select(Watchlist.complex_id, Complex.updated_at)
                         .outerjoin(Complex, Complex.complex_id == Watchlist.complex_id)).all()
    if ids:
        rows = [r for r in rows if r[0] in ids]
    due = [cid for cid, upd in rows if force or upd is None or upd < datetime.now() - timedelta(days=days)]
    n = 0
    try:
        for cid in due:
            fetch_complex(client, cid)
            n += 1
    except Blocked as e:
        log_collect("naver_complex", "blocked", n, str(e))
        raise
    log_collect("naver_complex", "ok", n)
    return n
