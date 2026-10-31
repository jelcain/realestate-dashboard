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
