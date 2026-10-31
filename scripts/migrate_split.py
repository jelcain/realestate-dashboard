"""기존 db/realestate.db 를 pc.db + cloud.db 로 나눈다 (한 번만 실행).

python scripts/migrate_split.py
끝나면 원본은 db/realestate.db.bak 으로 이름을 바꿔 둔다.
"""
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.models import CLOUD_DB, PC_DB, engine  # noqa: E402  (빈 새 DB 생성)

OLD = PC_DB.parent / "realestate.db"
PC_TABLES = ["region", "complex", "area_type", "watchlist", "listing_snapshot", "collect_log"]
CLOUD_TABLES = ["trade", "molit_progress", "news_daily"]


def cols(con, schema: str, table: str) -> list[str]:
    return [r[1] for r in con.execute(f"PRAGMA {schema}.table_info({table})")]


def main():
    if not OLD.exists():
        print("옮길 db/realestate.db 가 없습니다.")
        return
    engine.dispose()
    con = sqlite3.connect(PC_DB)
    con.execute("ATTACH DATABASE ? AS cloud", (str(CLOUD_DB),))
    con.execute("ATTACH DATABASE ? AS old", (str(OLD),))
    if con.execute("SELECT COUNT(*) FROM main.watchlist").fetchone()[0]:
        print("pc.db 에 이미 자료가 있어 중단합니다.")
        return
    for schema, tables in (("main", PC_TABLES), ("cloud", CLOUD_TABLES)):
        for t in tables:
            common = [c for c in cols(con, schema, t) if c in cols(con, "old", t)]
            cl = ", ".join(common)
            n = con.execute(f"INSERT INTO {schema}.{t} ({cl}) SELECT {cl} FROM old.{t}").rowcount
            print(f"{schema}.{t}: {n:,}행")
    # 매핑: 자동 결과는 cloud.apt_mapping, 사용자가 고친 결과는 pc.manual_mapping
    con.execute("""INSERT INTO cloud.apt_mapping (apt_key, sgg_cd, umd_nm, jibun, apt_nm, complex_id, score)
                   SELECT apt_key, sgg_cd, umd_nm, jibun, apt_nm,
                          CASE WHEN method = 'auto' THEN complex_id END, score FROM old.apt_mapping""")
    n = con.execute("""INSERT INTO main.manual_mapping (apt_key, complex_id)
                       SELECT apt_key, complex_id FROM old.apt_mapping
                       WHERE method = 'manual' AND complex_id IS NOT NULL""").rowcount
    print(f"수동 매핑: {n}건")
    con.commit()
    con.execute("DETACH DATABASE old")
    con.close()
    OLD.rename(OLD.with_suffix(".db.bak"))
    for suffix in ("-wal", "-shm"):
        p = Path(str(OLD) + suffix)
        if p.exists():
            p.unlink()
    print("완료: 원본은 db/realestate.db.bak")


if __name__ == "__main__":
    main()
