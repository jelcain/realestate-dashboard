"""시스템 점검: 키·토큰, 수집처 접속, 클라우드, 자동 수집, 저장 공간을 한 번에 확인한다.

python scripts/check_health.py   (또는 '점검 실행.bat')
요청은 수집처마다 1회씩만 보낸다.
"""
from datetime import date, datetime, timedelta
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from settings import cloud_mode, config, molit_key, mybox_token  # noqa: E402

problems: list[str] = []


def ok(msg):
    print(f"  [정상] {msg}")


def warn(msg):
    print(f"  [주의] {msg}")
    problems.append(msg)


def bad(msg):
    print(f"  [문제] {msg}")
    problems.append(msg)


def section(title):
    print(f"\n■ {title}")


def _kst(iso: str) -> str:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")


def check_keys():
    section("키·토큰 (.env)")
    ok("국토부 키 있음") if molit_key("trade") else bad("국토부 키(MOLIT_SERVICE_KEY)가 없습니다")
    if not mybox_token():
        warn("MYBOX_TOKEN 이 없어 로컬 모드입니다 (PC 가 꺼져 있으면 수집 안 됨)")
        return
    ok("MYBOX 토큰 있음 → 클라우드 분담 모드")
    exp = os.getenv("MYBOX_TOKEN_EXPIRES", "").strip()
    if not exp:
        warn("MYBOX_TOKEN_EXPIRES(토큰 만료일)가 비어 있어 만료를 미리 알릴 수 없습니다 → '토큰·키 갱신 안내서' 참고")
        return
    try:
        left = (date.fromisoformat(exp) - date.today()).days
    except ValueError:
        warn(f"MYBOX_TOKEN_EXPIRES 형식이 틀렸습니다 (예: 2027-04-30): {exp}")
        return
    if left < 0:
        bad(f"MYBOX 토큰이 만료되었습니다 ({exp}). 새로 발급해 .env 와 GitHub 시크릿을 바꾸세요")
    elif left <= 14:
        warn(f"MYBOX 토큰 만료 {left}일 전 ({exp}). 미리 새로 발급하세요")
    else:
        ok(f"MYBOX 토큰 만료까지 {left}일 ({exp})")


def check_molit():
    section("국토부 실거래 API")
    import httpx
    from collectors.molit_trade import APIS
    try:
        ym = (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y%m")
        r = httpx.get(APIS["trade"], params={"serviceKey": molit_key("trade"), "LAWD_CD": "11680", "DEAL_YMD": ym,
                                             "pageNo": 1, "numOfRows": 1}, timeout=30)
        code = r.text.split("<resultCode>")[1].split("<")[0] if "<resultCode>" in r.text else r.text[:120]
        ok("응답 정상") if code in ("000", "00") else bad(f"응답 이상: {code}")
    except Exception as e:  # noqa: BLE001
        bad(f"접속 실패: {e}")


def check_naver():
    section("네이버페이 부동산 (매물)")
    from collectors import naver_complex
    from collectors.naver_client import Blocked, NaverClient
    try:
        with NaverClient(delay=(0, 0)) as c:
            naver_complex.search(c, "래미안", size=1)
        ok("접속 정상")
    except Blocked as e:
        warn(f"일시 차단 중 ({e}). 보통 몇 분~몇 시간 뒤 풀립니다")
    except Exception as e:  # noqa: BLE001
        bad(f"접속 실패 (네이버 API 구조가 바뀌었을 수 있음): {e}")


def check_mybox():
    if not cloud_mode():
        return
    section("MYBOX")
    from storage import sync
    try:
        for name in ("pc", "cloud"):
            info = sync.remote_info(name)
            if not info:
                bad(f"{name}.db.gz 가 MYBOX 에 없습니다")
                continue
            age = datetime.now().astimezone() - datetime.fromisoformat(info["modified"])
            msg = f"{name}.db.gz {info['size'] / 1e6:.1f}MB, 마지막 갱신 {info['modified'][:16].replace('T', ' ')}"
            (warn if age > timedelta(days=2) else ok)(msg + (" (2일 넘게 갱신 안 됨)" if age > timedelta(days=2) else ""))
    except Exception as e:  # noqa: BLE001
        bad(f"접속 실패 (토큰 만료 가능성): {e}")


def check_github():
    if not cloud_mode():
        return
    section("GitHub 클라우드 수집")
    from storage import cloud_run
    try:
        out = cloud_run._run(["secret", "list"])
        names = {line.split()[0] for line in out.splitlines() if line.strip()}
        for s in ("MYBOX_TOKEN", "MOLIT_SERVICE_KEY"):
            ok(f"시크릿 {s} 있음") if s in names else bad(f"시크릿 {s} 가 없습니다")
        runs = cloud_run.recent_runs(10)
        sched = [r for r in runs if r["event"] == "schedule"]
        last = runs[0] if runs else None
        if not last:
            warn("아직 실행 기록이 없습니다")
        elif last.get("conclusion") == "failure":
            bad(f"최근 실행 실패: {_kst(last['createdAt'])} {last['url']}")
        else:
            ok(f"최근 실행: {_kst(last['createdAt'])} {last.get('conclusion') or last['status']}")
        if sched:
            s = sched[0]
            age = datetime.now().astimezone() - datetime.fromisoformat(s["createdAt"].replace("Z", "+00:00"))
            (ok if age < timedelta(days=2) else bad)(f"최근 예약 실행(매일 05:00): {_kst(s['createdAt'])} "
                                                     f"{s.get('conclusion') or s['status']}")
        else:
            print("  [참고] 예약(매일 05:00) 실행 기록이 아직 없습니다 (설정 다음 날부터 생깁니다)")
        state = cloud_run.workflow_state()
        ok("예약 실행 켜져 있음") if state == "active" else bad(f"예약 실행이 꺼져 있습니다 ({state}) → 관리 안내서 참고")
    except Exception as e:  # noqa: BLE001
        bad(f"GitHub 확인 실패 (gh 로그인 필요할 수 있음): {e}")


def check_task():
    section("PC 매물 자동 수집 (작업 스케줄러)")
    if os.name != "nt":
        return
    ps = ("$t=Get-ScheduledTask -TaskName RealEstateListing -ErrorAction SilentlyContinue; if(-not $t){'none'} "
          "else {$i=Get-ScheduledTaskInfo -TaskName RealEstateListing; "
          "'{0}|{1}|{2}' -f $i.LastRunTime.ToString('yyyy-MM-dd HH:mm'), $i.LastTaskResult, "
          "$i.NextRunTime.ToString('yyyy-MM-dd HH:mm')}")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=0x08000000)
    out = r.stdout.strip()
    if out == "none" or not out:
        bad("등록되어 있지 않습니다 → register_task.ps1 실행")
        return
    last, result, nxt = out.split("|")
    (ok if result in ("0", "267011") else warn)(f"등록됨. 마지막 실행 {last} (결과 {result}), 다음 실행 {nxt}")


def check_data():
    section("수집 상태와 저장 공간")
    from sqlalchemy import text
    from db.models import CLOUD_DB, PC_DB, engine
    with engine.connect() as c:
        last = c.execute(text("SELECT MAX(run_at) FROM collect_log WHERE collector='naver_listing' "
                              "AND status='ok'")).scalar()
        news = c.execute(text("SELECT MAX(news_date) FROM news_daily")).scalar()
        n_watch = c.execute(text("SELECT COUNT(*) FROM watchlist")).scalar()
    if last and datetime.fromisoformat(str(last)) > datetime.now() - timedelta(days=2):
        ok(f"마지막 전체 매물 수집: {str(last)[:16]}")
    else:
        warn(f"전체 매물 수집이 2일 넘게 없습니다 (마지막 {str(last)[:16] if last else '-'})")
    if news and date.fromisoformat(str(news)) >= date.today() - timedelta(days=1):
        ok(f"마지막 뉴스: {news}")
    else:
        warn(f"뉴스가 최근에 갱신되지 않았습니다 (마지막 {news or '-'})")
    ok(f"관심 단지 {n_watch}개 (권장 100개 이내)") if n_watch <= 100 else warn(f"관심 단지 {n_watch}개 (100개 초과)")
    for p in (PC_DB, CLOUD_DB):
        mb = p.stat().st_size / 1e6 if p.exists() else 0
        (ok if mb < 1000 else warn)(f"{p.name} {mb:.0f}MB")
    bak = list(PC_DB.parent.glob("*.bak"))
    if bak:
        print(f"  [참고] 백업 파일 {', '.join(b.name for b in bak)} — 문제없으면 지워도 됩니다")


def main():
    print(f"부동산 정보 조회 시스템 점검 ({datetime.now():%Y-%m-%d %H:%M})")
    for fn in (check_keys, check_molit, check_naver, check_mybox, check_github, check_task, check_data):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            bad(f"{fn.__name__} 점검 중 오류: {e}")
    print("\n" + ("결과: 모두 정상" if not problems else f"결과: 확인 필요 {len(problems)}건"))
    for p in problems:
        print(f"  - {p}")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
