import asyncio
import json
from base64 import b64encode
from hashlib import sha256
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import pytest
from PyQt5.QtCore import Qt

from ai_diffusion import vnccs_pose
from ai_diffusion.image import Extent, Image
from ai_diffusion.vnccs_pose import VnccsSession, load_vnccs_state, render_vnccs_pose

from .conftest import qtapp


@qtapp
async def test_vnccs_assets_install_and_retry(tmp_path: Path, monkeypatch):
    files = {"vnccs_pose_studio.js": b"editor", "pose_studio/assets/body.gz": b"rig"}
    monkeypatch.setattr(vnccs_pose, "user_data_dir", tmp_path)
    monkeypatch.setattr(
        vnccs_pose, "_asset_manifest", lambda: {k: sha256(v).hexdigest() for k, v in files.items()}
    )
    downloads: list[str] = []
    corrupt = True

    async def download(url: str, file: Path):
        name = url.removeprefix(vnccs_pose.vnccs_source)
        downloads.append(name)
        file.write_bytes(b"wrong" if corrupt and name.endswith(".gz") else files[name])

    with pytest.raises(ValueError, match="checksum mismatch"):
        await vnccs_pose.install_vnccs_assets(download)
    assert not vnccs_pose.vnccs_assets_installed()
    assert not vnccs_pose.vnccs_assets_path().exists()

    corrupt = False
    await vnccs_pose.install_vnccs_assets(download)
    assert vnccs_pose.vnccs_assets_installed()
    assert downloads == list(files) * 2
    await vnccs_pose.install_vnccs_assets(download)
    assert downloads == list(files) * 2
    session = VnccsSession("", Extent(96, 128))

    def fetch_script():
        with urlopen(session.url + "extensions/vnccs/vnccs_pose_studio.js", timeout=5) as response:
            return response.read()

    try:
        assert await asyncio.to_thread(fetch_script) == files["vnccs_pose_studio.js"]
    finally:
        session.close()


def test_vnccs_browser_round_trip():
    extent = Extent(96, 128)
    source = Image.create(extent, Qt.GlobalColor.white)
    pose = {"poses": [{"index_02_l": [0, 0, 0, 1]}], "export": {"hand_controls_v2": True}}
    capture = "data:image/png;base64," + b64encode(bytes(source.to_bytes())).decode("ascii")
    session = VnccsSession("", extent)
    try:
        with urlopen(session.url, timeout=5) as response:
            assert b'data-src="./frame.html"' in response.read()
            assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
        with urlopen(session.url + "frame.html", timeout=5) as response:
            assert "frame-ancestors 'self'" in response.headers["Content-Security-Policy"]
        with urlopen(session.url + "health", timeout=5) as response:
            assert response.status == 204
        with urlopen(session.url + "state", timeout=5) as response:
            assert json.load(response) == {"pose_data": None, "width": 96, "height": 128}
        body = json.dumps({"pose_data": pose, "capture": capture}).encode()
        request = Request(session.url + "apply", data=body)
        with pytest.raises(HTTPError, match="403"):
            urlopen(Request(session.url + "apply", method="POST"), timeout=5)
        url = urlsplit(session.url)
        request.add_header("Origin", f"{url.scheme}://{url.netloc}")
        with urlopen(request, timeout=5) as response:
            assert json.load(response) == {"ok": True}
        state = session.results.get(timeout=1)
        saved = load_vnccs_state(state)
        assert saved and saved["pose_data"] == pose
        image = render_vnccs_pose(state)
        assert image and Image.compare(image, source) == 0
    finally:
        session.close()

    reopened = VnccsSession(state, extent)
    try:
        with urlopen(reopened.url + "state", timeout=5) as response:
            assert json.load(response)["pose_data"] == pose
    finally:
        reopened.close()


def test_vnccs_local_library_across_sessions(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(vnccs_pose, "user_data_dir", tmp_path)
    vendor = vnccs_pose.vnccs_assets_path()
    vendor.mkdir(parents=True)
    (vendor / "vnccs_pose_studio.js").write_text("fetch('/vnccs/pose_library/list')")
    pose = {"poses": [{"index_02_l": [0, 0, 0, 1]}]}
    preview = bytes(Image.create(Extent(32, 32), Qt.GlobalColor.white).to_bytes())
    item = {
        "name": "Pose / 1",
        "category": "Uncategorized",
        "asset_type": "pose",
        "repository": "local_user_poses",
        "tags": ["test"],
        "pose": pose,
        "preview": "data:image/png;base64," + b64encode(preview).decode(),
    }

    def request(session, route, method="GET", data=None, with_origin=True):
        url = urlsplit(session.url)
        headers = {"Origin": f"{url.scheme}://{url.netloc}"} if with_origin else {}
        return urlopen(
            Request(session.url + route, data, headers, method=method),
            timeout=5,
        )

    prefix = "vnccs/pose_library/"
    session = VnccsSession("", Extent(96, 128))
    try:
        with request(session, "extensions/vnccs/vnccs_pose_studio.js") as response:
            assert response.read() == b"fetch('./vnccs/pose_library/list')"
        with request(session, prefix + "list") as response:
            assert json.load(response) == {"poses": []}
        payload = json.dumps(item).encode()
        with pytest.raises(HTTPError, match="403"):
            request(session, prefix + "save", "POST", with_origin=False)
        with request(session, prefix + "save", "POST", payload) as response:
            item_id = json.load(response)["id"]
    finally:
        session.close()

    session = VnccsSession("", Extent(96, 128))
    try:
        with request(session, prefix + "list?full=true") as response:
            saved = json.load(response)["poses"][0]
            assert (saved["id"], saved["data"], saved["tags"]) == (item_id, pose, ["test"])
        name = "Pose%20%2F%201"
        with request(session, prefix + "get/" + name) as response:
            assert json.load(response)["pose"] == pose
        with request(session, prefix + "preview/" + name) as response:
            assert response.headers.get_content_type() == "image/png"
            assert response.read() == preview
        with request(session, prefix + "delete/" + name, "DELETE") as response:
            assert json.load(response)["ok"]
        with request(session, prefix + "list") as response:
            assert json.load(response) == {"poses": []}
    finally:
        session.close()
