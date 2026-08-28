import json
import os
import random
import re
import shutil
import tempfile
import threading
from datetime import datetime
from typing import Any, Callable

from PIL import Image
from playwright.sync_api import BrowserContext, Page, Playwright, TimeoutError as PlaywrightTimeoutError

from config import (
    ATTRIBUTE_LABEL_ALIASES,
    ATTRIBUTE_LABEL_MAP,
    BODY_REAL_PHOTO_DIR_NAME,
    CATEGORY_CHILD_TEXT,
    CATEGORY_ROOT_TEXT,
    CERTIFICATE_CONFIG_KEY,
    CERTIFICATE_ENABLED_KEY,
    CERTIFICATE_NAME_KEYS,
    COMPLIANCE_INFO_ROW_ALIASES,
    COMPLIANCE_INFO_SECTION_TEXT,
    CONFIGURABLE_QUALIFICATIONS,
    CONFIRM_NEXT_TEXT,
    DEFAULT_PRODUCT_TITLE,
    DEFAULT_PUBLISH_CATEGORY_PATH,
    EDIT_STOCK_TEXT,
    EDIT_TEXT,
    EU_TOY_SAFETY_DIRECTIVE_TEXT,
    EXPAND_VIDEO_TEXT,
    I_KNOW_TEXT,
    MARKET_HOT_TEXT,
    MULTI_COLOR_TEXT,
    NEW_IMAGE_UPLOAD_TEXT,
    NO_CHOKING_WARNING_TEXT,
    NO_MORE_UPLOAD_TEXT,
    NOT_UNDER_3_TEXT,
    OK_TEXT,
    OTHER_TEXT,
    PACKAGE_REAL_PHOTO_DIR_NAME,
    PIECE_TYPE_TEXT,
    PRICE_MAX,
    PRICE_MIN,
    PRODUCT_ATTRIBUTES,
    PRODUCT_IDENTIFIER_TEXT,
    SCARCE_HOT_TAB_TEXT,
    PUBLISH_AND_SIGN_UP_TEXT,
    PUBLISH_ENTRY_TEXTS,
    PUBLISH_SAME_TEXT,
    REAL_PHOTO_QUALIFICATION_KEYWORD,
    REAL_PHOTO_SECTION_TEXT,
    SEARCH_TEXT,
    STOCK_VALUE,
    SUBMIT_TEXT,
    TARGET_URL,
    TOY_HAZARD_DESC_TEXT,
    TOY_MANUAL_QUALIFICATION,
    TOY_TYPE_TEXT,
    UPLOAD_TEXT,
    USER_DATA_DIR,
    USE_TEMPLATE_TEXT,
    US_CHOKING_HAZARD_TEXT,
    VIEWPORT_HEIGHT,
    VIEWPORT_WIDTH,
)
from product_files import ProductFiles, load_product_config, resolve_product_file_sets


LogHandler = Callable[[str], None]


class AutomationCancelled(RuntimeError):
    """Raised when the user requests a cooperative stop."""


class PublishBlockedRetry(RuntimeError):
    """Raised when the current publish entry is blocked and should be retried."""


class BrowserAutomation:
    def __init__(
        self,
        playwright: Playwright,
        product_root_dir: str,
        cookies_file: str,
        viewport_width: int = VIEWPORT_WIDTH,
        viewport_height: int = VIEWPORT_HEIGHT,
        pause_event: threading.Event | None = None,
        stop_event: threading.Event | None = None,
        opportunity_tab: str = SCARCE_HOT_TAB_TEXT,
        category_path: tuple[str, ...] = (CATEGORY_ROOT_TEXT, CATEGORY_CHILD_TEXT),
        publish_category_path: tuple[str, ...] = DEFAULT_PUBLISH_CATEGORY_PATH,
        product_file_sets: list[ProductFiles] | None = None,
        common_mark_image_file: str = "",
        log: LogHandler | None = None,
    ) -> None:
        self.playwright = playwright
        self.product_root_dir = product_root_dir
        self.product_file_sets = (
            product_file_sets
            if product_file_sets is not None
            else resolve_product_file_sets(product_root_dir)
        )
        if not self.product_file_sets:
            raise FileNotFoundError("未找到可发布的商品图片轮次")
        config_file = self.product_file_sets[0].config_file
        if not config_file or not os.path.isfile(config_file):
            raise FileNotFoundError("当前商品没有生成发布配置，请先执行商品准备")
        self.product_config = load_product_config(os.path.dirname(config_file))
        self.product_files = self.product_file_sets[0]
        self.main_image_file = ""
        self.image_dir = ""
        self.product_video_file = ""
        self.cookies_file = cookies_file
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self.pause_event = pause_event
        self.stop_event = stop_event
        self.opportunity_tab = opportunity_tab
        self.category_path = tuple(
            category_name.strip()
            for category_name in category_path
            if category_name.strip()
        )
        self.publish_category_path = tuple(
            category_name.strip()
            for category_name in publish_category_path
            if category_name.strip()
        )
        self.common_mark_image_file = common_mark_image_file.strip()
        self.log_handler = log or print
        self.supplier_code = ""
        self.product_skc = ""
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.temp_dir: str | None = None
        self.set_active_product_files(self.product_files)

    def set_active_product_files(self, product_files) -> None:
        self.product_files = product_files
        self.main_image_file = product_files.main_image_file
        self.image_dir = product_files.selected_image_dir
        self.product_video_file = product_files.product_video_file
        if not product_files.config_file or not os.path.isfile(product_files.config_file):
            raise FileNotFoundError("当前商品没有生成发布配置，请先执行商品准备")
        self.product_config = load_product_config(os.path.dirname(product_files.config_file))
        self.supplier_code = self.get_supplier_code_from_config()
        self.product_skc = ""

    def log(self, message: str) -> None:
        self.log_handler(message)

    def ensure_not_cancelled(self) -> None:
        if self.stop_event is not None and self.stop_event.is_set():
            raise AutomationCancelled("用户已请求停止运行")

    def wait_if_paused(self) -> None:
        self.ensure_not_cancelled()
        if self.pause_event is None or self.pause_event.is_set():
            return

        self.log("\u6d41\u7a0b\u5df2\u6682\u505c\uff0c\u7b49\u5f85\u7ee7\u7eed\u8fd0\u884c")
        while not self.pause_event.wait(timeout=0.2):
            self.ensure_not_cancelled()
        self.ensure_not_cancelled()
        self.log("\u6d41\u7a0b\u5df2\u7ee7\u7eed\u8fd0\u884c")

    def run_step(self, action: Callable[..., Any], *args) -> Any:
        self.ensure_not_cancelled()
        self.wait_if_paused()
        return action(*args)

    def reveal(self, locator, timeout: int = 30000) -> None:
        self.wait_if_paused()
        try:
            locator.wait_for(state="attached", timeout=timeout)
            locator.evaluate(
                """element => element.scrollIntoView({
                    block: 'center',
                    inline: 'center',
                    behavior: 'instant'
                })"""
            )
            self.require_page().wait_for_timeout(300)
        except Exception:
            try:
                locator.scroll_into_view_if_needed(timeout=timeout)
                self.require_page().wait_for_timeout(300)
            except Exception:
                pass

    def visible_click(self, locator, timeout: int = 30000, **kwargs) -> None:
        self.wait_if_paused()
        self.reveal(locator, timeout=timeout)
        locator.wait_for(state="visible", timeout=timeout)
        locator.click(**kwargs)

    def visible_fill(self, locator, value: str, timeout: int = 30000) -> None:
        self.wait_if_paused()
        self.reveal(locator, timeout=timeout)
        locator.wait_for(state="visible", timeout=timeout)
        locator.fill(value)

    @staticmethod
    def normalize_cookies(cookies: list[dict[str, Any]]) -> list[dict[str, Any]]:
        same_site_map = {
            "strict": "Strict",
            "lax": "Lax",
            "none": "None",
            "no_restriction": "None",
            "unspecified": "Lax",
        }

        normalized = []
        for cookie in cookies:
            clean_cookie = cookie.copy()

            same_site = clean_cookie.get("sameSite")
            if same_site is not None:
                clean_cookie["sameSite"] = same_site_map.get(
                    str(same_site).strip().lower(),
                    "Lax",
                )

            if "expirationDate" in clean_cookie and "expires" not in clean_cookie:
                clean_cookie["expires"] = clean_cookie.pop("expirationDate")

            normalized.append(clean_cookie)

        return normalized

    def start_browser(self) -> Page:
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            channel="chrome",
            headless=False,
            slow_mo=300,
            viewport={
                "width": self.viewport_width,
                "height": self.viewport_height,
            },
            args=[
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-session-crashed-bubble",
                f"--window-size={self.viewport_width},{self.viewport_height}",
            ],
        )
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.log("\u6d4f\u89c8\u5668\u5df2\u542f\u52a8")
        return self.page

    def load_cookies(self) -> None:
        if self.context is None:
            return

        if not os.path.exists(self.cookies_file):
            self.log("\u672a\u627e\u5230 cookies.json\uff0c\u5c06\u4f7f\u7528\u5df2\u4fdd\u5b58\u7684\u6d4f\u89c8\u5668\u4f1a\u8bdd")
            return

        with open(self.cookies_file, "r", encoding="utf-8") as file:
            cookies = self.normalize_cookies(json.load(file))
        self.context.add_cookies(cookies)
        self.log(f"\u5df2\u52a0\u8f7d Cookie: {self.cookies_file}")

    def open_target_page(self) -> None:
        page = self.require_page()
        page.goto(TARGET_URL, wait_until="domcontentloaded")
        page.bring_to_front()
        self.log(f"\u5df2\u6253\u5f00\u9875\u9762: {page.url}")

    def click_visible_text(self, page: Page, text: str, times: int = 1) -> None:
        target = page.get_by_text(text, exact=True)
        target.wait_for(state="visible", timeout=30000)
        for _ in range(times):
            self.visible_click(target)

    def click_text_if_visible(self, page: Page, text: str, timeout: int = 10000) -> bool:
        target = page.get_by_text(text, exact=True)
        try:
            target.wait_for(state="visible", timeout=timeout)
        except Exception:
            return False

        self.visible_click(target, timeout=timeout)
        return True

    def click_last_visible_text(self, page: Page, text: str) -> None:
        target = page.get_by_text(text, exact=True)
        target.last.wait_for(state="visible", timeout=30000)
        self.visible_click(target.last)

    def click_dropdown_option(self, page: Page, text: str) -> None:
        page.wait_for_timeout(500)
        exact_target = page.get_by_text(text, exact=True)
        for index in range(exact_target.count() - 1, -1, -1):
            option = exact_target.nth(index)
            try:
                if option.is_visible(timeout=500):
                    self.visible_click(option, timeout=5000)
                    return
            except Exception:
                continue

        partial_target = page.get_by_text(text, exact=False)
        deadline = datetime.now().timestamp() + 30
        while datetime.now().timestamp() < deadline:
            for index in range(partial_target.count() - 1, -1, -1):
                option = partial_target.nth(index)
                try:
                    if option.is_visible(timeout=500):
                        self.visible_click(option, timeout=5000)
                        return
                except Exception:
                    continue
            page.wait_for_timeout(500)

        partial_target.last.wait_for(state="visible", timeout=1000)
        self.visible_click(partial_target.last, timeout=5000)

    def click_publish_category_option(self, page: Page, text: str) -> None:
        exact_text = re.compile(rf"^\s*{re.escape(text)}\s*$")
        option = page.locator(".spmc_itemContent_WXhBo").filter(has_text=exact_text)
        option.wait_for(state="visible", timeout=30000)
        self.visible_click(option)

    def convert_image_to_square(self, image_path: str) -> str:
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")

        if self.temp_dir is None:
            self.temp_dir = tempfile.mkdtemp(prefix="xiyin_upload_")

        base_name = os.path.splitext(os.path.basename(image_path))[0]
        output_path = os.path.join(self.temp_dir, f"{base_name}_1x1.jpeg")

        with Image.open(image_path) as image:
            image = image.convert("RGB")
            target_size = max(1200, image.width, image.height)
            scale = min(target_size / image.width, target_size / image.height)
            resized_size = (
                max(1, round(image.width * scale)),
                max(1, round(image.height * scale)),
            )
            resized_image = image.resize(resized_size, Image.Resampling.LANCZOS)
            square = Image.new("RGB", (target_size, target_size), (255, 255, 255))
            offset = (
                (target_size - resized_image.width) // 2,
                (target_size - resized_image.height) // 2,
            )
            square.paste(resized_image, offset)
            square.save(output_path, "JPEG", quality=95)

        self.log(f"\u5df2\u8f6c\u6362\u56fe\u7247\u4e3a {target_size} x {target_size}: {output_path}")
        return output_path

    @staticmethod
    def is_mark_image_file(image_file: str) -> bool:
        name = os.path.splitext(os.path.basename(image_file))[0].lower()
        return any(keyword in name for keyword in ("标", "logo", "商标", "品牌"))

    def get_image_files(self, directory: str, exclude_mark_images: bool = False) -> list[str]:
        image_extensions = {".jpg", ".jpeg", ".png"}
        if not os.path.isdir(directory):
            raise FileNotFoundError(f"Image directory not found: {directory}")

        image_files = [
            os.path.join(directory, file_name)
            for file_name in os.listdir(directory)
            if os.path.splitext(file_name)[1].lower() in image_extensions
        ]
        if exclude_mark_images:
            image_files = [
                image_file
                for image_file in image_files
                if not self.is_mark_image_file(image_file)
            ]
        image_files.sort()

        if not image_files:
            raise FileNotFoundError(f"No image files found in: {directory}")

        return image_files

    def select_opportunity_entry(self) -> None:
        page = self.require_page()
        tab_bar = page.locator("#follow-sales-tab-bar")
        tab = tab_bar.locator(".soui-tabs-tab").filter(has_text=self.opportunity_tab).first
        self.visible_click(tab)
        self.log(f"\u5df2\u9009\u62e9\u673a\u4f1a\u5546\u54c1\u9875\u7b7e: {self.opportunity_tab}")

        if self.opportunity_tab == SCARCE_HOT_TAB_TEXT:
            opportunity_search = page.locator("#guider-step-search")
            market_hot_button = opportunity_search.get_by_role(
                "button",
                name=MARKET_HOT_TEXT,
                exact=True,
            )
            self.visible_click(market_hot_button)
            self.log(f"\u5df2\u9009\u62e9\u673a\u4f1a\u7c7b\u578b: {MARKET_HOT_TEXT}")

    def select_product_category(self) -> None:
        page = self.require_page()
        category_input = page.locator(".list-search-category input")
        self.visible_click(category_input)

        if not self.category_path:
            raise RuntimeError("\u672a\u9009\u62e9\u5546\u54c1\u7c7b\u76ee")

        for index, category_name in enumerate(self.category_path):
            is_leaf = index == len(self.category_path) - 1
            self.click_visible_text(page, category_name, times=1 if is_leaf else 2)

        self.log(f"\u5df2\u9009\u62e9\u7c7b\u76ee: {' > '.join(self.category_path)}")

    def search(self) -> None:
        page = self.require_page()
        self.click_visible_text(page, SEARCH_TEXT)
        self.log(f"\u5df2\u70b9\u51fb: {SEARCH_TEXT}")

    def click_random_publish_same(self) -> Page:
        page = self.require_page()
        publish_entries = self.find_visible_publish_entries(page)
        if not publish_entries:
            supported_text = " / ".join(PUBLISH_ENTRY_TEXTS)
            raise RuntimeError(f"未找到可点击的发布入口: {supported_text}")

        entry_attempts = random.sample(publish_entries, k=len(publish_entries))
        publish_button = None
        entry_text = ""
        selected_index = 0
        existing_pages: set[Page] = set()
        initial_url = ""
        for selected_index, (candidate_button, candidate_text) in enumerate(
            entry_attempts,
            start=1,
        ):
            try:
                candidate_pages = set(page.context.pages)
                candidate_url = page.url
                self.visible_click(candidate_button, timeout=3000)
                publish_button = candidate_button
                entry_text = candidate_text
                existing_pages = candidate_pages
                initial_url = candidate_url
                break
            except Exception as error:
                self.log(f"\u5df2\u8df3\u8fc7\u4e0d\u53ef\u7528\u7684{candidate_text}\u5165\u53e3: {error}")

        if publish_button is None:
            raise RuntimeError("当前结果中的发布入口均不可点击，请重新搜索后再试")

        publish_page = self.wait_for_publish_page(
            page,
            existing_pages,
            initial_url,
        )
        publish_page.wait_for_load_state("domcontentloaded", timeout=30000)
        publish_page.bring_to_front()
        self.log(f"\u5df2\u968f\u673a\u70b9\u51fb{entry_text}: \u7b2c {selected_index} \u4e2a")
        self.log(f"\u5df2\u6253\u5f00\u53d1\u5e03\u9875: {publish_page.url}")
        return publish_page

    def find_visible_publish_entries(self, page: Page) -> list[tuple[Any, str]]:
        card_buttons = page.locator(
            "[data-display-name='mfrp-follow-sales-card-item']:visible button:visible"
        )
        entries = self.filter_visible_publish_entries(card_buttons)
        if entries:
            return entries

        return self.filter_visible_publish_entries(page.locator("button:visible"))

    def filter_visible_publish_entries(self, buttons) -> list[tuple[Any, str]]:
        entries: list[tuple[Any, str]] = []
        for index in range(buttons.count()):
            button = buttons.nth(index)
            try:
                button.wait_for(state="visible", timeout=500)
                if not button.is_enabled():
                    continue
                button_text = button.inner_text(timeout=1000).strip()
            except Exception:
                continue

            if button_text in PUBLISH_ENTRY_TEXTS:
                entries.append((button, button_text))
        return entries

    def wait_for_publish_page(
        self,
        page: Page,
        existing_pages: set[Page],
        initial_url: str,
    ) -> Page:
        deadline = datetime.now().timestamp() + 30
        while datetime.now().timestamp() < deadline:
            new_pages = [
                candidate
                for candidate in page.context.pages
                if candidate not in existing_pages
            ]
            if new_pages:
                return new_pages[-1]
            if page.url != initial_url:
                return page
            page.wait_for_timeout(300)

        raise RuntimeError("已点击发布入口，但未检测到发布页打开或跳转")

    def select_publish_category(self, page: Page) -> None:
        if not self.publish_category_path:
            raise RuntimeError("\u672a\u914d\u7f6e\u53d1\u5e03\u7c7b\u76ee\u8def\u5f84")

        for category_name in self.publish_category_path:
            self.click_publish_category_option(page, category_name)
            self.log(f"\u5df2\u70b9\u51fb\u53d1\u5e03\u7c7b\u76ee: {category_name}")

        self.click_visible_text(page, CONFIRM_NEXT_TEXT)
        self.log(f"\u5df2\u70b9\u51fb: {CONFIRM_NEXT_TEXT}")

    def handle_publish_tips(self, page: Page) -> None:
        if self.click_text_if_visible(page, I_KNOW_TEXT):
            self.log(f"\u5df2\u70b9\u51fb: {I_KNOW_TEXT}")

        self.click_visible_text(page, NEW_IMAGE_UPLOAD_TEXT)
        self.log(f"\u5df2\u70b9\u51fb: {NEW_IMAGE_UPLOAD_TEXT}")

        if self.click_text_if_visible(page, OK_TEXT):
            self.log(f"\u5df2\u70b9\u51fb: {OK_TEXT}")

    def upload_main_image(self, page: Page) -> None:
        if not os.path.exists(self.main_image_file):
            raise FileNotFoundError(f"Main image not found: {self.main_image_file}")

        square_image_file = self.convert_image_to_square(self.main_image_file)
        upload_input = page.locator('input[type="file"][accept*="image"]').last
        upload_input.wait_for(state="attached", timeout=30000)
        self.reveal(page.locator(".main_image, .main_img, .so-form-item").filter(has=upload_input).last, timeout=5000)
        upload_input.set_input_files(square_image_file)
        self.log(f"\u5df2\u4e0a\u4f20\u5546\u54c1\u4e3b\u56fe: {square_image_file}")

    def upload_detail_images(self, page: Page) -> None:
        detail_images = [
            self.convert_image_to_square(image_file)
            for image_file in self.get_image_files(self.image_dir)
        ]

        container = page.locator(".detail_img_container").first
        container.wait_for(state="attached", timeout=30000)

        # 新版页面实际结构：表格列为 颜色/细节图/方形图/色块图。
        # 按表头「细节图」确定列号，只使用新版入口，不再保留旧版回退。
        header_cells = container.locator("thead th")
        detail_index = None
        for index in range(header_cells.count()):
            cell = header_cells.nth(index)
            try:
                has_marker = cell.locator(".detail_img").count() > 0
                has_text = "\u7ec6\u8282\u56fe" in (cell.inner_text(timeout=3000) or "")
            except Exception:
                continue
            if has_marker or has_text:
                detail_index = index
                break
        if detail_index is None:
            raise RuntimeError(
                "\u672a\u627e\u5230\u7ec6\u8282\u56fe\u5217\u8868\u5934\uff0c\u65e0\u6cd5\u5b9a\u4f4d\u65b0\u7248\u7ec6\u8282\u56fe\u4e0a\u4f20\u5165\u53e3"
            )

        detail_cell = container.locator("tbody tr").first.locator("td").nth(detail_index)
        self.reveal(container, timeout=10000)

        # 实际入口：细节图列单元格里的「点击上传」控件。每次点击打开系统文件选择器，
        # 一次选择一张，页面会把图片累积到下一个槽位（该入口按单张处理，多张会提示“不能超过一张”）。
        for image_index, image_file in enumerate(detail_images, start=1):
            upload_entry = detail_cell.locator('[class*="uploadHandle"]').first
            upload_entry.wait_for(state="attached", timeout=30000)
            with page.expect_file_chooser(timeout=30000) as chooser_info:
                self.visible_click(upload_entry)
            chooser = chooser_info.value
            chooser.set_files([image_file])
            self.log(
                f"\u5df2\u4e0a\u4f20\u7ec6\u8282\u56fe {image_index}/{len(detail_images)}: "
                f"{os.path.basename(image_file)}"
            )
            page.wait_for_timeout(2000)

        self.log(f"\u5df2\u901a\u8fc7\u7ec6\u8282\u56fe\u5217\u5165\u53e3\u5b8c\u6210\u4e0a\u4f20: {len(detail_images)} \u5f20")

    def get_supplier_config(self) -> dict[str, Any]:
        return self.product_config.get("\u4f9b\u65b9\u4fe1\u606f", {})

    def get_supplier_code_from_config(self) -> str:
        supplier_code = str(self.get_supplier_config().get("\u4f9b\u65b9\u8d27\u53f7", "")).strip()
        if not supplier_code:
            raise RuntimeError("\u5546\u54c1\u914d\u7f6e.json \u4e2d\u672a\u914d\u7f6e\u4f9b\u65b9\u8d27\u53f7")
        return supplier_code

    def get_certificate_upload_items(self) -> list[tuple[str, str | None]]:
        certificate_config = self.product_config.get(CERTIFICATE_CONFIG_KEY, {})
        if not isinstance(certificate_config, dict):
            self.log(f"\u5546\u54c1\u914d\u7f6e.json \u4e2d {CERTIFICATE_CONFIG_KEY} \u4e0d\u662f\u5bf9\u8c61\uff0c\u5df2\u8df3\u8fc7\u8bc1\u4e66\u4e0a\u4f20")
            return []
        if not self.is_certificate_upload_enabled(certificate_config):
            self.log("\u8bc1\u4e66\u5217\u8868\u5df2\u5173\u95ed\u5168\u5c40\u4e0a\u4f20\uff0c\u8df3\u8fc7\u8bc1\u4e66\u4e0a\u4f20")
            return []

        upload_items = []
        for qualification_name in CONFIGURABLE_QUALIFICATIONS:
            certificate_name = self.resolve_certificate_name(certificate_config.get(qualification_name))
            if not certificate_name:
                if qualification_name == TOY_MANUAL_QUALIFICATION:
                    self.log(f"\u73a9\u5177\u8bf4\u660e\u4e66\u672a\u914d\u7f6e\u8bc1\u4e66\u540d\uff0c\u5c06\u9ed8\u8ba4\u4e0a\u4f20\u5f39\u7a97\u7b2c\u4e00\u884c")
                    upload_items.append((qualification_name, None))
                    continue

                self.log(f"\u672a\u914d\u7f6e\u8bc1\u4e66\u540d\uff0c\u8df3\u8fc7: {qualification_name}")
                continue

            upload_items.append((qualification_name, certificate_name))

        return upload_items

    @staticmethod
    def is_certificate_upload_enabled(certificate_config: dict[str, Any]) -> bool:
        raw_value = certificate_config.get(CERTIFICATE_ENABLED_KEY, True)
        if isinstance(raw_value, str):
            return raw_value.strip().lower() not in {"false", "0", "no", "\u5426"}
        return bool(raw_value)

    def resolve_certificate_name(self, raw_value: Any) -> str:
        if isinstance(raw_value, dict):
            for key in CERTIFICATE_NAME_KEYS:
                value = str(raw_value.get(key, "")).strip()
                if value:
                    return value
            return ""

        if raw_value is None:
            return ""
        return str(raw_value).strip()

    def get_package_info(self) -> dict[str, str]:
        package_config = self.product_config.get("\u5305\u88c5\u4fe1\u606f", {})
        dimensions = package_config.get("\u542b\u5305\u88c5\u5c3a\u5bf8", {})

        return {
            "weight": str(package_config.get("\u542b\u5305\u88c5\u91cd\u91cf(g)", "")),
            "length": str(dimensions.get("\u957f", "")),
            "width": str(dimensions.get("\u5bbd", "")),
            "height": str(dimensions.get("\u9ad8", "")),
            "unit": str(package_config.get("\u5355\u4f4d", "")),
            "package_type": str(package_config.get("\u5305\u88c5\u7c7b\u578b", "")),
        }

    def get_product_attributes(self) -> list[tuple[str, str, str | None]]:
        attributes = self.product_config.get("\u5fc5\u586b\u5c5e\u6027")
        if not isinstance(attributes, dict):
            return PRODUCT_ATTRIBUTES

        resolved = []
        for chinese_label, raw_value in attributes.items():
            attr_title_keyword = ATTRIBUTE_LABEL_MAP.get(chinese_label, chinese_label)

            if isinstance(raw_value, dict):
                value = raw_value.get("\u503c")
                ratio = raw_value.get("\u6bd4\u4f8b")
            else:
                value = raw_value
                ratio = None

            if value is None:
                continue

            if isinstance(value, (list, tuple)):
                values = [
                    str(item).strip()
                    for item in value
                    if item is not None and str(item).strip()
                ]
            else:
                normalized_value = str(value).strip()
                values = [normalized_value] if normalized_value else []

            for attribute_value in values:
                resolved.append(
                    (
                        attr_title_keyword,
                        attribute_value,
                        str(ratio).strip() if ratio is not None else None,
                    )
                )

        return resolved

    def get_color_config(self) -> list[str]:
        colors = self.product_config.get("\u989c\u8272\u914d\u7f6e", [])
        if not isinstance(colors, list):
            return []

        return [str(color).strip() for color in colors if str(color).strip()]

    def get_style_config(self) -> str:
        return str(self.product_config.get("\u6b3e\u5f0f", "")).strip()

    def fill_supplier_info(self, page: Page) -> None:
        page.wait_for_timeout(1000)
        supplier_section = page.locator(".supplier_info").last
        supplier_section.wait_for(state="attached", timeout=30000)
        supplier_section.scroll_into_view_if_needed(timeout=30000)

        table = supplier_section.locator("#userguide_commodities_info_supply_weight_table")
        table.wait_for(state="visible", timeout=30000)
        rows = table.locator("tbody tr")
        row_count = rows.count()
        if row_count == 0:
            raise RuntimeError("供方信息表格没有找到可填写的颜色行")

        first_row = rows.first
        self.product_skc = self.read_product_skc_from_supplier_row(first_row)
        if not self.product_skc:
            self.product_skc = self.read_product_skc_from_skc_table(page)
        if self.product_skc:
            self.log(f"\u5df2\u8bfb\u53d6\u5546\u54c1 SKC: {self.product_skc}")

        supplier_config = self.get_supplier_config()
        price_range = supplier_config.get("\u4ef7\u683c\u8303\u56f4", {})
        price_min = int(price_range.get("\u6700\u4f4e", PRICE_MIN))
        price_max = int(price_range.get("\u6700\u9ad8", PRICE_MAX))
        stock_value = str(supplier_config.get("\u5e93\u5b58", STOCK_VALUE))
        piece_type_text = str(supplier_config.get("\u4ef6\u6570", PIECE_TYPE_TEXT))

        price = str(random.randint(price_min, price_max))
        self.log(f"\u5df2\u751f\u6210\u7edf\u4e00\u4ef7\u683c: {price}\uff0c\u5171 {row_count} \u4e2a\u989c\u8272\u884c")

        for row_index in range(row_count):
            row = rows.nth(row_index)
            row.scroll_into_view_if_needed(timeout=30000)

            price_input = row.locator(f".supplier_priceClass_{row_index} input")
            if price_input.count() == 0:
                price_input = row.locator('[class*="supplier_priceClass_"] input').first
            self.visible_fill(price_input, price)
            self.log(f"\u5df2\u586b\u5199\u7b2c {row_index + 1} \u884c\u4ef7\u683c: {price}")

            edit_stock_button = row.locator("button", has_text=EDIT_STOCK_TEXT)
            self.visible_click(edit_stock_button)
            self.log(f"\u5df2\u70b9\u51fb\u7b2c {row_index + 1} \u884c: {EDIT_STOCK_TEXT}")

            stock_input = page.locator(f".stockInfo_nullClass_{row_index} input")
            if stock_input.count() == 0:
                stock_input = page.locator('[class*="stockInfo_nullClass_"] input').last
            self.visible_fill(stock_input, stock_value)
            self.log(f"\u5df2\u586b\u5199\u7b2c {row_index + 1} \u884c\u5e93\u5b58: {stock_value}")

            if self.click_text_if_visible(page, OK_TEXT, timeout=5000):
                self.log(f"\u5df2\u70b9\u51fb: {OK_TEXT}")

            self.select_supplier_piece_type(page, row, row_index, piece_type_text)
            self.log(f"\u5df2\u9009\u62e9\u7b2c {row_index + 1} \u884c\u4ef6\u6570: {piece_type_text}")

        supplier_code_inputs = page.locator('[class*="supplier_codeClass_"] input')
        supplier_code_count = supplier_code_inputs.count()
        if supplier_code_count == 0:
            supplier_code_inputs = table.locator('[class*="supplier_codeClass_"] input')
            supplier_code_count = supplier_code_inputs.count()
        if supplier_code_count == 0:
            raise RuntimeError("\u672a\u627e\u5230\u4f9b\u65b9\u8d27\u53f7\u8f93\u5165\u6846")

        in_supply_table = table.locator('[class*="supplier_codeClass_"] input').count() > 0
        self.log(
            f"\u5df2\u627e\u5230 {supplier_code_count} \u4e2a\u4f9b\u65b9\u8d27\u53f7\u8f93\u5165\u6846"
            f"\uff08{'供方信息表' if in_supply_table else '\u89c4\u683c\u4fe1\u606f SKC \u5217\u8868'}\uff09"
        )
        for input_index in range(supplier_code_count):
            supplier_code_input = supplier_code_inputs.nth(input_index)
            self.visible_fill(supplier_code_input, self.supplier_code)
        self.log(f"\u5df2\u586b\u5199\u4f9b\u65b9\u8d27\u53f7: {self.supplier_code}")

        if not self.product_skc:
            raise RuntimeError("\u672a\u8bfb\u53d6\u5230\u591a\u8272\u884c\u7684 SKC\uff0c\u4e0d\u4f1a\u4f7f\u7528\u6587\u4ef6\u5939\u540d\u586b\u5199\u4ea7\u54c1\u6807\u8bc6\u7b26")

    def select_supplier_piece_type(self, page: Page, row, row_index: int, piece_type_text: str) -> None:
        quantity_box = row.locator(f'[class*="skuQuantityClass_{row_index}"]').first
        if quantity_box.count() > 0:
            piece_cell = quantity_box.locator("xpath=ancestor::td[1]")
            piece_type_select = piece_cell.locator(".soui-select").first
        else:
            piece_type_select = row.locator(".soui-select").first

        self.visible_click(piece_type_select)
        page.wait_for_timeout(500)
        self.click_dropdown_option(page, piece_type_text)

    def read_product_skc_from_supplier_row(self, row) -> str:
        first_cell_text = row.locator("td").first.inner_text(timeout=10000)
        reliable_skc_match = re.search(r"SKC\W*([A-Za-z0-9]+)", first_cell_text, re.IGNORECASE)
        if reliable_skc_match:
            return reliable_skc_match.group(1)
        skc_match = re.search(r"SKC\s*[:：]?\s*([A-Za-z0-9]+)", first_cell_text, re.IGNORECASE)
        if skc_match:
            return skc_match.group(1)

        row_text = row.inner_text(timeout=10000)
        reliable_skc_match = re.search(r"SKC\W*([A-Za-z0-9]+)", row_text, re.IGNORECASE)
        if reliable_skc_match:
            return reliable_skc_match.group(1)
        skc_match = re.search(r"SKC\s*[:：]?\s*([A-Za-z0-9]+)", row_text, re.IGNORECASE)
        if skc_match:
            return skc_match.group(1)

        return ""

    def read_product_skc_from_skc_table(self, page: Page) -> str:
        """新版页面把 SKC 与供方货号一起放进了规格信息的 SKC 列表。"""
        code_input = page.locator('[class*="supplier_codeClass_"] input').first
        if code_input.count() == 0:
            return ""
        row = code_input.locator("xpath=ancestor::tr[1]").first
        if row.count() == 0:
            return ""
        return self.read_product_skc_from_supplier_row(row)

    def select_so_option(self, page: Page, select_locator, value: str) -> None:
        self.visible_click(select_locator)
        page.wait_for_timeout(500)
        self.click_dropdown_option(page, value)

    def fill_package_info(self, page: Page) -> None:
        package_info = self.get_package_info()

        package_section = page.locator(".package_info").last
        package_section.wait_for(state="attached", timeout=30000)
        package_section.scroll_into_view_if_needed(timeout=30000)

        table = package_section.locator("#userguide_commodities_info_supply_weight_table")
        table.wait_for(state="visible", timeout=30000)
        rows = table.locator("tbody tr")
        row_count = rows.count()
        if row_count == 0:
            raise RuntimeError("\u5305\u88c5\u4fe1\u606f\u8868\u683c\u6ca1\u6709\u627e\u5230\u53ef\u586b\u5199\u7684\u989c\u8272\u884c")

        for row_index in range(row_count):
            row = rows.nth(row_index)
            self.reveal(row)

            self.visible_fill(
                self.find_row_input_by_class(row, f"weightClass_{row_index}"),
                package_info["weight"],
            )
            self.visible_fill(
                self.find_row_input_by_class(row, f"lengthClass_{row_index}"),
                package_info["length"],
            )
            self.visible_fill(
                self.find_row_input_by_class(row, f"widthClass_{row_index}"),
                package_info["width"],
            )
            self.visible_fill(
                self.find_row_input_by_class(row, f"heightClass_{row_index}"),
                package_info["height"],
            )

            unit_select = self.find_package_unit_select(row, row_index)
            self.select_so_option(page, unit_select, package_info["unit"])

            package_type_select = self.find_package_type_select(row)
            self.select_so_option(page, package_type_select, package_info["package_type"])
            self.log(f"\u5df2\u586b\u5199\u7b2c {row_index + 1} \u884c\u5305\u88c5\u4fe1\u606f")

        self.log(
            "\u5df2\u586b\u5199\u5305\u88c5\u4fe1\u606f: "
            f"{package_info['weight']}g, "
            f"{package_info['length']}x{package_info['width']}x{package_info['height']} "
            f"{package_info['unit']}, {package_info['package_type']}"
        )

    def confirm_package_size_warning_if_present(self, page: Page) -> None:
        warning_alerts = page.locator(".so-alert-warning").filter(
            has=page.locator("button", has_text="\u6211\u5df2\u786e\u8ba4")
        )
        for index in range(warning_alerts.count()):
            confirm_button = warning_alerts.nth(index).locator(
                "button",
                has_text="\u6211\u5df2\u786e\u8ba4",
            ).first
            try:
                if not confirm_button.is_visible(timeout=500):
                    continue
                self.visible_click(confirm_button, timeout=5000)
                self.log("\u5df2\u786e\u8ba4\u5305\u88c5\u4f53\u79ef\u9884\u8b66")
                return
            except Exception:
                continue

    def find_row_input_by_class(self, row, class_name: str):
        exact_input = row.locator(f".{class_name} input")
        if exact_input.count() > 0:
            return exact_input.first
        return row.locator(f'[class*="{class_name}"] input').first

    def find_package_unit_select(self, row, row_index: int):
        length_box = row.locator(f'[class*="lengthClass_{row_index}"]').first
        if length_box.count() > 0:
            dimension_cell = length_box.locator("xpath=ancestor::td[1]")
            return dimension_cell.locator(".so-select").first
        return row.locator(".so-select").first

    def find_package_type_select(self, row):
        package_type_select = row.locator("td").last.locator(".so-select").first
        if package_type_select.count() > 0:
            return package_type_select
        return row.locator(".so-select").last

    def click_qualification_upload(self, page: Page, qualification_name: str) -> None:
        self.ensure_qualification_section_loaded(page)
        qualification_section = page.locator("#qualification_info")

        row = qualification_section.locator("tbody tr").filter(has_text=qualification_name).first
        row.wait_for(state="visible", timeout=30000)
        upload_button = row.locator("button", has_text=UPLOAD_TEXT).first
        self.visible_click(upload_button)
        self.log(f"\u5df2\u70b9\u51fb\u8d44\u8d28\u4e0a\u4f20: {qualification_name}")

    def click_real_shot_upload(self, page: Page) -> None:
        qualification_section = page.locator("#qualification_info")
        try:
            qualification_section.wait_for(state="attached", timeout=5000)
            qualification_section.scroll_into_view_if_needed(timeout=10000)
        except PlaywrightTimeoutError:
            pass

        legacy_row = qualification_section.locator("tbody tr").filter(
            has_text=REAL_PHOTO_QUALIFICATION_KEYWORD
        ).first
        if legacy_row.count() == 0:
            self.log(
                f"\u672a\u627e\u5230\u5b9e\u62cd\u56fe\u65e7\u5165\u53e3: {REAL_PHOTO_QUALIFICATION_KEYWORD}\uff0c"
                f"\u6539\u4e3a\u5339\u914d\u201c{REAL_PHOTO_SECTION_TEXT}\u201d\u533a\u57df"
            )
        else:
            legacy_row.wait_for(state="visible", timeout=10000)
            upload_button = legacy_row.locator("button", has_text=UPLOAD_TEXT).first
            self.visible_click(upload_button)
            self.log(f"\u5df2\u70b9\u51fb\u5b9e\u62cd\u56fe\u4e0a\u4f20: {REAL_PHOTO_QUALIFICATION_KEYWORD}")
            return

        real_shot_label = page.get_by_text(REAL_PHOTO_SECTION_TEXT, exact=True).first
        real_shot_label.wait_for(state="visible", timeout=30000)
        real_shot_section = real_shot_label.locator("xpath=..")
        real_shot_section.scroll_into_view_if_needed(timeout=10000)
        upload_button = real_shot_section.locator("button", has_text=UPLOAD_TEXT).first
        self.visible_click(upload_button)
        self.log(f"\u5df2\u70b9\u51fb\u5b9e\u62cd\u56fe\u4e0a\u4f20: {REAL_PHOTO_SECTION_TEXT}")

    @staticmethod
    def get_compliance_info_row_candidates(qualification_name: str) -> tuple[str, ...]:
        return COMPLIANCE_INFO_ROW_ALIASES.get(qualification_name, (qualification_name,))

    def click_qualification_edit(self, page: Page, qualification_name: str) -> None:
        qualification_section = page.locator("#qualification_info")
        try:
            qualification_section.wait_for(state="attached", timeout=5000)
            qualification_section.scroll_into_view_if_needed(timeout=10000)
        except PlaywrightTimeoutError:
            pass

        legacy_row = qualification_section.locator("tbody tr").filter(
            has_text=qualification_name
        ).first
        if legacy_row.count() > 0:
            legacy_row.wait_for(state="visible", timeout=10000)
            edit_button = legacy_row.locator("button", has_text=EDIT_TEXT).first
            self.visible_click(edit_button)
            self.log(f"\u5df2\u70b9\u51fb\u8d44\u8d28\u7f16\u8f91: {qualification_name}")
            return

        self.log(
            f"\u672a\u627e\u5230\u65e7\u8d44\u8d28\u5165\u53e3: {qualification_name}\uff0c"
            f"\u6539\u4e3a\u5339\u914d\u201c{COMPLIANCE_INFO_SECTION_TEXT}\u201d\u533a\u57df"
        )
        compliance_label = page.get_by_text(COMPLIANCE_INFO_SECTION_TEXT, exact=True).first
        compliance_label.wait_for(state="visible", timeout=30000)
        compliance_section = compliance_label.locator("xpath=..")
        compliance_section.scroll_into_view_if_needed(timeout=10000)
        rows = compliance_section.locator("tbody tr")

        for row_label in self.get_compliance_info_row_candidates(qualification_name):
            row = rows.filter(has_text=row_label).first
            if row.count() == 0:
                continue

            row.wait_for(state="visible", timeout=10000)
            edit_button = row.locator("button", has_text=EDIT_TEXT).first
            self.visible_click(edit_button)
            self.log(
                f"\u5df2\u70b9\u51fb\u5408\u89c4\u4fe1\u606f\u7f16\u8f91: "
                f"{qualification_name} -> {row_label}"
            )
            return

        candidate_text = " / ".join(self.get_compliance_info_row_candidates(qualification_name))
        raise RuntimeError(
            f"\u672a\u5728{COMPLIANCE_INFO_SECTION_TEXT}\u533a\u57df\u627e\u5230\u53ef\u7f16\u8f91\u9879: {candidate_text}"
        )

    def get_active_compliance_dialog(self, page: Page):
        dialog = page.locator(".soui-modal-panel").last
        dialog.wait_for(state="visible", timeout=30000)
        return dialog

    @staticmethod
    def xpath_literal(value: str) -> str:
        if '"' not in value:
            return f'"{value}"'
        if "'" not in value:
            return f"'{value}'"

        parts = value.split('"')
        return "concat(" + ', \'"\', '.join(f'"{part}"' for part in parts) + ")"

    def select_dialog_option_by_label(self, page: Page, dialog, label_text: str, value_text: str) -> None:
        self.select_dialog_option_by_label_return_select(page, dialog, label_text, value_text)

    def select_dialog_option_by_label_return_select(self, page: Page, dialog, label_text: str, value_text: str):
        label_literal = self.xpath_literal(label_text)
        form_item = dialog.locator(
            "xpath=.//*[contains(@class, 'soui-form-item-wrapper')]["
            "./*[contains(@class, 'soui-form-item-label') and contains(., "
            f"{label_literal}"
            ")]"
            "]"
        ).first
        form_item.wait_for(state="visible", timeout=30000)
        select = form_item.locator(".soui-select").first
        select.wait_for(state="visible", timeout=30000)

        self.open_soui_select(page, dialog, select, value_text)
        self.click_option_inside_select(page, dialog, value_text)
        self.wait_select_value(page, select, value_text)
        page.wait_for_timeout(300)
        self.log(f"\u5df2\u9009\u62e9: {label_text} = {value_text}")
        return select

    def wait_for_stable_locator(self, page: Page, locator, description: str, timeout: int = 10000) -> None:
        deadline = datetime.now().timestamp() + timeout / 1000
        previous_box = None
        stable_checks = 0

        while datetime.now().timestamp() < deadline:
            try:
                if not locator.is_visible(timeout=500) or not locator.is_enabled():
                    page.wait_for_timeout(200)
                    continue
                box = locator.bounding_box()
                if box is None:
                    page.wait_for_timeout(200)
                    continue
                if box == previous_box:
                    stable_checks += 1
                    if stable_checks >= 2:
                        return
                else:
                    previous_box = box
                    stable_checks = 0
            except Exception:
                stable_checks = 0
            page.wait_for_timeout(200)

        raise RuntimeError(f"{description} 在 {timeout}ms 内未准备完成")

    def open_soui_select(self, page: Page, dialog, select, value_text: str) -> None:
        result_wrapper = select.locator(".soui-select-result-wrapper").first
        self.reveal(result_wrapper, timeout=10000)
        self.wait_for_stable_locator(page, result_wrapper, "下拉框")

        option = dialog.locator(".soui-select-option:visible").filter(
            has_text=re.compile(rf"^\s*{re.escape(value_text)}\s*$")
        ).first

        for attempt in range(1, 4):
            self.visible_click(result_wrapper, timeout=10000)
            try:
                option.wait_for(state="visible", timeout=1500)
                self.log(f"下拉框已打开: {value_text}（第 {attempt} 次点击）")
                return
            except PlaywrightTimeoutError:
                if attempt < 3:
                    self.log(f"下拉框未打开，准备重试: {value_text}（第 {attempt} 次）")
                    page.wait_for_timeout(400)

        raise RuntimeError(f"下拉框未成功打开，当前弹窗内未出现选项: {value_text}")

    def click_option_inside_select(self, page: Page, dialog, value_text: str) -> None:
        option = dialog.locator(".soui-select-option:visible").filter(
            has_text=re.compile(rf"^\s*{re.escape(value_text)}\s*$")
        ).first
        option.wait_for(state="visible", timeout=10000)
        self.reveal(option, timeout=5000)
        option.locator(".soui-select-option-inner").first.click(force=True)

    def click_visible_soui_option(self, page: Page, value_text: str) -> None:
        for _ in range(10):
            options = page.locator(".soui-select-option").filter(has_text=value_text)
            for index in range(options.count() - 1, -1, -1):
                option = options.nth(index)
                try:
                    if not option.is_visible(timeout=500):
                        continue
                    option.locator(".soui-select-option-inner").first.click(force=True)
                    return
                except Exception:
                    continue
            page.wait_for_timeout(300)

        raise RuntimeError(f"\u672a\u627e\u5230\u5df2\u5c55\u5f00\u7684\u4e0b\u62c9\u9009\u9879: {value_text}")

    def wait_select_value(self, page: Page, select, value_text: str) -> None:
        for _ in range(10):
            selected_text = select.locator(".soui-select-result").first.inner_text(timeout=1000)
            if value_text in selected_text:
                return
            page.wait_for_timeout(200)

        raise RuntimeError(f"\u4e0b\u62c9\u9009\u9879\u70b9\u51fb\u540e\u672a\u786e\u8ba4\u9009\u4e2d: {value_text}")

    def submit_active_dialog(self, page: Page, dialog, log_name: str) -> None:
        submit_button = dialog.locator("button", has_text=SUBMIT_TEXT).last
        self.wait_for_button_enabled(page, submit_button, f"{log_name} 提交")
        self.visible_click(submit_button)
        self.log(f"\u5df2\u63d0\u4ea4: {log_name}")
        page.wait_for_timeout(1000)
        if self.click_text_if_visible(page, NO_MORE_UPLOAD_TEXT, timeout=10000):
            self.log(f"\u5df2\u70b9\u51fb: {NO_MORE_UPLOAD_TEXT}")
        self.wait_or_close_active_modal(page)

    def wait_or_close_active_modal(self, page: Page) -> None:
        modal = page.locator(".soui-modal-panel").last
        try:
            modal.wait_for(state="hidden", timeout=5000)
            return
        except Exception:
            pass

        close_button = modal.locator(".soui-modal-header-close").last
        try:
            self.visible_click(close_button, timeout=5000)
            modal.wait_for(state="hidden", timeout=10000)
        except Exception:
            page.keyboard.press("Escape")
            modal.wait_for(state="hidden", timeout=10000)

    def wait_for_button_enabled(self, page: Page, button, description: str, timeout: int = 30000) -> None:
        deadline = datetime.now().timestamp() + timeout / 1000
        last_state = "unknown"

        while datetime.now().timestamp() < deadline:
            try:
                if button.count() == 0:
                    last_state = "not found"
                elif button.is_visible(timeout=500) and button.is_enabled():
                    return
                else:
                    last_state = "disabled"
            except Exception as error:
                last_state = str(error)
            page.wait_for_timeout(300)

        raise RuntimeError(f"{description} 按钮在 {timeout}ms 内未启用，当前状态: {last_state}")

    def blur_dialog_select(self, page: Page, dialog) -> None:
        header = dialog.locator(".soui-modal-header").first
        self.visible_click(header, timeout=5000)

        deadline = datetime.now().timestamp() + 5
        while datetime.now().timestamp() < deadline:
            open_options = dialog.locator(".soui-select-option:visible")
            if open_options.count() == 0:
                return
            page.wait_for_timeout(200)

        raise RuntimeError("下拉框未失焦，无法继续选择下一项")

    def edit_eu_toy_safety_directive(self, page: Page) -> None:
        self.click_qualification_edit(page, EU_TOY_SAFETY_DIRECTIVE_TEXT)
        dialog = self.get_active_compliance_dialog(page)
        self.select_dialog_option_by_label(page, dialog, "\u9002\u7528\u89c4\u683c", MULTI_COLOR_TEXT)
        self.select_dialog_option_by_label_return_select(page, dialog, TOY_TYPE_TEXT, OTHER_TEXT)
        self.blur_dialog_select(page, dialog)
        self.select_dialog_option_by_label(page, dialog, "\u4e0d\u9002\u7528\u5e74\u9f84", NOT_UNDER_3_TEXT)
        self.submit_active_dialog(page, dialog, EU_TOY_SAFETY_DIRECTIVE_TEXT)

    def edit_product_identifier(self, page: Page) -> None:
        self.click_qualification_edit(page, PRODUCT_IDENTIFIER_TEXT)
        dialog = self.get_active_compliance_dialog(page)
        self.select_dialog_option_by_label(
            page,
            dialog,
            "\u9002\u7528\u89c4\u683c",
            self.get_configured_spec_value(),
        )

        if not self.product_skc:
            raise RuntimeError("\u4ea7\u54c1\u6807\u8bc6\u7b26\u9700\u8981\u586b\u5199 SKC\uff0c\u4f46\u5f53\u524d SKC \u4e3a\u7a7a")

        product_identifier_literal = self.xpath_literal(PRODUCT_IDENTIFIER_TEXT)
        identifier_input = dialog.locator(
            "xpath=.//*[contains(@class, 'soui-form-item-wrapper')]["
            "./*[contains(@class, 'soui-form-item-label') and contains(., "
            f"{product_identifier_literal}"
            ")]"
            "]"
        ).first.locator("input").first
        self.visible_fill(identifier_input, self.product_skc)
        self.log(f"\u5df2\u586b\u5199\u4ea7\u54c1\u6807\u8bc6\u7b26: {self.product_skc}")
        self.submit_active_dialog(page, dialog, PRODUCT_IDENTIFIER_TEXT)

    def edit_us_choking_hazard_warning(self, page: Page) -> None:
        self.click_qualification_edit(page, US_CHOKING_HAZARD_TEXT)
        dialog = self.get_active_compliance_dialog(page)
        self.select_dialog_option_by_label(page, dialog, "\u9002\u7528\u89c4\u683c", MULTI_COLOR_TEXT)
        self.select_dialog_option_by_label(page, dialog, TOY_HAZARD_DESC_TEXT, NO_CHOKING_WARNING_TEXT)
        self.submit_active_dialog(page, dialog, US_CHOKING_HAZARD_TEXT)

    def has_legacy_qualification_entry(self, page: Page, qualification_name: str) -> bool:
        qualification_section = page.locator("#qualification_info")
        try:
            qualification_section.wait_for(state="attached", timeout=5000)
            qualification_section.scroll_into_view_if_needed(timeout=10000)
        except PlaywrightTimeoutError:
            return False

        legacy_row = qualification_section.locator("tbody tr").filter(
            has_text=qualification_name
        ).first
        return legacy_row.count() > 0

    def has_compliance_info_entry(self, page: Page, row_label: str) -> bool:
        compliance_label = page.get_by_text(COMPLIANCE_INFO_SECTION_TEXT, exact=True).first
        if compliance_label.count() == 0:
            return False

        compliance_section = compliance_label.locator("xpath=..")
        rows = compliance_section.locator("tbody tr")
        return rows.filter(has_text=row_label).count() > 0

    def edit_compliance_infos(self, page: Page) -> None:
        if self.has_legacy_qualification_entry(page, EU_TOY_SAFETY_DIRECTIVE_TEXT):
            self.edit_eu_toy_safety_directive(page)
        else:
            self.log(f"\u672a\u627e\u5230\u5408\u89c4\u9879\uff0c\u8df3\u8fc7: {EU_TOY_SAFETY_DIRECTIVE_TEXT}")

        if self.has_legacy_qualification_entry(page, PRODUCT_IDENTIFIER_TEXT):
            self.edit_product_identifier(page)
        elif self.has_compliance_info_entry(page, PRODUCT_IDENTIFIER_TEXT):
            self.log(
                f"\u5728\u201c{COMPLIANCE_INFO_SECTION_TEXT}\u201d\u9996\u884c"
                f"\u201c{PRODUCT_IDENTIFIER_TEXT}\u201d\u6267\u884c\u4ea7\u54c1\u6807\u8bc6\u7b26\u64cd\u4f5c"
            )
            self.edit_product_identifier(page)
        else:
            self.log(f"\u672a\u627e\u5230\u5408\u89c4\u9879\uff0c\u8df3\u8fc7: {PRODUCT_IDENTIFIER_TEXT}")

        if self.has_legacy_qualification_entry(page, US_CHOKING_HAZARD_TEXT):
            self.edit_us_choking_hazard_warning(page)
        else:
            self.log(f"\u672a\u627e\u5230\u5408\u89c4\u9879\uff0c\u8df3\u8fc7: {US_CHOKING_HAZARD_TEXT}")

    def ensure_qualification_section_loaded(self, page: Page) -> None:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1000)

        qualification_section = page.locator("#qualification_info")
        for _ in range(8):
            try:
                qualification_section.wait_for(state="attached", timeout=3000)
                qualification_section.scroll_into_view_if_needed(timeout=10000)
                qualification_section.locator("tbody tr").first.wait_for(state="visible", timeout=5000)
                return
            except Exception:
                page.mouse.wheel(0, 1800)
                page.wait_for_timeout(1000)

        qualification_section.wait_for(state="attached", timeout=30000)
        qualification_section.scroll_into_view_if_needed(timeout=30000)
        qualification_section.locator("tbody tr").first.wait_for(state="visible", timeout=30000)

    def select_scope_multi_color_in_row(self, page: Page, row) -> None:
        scope_select = row.locator(".soui-select").first
        self.visible_click(scope_select)
        page.wait_for_timeout(500)
        self.click_visible_soui_option(page, MULTI_COLOR_TEXT)
        self.wait_select_value(page, scope_select, MULTI_COLOR_TEXT)
        self.log(f"\u5df2\u9009\u62e9\u9002\u7528\u8303\u56f4: {MULTI_COLOR_TEXT}")

    def choose_certificate_in_dialog(
        self,
        page: Page,
        qualification_name: str,
        certificate_name: str | None,
    ) -> str:
        dialog = page.locator(".soui-modal-panel").filter(
            has=page.locator("#upload-compliance-modal-content")
        ).last
        dialog.wait_for(state="visible", timeout=30000)

        rows = dialog.locator("tbody tr")
        rows.first.wait_for(state="visible", timeout=30000)
        target_row = rows.filter(has_text=certificate_name).first if certificate_name else rows.first
        target_row.wait_for(state="visible", timeout=30000)

        uploaded_name = self.read_certificate_row_name(target_row)

        checkbox = target_row.locator('[data-soui-role="checkbox-indicator"]').first
        try:
            checkbox.wait_for(state="visible", timeout=5000)
            self.visible_click(checkbox, timeout=5000)
        except Exception:
            self.visible_click(target_row.locator("td").first, timeout=5000)
        self.log(
            f"\u5df2\u9009\u62e9\u8bc1\u4e66: "
            f"{uploaded_name or certificate_name or qualification_name}"
        )

        self.select_scope_multi_color_in_row(page, target_row)

        submit_button = dialog.locator("button", has_text=SUBMIT_TEXT).last
        self.visible_click(submit_button)
        self.log(f"\u5df2\u63d0\u4ea4\u8d44\u8d28: {qualification_name}")
        page.wait_for_timeout(1000)

        if self.click_text_if_visible(page, NO_MORE_UPLOAD_TEXT, timeout=10000):
            self.log(f"\u5df2\u70b9\u51fb: {NO_MORE_UPLOAD_TEXT}")
        self.wait_or_close_active_modal(page)

        return uploaded_name

    def read_certificate_row_name(self, row) -> str:
        cells = row.locator("td")
        cell_count = cells.count()
        for cell_index in (3, 2, 1):
            if cell_index >= cell_count:
                continue

            cell_text = cells.nth(cell_index).inner_text(timeout=10000).strip()
            if cell_text:
                return cell_text

        return row.inner_text(timeout=10000).strip()

    def upload_qualification_by_name(
        self,
        page: Page,
        qualification_name: str,
        certificate_name: str | None,
    ) -> None:
        self.click_qualification_upload(page, qualification_name)
        self.choose_certificate_in_dialog(
            page,
            qualification_name=qualification_name,
            certificate_name=certificate_name,
        )

    def get_configured_spec_value(self) -> str:
        return self.get_style_config() or MULTI_COLOR_TEXT

    def ensure_real_shot_spec_selected_in_dialog(self, page: Page, dialog) -> None:
        spec_value = self.get_configured_spec_value()
        if dialog.get_by_text(spec_value, exact=True).count() > 0:
            self.log(f"\u5df2\u786e\u8ba4\u9009\u62e9\u89c4\u683c: {spec_value}")
            return

        spec_select = dialog.locator(".soui-select").first
        self.visible_click(spec_select)
        page.wait_for_timeout(500)
        self.click_visible_soui_option(page, spec_value)
        self.wait_select_value(page, spec_select, spec_value)
        self.log(f"\u5df2\u9009\u62e9\u89c4\u683c: {spec_value}")

    @staticmethod
    def is_image_upload_accept(accept: str) -> bool:
        normalized = str(accept or "").replace(" ", "").lower()
        if not normalized:
            return False
        values = [value for value in normalized.split(",") if value]
        return any(
            value in {"image/*", ".png", ".jpg", ".jpeg"}
            or value.startswith("image/")
            for value in values
        )

    def wait_for_real_shot_upload_inputs(self, page: Page, dialog):
        deadline = datetime.now().timestamp() + 30
        last_inputs_description = ""

        while datetime.now().timestamp() < deadline:
            upload_inputs = dialog.locator('input[type="file"]')
            image_input_indexes = []
            descriptions = []

            for index in range(upload_inputs.count()):
                upload_input = upload_inputs.nth(index)
                accept = upload_input.get_attribute("accept") or ""
                descriptions.append(f"#{index + 1} accept={accept or '<empty>'}")
                if self.is_image_upload_accept(accept):
                    image_input_indexes.append(index)

            last_inputs_description = "; ".join(descriptions) or "未找到 input[type=file]"
            if len(image_input_indexes) == 2:
                return (
                    upload_inputs.nth(image_input_indexes[0]),
                    upload_inputs.nth(image_input_indexes[1]),
                )

            page.wait_for_timeout(500)

        raise RuntimeError(
            "实拍图弹窗中未找到明确的两个图片上传框，"
            f"当前文件上传框: {last_inputs_description}"
        )

    def upload_real_shot_photos(self, page: Page) -> None:
        body_photo_dir = self.product_files.body_photo_dir or os.path.join(
            self.product_files.root_dir, BODY_REAL_PHOTO_DIR_NAME
        )
        package_photo_dir = self.product_files.package_photo_dir or os.path.join(
            self.product_files.root_dir, PACKAGE_REAL_PHOTO_DIR_NAME
        )
        body_photos = [
            self.convert_image_to_square(image_file)
            for image_file in self.get_image_files(
                body_photo_dir,
                exclude_mark_images=bool(self.common_mark_image_file),
            )
        ]
        package_photos = [
            self.convert_image_to_square(image_file)
            for image_file in self.get_image_files(
                package_photo_dir,
                exclude_mark_images=bool(self.common_mark_image_file),
            )
        ]
        if self.common_mark_image_file:
            if not os.path.exists(self.common_mark_image_file):
                raise FileNotFoundError(f"Common mark image not found: {self.common_mark_image_file}")
            package_photos.append(self.convert_image_to_square(self.common_mark_image_file))
            self.log(f"\u5df2\u52a0\u5165\u516c\u5171\u5305\u88c5\u6807\u56fe: {self.common_mark_image_file}")

        self.click_real_shot_upload(page)

        dialog = page.locator(".soui-modal-panel").filter(
            has=page.locator("#upload-compliance-modal-content")
        ).last
        dialog.wait_for(state="visible", timeout=30000)
        before_spec_wait_ms = random.randint(1000, 3000)
        page.wait_for_timeout(before_spec_wait_ms)
        self.log(f"\u5df2\u7b49\u5f85\u5b9e\u62cd\u56fe\u89c4\u683c\u521d\u59cb\u5316: {before_spec_wait_ms / 1000:.1f}\u79d2")
        self.ensure_real_shot_spec_selected_in_dialog(page, dialog)
        wait_ms = random.randint(1000, 3000)
        page.wait_for_timeout(wait_ms)
        self.log(f"\u5df2\u7b49\u5f85\u5b9e\u62cd\u56fe\u5f39\u7a97\u7a33\u5b9a: {wait_ms / 1000:.1f}\u79d2")

        body_upload_input, package_upload_input = self.wait_for_real_shot_upload_inputs(page, dialog)
        self.reveal(dialog, timeout=5000)
        body_upload_input.set_input_files(body_photos)
        self.log(f"\u5df2\u4e0a\u4f20\u672c\u4f53\u5b9e\u62cd\u56fe: {len(body_photos)} \u5f20")

        self.reveal(dialog, timeout=5000)
        package_upload_input.set_input_files(package_photos)
        self.log(f"\u5df2\u4e0a\u4f20\u5305\u88c5\u5b9e\u62cd\u56fe: {len(package_photos)} \u5f20")

        submit_button = dialog.locator("button", has_text=SUBMIT_TEXT).last
        self.wait_for_button_enabled(page, submit_button, "实拍图上传提交")
        self.visible_click(submit_button)
        self.log("\u5df2\u63d0\u4ea4\u5b9e\u62cd\u56fe")
        page.wait_for_timeout(1000)

        if self.click_text_if_visible(page, NO_MORE_UPLOAD_TEXT, timeout=10000):
            self.log(f"\u5df2\u70b9\u51fb: {NO_MORE_UPLOAD_TEXT}")
        self.wait_or_close_active_modal(page)

    def upload_qualifications(self, page: Page) -> None:
        for qualification_name, certificate_name in self.get_certificate_upload_items():
            self.upload_qualification_by_name(
                page,
                qualification_name,
                certificate_name=certificate_name,
            )

        self.upload_real_shot_photos(page)
        self.edit_compliance_infos(page)

    def upload_product_video(self, page: Page) -> None:
        if not os.path.exists(self.product_video_file):
            raise FileNotFoundError(f"Product video not found: {self.product_video_file}")

        if self.click_text_if_visible(page, EXPAND_VIDEO_TEXT, timeout=5000):
            self.log(f"\u5df2\u5c55\u5f00: {EXPAND_VIDEO_TEXT}")
        else:
            self.log("\u5546\u54c1\u89c6\u9891\u533a\u57df\u5df2\u5c55\u5f00\u6216\u5c55\u5f00\u6309\u94ae\u672a\u663e\u793a")

        video_input = page.locator('input[type="file"][accept=".mp4"]')
        video_input.wait_for(state="attached", timeout=30000)
        self.reveal(page.locator(".package_info, .supplier_info, .so-form-item").filter(has=video_input).last, timeout=5000)
        video_input.set_input_files(self.product_video_file)
        self.log(f"\u5df2\u4e0a\u4f20\u5546\u54c1\u89c6\u9891: {self.product_video_file}")

    def fill_product_title(self, page: Page) -> None:
        title_input = page.locator(".main_name input")
        product_title = str(self.product_config.get("\u5546\u54c1\u6807\u9898", DEFAULT_PRODUCT_TITLE))
        self.visible_fill(title_input, product_title)
        self.log("\u5df2\u586b\u5199\u5546\u54c1\u6807\u9898")

    @staticmethod
    def get_attribute_label_candidates(attr_title_keyword: str) -> tuple[str, ...]:
        return ATTRIBUTE_LABEL_ALIASES.get(attr_title_keyword, (attr_title_keyword,))

    def find_attribute_item(self, page: Page, attr_title_keyword: str):
        label_candidates = self.get_attribute_label_candidates(attr_title_keyword)
        locator_pairs = (
            (
                ".spmp_style__productAttrItem--KizVG6UF",
                ".spmp_style__productAttrLabelBox--bZlNXzwd",
            ),
            ('[class*="productAttrItem"]', '[class*="productAttrLabelBox"]'),
        )

        for item_selector, label_selector in locator_pairs:
            for label in label_candidates:
                attr_item = page.locator(item_selector).filter(
                    has=page.locator(label_selector, has_text=label)
                )
                if attr_title_keyword == "Material":
                    attr_item = attr_item.filter(
                        has_not=page.locator(label_selector, has_text="Other Material")
                    )
                try:
                    attr_item.first.wait_for(state="visible", timeout=2000)
                    return attr_item.first
                except PlaywrightTimeoutError:
                    continue

        labels = " / ".join(label_candidates)
        raise RuntimeError(f"未找到可见的商品属性下拉框: {labels}")

    def select_attribute(
        self,
        page: Page,
        attr_title_keyword: str,
        value: str,
        ratio: str | None = None,
    ) -> None:
        attr_item = self.find_attribute_item(page, attr_title_keyword)

        select_input = attr_item.locator(".soui-select input").first
        self.visible_click(select_input)
        select_input.fill(value)
        page.wait_for_timeout(500)
        select_input.press("Enter")
        page.wait_for_timeout(300)

        if ratio is not None:
            ratio_input = attr_item.locator('input[type="text"]').last
            self.visible_fill(ratio_input, ratio)
            self.log(f"\u5df2\u586b\u5199\u5c5e\u6027\u6bd4\u4f8b: {attr_title_keyword} = {ratio}")

        self.log(f"\u5df2\u9009\u62e9\u5c5e\u6027: {attr_title_keyword} = {value}")

    def fill_product_attributes(self, page: Page) -> None:
        for attr_title_keyword, value, ratio in self.get_product_attributes():
            self.select_attribute(page, attr_title_keyword, value, ratio)

    def use_spec_template(self, page: Page) -> None:
        template_button = page.locator(
            ".spmp_style__specContent--gAJidZU0 button",
            has_text=USE_TEMPLATE_TEXT,
        )
        self.visible_click(template_button)
        self.log(f"\u5df2\u70b9\u51fb: {USE_TEMPLATE_TEXT}")

    def fill_main_style_spec_from_config(self, page: Page) -> None:
        style = self.get_style_config()
        if not style:
            self.log("\u672a\u914d\u7f6e\u6b3e\u5f0f\uff0c\u8df3\u8fc7\u4e3b\u89c4\u683c\u6b3e\u5f0f\u586b\u5199")
            return

        spec_section = page.locator(".main_spec .spmp_style__specContent--gAJidZU0")
        spec_section.wait_for(state="visible", timeout=30000)
        self.reveal(spec_section)

        style_input = spec_section.locator(
            ".spmp_style__specValues--xvosvt9D "
            ".spmp_style__specValueItem--mHIth8aj "
            ".so-select-inner"
        ).first
        self.visible_click(style_input)
        page.wait_for_timeout(300)
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        page.keyboard.type(style, delay=50)
        page.keyboard.press("Enter")
        self.reveal(spec_section, timeout=5000)
        spec_section.click(position={"x": 10, "y": 10}, force=True)
        page.wait_for_timeout(800)
        self.log(f"\u5df2\u586b\u5199\u4e3b\u89c4\u683c\u6b3e\u5f0f: {style}")

    def fill_color_specs_from_config(self, page: Page) -> None:
        colors = self.get_color_config()
        if not colors:
            self.log("\u672a\u914d\u7f6e\u989c\u8272\uff0c\u8df3\u8fc7\u89c4\u683c\u989c\u8272\u586b\u5199")
            return

        spec_section = page.locator(".other_spec .spmp_style__specContent--gAJidZU0")
        spec_section.wait_for(state="visible", timeout=30000)
        self.reveal(spec_section)

        for index, color in enumerate(colors):
            self.fill_color_spec_value(page, spec_section, index, color)

        self.log(f"\u5df2\u586b\u5199\u989c\u8272\u89c4\u683c: {', '.join(colors)}")

    def fill_color_spec_value(self, page: Page, spec_section, index: int, color: str) -> None:
        value_items = spec_section.locator(".spmp_style__specValues--xvosvt9D .spmp_style__specValueItem--mHIth8aj")
        for _ in range(20):
            if value_items.count() > index:
                break
            page.wait_for_timeout(500)

        if value_items.count() <= index:
            raise RuntimeError(f"\u672a\u627e\u5230\u7b2c {index + 1} \u4e2a\u989c\u8272\u89c4\u683c\u8f93\u5165\u6846")

        value_item = value_items.nth(index)
        select_inner = value_item.locator(".so-select-inner").first
        self.visible_click(select_inner)
        page.wait_for_timeout(300)
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        page.keyboard.type(color, delay=50)
        page.keyboard.press("Enter")
        self.reveal(spec_section, timeout=5000)
        spec_section.click(position={"x": 10, "y": 10}, force=True)
        page.wait_for_timeout(800)
        self.log(f"\u5df2\u586b\u5199\u989c\u8272\u89c4\u683c {index + 1}: {color}")

    def publish_product_and_sign_up(self, page: Page) -> None:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1000)
        publish_button = page.locator("button", has_text=PUBLISH_AND_SIGN_UP_TEXT).last
        self.visible_click(publish_button)
        self.log(f"\u5df2\u70b9\u51fb: {PUBLISH_AND_SIGN_UP_TEXT}")
        self.wait_for_publish_completion(page)

    def wait_for_publish_completion(self, page: Page) -> None:
        initial_url = page.url
        success_pattern = re.compile(
            r"\u53d1\u5e03\u6210\u529f|\u62a5\u540d\u6210\u529f|\u63d0\u4ea4\u6210\u529f|\u53d1\u5e03\u5e76\u62a5\u540d\u6210\u529f"
        )
        blocked_pattern = re.compile(r"\u53d1\u5e03\u62e6\u622a|14525|\u5c5e\u6027\u3010\u654f\u611f\u7c7b\u522b\u3011")
        deadline = datetime.now().timestamp() + 30

        while datetime.now().timestamp() < deadline:
            self.ensure_not_cancelled()
            blocked_dialog = page.locator(".so-modal-panel, .soui-modal-panel").filter(
                has_text=blocked_pattern
            ).last
            try:
                if blocked_dialog.count() > 0 and blocked_dialog.is_visible(timeout=300):
                    detail = blocked_dialog.inner_text(timeout=2000).strip()
                    self.log(f"\u53d1\u5e03\u88ab\u62e6\u622a\uff0c\u5c06\u91cd\u65b0\u9009\u62e9\u53d1\u5e03\u5165\u53e3: {detail}")
                    know_button = blocked_dialog.locator("button", has_text=I_KNOW_TEXT).last
                    if know_button.count() > 0:
                        know_button.click(force=True)
                        page.wait_for_timeout(500)
                    raise PublishBlockedRetry(detail)
            except PublishBlockedRetry:
                raise
            except Exception:
                pass

            success_notice = page.locator(
                '.soui-message, .soui-notification, [role="alert"]'
            ).filter(has_text=success_pattern)
            for index in range(success_notice.count()):
                try:
                    if success_notice.nth(index).is_visible(timeout=300):
                        self.log("\u5df2\u786e\u8ba4\u53d1\u5e03\u5e76\u62a5\u540d\u6210\u529f")
                        return
                except Exception:
                    continue

            publish_button = page.locator(
                "button",
                has_text=PUBLISH_AND_SIGN_UP_TEXT,
            ).last
            try:
                if publish_button.count() == 0 or not publish_button.is_visible(timeout=300):
                    self.log("\u53d1\u5e03\u9875\u5df2\u79fb\u9664\u63d0\u4ea4\u6309\u94ae\uff0c\u89c6\u4e3a\u63d0\u4ea4\u5b8c\u6210")
                    return
            except Exception:
                if page.url != initial_url:
                    self.log("\u53d1\u5e03\u9875\u5df2\u8df3\u8f6c\uff0c\u89c6\u4e3a\u63d0\u4ea4\u5b8c\u6210")
                    return

            if page.url != initial_url:
                self.log("\u53d1\u5e03\u9875\u5df2\u8df3\u8f6c\uff0c\u89c6\u4e3a\u63d0\u4ea4\u5b8c\u6210")
                return

            page.wait_for_timeout(500)

        raise RuntimeError(
            "\u5df2\u70b9\u51fb\u201c\u53d1\u5e03\u5546\u54c1\u5e76\u62a5\u540d\u201d\uff0c"
            "\u4f46 30 \u79d2\u5185\u672a\u786e\u8ba4\u63d0\u4ea4\u6210\u529f\uff0c\u5df2\u4fdd\u7559\u5f53\u524d\u53d1\u5e03\u9875\u4ee5\u4fbf\u68c0\u67e5"
        )

    def close_publish_page(self, publish_page: Page | None) -> None:
        if publish_page is None:
            return

        try:
            if not publish_page.is_closed():
                publish_page.close()
                self.log("\u5df2\u5173\u95ed\u5f02\u5e38\u7684\u53d1\u5e03\u9875")
        except Exception as error:
            self.log(f"\u5173\u95ed\u5f02\u5e38\u7684\u53d1\u5e03\u9875\u5931\u8d25: {error}")

    def run(self) -> None:
        self.log(f"\u5546\u54c1\u603b\u76ee\u5f55: {self.product_root_dir}")
        self.log(f"\u5df2\u51c6\u5907 {len(self.product_file_sets)} \u4e2a\u5546\u54c1\u53d1\u5e03\u8f6e\u6b21\uff0c\u5c06\u6309\u987a\u5e8f\u8fde\u7eed\u53d1\u5e03")
        self.run_step(self.start_browser)
        self.run_step(self.load_cookies)

        for index, product_files in enumerate(self.product_file_sets, start=1):
            self.set_active_product_files(product_files)
            self.log(
                f"\u5f00\u59cb\u7b2c {index}/{len(self.product_file_sets)} \u8f6e\uff1a"
                f"{os.path.basename(self.image_dir)}"
            )
            self.log(f"\u672c\u8f6e\u56fe\u7247\u76ee\u5f55: {self.image_dir}")
            self.log(f"\u672c\u8f6e\u5546\u54c1\u4e3b\u56fe: {self.main_image_file}")
            self.log(f"\u5546\u54c1\u89c6\u9891: {self.product_video_file}")
            self.log(f"UI\u751f\u6210\u914d\u7f6e: {self.product_files.config_file}")

            publish_page: Page | None = None
            round_completed = False
            round_skipped = False
            try:
                if index == 1:
                    self.run_step(self.open_target_page)
                    self.run_step(self.select_opportunity_entry)
                    self.run_step(self.select_product_category)
                    self.run_step(self.search)
                else:
                    self.log("\u590d\u7528\u9996\u8f6e\u5df2\u7b5b\u9009\u7684\u673a\u4f1a\u5546\u54c1\u9875\u9762\uff0c\u8df3\u8fc7\u9875\u7b7e\u4e0e\u7c7b\u76ee\u9009\u62e9")
                    self.run_step(self.search)

                for retry_index in range(1, 4):
                    try:
                        publish_page = self.run_step(self.click_random_publish_same)
                        self.run_step(self.select_publish_category, publish_page)
                        self.run_step(self.handle_publish_tips, publish_page)
                        self.run_step(self.upload_main_image, publish_page)
                        self.run_step(self.upload_product_video, publish_page)
                        self.run_step(self.fill_product_title, publish_page)
                        self.run_step(self.fill_product_attributes, publish_page)
                        self.run_step(self.use_spec_template, publish_page)
                        self.run_step(self.fill_main_style_spec_from_config, publish_page)
                        self.run_step(self.fill_color_specs_from_config, publish_page)
                        self.run_step(self.upload_detail_images, publish_page)
                        self.run_step(self.fill_supplier_info, publish_page)
                        self.run_step(self.fill_package_info, publish_page)
                        self.run_step(self.confirm_package_size_warning_if_present, publish_page)
                        self.run_step(self.upload_qualifications, publish_page)
                        self.run_step(self.publish_product_and_sign_up, publish_page)
                        round_completed = True
                        break
                    except AutomationCancelled:
                        raise
                    except Exception as error:
                        error_detail = str(error).strip() or error.__class__.__name__
                        self.log(
                            f"\u7b2c {retry_index}/3 \u6b21\u53d1\u5e03\u5f53\u524d\u5546\u54c1\u5931\u8d25: "
                            f"{error_detail}"
                        )
                        self.close_publish_page(publish_page)
                        publish_page = None

                        if retry_index >= 3:
                            self.log(
                                f"\u5f53\u524d\u5546\u54c1\u5df2\u8fde\u7eed\u91cd\u8bd5 3 \u6b21\uff0c"
                                "\u5df2\u8df3\u8fc7\u8be5\u5546\u54c1\u5e76\u7ee7\u7eed\u540e\u7eed\u5546\u54c1"
                            )
                            round_skipped = True
                            break

                        self.log(
                            f"\u5c06\u5173\u95ed\u5f53\u524d\u53d1\u5e03\u9875\uff0c\u91cd\u65b0\u641c\u7d22\u5e76\u968f\u673a\u9009\u62e9"
                            f"\u53d1\u5e03\u540c\u6b3e\uff08\u7b2c {retry_index + 1}/3 \u6b21\uff09"
                        )
                        self.run_step(self.search)
            finally:
                self.cleanup_temp_files()

            if round_completed and publish_page is not None:
                try:
                    self.log(f"\u7b2c {index} \u8f6e\u63d0\u4ea4\u5df2\u786e\u8ba4\uff0c10 \u79d2\u540e\u5173\u95ed\u53d1\u5e03\u6807\u7b7e\u9875")
                    publish_page.wait_for_timeout(10000)
                    publish_page.close()
                    self.log(f"\u5df2\u5173\u95ed\u7b2c {index} \u8f6e\u7684\u53d1\u5e03\u6807\u7b7e\u9875")
                except Exception as error:
                    self.log(f"\u5173\u95ed\u7b2c {index} \u8f6e\u53d1\u5e03\u6807\u7b7e\u9875\u5931\u8d25: {error}")

            if round_skipped:
                self.log(f"\u7b2c {index}/{len(self.product_file_sets)} \u8f6e\u5df2\u8df3\u8fc7")
            else:
                self.log(f"\u7b2c {index}/{len(self.product_file_sets)} \u8f6e\u53d1\u5e03\u6d41\u7a0b\u5df2\u5b8c\u6210")

        self.log("\u6240\u6709\u5546\u54c1\u53d1\u5e03\u8f6e\u6b21\u5df2\u5b8c\u6210\u53d1\u5e03")

    def close(self) -> None:
        if self.context is not None:
            self.context.close()
            self.context = None
            self.page = None
        self.cleanup_temp_files()

    def cleanup_temp_files(self) -> None:
        if self.temp_dir is None:
            return

        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            self.log(f"\u5df2\u6e05\u7406\u4e34\u65f6\u56fe\u7247\u76ee\u5f55: {self.temp_dir}")
        self.temp_dir = None

    def require_page(self) -> Page:
        if self.page is None:
            raise RuntimeError("Browser has not been started.")
        return self.page
