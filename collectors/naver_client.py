"""네이버페이 부동산(fin.land.naver.com) 비공식 front-api 공통 클라이언트.

수집 원칙: 동시 요청 없음, 요청 사이 무작위 대기, 429/403 이면 즉시 중단(Blocked).
"""
import logging
import random
import time

import httpx

from settings import config

log = logging.getLogger(__name__)

BASE = "https://fin.land.naver.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")


class Blocked(Exception):
    """네이버가 요청을 막았다 (HTTP 429/403). 이번 실행은 중단하고 다음 실행 때 다시 시도한다."""


class NaverClient:
    def __init__(self, delay: tuple[float, float] | None = None):
        cfg = config()["naver"]
        self.delay = delay or (cfg["min_delay"], cfg["max_delay"])
        self._last = 0.0
        self.calls = 0
        self.http = httpx.Client(
            base_url=f"{BASE}/front-api/v1", timeout=20, follow_redirects=True,
            headers={"User-Agent": UA, "Accept": "application/json, text/plain, */*",
                     "Accept-Language": "ko-KR,ko;q=0.9", "Referer": f"{BASE}/"})

    def _wait(self):
        gap = random.uniform(*self.delay)
        elapsed = time.monotonic() - self._last
        if self._last and elapsed < gap:
            time.sleep(gap - elapsed)

    def request(self, method: str, path: str, **kw) -> dict:
        self._wait()
        try:
            r = self.http.request(method, path, **kw)
        finally:
            self._last = time.monotonic()
            self.calls += 1
        if r.status_code in (403, 429):
            raise Blocked(f"HTTP {r.status_code} {path}")
        r.raise_for_status()
        data = r.json()
        if not data.get("isSuccess", True):
            raise RuntimeError(f"네이버 API 실패 {path}: {data.get('detailCode')} {data.get('message')}")
        return data.get("result")

    def get(self, path: str, **params) -> dict:
        return self.request("GET", path, params=params)

    def post(self, path: str, body: dict) -> dict:
        return self.request("POST", path, json=body)

    def close(self):
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
