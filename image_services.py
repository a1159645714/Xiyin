from __future__ import annotations

import base64
import io
import json
import re
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image, ImageOps

from ai_content_service import generate_product_content
from config_services import get_goods_id, get_goods_name, get_goods_platform, get_goods_thumbnail_url
import importlib

_ai = importlib.import_module("\u534f\u8baeAI")
AI_PROVIDER_CONFIGS = _ai.AI_PROVIDER_CONFIGS
build_prompt = _ai.build_prompt
build_core_prompt = _ai.build_core_prompt
edit_image_file = _ai.edit_image_file
get_ai_model_list = _ai.get_ai_model_list

OUTPUT_DIR = Path(__file__).with_name("output")
USD_TO_CNY_RATE = __import__("decimal").Decimal("7.20")
def normalize_thumbnail_bytes(image_bytes: bytes) -> bytes:
    with Image.open(io.BytesIO(image_bytes)) as image:
        image = image.convert("RGBA")
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()


def normalize_url(url: str) -> str:
    url = str(url or "").strip()
    if url.startswith("//"):
        return f"https:{url}"
    return url


def get_nested(value: dict, path: str, default=""):
    current = value
    for key in path.split("."):
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return current if current not in (None, "") else default


def first_value(goods: dict, *fields: str) -> str:
    for field in fields:
        value = get_nested(goods, field) if "." in field else goods.get(field)
        if value not in (None, ""):
            return str(value)
    return ""


def format_money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def convert_price_numbers(price_text: str, rate: Decimal, multiply: bool) -> list[str]:
    converted = []
    for number in re.findall(r"\d+(?:\.\d+)?", price_text)[:2]:
        try:
            amount = Decimal(number)
        except InvalidOperation:
            continue
        converted.append(format_money(amount * rate if multiply else amount / rate))
    return converted


def join_price_range(values: list[str]) -> str:
    return "-".join(values) if values else ""


def clean_price_text(price_text: str) -> str:
    return re.sub(r"\s+", " ", str(price_text or "").strip())


def extract_price_range(price_text: str) -> str:
    return join_price_range(re.findall(r"\d+(?:\.\d+)?", clean_price_text(price_text))[:2])


def sanitize_folder_name(value: str) -> str:
    text = str(value or "unknown_goods").strip() or "unknown_goods"
    return "".join(char if char not in '<>:"/\\|?*' else "_" for char in text)[:120]


def get_goods_folder(goods: dict) -> Path:
    goods_id = sanitize_folder_name(get_goods_id(goods) or "unknown_goods")
    round_value = goods.get("_output_round")
    if round_value:
        try:
            round_name = f"round_{int(round_value):03d}"
        except (TypeError, ValueError):
            round_name = f"round_{sanitize_folder_name(str(round_value))}"
        return OUTPUT_DIR / round_name / goods_id
    return OUTPUT_DIR / goods_id


def get_download_referer(image_url: str) -> str:
    host = urlparse(normalize_url(image_url)).netloc.lower()
    if "aliexpress-media.com" in host:
        return "https://www.aliexpress.com/"
    if "media-amazon.com" in host:
        return "https://www.amazon.com/"
    if "alicdn.com" in host:
        return "https://www.alibaba.com/"
    return "https://www.aiprice.com/"


def download_image(image_url: str, output_path: Path) -> Path:
    image_url = normalize_url(image_url)
    headers = {
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Referer": get_download_referer(image_url),
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36"
        ),
    }
    response = requests.get(image_url, headers=headers, timeout=120)
    if response.status_code != 200:
        raise RuntimeError(f"图片下载失败，HTTP {response.status_code}: {image_url}")

    try:
        with Image.open(io.BytesIO(response.content)) as image:
            image = image.convert("RGB")
            image.save(output_path, format="JPEG", quality=95)
    except Exception:
        output_path.write_bytes(response.content)
    return output_path


def save_ai_image_response(response, output_path: Path) -> bool:
    payload = response.json()
    data = payload.get("data") or []
    if not data:
        return False

    first = data[0]
    image_url = first.get("url")
    if image_url:
        image_response = requests.get(image_url, timeout=180)
        image_response.raise_for_status()
        output_path.write_bytes(image_response.content)
        return True

    b64_json = first.get("b64_json")
    if b64_json:
        output_path.write_bytes(base64.b64decode(b64_json))
        return True
    return False


def is_white_separator_pixel(pixel: tuple[int, int, int]) -> bool:
    red, green, blue = pixel[:3]
    luminance = (red + green + blue) / 3
    saturation = max(pixel[:3]) - min(pixel[:3])
    return luminance >= 230 and saturation <= 42


def find_separator_bands(image: Image.Image, box: tuple[int, int, int, int], axis: str) -> list[tuple[int, int, float]]:
    x1, y1, x2, y2 = box
    width = x2 - x1
    height = y2 - y1
    if width < 240 or height < 240:
        return []

    if axis == "vertical":
        scan_start = x1 + max(8, int(width * 0.04))
        scan_end = x2 - max(8, int(width * 0.04))
        line_length = height
    else:
        scan_start = y1 + max(8, int(height * 0.04))
        scan_end = y2 - max(8, int(height * 0.04))
        line_length = width

    scores = []
    for position in range(scan_start, scan_end):
        white_count = 0
        if axis == "vertical":
            for y in range(y1, y2):
                if is_white_separator_pixel(image.getpixel((position, y))):
                    white_count += 1
        else:
            for x in range(x1, x2):
                if is_white_separator_pixel(image.getpixel((x, position))):
                    white_count += 1
        scores.append((position, white_count / line_length))

    bands = []
    band_start = None
    band_scores = []
    for position, score in scores:
        if score >= 0.88:
            if band_start is None:
                band_start = position
                band_scores = []
            band_scores.append(score)
        elif band_start is not None:
            bands.append((band_start, position, sum(band_scores) / len(band_scores)))
            band_start = None
            band_scores = []
    if band_start is not None and band_scores:
        bands.append((band_start, scores[-1][0] + 1, sum(band_scores) / len(band_scores)))

    max_band_width = max(32, int((width if axis == "vertical" else height) * 0.08))
    return [band for band in bands if 3 <= band[1] - band[0] <= max_band_width]


def split_regular_grid(image: Image.Image) -> list[tuple[int, int, int, int]]:
    full_box = (0, 0, image.width, image.height)
    vertical_bands = find_separator_bands(image, full_box, "vertical")
    horizontal_bands = find_separator_bands(image, full_box, "horizontal")
    if not vertical_bands or not horizontal_bands:
        return []

    x_edges = [0]
    for start, end, _ in vertical_bands:
        x_edges.extend([start, end])
    x_edges.append(image.width)

    y_edges = [0]
    for start, end, _ in horizontal_bands:
        y_edges.extend([start, end])
    y_edges.append(image.height)

    boxes = []
    for y_index in range(0, len(y_edges) - 1, 2):
        for x_index in range(0, len(x_edges) - 1, 2):
            box = (x_edges[x_index], y_edges[y_index], x_edges[x_index + 1], y_edges[y_index + 1])
            if box[2] - box[0] >= 180 and box[3] - box[1] >= 180:
                boxes.append(box)
    return boxes if len(boxes) >= 4 else []


def split_collage_box(image: Image.Image, box: tuple[int, int, int, int], depth: int = 0) -> list[tuple[int, int, int, int]]:
    x1, y1, x2, y2 = box
    width = x2 - x1
    height = y2 - y1
    if depth >= 8 or width < 240 or height < 240:
        return [box]

    candidates = []
    for start, end, score in find_separator_bands(image, box, "vertical"):
        candidates.append(("vertical", start, end, score, end - start))
    for start, end, score in find_separator_bands(image, box, "horizontal"):
        candidates.append(("horizontal", start, end, score, end - start))
    if not candidates:
        return [box]

    axis, start, end, _, _ = max(candidates, key=lambda item: (item[3], item[4]))
    parts = (
        [(x1, y1, start, y2), (end, y1, x2, y2)]
        if axis == "vertical"
        else [(x1, y1, x2, start), (x1, end, x2, y2)]
    )

    result = []
    for part in parts:
        px1, py1, px2, py2 = part
        if px2 - px1 >= 180 and py2 - py1 >= 180:
            result.extend(split_collage_box(image, part, depth + 1))
    return result or [box]


def is_blank_crop(image: Image.Image, box: tuple[int, int, int, int]) -> bool:
    x1, y1, x2, y2 = box
    width = x2 - x1
    height = y2 - y1
    step = max(4, min(width, height) // 80)
    sampled = 0
    content = 0
    for y in range(y1, y2, step):
        for x in range(x1, x2, step):
            red, green, blue = image.getpixel((x, y))[:3]
            luminance = (red + green + blue) / 3
            saturation = max(red, green, blue) - min(red, green, blue)
            if luminance < 238 or saturation > 20:
                content += 1
            sampled += 1
    return True if not sampled else content / sampled < 0.035


def fallback_grid_boxes(image: Image.Image) -> list[tuple[int, int, int, int]]:
    width, height = image.size
    columns, rows = 3, 3

    boxes = []
    for row in range(rows):
        for column in range(columns):
            left = round(column * width / columns)
            top = round(row * height / rows)
            right = round((column + 1) * width / columns)
            bottom = round((row + 1) * height / rows)
            if right - left >= 180 and bottom - top >= 180:
                boxes.append((left, top, right, bottom))
    return boxes


def save_square_crop(image: Image.Image, box: tuple[int, int, int, int], path: Path) -> None:
    crop = image.crop(box)
    if crop.width < 1200 or crop.height < 1200:
        crop = ImageOps.fit(crop, (1200, 1200), method=Image.Resampling.LANCZOS)
    crop.save(path, format="PNG")


def crop_ai_collage(image_path: Path, output_dir: Path) -> list[Path]:
    with Image.open(image_path) as image:
        image = image.convert("RGB")
        boxes = fallback_grid_boxes(image)
        if len(boxes) != 9:
            return []

        output_dir.mkdir(parents=True, exist_ok=True)
        for old_crop in output_dir.glob("*.png"):
            old_crop.unlink()

        crop_paths = []
        for index, box in enumerate(boxes, start=1):
            crop_path = output_dir / f"product_image_{index:02d}.png"
            save_square_crop(image, box, crop_path)
            crop_paths.append(crop_path)
        return crop_paths


def generate_ai_crops_for_goods(
    goods: dict,
    log_handler,
    ai_provider: str = "geeknow",
    ai_token: str = "",
    ai_model: str = "gpt-image-2",
    chat_provider: str = "geeknow",
    chat_token: str = "",
    chat_model: str = "gpt-5.5",
    generate_title: bool = False,
    generate_prompt: bool = False,
    product_config: dict | None = None,
    reference_image_paths: list[Path] | None = None,
    source_image_path: Path | None = None,
) -> list[Path]:
    image_url = goods.get("_display_image_url") or get_goods_thumbnail_url(goods)
    if source_image_path is None and not image_url:
        raise RuntimeError("当前商品没有可提交给 AI 的图片")

    folder = get_goods_folder(goods)
    folder.mkdir(parents=True, exist_ok=True)
    safe_goods = {key: value for key, value in goods.items() if not key.startswith("_")}
    (folder / "goods.json").write_text(json.dumps(safe_goods, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / "display_image_url.txt").write_text(normalize_url(image_url), encoding="utf-8")

    source_path = folder / "display_original.jpg"
    if source_image_path is not None:
        log_handler(f"正在使用本地产品图: {source_image_path}")
        shutil.copyfile(source_image_path, source_path)
    else:
        log_handler("正在下载当前列表显示的图片...")
        download_image(image_url, source_path)

    product_name = get_goods_name(goods)
    product_attributes = product_config.get("必填属性", {}) if isinstance(product_config, dict) else {}
    current_material = ""
    if isinstance(product_attributes, dict):
        material = str(product_attributes.get("材质") or "").strip()
        other_material = str(product_attributes.get("次要材质") or "").strip()
        if material and other_material and other_material not in material:
            current_material = f"{material} / {other_material}"
        else:
            current_material = material or other_material
    generated_content = {}
    if generate_title or generate_prompt:
        provider_label = AI_PROVIDER_CONFIGS.get(chat_provider, {}).get("label", chat_provider)
        log_handler(
            f"正在调用对话模型: {provider_label} / {chat_model}，正在生成商品标题和专属图片提示词"
        )
        chat_error = None
        for attempt in range(1, 4):
            try:
                generated_content = generate_product_content(
                    image_path=source_path,
                    product_name=product_name,
                    goods=goods,
                    product_config=product_config or {},
                    reference_image_paths=reference_image_paths,
                    provider=chat_provider,
                    token=chat_token,
                    model=chat_model,
                )
                chat_error = None
                break
            except Exception as error:
                chat_error = error
                log_handler(f"对话模型第 {attempt}/3 次调用失败: {error}")
                if attempt < 3:
                    time.sleep(2)
        if chat_error is not None:
            raise RuntimeError(f"对话模型连续 3 次调用失败: {chat_error}") from chat_error
        try:
            if generate_title and generated_content.get("title"):
                goods["_ai_generated_title"] = generated_content["title"]
                log_handler(f"对话模型已返回商品标题: {generated_content['title']}")
            if generated_content.get("image_prompt"):
                goods["_ai_generated_prompt"] = generated_content["image_prompt"]
                log_handler(
                    f"对话模型已返回完整九宫格提示词: {generated_content['image_prompt']}"
                )
        except Exception as error:
            raise RuntimeError(f"对话模型返回内容处理失败: {error}") from error

    final_prompt = build_core_prompt(product_name)
    if generate_prompt and generated_content.get("image_prompt"):
        final_prompt += "\n\nComplete nine-grid instructions from chat model:\n" + generated_content["image_prompt"]
    if current_material:
        final_prompt += (
            "\n\nCurrent material to preserve and emphasize in every panel: "
            f"{current_material}. Make the visible texture, surface finish, and hand interaction"
            " match this material consistently across the nine-grid collage."
        )
    size_hint = ""
    if isinstance(product_config, dict):
        package_info = product_config.get("包装信息", {})
        if isinstance(package_info, dict):
            dimensions = package_info.get("含包装尺寸", {})
            if isinstance(dimensions, dict):
                dimension_parts = []
                for key in ("长", "宽", "高"):
                    value = str(dimensions.get(key) or "").strip()
                    if value:
                        dimension_parts.append(f"{key}{value}cm")
                if dimension_parts:
                    size_hint = "，".join(dimension_parts)
    if size_hint:
        final_prompt += (
            "\n\nSize hint to preserve realistic scale: "
            f"{size_hint}. Keep the product's apparent size consistent with hands, desk surfaces, "
            "and everyday use so it does not look tiny or oversized."
        )
    final_prompt += (
        "\n\nPackaging exclusion: do not dedicate any of the nine panels to packaging display, "
        "even if packaging references or packaging data exist. Replace it with a confirmed "
        "product detail, alternate angle, realistic usage, display, or lifestyle scene. "
        "Do not invent boxes, bags, labels, wrappers, or other packaging. Keep all nine panels complete."
    )
    (folder / "product_name.txt").write_text(product_name, encoding="utf-8")
    (folder / "ai_prompt.txt").write_text(final_prompt, encoding="utf-8")

    provider_label = AI_PROVIDER_CONFIGS.get(ai_provider, AI_PROVIDER_CONFIGS["geeknow"])["label"]
    log_handler(f"正在调用图片模型: {provider_label} / {ai_model}，正在生成原创展示图...")
    response = None
    image_error = None
    for attempt in range(1, 4):
        try:
            response = edit_image_file(
                source_path,
                prompt=final_prompt,
                provider=ai_provider,
                token=ai_token,
                model=ai_model,
            )
            response.raise_for_status()
            image_error = None
            break
        except Exception as error:
            image_error = error
            log_handler(f"图片模型第 {attempt}/3 次调用失败: {error}")
            if attempt < 3:
                time.sleep(3)
    if image_error is not None or response is None:
        raise RuntimeError(f"图片模型连续 3 次调用失败: {image_error}") from image_error
    (folder / "ai_response.json").write_text(response.text, encoding="utf-8")

    output_path = folder / "ai_generated.png"
    if not save_ai_image_response(response, output_path):
        raise RuntimeError(f"AI 已返回结果，但没有解析到可保存的图片，响应已保存到 {folder}")

    log_handler("正在裁剪 AI 拼接图...")
    crop_dir = folder / "cropped_images"
    crop_paths = crop_ai_collage(output_path, crop_dir)
    if crop_paths:
        log_handler(f"已生成 {len(crop_paths)} 张裁剪商品图: {crop_dir}")
    else:
        log_handler("未识别到可裁剪区域，将使用 AI 原图作为商品图")
    return crop_paths or [output_path]
