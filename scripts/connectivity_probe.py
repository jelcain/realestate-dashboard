"""클라우드에서 각 수집처에 접속되는지 확인 (각 1회 요청)."""
import sys

import httpx

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")
TARGETS = [
    ("네이버 메인", "https://www.naver.com/"),
    ("네이버페이 부동산", "https://fin.land.naver.com/"),
    ("국토부 실거래 API", "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"),
    ("Google 뉴스 RSS", "https://news.google.com/rss/search?q=%EB%B6%80%EB%8F%99%EC%82%B0&hl=ko&gl=KR&ceid=KR:ko"),
    ("매일경제 RSS", "https://www.mk.co.kr/rss/50300009/"),
    ("한국경제 RSS", "https://www.hankyung.com/feed/realestate"),
    ("네이버 MYBOX API", "https://open-api.mybox.naver.com/v1"),
]

with httpx.Client(headers={"User-Agent": UA}, timeout=15, follow_redirects=True) as c:
    for name, url in TARGETS:
        try:
            r = c.get(url)
            print(f"[접속] {name}: HTTP {r.status_code}")
        except Exception as e:  # noqa: BLE001
            print(f"[불가] {name}: {type(e).__name__} {e}")
sys.exit(0)
