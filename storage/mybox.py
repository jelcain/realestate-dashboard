"""네이버 MYBOX Open API 클라이언트 (개인 액세스 토큰).

https://open-api.mybox.naver.com/v1 , 인증: Authorization: Bearer <PAT>
업로드: POST /drive/files → uploadUrl 로 multipart(Filedata) 전송
다운로드: GET /drive/files/{id}/download → downloadUrl 을 GET (서명된 URL 에는 토큰을 보내지 않는다)
"""
from pathlib import Path

import httpx

BASE = "https://open-api.mybox.naver.com/v1"


class MyBoxError(Exception):
    pass


def _rid(r: dict) -> str | None:
    for k in ("resourceId", "id", "fileId", "folderId"):
        if r.get(k):
            return str(r[k])
    return None


def _is_folder(r: dict) -> bool:
    t = str(r.get("resourceType") or r.get("type") or "").lower()
    return "folder" in t or r.get("isFolder") is True


def _info(r: dict) -> dict:
    return {"id": _rid(r), "name": r.get("name") or r.get("resourceName"), "size": r.get("size"),
            "modified": r.get("modifiedAt") or r.get("updatedAt") or r.get("modified"), "raw": r}


class MyBox:
    def __init__(self, token: str, folder: str):
        if not token:
            raise MyBoxError("MYBOX_TOKEN 이 설정되지 않았습니다")
        self.folder = folder
        self.http = httpx.Client(base_url=BASE, timeout=60,
                                 headers={"Authorization": f"Bearer {token}", "User-Agent": "realestate-dashboard"})
        self._folder_id: str | None = None

    def _call(self, method: str, path: str, **kw) -> dict:
        r = self.http.request(method, path, **kw)
        if r.status_code >= 400:
            try:
                err = r.json()
            except ValueError:
                err = {"message": r.text[:300]}
            raise MyBoxError(f"MYBOX {method} {path} → {r.status_code} {err.get('code', '')} {err.get('message', '')}")
        return r.json() if r.content else {}

    def _list(self, path: str) -> list[dict]:
        out, cursor = [], None
        while True:
            params = {"count": 1000, **({"cursor": cursor} if cursor else {})}
            res = self._call("GET", path, params=params)
            out += res.get("resources", [])
            cursor = (res.get("responseMetaData") or {}).get("nextCursor")
            if not cursor:
                return out

    def folder_id(self) -> str:
        """작업 폴더 ID (없으면 루트에 만든다)"""
        if self._folder_id:
            return self._folder_id
        for r in self._list("/drive/resources"):
            if _is_folder(r) and (r.get("name") or r.get("resourceName")) == self.folder:
                self._folder_id = _rid(r)
                return self._folder_id
        created = self._call("POST", "/drive/folders", json={"folderName": self.folder})
        self._folder_id = _rid(created) or _rid(created.get("resource", {}) or {})
        if not self._folder_id:
            raise MyBoxError(f"폴더 생성 응답에서 ID 를 찾지 못함: {created}")
        return self._folder_id

    def file_info(self, name: str) -> dict | None:
        for r in self._list(f"/drive/folders/{self.folder_id()}/resources"):
            if not _is_folder(r) and (r.get("name") or r.get("resourceName")) == name:
                return _info(r)
        return None

    def upload(self, path: Path, name: str) -> dict:
        size = path.stat().st_size
        res = self._call("POST", "/drive/files", json={"fileName": name, "fileSize": size, "isOverwrite": True,
                                                       "parentId": self.folder_id()})
        url = res.get("uploadUrl")
        if not url:
            raise MyBoxError(f"업로드 URL 을 받지 못함: {res}")
        with open(path, "rb") as f:
            r = httpx.post(url, files={"Filedata": (name, f, "application/gzip")}, timeout=600)
        if r.status_code >= 400:
            raise MyBoxError(f"업로드 실패 {r.status_code}: {r.text[:300]}")
        return self.file_info(name) or {"size": size}

    def download(self, file_id: str, dest: Path):
        res = self._call("GET", f"/drive/files/{file_id}/download")
        url = res.get("downloadUrl")
        if not url:
            raise MyBoxError(f"다운로드 URL 을 받지 못함: {res}")
        part = dest.with_suffix(dest.suffix + ".part")
        with httpx.stream("GET", url, timeout=300, follow_redirects=True) as r:
            r.raise_for_status()
            with open(part, "wb") as f:
                for chunk in r.iter_bytes(1 << 18):
                    f.write(chunk)
        part.replace(dest)
