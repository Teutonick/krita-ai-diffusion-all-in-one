import asyncio
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

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
    return error.status in (404, 405, 500, 502, 503, 504) or error.code in (
        QNetworkReply.NetworkError.ConnectionRefusedError,
        QNetworkReply.NetworkError.RemoteHostClosedError,
        QNetworkReply.NetworkError.TimeoutError,
        QNetworkReply.NetworkError.OperationCanceledError,
    )


def configured_mcp_url(root: Path, url: str):
    if not can_launch(url):
        return url
    try:
        data = json.loads((root / "wgp_config.json").read_text(encoding="utf-8-sig"))
        port = data.get("mcp_port") if isinstance(data, dict) else None
    except (OSError, ValueError):
        return url
    if type(port) is not int or not 0 < port < 65536:
        return url
    endpoint = urlsplit(url)
    return urlunsplit(endpoint._replace(netloc=f"127.0.0.1:{port}"))


def launch_command(root: Path) -> list[str]:
    if not (root / "wgp.py").is_file():
        raise ValueError(_("The selected folder does not contain wgp.py."))
    args = [str(root / "wgp.py")]
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
    if process.returncode not in (0, 3):
        raise RuntimeError(_("Could not verify whether WanGP is running. Start it manually."))
    return process.returncode == 3


async def launch_and_connect(root: Path, client: WanGPClient, command: list[str]):
    global _process
    if not can_launch(client.url):
        raise ValueError(_("WanGP can only be launched locally on Windows."))
    async with _launch_lock:
        try:
            await client.connect(timeout=3)
            return
        except NetworkError as e:
            if not mcp_unavailable(e):
                raise
        owned = _process if _process is not None and _process.poll() is None else None
        running = owned is not None or await _check_wangp_process()
        if not running:
            env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
            _process = owned = await asyncio.to_thread(
                subprocess.Popen,
                command,
                cwd=root,
                env=env,
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
        deadline = asyncio.get_running_loop().time() + (120 if owned else 20)
        while asyncio.get_running_loop().time() < deadline:
            if owned is not None and (code := owned.poll()) is not None:
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
        raise TimeoutError(
            _(
                "WanGP MCP did not respond. Check Enable MCP with Web UI in the WanGP terminal or settings."
            )
        )
