import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from update_service import UpdateError, is_newer_version, parse_update_manifest
from updater_main import apply_update_archive, safe_extract_archive
from upload_release import cos_location, upload_release


class UpdateServiceTests(unittest.TestCase):
    def test_version_comparison_normalizes_missing_parts(self) -> None:
        self.assertTrue(is_newer_version("1.0.6", "1.0.5"))
        self.assertFalse(is_newer_version("1.0.5", "1.0.5"))
        self.assertFalse(is_newer_version("1.0", "1.0.0"))

    def test_manifest_matches_cos_format(self) -> None:
        manifest = parse_update_manifest(
            {
                "version": "1.0.6",
                "download_url": "https://example.com/updates/app.zip",
                "sha256": "a" * 64,
                "notes": "fixes",
            }
        )
        self.assertEqual(manifest.version, "1.0.6")

    def test_manifest_rejects_insecure_download(self) -> None:
        with self.assertRaises(UpdateError):
            parse_update_manifest(
                {
                    "version": "1.0.6",
                    "download_url": "http://example.com/app.zip",
                    "sha256": "a" * 64,
                }
            )

    def test_updater_replaces_program_and_preserves_user_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "app"
            target.mkdir()
            (target / "XiYinAutoUploader.exe").write_bytes(b"old")
            (target / "_internal").mkdir()
            (target / "_internal" / "old.txt").write_text("old", encoding="utf-8")
            (target / "app_settings.json").write_text("user settings", encoding="utf-8")
            (target / "playwright_chrome_profile").mkdir()
            (target / "playwright_chrome_profile" / "Login Data").write_text(
                "login",
                encoding="utf-8",
            )

            archive_path = root / "update.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("XiYinAutoUploader.exe", b"new")
                archive.writestr("XiYinUpdater.exe", b"updater")
                archive.writestr("_internal/new.txt", "new")
                archive.writestr("app_settings.json", "release default")

            digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            apply_update_archive(
                archive_path,
                target,
                "XiYinAutoUploader.exe",
                digest,
            )

            self.assertEqual((target / "XiYinAutoUploader.exe").read_bytes(), b"new")
            self.assertTrue((target / "_internal" / "new.txt").is_file())
            self.assertFalse((target / "_internal" / "old.txt").exists())
            self.assertEqual(
                (target / "app_settings.json").read_text(encoding="utf-8"),
                "user settings",
            )
            self.assertEqual(
                (target / "playwright_chrome_profile" / "Login Data").read_text(
                    encoding="utf-8"
                ),
                "login",
            )

    def test_archive_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "unsafe.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../outside.txt", "unsafe")
            with self.assertRaises(RuntimeError):
                safe_extract_archive(archive_path, root / "extract")

    def test_cos_location_uses_manifest_bucket_region_and_key(self) -> None:
        self.assertEqual(
            cos_location(
                "https://xiyin-updates-1302706245.cos.ap-chongqing.myqcloud.com/updates/update.json"
            ),
            (
                "xiyin-updates-1302706245",
                "ap-chongqing",
                "updates/update.json",
            ),
        )

    def test_cos_upload_publishes_archive_before_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            release_dir = Path(temp_dir)
            archive_path = release_dir / "XiYinAutoUploader_v1.0.6.zip"
            archive_path.write_bytes(b"release archive")
            digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            payload = {
                "download_url": (
                    "https://xiyin-updates-1302706245.cos.ap-chongqing.myqcloud.com/"
                    "updates/XiYinAutoUploader_v1.0.6.zip"
                ),
                "sha256": digest,
                "version": "1.0.6",
                "notes": "test",
            }
            (release_dir / "update.json").write_text(
                json.dumps(payload),
                encoding="utf-8",
            )

            response = MagicMock()
            response.json.return_value = payload
            response.raise_for_status.return_value = None
            client = MagicMock()
            with (
                patch.dict(
                    os.environ,
                    {
                        "TENCENTCLOUD_SECRET_ID": "test-id",
                        "TENCENTCLOUD_SECRET_KEY": "test-key",
                    },
                ),
                patch("upload_release.check_remote_version"),
                patch("upload_release.public_object_size", return_value=archive_path.stat().st_size),
                patch("upload_release.requests.get", return_value=response),
                patch("qcloud_cos.CosS3Client", return_value=client),
            ):
                upload_release(release_dir)

            method_names = [method_call[0] for method_call in client.method_calls]
            self.assertLess(
                method_names.index("upload_file"),
                method_names.index("put_object"),
            )


if __name__ == "__main__":
    unittest.main()
