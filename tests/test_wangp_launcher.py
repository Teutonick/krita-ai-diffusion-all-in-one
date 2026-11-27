import json
from unittest.mock import AsyncMock, Mock

import pytest
from PyQt5.QtNetwork import QNetworkReply

from ai_diffusion.backend import wangp_launcher
from ai_diffusion.backend.network import NetworkError
from ai_diffusion.backend.wangp_launcher import launch_command

from .conftest import qtapp


def test_wangp_uses_registered_conda_prefix(tmp_path):
    root = tmp_path / "Wan2GP"
    root.mkdir()
    (root / "wgp.py").touch()
    base = tmp_path / "Conda"
    prefix = base / "envs" / "wan2gp"
    (prefix / "conda-meta").mkdir(parents=True)
    python = prefix / "python.exe"
    python.touch()
    conda = base / "Scripts" / "conda.exe"
    conda.parent.mkdir()
    conda.touch()
    (root / "envs.json").write_text(
        json.dumps({
            "active": "wan2gp",
            "envs": {"wan2gp": {"type": "conda", "path": str(prefix)}},
        }),
        encoding="utf-8",
    )
    command = launch_command(root, "http://localhost:8765/mcp")
    assert command == [
        str(conda),
        "run",
        "--prefix",
        str(prefix),
        "--no-capture-output",
        str(python),
        str(root / "wgp.py"),
        "--mcp-webui",
        "--mcp-host",
        "127.0.0.1",
        "--mcp-port",
        "8765",
    ]


def test_wangp_does_not_guess_between_local_environments(tmp_path):
    (tmp_path / "wgp.py").touch()
    for name in ("env", ".venv"):
        python = tmp_path / name / "Scripts" / "python.exe"
        python.parent.mkdir(parents=True)
        python.touch()
    with pytest.raises(ValueError, match="one local Python environment"):
        launch_command(tmp_path, "http://localhost:8000/mcp")


@qtapp
async def test_wangp_launches_after_connection_refused(monkeypatch, tmp_path):
    url = "http://localhost:8000/mcp"
    refused = NetworkError(QNetworkReply.NetworkError.ConnectionRefusedError, "refused", url)
    client = Mock(url=url, connect=AsyncMock(side_effect=[refused, None]))
    process = Mock()
    process.poll.return_value = None
    spawn = Mock(return_value=process)
    check = AsyncMock()
    monkeypatch.setattr(wangp_launcher, "is_windows", True)
    monkeypatch.setattr(wangp_launcher, "_process", None)
    monkeypatch.setattr(wangp_launcher, "_check_wangp_process", check)
    monkeypatch.setattr(wangp_launcher, "subprocess", Mock(Popen=spawn, DEVNULL=-3))
    await wangp_launcher.launch_and_connect(tmp_path, client, ["launcher", "wgp.py"])
    check.assert_awaited_once()
    spawn.assert_called_once()
    assert client.connect.await_count == 2
    await wangp_launcher.launch_and_connect(
        tmp_path, Mock(url=url, connect=AsyncMock()), ["launcher", "wgp.py"]
    )
    spawn.assert_called_once()
