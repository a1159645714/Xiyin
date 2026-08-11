from __future__ import annotations

import argparse
import ctypes
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path


PRESERVED_NAMES = {
    "app_settings.json",
    "cookies.json",
    "playwright_chrome_profile",
    "category_catalog.json",
    "category_catalog_home.json",
    "config_profiles",
    "output",
    "update.log",
    ".update_manifest_cache.json",
}


def log_message(target_dir: Path, message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with (target_dir / "update.log").open("a", encoding="utf-8") as file:
            file.write(f"[{timestamp}] {message}\n")
    except OSError:
        pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wait_for_process_exit(pid: int, timeout_seconds: int = 120) -> bool:
    if os.name == "nt":
        synchronize = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return True
        try:
            wait_result = ctypes.windll.kernel32.WaitForSingleObject(
                handle,
                timeout_seconds * 1000,
            )
            return wait_result == 0
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.25)
    return False


def safe_extract_archive(archive_path: Path, destination: Path) -> None:
    destination_resolved = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            member_path = (destination / info.filename).resolve()
            try:
                member_path.relative_to(destination_resolved)
            except ValueError as error:
                raise RuntimeError(f"更新包包含不安全路径: {info.filename}") from error
            if info.external_attr >> 16 & 0o170000 == 0o120000:
                raise RuntimeError(f"更新包不允许包含符号链接: {info.filename}")
        archive.extractall(destination)


def find_release_root(extracted_dir: Path, app_name: str) -> Path:
    if (extracted_dir / app_name).is_file():
        return extracted_dir

    children = [child for child in extracted_dir.iterdir() if child.name != "__MACOSX"]
    if len(children) == 1 and children[0].is_dir() and (children[0] / app_name).is_file():
        return children[0]
    raise RuntimeError(f"更新包中缺少 {app_name}")


def remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def apply_update_archive(
    archive_path: Path,
    target_dir: Path,
    app_name: str,
    expected_sha256: str,
) -> None:
    if sha256_file(archive_path).lower() != expected_sha256.lower():
        raise RuntimeError("更新包 SHA-256 校验失败")

    extract_dir = Path(tempfile.mkdtemp(prefix="xiyin_extract_"))
    backup_dir = target_dir.parent / f".{target_dir.name}_backup_{int(time.time())}"
    installed_names: list[str] = []
    backed_up_names: list[str] = []

    try:
        safe_extract_archive(archive_path, extract_dir)
        release_root = find_release_root(extract_dir, app_name)
        backup_dir.mkdir(parents=True, exist_ok=False)

        for source in release_root.iterdir():
            if source.name in PRESERVED_NAMES:
                continue
            destination = target_dir / source.name
            backup = backup_dir / source.name
            if destination.exists() or destination.is_symlink():
                shutil.move(str(destination), str(backup))
                backed_up_names.append(source.name)
            shutil.move(str(source), str(destination))
            installed_names.append(source.name)
    except Exception:
        for name in reversed(installed_names):
            remove_path(target_dir / name)
        for name in reversed(backed_up_names):
            backup = backup_dir / name
            if backup.exists() or backup.is_symlink():
                shutil.move(str(backup), str(target_dir / name))
        raise
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)

    shutil.rmtree(backup_dir, ignore_errors=True)


def restart_application(app_path: Path) -> None:
    subprocess.Popen(
        [str(app_path)],
        cwd=str(app_path.parent),
        close_fds=True,
        creationflags=(subprocess.DETACHED_PROCESS if os.name == "nt" else 0),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="XiYin Windows updater")
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--app", required=True, type=Path)
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--sha256", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target_dir = args.target.resolve()
    app_path = args.app.resolve()
    log_message(target_dir, "等待主程序退出")

    try:
        if not wait_for_process_exit(args.pid):
            raise RuntimeError("等待主程序退出超时")
        log_message(target_dir, "开始安装更新")
        apply_update_archive(
            args.archive.resolve(),
            target_dir,
            app_path.name,
            args.sha256,
        )
        log_message(target_dir, "更新安装完成，正在重新启动")
        restart_application(app_path)
        return 0
    except Exception as error:
        log_message(target_dir, f"更新失败: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
