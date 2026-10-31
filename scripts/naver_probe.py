"""클라우드(GitHub Actions)에서 네이버 매물 API 가 막히는지 확인하는 시험 (요청 4회).

python scripts/naver_probe.py
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors.naver_client import Blocked, NaverClient  # noqa: E402

TESTS = [
    ("단지 검색", "GET", "/search/autocomplete/complexes", {"keyword": "래미안대치팰리스", "size": 5}),
    ("단지 정보", "GET", "/complex", {"complexNumber": 180280}),
    ("평형 목록", "GET", "/complex/pyeongList", {"complexNumber": 180280}),
    ("매물 목록", "POST", "/complex/article/list", {"size": 30, "complexNumber": "180280", "tradeTypes": ["A1"],
                                                "userChannelType": "PC", "lastInfo": []}),
]


def main() -> int:
    ok = 0
    with NaverClient(delay=(3.0, 4.0)) as c:
        for name, method, path, payload in TESTS:
            try:
                if method == "GET":
                    res = c.get(path, **payload)
                else:
                    res = c.post(path, payload)
                size = len(res) if isinstance(res, list) else len((res or {}).get("list", [])) or 1
                print(f"[통과] {name}: 결과 {size}건")
                ok += 1
            except Blocked as e:
                print(f"[차단] {name}: {e}")
                break
            except Exception as e:  # noqa: BLE001
                print(f"[실패] {name}: {e}")
    print(f"결과: {ok}/{len(TESTS)} 통과")
    return 0 if ok == len(TESTS) else 1


if __name__ == "__main__":
    sys.exit(main())
