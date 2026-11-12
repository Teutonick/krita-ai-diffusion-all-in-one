import hashlib
import io
import os
from pathlib import Path

import pytest
from aiohttp import ClientSession
from PyQt5.QtCore import pyqtBoundSignal

from ai_diffusion.model.updates import AutoUpdate, UpdateState, fork_releases_url, fork_repo
from ai_diffusion.platform_tools import ZipFile

from .conftest import CloudService, qtapp


class SignalObserver:
    def __init__(self, signal: pyqtBoundSignal):
        self.events = []
        signal.connect(self.on_changed)

    def on_changed(self, value):
        self.events.append(value)

    def reset(self):
        self.events = []


def http_session(service_url: str):
    service_token = os.environ["INTERSTICE_INFRA_TOKEN"]
    headers = {"Authorization": f"Bearer {service_token}"}
    return ClientSession(service_url, headers=headers)


@qtapp
async def test_auto_update(cloud_service: CloudService, tmp_path: Path):
    if not cloud_service.enabled:
        pytest.skip("Cloud service not running")
    await run_auto_update_test(cloud_service, tmp_path)


async def run_auto_update_test(service: CloudService, tmp_path: Path):
    async with http_session(service.url) as session:
        last_version = new_version = "666.6.6"

        # Get the latest plugin version (set from previous test)
        async with session.get(f"/plugin/latest?version={new_version}") as response:
            assert response.status == 200
            result = await response.json()
            last_version = result["version"]
            a, b, c = last_version.split(".")
            new_version = f"{a}.{b}.{int(c) + 1}"

        # Create an existing installation
        install_dir = tmp_path / "install"
        install_plugin_dir = install_dir / "test_plugin"
        install_plugin_dir.mkdir(parents=True)
        install_test_file = install_plugin_dir / "test_file.txt"
        install_test_file.write_text("local produce is the best")

        updater = AutoUpdate(
            current_version=last_version,
            plugin_dir=install_dir,
            api_url=service.url,
        )
        assert updater.state is UpdateState.unknown

        state_changes = SignalObserver(updater.state_changed)
        await updater.check()
        assert state_changes.events == [UpdateState.checking, UpdateState.latest]
        assert updater.state is UpdateState.latest

        # Create a new plugin version
        build_dir = tmp_path / "build"
        build_plugin_dir = build_dir / "test_plugin"
        build_plugin_dir.mkdir(parents=True)
        build_test_file = build_plugin_dir / "test_file.txt"
        build_test_file.write_text("if you're feeling orange, try flying a kite")
        build_archive = build_dir / f"test_plugin-{new_version}.zip"

        # Build the plugin archive
        with ZipFile(build_archive, "w") as zip_file:
            for file in build_plugin_dir.iterdir():
                zip_file.write(file, f"test_plugin/{file.name}")

        # Upload the plugin as new version
        archive_data = build_archive.read_bytes()
        async with session.put(f"/plugin/upload/{new_version}", data=archive_data) as response:
            assert response.status == 200
            uploaded = await response.json()
            assert uploaded["status"] == "uploaded" and uploaded["version"] == new_version

        # Check for new version
        state_changes.reset()
        await updater.check()
        assert state_changes.events == [UpdateState.checking, UpdateState.available]
        assert updater.state is UpdateState.available
        assert updater.latest_version == new_version

        # Run the update
        state_changes.reset()
        await updater.run()
        assert state_changes.events == [
            UpdateState.downloading,
            UpdateState.installing,
            UpdateState.restart_required,
        ]
        assert updater.state is UpdateState.restart_required
        assert updater.latest_version == new_version
        assert install_test_file.read_text() == "if you're feeling orange, try flying a kite"


async def test_authorization(cloud_service: CloudService):
    if not cloud_service.enabled:
        pytest.skip("Cloud service not running")
    async with ClientSession(cloud_service.url) as session:
        # Version check is public
        async with session.get("/plugin/latest?version=1.2.3") as response:
            assert response.status == 200

        # Upload requires authorization
        async with session.put("/plugin/upload/1.2.3") as response:
            assert response.status == 401


@qtapp
async def test_reloaded_does_not_install_upstream_updates():
    updater = AutoUpdate(current_version="1.53.0-reloaded.11")
    await updater._check()
    assert updater.state is UpdateState.failed_check
    assert "all-in-one" in updater.error


@qtapp
@pytest.mark.parametrize("corrupt", [False, True])
async def test_fork_update(tmp_path: Path, monkeypatch, corrupt: bool):
    version = "1.53.0-all-in-one.10"
    name = f"krita_ai_diffusion-{version}.zip"
    checksums = f"SHA256SUMS-{version}.txt"
    base = f"https://github.com/{fork_repo}/releases/download/v{version}"
    init = tmp_path / "ai_diffusion" / "__init__.py"
    init.parent.mkdir()
    init.write_text('__version__ = "1.53.0-all-in-one.8"\n')
    data = io.BytesIO()
    with ZipFile(data, "w") as archive:
        archive.writestr("ai_diffusion.desktop", "[Desktop Entry]\n")
        archive.writestr("ai_diffusion/__init__.py", f'__version__ = "{version}"\r\n')
    payload = data.getvalue()
    digest = hashlib.sha256(payload).hexdigest()

    class Network:
        async def get(self, url, timeout):
            assert url == fork_releases_url
            return [
                {"tag_name": tag, "draft": False, "prerelease": prerelease, "assets": assets}
                for tag, prerelease, assets in [
                    ("1.53.0-all-in-one.9", False, []),
                    ("v1.53.0-all-in-one.11", True, []),
                    ("v1.54.0", False, []),
                    (f"v{version}", False, [{"name": name}, {"name": checksums}]),
                ]
            ]

        async def download(self, url, timeout):
            if url == f"{base}/{checksums}":
                return f"{digest}  {name}\r\n".encode()
            assert url == f"{base}/{name}"
            return payload + b"bad" if corrupt else payload

    monkeypatch.setattr(AutoUpdate, "_net", property(lambda self: Network()))
    updater = AutoUpdate(tmp_path, current_version="1.53.0-all-in-one.8")
    await updater.check()
    assert updater.latest_version == version
    assert updater.state is UpdateState.available
    await updater.run()
    if corrupt:
        assert updater.state is UpdateState.failed_update
        assert "all-in-one.8" in init.read_text()
    else:
        assert updater.state is UpdateState.restart_required
        assert version in init.read_text()
        assert (tmp_path / "ai_diffusion.desktop").is_file()
