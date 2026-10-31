"""PC 에서 GitHub Actions 수집(실거래·뉴스)을 실행시키고 상태를 본다 (gh CLI 사용)."""
import json
import os
from pathlib import Path
import shutil
import subprocess

from settings import config

WORKFLOW = "daily.yml"


def _gh() -> str | None:
    found = shutil.which("gh")
    if found:
        return found
    p = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "GitHub CLI" / "gh.exe"
    return str(p) if p.exists() else None


def _run(args: list[str], timeout: int = 30) -> str:
    gh = _gh()
    if not gh:
        raise RuntimeError("GitHub CLI(gh)를 찾을 수 없습니다")
    flags = 0x08000000 if os.name == "nt" else 0  # 창 숨김
    r = subprocess.run([gh, *args, "--repo", config()["github_repo"]], capture_output=True, text=True,
                       encoding="utf-8", timeout=timeout, creationflags=flags)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[:300])
    return r.stdout


def dispatch(complex_ids: list[int] | None = None, only: list[str] | None = None):
    """클라우드 수집 실행 요청. complex_ids: 그 단지의 시군구만, only: trade/news 중 일부"""
    args = ["workflow", "run", WORKFLOW]
    if complex_ids:
        args += ["-f", "complex=" + ",".join(map(str, complex_ids))]
    if only:
        args += ["-f", "only=" + ",".join(only)]
    _run(args)


def recent_runs(limit: int = 5) -> list[dict]:
    """[{status, conclusion, createdAt, event, url}]"""
    out = _run(["run", "list", "--workflow", WORKFLOW, "--limit", str(limit),
                "--json", "status,conclusion,createdAt,event,url,displayTitle"])
    return json.loads(out or "[]")


def actions_url() -> str:
    return f"https://github.com/{config()['github_repo']}/actions/workflows/{WORKFLOW}"
