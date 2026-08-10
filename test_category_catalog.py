import tempfile
import unittest
from pathlib import Path

from category_catalog import (
    count_category_nodes,
    load_category_catalog,
    parse_category_path,
    resolve_category_path,
    save_category_catalog,
)


class CategoryCatalogTests(unittest.TestCase):
    def test_catalog_round_trip_keeps_leaf_nodes(self) -> None:
        catalog = {
            "一级类目": {
                "二级类目": {
                    "三级类目": {},
                },
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog_file = Path(temp_dir) / "categories.json"
            save_category_catalog(catalog, catalog_file)

            self.assertEqual(load_category_catalog(catalog_file), catalog)
            self.assertEqual(count_category_nodes(catalog), 3)

    def test_resolve_category_path_stops_at_invalid_level(self) -> None:
        catalog = {"一级类目": {"二级类目": {}}}

        path = resolve_category_path(catalog, ["一级类目", "不存在的类目"])

        self.assertEqual(path, ["一级类目"])

    def test_parse_category_path_supports_both_separator_styles(self) -> None:
        path = parse_category_path("一级类目 > 二级类目＞三级类目")

        self.assertEqual(path, ("一级类目", "二级类目", "三级类目"))

    def test_missing_profile_catalog_can_remain_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog_file = Path(temp_dir) / "furniture_categories.json"

            self.assertEqual(
                load_category_catalog(
                    catalog_file,
                    use_bundled_catalog=False,
                ),
                {},
            )

    def test_missing_catalog_can_copy_a_custom_bundled_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            catalog_file = root / "home_categories.json"
            bundled_file = root / "bundled_home_categories.json"
            bundled_file.write_text(
                '{"家居&生活": {"家居装饰": {}}}',
                encoding="utf-8",
            )

            self.assertEqual(
                load_category_catalog(
                    catalog_file,
                    bundled_catalog_file=bundled_file,
                ),
                {"家居&生活": {"家居装饰": {}}},
            )


if __name__ == "__main__":
    unittest.main()
