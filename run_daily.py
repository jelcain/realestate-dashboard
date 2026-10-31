"""수집 배치 진입점.

실행 위치에 따라 맡는 일이 다르다.
  - 클라우드(GitHub Actions): 실거래·뉴스. 시작할 때 MYBOX 에서 pc.db·cloud.db 를 받고, 끝나면 cloud.db 를 올린다.
  - PC + MYBOX_TOKEN 있음(분담 모드): 단지 정보·매물. 끝나면 pc.db 를 올린다.
    실거래·뉴스를 요청하면 pc.db 를 먼저 올린 뒤 클라우드 수집을 실행시킨다.
  - PC + 토큰 없음(로컬 모드): 전부 PC 에서.

사용법:
  python run_daily.py                    # 전체 (단지 정보 → 실거래 → 매물 → 뉴스)
  python run_daily.py --only news        # 일부만: complex, trade, listing, news (여러 개는 쉼표)
  python run_daily.py --complex 236      # 특정 단지만 (단지 정보 강제 갱신 + 그 시군구 실거래 + 매물)
"""
import argparse
import ctypes
from datetime import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import subprocess
import sys

from settings import ROOT, cloud_mode, on_cloud

STEPS = ["complex", "trade", "listing", "news"]
CLOUD_STEPS = {"trade", "news"}   # 클라우드 분담 모드에서 클라우드가 맡는 일
PC_STEPS = {"complex", "listing"}  # 네이버페이 부동산은 해외 IP 를 막아서 PC 가 맡는다
LOCK = ROOT / "logs" / "run_daily.lock"
LOG = ROOT / "logs" / "run_daily.log"


def setup_logging():
    LOG.parent.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = RotatingFileHandler(LOG, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[fh, sh])
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _pid_alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    k.GetExitCodeProcess(h, ctypes.byref(code))
    k.CloseHandle(h)
    return code.value == 259  # STILL_ACTIVE


def running() -> dict | None:
    """실행 중인 수집 정보 {pid, started, args}. 없으면 None"""
    try:
        info = json.loads(LOCK.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return info if _pid_alive(info.get("pid", 0)) else None


def start_background(args: list[str]) -> bool:
    """대시보드에서 수집을 백그라운드로 시작. 이미 실행 중이면 False"""
    if running():
        return False
    flags = 0x08000000 | 0x00000200 if os.name == "nt" else 0  # CREATE_NO_WINDOW | NEW_PROCESS_GROUP
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    subprocess.Popen([sys.executable, str(ROOT / "run_daily.py"), *args], cwd=ROOT, env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    return True


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--only", help="쉼표로 구분: " + ",".join(STEPS))
    p.add_argument("--complex", help="네이버 단지번호 (쉼표로 여러 개)")
    p.add_argument("--auto", action="store_true",
                   help="작업 스케줄러용 (20:00, 로그인 시): 오늘 전체 매물 수집에 이미 성공했으면 건너뜀")
    args = p.parse_args(argv)
    steps = [s for s in args.only.split(",") if s] if args.only else STEPS
    ids = [int(x) for x in args.complex.split(",") if x] if args.complex else None
    if ids and not args.only:
        steps = ["complex", "trade", "listing"]
    if args.auto:
        # 분담 모드면 PC 몫(단지 정보·매물)만. 실거래·뉴스는 클라우드가 매일 05:00 에 따로 한다
        steps, ids = ([s for s in STEPS if s in PC_STEPS] if cloud_mode() else STEPS), None
    setup_logging()
    log = logging.getLogger("run_daily")

    if on_cloud():
        return run_cloud([s for s in steps if s in CLOUD_STEPS], ids, log)

    other = running()
    if other:
        log.warning("이미 수집이 실행 중입니다 (pid %s, %s 시작) → 종료", other["pid"], other["started"])
        return 1
    LOCK.write_text(json.dumps({"pid": os.getpid(), "started": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                "args": sys.argv[1:] if argv is None else argv}, ensure_ascii=False),
                    encoding="utf-8")
    try:
        if cloud_mode():
            # 이 프로세스는 cloud.db 를 열지 않는다 → 대시보드가 수집 중에도 cloud.db 를 새 파일로 바꿀 수 있다
            os.environ["REALESTATE_ATTACH_CLOUD"] = "0"
        if args.auto and listing_done_today():
            log.info("자동 수집: 오늘 전체 매물 수집을 이미 마쳐서 건너뜀")
            return 0
        if cloud_mode():
            return run_pc_shared(steps, ids, log)
        log.info("수집 시작 (로컬 모드): %s%s", ",".join(steps), f" (단지 {ids})" if ids else "")
        collect(steps, ids, log)
        return 0
    finally:
        LOCK.unlink(missing_ok=True)


def listing_done_today() -> bool:
    """오늘 전체 관심 단지 매물 수집에 성공한 적이 있나 (특정 단지만 수집한 것은 제외)"""
    from sqlalchemy import func, select
    from db.models import CollectLog, Session
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    with Session() as s:
        return bool(s.scalar(select(func.count()).select_from(CollectLog).where(
            CollectLog.collector == "naver_listing", CollectLog.status == "ok", CollectLog.run_at >= today)))


def run_cloud(steps: list[str], ids: list[int] | None, log) -> int:
    """GitHub Actions: MYBOX 에서 받기 → 실거래·뉴스 → cloud.db 올리기"""
    from storage import sync
    log.info("클라우드 수집 시작: %s%s", ",".join(steps), f" (단지 {ids})" if ids else "")
    sync.pull("pc", force=True)
    sync.pull("cloud", force=True)
    collect(steps, ids, log)
    sync.push("cloud")
    return 0


def run_pc_shared(steps: list[str], ids: list[int] | None, log) -> int:
    """PC 분담 모드: 단지 정보·매물은 PC 에서, 실거래·뉴스는 클라우드에 맡긴다"""
    from storage import cloud_run, sync
    local = [s for s in steps if s in PC_STEPS]
    remote = [s for s in steps if s in CLOUD_STEPS]
    log.info("수집 시작 (분담 모드): PC=%s, 클라우드=%s%s", ",".join(local) or "-", ",".join(remote) or "-",
             f" (단지 {ids})" if ids else "")
    if "complex" in local:
        collect(["complex"], ids, log)
    if remote:
        sync.push("pc")  # 클라우드가 새 관심 단지·매핑을 알 수 있게 먼저 올린다
        cloud_run.dispatch(ids, remote)
        log.info("클라우드 수집 요청: %s", ",".join(remote))
    if "listing" in local:
        collect(["listing"], ids, log)
    if local:
        sync.push("pc")
    return 0


def collect(steps: list[str], ids: list[int] | None, log):
    from collectors.naver_client import Blocked, NaverClient

    if ids is None:  # 전체 수집 때 관심 해제 후 보관 기간이 지난 자료를 정리한다
        from processing import retention
        try:
            if "listing" in steps and not on_cloud():
                retention.cleanup_pc()
            if "trade" in steps:
                retention.cleanup_cloud()
        except Exception:  # noqa: BLE001 - 정리 실패가 수집을 막지 않게
            log.exception("자료 정리 중 오류")

    naver = NaverClient()
    blocked = False
    try:
        if "complex" in steps:
            from collectors import naver_complex
            try:
                log.info("단지 정보 갱신: %d개", naver_complex.refresh_watchlist(naver, force=bool(ids), ids=ids))
            except Blocked:
                blocked = True
                log.warning("네이버 차단 → 단지 정보·매물 수집을 다음 실행으로 미룸")
        if "trade" in steps:
            from collectors import molit_trade
            sggs = molit_trade.sggs_of(ids) if ids else None
            log.info("실거래 수집: %d건", molit_trade.run(sggs))
        if "listing" in steps and not blocked:
            from collectors import naver_listing
            log.info("매물 수집: %d건", naver_listing.run(ids, client=naver))
        if "news" in steps:
            from processing import news_summary
            log.info("뉴스 요약: %d건", news_summary.run())
        log.info("수집 끝: %s", ",".join(steps))
    finally:
        naver.close()


if __name__ == "__main__":
    sys.exit(main())
