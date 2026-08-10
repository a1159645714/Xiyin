import json
import os
from dataclasses import dataclass
from typing import Any

from config import (
    BODY_REAL_PHOTO_DIR_NAME,
    CONFIG_FILE_NAME,
    PACKAGE_REAL_PHOTO_DIR_NAME,
)


@dataclass
class ProductFiles:
    root_dir: str
    selected_image_dir: str
    main_image_file: str
    product_video_file: str
    config_file: str
    body_photo_dir: str = ""
    package_photo_dir: str = ""


def load_product_config(root_dir: str) -> dict[str, Any]:
    config_file = os.path.join(root_dir, CONFIG_FILE_NAME)
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"未找到商品配置 JSON: {config_file}")

    with open(config_file, "r", encoding="utf-8") as file:
        config = json.load(file)

    if not isinstance(config, dict):
        raise ValueError(f"商品配置 JSON 必须是对象: {config_file}")
    return config


def get_image_files(directory: str) -> list[str]:
    image_extensions = {".jpg", ".jpeg", ".png"}
    if not os.path.isdir(directory):
        raise FileNotFoundError(f"图片目录不存在: {directory}")

    image_files = [
        os.path.join(directory, file_name)
        for file_name in os.listdir(directory)
        if os.path.splitext(file_name)[1].lower() in image_extensions
    ]
    image_files.sort()
    if not image_files:
        raise FileNotFoundError(f"图片目录没有可上传的图片: {directory}")
    return image_files


def resolve_product_file_sets(root_dir: str) -> list[ProductFiles]:
    if not os.path.isdir(root_dir):
        raise FileNotFoundError(f"商品总目录不存在: {root_dir}")

    child_dirs = [
        os.path.join(root_dir, name)
        for name in os.listdir(root_dir)
        if name.isdigit() and os.path.isdir(os.path.join(root_dir, name))
    ]
    if not child_dirs:
        raise FileNotFoundError("商品总目录下未找到 1/2/3/4 这类数字图片文件夹")

    product_file_sets = []
    for child_dir in sorted(child_dirs, key=lambda directory: int(os.path.basename(directory))):
        try:
            image_files = get_image_files(child_dir)
        except FileNotFoundError:
            continue

        main_candidates = [
            path
            for path in image_files
            if "主图" in os.path.splitext(os.path.basename(path))[0]
        ]
        product_file_sets.append(
            ProductFiles(
                root_dir=root_dir,
                selected_image_dir=child_dir,
                main_image_file=sorted(main_candidates or image_files)[0],
                product_video_file="",
                config_file="",
            )
        )

    if not product_file_sets:
        raise FileNotFoundError("数字图片文件夹中没有可上传的图片")

    video_files = [
        os.path.join(root_dir, name)
        for name in os.listdir(root_dir)
        if os.path.isfile(os.path.join(root_dir, name)) and name.lower().endswith(".mp4")
    ]
    if not video_files:
        raise FileNotFoundError(f"商品总目录下未找到 MP4 视频: {root_dir}")

    product_video_file = sorted(video_files)[0]
    for product_files in product_file_sets:
        product_files.product_video_file = product_video_file

    return product_file_sets


def resolve_product_files(root_dir: str) -> ProductFiles:
    """Return the first numbered image directory for backwards compatibility."""
    return resolve_product_file_sets(root_dir)[0]


def validate_product_directory(root_dir: str) -> ProductFiles:
    product_file_sets = resolve_product_file_sets(root_dir)

    for directory_name in (BODY_REAL_PHOTO_DIR_NAME, PACKAGE_REAL_PHOTO_DIR_NAME):
        get_image_files(os.path.join(root_dir, directory_name))

    return product_file_sets[0]
