#!/usr/bin/env python3
"""
Reproduce AliPrice extension 4.0.7 image-search requests.

Examples:
  python aiprice_image_search.py --platform 1688 --image product.jpg --cookie-file cookies.txt
  python aiprice_image_search.py --platform aliexpress --image product.jpg --cookie-file cookies.txt
  python aiprice_image_search.py --platform generic --adid 76 --image product.jpg --cookie-file cookies.txt

cookies.txt should contain only the Cookie header value:
  token=...; PHPSESSID=...; i_m_v=...; i_m_k=...
"""

from __future__ import annotations

import argparse
import base64
import http.cookiejar
import io
import json
import random
import re
import string
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

try:
    from PIL import Image
except ImportError as exc:
    raise SystemExit("Missing dependency: pip install pillow") from exc

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")


API_ROOT = "https://api.aiprice.com/index.php/chrome/items"
IMAGE_UPLOAD_URL = f"{API_ROOT}/imageUpload"
IMAGE_ANALYSIS_URL = f"{API_ROOT}/imageAnalysis"

ALIBABA_APP_NAME = "magellan"
ALIBABA_APP_KEY = "a5m1ismomeptugvfmkkjnwwqnwyrhpb1"
ALIBABA_OSS_SECRET_URL = (
    "https://open-s.alibaba.com/openservice/ossUploadSecretKeyDataService"
)
ALIBABA_IMAGE_SEARCH_URL = (
    "https://open-s.alibaba.com/openservice/sourcenowImageSearchViewService"
)
ALIBABA_IMAGE_SEARCH_FALLBACK_URL = (
    "https://open-s.alibaba.com/openservice/imageSearchViewService"
)
SHEIN_ENTRY_URL = "https://m.shein.com"
SHEIN_API_VERSION = "1.1.8"
DEFAULT_SEARCH_SIZE = 50

BSFC_RANDOM_ALPHABET = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"

PLATFORM_ADIDS = {
    "aliexpress": "18",
    "amazon": "23",
    "coupang": "206",
    "domeggook": "431",
    "naver": "256",
    "ozon": "50",
    "rakuten": "319",
    "shopee": "45",
    "target": "555",
    "tiktok": "745",
    "tokopedia": "63",
    "wildberries": "226",
    "yahoo-jp": "224",
    "yandex": "458",
}

SPECIAL_PLATFORMS = {"alibaba", "shein", "walmart"}

HELPER_ONLY_PLATFORMS = {
    "walmart": {
        "adid": "200",
        "message": (
            "AliPrice 4.0.7 contains a Walmart page-image helper, but no "
            "Walmart image-search request handler."
        ),
    },
}

PLATFORM_ALIASES = {
    "1688": "1688",
    "阿里巴巴中国站": "1688",
    "阿里巴巴国内站": "1688",
    "aliexpress": "aliexpress",
    "速卖通": "aliexpress",
    "全球速卖通": "aliexpress",
    "alibaba": "alibaba",
    "alibaba.com": "alibaba",
    "阿里巴巴国际站": "alibaba",
    "amazon": "amazon",
    "亚马逊": "amazon",
    "coupang": "coupang",
    "酷澎": "coupang",
    "domeggook": "domeggook",
    "naver": "naver",
    "navershopping": "naver",
    "ozon": "ozon",
    "rakuten": "rakuten",
    "乐天": "rakuten",
    "shein": "shein",
    "shopee": "shopee",
    "虾皮": "shopee",
    "target": "target",
    "tiktok": "tiktok",
    "tiktokshop": "tiktok",
    "tokopedia": "tokopedia",
    "walmart": "walmart",
    "沃尔玛": "walmart",
    "wildberries": "wildberries",
    "yahoo-jp": "yahoo-jp",
    "yahoojp": "yahoo-jp",
    "雅虎日本": "yahoo-jp",
    "yandex": "yandex",
}


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def random4() -> str:
    return "".join(random.choice(BSFC_RANDOM_ALPHABET) for _ in range(4))


def make_bsfc_sign(value: Any, prefix: str | None = None, suffix: str | None = None) -> str:
    """
    Extension source algorithm:
      JSON.stringify(value)
      -> encodeURIComponent
      -> Base64
      -> remove '=' padding
      -> insert padding count after first and before last character
      -> RANDOM4.middle.RANDOM4
    """
    text = value if isinstance(value, str) else compact_json(value)
    encoded = quote(text, safe="~()*!.'-")
    b64 = base64.b64encode(encoded.encode("utf-8")).decode("ascii")
    padding_count = b64.count("=")
    b64 = b64.rstrip("=")

    if len(b64) < 2:
        raise ValueError("Value is too short for bsfc encoding")

    middle = (
        b64[0]
        + str(padding_count)
        + b64[1:-1]
        + str(padding_count)
        + b64[-1]
    )
    return f"{prefix or random4()}.{middle}.{suffix or random4()}"


def decode_bsfc_sign(sign: str) -> Any:
    prefix, middle, suffix = sign.split(".", 2)
    del prefix, suffix

    padding_count = int(middle[1])
    clean = middle[0] + middle[2:-2] + middle[-1]
    clean += "=" * padding_count
    encoded = base64.b64decode(clean).decode("utf-8")
    text = unquote(encoded)
    return json.loads(text)


def make_m_info_cookie(
    platform: str = "1688",
    version: str = "4.0.7",
    browser: str = "chrome",
    method: str = "bsfc",
    timestamp_ms: int | None = None,
) -> str:
    """
    Locally generate the only cookie required by the tested imageAnalysis route.
    The server uses this metadata to select the sign decoding method.
    """
    value = [
        {
            "platform": platform,
            "version": version,
            "browser": browser,
            "m": method,
            "t": timestamp_ms if timestamp_ms is not None else int(time.time() * 1000),
        }
    ]
    return "m-info=" + quote(compact_json(value), safe="")


def cookie_has_name(cookie: str, name: str) -> bool:
    return any(
        part.strip().split("=", 1)[0] == name
        for part in cookie.split(";")
        if "=" in part
    )


def normalize_platform_name(platform_name: str) -> str:
    key = platform_name.strip().lower()
    compact_key = (
        key.replace(" ", "")
        .replace("_", "")
        .replace("-", "")
        .replace(".", "")
    )

    for alias, platform in PLATFORM_ALIASES.items():
        alias_key = alias.lower()
        alias_compact = (
            alias_key.replace(" ", "")
            .replace("_", "")
            .replace("-", "")
            .replace(".", "")
        )
        if key == alias_key or compact_key == alias_compact:
            return platform

    supported = sorted(set(PLATFORM_ALIASES.values()))
    raise ValueError(
        f"Unsupported platform: {platform_name}. "
        f"Supported platform names: {', '.join(supported)}"
    )


def prepare_jpeg(path: Path) -> bytes:
    """
    Matches the common handler settings:
      JPEG, quality 0.8, resize enabled, max 300x300.
    """
    with Image.open(path) as image:
        image = image.convert("RGB")
        image.thumbnail((300, 300), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=80, optimize=True)
        return output.getvalue()


def read_cookie(args: argparse.Namespace) -> str:
    cookie = ""
    if args.cookie:
        cookie = args.cookie.strip()
    elif args.cookie_file:
        cookie = Path(args.cookie_file).read_text(encoding="utf-8").strip()

    if not args.no_auto_m_info and not cookie_has_name(cookie, "m-info"):
        generated = make_m_info_cookie()
        cookie = f"{cookie}; {generated}" if cookie else generated
    return cookie


def common_headers(cookie: str) -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "browser": "chrome",
        "channel": "chrome",
        "ext_id": "10600",
        "ext-id": "10600",
        "version": "4.0.7",
        "platform": "1688",
        "Origin": "chrome-extension://ccheepfhfjiafnlakajbfhlpcigpplec",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36"
        ),
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


def safe_headers(headers: dict[str, str]) -> dict[str, str]:
    result = dict(headers)
    if "Cookie" in result:
        result["Cookie"] = "<COOKIE_REDACTED>"
    return result


def print_request(
    method: str,
    url: str,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
    body: Any = None,
) -> None:
    print(f"\n[{method}] {url}")
    if params:
        print("Query:")
        print(json.dumps(params, ensure_ascii=False, indent=2))
    print("Headers:")
    print(json.dumps(safe_headers(headers), ensure_ascii=False, indent=2))
    if body is not None:
        print("Body:")
        print(json.dumps(body, ensure_ascii=False, indent=2))


def request_1688(
    jpeg: bytes,
    headers: dict[str, str],
    args: argparse.Namespace,
) -> dict[str, Any]:
    params_to_sign: dict[str, Any] = {
        "page": args.page if args.page is not None else 1,
        "size": args.size,
        "website": "1688_lite2",
        "language": args.language,
        "currency": args.currency,
        "from": args.source,
        "itemTitle": args.title,
        "domain": args.domain,
    }
    sign = make_bsfc_sign(params_to_sign)

    # 1688 Lite keeps the clear parameters and appends sign.
    query = dict(params_to_sign)
    query["sign"] = sign
    body = {"imageBase64": base64.b64encode(jpeg).decode("ascii")}

    print_request(
        "POST",
        IMAGE_ANALYSIS_URL,
        headers,
        query,
        {"imageBase64": f"<BASE64:{len(body['imageBase64'])} chars>"},
    )
    print("Decoded sign:")
    print(json.dumps(decode_bsfc_sign(sign), ensure_ascii=False, indent=2))

    if args.dry_run:
        return {"dryRun": True, "params": query}

    return http_json(
        "POST",
        IMAGE_ANALYSIS_URL,
        headers=headers,
        query=query,
        body=compact_json(body).encode("utf-8"),
        timeout=args.timeout,
    )


def upload_for_adid(
    jpeg: bytes,
    headers: dict[str, str],
    adid: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    upload_headers = dict(headers)
    # requests must generate the multipart boundary itself.
    upload_headers.pop("Content-Type", None)

    print_request(
        "POST",
        IMAGE_UPLOAD_URL,
        upload_headers,
        body={
            "multipart": {
                "file": f"<JPEG:{len(jpeg)} bytes>",
                "adid": adid,
            }
        },
    )

    if args.dry_run:
        return {"success": 1, "uploadKey": "DRY_RUN_UPLOAD_KEY.jpg"}

    boundary = f"----AliPriceBoundary{uuid.uuid4().hex}"
    multipart = build_multipart(
        boundary,
        fields={"adid": adid},
        files={"file": ("search.jpg", "image/jpeg", jpeg)},
    )
    upload_headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    return http_json(
        "POST",
        IMAGE_UPLOAD_URL,
        headers=upload_headers,
        body=multipart,
        timeout=args.timeout,
    )


def request_by_adid(
    jpeg: bytes,
    headers: dict[str, str],
    adid: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    upload = upload_for_adid(jpeg, headers, adid, args)
    upload_key = upload.get("uploadKey")
    if not upload_key:
        raise RuntimeError(f"imageUpload did not return uploadKey: {upload}")

    params_to_sign: dict[str, Any] = {
        "uploadKey": upload_key,
        "page": args.page if args.page is not None else 0,
        "size": args.size,
        "language": args.language,
        "adids": str(adid),
    }
    if args.cateid:
        params_to_sign["cateid"] = args.cateid
    if args.phash:
        params_to_sign["phash"] = args.phash

    sign = make_bsfc_sign(params_to_sign)
    query = {"sign": sign}

    print_request("GET", IMAGE_ANALYSIS_URL, headers, query)
    print("Decoded sign:")
    print(json.dumps(decode_bsfc_sign(sign), ensure_ascii=False, indent=2))

    if args.dry_run:
        return {
            "dryRun": True,
            "upload": upload,
            "params": params_to_sign,
            "sign": sign,
        }

    return http_json(
        "GET",
        IMAGE_ANALYSIS_URL,
        headers=headers,
        query=query,
        timeout=args.timeout,
    )


def parse_jsonp(raw: bytes | str) -> dict[str, Any]:
    """Parse either plain JSON or callback({...}) JSONP."""
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    text = text.strip()
    match = re.match(r"^[^(]*\((.*)\)\s*;?\s*$", text, flags=re.DOTALL)
    if match:
        text = match.group(1)
    result = json.loads(text)
    if not isinstance(result, dict):
        raise RuntimeError(f"Expected an object response, got: {type(result).__name__}")
    return result


def request_alibaba(
    jpeg: bytes,
    headers: dict[str, str],
    args: argparse.Namespace,
) -> dict[str, Any]:
    """
    Alibaba.com does not use AliPrice imageUpload/imageAnalysis + adid 76.

    Extension 4.0.7 uses Alibaba's native flow:
      ossUploadSecretKeyDataService
      -> upload JPEG to Alibaba OSS
      -> sourcenowImageSearchViewService
    """
    del headers  # The native Alibaba flow does not require the AliPrice cookie.

    timestamp = int(time.time() * 1000)
    secret_callback = f"jQuery18303056861580429502_{timestamp}"
    secret_params = {
        "appKey": ALIBABA_APP_KEY,
        "appName": ALIBABA_APP_NAME,
        "callback": secret_callback,
        "_": timestamp,
    }
    native_headers = {
        "Accept": "*/*",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36"
        ),
        "Origin": "https://www.alibaba.com",
        "Referer": "https://www.alibaba.com/",
    }

    print_request("GET", ALIBABA_OSS_SECRET_URL, native_headers, secret_params)
    if args.dry_run:
        secret = {
            "code": 200,
            "data": {
                "host": "https://ALIBABA_OSS_HOST",
                "imagePath": "icbuimgsearch",
                "policy": "POLICY",
                "accessid": "OSS_ACCESS_KEY_ID",
                "signature": "OSS_SIGNATURE",
            },
        }
    else:
        secret = parse_jsonp(
            http_raw(
                "GET",
                ALIBABA_OSS_SECRET_URL,
                headers=native_headers,
                query=secret_params,
                timeout=args.timeout,
            )
        )

    secret_data = secret.get("data") or {}
    if int(secret.get("code") or 0) != 200 or not all(
        secret_data.get(key)
        for key in ("host", "imagePath", "policy", "accessid", "signature")
    ):
        raise RuntimeError(f"Alibaba OSS authorization failed: {secret}")

    random_name = "".join(
        random.choice(string.ascii_letters + string.digits) for _ in range(10)
    )
    filename = f"{random_name}.jpg"
    object_key = f"{str(secret_data['imagePath']).rstrip('/')}/{filename}"
    image_address = f"/{object_key}"
    boundary = f"----AlibabaImageSearchBoundary{uuid.uuid4().hex}"
    upload_body = build_multipart(
        boundary,
        fields={
            "name": filename,
            "key": object_key,
            "policy": str(secret_data["policy"]),
            "OSSAccessKeyId": str(secret_data["accessid"]),
            "success_action_status": "200",
            "callback": "",
            "signature": str(secret_data["signature"]),
        },
        files={"file": (filename, "image/jpeg", jpeg)},
    )
    upload_headers = dict(native_headers)
    upload_headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    print_request(
        "POST",
        str(secret_data["host"]),
        upload_headers,
        body={
            "multipart": {
                "file": f"<JPEG:{len(jpeg)} bytes>",
                "key": object_key,
                "OSSAccessKeyId": "<TEMPORARY_ACCESS_ID>",
                "policy": "<POLICY>",
                "signature": "<SIGNATURE>",
            }
        },
    )
    if not args.dry_run:
        http_raw(
            "POST",
            str(secret_data["host"]),
            headers=upload_headers,
            body=upload_body,
            timeout=args.timeout,
        )

    timestamp = int(time.time() * 1000)
    search_callback = f"jsonp_{timestamp}_{random.randint(1, 10000)}"
    search_params: dict[str, Any] = {
        "appKey": ALIBABA_APP_KEY,
        "appName": ALIBABA_APP_NAME,
        "pageSize": args.size,
        "beginPage": args.page if args.page is not None else 1,
        "imageType": "oss",
        "imageAddress": image_address,
        "callback": search_callback,
        "_": timestamp,
    }
    if args.cateid:
        search_params["categoryId"] = args.cateid
    print_request("GET", ALIBABA_IMAGE_SEARCH_URL, native_headers, search_params)

    if args.dry_run:
        return {
            "dryRun": True,
            "mode": "alibaba_native",
            "imageAddress": image_address,
            "params": search_params,
        }

    result = parse_jsonp(
        http_raw(
            "GET",
            ALIBABA_IMAGE_SEARCH_URL,
            headers=native_headers,
            query=search_params,
            timeout=args.timeout,
        )
    )

    # This is the same fallback used by extension 4.0.7 when source-now
    # returns code 200 but an empty offerList.
    data = result.get("data") or {}
    if int(result.get("code") or 0) == 200 and not (data.get("offerList") or []):
        fallback_params: dict[str, Any] = {
            "pageSize": search_params["pageSize"],
            "beginPage": search_params["beginPage"],
            "imageType": "oss",
            "imageAddress": image_address,
            "categoryId": search_params.get("categoryId") or "66666666",
        }
        if data.get("region"):
            fallback_params["region"] = data["region"]
        if data.get("language"):
            fallback_params["language"] = data["language"]
        print_request(
            "GET",
            ALIBABA_IMAGE_SEARCH_FALLBACK_URL,
            native_headers,
            fallback_params,
        )
        try:
            fallback = parse_jsonp(
                http_raw(
                    "GET",
                    ALIBABA_IMAGE_SEARCH_FALLBACK_URL,
                    headers=native_headers,
                    query=fallback_params,
                    timeout=args.timeout,
                )
            )
            fallback_data = fallback.get("data") or {}
            if fallback_data.get("offers") and not fallback_data.get("offerList"):
                fallback_data["offerList"] = fallback_data["offers"]
            if fallback_data:
                result = fallback
        except Exception as exc:
            print(f"Alibaba fallback search error: {exc}", file=sys.stderr)

    return result


def opener_raw(
    opener: Any,
    method: str,
    url: str,
    headers: dict[str, str],
    query: dict[str, Any] | None = None,
    body: bytes | None = None,
    timeout: float = 60,
    retries: int = 2,
) -> tuple[bytes, str]:
    if query:
        url = f"{url}?{urlencode(query)}"

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with opener.open(request, timeout=timeout) as response:
                raw = response.read()
                print(f"HTTP {response.status} {response.reason}")
                return raw, response.geturl()
        except HTTPError as error:
            raw = error.read()
            raise RuntimeError(
                f"HTTP {error.code} {error.reason}: "
                f"{raw.decode('utf-8', errors='replace')[:1000]}"
            ) from error
        except URLError as error:
            last_error = error
            if attempt >= retries:
                break
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"Request failed after retries: {last_error}")


def request_shein(
    jpeg: bytes,
    headers: dict[str, str],
    args: argparse.Namespace,
) -> dict[str, Any]:
    """
    Reproduce extension 4.0.7's native SHEIN flow:
      open mobile SHEIN/presearch to establish regional session
      -> POST /bff-api/setting/upload_image
      -> POST /bff-api/product/recommend/image_search
    """
    del headers  # SHEIN uses its own regional session cookies.

    cookie_jar = http.cookiejar.CookieJar()
    opener = build_opener(HTTPCookieProcessor(cookie_jar))
    mobile_ua = (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Mobile Safari/537.36"
    )
    navigation_headers = {
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": mobile_ua,
    }

    print_request("GET", SHEIN_ENTRY_URL, navigation_headers)
    if args.dry_run:
        site_host = "https://m.shein.com/REGION"
        site_language = "en"
    else:
        home_raw, final_url = opener_raw(
            opener,
            "GET",
            SHEIN_ENTRY_URL,
            navigation_headers,
            timeout=args.timeout,
        )
        parsed = urlsplit(final_url)
        site_host = f"{parsed.scheme}://{parsed.netloc}"
        home_text = home_raw.decode("utf-8", errors="replace")
        language_match = re.search(
            r'(?:data-app-language|app-language)="([^"]+)"',
            home_text,
            flags=re.IGNORECASE,
        )
        site_language = language_match.group(1) if language_match else "en"

    presearch_params = {
        "Searchboxform": "2",
        "pageType": "all",
        "pagefrom": "page_search",
        "pre_search_content": "Christmas",
        "src_identifier": "st=6`sc=Christmas`sr=0`ps=1",
    }
    presearch_url = f"{site_host.rstrip('/')}/presearch"
    print_request("GET", presearch_url, navigation_headers, presearch_params)
    if not args.dry_run:
        opener_raw(
            opener,
            "GET",
            presearch_url,
            navigation_headers,
            query=presearch_params,
            timeout=args.timeout,
        )

    api_headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": site_host,
        "Referer": f"{presearch_url}?{urlencode(presearch_params)}",
        "User-Agent": mobile_ua,
        "X-Requested-With": "XMLHttpRequest",
    }
    filename = (
        "".join(random.choice(string.ascii_letters + string.digits) for _ in range(10))
        + ".jpg"
    )
    upload_boundary = f"----SheinImageSearchBoundary{uuid.uuid4().hex}"
    upload_body = build_multipart(
        upload_boundary,
        fields={},
        files={"image": (filename, "image/jpeg", jpeg)},
    )
    upload_headers = dict(api_headers)
    upload_headers["Content-Type"] = (
        f"multipart/form-data; boundary={upload_boundary}"
    )
    upload_url = f"{site_host.rstrip('/')}/bff-api/setting/upload_image"
    upload_params = {"_ver": SHEIN_API_VERSION, "_lang": "en"}
    print_request(
        "POST",
        upload_url,
        upload_headers,
        upload_params,
        {"multipart": {"image": f"<JPEG:{len(jpeg)} bytes>"}},
    )
    if args.dry_run:
        uploaded_url = "https://img.shein.com/PATH/IMAGE.jpg"
        upload_result = {"code": "0", "msg": "ok", "info": {"path": uploaded_url}}
    else:
        upload_raw, _ = opener_raw(
            opener,
            "POST",
            upload_url,
            upload_headers,
            query=upload_params,
            body=upload_body,
            timeout=args.timeout,
        )
        upload_result = json.loads(upload_raw.decode("utf-8", errors="replace"))
        uploaded_url = str((upload_result.get("info") or {}).get("path") or "")

    if str(upload_result.get("code")) != "0" or not uploaded_url:
        raise RuntimeError(f"SHEIN image upload failed: {upload_result}")

    search_boundary = f"----SheinImageSearchBoundary{uuid.uuid4().hex}"
    search_body = build_multipart(
        search_boundary,
        fields={
            "img_url": uploaded_url,
            "sort": "",
            "filter_goods_id": "",
        },
        files={},
    )
    search_headers = dict(api_headers)
    search_headers["Content-Type"] = (
        f"multipart/form-data; boundary={search_boundary}"
    )
    search_url = (
        f"{site_host.rstrip('/')}/bff-api/product/recommend/image_search"
    )
    search_params = {
        "_ver": SHEIN_API_VERSION,
        "_lang": site_language,
    }
    print_request(
        "POST",
        search_url,
        search_headers,
        search_params,
        {
            "multipart": {
                "img_url": uploaded_url,
                "sort": "",
                "filter_goods_id": "",
            }
        },
    )
    if args.dry_run:
        return {
            "dryRun": True,
            "mode": "shein_native",
            "siteHost": site_host,
            "siteLanguage": site_language,
            "uploadedUrl": uploaded_url,
        }

    try:
        search_raw, _ = opener_raw(
            opener,
            "POST",
            search_url,
            search_headers,
            query=search_params,
            body=search_body,
            timeout=args.timeout,
        )
    except RuntimeError as exc:
        if "HTTP 403" in str(exc):
            return {
                "success": 0,
                "code": "SHEIN_DYNAMIC_HEADERS_REQUIRED",
                "msg": (
                    "SHEIN accepted the image upload, but its image-search "
                    "endpoint requires short-lived headers generated by the "
                    "SHEIN page runtime."
                ),
                "details": {
                    "siteHost": site_host,
                    "siteLanguage": site_language,
                    "uploadedUrl": uploaded_url,
                    "requiredHeaderExamples": [
                        "armorToken",
                        "x-cs-random",
                        "x-csrf-token",
                        "x-gw-auth",
                        "x-oest",
                    ],
                    "cookieAloneIsSufficient": False,
                    "extensionImplementsOfflineSigner": False,
                },
            }
        raise
    result = json.loads(search_raw.decode("utf-8", errors="replace"))
    return result


def request_helper_only_platform(platform: str) -> dict[str, Any]:
    info = HELPER_ONLY_PLATFORMS[platform]
    return {
        "success": 0,
        "code": "NO_IMAGE_SEARCH_HANDLER",
        "msg": info["message"],
        "platform": platform,
        "details": {
            "configuredAdid": info["adid"],
            "legacyAliPriceResponseCode": 20024,
            "cookieRequired": False,
        },
    }


def search_by_image(
    image_file: str | Path,
    platform_name: str,
    page: int | None = None,
    size: int = DEFAULT_SEARCH_SIZE,
) -> dict[str, Any]:
    """
    Independent two-argument API.

    Args:
        image_file: Local image path.
        platform_name: Platform name, for example 1688, AliExpress, 速卖通,
                       Amazon, 亚马逊, Alibaba, Walmart.

    Returns:
        Parsed JSON response.

    For AliPrice-backed platforms, the function generates the minimal m-info
    cookie and bsfc sign locally. Alibaba.com uses its separate native
    Alibaba OSS + image-search flow and does not need the AliPrice cookie.
    """
    image_path = Path(image_file).expanduser().resolve()
    if not image_path.is_file():
        raise FileNotFoundError(f"Image does not exist: {image_path}")

    platform = normalize_platform_name(platform_name)
    jpeg = prepare_jpeg(image_path)
    cookie = make_m_info_cookie()
    headers = common_headers(cookie)

    args = SimpleNamespace(
        page=page,
        size=size,
        language="zh-CN",
        currency="USD",
        source="",
        title=image_path.stem,
        domain="local.image",
        cateid="",
        phash="",
        timeout=60,
        dry_run=False,
    )

    print(
        json.dumps(
            {
                "image": str(image_path),
                "platformInput": platform_name,
                "platform": platform,
                "preparedJPEGBytes": len(jpeg),
                "page": page,
                "size": size,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if platform == "1688":
        result = request_1688(jpeg, headers, args)
    elif platform == "alibaba":
        result = request_alibaba(jpeg, headers, args)
    elif platform == "shein":
        result = request_shein(jpeg, headers, args)
    elif platform in HELPER_ONLY_PLATFORMS:
        result = request_helper_only_platform(platform)
    else:
        result = request_by_adid(
            jpeg,
            headers,
            PLATFORM_ADIDS[platform],
            args,
        )

    print("\nSearch result:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def build_multipart(
    boundary: str,
    fields: dict[str, str],
    files: dict[str, tuple[str, str, bytes]],
) -> bytes:
    output = io.BytesIO()
    marker = boundary.encode("ascii")

    for name, value in fields.items():
        output.write(b"--" + marker + b"\r\n")
        output.write(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8")
        )
        output.write(str(value).encode("utf-8"))
        output.write(b"\r\n")

    for name, (filename, content_type, data) in files.items():
        output.write(b"--" + marker + b"\r\n")
        output.write(
            (
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"\r\n'
            ).encode("utf-8")
        )
        output.write(f"Content-Type: {content_type}\r\n\r\n".encode("ascii"))
        output.write(data)
        output.write(b"\r\n")

    output.write(b"--" + marker + b"--\r\n")
    return output.getvalue()


def http_json(
    method: str,
    url: str,
    headers: dict[str, str],
    query: dict[str, Any] | None = None,
    body: bytes | None = None,
    timeout: float = 60,
) -> dict[str, Any]:
    if query:
        url = f"{url}?{urlencode(query)}"
    request = Request(url, data=body, headers=headers, method=method)

    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            print(f"HTTP {response.status} {response.reason}")
            content_type = response.headers.get("Content-Type", "")
    except HTTPError as error:
        raw = error.read()
        raise RuntimeError(
            f"HTTP {error.code} {error.reason}: "
            f"{raw.decode('utf-8', errors='replace')[:1000]}"
        ) from error

    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Response is not JSON ({content_type}): "
            f"{raw.decode('utf-8', errors='replace')[:500]}"
        ) from exc


def http_raw(
    method: str,
    url: str,
    headers: dict[str, str],
    query: dict[str, Any] | None = None,
    body: bytes | None = None,
    timeout: float = 60,
) -> bytes:
    if query:
        url = f"{url}?{urlencode(query)}"
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            print(f"HTTP {response.status} {response.reason}")
            return raw
    except HTTPError as error:
        raw = error.read()
        raise RuntimeError(
            f"HTTP {error.code} {error.reason}: "
            f"{raw.decode('utf-8', errors='replace')[:1000]}"
        ) from error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce AliPrice 4.0.7 image-search requests."
    )
    parser.add_argument(
        "--platform",
        required=True,
        choices=[
            "1688",
            "generic",
            *sorted(SPECIAL_PLATFORMS),
            *sorted(PLATFORM_ADIDS),
        ],
    )
    parser.add_argument("--adid", help="Required with --platform generic")
    parser.add_argument("--image", required=True, help="Input image path")
    parser.add_argument("--cookie", help="Raw Cookie header value")
    parser.add_argument("--cookie-file", help="UTF-8 file containing Cookie value")
    parser.add_argument(
        "--no-auto-m-info",
        action="store_true",
        help="Do not locally generate the m-info cookie",
    )
    parser.add_argument("--page", type=int)
    parser.add_argument("--size", type=int, default=DEFAULT_SEARCH_SIZE)
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--source", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--domain", default="SOURCE_DOMAIN")
    parser.add_argument("--cateid", default="")
    parser.add_argument("--phash", default="")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", default="response.json")
    return parser.parse_args()


def main() -> int:
    # Simplified invocation:
    #   python aiprice_image_search.py IMAGE_FILE PLATFORM_NAME
    if len(sys.argv) == 3 and not sys.argv[1].startswith("-"):
        search_by_image(sys.argv[1], sys.argv[2])
        return 0

    args = parse_args()
    image_path = Path(args.image)
    if not image_path.is_file():
        raise SystemExit(f"Image does not exist: {image_path}")

    if args.platform == "generic" and not args.adid:
        raise SystemExit("--platform generic requires --adid")

    cookie = read_cookie(args)
    jpeg = prepare_jpeg(image_path)
    headers = common_headers(cookie)

    print(
        json.dumps(
            {
                "input": str(image_path.resolve()),
                "preparedJPEGBytes": len(jpeg),
                "platform": args.platform,
                "cookieProvided": bool(cookie),
                "dryRun": args.dry_run,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if args.platform == "1688":
        result = request_1688(jpeg, headers, args)
    elif args.platform == "alibaba":
        result = request_alibaba(jpeg, headers, args)
    elif args.platform == "shein":
        result = request_shein(jpeg, headers, args)
    elif args.platform in HELPER_ONLY_PLATFORMS:
        result = request_helper_only_platform(args.platform)
    else:
        adid = args.adid if args.platform == "generic" else PLATFORM_ADIDS[args.platform]
        result = request_by_adid(jpeg, headers, adid, args)

    output = Path(args.output)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nSaved response: {output.resolve()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
