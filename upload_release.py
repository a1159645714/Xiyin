from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import requests

from config import UPDATE_MANIFEST_URL
from update_service import UpdateManifest, is_newer_version, parse_update_manifest, sha256_file


SECRET_ID_ENV = "TENCENTCLOUD_SECRET_ID"
SECRET_KEY_ENV = "TENCENTCLOUD_SECRET_KEY"
SESSION_TOKEN_ENV = "TENCENTCLOUD_SESSION_TOKEN"


def cos_location(url: str) -> tuple[str, str, str]:
    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    if ".cos." not in hostname:
        raise RuntimeError(f"无法从 COS 地址识别存储桶和地域: {url}")
    bucket, endpoint = hostname.split(".cos.", 1)
    region = endpoint.split(".", 1)[0]
    key = parsed.path.lstrip("/")
    if not bucket or not region or not key:
        raise RuntimeError(f"COS 地址不完整: {url}")
    return bucket, region, key


def load_release(release_dir: Path) -> tuple[Path, Path, UpdateManifest]:
    manifest_path = release_dir / "update.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"缺少发布清单: {manifest_path}")

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = parse_update_manifest(payload)
    archive_name = PurePosixPath(urlsplit(manifest.download_url).path).name
    archive_path = release_dir / archive_name
    if not archive_path.is_file():
        raise RuntimeError(f"缺少更新包: {archive_path}")
    if sha256_file(archive_path) != manifest.sha256:
        raise RuntimeError("本地更新包 SHA-256 与 update.json 不一致")
    return manifest_path, archive_path, manifest


def check_remote_version(manifest, *, force: bool) -> None:
    try:
        response = requests.get(
            UPDATE_MANIFEST_URL,
            params={"check": int(time.time())},
            timeout=15,
        )
        if response.status_code == 404:
            return
        response.raise_for_status()
        remote_manifest = parse_update_manifest(response.json())
    except (requests.RequestException, ValueError) as error:
        print(f"警告: 无法读取线上版本，将继续上传: {error}")
        return

    if force:
        return
    if not is_newer_version(manifest.version, remote_manifest.version):
        raise RuntimeError(
            f"本地版本 v{manifest.version} 不高于线上版本 v{remote_manifest.version}。"
            "请先升级 APP_VERSION；确需覆盖时单独运行 upload_release.py --force。"
        )


def public_object_size(url: str) -> int:
    response = requests.head(
        url,
        params={"verify": int(time.time())},
        timeout=30,
        allow_redirects=True,
    )
    response.raise_for_status()
    return int(response.headers.get("Content-Length", -1))


def upload_archive(client, bucket: str, key: str, archive_path: Path) -> None:
    headers = {
        "ContentType": "application/zip",
        "CacheControl": "public, max-age=31536000, immutable",
    }
    try:
        client.upload_file(
            Bucket=bucket,
            LocalFilePath=str(archive_path),
            Key=key,
            PartSize=10,
            MAXThread=5,
            **headers,
        )
        return
    except Exception as error:
        get_error_code = getattr(error, "get_error_code", None)
        error_code = get_error_code() if callable(get_error_code) else ""
        if error_code != "AccessDenied":
            raise

    print("没有分片任务查询权限，改用单次对象上传")
    with archive_path.open("rb") as archive_file:
        client.put_object(
            Bucket=bucket,
            Body=archive_file,
            Key=key,
            **headers,
        )


def upload_release(release_dir: Path, *, force: bool = False) -> None:
    secret_id = os.environ.get(SECRET_ID_ENV, "").strip()
    secret_key = os.environ.get(SECRET_KEY_ENV, "").strip()
    session_token = os.environ.get(SESSION_TOKEN_ENV, "").strip() or None
    if not secret_id or not secret_key:
        raise RuntimeError(
            f"未配置腾讯云密钥。请先设置 {SECRET_ID_ENV} 和 {SECRET_KEY_ENV} 环境变量。"
        )

    manifest_path, archive_path, manifest = load_release(release_dir)
    check_remote_version(manifest, force=force)
    bucket, region, manifest_key = cos_location(UPDATE_MANIFEST_URL)
    archive_bucket, archive_region, archive_key = cos_location(manifest.download_url)
    if (archive_bucket, archive_region) != (bucket, region):
        raise RuntimeError("更新包和更新清单必须位于同一个 COS 存储桶及地域")

    from qcloud_cos import CosConfig, CosS3Client

    client = CosS3Client(
        CosConfig(
            Region=region,
            SecretId=secret_id,
            SecretKey=secret_key,
            Token=session_token,
        )
    )

    print(f"正在上传更新包: cos://{bucket}/{archive_key}")
    upload_archive(client, bucket, archive_key, archive_path)

    remote_size = public_object_size(manifest.download_url)
    if remote_size != archive_path.stat().st_size:
        raise RuntimeError(
            f"更新包公开访问校验失败: 线上大小 {remote_size}，本地大小 {archive_path.stat().st_size}"
        )
    print("更新包上传并公开访问验证成功")

    print(f"正在发布更新清单: cos://{bucket}/{manifest_key}")
    client.put_object(
        Bucket=bucket,
        Body=manifest_path.read_bytes(),
        Key=manifest_key,
        ContentType="application/json; charset=utf-8",
        CacheControl="no-cache, no-store, must-revalidate",
    )

    response = requests.get(
        UPDATE_MANIFEST_URL,
        params={"verify": int(time.time())},
        timeout=30,
    )
    response.raise_for_status()
    online_manifest = parse_update_manifest(response.json())
    if online_manifest != manifest:
        raise RuntimeError("线上 update.json 与本地发布清单不一致")
    print(f"COS 发布完成: v{manifest.version}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload XiYin release to Tencent COS")
    parser.add_argument("--release", type=Path, default=Path("release"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        upload_release(args.release.resolve(), force=args.force)
        return 0
    except Exception as error:
        print(f"COS 上传失败: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
