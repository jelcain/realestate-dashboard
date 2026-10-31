"""국토부 실거래 단지(apt_key) ↔ 네이버 단지ID 매핑.

자동 매핑(cloud.db apt_mapping): 같은 시군구·같은 동 안에서 지번 일치 + 단지명 유사도로 점수를 매겨
기준 이상이면 연결한다. 실거래를 수집하는 쪽(클라우드, 로컬 모드에선 PC)이 계산한다.
수동 매핑(pc.db manual_mapping): 단지 매핑 화면에서 사용자가 고친 결과. 자동 매핑보다 우선한다.
화면은 EFFECTIVE_SQL 로 둘을 합쳐 쓴다.
"""
from difflib import SequenceMatcher
import re

from sqlalchemy import delete, select, text

from db.models import AptMapping, Complex, ManualMapping, Session

AUTO_THRESHOLD = 0.75

# apt_key → 최종 단지ID (수동 우선, -1 은 '해당 없음')
EFFECTIVE_SQL = """
    SELECT m.apt_key, COALESCE(mm.complex_id, m.complex_id) AS complex_id
    FROM apt_mapping m LEFT JOIN manual_mapping mm ON mm.apt_key = m.apt_key
"""


def norm_name(name: str | None) -> str:
    n = name or ""
    n = re.sub(r"\(.*?\)", "", n)
    n = re.sub(r"아파트|단지|APT|apt|\s", "", n)
    return n.lower()


def norm_jibun(j: str | None) -> tuple[str, str]:
    j = (j or "").replace("산", "").strip()
    main, _, sub = j.partition("-")
    return main.lstrip("0"), sub.lstrip("0")


def score(apt: dict, cx: Complex) -> float:
    if (apt["umd_nm"] or "") != (cx.dong or ""):
        return 0.0
    name_sim = SequenceMatcher(None, norm_name(apt["apt_nm"]), norm_name(cx.name)).ratio()
    a_main, a_sub = norm_jibun(apt["jibun"])
    c_main, c_sub = norm_jibun(cx.jibun)
    if a_main and a_main == c_main and a_sub == c_sub:
        return 0.6 + 0.4 * name_sim
    if a_main and a_main == c_main:
        return 0.45 + 0.4 * name_sim
    return 0.8 * name_sim


def best_match(apt: dict, complexes: list[Complex]) -> tuple[int | None, float]:
    best, best_score = None, 0.0
    for cx in complexes:
        sc = score(apt, cx)
        if sc > best_score:
            best, best_score = cx.complex_id, sc
    return (best if best_score >= AUTO_THRESHOLD else None), best_score


def apply_mappings():
    """새 apt_key 등록 → 아직 못 찾은 건 자동 매핑 (새로 등록된 관심 단지가 있으면 그때 연결된다)"""
    with Session.begin() as s:
        s.execute(text("""
            INSERT OR IGNORE INTO apt_mapping (apt_key, sgg_cd, umd_nm, jibun, apt_nm, complex_id, score)
            SELECT apt_key, sgg_cd, umd_nm, jibun, apt_nm, NULL, NULL FROM trade GROUP BY apt_key
        """))
        by_sgg: dict[str, list[Complex]] = {}
        for cx in s.scalars(select(Complex)):
            by_sgg.setdefault((cx.legal_code or "")[:5], []).append(cx)
        for m in s.scalars(select(AptMapping).where(AptMapping.complex_id.is_(None))):
            cands = by_sgg.get(m.sgg_cd)
            if cands:
                cid, sc = best_match({"umd_nm": m.umd_nm, "jibun": m.jibun, "apt_nm": m.apt_nm}, cands)
                m.complex_id, m.score = cid, round(sc, 3)


def set_manual(apt_key: str, complex_id: int | None):
    """complex_id: 네이버 단지ID, -1 = 해당 없음, None = 자동 매핑으로 되돌림"""
    with Session.begin() as s:
        if complex_id is None:
            s.execute(delete(ManualMapping).where(ManualMapping.apt_key == apt_key))
        else:
            s.merge(ManualMapping(apt_key=apt_key, complex_id=complex_id))
