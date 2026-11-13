import json
import re
from hashlib import sha256
from threading import BoundedSemaphore
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

repositories = {
    "miuproject": "MIUProject/VNCCS_PoseLibrary_Main",
    "totemistyk": "Totemistyk/General_Poses_PoseStudio",
}
max_bytes = 4 * 1024 * 1024


class _Redirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = urlsplit(newurl)
        host = url.hostname or ""
        if url.scheme != "https" or not (
            host == "huggingface.co" or host.endswith((".huggingface.co", ".hf.co"))
        ):
            raise ValueError("Unexpected pose library redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download(repo: str, path: str):
    url = f"https://huggingface.co/{repositories[repo]}/resolve/main/{quote(path)}"
    with build_opener(_Redirects()).open(url, timeout=8) as response:
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("Pose library file exceeds size limit")
    return data


def _file(entry: dict, kind: str, folder: str, suffix: str):
    path, digest = entry.get(f"{kind}_path"), entry.get(f"{kind}_sha256")
    if (
        not isinstance(path, str)
        or len(path) > 512
        or not path.startswith(f"{folder}/")
        or not path.lower().endswith(suffix)
        or any(part in ("", ".", "..") for part in path.split("/"))
        or any(char in path for char in ("\\", "\x00", "%", "?", "#"))
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
    ):
        return None
    return path, digest


class RemotePoseLibrary:
    def __init__(self):
        self.catalogs: dict[
            str, dict[tuple[str, str, str], tuple[dict, tuple[str, str], tuple[str, str] | None]]
        ] = {}
        self._downloads = BoundedSemaphore(4)

    def _fetch(self, repo: str, path: str, digest: str = ""):
        if not self._downloads.acquire(timeout=8):
            raise TimeoutError("Pose library is busy")
        try:
            data = _download(repo, path)
            if digest and sha256(data).hexdigest() != digest:
                raise ValueError("Pose library checksum mismatch")
            return data
        finally:
            self._downloads.release()

    def enable(self, repo: str):
        if not isinstance(repo, str) or repo not in repositories:
            raise LookupError("Unknown pose library")
        if repo in self.catalogs:
            return
        manifest = json.loads(self._fetch(repo, "pose_library.json"))
        entries = manifest.get("poses") if isinstance(manifest, dict) else None
        if not isinstance(entries, list) or len(entries) > 2000:
            raise ValueError("Invalid pose library catalog")
        catalog = {}
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("asset_type") != "pose":
                continue
            name, category = entry.get("name"), entry.get("category")
            tags = entry.get("tags") or []
            if (
                not isinstance(name, str)
                or not 0 < len(name) <= 200
                or not isinstance(category, str)
                or not 0 < len(category) <= 200
                or not isinstance(tags, list)
            ):
                continue
            pose = _file(entry, "json", "poses", ".json")
            if not pose:
                continue
            preview = (
                _file(entry, "preview", "previews", ".webp")
                if entry.get("preview_type") == "image/webp"
                else None
            )
            meta = {
                "name": name,
                "category": category,
                "asset_type": "pose",
                "repository": repo,
                "tags": [t[:100] for t in tags[:50] if isinstance(t, str)],
                "has_preview": bool(preview),
                "preview_type": "image/webp" if preview else "",
                "preview_mtime": preview[1] if preview else "",
            }
            catalog[(name, category, "pose")] = (meta, pose, preview)
        if not catalog:
            raise ValueError("No supported poses in the catalog")
        self.catalogs[repo] = catalog

    def serve(self, repo: str, action: str, key: tuple[str, str, str]):
        catalog = self.catalogs.get(repo, {})
        if action == "list":
            return json.dumps({
                "poses": [item[0] for item in catalog.values()]
            }).encode(), "application/json"
        if key not in catalog or action not in ("get", "preview"):
            raise LookupError("Pose is not available")
        meta, pose_file, preview = catalog[key]
        if action == "preview":
            if not preview:
                raise LookupError("Preview is not available")
            return self._fetch(repo, *preview), "image/webp"
        pose = json.loads(self._fetch(repo, *pose_file))
        if not isinstance(pose, dict):
            raise TypeError("Invalid pose library item")
        return json.dumps(dict(meta, pose=pose)).encode(), "application/json"
