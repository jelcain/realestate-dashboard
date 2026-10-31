"""SQLite 스키마 (SQLAlchemy). 금액 단위는 모두 만원."""
from datetime import date, datetime

from sqlalchemy import (Boolean, Date, DateTime, Float, Integer, String, Text,
                        create_engine, event, Index)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from settings import db_path


class Base(DeclarativeBase):
    pass


class Region(Base):
    """법정동 계층. level: 1=시도, 2=시군구, 3=읍면동"""
    __tablename__ = "region"
    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    sido: Mapped[str] = mapped_column(String(40))
    sigungu: Mapped[str | None] = mapped_column(String(40))
    dong: Mapped[str | None] = mapped_column(String(40))
    level: Mapped[int] = mapped_column(Integer)
    parent: Mapped[str | None] = mapped_column(String(10), index=True)


class Complex(Base):
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


class AreaType(Base):
    __tablename__ = "area_type"
    complex_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pyeong_no: Mapped[int] = mapped_column(Integer, primary_key=True)  # 네이버 평형 번호
    name: Mapped[str | None] = mapped_column(String(40))
    exclusive_m2: Mapped[float] = mapped_column(Float)
    supply_m2: Mapped[float | None] = mapped_column(Float)
    households: Mapped[int | None] = mapped_column(Integer)
    bucket: Mapped[str | None] = mapped_column(String(20))


class Trade(Base):
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
    complex_id: Mapped[int | None] = mapped_column(Integer, index=True)
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


class AptMapping(Base):
    """국토부 단지 키(apt_key) → 네이버 단지ID. complex_id 가 -1 이면 '해당 없음'으로 확정."""
    __tablename__ = "apt_mapping"
    apt_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    sgg_cd: Mapped[str] = mapped_column(String(5), index=True)
    umd_nm: Mapped[str | None] = mapped_column(String(40))
    jibun: Mapped[str | None] = mapped_column(String(40))
    apt_nm: Mapped[str | None] = mapped_column(String(100))
    complex_id: Mapped[int | None] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(10))  # auto | manual
    score: Mapped[float | None] = mapped_column(Float)


class MolitProgress(Base):
    __tablename__ = "molit_progress"
    api: Mapped[str] = mapped_column(String(8), primary_key=True)
    sgg_cd: Mapped[str] = mapped_column(String(5), primary_key=True)
    deal_ym: Mapped[str] = mapped_column(String(6), primary_key=True)
    rows: Mapped[int] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(DateTime)


class ListingSnapshot(Base):
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


class NewsDaily(Base):
    __tablename__ = "news_daily"
    news_date: Mapped[date] = mapped_column(Date, primary_key=True)
    rank: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str | None] = mapped_column(Text)
    article_count: Mapped[int] = mapped_column(Integer)
    source_count: Mapped[int] = mapped_column(Integer)
    urls: Mapped[str] = mapped_column(Text)  # JSON [{title, url, source}]
    method: Mapped[str] = mapped_column(String(10))  # extract | llm


class Watchlist(Base):
    __tablename__ = "watchlist"
    complex_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    areas: Mapped[str | None] = mapped_column(Text)  # 관심 전용면적 JSON 목록 (비우면 전체)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class CollectLog(Base):
    __tablename__ = "collect_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    collector: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(10))  # ok | partial | blocked | error | skipped
    count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


_path = db_path()
_path.parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(f"sqlite:///{_path}", future=True)


@event.listens_for(engine, "connect")
def _sqlite_pragma(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


Session = sessionmaker(engine, expire_on_commit=False)
Base.metadata.create_all(engine)


def log_collect(collector: str, status: str, count: int = 0, error: str | None = None):
    with Session.begin() as s:
        s.add(CollectLog(collector=collector, status=status, count=count, error=error))
