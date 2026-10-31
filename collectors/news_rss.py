"""부동산 뉴스 수집 (RSS).

계획서의 네이버 검색 API 대신 키가 필요 없는 RSS 를 쓴다.
- Google 뉴스 RSS 키워드 검색: 여러 언론사 기사 → 이슈 순위(동시 보도 수)에 사용
- 언론사 부동산 RSS: 요약문이 있어 핵심 문장 발췌에 사용
"""
from calendar import timegm
from datetime import datetime, timedelta, timezone
import html
import logging
import re
from urllib.parse import quote

import feedparser
import httpx

from settings import config

log = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")
GOOGLE = "https://news.google.com/rss/search?q={q}+when:1d&hl=ko&gl=KR&ceid=KR:ko"


def clean(text: str | None) -> str:
    t = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def _published(e) -> datetime | None:
    t = e.get("published_parsed") or e.get("updated_parsed")
    return datetime.fromtimestamp(timegm(t), tz=timezone.utc) if t else None


def _feed_title(f) -> str:
    return clean(f.feed.get("title", "")) if f.get("feed") else ""


def parse_feed(content: bytes, google: bool) -> list[dict]:
    f = feedparser.parse(content)
    feed_source = _feed_title(f)
    out = []
    for e in f.entries:
        title, source = clean(e.get("title")), feed_source
        summary = clean(e.get("summary"))
        if google:
            src = e.get("source") or {}
            source = src.get("title") or source
            # Google 뉴스 제목은 '제목 - 언론사' 형식
            if source and title.endswith(f" - {source}"):
                title = title[: -len(source) - 3].strip()
            summary = ""  # Google 뉴스 요약은 링크 HTML 이라 쓰지 않는다
        out.append({"title": title, "url": e.get("link"), "source": source, "summary": summary,
                    "published": _published(e)})
    return out


def collect(hours: int = 24) -> list[dict]:
    cfg = config()["news"]
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    urls = [(GOOGLE.format(q=quote(k)), True) for k in cfg["keywords"]] + [(u, False) for u in cfg["feeds"]]
    articles = []
    with httpx.Client(headers={"User-Agent": UA}, timeout=20, follow_redirects=True) as c:
        for url, google in urls:
            try:
                r = c.get(url)
                r.raise_for_status()
                items = parse_feed(r.content, google)
            except Exception as e:  # noqa: BLE001 - 피드 하나 실패는 건너뛴다
                log.warning("뉴스 피드 실패 %s: %s", url, e)
                continue
            articles += [a for a in items if a["title"] and (a["published"] is None or a["published"] >= since)]
    log.info("뉴스 수집 %d건", len(articles))
    return articles
