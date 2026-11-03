from __future__ import annotations

import importlib.util
import inspect
import os
from pathlib import Path


def _krita_safe_checkpoint_shards(checkpoint_folder, index):
    folder = os.path.abspath(checkpoint_folder)
    shards = []
    for name in index.values():
        if not isinstance(name, str) or not name or os.path.isabs(name):
            raise ValueError("Invalid checkpoint shard path")
        target = os.path.abspath(os.path.join(folder, name))
        try:
            contained = os.path.commonpath([folder, target]) == folder
        except ValueError:
            contained = False
        if not contained or not os.path.isfile(target):
            raise ValueError("Checkpoint shard must be a regular file inside its folder")
        shards.append(target)
    return sorted(set(shards))


def patch_accelerate(module_path: Path):
    marker = "# Krita dependency security: GHSA-4j2p-28q2-5m79"
    source = module_path.read_text(encoding="utf-8")
    if marker in source:
        return False
    original = (
        "        checkpoint_files = sorted(list(set(index.values())))\n"
        "        checkpoint_files = [os.path.join(checkpoint_folder, f) for f in checkpoint_files]"
    )
    if source.count(original) != 1:
        raise RuntimeError(
            "Unsupported Accelerate source: checkpoint safety fix could not be applied"
        )
    source = source.replace(
        original,
        "        checkpoint_files = _krita_safe_checkpoint_shards(checkpoint_folder, index)",
    )
    source += "\n\n" + marker + "\n" + inspect.getsource(_krita_safe_checkpoint_shards)
    compile(source, str(module_path), "exec")
    temporary = module_path.with_suffix(".py.krita-security.tmp")
    temporary.write_text(source, encoding="utf-8")
    temporary.replace(module_path)
    return True


def apply_dependency_fixes():
    spec = importlib.util.find_spec("accelerate")
    if spec is not None and spec.origin:
        module_path = Path(spec.origin).parent / "utils" / "modeling.py"
        if patch_accelerate(module_path):
            print("Applied Accelerate checkpoint path and regular-file protection")


if __name__ == "__main__":
    apply_dependency_fixes()
