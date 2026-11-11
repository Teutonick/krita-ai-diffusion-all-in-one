import os
import subprocess
import sys
from pathlib import Path
from shutil import copy, copytree, ignore_patterns, make_archive
from tempfile import TemporaryDirectory
from typing import NamedTuple

from markdown import markdown

sys.path.append(str(Path(__file__).parent.parent))
import ai_diffusion
from ai_diffusion.backend.resources import update_model_checksums

sys.path.append(str(Path(__file__).parent))
import translation
from source_package import build_source, write_checksums

root = Path(__file__).parent.parent
build_dir = root / "builds" / ai_diffusion.__version__
version = ai_diffusion.__version__
package_name = f"krita_ai_diffusion-{version}"


def convert_markdown_to_html(markdown_file: Path, html_file: Path):
    with open(markdown_file, "r", encoding="utf-8") as f:
        text = f.read()
    html = markdown(text, extensions=["fenced_code", "codehilite", "tables"])
    html = html.replace('href="ai_diffusion/licenses/', 'href="licenses/')
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html)


def update_server_requirements():
    class Cfg(NamedTuple):
        platform: str
        extra_index: str | None = None
        override: str | None = None
        dependencies: str | None = None
        os_version: str | None = None

    req_dir = root / "ai_diffusion" / "backend" / "requirements"
    configs = {
        "linux-cpu": Cfg("x86_64-unknown-linux-gnu", "cpu"),
        "linux-cuda": Cfg("x86_64-unknown-linux-gnu", "cu130"),
        "linux-cuda126": Cfg("x86_64-unknown-linux-gnu", "cu126"),
        "linux-xpu": Cfg("x86_64-unknown-linux-gnu", "xpu"),
        "linux-rocm": Cfg("x86_64-unknown-linux-gnu", "rocm7.2"),
        "macos-cpu": Cfg("aarch64-apple-darwin", os_version="14.0"),
        "macos-mps": Cfg("aarch64-apple-darwin", os_version="14.0"),
        "windows-cpu": Cfg("x86_64-pc-windows-msvc", "cpu"),
        "windows-cuda": Cfg("x86_64-pc-windows-msvc", "cu130"),
        "windows-cuda126": Cfg("x86_64-pc-windows-msvc", "cu126"),
        "windows-xpu": Cfg("x86_64-pc-windows-msvc", "xpu"),
        "windows-rocm": Cfg(
            "x86_64-pc-windows-msvc", None, "rocm-windows.in", "rocm-windows-deps.in"
        ),
    }
    for name, cfg in configs.items():
        cmd = ["uv", "pip", "compile", str((req_dir / "base.in").relative_to(root))]
        if additional_reqs := cfg.dependencies:
            cmd += [str((req_dir / additional_reqs).relative_to(root))]
        cmd += ["--emit-index-annotation", "--emit-index-url"]
        cmd += ["--index-strategy", "unsafe-best-match"]
        cmd += ["--python-platform", cfg.platform, "--python-version", "3.12"]
        if override := cfg.override:
            cmd += ["--override", str((req_dir / override).relative_to(root))]
        cmd += ["--index-url", "https://pypi.org/simple"]
        if extra_index := cfg.extra_index:
            cmd += ["--extra-index-url", f"https://download.pytorch.org/whl/{extra_index}"]
        cmd += ["--upgrade", "--quiet"]
        cmd += ["-o", str((req_dir / f"{name}.txt").relative_to(root))]
        env = os.environ.copy()
        if cfg.platform == "aarch64-apple-darwin" and cfg.os_version is not None:
            env["MACOSX_DEPLOYMENT_TARGET"] = cfg.os_version
        print(f"{name}.txt")
        subprocess.run(cmd, cwd=root, check=True, env=env)


def precheck():
    translation.update_template()
    translation.update_all()

    update_model_checksums(root / "scripts" / "downloads")


def build_package():
    precheck()
    source_archive = build_source(root, version, build_dir)
    staging_root = root / ".build"
    staging_root.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="package-", dir=staging_root) as temporary:
        package_dir = Path(temporary)
        copy(root / "ai_diffusion.desktop", package_dir)
        plugin_src = root / "ai_diffusion"
        plugin_dst = package_dir / "ai_diffusion"

        def ignore(path, names):
            if Path(path) == plugin_src / "websockets":
                return [name for name in names if name not in ("src", "LICENSE")]
            return ignore_patterns(".*", "*.pyc", "__pycache__", "debugpy")(path, names)

        copytree(plugin_src, plugin_dst, ignore=ignore)
        copytree(root / "custom_workflows", plugin_dst / "presets" / "workflows")
        copy(root / "scripts" / "download_models.py", plugin_dst)
        for name in [
            "LICENSE",
            "BUILD-REPORT.md",
            "SECURITY-UPDATE.md",
            "THIRD-PARTY-NOTICES.md",
            "RELEASE-NOTES.md",
        ]:
            copy(root / name, plugin_dst)
        copy(build_dir / "SOURCE-MANIFEST.json", plugin_dst)
        convert_markdown_to_html(root / "README.md", plugin_dst / "manual.html")
        guide = plugin_dst / "docs" / "MINIMAX-H3-IMAGE.md"
        guide.parent.mkdir(exist_ok=True)
        copy(root / "docs" / guide.name, guide)
        make_archive(str(build_dir / package_name), "zip", package_dir)
    write_checksums(build_dir, version, [build_dir / f"{package_name}.zip", source_archive])
    print(f"Build artifacts: {build_dir.relative_to(root)}")
    print(f"Corresponding source: {source_archive.name}")
    print(f"Checksums: SHA256SUMS-{version}.txt")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"

    if cmd == "build":
        print("Building package", build_dir / package_name)
        build_package()

    elif cmd == "check":
        print("Performing precheck without building")
        precheck()

    elif cmd == "update":
        print("Updating server requirements without building")
        update_server_requirements()

    else:
        raise SystemExit("Usage: python scripts/package.py [build|check|update]")
