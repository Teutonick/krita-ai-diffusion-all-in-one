from __future__ import annotations

import importlib.util
from pathlib import Path
from tempfile import NamedTemporaryFile


def patch_file(path: Path, replacements: list[tuple[str, str]]):
    if not path.is_file():
        return
    marker = "# Krita managed translation: reuse cached resources"
    source = path.read_text(encoding="utf-8")
    if marker in source:
        return
    for old, new in replacements:
        if source.count(old) != 1:
            print(f"Managed translation cache: unsupported source in {path}")
            return
        source = source.replace(old, new)
    source += f"\n{marker}\n"
    compile(source, str(path), "exec")
    with NamedTemporaryFile(dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        try:
            file.write(source.encode("utf-8"))
            file.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def apply_translation_cache(comfy_dir: Path):
    spec = importlib.util.find_spec("argostranslate")
    if spec is None or spec.origin is None:
        return
    patch_file(
        Path(spec.origin).with_name("sbd.py"),
        [
            (
                '                logging_level="WARNING",\n',
                (
                    '                logging_level="WARNING",\n'
                    '                download_method="reuse_resources",\n'
                ),
            )
        ],
    )
    patch_file(
        comfy_dir / "custom_nodes" / "comfyui-tooling-nodes" / "translation.py",
        [
            (
                (
                    "        from argostranslate.package import update_package_index, get_available_packages\n"
                    "\n        update_package_index()\n"
                    "        list = get_available_packages()\n"
                    '        return [(l.from_code, l.from_name) for l in list if l.to_code == "en"]\n'
                ),
                (
                    "        from argostranslate import settings\n"
                    "        from argostranslate.package import get_installed_packages\n"
                    "\n        packages = get_installed_packages()\n"
                    "        if settings.local_package_index.is_file() or not packages:\n"
                    "            packages += _available_packages()\n"
                    '        return sorted({(p.from_code, p.from_name) for p in packages if p.to_code == "en"})\n'
                ),
            ),
            (
                "\ndef translate_chunk(text: str, language: str):",
                (
                    "\ndef _available_packages(*, refresh=False):\n"
                    "    from argostranslate import settings\n"
                    "    from argostranslate.package import get_available_packages, update_package_index\n"
                    "\n    if refresh or not settings.local_package_index.is_file():\n"
                    "        update_package_index()\n"
                    "    if settings.local_package_index.is_file():\n"
                    "        return get_available_packages()\n"
                    "    return []\n"
                    "\n\ndef translate_chunk(text: str, language: str):"
                ),
            ),
            (
                "        from argostranslate.package import get_installed_packages, get_available_packages\n",
                "        from argostranslate.package import get_installed_packages\n",
            ),
            (
                (
                    "            available = get_available_packages()\n"
                    "            pkg = next(\n"
                    "                (p for p in available if p.from_code == language and p.to_code == target), None\n"
                    "            )\n"
                    '            assert pkg, f"Couldn\'t find package for translation from {language}"'
                ),
                (
                    "            from argostranslate import settings\n"
                    "\n            has_index = settings.local_package_index.is_file()\n"
                    "            available = _available_packages()\n"
                    "            pkg = next((p for p in available if p.from_code == language and p.to_code == target), None)\n"
                    "            if pkg is None and has_index:\n"
                    "                available = _available_packages(refresh=True)\n"
                    "                pkg = next((p for p in available if p.from_code == language and p.to_code == target), None)\n"
                    "            if pkg is None:\n"
                    '                raise RuntimeError(f"Translation package {language} → {target} is unavailable. Check the connection and retry.")'
                ),
            ),
            ('        languages = [code for code, name in available_languages()] + ["en"]\n', ""),
            (
                (
                    "            if lang not in languages:\n"
                    "                raise ValueError(\n"
                    '                    f"Invalid language directive {m.group(0)} - {lang} is not a known language code."\n'
                    "                    f\" Available languages: {', '.join(languages)}\"\n"
                    "                )\n"
                ),
                "",
            ),
        ],
    )


if __name__ == "__main__":
    apply_translation_cache(Path.cwd())
