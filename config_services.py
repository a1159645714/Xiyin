from __future__ import annotations

import json
import os
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from config import BODY_REAL_PHOTO_DIR_NAME, CONFIG_FILE_NAME, PACKAGE_REAL_PHOTO_DIR_NAME
from product_files import get_image_files

OUTPUT_DIR = Path(__file__).with_name("output")
USD_TO_CNY_RATE = Decimal("7.20")


def normalize_url(url: str) -> str:
    url = str(url or "").strip()
    return f"https:{url}" if url.startswith("//") else url


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
def extract_result_list(value) -> list:
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return []
    for key in ("list", "data", "items", "itemList", "products", "productList", "offerList", "offers"):
        items = value.get(key)
        if isinstance(items, list):
            return items
        if isinstance(items, dict):
            nested = extract_result_list(items)
            if nested:
                return nested
    for item in value.values():
        if isinstance(item, dict):
            nested = extract_result_list(item)
            if nested:
                return nested
    return []


def normalize_aiprice_result_for_table(result: dict) -> dict:
    goods_list = extract_result_list(result)
    return {"total": len(goods_list), "list": goods_list, "raw": result}


def get_goods_id(goods: dict) -> str:
    return first_value(goods, "goodsId", "sku_id", "id", "information.id")


def get_goods_name(goods: dict) -> str:
    return first_value(goods, "goodsName", "goodsNameCn", "title", "information.title", "information.puretitle", "information.enPureTitle")


def get_goods_price(goods: dict) -> str:
    cny_source = clean_price_text(first_value(goods, "price", "salePrice", "minPrice"))
    usd_source = clean_price_text(first_value(goods, "cur_price", "price_symbol", "usd_price"))
    trade_price = clean_price_text(first_value(goods, "tradePrice.price", "tradePrice.priceMini"))
    currency = first_value(goods, "currency", "tradePrice.currency").upper()
    platform = get_goods_platform(goods).lower()

    price_is_cny = platform == "1688" or str(goods.get("adid")) == "100" or "¥" in cny_source or "￥" in cny_source
    price_is_usd = currency == "USD" and not price_is_cny
    cny_values = extract_price_range(cny_source) if price_is_cny else ""
    usd_values = extract_price_range(usd_source)

    if cny_values and usd_values:
        return f"¥{cny_values} / ${usd_values}"
    if cny_values:
        converted_usd = join_price_range(convert_price_numbers(cny_source, USD_TO_CNY_RATE, multiply=False))
        return f"¥{cny_values} / ${converted_usd}" if converted_usd else f"¥{cny_values}"
    if usd_values:
        converted_cny = join_price_range(convert_price_numbers(usd_source, USD_TO_CNY_RATE, multiply=True))
        return f"¥{converted_cny} / ${usd_values}" if converted_cny else f"${usd_values}"

    price_text = trade_price or cny_source
    if not price_text:
        return ""
    lower_price = price_text.lower()
    is_cny = currency in {"CNY", "RMB", "CNH"} or "¥" in price_text or "￥" in price_text or "cny" in lower_price or "rmb" in lower_price
    is_usd = price_is_usd or currency == "USD" or "$" in price_text or "usd" in lower_price
    if is_cny:
        return price_text
    if is_usd or re.search(r"\d", price_text):
        cny_values = convert_price_numbers(price_text, USD_TO_CNY_RATE, multiply=True)
        usd_values = extract_price_range(price_text)
        if cny_values and usd_values:
            return f"¥{join_price_range(cny_values)} / ${usd_values}"
    return price_text


def get_goods_url(goods: dict) -> str:
    return normalize_url(first_value(goods, "real_url", "href", "information.productUrl"))


def get_goods_platform(goods: dict) -> str:
    adid_names = {
        18: "AliExpress",
        23: "Amazon",
        45: "Shopee",
        50: "Ozon",
        63: "Tokopedia",
        100: "1688",
        206: "Coupang",
        224: "Yahoo JP",
        226: "Wildberries",
        256: "Naver",
        319: "Rakuten",
        431: "Domeggook",
        458: "Yandex",
        555: "Target",
        745: "TikTok",
    }
    name = goods.get("name") or goods.get("platform") or ""
    if name:
        return str(name)
    if isinstance(goods.get("information"), dict) and isinstance(goods.get("image"), dict):
        return "Alibaba"
    try:
        return adid_names.get(int(goods.get("adid")), "")
    except (TypeError, ValueError):
        return ""


def get_goods_metric(goods: dict) -> str:
    parts = []
    for label, value in (
        ("订单", goods.get("orders")),
        ("月销", goods.get("monthSold")),
        ("评分", goods.get("rating")),
        ("历史订单", get_nested(goods, "supplier.supplierHistoryOrderCount")),
        ("星级", get_nested(goods, "company.displayStarLevel")),
        ("回复率", get_nested(goods, "company.record.responseRate")),
        ("起订", get_nested(goods, "tradePrice.minOrder")),
    ):
        if value not in (None, "", 0, "0"):
            parts.append(f"{label} {value}")
    return " / ".join(parts)


def get_goods_thumbnail_url(goods: dict) -> str:
    for field in ("thumbnail", "thumbnailCn", "picture", "ori_picture", "image.mainImage", "image.productImage", "image.extendImage", "mainImage", "productImage"):
        value = get_nested(goods, field) if "." in field else goods.get(field)
        url = normalize_url(value)
        if url.startswith(("http://", "https://")):
            return url
    multi_image = get_nested(goods, "image.multiImage", [])
    if isinstance(multi_image, list):
        for value in multi_image:
            url = normalize_url(value)
            if url.startswith(("http://", "https://")):
                return url
    return ""


def find_first_video(root_dir: Path) -> Path:
    videos = sorted(path for path in root_dir.iterdir() if path.is_file() and path.suffix.lower() == ".mp4")
    if not videos:
        raise FileNotFoundError(f"商品总目录下未找到 MP4 视频: {root_dir}")
    return videos[0]


def validate_base_product_dir(root_dir: Path) -> None:
    if not root_dir.is_dir():
        raise FileNotFoundError(f"商品总目录不存在: {root_dir}")
    find_first_video(root_dir)
    get_image_files(os.fspath(root_dir / "本体"))
    get_image_files(os.fspath(root_dir / "包装"))


def write_round_product_config(
    folder: Path,
    product_config: dict,
    goods: dict,
    title_source: str,
) -> Path:
    config = json.loads(json.dumps(product_config, ensure_ascii=False))
    if title_source == "goods_name":
        goods_name = get_goods_name(goods).strip()
        if goods_name:
            config["商品标题"] = goods_name
    elif title_source == "ai":
        generated_title = str(goods.get("_ai_generated_title", "")).strip()
        if generated_title:
            config["商品标题"] = generated_title
        else:
            goods_name = get_goods_name(goods).strip()
            if goods_name:
                config["商品标题"] = goods_name
    config_file = folder / CONFIG_FILE_NAME
    config_file.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config_file

