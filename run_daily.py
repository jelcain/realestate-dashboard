"""일일 배치 진입점 (Windows 작업 스케줄러가 매일 05:00 실행, 대시보드의 '지금 수집' 단추도 이것을 실행).

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

from settings import ROOT

STEPS = ["complex", "trade", "listing", "news"]
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
    args = p.parse_args(argv)
    steps = args.only.split(",") if args.only else STEPS
    ids = [int(x) for x in args.complex.split(",")] if args.complex else None
    if ids and not args.only:
        steps = ["complex", "trade", "listing"]
    setup_logging()
    log = logging.getLogger("run_daily")

    other = running()
    if other:
        log.warning("이미 수집이 실행 중입니다 (pid %s, %s 시작) → 종료", other["pid"], other["started"])
        return 1
    LOCK.write_text(json.dumps({"pid": os.getpid(), "started": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                "args": sys.argv[1:] if argv is None else argv}, ensure_ascii=False),
                    encoding="utf-8")
    log.info("수집 시작: %s%s", ",".join(steps), f" (단지 {ids})" if ids else "")

    from collectors.naver_client import Blocked, NaverClient

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
        log.info("수집 끝")
    finally:
        naver.close()
        LOCK.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
