from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from config import BODY_REAL_PHOTO_DIR_NAME, PACKAGE_REAL_PHOTO_DIR_NAME
from product_files import get_image_files


@dataclass(frozen=True)
class RealPhotoVariant:
    """一个商品或颜色/款式变体的实拍素材。"""

    product_name: str
    variant_name: str
    product_dir: Path
    variant_dir: Path
    body_dir: Path
    product_image_dir: Path
    package_dir: Path | None
    video_file: Path | None


def _has_variant_resources(directory: Path) -> bool:
    return (
        (directory / BODY_REAL_PHOTO_DIR_NAME).is_dir()
        or (directory / PACKAGE_REAL_PHOTO_DIR_NAME).is_dir()
        or any(path.is_file() and path.suffix.lower() == ".mp4" for path in directory.iterdir())
    )


def _build_variant(product_dir: Path, variant_dir: Path) -> RealPhotoVariant:
    body_dir = variant_dir / BODY_REAL_PHOTO_DIR_NAME
    if not body_dir.is_dir():
        raise FileNotFoundError(f"缺少主体图片目录: {body_dir}")
    get_image_files(str(body_dir))

    product_image_dir = variant_dir / "产品图"
    if not product_image_dir.is_dir():
        raise FileNotFoundError(f"缺少产品图目录: {product_image_dir}")
    get_image_files(str(product_image_dir))

    package_dir = variant_dir / PACKAGE_REAL_PHOTO_DIR_NAME
    if package_dir.is_dir():
        get_image_files(str(package_dir))
    else:
        package_dir = None

    videos = sorted(
        path for path in variant_dir.iterdir()
        if path.is_file() and path.suffix.lower() == ".mp4"
    )
    return RealPhotoVariant(
        product_name=product_dir.name,
        variant_name="" if variant_dir == product_dir else variant_dir.name,
        product_dir=product_dir,
        variant_dir=variant_dir,
        body_dir=body_dir,
        product_image_dir=product_image_dir,
        package_dir=package_dir,
        video_file=videos[0] if videos else None,
    )


def scan_real_photo_library(root_dir: str | Path) -> list[RealPhotoVariant]:
    """扫描实拍图目录，支持商品直存和颜色/款式二级目录两种结构。"""

    root = Path(root_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"实拍图目录不存在: {root}")

    variants: list[RealPhotoVariant] = []
    for product_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        if _has_variant_resources(product_dir):
            variants.append(_build_variant(product_dir, product_dir))
            continue

        child_variants = sorted(
            path for path in product_dir.iterdir()
            if path.is_dir() and _has_variant_resources(path)
        )
        if not child_variants:
            raise FileNotFoundError(f"商品目录中没有可识别的素材: {product_dir}")
        for variant_dir in child_variants:
            variants.append(_build_variant(product_dir, variant_dir))

    if not variants:
        raise FileNotFoundError(f"实拍图目录下没有商品文件夹: {root}")
    return variants
