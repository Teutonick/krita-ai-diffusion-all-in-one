from __future__ import annotations

import json
import mimetypes
from base64 import b64decode, b64encode
from collections.abc import Awaitable, Callable
from contextlib import closing
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Full, Queue
from secrets import token_urlsafe
from shutil import copyfileobj
from sqlite3 import Error as DatabaseError
from sqlite3 import connect
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import urlopen

from .image import Extent, Image
from .localization import translate as _
from .util import user_data_dir

web_root = Path(__file__).parent / "vnccs_pose_web"
vnccs_component = "VNCCS Pose Studio"
vnccs_revision = "8e0fe0bd8470ba1c10273a4d37806b5902aa0b39"
vnccs_source = f"https://raw.githubusercontent.com/AHEKOT/ComfyUI_VNCCS_Utils/{vnccs_revision}/web/"
max_state_bytes = 24 * 1024 * 1024
format_name = "krita-vnccs-pose-v1"


def vnccs_assets_path():
    return user_data_dir / "components" / "vnccs-pose" / vnccs_revision


def _asset_manifest() -> dict[str, str]:
    return json.loads((web_root / "assets.json").read_text(encoding="utf-8"))


def vnccs_assets_installed():
    path = vnccs_assets_path()
    return (path / ".complete").is_file() and all(
        (path / name).is_file() for name in _asset_manifest()
    )


def download_vnccs_asset_https(url: str, file: Path):
    with urlopen(url, timeout=60) as response, file.open("wb") as target:
        copyfileobj(response, target)


async def install_vnccs_assets(download_file: Callable[[str, Path], Awaitable[None]]):
    if vnccs_assets_installed():
        return
    destination = vnccs_assets_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="install-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "assets"
        for name, digest in _asset_manifest().items():
            file = stage / name
            file.parent.mkdir(parents=True, exist_ok=True)
            await download_file(vnccs_source + name, file)
            checksum = sha256()
            with file.open("rb") as data:
                for chunk in iter(lambda: data.read(1024 * 1024), b""):
                    checksum.update(chunk)
            if checksum.hexdigest() != digest:
                raise ValueError(_("VNCCS asset checksum mismatch: {name}", name=name))
        (stage / ".complete").touch()
        backup = Path(temporary) / "previous"
        if destination.exists():
            destination.rename(backup)
        try:
            stage.rename(destination)
        except OSError:
            if backup.exists():
                backup.rename(destination)
            raise


def _decode_capture(value: str):
    data = b64decode(value.removeprefix("data:image/png;base64,"), validate=True)
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n") or data[12:16] != b"IHDR":
        raise ValueError("VNCCS did not return a PNG capture")
    if any(not 1 <= int.from_bytes(data[i : i + 4], "big") <= 2048 for i in (16, 20)):
        raise ValueError("VNCCS capture dimensions exceed 2048 pixels")
    return data


def load_vnccs_state(value: str):
    if not value or format_name not in value[:100]:
        return None
    state = json.loads(value)
    if not isinstance(state, dict) or state.get("format") != format_name:
        return None
    return state


def render_vnccs_pose(value: str):
    if state := load_vnccs_state(value):
        return Image.from_bytes(_decode_capture(state["capture"]), "PNG")
    return None


def _library(method: str, route: str, query: str, payload: dict, path: Path):
    action, _, name = route.partition("/")
    params = {key: values[0] for key, values in parse_qs(query).items()}
    key = (name, params.get("category", "Uncategorized"), params.get("asset_type", "pose"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(path)) as db, db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS poses (name TEXT, category TEXT, kind TEXT, "
            "metadata TEXT, pose TEXT, mime TEXT, preview BLOB, PRIMARY KEY(name, category, kind))"
        )
        if method == "POST" and action == "save":
            key = (payload["name"], payload["category"], payload["asset_type"])
            name, category, kind = key
            pose, tags = payload["pose"], payload["tags"]
            if (
                payload.get("repository") != "local_user_poses"
                or not all(isinstance(s, str) and 0 < len(s) <= 200 for s in key)
                or kind not in ("pose", "animation")
                or not isinstance(pose, dict)
                or not isinstance(tags, list)
                or not all(isinstance(tag, str) for tag in tags)
            ):
                raise ValueError("Invalid library item")
            mime, preview = "", b""
            if encoded := payload.get("preview"):
                header, _, data = encoded.partition(",")
                mime = header.removeprefix("data:").removesuffix(";base64")
                if mime not in ("image/png", "image/jpeg", "image/webp", "video/webm"):
                    raise ValueError("Unsupported library preview")
                preview = b64decode(data, validate=True)
            metadata = {
                "name": name,
                "category": category,
                "asset_type": kind,
                "repository": "local_user_poses",
                "tags": tags,
                "has_preview": bool(preview),
                "preview_type": mime,
                "preview_mtime": token_urlsafe(8),
                "id": token_urlsafe(12),
            }
            if payload.get("old_name") and payload.get("old_repository") == "local_user_poses":
                db.execute(
                    "DELETE FROM poses WHERE name=? AND category=? AND kind=?",
                    (payload["old_name"], payload["old_category"], kind),
                )
            db.execute(
                "INSERT OR REPLACE INTO poses VALUES (?, ?, ?, ?, ?, ?, ?)",
                (*key, json.dumps(metadata), json.dumps(pose), mime, preview),
            )
            result = {"id": metadata["id"]}
        elif method == "GET" and action == "list":
            full = params.get("full") == "true"
            columns = "metadata, pose" if full else "metadata"
            rows = db.execute(f"SELECT {columns} FROM poses ORDER BY name COLLATE NOCASE")
            result = {
                "poses": [
                    dict(json.loads(row[0]), data=json.loads(row[1]))
                    if full
                    else json.loads(row[0])
                    for row in rows
                ]
            }
        elif params.get("repository", "local_user_poses") != "local_user_poses":
            raise LookupError("Only the local library is available in Krita")
        elif method == "DELETE" and action == "delete":
            db.execute("DELETE FROM poses WHERE name=? AND category=? AND kind=?", key)
            result = {"ok": True}
        elif method == "GET" and action in ("get", "preview"):
            columns = "metadata, pose" if action == "get" else "mime, preview"
            row = db.execute(
                f"SELECT {columns} FROM poses WHERE name=? AND category=? AND kind=?", key
            ).fetchone()
            if not row or (action == "preview" and not row[1]):
                raise LookupError("Library item not found")
            if action == "preview":
                return row[1], row[0]
            result = dict(json.loads(row[0]), pose=json.loads(row[1]))
        else:
            raise LookupError("Library operation not available in Krita")
    return json.dumps(result).encode(), "application/json"


class VnccsSession:
    def __init__(self, value: str, extent: Extent):
        self.results: Queue[str] = Queue(maxsize=1)
        prefix = "/" + token_urlsafe(24) + "/"
        state = load_vnccs_state(value)
        ratio = min(1.0, 1024 / extent.longest_side)
        initial = json.dumps({
            "pose_data": state["pose_data"] if state else None,
            "width": max(32, round(extent.width * ratio)),
            "height": max(32, round(extent.height * ratio)),
        }).encode()
        results = self.results
        vendor_root = vnccs_assets_path().resolve()
        library_path = user_data_dir / "pose-library.sqlite3"
        library_prefix = "vnccs/pose_library/"

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args):
                pass

            def setup(self):
                super().setup()
                self.connection.settimeout(20)

            def respond(self, data: bytes, kind: str, status=200):
                self.send_response(status)
                self.send_header("Content-Type", kind)
                if status != 204:
                    self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)

            def serve_library(self, url):
                route = unquote(url.path[len(prefix + library_prefix) :])
                payload = {}
                try:
                    if self.command != "GET" and self.headers.get("Origin") != origin:
                        self.respond(b'{"error":"Invalid origin"}', "application/json", 403)
                        return
                    if self.command == "POST":
                        size = int(self.headers.get("Content-Length", "0"))
                        if not 0 < size <= max_state_bytes:
                            raise ValueError("Invalid library payload size")
                        payload = json.loads(self.rfile.read(size))
                        if not isinstance(payload, dict):
                            raise ValueError("Invalid library payload")
                    data, mime = _library(self.command, route, url.query, payload, library_path)
                except (KeyError, TypeError, AttributeError, ValueError):
                    self.respond(b'{"error":"Invalid library item"}', "application/json", 400)
                except LookupError:
                    self.respond(b'{"error":"Library item unavailable"}', "application/json", 404)
                except (DatabaseError, OSError):
                    self.respond(
                        b'{"error":"Could not access local library"}', "application/json", 500
                    )
                else:
                    self.respond(data, mime)

            def do_GET(self):
                url = urlsplit(self.path)
                if url.path.startswith(prefix + library_prefix):
                    self.serve_library(url)
                    return
                path = unquote(url.path)
                if not path.startswith(prefix):
                    self.send_error(404)
                    return
                name = path[len(prefix) :]
                if name == "state":
                    self.respond(initial, "application/json")
                    return
                if name == "health":
                    self.respond(b"", "text/plain", status=204)
                    return
                if name.startswith("extensions/vnccs/"):
                    folder = vendor_root
                    name = name.removeprefix("extensions/vnccs/")
                elif name in (
                    "",
                    "frame.html",
                    "session.js",
                    "editor.js",
                    "scripts/api.js",
                    "scripts/app.js",
                ):
                    folder = web_root.resolve()
                else:
                    self.send_error(404)
                    return
                file = (folder / (name or "index.html")).resolve()
                if not file.is_relative_to(folder) or not file.is_file():
                    self.send_error(404)
                    return
                mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                if file.suffix in (".js", ".mjs"):
                    mime = "text/javascript"
                if folder == vendor_root and name == "vnccs_pose_studio.js":
                    script = file.read_bytes().replace(
                        b"/vnccs/pose_library/", b"./vnccs/pose_library/"
                    )
                else:
                    script = None
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header(
                    "Content-Length",
                    str(len(script) if script is not None else file.stat().st_size),
                )
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Content-Type-Options", "nosniff")
                frame_ancestors = "'self'" if name == "frame.html" else "'none'"
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; script-src 'self'; worker-src 'self' blob:; "
                    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                    f"font-src 'self' data:; connect-src 'self'; frame-ancestors {frame_ancestors}; "
                    "base-uri 'none'; form-action 'none'",
                )
                self.end_headers()
                if script is not None:
                    self.wfile.write(script)
                else:
                    with file.open("rb") as source:
                        copyfileobj(source, self.wfile)

            def do_DELETE(self):
                url = urlsplit(self.path)
                if url.path.startswith(prefix + library_prefix):
                    self.serve_library(url)
                else:
                    self.send_error(404)

            def do_POST(self):
                url = urlsplit(self.path)
                if url.path.startswith(prefix + library_prefix):
                    self.serve_library(url)
                    return
                if self.path != prefix + "apply" or self.headers.get("Origin") != origin:
                    self.send_error(403)
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= max_state_bytes or not results.empty():
                        raise ValueError()
                    payload = json.loads(self.rfile.read(size))
                    pose = payload["pose_data"]
                    if not isinstance(pose, dict) or not pose.get("poses"):
                        raise ValueError()
                    capture = _decode_capture(payload["capture"])
                    state = {
                        "format": format_name,
                        "pose_data": pose,
                        "capture": b64encode(capture).decode("ascii"),
                    }
                    results.put_nowait(json.dumps(state, separators=(",", ":")))
                except (Full, KeyError, TypeError, ValueError, OSError):
                    self.send_error(400)
                    return
                self.respond(b'{"ok":true}', "application/json")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        origin = f"http://127.0.0.1:{self._server.server_port}"
        self.url = origin + prefix
        self._thread = Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True
        )
        self._thread.start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()
