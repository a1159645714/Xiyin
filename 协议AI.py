from pathlib import Path
import time

import requests


URL = "https://www.geeknow.top/v1/images/edits"
IMAGE_PATH = Path(__file__).with_name("img.png")
AI_PROVIDER_CONFIGS = {
    "geeknow": {
        "label": "GeekNow",
        "url": URL,
        "token": "",
        "model": "gpt-image-2",
    },
    "cangyuan": {
        "label": "\u6ca7\u6e90\u7b97\u529b",
        "url": "https://ai.cangyuansuanli.cn/v1/images/edits",
        "token": "",
        "model": "gpt-image-2",
        "size": "2880x2880",
    },
}

PROMPT = """Professional cross-border e-commerce product image set generation prompt:

Product information:
Product name: [Enter product name here]
Product category: Toy
Target platform: SHEIN
Target market: Global international markets
Target audience: General toy shoppers, including parents, gift buyers, children, families, hobby users, and toy consumers, depending on the uploaded product type.

Use the uploaded product image as the only visual reference for the target product. Use the product information above only to understand the product type, platform style, target market, and suitable commercial presentation. The uploaded product image has the highest priority. If the text information conflicts with the uploaded product image, always follow the uploaded product image and keep the target product unchanged.

Generate exactly 9 product display images inside one single final collage image. Do not output separate image files. Do not generate 4, 5, 6, 7, 8, 10, or any other number of images.

The output must be a clean structured 3x3 collage grid, not a random or irregular layout.

Use this layout only:
- For 9 images: use a 3x3 grid.

Each grid panel must contain one complete commercial product image with real content. Do not create empty panels, blank frames, placeholder areas, duplicated blank spaces, uneven panels, overlapping panels, or random collage arrangements. All panels should have clear boundaries, consistent spacing, balanced composition, and enough resolution for later cropping.

The overall collage size can be flexible, but the layout must remain neat, aligned, and easy to separate into individual product images.

Strictly keep the target product unchanged in every generated image, including its shape, structure, proportions, material, color, texture, logo, text, packaging information, labels, functional details, and visible design features. Do not redesign, replace, stretch, compress, deform, cover, beautify, or alter the target product itself.

Packaging restriction: do not add any new packaging, boxes, bags, labels, tags, hang cards, instruction sheets, manuals, barcode stickers, warning labels, certification marks, or retail display packaging that is not already visible in the uploaded image. If packaging is visible in the uploaded image, keep it unchanged and do not redesign, replace, recolor, simplify, remove, distort, or add text to it. If packaging is not visible in the uploaded image, do not create packaging in any panel.

Warning and label restriction: do not add any warning signs, warning icons, safety labels, caution symbols, age warning marks, choking hazard icons, certification badges, compliance icons, CE/FCC/UKCA/RoHS-style marks, barcode labels, QR codes, stickers, seals, tags, or any generated text labels anywhere in the image.

All elements outside the target product may be redesigned, including background, scene, lighting, props, human hands, hand gestures, skin tone, partial clothing, non-product phones, tablets, laptops, electronic devices, and overall atmosphere. If a phone or electronic device in the original image is not the target product, it may be replaced with a different generic device or removed completely. If the phone or electronic device is the target product being sold, it must remain unchanged.

The 9 panels must be designed as a complete e-commerce product detail image set. Do not make them only different angles of the same product. Each panel should answer a different buyer question and serve a different listing purpose:

1. Main product image: show the complete product clearly while a natural female hand with neat realistic manicure holds or gently presents it. Keep the product dominant, with a clean background and no text.
2. Included-items image: show only confirmed product contents while child hands or parent-child hands naturally arrange or hold the items. Do not add packaging, boxes, bags, labels, tags, manuals, barcode stickers, warning labels, certification marks, or fake accessories.
3. Core play / usage image: show realistic child hands or family hands actively playing with, squeezing, arranging, assembling, or interacting with the product according to its actual design.
4. Detail / material close-up image: show the product held by a manicured female hand, with the fingers naturally revealing texture, surface, structure, color, finish, edges, or craftsmanship without changing the product.
5. Hand interaction image: show a close realistic view of manicured female hands holding, operating, pressing, arranging, assembling, or interacting with the product. Keep all fingers anatomically correct and the product unobstructed.
6. Child interaction image: show natural child hands playing with or holding the product in a believable everyday scene; do not invent functions, unsafe actions, or unsupported age claims.
7. Parent-child interaction image: show adult and child hands interacting with the product together in a realistic play or learning scene, keeping the product unchanged.
8. Lifestyle / gift image: show the product being handed, played with, displayed, or shared through visible hands in a simple realistic home or gift scene. Do not add gift boxes, gift bags, packaging, ribbons, labels, or text unless already visible in the uploaded image.
9. Advertising whitespace / secondary hero image: show the product with a natural hand interaction and limited clean negative space for later text placement. Do not generate any text, icons, labels, badges, warnings, or marks inside the image.

Size-reference restriction: do not create explicit size-comparison images. Do not use eggs, coins, rulers, measuring tapes, credit cards, phones, cups, bottles, keys, pens, notebooks, fruit, or any other object mainly intended to show the product's size. Natural hands and fingers are encouraged for interaction, but must never be used as a direct size reference. Props may appear only if they are natural to the scene and not used as a direct size reference. Do not add measurement marks, arrows, scale lines, size labels, or comparison text.

Background requirements: all backgrounds must be extremely realistic, plain, clean, and minimal. They should look like real product photography environments or real-life commercial shooting scenes, not decorative AI-generated scenes. Use simple solid colors, neutral tones, soft gradients, natural walls, tabletops, fabric surfaces, studio backdrops, clean indoor scenes, or simple toy-use environments when appropriate. Avoid busy patterns, excessive decorations, fantasy elements, colorful effects, artificial props, exaggerated lighting, and any flashy or cluttered visual style. The background must quietly support the product and must not compete with it.

Human hand redrawing requirements: if hands are included, the hands may be fully redrawn or replaced while keeping the target product unchanged. For example, female hands can have a different manicure style, nail color, nail length, jewelry, skin tone, or hand pose; female hands can also be replaced with male hands, or male hands can be replaced with female hands, depending on the uploaded toy type and commercial scene. The new hands must look natural and realistic, with correct anatomy, the correct number of fingers, reasonable grip, and believable contact with the product. Hands must not cover key selling points, logos, text, labels, or the core structure of the target product.

Toy and interactive product usage requirements: because the product category is toy, create realistic lifestyle images that show the product being used, held, played with, assembled, displayed, or interacted with naturally when appropriate. The scene may include children, adults, families, pets, or hands interacting with the product, depending on the uploaded toy type and target shoppers. Show believable play, use, handling, assembly, display, or interaction effects that are visually consistent with the product's real design.

Do not invent functions that the product does not have. Do not add lights, sounds, moving parts, accessories, characters, parts, digital effects, water effects, flying effects, transformation effects, or special abilities unless they are clearly visible or strongly implied by the original product. Do not change the target product's shape, parts, colors, printed details, or quantity. Any play effect must look realistic, natural, and physically plausible.

Phone and electronic device requirements: if the original image contains a phone, tablet, laptop, smartwatch, earphones, or any other electronic device that is not the target product, it may be replaced with a different generic device or removed completely, depending on what makes the image cleaner and more commercially suitable. Any replacement device should look modern, realistic, unbranded, and visually simple. Do not show recognizable third-party logos, app interfaces, copyrighted screen content, private information, or distracting text. If the phone or electronic device is the target product being sold, it must remain completely unchanged.

Image style: high-end commercial photography, realistic product photography, SHEIN-style global e-commerce display image / lifestyle image style, high-definition details, soft natural lighting, realistic shadows, clean composition, sharp and clear target product, slightly blurred plain background. Suitable for SHEIN product listings, cross-border e-commerce display, and international online advertising.

Image quality and resolution requirements: generate one high-resolution photorealistic commercial product collage. Prefer a 4K final output resolution, such as 4096 x 4096 pixels or the closest supported 4K-level resolution. If true 4K output is not supported by the image generation tool, automatically fall back to 2K final output resolution, such as 2048 x 2048 pixels or the closest supported 2K-level resolution.

The resolution requirement applies to the final single collage image, not to each individual internal panel. Each panel should still remain sharp, detailed, clean, and suitable for later cropping. Preserve crisp product details, clean edges, accurate lighting, realistic shadows, natural textures, and professional color grading. Avoid blur, pixelation, compression artifacts, noise, distortion, low-detail panels, or obvious AI-generated appearance.

Composition requirements: the target product must always be the main visual focus in every panel. Keep the target product fully visible in most images, except for intentional close-up detail shots. Leave appropriate empty space for advertising text in the advertising whitespace panel. The overall output must be a structured 3x3 grid collage, but do not merge images, overlap images, crop product edges accidentally, create uneven meaningless layout spaces, or generate empty image areas.

Negative requirements: do not change the target product, do not change the brand logo, do not change packaging text, do not add any new packaging, do not add boxes, bags, labels, tags, manuals, instruction sheets, retail display packaging, barcode stickers, warning labels, certification marks, or gift packaging, do not add any warning signs, warning icons, caution symbols, age warning marks, choking hazard icons, certification badges, compliance marks, CE/FCC/UKCA/RoHS-style icons, QR codes, stickers, seals, tags, or generated text labels, do not generate incorrect text, do not add non-existent functions, do not change the product color, do not change the product quantity unless requested, do not generate 4, 5, 6, 7, 8, 10, or any unsupported number of images, do not output multiple separate images, do not create random collage layouts, do not make all panels simple angle variations, do not create explicit size comparisons, do not add eggs, coins, rulers, measuring tapes, credit cards, fruit, keys, pens, notebooks, bottles, cups, phones, or other objects used mainly as size references, do not add fake included accessories, fake packaging, fake certifications, fake safety labels, fake icons, unsupported claims, or generated text, do not create empty panels, blank spaces, placeholder frames, unfinished image blocks, meaningless collage areas, or duplicated blank frames, do not overlap images, do not crop the product unintentionally, do not create deformed hands, extra fingers, missing fingers, unrealistic manicure, unnatural hand pose, or incorrect contact with the product, do not keep distracting non-product phones or devices, do not show third-party logos or app screens, do not add unrealistic toy effects, fake motion effects, fake lighting effects, fake transformation effects, or imaginary accessories, do not make the product look melted, twisted, damaged, or unnaturally reflective, and avoid low resolution, cartoon style, obvious AI artifacts, excessive skin smoothing, cluttered backgrounds, busy patterns, flashy decorations, colorful effects, fantasy scenes, artificial-looking props, exaggerated lighting, or cheap studio-photo style."""


def build_prompt(product_name: str = "") -> str:
    name = str(product_name or "").strip() or "[Enter product name here]"
    return PROMPT.replace("Product name: [Enter product name here]", f"Product name: {name}")


CORE_PROMPT = """Create one high-resolution commercial product image collage for the uploaded product.
Generate exactly 9 complete images in a clean, aligned 3x3 grid. Every panel must contain useful visual content and remain easy to crop.
Keep the target product unchanged: shape, structure, proportions, material, color, texture, logo, printed details, packaging information, functions, and quantity.
Use only facts visible in the product image or supplied product data. Do not invent accessories, packaging, certifications, labels, warning marks, text, measurements, sizes, functions, or claims. Do not show age information.
Use realistic high-end e-commerce photography, clean minimal backgrounds, natural lighting, realistic shadows, sharp details, and product-focused composition.
At least 6 of the 9 panels must show natural hands actively holding, squeezing, arranging, playing with, or interacting with the product. Include at least 2 panels with realistic manicured female hands and at least 2 panels with child hands or parent-child hand interaction. Use no more than 1 pure product-only background display panel.
Do not use unrelated props such as rulers, coins, phones, cups, or keys as scale references. If complete dimensions are supplied, one panel may show a clean product dimension diagram using only those dimensions and the requested unit.
Do not dedicate any panel to packaging display. Replace packaging-related coverage with another confirmed product detail, angle, usage, display, or lifestyle scene. Never leave a panel blank and never invent packaging.
Do not output separate images, irregular collages, empty panels, placeholder frames, generated text, badges, logos, or warning symbols."""


def build_core_prompt(product_name: str = "") -> str:
    name = str(product_name or "").strip() or "[Enter product name here]"
    return f"{CORE_PROMPT}\nProduct name: {name}"


def get_image_content_type(image_path: str | Path) -> str:
    suffix = Path(image_path).suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    return "application/octet-stream"


def get_provider_models_url(provider_config: dict) -> str:
    request_url = str(provider_config.get("url") or URL).strip()
    for suffix in ("/v1/images/edits", "/v1/images/generations"):
        if request_url.endswith(suffix):
            return f"{request_url[:-len(suffix)]}/v1/models"
    if "/v1/" in request_url:
        return f"{request_url.split('/v1/', 1)[0]}/v1/models"
    return f"{request_url.rstrip('/')}/v1/models"


def extract_model_ids(payload) -> list[str]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("data") or payload.get("models") or payload.get("list") or payload.get("items") or []
    else:
        items = []

    model_ids = []
    for item in items:
        if isinstance(item, str):
            model_id = item
        elif isinstance(item, dict):
            model_id = item.get("id") or item.get("model") or item.get("name")
        else:
            model_id = ""
        model_id = str(model_id or "").strip()
        if model_id:
            model_ids.append(model_id)
    return sorted(dict.fromkeys(model_ids), key=str.lower)


def get_ai_model_list(provider: str = "geeknow", token: str = "", timeout: int = 60) -> list[str]:
    provider_config = AI_PROVIDER_CONFIGS.get(provider) or AI_PROVIDER_CONFIGS["geeknow"]
    request_token = str(token or "").strip()
    if not request_token:
        raise ValueError(f"请先填写 {provider_config['label']} 的 AI Token")

    response = requests.get(
        get_provider_models_url(provider_config),
        headers={"Authorization": f"Bearer {request_token}"},
        timeout=timeout,
    )
    response.raise_for_status()
    return extract_model_ids(response.json())


def poll_cangyuan_image_task(
    task_id: str,
    token: str,
    poll_url_base: str = "https://ai.cangyuansuanli.cn/v1/images/edits",
    poll_interval: int = 5,
    poll_timeout: int = 900,
):
    headers = {"Authorization": f"Bearer {token}"}
    deadline = time.monotonic() + poll_timeout
    last_response = None

    while time.monotonic() < deadline:
        response = requests.get(f"{poll_url_base.rstrip('/')}/{task_id}", headers=headers, timeout=60)
        last_response = response
        response.raise_for_status()
        payload = response.json()
        status = str(payload.get("status") or "").lower()
        if status == "completed":
            return response
        if status == "failed":
            raise RuntimeError(f"\u6ca7\u6e90\u7b97\u529b AI \u751f\u6210\u5931\u8d25: {response.text}")
        time.sleep(poll_interval)

    detail = last_response.text if last_response is not None else task_id
    raise TimeoutError(f"\u6ca7\u6e90\u7b97\u529b AI \u751f\u6210\u8d85\u65f6\uff0c\u6700\u540e\u54cd\u5e94: {detail}")


def edit_image_file(
    image_path: str | Path,
    prompt: str = PROMPT,
    provider: str = "geeknow",
    token: str = "",
    model: str = "gpt-image-2",
    size: str = "4096x4096",
    response_format: str = "url",
    quality: str = "high",
    timeout: int = 180,
):
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"找不到图片: {path}")

    provider_config = AI_PROVIDER_CONFIGS.get(provider) or AI_PROVIDER_CONFIGS["geeknow"]
    request_url = provider_config["url"]
    request_token = str(token or "").strip()
    request_model = str(model or provider_config.get("model") or "gpt-image-2").strip()
    if not request_token:
        raise ValueError(f"请先填写 {provider_config['label']} 的 AI Token")

    data = {
        "model": request_model,
        "prompt": prompt,
        "n": "1",
    }
    if provider == "cangyuan":
        data.update(
            {
                "async": "true",
                "size": str(provider_config.get("size") or "1:1"),
            }
        )
    else:
        data.update(
            {
                "size": size,
                "response_format": response_format,
                "quality": quality,
            }
        )

    headers = {
        "Authorization": f"Bearer {request_token}",
    }

    with path.open("rb") as image_file:
        files = {
            "image": (path.name, image_file, get_image_content_type(path)),
        }
        response = requests.post(
            request_url,
            data=data,
            files=files,
            headers=headers,
            timeout=timeout,
        )

    if provider == "cangyuan":
        response.raise_for_status()
        payload = response.json()
        task_id = str(payload.get("id") or "").strip()
        if not task_id:
            raise RuntimeError(f"\u6ca7\u6e90\u7b97\u529b AI \u672a\u8fd4\u56de\u4efb\u52a1 ID: {response.text}")
        return poll_cangyuan_image_task(task_id, request_token)

    return response


def main():
    try:
        response = edit_image_file(IMAGE_PATH)
        print("状态码:", response.status_code)
        print("返回内容:")
        print(response.text)
        response.raise_for_status()
    except requests.RequestException as error:
        print("请求失败:", error)


if __name__ == "__main__":
    main()
