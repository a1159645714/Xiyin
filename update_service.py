from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

from config import BASE_DIR, UPDATE_MANIFEST_CACHE_FILE, UPDATE_MANIFEST_URL


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdateManifest:
    version: str
    download_url: str
    sha256: str
    notes: str = ""
    minimum_supported_version: str = ""
    disabled_versions: tuple[str, ...] = ()
    force_update: bool = False
    message: str = ""


def parse_version(value: str) -> tuple[int, ...]:
    normalized = value.strip().lower().removeprefix("v")
    if not normalized:
        raise UpdateError("更新版本号为空")

    parts: list[int] = []
    for part in normalized.split("."):
        digits = "".join(character for character in part if character.isdigit())
        if not digits:
            raise UpdateError(f"无法识别版本号: {value}")
        parts.append(int(digits))
    return tuple(parts)


def is_newer_version(candidate: str, current: str) -> bool:
    candidate_parts = parse_version(candidate)
    current_parts = parse_version(current)
    width = max(len(candidate_parts), len(current_parts))
    return candidate_parts + (0,) * (width - len(candidate_parts)) > current_parts + (0,) * (
        width - len(current_parts)
    )


def versions_equal(left: str, right: str) -> bool:
    return not is_newer_version(left, right) and not is_newer_version(right, left)


def is_version_disabled(manifest: UpdateManifest, current_version: str) -> bool:
    if any(versions_equal(version, current_version) for version in manifest.disabled_versions):
        return True
    if manifest.minimum_supported_version:
        return is_newer_version(manifest.minimum_supported_version, current_version)
    return False


def is_update_required(manifest: UpdateManifest, current_version: str) -> bool:
    return is_version_disabled(manifest, current_version) or (
        manifest.force_update and is_newer_version(manifest.version, current_version)
    )


def parse_update_manifest(payload: object) -> UpdateManifest:
    if not isinstance(payload, dict):
        raise UpdateError("更新清单格式错误")

    version = str(payload.get("version", "")).strip()
    download_url = str(payload.get("download_url", "")).strip()
    sha256 = str(payload.get("sha256", "")).strip().lower()
    notes = str(payload.get("notes", "")).strip()
    minimum_supported_version = str(payload.get("minimum_supported_version", "")).strip()
    raw_disabled_versions = payload.get("disabled_versions", [])
    force_update = payload.get("force_update", False)
    message = str(payload.get("message", "")).strip()

    parse_version(version)
    if not download_url.startswith("https://"):
        raise UpdateError("更新包必须使用 HTTPS 地址")
    if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
        raise UpdateError("更新清单中的 SHA-256 无效")
    if minimum_supported_version:
        parse_version(minimum_supported_version)
    if not isinstance(raw_disabled_versions, list):
        raise UpdateError("disabled_versions 必须是版本号列表")
    disabled_versions = tuple(str(value).strip() for value in raw_disabled_versions)
    for disabled_version in disabled_versions:
        parse_version(disabled_version)
    if not isinstance(force_update, bool):
        raise UpdateError("force_update 必须是布尔值")

    return UpdateManifest(
        version=version,
        download_url=download_url,
        sha256=sha256,
        notes=notes,
        minimum_supported_version=minimum_supported_version,
        disabled_versions=disabled_versions,
        force_update=force_update,
        message=message,
    )


def manifest_to_dict(manifest: UpdateManifest) -> dict[str, object]:
    return {
        "download_url": manifest.download_url,
        "sha256": manifest.sha256,
        "version": manifest.version,
        "notes": manifest.notes,
        "minimum_supported_version": manifest.minimum_supported_version,
        "disabled_versions": list(manifest.disabled_versions),
        "force_update": manifest.force_update,
        "message": manifest.message,
    }


def save_cached_manifest(manifest: UpdateManifest) -> None:
    temporary_path = UPDATE_MANIFEST_CACHE_FILE.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(manifest_to_dict(manifest), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(UPDATE_MANIFEST_CACHE_FILE)


def load_cached_manifest() -> UpdateManifest | None:
    if not UPDATE_MANIFEST_CACHE_FILE.is_file():
        return None
    try:
        payload = json.loads(UPDATE_MANIFEST_CACHE_FILE.read_text(encoding="utf-8"))
        return parse_update_manifest(payload)
    except (OSError, ValueError, UpdateError):
        return None


def fetch_update_manifest(
    manifest_url: str = UPDATE_MANIFEST_URL,
    *,
    timeout: int = 15,
) -> UpdateManifest:
    try:
        response = requests.get(manifest_url, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, json.JSONDecodeError, ValueError) as error:
        raise UpdateError(f"获取更新清单失败: {error}") from error
    return parse_update_manifest(payload)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_update(
    manifest: UpdateManifest,
    *,
    progress_callback: Callable[[int], None] | None = None,
    timeout: tuple[int, int] = (15, 120),
) -> Path:
    download_dir = Path(tempfile.mkdtemp(prefix="xiyin_update_"))
    archive_path = download_dir / f"XiYinAutoUploader_v{manifest.version}.zip"

    try:
        with requests.get(manifest.download_url, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            total_size = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            last_progress = -1
            with archive_path.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    output.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total_size > 0:
                        progress = min(99, int(downloaded * 100 / total_size))
                        if progress != last_progress:
                            progress_callback(progress)
                            last_progress = progress
    except (requests.RequestException, OSError, ValueError) as error:
        shutil.rmtree(download_dir, ignore_errors=True)
        raise UpdateError(f"下载更新包失败: {error}") from error

    actual_sha256 = sha256_file(archive_path)
    if actual_sha256 != manifest.sha256:
        shutil.rmtree(download_dir, ignore_errors=True)
        raise UpdateError("更新包校验失败，文件可能不完整或已被篡改")

    if progress_callback:
        progress_callback(100)
    return archive_path


def updater_path() -> Path:
    return BASE_DIR / "XiYinUpdater.exe"


def can_install_updates() -> bool:
    return bool(getattr(sys, "frozen", False))


def launch_updater(archive_path: Path, expected_sha256: str) -> None:
    source_updater = updater_path()
    if not source_updater.is_file():
        raise UpdateError("缺少 XiYinUpdater.exe，无法安装更新")

    temp_updater_dir = Path(tempfile.mkdtemp(prefix="xiyin_updater_"))
    temp_updater = temp_updater_dir / source_updater.name
    try:
        shutil.copy2(source_updater, temp_updater)
        creation_flags = 0
        if os.name == "nt":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        subprocess.Popen(
            [
                str(temp_updater),
                "--archive",
                str(archive_path),
                "--target",
                str(BASE_DIR),
                "--app",
                str(Path(sys.executable).resolve()),
                "--pid",
                str(os.getpid()),
                "--sha256",
                expected_sha256,
            ],
            close_fds=True,
            creationflags=creation_flags,
        )
    except (OSError, subprocess.SubprocessError) as error:
        shutil.rmtree(temp_updater_dir, ignore_errors=True)
        raise UpdateError(f"无法启动更新程序: {error}") from error
