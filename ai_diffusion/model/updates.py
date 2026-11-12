import hashlib
import os
import re
import shutil
from enum import Enum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import NamedTuple
from zipfile import ZipFile as ZipArchive

from PyQt5.QtCore import QObject, pyqtSignal

from .. import __version__, eventloop
from ..backend.network import RequestManager
from ..platform_tools import ZipFile
from ..util import client_logger as log
from .properties import ObservableProperties, Property


class UpdateState(Enum):
    unknown = 1
    checking = 2
    available = 3
    latest = 4
    downloading = 5
    installing = 6
    restart_required = 7
    failed_check = 8
    failed_update = 9


class UpdatePackage(NamedTuple):
    version: str
    url: str
    sha256: str


fork_repo = "Teutonick/krita-ai-diffusion-all-in-one"
fork_releases_url = f"https://api.github.com/repos/{fork_repo}/releases?per_page=100"
_fork_version = re.compile(r"(\d+)\.(\d+)\.(\d+)-all-in-one\.(\d+)")


def _version_key(version: str):
    if match := _fork_version.fullmatch(version):
        return tuple(map(int, match.groups()))
    return ()


class AutoUpdate(QObject, ObservableProperties):
    default_api_url = os.getenv("INTERSTICE_URL", "https://api.interstice.cloud")

    state = Property(UpdateState.unknown)
    latest_version = Property("")
    error = Property("")

    state_changed = pyqtSignal(UpdateState)
    latest_version_changed = pyqtSignal(str)
    error_changed = pyqtSignal(str)

    def __init__(
        self,
        plugin_dir: Path | None = None,
        current_version: str | None = None,
        api_url: str | None = None,
    ):
        super().__init__()
        self.plugin_dir = plugin_dir or Path(__file__).parent.parent.parent
        self.current_version = current_version or __version__
        self.api_url = api_url or self.default_api_url
        self._package: UpdatePackage | None = None
        self._request_manager: RequestManager | None = None

    def check(self):
        return eventloop.run(
            self._handle_errors(
                self._check, UpdateState.failed_check, "Failed to check for new plugin version"
            )
        )

    async def _check(self):
        if self.state in (
            UpdateState.checking,
            UpdateState.downloading,
            UpdateState.installing,
            UpdateState.restart_required,
        ):
            return

        self._package = None
        self.error = ""
        if _version_key(self.current_version):
            await self._check_fork()
            return

        if (
            any(tag in self.current_version for tag in ("-reloaded.", "-all-in-one."))
            and self.api_url == self.default_api_url
        ):
            self.error = (
                "Install updates from the all-in-one project ZIP to preserve fork features."
            )
            self.state = UpdateState.failed_check
            return

        self.state = UpdateState.checking
        log.info(f"Checking for latest plugin version at {self.api_url}")
        result = await self._net.get(
            f"{self.api_url}/plugin/latest?version={self.current_version}", timeout=10
        )
        self.latest_version = result.get("version")
        if not self.latest_version:
            log.error(f"Invalid plugin update information: {result}")
            self.state = UpdateState.failed_check
            self.error = "Failed to retrieve plugin update information"
        elif self.latest_version == self.current_version:
            log.info("Plugin is up to date!")
            self.state = UpdateState.latest
        elif "url" not in result or "sha256" not in result:
            log.error(f"Invalid plugin update information: {result}")
            self.state = UpdateState.failed_check
            self.error = "Plugin update package is incomplete"
        else:
            log.info(f"New plugin version available: {self.latest_version}")
            self._package = UpdatePackage(
                version=self.latest_version,
                url=result["url"],
                sha256=result["sha256"],
            )
            self.state = UpdateState.available

    async def _check_fork(self):
        self.state = UpdateState.checking
        releases = await self._net.get(fork_releases_url, timeout=10)
        candidates = []
        for release in releases:
            if release["draft"] or release["prerelease"]:
                continue
            version = release["tag_name"].removeprefix("v")
            if _version_key(version) > _version_key(self.current_version):
                candidates.append((version, release))
        if not candidates:
            self.latest_version = self.current_version
            self.state = UpdateState.latest
            return

        version, release = max(candidates, key=lambda item: _version_key(item[0]))
        archive = f"krita_ai_diffusion-{version}.zip"
        checksums = f"SHA256SUMS-{version}.txt"
        asset_names = {asset["name"] for asset in release["assets"]}
        if not {archive, checksums} <= asset_names:
            raise ValueError(f"Release {version} is missing the plugin ZIP or SHA-256 checksums")
        base_url = f"https://github.com/{fork_repo}/releases/download/{release['tag_name']}"
        checksum_data = bytes(await self._net.download(f"{base_url}/{checksums}", timeout=15))
        digest_pattern = rf"([0-9a-fA-F]{{64}})\s+\*?{re.escape(archive)}"
        digests = [
            match[1]
            for line in checksum_data.decode("utf-8-sig").splitlines()
            if (match := re.fullmatch(digest_pattern, line))
        ]
        if len(digests) != 1:
            raise ValueError(f"Release {version} has no unique SHA-256 checksum for the plugin ZIP")
        self._package = UpdatePackage(version, f"{base_url}/{archive}", digests[0].lower())
        self.latest_version = version
        self.state = UpdateState.available

    def run(self):
        return eventloop.run(
            self._handle_errors(self._run, UpdateState.failed_update, "Failed to update plugin")
        )

    async def _run(self):
        if self.state not in (UpdateState.available, UpdateState.failed_update):
            return
        assert self._package
        self.error = ""
        log.info(f"Downloading plugin update {self._package.url}")
        self.state = UpdateState.downloading
        archive_data = await self._net.download(self._package.url, timeout=120)

        sha256 = hashlib.sha256(archive_data).hexdigest()
        if sha256 != self._package.sha256:
            log.error(f"Update package hash mismatch: {sha256} != {self._package.sha256}")
            raise RuntimeError("Downloaded plugin package is corrupted or incomplete")

        self.state = UpdateState.installing
        with TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "update.zip"
            archive_path.write_bytes(archive_data)
            source_dir = Path(tmp) / "plugin"
            with ZipFile(archive_path) as zip_file:
                if _version_key(self.current_version):
                    self._validate_fork_zip(zip_file, self._package.version)
                zip_file.extractall(source_dir)
            log.info(f"Installing new plugin version to {self.plugin_dir}")
            shutil.copytree(source_dir, self.plugin_dir, dirs_exist_ok=True)
        self.current_version = self._package.version
        self.state = UpdateState.restart_required

    @staticmethod
    def _validate_fork_zip(archive: ZipArchive, version: str):
        names = archive.namelist()
        if not {"ai_diffusion.desktop", "ai_diffusion/__init__.py"} <= set(names) or any(
            (name != "ai_diffusion.desktop" and not name.startswith("ai_diffusion/"))
            or "\\" in name
            or ":" in name
            or ".." in name.split("/")
            for name in names
        ):
            raise ValueError("The downloaded ZIP is not a Krita plugin package")
        init = archive.read("ai_diffusion/__init__.py").decode("utf-8")
        if f'__version__ = "{version}"' not in init.splitlines():
            raise ValueError("The plugin ZIP version does not match the release tag")

    @property
    def is_available(self):
        return self.latest_version is not None and self.latest_version != self.current_version

    @property
    def _net(self):
        if self._request_manager is None:
            self._request_manager = RequestManager()
            self._request_manager.add_header(
                "User-Agent", f"krita-ai-diffusion/{self.current_version}"
            )
        return self._request_manager

    async def _handle_errors(self, func, error_state: UpdateState, message: str):
        try:
            return await func()
        except Exception as e:
            log.exception(e)
            self.error = f"{message}: {e}"
            self.state = error_state
            return None
