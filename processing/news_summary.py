"""일일 뉴스 요약: 정제 → 이슈 묶기(TF-IDF + 군집) → 순위(동시 보도 수) → 발췌 요약(TextRank).

선택 옵션: config news.llm.enabled 이면 로컬 LLM(Ollama)으로 문장 요약을 만들고, 실패하면 발췌 요약을 쓴다.
"""
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from functools import lru_cache
import json
import logging
import os
import re

import httpx
import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import delete

from db.models import NewsDaily, Session, log_collect
from settings import config

log = logging.getLogger(__name__)

LINKS_KEPT = 10  # 이슈마다 저장할 원문 링크 수 (화면에는 5개)


@lru_cache
def _kiwi():
    from kiwipiepy import Kiwi
    return Kiwi()


def tokens(text: str) -> list[str]:
    return [t.form for t in _kiwi().tokenize(text)
            if t.tag in ("NNG", "NNP", "SL", "SH") and len(t.form) > 1]


def _norm_title(t: str) -> str:
    return re.sub(r"[\W_]+", "", re.sub(r"\[.*?\]|\(.*?\)", "", t))


def refine(articles: list[dict]) -> list[dict]:
    """같은 기사 제거(URL·제목 유사도), 광고성·무관 기사 제거"""
    cfg = config()["news"]
    out, seen_urls = [], set()
    for a in articles:
        if a["url"] in seen_urls or any(w in a["title"] for w in cfg["ad_words"]):
            continue
        if not any(w in a["title"] + a["summary"] for w in cfg["relevance_words"]):
            continue
        nt = _norm_title(a["title"])
        dup = next((b for b in out if SequenceMatcher(None, nt, _norm_title(b["title"])).ratio() > 0.9), None)
        if dup:
            # 같은 기사: 요약문이 있는 쪽을 남긴다
            if not dup["summary"] and a["summary"]:
                dup["summary"] = a["summary"]
            dup.setdefault("dup_sources", set()).add(a["source"])
            continue
        seen_urls.add(a["url"])
        out.append(dict(a))
    return out


def cluster(articles: list[dict]) -> list[list[int]]:
    if len(articles) < 2:
        return [[i] for i in range(len(articles))]
    docs = [f"{a['title']} {a['title']} {a['summary'][:300]}" for a in articles]
    vec = TfidfVectorizer(tokenizer=tokens, lowercase=False, token_pattern=None, min_df=1)
    X = vec.fit_transform(docs)
    keep = np.asarray(X.sum(axis=1)).ravel() > 0
    labels = np.full(len(articles), -1)
    if keep.sum() >= 2:
        model = AgglomerativeClustering(n_clusters=None, metric="cosine", linkage="average",
                                        distance_threshold=config()["news"]["cluster_distance"])
        labels[keep] = model.fit_predict(X[keep].toarray())
    groups: dict[int, list[int]] = {}
    nxt = labels.max() + 1
    for i, lb in enumerate(labels):
        if lb < 0:
            lb, nxt = nxt, nxt + 1
        groups.setdefault(int(lb), []).append(i)
    return list(groups.values())


def split_sentences(text: str) -> list[str]:
    try:
        sents = [s.text.strip() for s in _kiwi().split_into_sents(text)]
    except Exception:  # noqa: BLE001
        sents = re.split(r"(?<=다\.)\s+", text)
    return [s for s in sents if 15 <= len(s) <= 200]


def textrank(sentences: list[str], k: int = 3) -> list[str]:
    if len(sentences) <= k:
        return sentences
    try:
        X = TfidfVectorizer(tokenizer=tokens, lowercase=False, token_pattern=None).fit_transform(sentences)
    except ValueError:
        return sentences[:k]
    sim = cosine_similarity(X)
    np.fill_diagonal(sim, 0)
    row = sim.sum(axis=1, keepdims=True)
    row[row == 0] = 1
    M = sim / row
    score = np.ones(len(sentences)) / len(sentences)
    for _ in range(50):
        score = 0.15 / len(sentences) + 0.85 * M.T @ score
    top = sorted(np.argsort(-score)[:k])
    return [sentences[i] for i in top]


def _sources(a: dict) -> set[str]:
    return {a["source"]} | a.get("dup_sources", set())


def summarize_group(arts: list[dict]) -> dict:
    titles = [a["title"] for a in arts]
    # 대표 제목: 다른 제목들과 가장 많이 겹치는 제목
    if len(arts) > 2:
        X = TfidfVectorizer(tokenizer=tokens, lowercase=False, token_pattern=None).fit_transform(titles)
        rep = int(cosine_similarity(X).sum(axis=1).argmax())
    else:
        rep = 0
    sents = []
    for a in arts:
        for s in split_sentences(a["summary"]):
            if s not in sents:
                sents.append(s)
    key = textrank(sents, 3)
    if not key:  # 요약문이 없으면 다른 언론사 제목으로 대신한다
        key = [t for i, t in enumerate(titles) if i != rep][:3]
    return {"title": titles[rep], "sentences": key,
            "links": [{"title": a["title"], "url": a["url"], "source": a["source"]} for a in arts]}


def llm_summary(group: dict) -> str | None:
    cfg = config()["news"]["llm"]
    if not cfg.get("enabled"):
        return None
    prompt = ("다음은 같은 부동산 이슈를 다룬 기사 제목과 발췌문이다. 핵심을 한국어 2~3문장으로 요약하라. "
              "기사에 없는 내용은 쓰지 마라.\n\n"
              + "\n".join(f"- {l['title']}" for l in group["links"][:10])
              + "\n\n" + "\n".join(group["sentences"]))
    try:
        r = httpx.post(cfg["url"], json={"model": cfg["model"], "prompt": prompt, "stream": False}, timeout=120)
        r.raise_for_status()
        return r.json().get("response", "").strip() or None
    except Exception as e:  # noqa: BLE001 - 실패하면 발췌 요약으로 대체
        log.warning("로컬 LLM 요약 실패, 발췌 요약 사용: %s", e)
        return None


def build(articles: list[dict]) -> list[dict]:
    arts = refine(articles)
    groups = cluster(arts)
    groups.sort(key=lambda g: (-len(set().union(*(_sources(arts[i]) for i in g))), -len(g)))
    out = []
    for g in groups[: config()["news"]["max_items"]]:
        members = [arts[i] for i in g]
        s = summarize_group(members)
        s["article_count"] = len(members) + sum(len(a.get("dup_sources", ())) for a in members)
        s["source_count"] = len(set().union(*(_sources(a) for a in members)))
        llm = llm_summary(s)
        s["summary"], s["method"] = (llm, "llm") if llm else ("\n".join(s["sentences"]), "extract")
        out.append(s)
    return out


def run() -> int:
    """한 회차 수집. 회차 = 수집 시각의 '시' (05·11·17시 예약, 수동 수집은 그때 시각).
    같은 날 같은 회차를 다시 수집하면 덮어쓰고, 보관 기간(news.keep_days)이 지난 뉴스는 지운다."""
    from collectors.news_rss import collect

    now = datetime.now()
    # 예약 실행은 GitHub 이 늦게 시작해도 예약 시각(5·11·17)으로 저장한다 (daily.yml 이 NEWS_EDITION 지정)
    edition = int(os.getenv("NEWS_EDITION") or now.hour)
    try:
        items = build(collect())
        with Session.begin() as s:
            s.execute(delete(NewsDaily).where(NewsDaily.news_date == now.date(), NewsDaily.edition == edition))
            for rank, it in enumerate(items, 1):
                s.add(NewsDaily(news_date=now.date(), edition=edition, rank=rank, collected_at=now,
                                title=it["title"], summary=it["summary"],
                                article_count=it["article_count"], source_count=it["source_count"],
                                urls=json.dumps(it["links"][:LINKS_KEPT], ensure_ascii=False), method=it["method"]))
            keep = int(config()["news"].get("keep_days", 365))
            if keep > 0:
                old = s.execute(delete(NewsDaily).where(NewsDaily.news_date < now.date() - timedelta(days=keep)))
                if old.rowcount:
                    log.info("보관 기간(%d일) 지난 뉴스 %d건 삭제", keep, old.rowcount)
        log_collect("news", "ok", len(items))
        return len(items)
    except Exception as e:  # noqa: BLE001
        log.exception("뉴스 요약 오류")
        log_collect("news", "error", 0, str(e))
        return 0
