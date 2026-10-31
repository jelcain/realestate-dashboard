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


def db_path() -> Path:
    return ROOT / config()["db_path"]


def molit_key(api: str) -> str:
    """api: 'trade' | 'rent'"""
    specific = os.getenv(f"MOLIT_{api.upper()}_KEY", "").strip()
    return specific or os.getenv("MOLIT_SERVICE_KEY", "").strip()
