from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from urllib.parse import urljoin

from config import APP_VERSION, UPDATE_MANIFEST_URL


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--notes", default="Feature improvements and fixes")
    args = parser.parse_args()

    dist_dir = args.dist.resolve()
    output_dir = args.output.resolve()
    expected_exe = dist_dir / "XiYinAutoUploader.exe"
    expected_updater = dist_dir / "XiYinUpdater.exe"
    if not expected_exe.is_file() or not expected_updater.is_file():
        raise SystemExit("发布目录缺少主程序或 XiYinUpdater.exe")

    output_dir.mkdir(parents=True, exist_ok=True)
    archive_base = output_dir / f"XiYinAutoUploader_v{APP_VERSION}"
    archive_path = Path(
        shutil.make_archive(
            str(archive_base),
            "zip",
            root_dir=dist_dir,
        )
    )
    digest = sha256_file(archive_path)
    download_url = urljoin(UPDATE_MANIFEST_URL, archive_path.name)
    manifest = {
        "download_url": download_url,
        "sha256": digest,
        "version": APP_VERSION,
        "notes": args.notes,
    }
    manifest_path = output_dir / "update.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )
    print(f"Release archive: {archive_path}")
    print(f"SHA-256: {digest}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
