import json
import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from ai_diffusion.backend import server as server_module
from ai_diffusion.backend.server import Server

from .conftest import qtapp

root = Path(__file__).parent.parent
minimums = {"pillow": (13, 0, 0), "certifi": (2026, 10, 18), "pyjwt": (2, 14, 0), "uv": (0, 13, 4)}


def test_all_python_locks_respect_critical_security_floors():
    paths = list((root / "ai_diffusion/backend/requirements").glob("*.txt"))
    paths += [
        root / "ai_diffusion/backend/server_requirements.txt",
        root / "scripts/docker/requirements.txt",
    ]
    for path in paths:
        for name, version in re.findall(r"(?im)^([a-z0-9_-]+)==([0-9.]+)", path.read_text()):
            if name.lower() in minimums:
                assert tuple(map(int, version.split("."))) >= minimums[name.lower()], (
                    path,
                    name,
                    version,
                )


@pytest.mark.parametrize("use_uv", [True, False])
@qtapp
async def test_every_dependency_install_applies_security_constraints(tmp_path, monkeypatch, use_uv):
    server = Server(str(tmp_path))
    server._python_cmd = tmp_path / "python.exe"
    server._uv_cmd = tmp_path / "uv.exe" if use_uv else None
    execute = AsyncMock()
    monkeypatch.setattr(server_module, "_execute_process", execute)
    await server._pip_install("test", ["-r", "requirements.txt"], lambda *args: None)
    assert execute.await_args is not None
    cmd = execute.await_args_list[0].args[1]
    assert "--constraint" in cmd
    path = Path(cmd[cmd.index("--constraint") + 1])
    assert path.read_text().count("Pillow>=13.0.0") == 1

    assert execute.await_count == 2
    assert str(execute.await_args_list[1].args[1][-1]).endswith("dependency_security.py")


def test_manifest_versions_are_outside_all_reported_vulnerable_ranges():
    advisories = json.loads((root / "tests/data/security_advisories.json").read_text())
    for advisory in advisories:
        affected = SpecifierSet(advisory["affected"].replace(" ", ""))
        for name in advisory["manifests"]:
            versions = []
            for line in (root / name).read_text().splitlines():
                if not line or line[0].isspace() or line.startswith(("#", "-")):
                    continue
                requirement = Requirement(line)
                if requirement.name.lower() != advisory["package"]:
                    continue
                versions.extend(
                    Version(s.version) for s in requirement.specifier if s.operator in ("==", ">=")
                )
            assert versions, (name, advisory["id"], "Missing explicit safe version")
            assert not any(v in affected for v in versions), (name, advisory["id"], versions)
