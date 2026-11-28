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
    command = launch_command(root)
    assert command == [
        str(conda),
        "run",
        "--prefix",
        str(prefix),
        "--no-capture-output",
        str(python),
        str(root / "wgp.py"),
    ]


def test_wangp_does_not_guess_between_local_environments(tmp_path):
    (tmp_path / "wgp.py").touch()
    for name in ("env", ".venv"):
        python = tmp_path / name / "Scripts" / "python.exe"
        python.parent.mkdir(parents=True)
        python.touch()
    with pytest.raises(ValueError, match="one local Python environment"):
        launch_command(tmp_path)


def test_wangp_uses_port_from_selected_installation(monkeypatch, tmp_path):
    monkeypatch.setattr(wangp_launcher, "is_windows", True)
    (tmp_path / "wgp_config.json").write_text('{"mcp_port":8765}', encoding="utf-8")
    url = "http://localhost:8000/mcp"
    assert wangp_launcher.configured_mcp_url(tmp_path, url) == "http://127.0.0.1:8765/mcp"
    remote = "https://example.com/mcp"
    assert wangp_launcher.configured_mcp_url(tmp_path, remote) == remote


@qtapp
async def test_wangp_launches_after_connection_refused(monkeypatch, tmp_path):
    url = "http://localhost:8000/mcp"
    refused = NetworkError(QNetworkReply.NetworkError.ConnectionRefusedError, "refused", url)
    client = Mock(url=url, connect=AsyncMock(side_effect=[refused, None]))
    process = Mock()
    process.poll.return_value = None
    spawn = Mock(return_value=process)
    check = AsyncMock(return_value=False)
    monkeypatch.setattr(wangp_launcher, "is_windows", True)
    monkeypatch.setattr(wangp_launcher, "_process", None)
    monkeypatch.setattr(wangp_launcher, "_check_wangp_process", check)
    monkeypatch.setattr(wangp_launcher, "subprocess", Mock(Popen=spawn, CREATE_NEW_CONSOLE=16))
    await wangp_launcher.launch_and_connect(tmp_path, client, ["launcher", "wgp.py"])
    check.assert_awaited_once()
    spawn.assert_called_once()
    assert spawn.call_args.kwargs["creationflags"] == 16
    assert client.connect.await_count == 2
    await wangp_launcher.launch_and_connect(
        tmp_path, Mock(url=url, connect=AsyncMock()), ["launcher", "wgp.py"]
    )
    spawn.assert_called_once()


@qtapp
async def test_wangp_waits_for_existing_process_on_timeout(monkeypatch, tmp_path):
    url = "http://localhost:8000/mcp"
    timeout = NetworkError(QNetworkReply.NetworkError.TimeoutError, "timeout", url)
    client = Mock(url=url, connect=AsyncMock(side_effect=[timeout, None]))
    spawn = Mock()
    monkeypatch.setattr(wangp_launcher, "is_windows", True)
    monkeypatch.setattr(wangp_launcher, "_process", None)
    monkeypatch.setattr(wangp_launcher, "_check_wangp_process", AsyncMock(return_value=True))
    monkeypatch.setattr(wangp_launcher, "subprocess", Mock(Popen=spawn))
    await wangp_launcher.launch_and_connect(tmp_path, client, ["launcher", "wgp.py"])
    spawn.assert_not_called()
