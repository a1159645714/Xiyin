import unittest

from store_profiles import (
    HOME_STORE_TYPE,
    TOY_STORE_TYPE,
    get_store_profile,
)


class StoreProfileTests(unittest.TestCase):
    def test_toy_and_home_use_different_catalog_files(self) -> None:
        toy_profile = get_store_profile(TOY_STORE_TYPE)
        home_profile = get_store_profile(HOME_STORE_TYPE)

        self.assertNotEqual(
            toy_profile.category_catalog_file,
            home_profile.category_catalog_file,
        )
        self.assertTrue(toy_profile.use_bundled_catalog)
        self.assertTrue(home_profile.use_bundled_catalog)
        self.assertEqual(
            home_profile.default_category_path,
            ("家居&生活", "家居装饰", "挂画"),
        )

    def test_unknown_store_type_falls_back_to_toy_profile(self) -> None:
        self.assertEqual(
            get_store_profile("unknown").name,
            TOY_STORE_TYPE,
        )


if __name__ == "__main__":
    unittest.main()
