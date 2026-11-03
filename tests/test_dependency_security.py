import importlib.util
import os
from pathlib import Path

import pytest

from ai_diffusion.backend.dependency_security import _krita_safe_checkpoint_shards, patch_accelerate


@pytest.mark.parametrize("name", ["../outside.safetensors", "nested/../../outside.safetensors", ""])
def test_checkpoint_shards_reject_traversal(tmp_path: Path, name):
    (tmp_path.parent / "outside.safetensors").write_bytes(b"weights")
    with pytest.raises(ValueError):
        _krita_safe_checkpoint_shards(str(tmp_path), {"weight": name})


def test_checkpoint_shards_reject_absolute_paths_and_non_files(tmp_path: Path):
    regular = tmp_path / "model.safetensors"
    regular.touch()
    for name in [str(regular), "missing.safetensors", "folder", None, 42]:
        with pytest.raises(ValueError):
            _krita_safe_checkpoint_shards(str(tmp_path), {"weight": name})


def test_checkpoint_shards_accept_nested_regular_files(tmp_path: Path):
    shard = tmp_path / "shards" / "model.safetensors"
    shard.parent.mkdir()
    shard.touch()
    assert _krita_safe_checkpoint_shards(
        str(tmp_path), {"a": "shards/model.safetensors", "b": "./shards/model.safetensors"}
    ) == [str(shard)]


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="Named pipes require POSIX")
def test_checkpoint_shards_reject_fifo_without_opening(tmp_path: Path):
    os.mkfifo(tmp_path / "pipe")  # pyright: ignore[reportAttributeAccessIssue]
    with pytest.raises(ValueError):
        _krita_safe_checkpoint_shards(str(tmp_path), {"weight": "pipe"})


def test_checkpoint_shards_reject_non_regular_files_on_windows(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(os.path, "isfile", lambda path: False)
    with pytest.raises(ValueError):
        _krita_safe_checkpoint_shards(str(tmp_path), {"weight": "pipe"})


def test_accelerate_patch_is_idempotent_and_executable(tmp_path: Path):
    module = tmp_path / "modeling.py"
    module.write_text(
        "import os\ndef load(checkpoint_folder, index):\n    if index:\n        checkpoint_files = sorted(list(set(index.values())))\n        checkpoint_files = [os.path.join(checkpoint_folder, f) for f in checkpoint_files]\n        return checkpoint_files\n"
    )
    assert patch_accelerate(module)
    first = module.read_bytes()
    assert not patch_accelerate(module)
    assert module.read_bytes() == first
    spec = importlib.util.spec_from_file_location("patched_accelerate_test", module)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    with pytest.raises(ValueError):
        loaded.load(str(tmp_path), {"weight": "../outside"})


def test_accelerate_patch_rejects_unknown_source_without_modifying_it(tmp_path: Path):
    module = tmp_path / "unknown.py"
    module.write_text("# unknown upstream version\n")
    before = module.read_bytes()
    with pytest.raises(RuntimeError, match="Unsupported Accelerate"):
        patch_accelerate(module)
    assert module.read_bytes() == before
