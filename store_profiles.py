from dataclasses import dataclass
from pathlib import Path

from config import (
    BASE_DIR,
    CATEGORY_CATALOG_FILE,
    CATEGORY_CATALOG_HOME_BUNDLED_FILE,
    CATEGORY_CATALOG_HOME_FILE,
    CATEGORY_CHILD_TEXT,
    CATEGORY_ROOT_TEXT,
    DEFAULT_PUBLISH_CATEGORY_PATH,
)


TOY_STORE_TYPE = "玩具店"
HOME_STORE_TYPE = "家居店"
STORE_TYPE_OPTIONS = (TOY_STORE_TYPE, HOME_STORE_TYPE)


@dataclass(frozen=True)
class StoreProfile:
    name: str
    category_catalog_file: Path
    default_category_path: tuple[str, ...]
    default_publish_category_path: tuple[str, ...]
    use_bundled_catalog: bool
    bundled_catalog_file: Path | None = None


STORE_PROFILES = {
    TOY_STORE_TYPE: StoreProfile(
        name=TOY_STORE_TYPE,
        category_catalog_file=CATEGORY_CATALOG_FILE,
        default_category_path=(CATEGORY_ROOT_TEXT, CATEGORY_CHILD_TEXT),
        default_publish_category_path=DEFAULT_PUBLISH_CATEGORY_PATH,
        use_bundled_catalog=True,
    ),
    HOME_STORE_TYPE: StoreProfile(
        name=HOME_STORE_TYPE,
        category_catalog_file=CATEGORY_CATALOG_HOME_FILE,
        default_category_path=("家居&生活", "家居装饰", "挂画"),
        default_publish_category_path=(),
        use_bundled_catalog=True,
        bundled_catalog_file=CATEGORY_CATALOG_HOME_BUNDLED_FILE,
    ),
}


def get_store_profile(store_type: str) -> StoreProfile:
    return STORE_PROFILES.get(store_type, STORE_PROFILES[TOY_STORE_TYPE])
