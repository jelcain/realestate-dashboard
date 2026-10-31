"""국토부 실거래 단지(apt_key) ↔ 네이버 단지ID 매핑.

자동 매핑: 같은 시군구·같은 동 안에서 지번 일치 + 단지명 유사도로 점수를 매겨 기준 이상이면 연결한다.
자동으로 못 찾은 단지는 수동 매핑 화면에서 처리한다 (method='manual' 은 자동 매핑이 덮어쓰지 않는다).
"""
from difflib import SequenceMatcher
import re

from sqlalchemy import select, text, update

from db.models import AptMapping, Complex, Session

AUTO_THRESHOLD = 0.75


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
    """새 apt_key 등록 → 미확정 건 자동 매핑 → trade.complex_id 반영"""
    with Session.begin() as s:
        s.execute(text("""
            INSERT OR IGNORE INTO apt_mapping (apt_key, sgg_cd, umd_nm, jibun, apt_nm, complex_id, method, score)
            SELECT apt_key, sgg_cd, umd_nm, jibun, apt_nm, NULL, 'auto', NULL
            FROM trade GROUP BY apt_key
        """))
        complexes = list(s.scalars(select(Complex)))
        by_sgg: dict[str, list[Complex]] = {}
        for cx in complexes:
            by_sgg.setdefault((cx.legal_code or "")[:5], []).append(cx)
        pending = s.scalars(select(AptMapping).where(AptMapping.method == "auto",
                                                     AptMapping.complex_id.is_(None)))
        for m in pending:
            cands = by_sgg.get(m.sgg_cd)
            if not cands:
                continue
            cid, sc = best_match({"umd_nm": m.umd_nm, "jibun": m.jibun, "apt_nm": m.apt_nm}, cands)
            m.complex_id, m.score = cid, round(sc, 3)
        s.execute(text("""
            UPDATE trade SET complex_id = (
                SELECT CASE WHEN m.complex_id > 0 THEN m.complex_id END
                FROM apt_mapping m WHERE m.apt_key = trade.apt_key)
        """))


def set_manual(apt_key: str, complex_id: int | None):
    """complex_id: 네이버 단지ID, -1 = 해당 없음, None = 자동 매핑으로 되돌림"""
    with Session.begin() as s:
        m = s.get(AptMapping, apt_key)
        if m is None:
            return
        if complex_id is None:
            m.method, m.complex_id, m.score = "auto", None, None
        else:
            m.method, m.complex_id = "manual", complex_id
    apply_mappings()


def reset_auto_for_complex_area():
    """새 관심 단지가 추가되면 자동 매핑 결과를 다시 계산하도록 미매핑 상태로 되돌린다."""
    with Session.begin() as s:
        s.execute(update(AptMapping).where(AptMapping.method == "auto").values(complex_id=None, score=None))
    apply_mappings()
