import asyncio
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from PyQt5.QtNetwork import QNetworkReply

from ..localization import translate as _
from ..platform_tools import create_process, is_windows
from .network import NetworkError
from .wangp import WanGPClient

_launch_lock = asyncio.Lock()
_process: subprocess.Popen | None = None


def can_launch(url: str):
    endpoint = urlsplit(url)
    return (
        is_windows
        and endpoint.scheme == "http"
        and endpoint.hostname
        in (
            "localhost",
            "127.0.0.1",
            "::1",
        )
    )


def mcp_unavailable(error: NetworkError):
    return error.status in (404, 405, 502, 503, 504) or error.code in (
        QNetworkReply.NetworkError.ConnectionRefusedError,
        QNetworkReply.NetworkError.TimeoutError,
        QNetworkReply.NetworkError.OperationCanceledError,
    )


def launch_command(root: Path, url: str) -> list[str]:
    if not (root / "wgp.py").is_file():
        raise ValueError(_("The selected folder does not contain wgp.py."))
    endpoint = urlsplit(url)
    port = endpoint.port or 80
    host = "127.0.0.1" if endpoint.hostname == "localhost" else endpoint.hostname
    if host is None:
        raise ValueError(_("The WanGP MCP address is invalid."))
    args = [str(root / "wgp.py"), "--mcp-webui", "--mcp-host", host, "--mcp-port", str(port)]
    registry = root / "envs.json"
    if registry.is_file():
        try:
            data = json.loads(registry.read_text(encoding="utf-8-sig"))
            entry = data["envs"][data["active"]]
            prefix = (root / entry["path"]).resolve()
            kind = entry["type"]
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise ValueError(_("The WanGP environment in envs.json could not be read.")) from e
        if kind == "conda":
            python = prefix / "python.exe"
            candidates = [parent / "Scripts" / "conda.exe" for parent in (prefix, *prefix.parents)]
            conda = next((path for path in candidates if path.is_file()), None)
            if conda is None or not python.is_file() or not (prefix / "conda-meta").is_dir():
                raise ValueError(_("The Conda environment recorded by WanGP could not be found."))
            return [
                str(conda),
                "run",
                "--prefix",
                str(prefix),
                "--no-capture-output",
                str(python),
                *args,
            ]
        python = prefix if prefix.is_file() else prefix / "Scripts" / "python.exe"
        if kind in ("uv", "venv", "python") and python.is_file():
            return [str(python), *args]
        raise ValueError(_("The Python environment recorded by WanGP could not be found."))
    candidates = [
        root / name / "Scripts" / "python.exe" for name in ("env_uv", "venv", ".venv", "env")
    ]
    installed = [path for path in candidates if path.is_file()]
    if len(installed) != 1:
        raise ValueError(_("WanGP needs a registered environment or one local Python environment."))
    return [str(installed[0]), *args]


async def _check_wangp_process():
    command = (
        "$ErrorActionPreference='Stop'; "
        "$running = Get-CimInstance Win32_Process | Where-Object { "
        "$_.Name -match '^python[\\w.-]*\\.exe$' -and "
        "$_.CommandLine -match '(?i)(^|[\\s\\x22\\\\/])wgp\\.py($|[\\s\\x22])' }; "
        "if ($running) { exit 3 }"
    )
    process = await create_process(
        "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command
    )
    try:
        await asyncio.wait_for(process.communicate(), timeout=12)
    except (TimeoutError, asyncio.CancelledError):
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    if process.returncode == 3:
        raise RuntimeError(
            _("WanGP is already running. Enable MCP in its web UI and restart WanGP.")
        )
    if process.returncode != 0:
        raise RuntimeError(_("Could not verify whether WanGP is running. Start it manually."))


async def launch_and_connect(root: Path, client: WanGPClient, command: list[str]):
    global _process
    if not can_launch(client.url):
        raise ValueError(_("WanGP can only be launched locally on Windows."))
    async with _launch_lock:
        try:
            await client.connect(timeout=3)
            return
        except NetworkError as e:
            if e.code != QNetworkReply.NetworkError.ConnectionRefusedError:
                raise RuntimeError(
                    _("The MCP port is in use. Check the WanGP MCP settings.")
                ) from e
        if _process is None or _process.poll() is not None:
            await _check_wangp_process()
            env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
            _process = await asyncio.to_thread(
                subprocess.Popen,
                command,
                cwd=root,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        deadline = asyncio.get_running_loop().time() + 120
        while asyncio.get_running_loop().time() < deadline:
            if (code := _process.poll()) is not None:
                raise RuntimeError(
                    _("WanGP exited before MCP was ready (exit code {code}).", code=code)
                )
            try:
                await client.connect(timeout=3)
                return
            except NetworkError as e:
                if not mcp_unavailable(e):
                    raise
            await asyncio.sleep(1)
        raise TimeoutError(_("WanGP did not start MCP in time. Check WanGP and retry."))
