import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

from PIL import Image

from automation import BrowserAutomation
from config import (
    CERTIFICATE_CONFIG_KEY,
    MULTI_COLOR_TEXT,
    PRODUCT_ATTRIBUTES,
    TOY_MANUAL_QUALIFICATION,
)


def make_automation(product_config=None):
    """Build a BrowserAutomation without opening a browser or touching disk."""
    instance = object.__new__(BrowserAutomation)
    instance.product_config = dict(product_config if product_config is not None else {})
    instance.log_handler = lambda message: None
    instance.temp_dir = None
    return instance


class CookieNormalizationTests(unittest.TestCase):
    def test_same_site_values_are_normalized(self) -> None:
        cookies = [
            {"name": "a", "sameSite": "strict"},
            {"name": "b", "sameSite": "Lax"},
            {"name": "c", "sameSite": "none"},
            {"name": "d", "sameSite": "no_restriction"},
            {"name": "e", "sameSite": "unspecified"},
        ]
        result = BrowserAutomation.normalize_cookies(cookies)
        self.assertEqual(
            [cookie["sameSite"] for cookie in result],
            ["Strict", "Lax", "None", "None", "Lax"],
        )

    def test_unknown_same_site_defaults_to_lax(self) -> None:
        result = BrowserAutomation.normalize_cookies([{"name": "a", "sameSite": "weird"}])
        self.assertEqual(result[0]["sameSite"], "Lax")

    def test_expiration_date_becomes_expires(self) -> None:
        cookies = [{"name": "a", "expirationDate": 123.5}]
        result = BrowserAutomation.normalize_cookies(cookies)
        self.assertNotIn("expirationDate", result[0])
        self.assertEqual(result[0]["expires"], 123.5)

    def test_existing_expires_is_preserved(self) -> None:
        cookies = [{"name": "a", "expirationDate": 123.5, "expires": 999.0}]
        result = BrowserAutomation.normalize_cookies(cookies)
        self.assertEqual(result[0]["expires"], 999.0)
        self.assertEqual(result[0]["expirationDate"], 123.5)

    def test_input_cookies_are_not_mutated(self) -> None:
        cookies = [{"name": "a", "sameSite": "strict", "expirationDate": 1.0}]
        BrowserAutomation.normalize_cookies(cookies)
        self.assertEqual(cookies[0]["sameSite"], "strict")
        self.assertIn("expirationDate", cookies[0])
        self.assertNotIn("expires", cookies[0])


class MarkImageFileTests(unittest.TestCase):
    def test_mark_keywords_are_detected(self) -> None:
        for name in ("标.png", "LOGO.jpg", "商标图.jpeg", "品牌主图.png"):
            self.assertTrue(BrowserAutomation.is_mark_image_file(name), name)

    def test_plain_names_are_not_mark_images(self) -> None:
        for name in ("主图.jpg", "detail_1.png", "photo.jpeg"):
            self.assertFalse(BrowserAutomation.is_mark_image_file(name), name)


class ImageFileScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="xiyin_test_images_")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _touch(self, name: str) -> None:
        path = os.path.join(self.temp_dir, name)
        with open(path, "wb") as file:
            file.write(b"x")

    def test_collects_image_extensions_sorted(self) -> None:
        for name in ("c.jpeg", "a.jpg", "b.png", "d.gif", "e.txt"):
            self._touch(name)
        automation = make_automation()
        files = automation.get_image_files(self.temp_dir)
        self.assertEqual([os.path.basename(path) for path in files], ["a.jpg", "b.png", "c.jpeg"])

    def test_excludes_mark_images_when_requested(self) -> None:
        for name in ("a.jpg", "b.png", "标.png", "logo.jpg"):
            self._touch(name)
        automation = make_automation()
        files = automation.get_image_files(self.temp_dir, exclude_mark_images=True)
        self.assertEqual([os.path.basename(path) for path in files], ["a.jpg", "b.png"])

    def test_missing_directory_raises(self) -> None:
        automation = make_automation()
        with self.assertRaises(FileNotFoundError):
            automation.get_image_files(os.path.join(self.temp_dir, "missing"))

    def test_empty_directory_raises(self) -> None:
        automation = make_automation()
        with self.assertRaises(FileNotFoundError):
            automation.get_image_files(self.temp_dir)


class SquareImageConversionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="xiyin_test_square_")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_image(self, size: tuple[int, int]) -> str:
        path = os.path.join(self.temp_dir, f"src_{size[0]}x{size[1]}.png")
        Image.new("RGB", size, (10, 20, 30)).save(path)
        return path

    def test_small_image_is_padded_to_1200_square(self) -> None:
        automation = make_automation()
        output_path = automation.convert_image_to_square(self._write_image((300, 500)))
        with Image.open(output_path) as image:
            self.assertEqual(image.size, (1200, 1200))
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))

    def test_large_image_is_downscaled_to_square(self) -> None:
        automation = make_automation()
        output_path = automation.convert_image_to_square(self._write_image((1600, 800)))
        with Image.open(output_path) as image:
            self.assertEqual(image.size, (1600, 1600))
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))

    def test_output_lives_in_temp_dir(self) -> None:
        automation = make_automation()
        output_path = automation.convert_image_to_square(self._write_image((300, 500)))
        self.assertEqual(os.path.dirname(output_path), automation.temp_dir)
        self.assertTrue(output_path.endswith("_1x1.jpeg"))

    def test_missing_source_raises(self) -> None:
        automation = make_automation()
        with self.assertRaises(FileNotFoundError):
            automation.convert_image_to_square(os.path.join(self.temp_dir, "missing.png"))


class XPathLiteralTests(unittest.TestCase):
    def test_value_without_quotes(self) -> None:
        self.assertEqual(BrowserAutomation.xpath_literal("plain"), '"plain"')

    def test_value_with_double_quotes(self) -> None:
        self.assertEqual(BrowserAutomation.xpath_literal('say "hi"'), '\'say "hi"\'')

    def test_value_with_single_quotes(self) -> None:
        self.assertEqual(BrowserAutomation.xpath_literal("it's"), '"it\'s"')

    def test_value_with_both_quotes(self) -> None:
        result = BrowserAutomation.xpath_literal('a"b\'c')
        self.assertTrue(result.startswith("concat("))
        self.assertIn('"a"', result)
        self.assertIn("'\"'", result)


class ImageUploadAcceptTests(unittest.TestCase):
    def test_accepts_image_values(self) -> None:
        for accept in ("image/*", ".png", ".jpg", ".jpeg", "image/png", "image/webp"):
            self.assertTrue(BrowserAutomation.is_image_upload_accept(accept), accept)

    def test_accepts_comma_separated_with_spaces(self) -> None:
        self.assertTrue(BrowserAutomation.is_image_upload_accept(" .png , .jpg "))

    def test_rejects_non_image_values(self) -> None:
        for accept in ("", "application/pdf", "video/mp4", "text/plain"):
            self.assertFalse(BrowserAutomation.is_image_upload_accept(accept), accept)

    def test_rejects_none(self) -> None:
        self.assertFalse(BrowserAutomation.is_image_upload_accept(None))


class AttributeLabelCandidatesTests(unittest.TestCase):
    def test_known_label_expands_aliases(self) -> None:
        candidates = BrowserAutomation.get_attribute_label_candidates("Applicable Age")
        self.assertIn("Applicable Age", candidates)
        self.assertIn("Suitable Age", candidates)
        self.assertIn("适用年龄", candidates)

    def test_unknown_label_passes_through(self) -> None:
        self.assertEqual(
            BrowserAutomation.get_attribute_label_candidates("Something New"),
            ("Something New",),
        )


class SupplierCodeTests(unittest.TestCase):
    def test_reads_supplier_code(self) -> None:
        automation = make_automation({"供方信息": {"供方货号": " 西瓜 "}})
        self.assertEqual(automation.get_supplier_code_from_config(), "西瓜")

    def test_missing_code_raises(self) -> None:
        automation = make_automation()
        with self.assertRaises(RuntimeError):
            automation.get_supplier_code_from_config()


class CertificateUploadTests(unittest.TestCase):
    def test_enabled_values(self) -> None:
        self.assertTrue(BrowserAutomation.is_certificate_upload_enabled({}))
        self.assertTrue(BrowserAutomation.is_certificate_upload_enabled({"是否启用": True}))
        self.assertTrue(BrowserAutomation.is_certificate_upload_enabled({"是否启用": "yes"}))
        self.assertFalse(BrowserAutomation.is_certificate_upload_enabled({"是否启用": False}))
        for disabled in ("false", "0", "no", "否"):
            self.assertFalse(
                BrowserAutomation.is_certificate_upload_enabled({"是否启用": disabled}),
                disabled,
            )

    def test_resolve_name_from_dict(self) -> None:
        automation = make_automation()
        self.assertEqual(
            automation.resolve_certificate_name({"证书名": "", "匹配证书名": " 西瓜 "}),
            "西瓜",
        )

    def test_resolve_name_scalar_and_empty(self) -> None:
        automation = make_automation()
        self.assertEqual(automation.resolve_certificate_name(" 西瓜 "), "西瓜")
        self.assertEqual(automation.resolve_certificate_name(None), "")
        self.assertEqual(automation.resolve_certificate_name({}), "")

    def test_upload_items_respect_config(self) -> None:
        automation = make_automation(
            {
                CERTIFICATE_CONFIG_KEY: {
                    "是否启用": True,
                    TOY_MANUAL_QUALIFICATION: "",
                    "CPC证书（手动）": "",
                    "ASTM F963报告": "西瓜",
                }
            }
        )
        items = automation.get_certificate_upload_items()
        self.assertIn((TOY_MANUAL_QUALIFICATION, None), items)
        self.assertIn(("ASTM F963报告", "西瓜"), items)
        self.assertNotIn(("CPC证书（手动）", "西瓜"), items)
        self.assertNotIn(("CPC证书（手动）", None), items)

    def test_disabled_certificates_return_empty(self) -> None:
        automation = make_automation({CERTIFICATE_CONFIG_KEY: {"是否启用": False}})
        self.assertEqual(automation.get_certificate_upload_items(), [])

    def test_non_dict_certificate_config_returns_empty(self) -> None:
        automation = make_automation({CERTIFICATE_CONFIG_KEY: "abc"})
        self.assertEqual(automation.get_certificate_upload_items(), [])

    def test_missing_certificate_config_defaults_to_manual_only(self) -> None:
        automation = make_automation()
        self.assertEqual(
            automation.get_certificate_upload_items(),
            [(TOY_MANUAL_QUALIFICATION, None)],
        )


class PackageInfoTests(unittest.TestCase):
    def test_reads_package_fields(self) -> None:
        automation = make_automation(
            {
                "包装信息": {
                    "含包装重量(g)": "130",
                    "含包装尺寸": {"长": "6", "宽": "6", "高": "6"},
                    "单位": "cm",
                    "包装类型": "软包装+硬物",
                }
            }
        )
        self.assertEqual(
            automation.get_package_info(),
            {
                "weight": "130",
                "length": "6",
                "width": "6",
                "height": "6",
                "unit": "cm",
                "package_type": "软包装+硬物",
            },
        )

    def test_missing_package_fields_are_empty_strings(self) -> None:
        automation = make_automation()
        self.assertEqual(
            automation.get_package_info(),
            {
                "weight": "",
                "length": "",
                "width": "",
                "height": "",
                "unit": "",
                "package_type": "",
            },
        )


class ProductAttributeTests(unittest.TestCase):
    def test_missing_config_falls_back_to_defaults(self) -> None:
        automation = make_automation()
        self.assertEqual(automation.get_product_attributes(), PRODUCT_ATTRIBUTES)

    def test_non_dict_config_falls_back_to_defaults(self) -> None:
        automation = make_automation({"必填属性": "abc"})
        self.assertEqual(automation.get_product_attributes(), PRODUCT_ATTRIBUTES)

    def test_composition_dict_keeps_ratio(self) -> None:
        automation = make_automation({"必填属性": {"成分": {"值": "PU", "比例": "100"}}})
        self.assertEqual(automation.get_product_attributes(), [("Composition", "PU", "100")])

    def test_list_values_expand_to_multiple_attributes(self) -> None:
        automation = make_automation({"必填属性": {"材质": ["TPR", "ABS"]}})
        self.assertEqual(
            automation.get_product_attributes(),
            [("Material", "TPR", None), ("Material", "ABS", None)],
        )

    def test_none_values_are_skipped(self) -> None:
        automation = make_automation({"必填属性": {"敏感类别": None, "适用年龄": "3岁以上"}})
        self.assertEqual(
            automation.get_product_attributes(),
            [("Applicable Age", "3岁以上", None)],
        )


class ProductSkcReadingTests(unittest.TestCase):
    def _make_row(self, first_cell_text: str, row_text: str | None = None) -> MagicMock:
        row = MagicMock()
        first_td = MagicMock()
        first_td.inner_text.return_value = first_cell_text
        row.locator.return_value.first = first_td
        row.inner_text.return_value = (
            row_text if row_text is not None else first_cell_text
        )
        return row

    def test_reads_skc_from_new_spec_info_cell(self) -> None:
        row = self._make_row("多色\nSKC：sl260828202247889352022")
        automation = make_automation()
        self.assertEqual(
            automation.read_product_skc_from_supplier_row(row),
            "sl260828202247889352022",
        )

    def test_reads_skc_from_old_format(self) -> None:
        row = self._make_row("SKC: abc123")
        automation = make_automation()
        self.assertEqual(automation.read_product_skc_from_supplier_row(row), "abc123")

    def test_reads_skc_from_row_text_fallback(self) -> None:
        row = self._make_row("多色", "其他信息 SKC：xyz999 更多内容")
        automation = make_automation()
        self.assertEqual(automation.read_product_skc_from_supplier_row(row), "xyz999")

    def test_returns_empty_without_skc(self) -> None:
        row = self._make_row("多色")
        automation = make_automation()
        self.assertEqual(automation.read_product_skc_from_supplier_row(row), "")


class ColorAndStyleTests(unittest.TestCase):
    def test_colors_are_filtered_and_stripped(self) -> None:
        automation = make_automation({"颜色配置": [" 粉红 ", "", " 白 "]})
        self.assertEqual(automation.get_color_config(), ["粉红", "白"])

    def test_non_list_colors_return_empty(self) -> None:
        automation = make_automation({"颜色配置": "abc"})
        self.assertEqual(automation.get_color_config(), [])

    def test_style_is_stripped(self) -> None:
        automation = make_automation({"款式": " 粉色款 "})
        self.assertEqual(automation.get_style_config(), "粉色款")

    def test_spec_value_falls_back_to_multi_color(self) -> None:
        automation = make_automation()
        self.assertEqual(automation.get_configured_spec_value(), MULTI_COLOR_TEXT)
        automation = make_automation({"款式": "粉色"})
        self.assertEqual(automation.get_configured_spec_value(), "粉色")


if __name__ == "__main__":
    unittest.main()
