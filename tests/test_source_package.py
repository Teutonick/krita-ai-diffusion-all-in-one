import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from scripts.source_package import build_source, collect_files


def test_source_archive_records_exact_bytes_without_private_files(tmp_path: Path):
    (tmp_path / "ai_diffusion").mkdir()
    (tmp_path / "ai_diffusion/__init__.py").write_text("version = 'test'\n")
    (tmp_path / "LICENSE").write_text("license")
    (tmp_path / ".appdata").mkdir()
    (tmp_path / ".appdata/secret.txt").write_text("private")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/.env").write_text("secret")
    archive = build_source(tmp_path, "test")
    manifest_path = archive.parent / "SOURCE-MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    assert archive.parent == tmp_path / "builds" / "test"
    assert not (tmp_path / "SOURCE-MANIFEST.json").exists()
    assert (
        manifest["files"]["ai_diffusion/__init__.py"]
        == hashlib.sha256((tmp_path / "ai_diffusion/__init__.py").read_bytes()).hexdigest()
    )
    with ZipFile(archive) as z:
        assert not any("secret" in p or ".env" in p or "/builds/" in p for p in z.namelist())
        assert (
            z.read("krita_ai_diffusion-test-source/SOURCE-MANIFEST.json")
            == manifest_path.read_bytes()
        )
        assert (
            z.read("krita_ai_diffusion-test-source/ai_diffusion/__init__.py")
            == (tmp_path / "ai_diffusion/__init__.py").read_bytes()
        )
    assert collect_files(tmp_path) == sorted(manifest["files"])


def test_extracted_source_rebuilds_without_git(tmp_path: Path):
    (tmp_path / "ai_diffusion").mkdir()
    (tmp_path / "ai_diffusion/__init__.py").write_text("version = 'test'\n")
    (tmp_path / "LICENSE").write_text("license")
    first = build_source(tmp_path, "test")
    with ZipFile(first) as archive:
        archive.extractall(tmp_path / "extracted")
    source = tmp_path / "extracted/krita_ai_diffusion-test-source"
    rebuilt = build_source(source, "test")
    with ZipFile(rebuilt) as archive:
        manifest = json.loads(archive.read("krita_ai_diffusion-test-source/SOURCE-MANIFEST.json"))
        assert (
            manifest["files"] == json.loads((source / "SOURCE-MANIFEST.json").read_text())["files"]
        )
    assert not (source / ".git").exists()
