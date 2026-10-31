"""관심 해제한 단지의 자료 정리 (데이터가 끝없이 늘지 않게).

- cleanup_pc   (PC, pc.db)   : 해제 후 보관 기간이 지난 단지의 매물·평형·단지 정보·수동 매핑 삭제
- cleanup_cloud(실거래 쪽, cloud.db): 관심 단지(해제 대기 포함)가 하나도 없는 시군구의 실거래 삭제
지운 것이 있으면 VACUUM 으로 파일 크기를 줄인다.
"""
from datetime import datetime, timedelta
import logging

from sqlalchemy import delete, select, text

from db.models import (AreaType, Complex, ListingSnapshot, ManualMapping, Session, Unwatched, Watchlist,
                       engine, log_collect)
from settings import config

log = logging.getLogger(__name__)


def keep_days() -> int:
    return int(config().get("retention", {}).get("unwatched_days", 30))


def _vacuum(schema: str):
    """파일 크기 줄이기. 다른 프로그램(대시보드 등)이 DB 를 쓰는 중이면 실패할 수 있는데, 그래도 자료는 이미 지워졌다"""
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.exec_driver_sql(f"VACUUM {schema}")
    except Exception as e:  # noqa: BLE001
        log.warning("VACUUM %s 건너뜀 (다음 정리 때 다시 시도): %s", schema, e)


def cleanup_pc() -> int:
    """반환: 지운 단지 수"""
    cutoff = datetime.now() - timedelta(days=keep_days())
    with Session.begin() as s:
        watched = set(s.scalars(select(Watchlist.complex_id)))
        pending = set(s.scalars(select(Unwatched.complex_id)))
        # 이 기능 전에 해제된 단지(관심 목록에도 해제 대기에도 없는 단지)는 오늘부터 보관 기간을 센다
        for cid in set(s.scalars(select(Complex.complex_id))) - watched - pending:
            s.add(Unwatched(complex_id=cid, removed_at=datetime.now()))
        expired = list(s.scalars(select(Unwatched.complex_id).where(Unwatched.removed_at < cutoff)))
        expired = [c for c in expired if c not in watched]
        for model in (ListingSnapshot, AreaType, ManualMapping, Complex, Unwatched):
            s.execute(delete(model).where(model.complex_id.in_(expired)))
    if expired:
        _vacuum("main")
        log.info("관심 해제 %d일 지난 단지 자료 삭제: %s", keep_days(), expired)
        log_collect("cleanup_pc", "ok", len(expired), f"삭제한 단지: {expired}")
    return len(expired)


def cleanup_cloud() -> int:
    """반환: 지운 실거래 건수. 관심 단지가 하나도 없으면(자료를 못 받은 경우 등) 아무것도 지우지 않는다"""
    with Session.begin() as s:
        codes = set(s.scalars(select(Complex.legal_code).where(
            Complex.complex_id.in_(select(Watchlist.complex_id).union(select(Unwatched.complex_id))))))
        keep = sorted({c[:5] for c in codes if c})
        if not keep:
            log.warning("관심 단지가 없어 실거래 정리를 건너뜀")
            return 0
        params = {f"k{i}": k for i, k in enumerate(keep)}
        cond = f"sgg_cd NOT IN ({', '.join(':' + k for k in params)})"
        drop = [r[0] for r in s.execute(text(f"SELECT DISTINCT sgg_cd FROM trade WHERE {cond}"), params)]
        n = s.execute(text(f"DELETE FROM trade WHERE {cond}"), params).rowcount
        s.execute(text(f"DELETE FROM molit_progress WHERE {cond}"), params)
        s.execute(text(f"DELETE FROM apt_mapping WHERE {cond}"), params)
    if n:
        _vacuum("cloud")
        log.info("관심 단지가 없는 시군구 실거래 삭제: %s (%d건)", drop, n)
        log_collect("cleanup_cloud", "ok", n, f"삭제한 시군구: {drop}")
    return n
