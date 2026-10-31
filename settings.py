"""설정 로딩 (config.yaml + .env)."""
from functools import lru_cache
from pathlib import Path
import os

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


@lru_cache
def config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def db_dir() -> Path:
    # REALESTATE_DB_DIR: 다른 위치의 DB 를 쓸 때 (시험용)
    return Path(os.getenv("REALESTATE_DB_DIR") or ROOT / config()["db_dir"])


@lru_cache
def app_version() -> str:
    """실행 중인 코드의 버전 (git 커밋 번호·날짜). 웹과 PC 가 같은 코드인지 확인용"""
    import subprocess
    try:
        r = subprocess.run(["git", "log", "-1", "--format=%h · %cd", "--date=format:%m/%d %H:%M"],
                           cwd=ROOT, capture_output=True, text=True, timeout=5,
                           creationflags=0x08000000 if os.name == "nt" else 0)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:  # noqa: BLE001 - git 이 없으면 .git 파일에서 읽는다
        pass
    try:
        head = (ROOT / ".git" / "HEAD").read_text().strip()
        if head.startswith("ref: "):
            head = (ROOT / ".git" / head[5:]).read_text().strip()
        return head[:7]
    except OSError:
        return "알 수 없음"


def web_mode() -> bool:
    """웹(Streamlit Community Cloud) 보기 전용 모드: MYBOX 에서 받기만 하고, 수집·등록·수정은 숨긴다"""
    return os.getenv("WEB_MODE") == "1"


def molit_key(api: str) -> str:
    """api: 'trade' | 'rent'"""
    specific = os.getenv(f"MOLIT_{api.upper()}_KEY", "").strip()
    return specific or os.getenv("MOLIT_SERVICE_KEY", "").strip()


def mybox_token() -> str:
    return os.getenv("MYBOX_TOKEN", "").strip()


def cloud_mode() -> bool:
    """MYBOX 토큰이 있으면 클라우드 분담 모드: 실거래·뉴스는 클라우드, 매물·단지 정보는 PC.
    없으면 지금처럼 PC 혼자 모두 수집한다."""
    return bool(mybox_token())


def on_cloud() -> bool:
    """GitHub Actions 안에서 실행 중인가"""
    return os.getenv("GITHUB_ACTIONS") == "true"
