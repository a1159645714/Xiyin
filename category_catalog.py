import json
import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from config import (
    CATEGORY_CATALOG_BUNDLED_FILE,
    CATEGORY_CATALOG_FILE,
    CATEGORY_CHILD_TEXT,
    CATEGORY_ROOT_TEXT,
)


CategoryTree = dict[str, "CategoryTree"]

DEFAULT_CATEGORY_CATALOG: CategoryTree = {
    CATEGORY_ROOT_TEXT: {
        CATEGORY_CHILD_TEXT: {},
    },
}


def normalize_category_catalog(
    value: Any,
    *,
    allow_empty: bool = False,
) -> CategoryTree:
    if not isinstance(value, Mapping):
        raise ValueError("类目目录必须是对象")

    catalog: CategoryTree = {}
    for raw_name, raw_children in value.items():
        name = str(raw_name).strip()
        if not name:
            continue
        catalog[name] = normalize_category_catalog(raw_children, allow_empty=True)

    if not catalog and not allow_empty:
        raise ValueError("类目目录不能为空")
    return catalog


def load_category_catalog(
    path: Path = CATEGORY_CATALOG_FILE,
    *,
    use_bundled_catalog: bool = True,
    bundled_catalog_file: Path | None = None,
) -> CategoryTree:
    if not path.exists():
        bundled_file = bundled_catalog_file or CATEGORY_CATALOG_BUNDLED_FILE
        if (
            use_bundled_catalog
            and bundled_file.exists()
            and path != bundled_file
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(bundled_file, path)
        else:
            return DEFAULT_CATEGORY_CATALOG if use_bundled_catalog else {}

    with path.open("r", encoding="utf-8") as file:
        return normalize_category_catalog(json.load(file))


def save_category_catalog(
    catalog: CategoryTree,
    path: Path = CATEGORY_CATALOG_FILE,
) -> None:
    normalized_catalog = normalize_category_catalog(catalog)
    with path.open("w", encoding="utf-8") as file:
        json.dump(normalized_catalog, file, ensure_ascii=False, indent=2)


def resolve_category_path(
    catalog: CategoryTree,
    requested_path: list[str] | tuple[str, ...],
) -> list[str]:
    resolved_path: list[str] = []
    current_level = catalog
    for requested_name in requested_path:
        if requested_name not in current_level:
            break
        resolved_path.append(requested_name)
        current_level = current_level[requested_name]
    return resolved_path


def parse_category_path(value: str) -> tuple[str, ...]:
    return tuple(
        category_name.strip()
        for category_name in re.split(r"[>＞]", value)
        if category_name.strip()
    )


def count_category_nodes(catalog: CategoryTree) -> int:
    return sum(1 + count_category_nodes(children) for children in catalog.values())
