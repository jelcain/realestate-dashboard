"""DB 파일을 MYBOX 와 주고받는다 (클라우드 분담 모드).

- push(name): SQLite 백업 API 로 일관된 사본을 만들어 gzip 압축 후 업로드
- pull(name): MYBOX 쪽이 마지막으로 받은 것보다 새로우면 내려받아 로컬 파일을 바꾼다
name: 'pc' | 'cloud'
"""
from datetime import datetime
import gzip
import json
import logging
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

from settings import config, mybox_token
from storage.mybox import MyBox

log = logging.getLogger(__name__)

STATE = Path(__file__).resolve().parent.parent / "db" / ".sync.json"


def _local(name: str) -> Path:
    from db.models import CLOUD_DB, PC_DB
    return {"pc": PC_DB, "cloud": CLOUD_DB}[name]


def _remote_name(name: str) -> str:
    return f"{name}.db.gz"


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(st: dict):
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def _client() -> MyBox:
    return MyBox(mybox_token(), config()["mybox_folder"])


def remote_info(name: str) -> dict | None:
    """{'id', 'size', 'modified'} 또는 None"""
    return _client().file_info(_remote_name(name))


def push(name: str) -> dict:
    src = _local(name)
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / f"{name}.db"
        a, b = sqlite3.connect(src), sqlite3.connect(snap)
        a.backup(b)  # 쓰는 중이어도 일관된 사본
        b.close()
        a.close()
        gz = Path(tmp) / _remote_name(name)
        with open(snap, "rb") as f, gzip.open(gz, "wb", compresslevel=6) as g:
            shutil.copyfileobj(f, g, 1 << 20)
        info = _client().upload(gz, _remote_name(name))
    st = _state()
    st[name] = {"remote_modified": info.get("modified"), "pushed_at": datetime.now().isoformat(timespec="seconds")}
    _save_state(st)
    log.info("MYBOX 업로드: %s (%.1fMB)", _remote_name(name), (info.get("size") or 0) / 1e6)
    return info


def pull(name: str, force: bool = False) -> bool:
    """새 버전이 있으면 내려받아 교체. 교체했으면 True"""
    info = remote_info(name)
    if not info:
        log.info("MYBOX 에 %s 가 아직 없음", _remote_name(name))
        return False
    st = _state()
    if not force and st.get(name, {}).get("remote_modified") == info.get("modified") and _local(name).exists():
        return False
    dst = _local(name)
    with tempfile.TemporaryDirectory(dir=dst.parent) as tmp:
        gz = Path(tmp) / _remote_name(name)
        _client().download(info["id"], gz)
        new = Path(tmp) / f"{name}.db"
        with gzip.open(gz, "rb") as g, open(new, "wb") as f:
            shutil.copyfileobj(g, f, 1 << 20)
        c = sqlite3.connect(new)
        ok = c.execute("PRAGMA quick_check").fetchone()[0]
        c.close()
        if ok != "ok":
            raise RuntimeError(f"내려받은 {name}.db 가 손상됨: {ok}")
        _replace(new, dst)
    st[name] = {**st.get(name, {}), "remote_modified": info.get("modified"),
                "pulled_at": datetime.now().isoformat(timespec="seconds")}
    _save_state(st)
    log.info("MYBOX 내려받기: %s (%s)", _remote_name(name), info.get("modified"))
    return True


def _replace(new: Path, dst: Path):
    """열린 연결을 닫고, 이전 WAL 파일까지 지운 뒤 새 파일로 바꾼다"""
    from db.models import engine
    engine.dispose()
    for suffix in ("-wal", "-shm"):
        p = Path(str(dst) + suffix)
        if p.exists():
            os.remove(p)
    os.replace(new, dst)
