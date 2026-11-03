#!/usr/bin/env python3
"""
Download test image fixtures and verify their checksums.

Usage:
    python images.py [download]
"""

import argparse
import hashlib
import sys
from pathlib import Path

import requests

root_dir = Path(__file__).parent.parent
image_dir = root_dir / "tests" / "images"

MANIFEST_FILE = image_dir / "manifest.txt"
BASE_URL = "https://lfs.interstice.cloud"
REPO_NAME = "krita-ai-diffusion"


def compute_sha256(file_path: Path) -> str:
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def compute_key(file_path: Path, sha256: str) -> str:
    rel_path = file_path.relative_to(image_dir).as_posix()
    return f"{REPO_NAME}/{rel_path}/{sha256}"


def compute_url(file_path: Path, sha256: str) -> str:
    return f"{BASE_URL}/{compute_key(file_path, sha256)}"


def load_manifest() -> dict[str, str]:
    manifest = {}
    if not MANIFEST_FILE.exists():
        return manifest

    with open(MANIFEST_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                local_filepath = parts[0]
                sha256 = parts[1]
                manifest[local_filepath] = sha256

    return manifest


def download_images() -> None:
    manifest = load_manifest()

    if not manifest:
        print("No manifest file found or manifest is empty.")
        return

    print(f"Downloading {len(manifest)} images...")
    success_count = 0
    skip_count = 0
    error_count = 0

    for local_filepath, expected_sha256 in manifest.items():
        local_path = image_dir / local_filepath

        if local_path.exists():
            actual_sha256 = compute_sha256(local_path)
            if actual_sha256 == expected_sha256:
                print(f"✓ {local_filepath} (already up-to-date)")
                skip_count += 1
                continue
            else:
                print(f"⟳ {local_filepath} (outdated, re-downloading)")

        local_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            url = compute_url(local_path, expected_sha256)
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            with open(local_path, "wb") as f:
                f.write(response.content)

            actual_sha256 = compute_sha256(local_path)
            if actual_sha256 == expected_sha256:
                print(f"✓ {local_filepath} (downloaded)")
                success_count += 1
            else:
                print(f"✗ {local_filepath} (SHA256 mismatch after download)")
                error_count += 1
                local_path.unlink()

        except Exception as e:
            print(f"✗ {local_filepath} (download failed: {e})")
            error_count += 1
            if local_path.exists():
                local_path.unlink()

    print(
        f"\nDownload complete: {success_count} downloaded, {skip_count} skipped, {error_count} errors"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Download test image fixtures")
    parser.add_argument(
        "action",
        nargs="?",
        default="download",
        choices=["download"],
        help="Action to perform (default: download)",
    )

    parser.parse_args()

    try:
        download_images()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
