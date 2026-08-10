import tempfile
import unittest
from pathlib import Path

from real_photo_library import scan_real_photo_library


class RealPhotoLibraryTests(unittest.TestCase):
    def test_scans_direct_product_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            product = Path(temp_dir) / "商品A"
            (product / "本体").mkdir(parents=True)
            (product / "包装").mkdir()
            (product / "产品图").mkdir()
            (product / "本体" / "a.jpg").touch()
            (product / "包装" / "a.jpg").touch()
            (product / "产品图" / "a.jpg").touch()
            (product / "商品视频.mp4").touch()

            items = scan_real_photo_library(temp_dir)

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].product_name, "商品A")
            self.assertEqual(items[0].variant_name, "")
            self.assertEqual(items[0].video_file.name, "商品视频.mp4")

    def test_scans_variant_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            product = Path(temp_dir) / "商品B"
            for name in ("红色", "蓝色"):
                body = product / name / "本体"
                body.mkdir(parents=True)
                (body / "main.png").touch()
                product_images = product / name / "产品图"
                product_images.mkdir()
                (product_images / "product.png").touch()

            items = scan_real_photo_library(temp_dir)

            self.assertEqual([item.variant_name for item in items], ["红色", "蓝色"])
            self.assertTrue(all(item.package_dir is None for item in items))


if __name__ == "__main__":
    unittest.main()
