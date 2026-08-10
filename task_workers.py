from __future__ import annotations

import os
import requests
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright
from PyQt5.QtCore import QThread, pyqtSignal

from aiprice_image_search import search_by_image as aiprice_search_by_image
from automation import AutomationCancelled, BrowserAutomation
from config import BODY_REAL_PHOTO_DIR_NAME
from config_services import (
    find_first_video, get_goods_id, get_goods_name, normalize_aiprice_result_for_table,
    validate_base_product_dir, write_round_product_config,
)
from image_services import (
    OUTPUT_DIR, build_prompt, edit_image_file, generate_ai_crops_for_goods,
    get_ai_model_list, get_download_referer, normalize_thumbnail_bytes,
    save_ai_image_response,
)
from product_files import ProductFiles, get_image_files
from real_photo_library import RealPhotoVariant, scan_real_photo_library
class AipriceImageSearchWorker(QThread):
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, image_path: str, platform: str):
        super().__init__()
        self.image_path = image_path
        self.platform = platform

    def run(self):
        try:
            result = aiprice_search_by_image(self.image_path, self.platform)
            self.finished.emit(normalize_aiprice_result_for_table(result))
        except Exception as error:
            self.failed.emit(str(error))


class ThumbnailWorker(QThread):
    loaded = pyqtSignal(int, bytes)

    def __init__(self, row: int, image_url: str):
        super().__init__()
        self.row = row
        self.image_url = image_url

    def run(self):
        try:
            headers = {
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": get_download_referer(self.image_url),
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/151.0.0.0 Safari/537.36"
                ),
            }
            response = requests.get(self.image_url, headers=headers, timeout=60)
            if response.status_code == 200:
                self.loaded.emit(self.row, normalize_thumbnail_bytes(response.content))
        except Exception:
            pass


class AiModelListWorker(QThread):
    finished = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, provider: str, token: str):
        super().__init__()
        self.provider = provider
        self.token = token

    def run(self):
        try:
            self.finished.emit(get_ai_model_list(self.provider, self.token))
        except Exception as error:
            self.failed.emit(str(error))


class AiImageTestWorker(QThread):
    finished = pyqtSignal(str, str)
    failed = pyqtSignal(str)

    def __init__(
        self,
        image_path: str,
        provider: str,
        model: str,
        token: str,
        product_name: str,
    ):
        super().__init__()
        self.image_path = image_path
        self.provider = provider
        self.model = model
        self.token = token
        self.product_name = product_name

    def run(self):
        try:
            output_dir = OUTPUT_DIR / f"ai_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            output_dir.mkdir(parents=True, exist_ok=True)
            prompt = build_prompt(self.product_name)
            (output_dir / "ai_prompt.txt").write_text(prompt, encoding="utf-8")
            response = edit_image_file(
                self.image_path,
                prompt=prompt,
                provider=self.provider,
                token=self.token,
                model=self.model,
            )
            (output_dir / "ai_response.json").write_text(response.text, encoding="utf-8")
            response.raise_for_status()
            output_path = output_dir / "generated_image.png"
            if not save_ai_image_response(response, output_path):
                raise RuntimeError(f"AI 已返回结果，但没有解析到可保存的图片，响应已保存到 {output_dir}")
            self.finished.emit(os.fspath(output_path), os.fspath(output_dir))
        except Exception as error:
            self.failed.emit(str(error))


class AsyncProductFileSets:
    def __init__(
        self,
        first_product: ProductFiles,
        futures: list[Future],
        total_count: int,
        stop_event: threading.Event,
        log_handler,
    ):
        self.first_product = first_product
        self.futures = futures
        self.total_count = total_count
        self.stop_event = stop_event
        self.log_handler = log_handler

    def __len__(self) -> int:
        return self.total_count

    def __getitem__(self, index: int) -> ProductFiles:
        if index == 0:
            return self.first_product
        if index < 0 or index >= self.total_count:
            raise IndexError(index)
        return self.resolve_future(index)

    def __iter__(self):
        yield self.first_product
        for index in range(1, self.total_count):
            yield self.resolve_future(index)

    def resolve_future(self, index: int) -> ProductFiles:
        if self.stop_event.is_set():
            raise AutomationCancelled("用户已请求停止运行")
        future = self.futures[index - 1]
        if not future.done():
            self.log_handler(f"第 {index + 1}/{self.total_count} 轮图片仍在生成，正在等待生成完成...")
        return future.result()


class PublishWorker(QThread):
    log = pyqtSignal(str)
    status = pyqtSignal(str)
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, goods_list: list[dict], settings: dict):
        super().__init__()
        self.goods_list = goods_list
        self.settings = settings
        self.pause_event = threading.Event()
        self.pause_event.set()
        self.stop_event = threading.Event()
        self.playwright = None
        self.automation: BrowserAutomation | None = None
        self.generation_executor: ThreadPoolExecutor | None = None

    def pause_or_resume(self) -> bool:
        if self.pause_event.is_set():
            self.pause_event.clear()
            return True
        self.pause_event.set()
        return False

    def stop(self) -> None:
        self.stop_event.set()
        self.pause_event.set()

    def run(self):
        completed = False
        try:
            self.status.emit("正在生成首轮图片")
            product_file_sets = self.prepare_product_file_pipeline()
            self.status.emit("正在上架")
            self.playwright = sync_playwright().start()
            self.automation = BrowserAutomation(
                self.playwright,
                product_root_dir=self.settings["product_root_dir"],
                cookies_file=self.settings["cookies_file"],
                viewport_width=self.settings["viewport_width"],
                viewport_height=self.settings["viewport_height"],
                pause_event=self.pause_event,
                stop_event=self.stop_event,
                opportunity_tab=self.settings["opportunity_tab"],
                category_path=self.settings["category_path"],
                publish_category_path=self.settings["publish_category_path"],
                product_file_sets=product_file_sets,
                common_mark_image_file=self.settings.get("common_mark_image_file", ""),
                log=lambda message: self.log.emit(f"[自动化] {message}"),
            )
            self.automation.run()
            completed = True
            self.status.emit("已完成")
            self.finished.emit("所有勾选商品已完成生图和上架")
        except AutomationCancelled:
            self.status.emit("已停止")
            self.failed.emit("已按用户请求停止流程")
        except Exception as error:
            self.status.emit("执行失败")
            self.failed.emit(str(error))
        finally:
            if self.automation is not None:
                try:
                    if completed:
                        self.automation.cleanup_temp_files()
                    else:
                        self.automation.close()
                except Exception as cleanup_error:
                    self.log.emit(f"清理浏览器或临时文件失败: {cleanup_error}")
            if self.playwright is not None:
                try:
                    self.playwright.stop()
                except Exception as cleanup_error:
                    self.log.emit(f"清理 Playwright 失败: {cleanup_error}")
            if self.generation_executor is not None:
                self.generation_executor.shutdown(wait=False, cancel_futures=True)
                self.generation_executor = None

    def prepare_product_file_pipeline(self) -> AsyncProductFileSets:
        root_dir = Path(self.settings["product_root_dir"])
        variants = scan_real_photo_library(root_dir)
        if len(variants) != len(self.goods_list):
            raise RuntimeError(
                f"实拍图商品数量 {len(variants)} 与待处理商品数量 {len(self.goods_list)} 不一致"
            )

        first_product = self.prepare_one_product_files(1, self.goods_list[0], root_dir, variants[0])
        remaining_goods = self.goods_list[1:]
        remaining_variants = variants[1:]
        self.generation_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="xiyin_ai_generator")
        futures = [
            self.generation_executor.submit(
                self.prepare_one_product_files,
                index,
                goods,
                root_dir,
                variant,
            )
            for index, (goods, variant) in enumerate(zip(remaining_goods, remaining_variants), start=2)
        ]
        if futures:
            self.log.emit(f"首轮图片已就绪，剩余 {len(futures)} 个商品将在上架过程中后台生成")
        return AsyncProductFileSets(
            first_product,
            futures,
            len(self.goods_list),
            self.stop_event,
            self.log.emit,
        )

    def prepare_one_product_files(
        self,
        index: int,
        goods: dict,
        root_dir: Path,
        variant: RealPhotoVariant,
    ) -> ProductFiles:
        self.ensure_not_cancelled()
        goods_id = get_goods_id(goods) or f"selected_{index:02d}"
        self.log.emit(f"开始生成第 {index}/{len(self.goods_list)} 个勾选商品: {goods_id}")
        product_config = self.get_product_config_for_goods(goods)
        product_images = sorted(path for path in variant.product_image_dir.iterdir() if path.is_file())
        source_image_path = product_images[(index - 1) % len(product_images)]
        crop_paths = generate_ai_crops_for_goods(
            goods,
            lambda message: self.log.emit(f"[AI] {message}"),
            ai_provider=self.settings.get("ai_provider", "geeknow"),
            ai_token=self.settings.get("ai_token", ""),
            ai_model=self.settings.get("ai_model", "gpt-image-2"),
            chat_provider=self.settings.get("ai_chat_provider", "geeknow"),
            chat_token=self.settings.get("ai_chat_token", ""),
            chat_model=self.settings.get("ai_chat_model", "gpt-5.5"),
            generate_title=bool(self.settings.get("ai_generate_title", False)),
            generate_prompt=bool(self.settings.get("ai_generate_prompt", False)),
            product_config=product_config,
            reference_image_paths=self.collect_reference_images(variant),
            source_image_path=source_image_path,
        )
        if not crop_paths:
            raise RuntimeError(f"商品 {goods_id} 未生成可用裁剪图")
        goods_folder = (
            crop_paths[0].parent.parent
            if crop_paths[0].parent.name == "cropped_images"
            else crop_paths[0].parent
        )
        config_file = write_round_product_config(
            goods_folder,
            product_config,
            goods,
            self.settings["title_source"],
        )
        self.log.emit(f"已根据UI设置生成本轮配置: {config_file}")
        self.log.emit(f"第 {index}/{len(self.goods_list)} 个商品图片已生成完成")

        return ProductFiles(
            root_dir=os.fspath(variant.variant_dir),
            selected_image_dir=os.fspath(crop_paths[0].parent),
            main_image_file=os.fspath(crop_paths[0]),
            product_video_file=os.fspath(variant.video_file) if variant.video_file else "",
            config_file=os.fspath(config_file),
            body_photo_dir=os.fspath(variant.body_dir),
            package_photo_dir=os.fspath(variant.package_dir) if variant.package_dir else "",
        )

    def get_product_config_for_goods(self, goods: dict) -> dict:
        product_name = get_goods_name(goods).strip()
        configured = self.settings.get("real_photo_configs", {}).get(product_name)
        if isinstance(configured, dict) and (
            "商品标题" in configured or "必填属性" in configured or "包装信息" in configured
        ):
            return configured

        return self.settings.get("product_config", {})

    @staticmethod
    def collect_reference_images(variant: RealPhotoVariant) -> list[Path]:
        references: list[Path] = []
        references.extend(Path(path) for path in get_image_files(os.fspath(variant.product_image_dir))[:3])
        references.extend(Path(path) for path in get_image_files(os.fspath(variant.body_dir))[:3])
        return references

    def ensure_not_cancelled(self) -> None:
        if self.stop_event.is_set():
            raise AutomationCancelled("用户已请求停止运行")
