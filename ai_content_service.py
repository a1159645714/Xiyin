from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import requests

from 协议AI import AI_PROVIDER_CONFIGS


def get_chat_completions_url(provider: str) -> str:
    config = AI_PROVIDER_CONFIGS.get(provider) or AI_PROVIDER_CONFIGS["geeknow"]
    image_url = str(config.get("url") or "").strip()
    if "/v1/" in image_url:
        return f"{image_url.split('/v1/', 1)[0]}/v1/chat/completions"
    return f"{image_url.rstrip('/')}/v1/chat/completions"


def _image_data_url(image_path: Path) -> str:
    suffix = image_path.suffix.lower()
    content_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def _message_text(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict)
        ).strip()
    return str(content or "").strip()


def _parse_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("对话模型没有返回有效 JSON")
    result = json.loads(cleaned[start : end + 1])
    if not isinstance(result, dict):
        raise ValueError("对话模型返回结果不是 JSON 对象")
    return result


def _contains_age_expression(title: str) -> bool:
    patterns = (
        r"\d+\s*(?:岁|周岁|月龄|个月|年龄)",
        r"(?:适合|适用|推荐)\s*\d+\s*(?:岁|周岁|个月)",
        r"\d+\s*[-~至]\s*\d+\s*(?:岁|周岁|个月)",
        r"\b\d+\s*\+\s*(?:years?|yrs?|months?)?\b",
        r"\b\d+\s*(?:years?|yrs?|months?)\s*(?:old)?\b",
    )
    return any(re.search(pattern, title, flags=re.IGNORECASE) for pattern in patterns)


def _extract_quantity(text: str) -> str:
    patterns = (
        r"(?<!\d)(\d+)\s*(?:pcs?|pieces?|packs?|sets?)\b",
        r"(?<!\d)(\d+)\s*(?:个|只|件|枚|颗|粒|套|装|包|盒)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, str(text or ""), flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def _strip_quantity_expressions(title: str) -> str:
    patterns = (
        r"(?<!\d)\d+\s*(?:pcs?|pieces?|packs?|sets?)\b",
        r"(?<!\d)\d+\s*(?:个|只|件|枚|颗|粒|套|装|包|盒)",
        r"几(?:个|只|件|枚|颗|粒|套)装",
    )
    cleaned = str(title or "")
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"^[\s,，、:/：-]+|[\s,，、:/：-]+$", "", cleaned)
    return cleaned.strip()


def _normalize_listing_title(title: str, product_name: str, original_title: str) -> str:
    quantity = (
        _extract_quantity(title)
        or _extract_quantity(original_title)
        or _extract_quantity(product_name)
    )
    cleaned_title = _strip_quantity_expressions(title)
    if quantity:
        return f"{quantity}PCS {cleaned_title}".strip()
    return cleaned_title


def _cm_to_inches(value: object) -> str:
    try:
        inches = float(str(value).strip()) * 0.3937008
    except (TypeError, ValueError):
        return ""
    return f"{inches:.2f} in"


def _build_dimension_facts(product_config: dict) -> dict[str, str]:
    package_info = product_config.get("包装信息", {})
    if not isinstance(package_info, dict):
        return {}
    dimensions = package_info.get("含包装尺寸", {})
    if not isinstance(dimensions, dict):
        return {}
    result = {
        "长": _cm_to_inches(dimensions.get("长")),
        "宽": _cm_to_inches(dimensions.get("宽")),
        "高": _cm_to_inches(dimensions.get("高")),
    }
    return {key: value for key, value in result.items() if value}


def generate_product_content(
    *,
    image_path: Path,
    product_name: str,
    goods: dict,
    product_config: dict,
    reference_image_paths: list[Path] | None = None,
    provider: str,
    token: str,
    model: str,
    timeout: int = 180,
) -> dict[str, str]:
    request_token = str(token or "").strip()
    if not request_token:
        raise ValueError("未填写对话模型 Token")

    facts = {
        "商品名称": product_name,
        "商品原始标题": product_config.get("商品标题") or "",
        "商品类别": "玩具",
        "玩具类型": "捏捏乐",
        "固定关键词": [
            "柔软",
            "解压玩具",
            "squishy",
            "squishy toys",
            "squishy stress toy",
            "nee doh",
            "dumpling squish",
            "squishy's",
            "squishies",
        ],
        "必填属性": product_config.get("必填属性", {}),
        "包装信息": product_config.get("包装信息", {}),
        "尺寸信息（英寸）": _build_dimension_facts(product_config),
        "参考图片情况": {
            "主体图片数量": sum(1 for path in (reference_image_paths or []) if path.parent.name == "主体"),
            "包装图片数量": sum(1 for path in (reference_image_paths or []) if path.parent.name == "包装"),
        },
    }
    system_prompt = """
你是跨境电商商品内容编辑。请根据商品图片和结构化商品资料，生成商品标题以及图片生成模型需要的商品专属补充提示词。

必须遵守：
1. 只使用图片或资料中能确认的商品事实，不得虚构材质、功能、配件、认证、尺寸、数量或安全承诺。
2. 商品标题必须以明确的商品数量开头，使用大写英文 PCS 格式，例如“6PCS ”、“8PCS ”，然后再写中文商品标题，最后补充相关英文搜索词。禁止使用“几个装、几件装、几只装、套装、X个、X件”等中文数量表达。数量只能来自图片或商品资料中能够确认的数量，不得猜测或虚构。
3. 标题严禁出现任何年龄信息，包括“岁、周岁、月龄、个月、适合X岁、X years old、X+ years”等表达，也不要用年龄范围暗示适用人群。
4. 标题应尽量覆盖商品类型、数量、主题或系列、主要用途和礼物/装饰等真实场景；中文部分自然易读，英文部分用于补充搜索词，不要机械重复同义词。
5. 固定关键词可作为标题末尾的英文搜索词使用，但必须结合图片和商品标题自然选择，不要全部机械堆叠，也不要因为关键词虚构商品功能。
6. image_prompt 必须是一份完整的九宫格图片生成提示词，明确列出第 1 到第 9 张图分别展示什么效果，不要只返回零散的商品补充词。
7. 九宫格至少 6 个画面必须有人手自然把玩、握持、按压、整理或互动商品；其中至少 2 个画面使用自然的女性美甲手，至少 2 个画面使用儿童手或亲子互动的手。纯背景或无人手的商品陈列最多 1 个画面，不能让多数画面只是商品放在背景上。
8. 九宫格完全不要安排包装展示图，即使存在包装图片或包装资料，也必须把该位置改为商品细节、多角度、真实使用、陈列或生活方式场景。只有在“尺寸信息（英寸）”完整时，才生成一张简洁的尺寸标注图，并且只能标注提供的长、宽、高；尺寸不完整时，改用其他可确认的商品展示效果，不能留下空白或编造信息。
9. 图片提示词只描述商品本身、真实卖点、适合的使用场景、真实颜色材质、女性美甲手/儿童手的自然互动方式和九宫格中值得展示的画面方向。
10. 不要重复全局图片规则，不要要求改变商品，不要添加包装、认证标志、警告文字、虚假配件或不存在的功能。
11. 必须只返回 JSON，不要 Markdown，不要解释文字，格式必须是：
{"title":"6PCS 中文商品标题, english keyword, search keyword","image_prompt":"1. ...\\n2. ...\\n3. ...\\n4. ...\\n5. ...\\n6. ...\\n7. ...\\n8. ...\\n9. ..."}
""".strip()
    user_text = (
        "请先识别图片中的真实商品，再结合资料生成结果。"
        "商品资料如下：\n"
        + json.dumps(facts, ensure_ascii=False, indent=2)
    )
    content = [{"type": "text", "text": user_text}]
    if image_path.is_file():
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": _image_data_url(image_path)},
            }
        )
    for reference_path in (reference_image_paths or [])[:6]:
        if reference_path.is_file() and reference_path != image_path:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _image_data_url(reference_path)},
                }
            )

    payload = {
        "model": str(model or "gpt-5.5").strip(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        "temperature": 0.7,
        "max_tokens": 1200,
    }
    response = requests.post(
        get_chat_completions_url(provider),
        headers={"Authorization": f"Bearer {request_token}"},
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    result = _parse_json(_message_text(response.json()))
    title = _normalize_listing_title(
        str(result.get("title") or "").strip(),
        product_name,
        str(product_config.get("商品标题") or ""),
    )
    image_prompt = str(result.get("image_prompt") or "").strip()
    if not title or not image_prompt:
        raise ValueError("对话模型返回结果缺少 title 或 image_prompt")
    if _contains_age_expression(title):
        raise ValueError("对话模型返回的标题包含年龄信息，已拒绝使用")
    return {"title": title[:180], "image_prompt": image_prompt}
