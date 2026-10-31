"""SQLite 스키마 (SQLAlchemy). 금액 단위는 모두 만원.

두 파일로 나뉜다. 연결은 pc.db 를 열고 cloud.db 를 'cloud' 로 ATTACH 해서 한 DB 처럼 쓴다
(SQLite 는 스키마를 안 붙인 테이블 이름을 main → 붙인 DB 순서로 찾는다).
  - PcBase    → pc.db    : PC 가 쓰는 표 (네이버 수집, 관심 단지, 수동 매핑)
  - CloudBase → cloud.db : 클라우드가 쓰는 표 (국토부 실거래, 자동 매핑, 뉴스)
"""
from datetime import date, datetime
import os

from sqlalchemy import (Boolean, Date, DateTime, Float, Integer, String, Text,
                        create_engine, event, Index)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from settings import db_dir, on_cloud


class PcBase(DeclarativeBase):
    pass


class CloudBase(DeclarativeBase):
    pass


class Region(PcBase):
    """법정동 계층. level: 1=시도, 2=시군구, 3=읍면동"""
    __tablename__ = "region"
    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    sido: Mapped[str] = mapped_column(String(40))
    sigungu: Mapped[str | None] = mapped_column(String(40))
    dong: Mapped[str | None] = mapped_column(String(40))
    level: Mapped[int] = mapped_column(Integer)
    parent: Mapped[str | None] = mapped_column(String(10), index=True)


class Complex(PcBase):
    __tablename__ = "complex"
    complex_id: Mapped[int] = mapped_column(Integer, primary_key=True)  # 네이버 단지번호
    name: Mapped[str] = mapped_column(String(100))
    legal_code: Mapped[str] = mapped_column(String(10), index=True)
    sido: Mapped[str | None] = mapped_column(String(40))
    sigungu: Mapped[str | None] = mapped_column(String(40))
    dong: Mapped[str | None] = mapped_column(String(40))
    jibun: Mapped[str | None] = mapped_column(String(40))
    road_address: Mapped[str | None] = mapped_column(String(200))
    households: Mapped[int | None] = mapped_column(Integer)
    approval_date: Mapped[str | None] = mapped_column(String(8))  # 사용승인일 YYYYMMDD
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class AreaType(PcBase):
    __tablename__ = "area_type"
    complex_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pyeong_no: Mapped[int] = mapped_column(Integer, primary_key=True)  # 네이버 평형 번호
    name: Mapped[str | None] = mapped_column(String(40))
    exclusive_m2: Mapped[float] = mapped_column(Float)
    supply_m2: Mapped[float | None] = mapped_column(Float)
    households: Mapped[int | None] = mapped_column(Integer)
    bucket: Mapped[str | None] = mapped_column(String(20))


class Trade(CloudBase):
    """국토부 실거래. kind: 매매 | 전세 | 월세"""
    __tablename__ = "trade"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    api: Mapped[str] = mapped_column(String(8))  # trade | rent
    sgg_cd: Mapped[str] = mapped_column(String(5))
    deal_ym: Mapped[str] = mapped_column(String(6))
    umd_nm: Mapped[str | None] = mapped_column(String(40))
    jibun: Mapped[str | None] = mapped_column(String(40))
    apt_nm: Mapped[str | None] = mapped_column(String(100))
    apt_key: Mapped[str] = mapped_column(String(160), index=True)  # aptSeq, 없으면 시군구|동|지번|단지명
    kind: Mapped[str] = mapped_column(String(4))
    contract_date: Mapped[date] = mapped_column(Date)
    exclusive_m2: Mapped[float] = mapped_column(Float)
    price: Mapped[int | None] = mapped_column(Integer)       # 매매가
    deposit: Mapped[int | None] = mapped_column(Integer)     # 보증금
    monthly_rent: Mapped[int | None] = mapped_column(Integer)
    converted: Mapped[float | None] = mapped_column(Float)   # 전세 환산가 (전세는 보증금과 같음)
    floor: Mapped[int | None] = mapped_column(Integer)
    apt_dong: Mapped[str | None] = mapped_column(String(40))
    contract_type: Mapped[str | None] = mapped_column(String(4))  # 신규 | 갱신
    canceled: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_date: Mapped[str | None] = mapped_column(String(10))

    __table_args__ = (Index("ix_trade_api_sgg_ym", "api", "sgg_cd", "deal_ym"),)


class AptMapping(CloudBase):
    """국토부 단지 키(apt_key) → 네이버 단지ID 자동 매핑 결과 (못 찾으면 complex_id NULL)"""
    __tablename__ = "apt_mapping"
    apt_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    sgg_cd: Mapped[str] = mapped_column(String(5), index=True)
    umd_nm: Mapped[str | None] = mapped_column(String(40))
    jibun: Mapped[str | None] = mapped_column(String(40))
    apt_nm: Mapped[str | None] = mapped_column(String(100))
    complex_id: Mapped[int | None] = mapped_column(Integer, index=True)
    score: Mapped[float | None] = mapped_column(Float)


class Unwatched(PcBase):
    """관심 해제한 단지. 보관 기간(config retention.unwatched_days)이 지나면 자료를 지운다.
    그 전에 다시 등록하면 고른 평형까지 그대로 되살린다."""
    __tablename__ = "unwatched"
    complex_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    areas: Mapped[str | None] = mapped_column(Text)
    removed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ManualMapping(PcBase):
    """사용자가 단지 매핑 화면에서 고친 결과. 자동 매핑보다 우선. complex_id -1 = '해당 없음'"""
    __tablename__ = "manual_mapping"
    apt_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    complex_id: Mapped[int] = mapped_column(Integer, index=True)


class MolitProgress(CloudBase):
    __tablename__ = "molit_progress"
    api: Mapped[str] = mapped_column(String(8), primary_key=True)
    sgg_cd: Mapped[str] = mapped_column(String(5), primary_key=True)
    deal_ym: Mapped[str] = mapped_column(String(6), primary_key=True)
    rows: Mapped[int] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(DateTime)


class ListingSnapshot(PcBase):
    """trade_type: 매매 | 전세 | 월세"""
    __tablename__ = "listing_snapshot"
    collect_date: Mapped[date] = mapped_column(Date, primary_key=True)
    article_no: Mapped[str] = mapped_column(String(20), primary_key=True)
    complex_id: Mapped[int] = mapped_column(Integer, index=True)
    trade_type: Mapped[str] = mapped_column(String(4))
    price: Mapped[int | None] = mapped_column(Integer)
    deposit: Mapped[int | None] = mapped_column(Integer)
    monthly_rent: Mapped[int | None] = mapped_column(Integer)
    converted: Mapped[float | None] = mapped_column(Float)
    dong: Mapped[str | None] = mapped_column(String(20))
    floor: Mapped[str | None] = mapped_column(String(20))
    direction: Mapped[str | None] = mapped_column(String(10))
    exclusive_m2: Mapped[float | None] = mapped_column(Float)
    supply_m2: Mapped[float | None] = mapped_column(Float)
    confirm_date: Mapped[str | None] = mapped_column(String(10))
    broker: Mapped[str | None] = mapped_column(String(100))
    realtor_count: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)


class NewsDaily(CloudBase):
    __tablename__ = "news_daily"
    news_date: Mapped[date] = mapped_column(Date, primary_key=True)
    rank: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str | None] = mapped_column(Text)
    article_count: Mapped[int] = mapped_column(Integer)
    source_count: Mapped[int] = mapped_column(Integer)
    urls: Mapped[str] = mapped_column(Text)  # JSON [{title, url, source}]
    method: Mapped[str] = mapped_column(String(10))  # extract | llm


class Watchlist(PcBase):
    __tablename__ = "watchlist"
    complex_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    areas: Mapped[str | None] = mapped_column(Text)  # 관심 전용면적 JSON 목록 (비우면 전체)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class _LogColumns:
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    collector: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(10))  # ok | partial | blocked | error | skipped
    count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class CollectLog(_LogColumns, PcBase):
    """PC 에서 실행한 수집 이력"""
    __tablename__ = "collect_log"


class CloudLog(_LogColumns, CloudBase):
    """클라우드(GitHub Actions)에서 실행한 수집 이력"""
    __tablename__ = "cloud_log"


DB_DIR = db_dir()
DB_DIR.mkdir(parents=True, exist_ok=True)
PC_DB = DB_DIR / "pc.db"
CLOUD_DB = DB_DIR / "cloud.db"
# 0 이면 cloud.db 를 붙이지 않는다 (PC 의 매물 수집 프로세스: 대시보드가 cloud.db 를 새 파일로 바꿀 수 있게)
ATTACH_CLOUD = os.getenv("REALESTATE_ATTACH_CLOUD", "1") != "0"


def _pragma(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA busy_timeout=30000")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    if ATTACH_CLOUD:
        cur.execute("ATTACH DATABASE ? AS cloud", (str(CLOUD_DB),))
        cur.execute("PRAGMA cloud.journal_mode=WAL")
    cur.close()


def _create(base, path):
    e = create_engine(f"sqlite:///{path}")
    base.metadata.create_all(e)
    e.dispose()


_create(PcBase, PC_DB)
_create(CloudBase, CLOUD_DB)

engine = create_engine(f"sqlite:///{PC_DB}", future=True)
event.listen(engine, "connect", _pragma)
Session = sessionmaker(engine, expire_on_commit=False)


def log_collect(collector: str, status: str, count: int = 0, error: str | None = None):
    model = CloudLog if on_cloud() else CollectLog
    with Session.begin() as s:
        s.add(model(collector=collector, status=status, count=count, error=error))
