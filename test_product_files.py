import json
import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from automation import BrowserAutomation
from config import CONFIG_FILE_NAME, PUBLISH_ENTRY_TEXTS
from product_files import (
    load_product_config,
    resolve_product_file_sets,
    resolve_product_files,
    validate_product_directory,
)


class ProductFilesTests(unittest.TestCase):
    def create_product_directory(self, root: Path) -> None:
        (root / "1").mkdir()
        (root / "2").mkdir()
        (root / "本体").mkdir()
        (root / "包装").mkdir()
        (root / "1" / "主图.jpg").touch()
        (root / "本体" / "body.jpg").touch()
        (root / "包装" / "package.png").touch()
        (root / "video.mp4").touch()

    def test_skips_empty_numbered_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.create_product_directory(root)

            files = resolve_product_files(os.fspath(root))

            self.assertEqual(files.selected_image_dir, os.fspath(root / "1"))
            self.assertEqual(files.main_image_file, os.fspath(root / "1" / "主图.jpg"))
            self.assertEqual(files.config_file, "")

    def test_resolves_numbered_directories_in_numeric_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.create_product_directory(root)
            (root / "2" / "second.jpg").touch()
            (root / "10").mkdir()
            (root / "10" / "tenth.jpg").touch()

            product_file_sets = resolve_product_file_sets(os.fspath(root))

            self.assertEqual(
                [Path(files.selected_image_dir).name for files in product_file_sets],
                ["1", "2", "10"],
            )

    def test_validate_product_directory_does_not_require_base_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.create_product_directory(root)

            files = validate_product_directory(os.fspath(root))
            self.assertEqual(files.root_dir, os.fspath(root))

    def test_load_product_config_rejects_non_object(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / CONFIG_FILE_NAME).write_text("[]", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "必须是对象"):
                load_product_config(os.fspath(root))

    def test_certificate_global_switch_disables_certificate_uploads(self) -> None:
        automation = BrowserAutomation.__new__(BrowserAutomation)
        automation.product_config = {
            "证书列表": {
                "是否启用": False,
                "CPC证书": "示例证书",
            },
        }
        log_messages = []
        automation.log_handler = log_messages.append

        self.assertEqual(automation.get_certificate_upload_items(), [])
        self.assertTrue(any("全局上传" in message for message in log_messages))

    def test_empty_composition_is_skipped(self) -> None:
        automation = BrowserAutomation.__new__(BrowserAutomation)
        automation.product_config = {
            "必填属性": {
                "敏感类别": "其他",
                "成分": {},
            },
        }

        self.assertEqual(
            automation.get_product_attributes(),
            [("Hazard Category", "其他", None)],
        )

    def test_applicable_age_supports_new_and_legacy_labels(self) -> None:
        self.assertEqual(
            BrowserAutomation.get_attribute_label_candidates("Applicable Age"),
            ("Applicable Age", "Suitable Age", "适用年龄"),
        )

    def test_secondary_material_is_optional_and_precedes_composition(self) -> None:
        automation = BrowserAutomation.__new__(BrowserAutomation)
        automation.product_config = {
            "必填属性": {
                "材质": "纸",
                "次要材质": "塑料",
                "成分": {"值": "PU", "比例": "100"},
            },
        }

        self.assertEqual(
            automation.get_product_attributes(),
            [
                ("Material", "纸", None),
                ("Other Material", "塑料", None),
                ("Composition", "PU", "100"),
            ],
        )

        automation.product_config["必填属性"]["次要材质"] = ""
        self.assertEqual(
            automation.get_product_attributes(),
            [
                ("Material", "纸", None),
                ("Composition", "PU", "100"),
            ],
        )

    def test_product_attributes_match_all_non_empty_json_fields(self) -> None:
        automation = BrowserAutomation.__new__(BrowserAutomation)
        automation.product_config = {
            "必填属性": {
                "材质": "纸",
                "自定义属性": "收藏品",
                "多选属性": ["照片", "", "贴纸"],
                "空字符串": "",
                "空对象": {},
                "成分": {},
            },
        }

        self.assertEqual(
            automation.get_product_attributes(),
            [
                ("Material", "纸", None),
                ("自定义属性", "收藏品", None),
                ("多选属性", "照片", None),
                ("多选属性", "贴纸", None),
            ],
        )

    def test_empty_product_attributes_do_not_use_default_values(self) -> None:
        automation = BrowserAutomation.__new__(BrowserAutomation)
        automation.product_config = {"必填属性": {}}

        self.assertEqual(automation.get_product_attributes(), [])

    def test_style_config_is_optional(self) -> None:
        automation = BrowserAutomation.__new__(BrowserAutomation)

        automation.product_config = {"款式": " 卡片 "}
        self.assertEqual(automation.get_style_config(), "卡片")
        self.assertEqual(automation.get_configured_spec_value(), "卡片")

        automation.product_config = {}
        self.assertEqual(automation.get_style_config(), "")
        self.assertEqual(automation.get_configured_spec_value(), "多色")

        automation.product_config = {"款式": "   "}
        self.assertEqual(automation.get_style_config(), "")
        self.assertEqual(automation.get_configured_spec_value(), "多色")

    def test_compliance_info_row_aliases_support_new_page(self) -> None:
        self.assertEqual(
            BrowserAutomation.get_compliance_info_row_candidates("欧盟玩具安全指令"),
            ("欧盟玩具安全指令",),
        )
        self.assertEqual(
            BrowserAutomation.get_compliance_info_row_candidates("产品标识符"),
            ("产品标识符",),
        )
        self.assertEqual(
            BrowserAutomation.get_compliance_info_row_candidates("美国玩具窒息危险提示"),
            ("美国玩具窒息危险提示",),
        )

    def test_publish_entry_texts_include_common_variants(self) -> None:
        self.assertEqual(
            PUBLISH_ENTRY_TEXTS,
            ("发布同款",),
        )

    def test_image_conversion_keeps_large_images_above_1200(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_sizes = {
                "large_landscape.png": ((1800, 900), (1800, 1800)),
                "large_square.png": ((1365, 1365), (1365, 1365)),
                "small_square.png": ((600, 600), (1200, 1200)),
            }
            automation = BrowserAutomation.__new__(BrowserAutomation)
            automation.temp_dir = None
            automation.log_handler = lambda _message: None

            try:
                for file_name, (source_size, expected_size) in source_sizes.items():
                    source_file = root / file_name
                    Image.new("RGB", source_size, "red").save(source_file)

                    output_file = automation.convert_image_to_square(
                        os.fspath(source_file)
                    )

                    with Image.open(output_file) as converted:
                        self.assertEqual(converted.size, expected_size)
            finally:
                automation.cleanup_temp_files()

    def test_common_mark_images_can_be_excluded_from_directory_uploads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            normal_file = root / "body.jpg"
            mark_file = root / "\u6807.png"
            logo_file = root / "logo.jpg"
            normal_file.touch()
            mark_file.touch()
            logo_file.touch()

            automation = BrowserAutomation.__new__(BrowserAutomation)
            files = automation.get_image_files(os.fspath(root), exclude_mark_images=True)

            self.assertEqual(files, [os.fspath(normal_file)])


if __name__ == "__main__":
    unittest.main()
