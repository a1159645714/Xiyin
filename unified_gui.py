import json
import os
import re
import sys
import webbrowser
from pathlib import Path

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QProgressDialog,
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    ElevatedCardWidget,
    FluentIcon as FIF,
    FluentWindow,
    PrimaryPushButton,
    PushButton as QPushButton,
    TextEdit as QTextEdit,
    Theme,
    setTheme,
    setThemeColor,
)

from aiprice_image_search import DEFAULT_SEARCH_SIZE
from category_catalog import CategoryTree, load_category_catalog, parse_category_path, resolve_category_path
from config import (
    APP_SETTINGS_FILE,
    APP_TITLE,
    APP_VERSION,
    CATEGORY_PATH_END_TEXT,
    CERTIFICATE_ENABLED_KEY,
    CONFIGURABLE_QUALIFICATIONS,
    COOKIES_FILE,
    DEFAULT_PRODUCT_ROOT_DIR,
    DEFAULT_PRODUCT_TITLE,
    OPPORTUNITY_TAB_OPTIONS,
    VIEWPORT_HEIGHT,
    VIEWPORT_WIDTH,
)
from product_files import CONFIG_FILE_NAME, ProductFiles, get_image_files, load_product_config
from store_profiles import STORE_TYPE_OPTIONS, TOY_STORE_TYPE, StoreProfile, get_store_profile
from 协议AI import AI_PROVIDER_CONFIGS
from config_services import *
from real_photo_library import scan_real_photo_library
from image_services import *
from task_workers import (
    AipriceImageSearchWorker,
    AiImageTestWorker,
    AiModelListWorker,
    AsyncProductFileSets,
    PublishWorker,
    ThumbnailWorker,
)
from update_service import (
    UpdateManifest,
    can_install_updates,
    is_newer_version,
    is_update_required,
    is_version_disabled,
    launch_updater,
)
from update_workers import UpdateCheckWorker, UpdateDownloadWorker


CERTIFICATE_FIELD_ALIASES = {
    "玩具说明书（五国语言）": ("玩具说明书",),
    "TOY自符声明-EU（手动）": ("TOY自符声明-EU",),
    "欧洲玩具检测报告:EN71-1/2/3、REACH二甲酸酯含量": (
        "欧洲玩具检测报告:EN71-1/2/3",
        "REACH二甲酸酯含量",
    ),
    "CPC证书（手动）": ("CPC证书",),
}


def certificate_upload_enabled_by_default(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no", "否", "关闭", "disabled"}
    return value is not False


class NoWheelComboBox(QComboBox):
    """Prevent accidental selection changes while the popup is closed."""

    def wheelEvent(self, event) -> None:
        if self.view().isVisible():
            super().wheelEvent(event)
            return
        event.ignore()



class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        setTheme(Theme.DARK)
        setThemeColor("#1677ff")
        try:
            self.setMicaEffectEnabled(True)
        except Exception:
            pass
        self.worker: AipriceImageSearchWorker | None = None
        self.publish_worker: PublishWorker | None = None
        self.ai_model_worker: AiModelListWorker | None = None
        self.ai_test_worker: AiImageTestWorker | None = None
        self.thumbnail_workers: list[ThumbnailWorker] = []
        self.update_check_worker: UpdateCheckWorker | None = None
        self.update_download_worker: UpdateDownloadWorker | None = None
        self.update_progress_dialog: QProgressDialog | None = None
        self.update_access_blocked = False
        self.current_goods_list: list[dict] = []
        self.selected_image_path = ""
        self.ai_test_image_path = ""
        self.category_catalog: CategoryTree = {}
        self.category_combos: list[QComboBox] = []
        self.active_store_type = TOY_STORE_TYPE
        self.is_restoring_settings = False

        self.settings = self.load_settings()
        self.setWindowTitle(f"{APP_TITLE} v{APP_VERSION}")
        self.setMinimumSize(1180, 760)
        self.resize(1380, 860)
        self.build_ui()
        self.apply_styles()
        self.restore_settings_to_ui()
        QTimer.singleShot(1500, self.check_for_updates)

    def build_ui(self) -> None:
        search_tab = self.build_search_tab()
        search_tab.setObjectName("searchInterface")
        ai_tab = self.build_ai_settings_tab()
        ai_tab.setObjectName("aiInterface")
        settings_tab = self.build_settings_tab()
        settings_tab.setObjectName("settingsInterface")
        run_tab = self.build_run_tab()
        run_tab.setObjectName("runInterface")

        self.addSubInterface(search_tab, FIF.SEARCH, "选品搜图")
        self.addSubInterface(ai_tab, FIF.PHOTO, "AI设置")
        self.addSubInterface(settings_tab, FIF.SETTING, "上架设置")
        self.addSubInterface(run_tab, FIF.PLAY, "执行中心")
        self.navigationInterface.setExpandWidth(186)
        self.navigationInterface.setCollapsible(False)
        self.navigationInterface.expand(useAni=False)
        self.navigationInterface.setStyleSheet(
            """
            QWidget {
                background: #111827;
                color: #d1d5db;
            }
            QPushButton {
                background: transparent;
                color: #9ca3af;
                border: none;
            }
            QPushButton:hover {
                background: #1f2937;
                color: #f9fafb;
            }
            QPushButton:checked {
                background: #1e3a8a;
                color: #dbeafe;
            }
            """
        )

    def build_search_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        self.add_page_header(layout, "选品搜图", "选择一张参考图，搜索机会商品并勾选要自动生成和上架的商品。")

        top = ElevatedCardWidget()
        top.setObjectName("Panel")
        top_layout = QHBoxLayout(top)
        self.preview_label = QLabel("未选择\n图片")
        self.preview_label.setObjectName("ImagePreview")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setFixedSize(132, 132)
        self.image_label = QLabel("未选择图片")
        self.choose_button = QPushButton("选择图片")
        self.choose_button.clicked.connect(self.choose_image)
        self.platform_combo = NoWheelComboBox()
        for label, value in (
            ("1688", "1688"), ("AliExpress", "aliexpress"), ("Alibaba", "alibaba"),
            ("Amazon", "amazon"), ("Coupang", "coupang"), ("Domeggook", "domeggook"),
            ("Naver", "naver"), ("Ozon", "ozon"), ("Rakuten", "rakuten"),
            ("Shopee", "shopee"), ("Target", "target"), ("TikTok", "tiktok"),
            ("Tokopedia", "tokopedia"), ("Wildberries", "wildberries"),
            ("Yahoo JP", "yahoo-jp"), ("Yandex", "yandex"),
        ):
            self.platform_combo.addItem(label, value)
        self.search_button = PrimaryPushButton("开始搜图")
        self.search_button.setObjectName("PrimaryButton")
        self.search_button.clicked.connect(self.search_by_image)
        self.search_button.setEnabled(False)

        right = QVBoxLayout()
        right.addWidget(self.image_label)
        row = QHBoxLayout()
        row.addWidget(self.choose_button)
        row.addWidget(QLabel("目标平台"))
        row.addWidget(self.platform_combo)
        row.addWidget(self.search_button)
        row.addStretch(1)
        right.addLayout(row)
        right.addStretch(1)
        top_layout.addWidget(self.preview_label)
        top_layout.addLayout(right, 1)
        layout.addWidget(top)

        self.result_label = QLabel("请选择图片并搜索")
        layout.addWidget(self.result_label)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["选中", "图片", "序号", "平台", "商品ID", "商品名称", "价格", "销量/评分", "链接"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 56)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 72)
        self.table.setColumnWidth(3, 96)
        self.table.setColumnWidth(4, 140)
        self.table.setColumnWidth(6, 90)
        self.table.setColumnWidth(7, 120)
        self.table.verticalHeader().setDefaultSectionSize(140)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_table_menu)
        layout.addWidget(self.table, 1)
        return tab

    def build_ai_settings_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        self.add_page_header(layout, "AI设置", "配置原创图生成平台、模型与 Token，并可先用本地图片测试生图效果。")

        config_panel = ElevatedCardWidget()
        config_panel.setObjectName("Panel")
        config_layout = QGridLayout(config_panel)
        config_layout.setHorizontalSpacing(10)
        config_layout.setVerticalSpacing(10)

        self.ai_provider_combo = NoWheelComboBox()
        for provider_key, provider_config in AI_PROVIDER_CONFIGS.items():
            self.ai_provider_combo.addItem(provider_config["label"], provider_key)
        self.ai_chat_provider_combo = NoWheelComboBox()
        for provider_key, provider_config in AI_PROVIDER_CONFIGS.items():
            self.ai_chat_provider_combo.addItem(provider_config["label"], provider_key)
        self.ai_model_edit = self.create_model_combo("gpt-image-2", "例如: gpt-image-2、gpt-image-2-4k")
        self.ai_chat_model_edit = self.create_model_combo("gpt-5.5", "例如: gpt-5.5、gpt-5.5-mini")
        self.ai_token_edit = QLineEdit()
        self.ai_token_edit.setPlaceholderText("所有 AI 生成平台均必填")
        self.ai_token_edit.setEchoMode(QLineEdit.Password)
        self.ai_chat_token_edit = QLineEdit()
        self.ai_chat_token_edit.setPlaceholderText("对话平台 Token")
        self.ai_chat_token_edit.setEchoMode(QLineEdit.Password)
        self.ai_model_fetch_button = QPushButton("获取模型列表")
        self.ai_model_fetch_button.clicked.connect(lambda: self.fetch_ai_model_list("image"))
        self.ai_chat_model_fetch_button = QPushButton("获取模型列表")
        self.ai_chat_model_fetch_button.clicked.connect(lambda: self.fetch_ai_model_list("chat"))
        self.ai_model_status_label = QLabel("可手动输入模型名")
        self.ai_chat_model_status_label = QLabel("可手动输入模型名")
        self.ai_generate_image_checkbox = QCheckBox("AI生成商品图片")
        self.ai_generate_image_checkbox.setChecked(True)
        self.ai_generate_title_checkbox = QCheckBox("AI生成商品标题")
        self.ai_generate_title_checkbox.setChecked(True)
        self.ai_generate_prompt_checkbox = QCheckBox("AI生成图片 PROMPT")
        self.ai_generate_prompt_checkbox.setChecked(True)
        self.ai_generate_image_hint = QLabel("关闭后跳过 AI 生图，直接上传实拍图库「产品图」文件夹图片")
        self.ai_generate_image_hint.setObjectName("HintLabel")

        config_layout.addWidget(QLabel("图片平台"), 0, 0)
        config_layout.addWidget(self.ai_provider_combo, 0, 1)
        config_layout.addWidget(QLabel("图片 Token"), 0, 2)
        config_layout.addWidget(self.ai_token_edit, 0, 3)
        config_layout.addWidget(QLabel("图片模型"), 1, 0)
        config_layout.addWidget(self.ai_model_edit, 1, 1)
        config_layout.addWidget(self.ai_model_fetch_button, 1, 2)
        config_layout.addWidget(self.ai_model_status_label, 1, 3)
        config_layout.addWidget(QLabel("对话平台"), 2, 0)
        config_layout.addWidget(self.ai_chat_provider_combo, 2, 1)
        config_layout.addWidget(QLabel("对话 Token"), 2, 2)
        config_layout.addWidget(self.ai_chat_token_edit, 2, 3)
        config_layout.addWidget(QLabel("对话模型"), 3, 0)
        config_layout.addWidget(self.ai_chat_model_edit, 3, 1)
        config_layout.addWidget(self.ai_chat_model_fetch_button, 3, 2)
        config_layout.addWidget(self.ai_chat_model_status_label, 3, 3)
        config_layout.addWidget(self.ai_generate_title_checkbox, 4, 0, 1, 2)
        config_layout.addWidget(self.ai_generate_prompt_checkbox, 4, 2, 1, 2)
        config_layout.addWidget(self.ai_generate_image_checkbox, 5, 0, 1, 2)
        config_layout.addWidget(self.ai_generate_image_hint, 5, 2, 1, 2)
        layout.addWidget(config_panel)

        test_panel = ElevatedCardWidget()
        test_panel.setObjectName("Panel")
        test_layout = QGridLayout(test_panel)
        test_layout.setHorizontalSpacing(10)
        test_layout.setVerticalSpacing(10)

        self.ai_test_preview_label = QLabel("未选择\n测试图片")
        self.ai_test_preview_label.setObjectName("ImagePreview")
        self.ai_test_preview_label.setAlignment(Qt.AlignCenter)
        self.ai_test_preview_label.setFixedSize(132, 132)
        self.ai_test_image_label = QLabel("未选择测试图片")
        self.ai_test_product_name_edit = QLineEdit()
        self.ai_test_product_name_edit.setPlaceholderText("可选，用于替换 PROMPT 中的商品名称")
        self.ai_test_choose_button = QPushButton("导入测试图片")
        self.ai_test_choose_button.clicked.connect(self.choose_ai_test_image)
        self.ai_test_button = PrimaryPushButton("测试生图")
        self.ai_test_button.setObjectName("PrimaryButton")
        self.ai_test_button.setEnabled(False)
        self.ai_test_button.clicked.connect(self.start_ai_image_test)
        self.ai_test_status_label = QLabel("导入图片后可测试当前 AI 配置")
        self.ai_test_result_label = QLabel("测试结果预览")
        self.ai_test_result_label.setObjectName("ResultImage")
        self.ai_test_result_label.setAlignment(Qt.AlignCenter)
        self.ai_test_result_label.setMinimumSize(360, 360)

        test_layout.addWidget(self.ai_test_preview_label, 0, 0, 3, 1)
        test_layout.addWidget(self.ai_test_image_label, 0, 1, 1, 3)
        test_layout.addWidget(QLabel("测试商品名"), 1, 1)
        test_layout.addWidget(self.ai_test_product_name_edit, 1, 2, 1, 2)
        test_layout.addWidget(self.ai_test_choose_button, 2, 1)
        test_layout.addWidget(self.ai_test_button, 2, 2)
        test_layout.addWidget(self.ai_test_status_label, 2, 3)
        test_layout.addWidget(self.ai_test_result_label, 3, 0, 1, 4)
        layout.addWidget(test_panel, 1)
        layout.addStretch(1)
        return tab

    def create_model_combo(self, default_model: str, placeholder: str) -> NoWheelComboBox:
        combo = NoWheelComboBox()
        combo.setEditable(True)
        combo.addItem(default_model)
        combo.setPlaceholderText(placeholder)
        return combo

    def build_settings_tab(self) -> QWidget:
        tab = QWidget()
        outer_layout = QVBoxLayout(tab)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName("settingsContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        self.add_page_header(layout, "上架设置", "集中维护店铺、类目、商品属性、包装、供方和证书配置。")
        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(10)

        self.product_root_edit = QLineEdit()
        self.real_photo_root_edit = QLineEdit()
        self.real_photo_status_label = QLabel("尚未扫描实拍图目录")
        self.real_photo_config_table = QTableWidget(0, 11)
        self.real_photo_config_table.setHorizontalHeaderLabels(
            ["商品", "变体数", "重量(g)", "长", "宽", "高", "件数", "包装类型", "供方货号", "证书名称", "证书上传"]
        )
        self.real_photo_config_table.horizontalHeader().setStretchLastSection(True)
        self.real_photo_config_table.setMinimumHeight(180)
        self.real_photo_config_table.setVisible(False)
        self.cookie_edit = QLineEdit()
        self.common_mark_image_edit = QLineEdit()
        self.viewport_width_edit = QLineEdit(str(VIEWPORT_WIDTH))
        self.viewport_height_edit = QLineEdit(str(VIEWPORT_HEIGHT))
        self.upload_rounds_edit = QLineEdit("1")
        self.store_combo = NoWheelComboBox()
        self.store_combo.addItems(STORE_TYPE_OPTIONS)
        self.store_combo.currentTextChanged.connect(self.on_store_changed)
        self.opportunity_combo = NoWheelComboBox()
        self.opportunity_combo.addItems(OPPORTUNITY_TAB_OPTIONS)
        self.publish_category_edit = QLineEdit()

        self.add_path_row(form, 0, "实拍图目录", self.real_photo_root_edit, self.choose_real_photo_root)
        form.addWidget(self.real_photo_status_label, 1, 1, 1, 3)
        self.add_path_row(form, 2, "Cookie 文件", self.cookie_edit, self.choose_cookie_file)
        self.add_path_row(form, 3, "公共标图", self.common_mark_image_edit, self.choose_common_mark_image)
        form.addWidget(QLabel("浏览器宽度"), 4, 0)
        form.addWidget(self.viewport_width_edit, 4, 1)
        form.addWidget(QLabel("浏览器高度"), 4, 2)
        form.addWidget(self.viewport_height_edit, 4, 3)
        form.addWidget(QLabel("上传轮数"), 5, 0)
        form.addWidget(self.upload_rounds_edit, 5, 1)
        form.addWidget(QLabel("店铺类型"), 6, 0)
        form.addWidget(self.store_combo, 6, 1)
        form.addWidget(QLabel("机会页签"), 6, 2)
        form.addWidget(self.opportunity_combo, 6, 3)
        form.addWidget(QLabel("发布类目路径"), 7, 0)
        form.addWidget(self.publish_category_edit, 7, 1, 1, 3)
        layout.addLayout(form)

        self.category_frame = QFrame()
        self.category_layout = QGridLayout(self.category_frame)
        self.category_layout.setContentsMargins(0, 12, 0, 0)
        layout.addWidget(QLabel("机会页类目"))
        layout.addWidget(self.category_frame)
        layout.addWidget(self.build_product_config_panel())
        layout.addStretch(1)
        scroll.setWidget(content)
        outer_layout.addWidget(scroll)
        return tab

    def build_product_config_panel(self) -> QWidget:
        panel = ElevatedCardWidget()
        panel.setObjectName("Panel")
        layout = QGridLayout(panel)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(8)
        layout.setColumnMinimumWidth(0, 92)
        layout.setColumnMinimumWidth(2, 92)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)

        self.real_photo_product_combo = NoWheelComboBox()
        self.real_photo_product_combo.currentTextChanged.connect(self.on_real_photo_product_changed)
        self.real_photo_upload_enabled_checkbox = QCheckBox("启用当前商品上传")
        self.real_photo_upload_enabled_checkbox.setChecked(True)
        self.title_source_combo = NoWheelComboBox()
        self.title_source_combo.addItem("使用自定义标题", "custom")
        self.title_source_combo.addItem("使用勾选商品名称", "goods_name")
        self.title_source_combo.addItem("使用 AI 生成标题", "ai")
        self.product_title_edit = QLineEdit(DEFAULT_PRODUCT_TITLE)
        self.attr_sensitive_edit = QLineEdit("其他")
        self.attr_age_edit = QLineEdit("3岁以上")
        self.attr_tariff_edit = QLineEdit("解压玩具")
        self.attr_material_edit = QLineEdit("TPR")
        self.attr_other_material_edit = QLineEdit("")
        self.attr_composition_value_edit = QLineEdit("PU")
        self.attr_composition_ratio_edit = QLineEdit("100")
        self.style_edit = QLineEdit("")
        self.colors_edit = QLineEdit("粉红色,白色,蓝色")
        self.package_weight_edit = QLineEdit("130")
        self.package_length_edit = QLineEdit("6")
        self.package_width_edit = QLineEdit("6")
        self.package_height_edit = QLineEdit("6")
        self.package_unit_edit = QLineEdit("cm")
        self.package_type_edit = QLineEdit("软包装+硬物")
        self.supplier_price_min_edit = QLineEdit("50")
        self.supplier_price_max_edit = QLineEdit("100")
        self.supplier_stock_edit = QLineEdit("5000")
        self.supplier_piece_type_edit = QLineEdit("单品")
        self.supplier_code_edit = QLineEdit("")
        self.certificate_enabled_combo = NoWheelComboBox()
        self.certificate_enabled_combo.addItem("启用证书上传", True)
        self.certificate_enabled_combo.addItem("关闭证书上传", False)
        self.certificate_edits: dict[str, QLineEdit] = {}

        row = 0
        layout.addWidget(QLabel("当前商品"), row, 0)
        layout.addWidget(self.real_photo_product_combo, row, 1, 1, 2)
        layout.addWidget(self.real_photo_upload_enabled_checkbox, row, 3)
        row += 1
        layout.addWidget(QLabel("商品配置"), row, 0)
        save_button = QPushButton("保存到 app_settings.json")
        save_button.clicked.connect(self.save_named_product_config)
        layout.addWidget(save_button, row, 2, 1, 2)

        row += 1
        layout.addWidget(QLabel("标题来源"), row, 0)
        layout.addWidget(self.title_source_combo, row, 1)
        layout.addWidget(QLabel("自定义标题"), row, 2)
        layout.addWidget(self.product_title_edit, row, 3)

        fields = [
            ("敏感类别", self.attr_sensitive_edit),
            ("适用年龄", self.attr_age_edit),
            ("关税种类", self.attr_tariff_edit),
            ("材质", self.attr_material_edit),
            ("次要材质", self.attr_other_material_edit),
            ("成分值", self.attr_composition_value_edit),
            ("成分比例", self.attr_composition_ratio_edit),
            ("款式", self.style_edit),
            ("颜色配置", self.colors_edit),
            ("重量(g)", self.package_weight_edit),
            ("长", self.package_length_edit),
            ("宽", self.package_width_edit),
            ("高", self.package_height_edit),
            ("单位", self.package_unit_edit),
            ("包装类型", self.package_type_edit),
            ("最低价", self.supplier_price_min_edit),
            ("最高价", self.supplier_price_max_edit),
            ("库存", self.supplier_stock_edit),
            ("件数", self.supplier_piece_type_edit),
            ("供方货号", self.supplier_code_edit),
        ]
        for index, (label, edit) in enumerate(fields):
            row += 1 if index % 2 == 0 else 0
            column = 0 if index % 2 == 0 else 2
            layout.addWidget(QLabel(label), row, column)
            layout.addWidget(edit, row, column + 1)

        row += 1
        layout.addWidget(QLabel("证书上传"), row, 0)
        layout.addWidget(self.certificate_enabled_combo, row, 1, 1, 3)
        for qualification_name in CONFIGURABLE_QUALIFICATIONS:
            row += 1
            edit = QLineEdit("")
            self.certificate_edits[qualification_name] = edit
            layout.addWidget(QLabel(qualification_name), row, 0)
            layout.addWidget(edit, row, 1, 1, 3)
        return panel

    def build_run_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        self.add_page_header(layout, "执行中心", "启动生成与上架流程，并查看每一步运行记录。")
        row = QHBoxLayout()
        self.start_button = PrimaryPushButton("开始生成并上架")
        self.start_button.setObjectName("PrimaryButton")
        self.start_button.clicked.connect(self.start_publish)
        self.pause_button = QPushButton("暂停运行")
        self.pause_button.clicked.connect(self.toggle_pause)
        self.pause_button.setEnabled(False)
        self.stop_button = QPushButton("停止运行")
        self.stop_button.setObjectName("DangerButton")
        self.stop_button.clicked.connect(self.stop_publish)
        self.stop_button.setEnabled(False)
        row.addWidget(self.start_button)
        row.addWidget(self.pause_button)
        row.addWidget(self.stop_button)
        row.addStretch(1)
        self.status_label = QLabel("就绪")
        row.addWidget(self.status_label)
        layout.addLayout(row)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        layout.addWidget(self.log_box, 1)
        return tab

    def add_page_header(self, layout: QVBoxLayout, title: str, subtitle: str) -> None:
        title_label = QLabel(title)
        title_label.setObjectName("PageTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("PageSubtitle")
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)

    def add_path_row(self, layout: QGridLayout, row: int, label: str, edit: QLineEdit, callback) -> None:
        layout.addWidget(QLabel(label), row, 0)
        layout.addWidget(edit, row, 1, 1, 2)
        button = QPushButton("选择")
        button.clicked.connect(callback)
        layout.addWidget(button, row, 3)

    def apply_styles(self) -> None:
        arrow_path = (Path(__file__).with_name("combo_arrow.svg")).as_posix()
        self.setStyleSheet(
            """
            QWidget {
                font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI";
                font-size: 13px;
                color: #e5e7eb;
            }
            QMainWindow, QTabWidget::pane {
                background: #111827;
            }
            QWidget#searchInterface, QWidget#aiInterface,
            QWidget#settingsInterface, QWidget#runInterface,
            QWidget#settingsContent {
                background: #111827;
            }
            QTabWidget::pane {
                border: none;
                top: -1px;
            }
            QTabBar::tab {
                background: transparent;
                color: #9ca3af;
                padding: 12px 20px;
                margin: 0 3px 0 0;
                border: none;
                border-bottom: 2px solid transparent;
                font-weight: 600;
            }
            QTabBar::tab:selected {
                color: #60a5fa;
                border-bottom-color: #2e90fa;
                background: #1f2937;
            }
            QTabBar::tab:hover:!selected {
                color: #d1d5db;
                background: #1f2937;
            }
            QScrollArea {
                background: #111827;
                border: none;
            }
            QScrollArea > QWidget > QWidget {
                background: #111827;
            }
            QFrame#Panel {
                background: #1f2937;
                border: 1px solid #374151;
                border-radius: 10px;
            }
            QLabel {
                color: #d1d5db;
            }
            QLabel#PageTitle {
                color: #f9fafb;
                font-size: 24px;
                font-weight: 800;
                padding: 2px 0 0 0;
            }
            QLabel#PageSubtitle {
                color: #9ca3af;
                font-size: 13px;
                padding: 0 0 6px 0;
            }
            QLabel#ImagePreview {
                background: #111827;
                border: 1px dashed #4b5563;
                border-radius: 8px;
                color: #9ca3af;
                font-weight: 600;
            }
            QLabel#ResultImage {
                background: #111827;
                border: 1px solid #374151;
                border-radius: 8px;
                color: #9ca3af;
                font-weight: 600;
            }
            QLineEdit, QComboBox, QTextEdit {
                background: #111827;
                border: 1px solid #4b5563;
                border-radius: 8px;
                padding: 8px 10px;
                color: #e5e7eb;
                selection-background-color: #1d4ed8;
            }
            QLineEdit, QComboBox {
                min-height: 20px;
            }
            QLineEdit:focus, QComboBox:focus, QTextEdit:focus {
                border: 1px solid #60a5fa;
                background: #172033;
            }
            QComboBox::drop-down {
                border: none;
                width: 28px;
            }
            QComboBox::down-arrow {
                image: url(__COMBO_ARROW__);
                width: 12px;
                height: 8px;
            }
            QPushButton {
                min-height: 20px;
                border-radius: 8px;
                padding: 8px 15px;
                font-weight: 700;
                background: #273449;
                color: #e5e7eb;
                border: 1px solid #4b5563;
            }
            QPushButton:hover {
                background: #374151;
                border-color: #6b7280;
            }
            QPushButton:pressed {
                background: #1f2937;
            }
            QPushButton:disabled {
                background: #1f2937;
                color: #6b7280;
                border-color: #374151;
            }
            QPushButton#PrimaryButton {
                background: #1570ef;
                color: #ffffff;
                border: 1px solid #1570ef;
            }
            QPushButton#PrimaryButton:hover {
                background: #175cd3;
                border-color: #175cd3;
            }
            QPushButton#PrimaryButton:disabled {
                background: #1e40af;
                color: #dbeafe;
                border-color: #1e40af;
            }
            QPushButton#DangerButton {
                color: #fca5a5;
                border-color: #7f1d1d;
                background: #2a1518;
            }
            QPushButton#DangerButton:hover {
                background: #451a1a;
                border-color: #b91c1c;
            }
            QTableWidget {
                background: #1f2937;
                border: 1px solid #374151;
                border-radius: 10px;
                gridline-color: #374151;
                selection-background-color: #1e3a8a;
                selection-color: #f9fafb;
                alternate-background-color: #172033;
            }
            QTableWidget::item {
                padding: 6px;
            }
            QHeaderView::section {
                background: #273449;
                color: #d1d5db;
                border: none;
                border-bottom: 1px solid #374151;
                padding: 10px 8px;
                font-weight: 800;
            }
            QTextEdit {
                background: #0b1220;
                color: #dbeafe;
                border: 1px solid #263449;
                font-family: "Consolas", "Microsoft YaHei UI";
            }
            QAbstractItemView {
                background: #1f2937;
                color: #e5e7eb;
                border: 1px solid #4b5563;
                selection-background-color: #1e3a8a;
                selection-color: #dbeafe;
                outline: none;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 10px;
                margin: 2px;
            }
            QScrollBar::handle:vertical {
                background: #4b5563;
                min-height: 32px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #6b7280;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
                height: 0px;
            }
            """.replace("__COMBO_ARROW__", arrow_path)
        )

    def choose_image(self) -> None:
        image_path, _ = QFileDialog.getOpenFileName(self, "选择商品图片", "", "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*.*)")
        if not image_path:
            return
        self.selected_image_path = image_path
        self.image_label.setText(image_path)
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            self.preview_label.setText("预览\n失败")
        else:
            self.preview_label.setText("")
            self.preview_label.setPixmap(pixmap.scaled(112, 112, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.search_button.setEnabled(True)

    def choose_ai_test_image(self) -> None:
        image_path, _ = QFileDialog.getOpenFileName(self, "导入测试图片", "", "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*.*)")
        if not image_path:
            return
        self.ai_test_image_path = image_path
        self.ai_test_image_label.setText(image_path)
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            self.ai_test_preview_label.setText("预览\n失败")
        else:
            self.ai_test_preview_label.setText("")
            self.ai_test_preview_label.setPixmap(pixmap.scaled(112, 112, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.ai_test_button.setEnabled(True)
        self.ai_test_status_label.setText("已导入测试图片")

    def collect_ai_settings(self) -> tuple[str, str, str]:
        ai_provider = self.ai_provider_combo.currentData() or "geeknow"
        ai_model = self.ai_model_edit.currentText().strip() or "gpt-image-2"
        ai_token = self.ai_token_edit.text().strip()
        if not ai_token:
            provider_label = AI_PROVIDER_CONFIGS.get(ai_provider, AI_PROVIDER_CONFIGS["geeknow"])["label"]
            raise ValueError(f"请填写 {provider_label} AI Token")
        return ai_provider, ai_model, ai_token

    def fetch_ai_model_list(self, target: str = "image") -> None:
        is_chat = target == "chat"
        provider_combo = self.ai_chat_provider_combo if is_chat else self.ai_provider_combo
        token_edit = self.ai_chat_token_edit if is_chat else self.ai_token_edit
        fetch_button = self.ai_chat_model_fetch_button if is_chat else self.ai_model_fetch_button
        status_label = self.ai_chat_model_status_label if is_chat else self.ai_model_status_label
        provider = provider_combo.currentData() or "geeknow"
        token = token_edit.text().strip()
        if not token:
            provider_label = AI_PROVIDER_CONFIGS.get(provider, AI_PROVIDER_CONFIGS["geeknow"])["label"]
            QMessageBox.warning(self, "提示", f"请先填写 {provider_label} Token")
            return
        fetch_button.setEnabled(False)
        status_label.setText("正在获取模型列表...")
        self.ai_model_worker = AiModelListWorker(provider, token)
        self.ai_model_worker.finished.connect(
            lambda models, model_target=target: self.show_ai_model_list(models, model_target)
        )
        self.ai_model_worker.failed.connect(
            lambda message, model_target=target: self.show_ai_model_list_error(message, model_target)
        )
        self.ai_model_worker.start()

    def show_ai_model_list(self, models: list, target: str = "image") -> None:
        if target == "chat":
            self.set_model_choices(self.ai_chat_model_edit, models, "gpt-5.5")
            self.ai_chat_model_status_label.setText(
                f"已获取 {len(models)} 个模型" if models else "未获取到模型，可继续手动输入"
            )
        else:
            self.set_model_choices(self.ai_model_edit, models, "gpt-image-2")
            self.ai_model_status_label.setText(
                f"已获取 {len(models)} 个模型" if models else "未获取到模型，可继续手动输入"
            )
        self.ai_chat_model_fetch_button.setEnabled(True)
        self.ai_model_fetch_button.setEnabled(True)
        self.ai_model_worker = None

    @staticmethod
    def set_model_choices(combo: NoWheelComboBox, models: list, fallback: str) -> None:
        current_model = combo.currentText().strip()
        combo.clear()
        for model in models:
            combo.addItem(str(model))
        selected_model = current_model or fallback
        index = combo.findText(selected_model)
        if index >= 0:
            combo.setCurrentIndex(index)
        else:
            combo.insertItem(0, selected_model)
            combo.setCurrentIndex(0)

    def show_ai_model_list_error(self, message: str, target: str = "image") -> None:
        status_label = self.ai_chat_model_status_label if target == "chat" else self.ai_model_status_label
        status_label.setText("获取模型列表失败")
        self.ai_chat_model_fetch_button.setEnabled(True)
        self.ai_model_fetch_button.setEnabled(True)
        self.ai_model_worker = None
        QMessageBox.critical(self, "获取模型列表失败", message)

    def start_ai_image_test(self) -> None:
        if not self.ai_test_image_path:
            QMessageBox.warning(self, "提示", "请先导入测试图片")
            return
        try:
            ai_provider, ai_model, ai_token = self.collect_ai_settings()
        except Exception as error:
            QMessageBox.critical(self, "配置错误", str(error))
            return
        self.save_settings()
        self.set_ai_test_running(True)
        self.ai_test_status_label.setText("正在调用 AI 生成测试图...")
        self.ai_test_result_label.setText("生成中")
        self.ai_test_result_label.setPixmap(QPixmap())
        self.ai_test_worker = AiImageTestWorker(
            self.ai_test_image_path,
            ai_provider,
            ai_model,
            ai_token,
            self.ai_test_product_name_edit.text().strip(),
        )
        self.ai_test_worker.finished.connect(self.finish_ai_image_test)
        self.ai_test_worker.failed.connect(self.fail_ai_image_test)
        self.ai_test_worker.start()

    def finish_ai_image_test(self, image_path: str, output_dir: str) -> None:
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            self.ai_test_result_label.setText(f"测试图已保存: {image_path}")
        else:
            self.ai_test_result_label.setText("")
            self.ai_test_result_label.setPixmap(pixmap.scaled(520, 520, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.ai_test_status_label.setText(f"测试完成，已保存到 {output_dir}")
        self.set_ai_test_running(False)
        self.ai_test_worker = None

    def fail_ai_image_test(self, message: str) -> None:
        self.ai_test_status_label.setText("测试失败")
        self.ai_test_result_label.setText("测试失败")
        self.set_ai_test_running(False)
        self.ai_test_worker = None
        QMessageBox.critical(self, "测试失败", message)

    def set_ai_test_running(self, running: bool) -> None:
        self.ai_test_choose_button.setEnabled(not running)
        self.ai_test_button.setEnabled(not running and bool(self.ai_test_image_path))
        self.ai_provider_combo.setEnabled(not running)
        self.ai_chat_provider_combo.setEnabled(not running)
        self.ai_model_edit.setEnabled(not running)
        self.ai_chat_model_edit.setEnabled(not running)
        self.ai_token_edit.setEnabled(not running)
        self.ai_chat_token_edit.setEnabled(not running)
        self.ai_model_fetch_button.setEnabled(not running)
        self.ai_chat_model_fetch_button.setEnabled(not running)

    def search_by_image(self) -> None:
        if not self.selected_image_path:
            QMessageBox.warning(self, "提示", "请先选择商品图片")
            return
        platform = self.platform_combo.currentData()
        self.search_button.setEnabled(False)
        self.choose_button.setEnabled(False)
        self.result_label.setText(f"正在搜索 {self.platform_combo.currentText()} 商品，最多返回 {DEFAULT_SEARCH_SIZE} 条...")
        self.table.setRowCount(0)
        self.worker = AipriceImageSearchWorker(self.selected_image_path, platform)
        self.worker.finished.connect(self.show_search_results)
        self.worker.failed.connect(self.show_search_error)
        self.worker.start()

    def show_search_results(self, result: dict) -> None:
        goods_list = result.get("list") or []
        self.current_goods_list = goods_list
        self.table.setRowCount(len(goods_list))
        self.thumbnail_workers = []
        for row, goods in enumerate(goods_list):
            self.table.setRowHeight(row, 140)
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            check_item.setCheckState(Qt.Unchecked)
            check_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, check_item)

            image_label = QLabel("加载中")
            image_label.setObjectName("ResultImage")
            image_label.setAlignment(Qt.AlignCenter)
            image_label.setFixedSize(128, 128)
            self.table.setCellWidget(row, 1, image_label)

            values = [
                row + 1,
                get_goods_platform(goods) or self.platform_combo.currentText(),
                get_goods_id(goods),
                get_goods_name(goods),
                get_goods_price(goods),
                get_goods_metric(goods),
                get_goods_url(goods),
            ]
            for column, value in enumerate(values, start=2):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                item.setTextAlignment(Qt.AlignVCenter | (Qt.AlignLeft if column == 5 else Qt.AlignCenter))
                self.table.setItem(row, column, item)

            thumbnail_url = get_goods_thumbnail_url(goods)
            if thumbnail_url:
                image_label.setToolTip(thumbnail_url)
                worker = ThumbnailWorker(row, thumbnail_url)
                worker.loaded.connect(self.show_thumbnail)
                self.thumbnail_workers.append(worker)
                worker.start()
            else:
                image_label.setText("无图")

        self.result_label.setText(f"搜索完成：共找到 {len(goods_list)} 条结果，请勾选要生成并上架的商品")
        self.search_button.setEnabled(bool(self.selected_image_path))
        self.choose_button.setEnabled(True)

    def show_search_error(self, message: str) -> None:
        self.result_label.setText("搜索失败")
        self.search_button.setEnabled(bool(self.selected_image_path))
        self.choose_button.setEnabled(True)
        QMessageBox.critical(self, "搜索失败", message)

    def show_thumbnail(self, row: int, image_bytes: bytes) -> None:
        widget = self.table.cellWidget(row, 1)
        if not isinstance(widget, QLabel):
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(image_bytes):
            widget.setText("预览失败")
            return
        widget.setText("")
        widget.setPixmap(pixmap.scaled(128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def show_table_menu(self, position) -> None:
        row = self.table.rowAt(position.y())
        if row < 0 or row >= len(self.current_goods_list):
            return
        goods = self.current_goods_list[row]
        self.table.selectRow(row)
        menu = QMenu(self)
        open_action = menu.addAction("打开链接")
        action = menu.exec_(self.table.viewport().mapToGlobal(position))
        if action == open_action:
            goods_url = get_goods_url(goods)
            if goods_url:
                webbrowser.open(goods_url)

    def choose_product_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择基础商品资料目录")
        if path:
            self.product_root_edit.setText(path)

    def choose_real_photo_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择实拍图目录")
        if path:
            self.real_photo_root_edit.setText(path)
            self.scan_real_photo_root()

    def scan_real_photo_root(self) -> None:
        root = self.real_photo_root_edit.text().strip()
        if not root:
            self.real_photo_status_label.setText("尚未选择实拍图目录")
            return
        try:
            variants = scan_real_photo_library(root)
            direct_count = sum(1 for item in variants if not item.variant_name)
            variant_count = len(variants) - direct_count
            grouped: dict[str, int] = {}
            for item in variants:
                grouped[item.product_name] = grouped.get(item.product_name, 0) + 1
            saved_configs = self.settings.get("real_photo_configs", {})
            if not isinstance(saved_configs, dict):
                saved_configs = {}
            self.real_photo_product_configs = dict(saved_configs)
            saved_enabled = self.settings.get("real_photo_upload_enabled", {})
            if not isinstance(saved_enabled, dict):
                saved_enabled = {}
            self.real_photo_upload_enabled = {
                product_name: bool(saved_enabled.get(product_name, True))
                for product_name in grouped
            }
            self._real_photo_config_ready = False
            self._active_real_photo_product = ""
            if not getattr(self, "real_photo_default_config", None):
                self.real_photo_default_config = self.build_product_config_from_ui()
            self.real_photo_product_combo.blockSignals(True)
            self.real_photo_product_combo.clear()
            self.real_photo_product_combo.addItems(sorted(grouped))
            self.real_photo_product_combo.blockSignals(False)
            if grouped:
                self.load_real_photo_product_config(self.real_photo_product_combo.currentText())
            self._real_photo_config_ready = True
            self.real_photo_config_table.setRowCount(0)
            for product_name, count in grouped.items():
                row = self.real_photo_config_table.rowCount()
                self.real_photo_config_table.insertRow(row)
                values = saved_configs.get(product_name, {})
                defaults = [
                    product_name,
                    str(count),
                    str(values.get("重量", self.package_weight_edit.text().strip())),
                    str(values.get("长", self.package_length_edit.text().strip())),
                    str(values.get("宽", self.package_width_edit.text().strip())),
                    str(values.get("高", self.package_height_edit.text().strip())),
                    str(values.get("件数", self.supplier_piece_type_edit.text().strip())),
                    str(values.get("包装类型", self.package_type_edit.text().strip())),
                    str(values.get("供方货号", self.supplier_code_edit.text().strip())),
                    str(values.get("证书名称", "")),
                    "",
                ]
                for column, value in enumerate(defaults):
                    self.real_photo_config_table.setItem(row, column, QTableWidgetItem(value))
                certificate_item = self.real_photo_config_table.item(row, 10)
                certificate_item.setFlags(certificate_item.flags() | Qt.ItemIsUserCheckable)
                certificate_item.setCheckState(
                    Qt.Checked if values.get("证书上传", True) else Qt.Unchecked
                )
            self.real_photo_status_label.setText(
                f"已扫描 {len(variants)} 个商品素材单元："
                f"{direct_count} 个普通商品，{variant_count} 个颜色/款式变体"
            )
            self.append_log(
                f"已扫描实拍图目录，共识别 {len(variants)} 个商品素材单元"
            )
        except Exception as error:
            self.real_photo_status_label.setText(f"扫描失败: {error}")

    def collect_real_photo_configs(self) -> dict[str, dict]:
        configs: dict[str, dict] = {}
        for row in range(self.real_photo_config_table.rowCount()):
            name_item = self.real_photo_config_table.item(row, 0)
            if name_item is None:
                continue
            values = [
                self.real_photo_config_table.item(row, column).text().strip()
                for column in range(2, 10)
            ]
            configs[name_item.text().strip()] = {
                "重量": values[0],
                "长": values[1],
                "宽": values[2],
                "高": values[3],
                "件数": values[4],
                "包装类型": values[5],
                "供方货号": values[6],
                "证书名称": values[7],
                "证书上传": self.real_photo_config_table.item(row, 10).checkState() == Qt.Checked,
            }
        return configs

    def save_real_photo_product_config(self) -> None:
        name = getattr(self, "_active_real_photo_product", "").strip()
        if name:
            if not hasattr(self, "real_photo_product_configs"):
                self.real_photo_product_configs = {}
            self.real_photo_product_configs[name] = self.build_product_config_from_ui()
            if not hasattr(self, "real_photo_upload_enabled"):
                self.real_photo_upload_enabled = {}
            self.real_photo_upload_enabled[name] = self.real_photo_upload_enabled_checkbox.isChecked()

    def load_real_photo_product_config(self, product_name: str) -> None:
        if not product_name:
            return
        if getattr(self, "_real_photo_config_ready", False):
            self.save_real_photo_product_config()
        configs = getattr(self, "real_photo_product_configs", {})
        config = configs.get(product_name)
        if isinstance(config, dict) and (
            "商品标题" in config or "必填属性" in config or "包装信息" in config
        ):
            self.apply_product_config_to_ui(config)
        elif isinstance(getattr(self, "real_photo_default_config", None), dict):
            self.apply_product_config_to_ui(self.real_photo_default_config)
        enabled = getattr(self, "real_photo_upload_enabled", {}).get(product_name, True)
        self.real_photo_upload_enabled_checkbox.setChecked(bool(enabled))
        self._active_real_photo_product = product_name

    def on_real_photo_product_changed(self, product_name: str) -> None:
        if not self.is_restoring_settings:
            self.load_real_photo_product_config(product_name)

    def on_real_photo_product_activated(self, index: int) -> None:
        if self.is_restoring_settings or index < 0:
            return
        self.load_real_photo_product_config(self.real_photo_product_combo.itemText(index))

    def choose_cookie_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 Cookie 文件", "", "JSON 文件 (*.json);;所有文件 (*.*)")
        if path:
            self.cookie_edit.setText(path)

    def choose_common_mark_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择公共标图",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*.*)",
        )
        if path:
            self.common_mark_image_edit.setText(path)

    def load_settings(self) -> dict:
        if not os.path.exists(APP_SETTINGS_FILE):
            return {}
        try:
            with open(APP_SETTINGS_FILE, "r", encoding="utf-8") as file:
                settings = json.load(file)
        except Exception:
            return {}
        return settings if isinstance(settings, dict) else {}

    def restore_settings_to_ui(self) -> None:
        self.is_restoring_settings = True
        self.product_root_edit.setText(str(self.settings.get("product_root_dir", DEFAULT_PRODUCT_ROOT_DIR)).strip())
        self.real_photo_root_edit.setText(str(self.settings.get("real_photo_root_dir", "")).strip())
        self.cookie_edit.setText(str(self.settings.get("cookies_file", COOKIES_FILE)).strip() or os.fspath(COOKIES_FILE))
        self.common_mark_image_edit.setText(str(self.settings.get("common_mark_image_file", "")).strip())
        ai_provider = str(self.settings.get("ai_provider", "geeknow"))
        ai_provider_index = self.ai_provider_combo.findData(ai_provider)
        if ai_provider_index >= 0:
            self.ai_provider_combo.setCurrentIndex(ai_provider_index)
        image_provider = str(self.settings.get("ai_image_provider", ai_provider))
        image_provider_index = self.ai_provider_combo.findData(image_provider)
        if image_provider_index >= 0:
            self.ai_provider_combo.setCurrentIndex(image_provider_index)
        chat_provider = str(self.settings.get("ai_chat_provider", "geeknow"))
        chat_provider_index = self.ai_chat_provider_combo.findData(chat_provider)
        if chat_provider_index >= 0:
            self.ai_chat_provider_combo.setCurrentIndex(chat_provider_index)
        image_model = self.settings.get("ai_image_model", self.settings.get("ai_model", "gpt-image-2"))
        self.ai_model_edit.setCurrentText(str(image_model).strip() or "gpt-image-2")
        self.ai_chat_model_edit.setCurrentText(str(self.settings.get("ai_chat_model", "gpt-5.5")).strip() or "gpt-5.5")
        self.ai_token_edit.setText(str(self.settings.get("ai_image_token", self.settings.get("ai_token", ""))).strip())
        self.ai_chat_token_edit.setText(str(self.settings.get("ai_chat_token", "")).strip())
        self.ai_generate_image_checkbox.setChecked(bool(self.settings.get("ai_generate_image", True)))
        self.ai_generate_title_checkbox.setChecked(bool(self.settings.get("ai_generate_title", True)))
        self.ai_generate_prompt_checkbox.setChecked(bool(self.settings.get("ai_generate_prompt", True)))
        self.viewport_width_edit.setText(str(self.settings.get("viewport_width", VIEWPORT_WIDTH)))
        self.viewport_height_edit.setText(str(self.settings.get("viewport_height", VIEWPORT_HEIGHT)))
        self.upload_rounds_edit.setText(str(self.settings.get("upload_rounds", 1)))
        self.opportunity_combo.setCurrentText(str(self.settings.get("opportunity_tab", OPPORTUNITY_TAB_OPTIONS[0])))
        store_type = str(self.settings.get("store_type", TOY_STORE_TYPE))
        if store_type not in STORE_TYPE_OPTIONS:
            store_type = TOY_STORE_TYPE
        self.store_combo.blockSignals(True)
        self.store_combo.setCurrentText(store_type)
        self.store_combo.blockSignals(False)
        self.active_store_type = store_type
        publish_paths = self.settings.get("store_publish_category_paths", {})
        self.publish_category_edit.setText(str(publish_paths.get(store_type, self.settings.get("publish_category_path", ""))).strip())
        self.reload_category_catalog()
        category_paths = self.settings.get("store_category_paths", {})
        requested_path = category_paths.get(store_type, self.settings.get("category_path", []))
        self.refresh_category_selector(requested_path if isinstance(requested_path, list) else [])
        product_config = self.settings.get("product_config")
        if isinstance(product_config, dict):
            self.apply_product_config_to_ui(product_config)
        title_source = str(self.settings.get("title_source", "custom"))
        if title_source in {"custom", "goods_name", "ai"}:
            index = self.title_source_combo.findData(title_source)
            if index >= 0:
                self.title_source_combo.setCurrentIndex(index)
        self.is_restoring_settings = False
        if self.real_photo_root_edit.text().strip():
            self.scan_real_photo_root()

    def save_settings(self) -> None:
        store_category_paths = self.settings.get("store_category_paths", {})
        if not isinstance(store_category_paths, dict):
            store_category_paths = {}
        store_publish_paths = self.settings.get("store_publish_category_paths", {})
        if not isinstance(store_publish_paths, dict):
            store_publish_paths = {}
        store_category_paths[self.active_store_type] = self.get_selected_category_path()
        store_publish_paths[self.active_store_type] = self.publish_category_edit.text().strip()
        self.settings = {
            "product_root_dir": self.real_photo_root_edit.text().strip(),
            "real_photo_root_dir": self.real_photo_root_edit.text().strip(),
            "cookies_file": self.cookie_edit.text().strip(),
            "common_mark_image_file": self.common_mark_image_edit.text().strip(),
            "real_photo_configs": dict(getattr(self, "real_photo_product_configs", {})),
            "real_photo_upload_enabled": dict(getattr(self, "real_photo_upload_enabled", {})),
            "ai_provider": self.ai_provider_combo.currentData(),
            "ai_image_provider": self.ai_provider_combo.currentData(),
            "ai_chat_provider": self.ai_chat_provider_combo.currentData(),
            "ai_model": self.ai_model_edit.currentText().strip() or "gpt-image-2",
            "ai_image_model": self.ai_model_edit.currentText().strip() or "gpt-image-2",
            "ai_chat_model": self.ai_chat_model_edit.currentText().strip() or "gpt-5.5",
            "ai_token": self.ai_token_edit.text().strip(),
            "ai_image_token": self.ai_token_edit.text().strip(),
            "ai_chat_token": self.ai_chat_token_edit.text().strip(),
            "ai_generate_image": self.ai_generate_image_checkbox.isChecked(),
            "ai_generate_title": self.ai_generate_title_checkbox.isChecked(),
            "ai_generate_prompt": self.ai_generate_prompt_checkbox.isChecked(),
            "viewport_width": self.viewport_width_edit.text().strip(),
            "viewport_height": self.viewport_height_edit.text().strip(),
            "upload_rounds": self.upload_rounds_edit.text().strip() or "1",
            "opportunity_tab": self.opportunity_combo.currentText(),
            "store_type": self.store_combo.currentText(),
            "store_category_paths": store_category_paths,
            "store_publish_category_paths": store_publish_paths,
            "category_path": self.get_selected_category_path(),
            "publish_category_path": self.publish_category_edit.text().strip(),
            "title_source": self.title_source_combo.currentData(),
            "product_config": self.build_product_config_from_ui(),
        }
        try:
            with open(APP_SETTINGS_FILE, "w", encoding="utf-8") as file:
                json.dump(self.settings, file, ensure_ascii=False, indent=2)
        except Exception as error:
            self.append_log(f"保存界面设置失败: {error}")

    def get_store_profile(self, store_type: str | None = None) -> StoreProfile:
        return get_store_profile(store_type or self.store_combo.currentText())

    def reload_category_catalog(self) -> None:
        profile = self.get_store_profile(self.active_store_type)
        self.category_catalog = load_category_catalog(
            profile.category_catalog_file,
            use_bundled_catalog=profile.use_bundled_catalog,
            bundled_catalog_file=profile.bundled_catalog_file,
        )

    def on_store_changed(self, store_type: str) -> None:
        if self.is_restoring_settings:
            return
        self.save_settings()
        self.active_store_type = store_type
        self.reload_category_catalog()
        profile = self.get_store_profile(store_type)
        publish_paths = self.settings.get("store_publish_category_paths", {})
        self.publish_category_edit.setText(str(publish_paths.get(store_type, " > ".join(profile.default_publish_category_path))).strip())
        category_paths = self.settings.get("store_category_paths", {})
        self.refresh_category_selector(category_paths.get(store_type, list(profile.default_category_path)))

    def refresh_category_selector(self, requested_path: list[str] | None = None) -> None:
        while self.category_layout.count():
            item = self.category_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.category_combos = []
        if not self.category_catalog:
            self.category_layout.addWidget(QLabel("当前店铺尚未同步类目"), 0, 0)
            return

        selected_path = resolve_category_path(self.category_catalog, requested_path or [])
        current_level = self.category_catalog
        level_index = 0
        while current_level:
            names = tuple(current_level.keys())
            values = names if level_index == 0 else (CATEGORY_PATH_END_TEXT, *names)
            selected_name = selected_path[level_index] if level_index < len(selected_path) else values[0]
            combo = NoWheelComboBox()
            combo.addItems(values)
            combo.setCurrentText(selected_name)
            combo.currentIndexChanged.connect(lambda _index, lvl=level_index: self.on_category_selected(lvl))
            self.category_combos.append(combo)
            row = level_index // 2
            column = (level_index % 2) * 2
            self.category_layout.addWidget(QLabel(f"第 {level_index + 1} 级类目"), row, column)
            self.category_layout.addWidget(combo, row, column + 1)
            if selected_name == CATEGORY_PATH_END_TEXT:
                break
            current_level = current_level[selected_name]
            level_index += 1

    def on_category_selected(self, level: int) -> None:
        self.refresh_category_selector(self.get_selected_category_path()[: level + 1])

    def get_selected_category_path(self) -> list[str]:
        path = []
        for combo in self.category_combos:
            name = combo.currentText().strip()
            if not name or name == CATEGORY_PATH_END_TEXT:
                break
            path.append(name)
        return path

    def get_selected_goods(self) -> list[dict]:
        selected = []
        for row, goods in enumerate(self.current_goods_list):
            item = self.table.item(row, 0)
            if item is not None and item.checkState() == Qt.Checked:
                copied = dict(goods)
                image_widget = self.table.cellWidget(row, 1)
                if isinstance(image_widget, QLabel):
                    copied["_display_image_url"] = normalize_url(image_widget.toolTip())
                selected.append(copied)
        return selected

    def collect_publish_settings(self) -> dict:
        product_root_dir = self.real_photo_root_edit.text().strip()
        common_mark_image_file = self.common_mark_image_edit.text().strip()
        generate_image = self.ai_generate_image_checkbox.isChecked()
        if generate_image:
            ai_provider, ai_model, ai_token = self.collect_ai_settings()
        else:
            ai_provider = self.ai_provider_combo.currentData() or "geeknow"
            ai_model = self.ai_model_edit.currentText().strip() or "gpt-image-2"
            ai_token = self.ai_token_edit.text().strip()
        chat_provider = self.ai_chat_provider_combo.currentData() or "geeknow"
        chat_model = self.ai_chat_model_edit.currentText().strip() or "gpt-5.5"
        chat_token = self.ai_chat_token_edit.text().strip()
        generate_title = self.ai_generate_title_checkbox.isChecked()
        generate_prompt = self.ai_generate_prompt_checkbox.isChecked() and generate_image
        if (generate_title or generate_prompt) and not chat_token:
            raise ValueError("请填写对话模型 Token，或关闭 AI 标题/PROMPT 生成")
        category_path = tuple(self.get_selected_category_path())
        publish_category_path = parse_category_path(self.publish_category_edit.text())
        if not product_root_dir:
            raise ValueError("请先选择实拍图目录")
        if not category_path:
            raise ValueError("请至少选择一级机会页类目")
        if not publish_category_path:
            raise ValueError("请填写发布类目路径")
        width = int(self.viewport_width_edit.text().strip())
        height = int(self.viewport_height_edit.text().strip())
        upload_rounds = int(self.upload_rounds_edit.text().strip() or "1")
        if upload_rounds < 1 or upload_rounds > 100:
            raise ValueError("上传轮数必须在 1 到 100 之间")
        if width < 800 or height < 600:
            raise ValueError("浏览器宽高不能小于 800 x 600")
        if common_mark_image_file and not os.path.isfile(common_mark_image_file):
            raise ValueError(f"公共标图不存在: {common_mark_image_file}")
        variants = scan_real_photo_library(product_root_dir)
        if not variants:
            raise ValueError("实拍图目录中没有可用商品")
        self.save_real_photo_product_config()
        product_config = self.build_product_config_from_ui()
        enabled_products = {
            product_name
            for product_name, enabled in getattr(self, "real_photo_upload_enabled", {}).items()
            if enabled
        }
        return {
            "product_root_dir": product_root_dir,
            "cookies_file": self.cookie_edit.text().strip(),
            "common_mark_image_file": common_mark_image_file,
            "ai_provider": ai_provider,
            "ai_model": ai_model,
            "ai_token": ai_token,
            "ai_image_provider": ai_provider,
            "ai_image_model": ai_model,
            "ai_image_token": ai_token,
            "ai_chat_provider": chat_provider,
            "ai_chat_model": chat_model,
            "ai_chat_token": chat_token,
            "ai_generate_title": generate_title,
            "ai_generate_prompt": generate_prompt,
            "ai_generate_image": generate_image,
            "viewport_width": width,
            "viewport_height": height,
            "upload_rounds": upload_rounds,
            "opportunity_tab": self.opportunity_combo.currentText(),
            "category_path": category_path,
            "publish_category_path": publish_category_path,
            "title_source": "ai" if generate_title else self.title_source_combo.currentData(),
            "product_config": product_config,
            "real_photo_configs": dict(getattr(self, "real_photo_product_configs", {})),
            "enabled_real_photo_products": sorted(enabled_products),
        }

    def build_product_config_from_ui(self) -> dict:
        attributes = {
            "敏感类别": self.attr_sensitive_edit.text().strip(),
            "适用年龄": self.attr_age_edit.text().strip(),
            "关税种类": self.attr_tariff_edit.text().strip(),
            "材质": self.attr_material_edit.text().strip(),
            "成分": {
                "值": self.attr_composition_value_edit.text().strip(),
                "比例": self.attr_composition_ratio_edit.text().strip(),
            },
        }
        other_material = self.attr_other_material_edit.text().strip()
        if other_material:
            attributes["次要材质"] = other_material

        certificates = {
            CERTIFICATE_ENABLED_KEY: certificate_upload_enabled_by_default(
                self.certificate_enabled_combo.currentData()
            )
        }
        for qualification_name, edit in self.certificate_edits.items():
            certificates[qualification_name] = edit.text().strip()

        return {
            "商品标题": self.product_title_edit.text().strip() or DEFAULT_PRODUCT_TITLE,
            "必填属性": attributes,
            "包装信息": {
                "含包装重量(g)": self.package_weight_edit.text().strip(),
                "含包装尺寸": {
                    "长": self.package_length_edit.text().strip(),
                    "宽": self.package_width_edit.text().strip(),
                    "高": self.package_height_edit.text().strip(),
                },
                "单位": self.package_unit_edit.text().strip(),
                "包装类型": self.package_type_edit.text().strip(),
            },
            "供方信息": {
                "价格范围": {
                    "最低": int(self.supplier_price_min_edit.text().strip() or 50),
                    "最高": int(self.supplier_price_max_edit.text().strip() or 100),
                },
                "库存": self.supplier_stock_edit.text().strip(),
                "件数": self.supplier_piece_type_edit.text().strip(),
                "供方货号": self.supplier_code_edit.text().strip(),
            },
            "款式": self.style_edit.text().strip(),
            "颜色配置": [
                color.strip()
                for color in re.split(r"[,，\n]", self.colors_edit.text())
                if color.strip()
            ],
            "证书列表": certificates,
        }

    def apply_product_config_to_ui(self, config: dict) -> None:
        self.product_title_edit.setText(str(config.get("商品标题", DEFAULT_PRODUCT_TITLE)))
        attributes = config.get("必填属性", {})
        if isinstance(attributes, dict):
            self.attr_sensitive_edit.setText(str(attributes.get("敏感类别", "")))
            self.attr_age_edit.setText(str(attributes.get("适用年龄", "")))
            self.attr_tariff_edit.setText(str(attributes.get("关税种类", "")))
            self.attr_material_edit.setText(str(attributes.get("材质", "")))
            self.attr_other_material_edit.setText(str(attributes.get("次要材质", "")))
            composition = attributes.get("成分", {})
            if isinstance(composition, dict):
                self.attr_composition_value_edit.setText(str(composition.get("值", "")))
                self.attr_composition_ratio_edit.setText(str(composition.get("比例", "")))
        package_info = config.get("包装信息", {})
        if isinstance(package_info, dict):
            self.package_weight_edit.setText(str(package_info.get("含包装重量(g)", "")))
            dimensions = package_info.get("含包装尺寸", {})
            if isinstance(dimensions, dict):
                self.package_length_edit.setText(str(dimensions.get("长", "")))
                self.package_width_edit.setText(str(dimensions.get("宽", "")))
                self.package_height_edit.setText(str(dimensions.get("高", "")))
            self.package_unit_edit.setText(str(package_info.get("单位", "")))
            self.package_type_edit.setText(str(package_info.get("包装类型", "")))
        supplier = config.get("供方信息", {})
        if isinstance(supplier, dict):
            price_range = supplier.get("价格范围", {})
            if isinstance(price_range, dict):
                self.supplier_price_min_edit.setText(str(price_range.get("最低", "")))
                self.supplier_price_max_edit.setText(str(price_range.get("最高", "")))
            self.supplier_stock_edit.setText(str(supplier.get("库存", "")))
            self.supplier_piece_type_edit.setText(str(supplier.get("件数", "")))
            self.supplier_code_edit.setText(str(supplier.get("供方货号", "")))
        self.style_edit.setText(str(config.get("款式", "")))
        colors = config.get("颜色配置", [])
        self.colors_edit.setText(",".join(str(color) for color in colors) if isinstance(colors, list) else str(colors))
        certificates = config.get("证书列表", {})
        if isinstance(certificates, dict):
            enabled = certificates.get(CERTIFICATE_ENABLED_KEY, True)
            self.certificate_enabled_combo.setCurrentIndex(
                0 if certificate_upload_enabled_by_default(enabled) else 1
            )
            for qualification_name, edit in self.certificate_edits.items():
                value = certificates.get(qualification_name, "")
                if not value:
                    for alias in CERTIFICATE_FIELD_ALIASES.get(qualification_name, ()):
                        value = certificates.get(alias, "")
                        if value:
                            break
                edit.setText(str(value))
        else:
            self.certificate_enabled_combo.setCurrentIndex(0)

    def save_named_product_config(self) -> None:
        if not self.real_photo_product_combo.currentText().strip():
            QMessageBox.warning(self, "提示", "请先扫描并选择商品")
            return
        self.save_real_photo_product_config()
        self.save_settings()
        QMessageBox.information(self, "已保存", "当前商品配置已保存到 app_settings.json")

    def start_publish(self) -> None:
        local_root = self.real_photo_root_edit.text().strip()
        if local_root:
            try:
                local_variants = scan_real_photo_library(local_root)
                self.save_real_photo_product_config()
                enabled_products = getattr(self, "real_photo_upload_enabled", {})
                local_variants = [
                    variant
                    for variant in local_variants
                    if enabled_products.get(variant.product_name, True)
                ]
            except Exception as error:
                QMessageBox.critical(self, "实拍图目录错误", str(error))
                return
            if not local_variants:
                QMessageBox.warning(self, "提示", "没有启用上传的商品，请至少勾选一个商品")
                return
            goods_list = [
                {
                    "goodsName": item.product_name,
                    "goodsId": f"local_{index:03d}_{item.product_name}_{item.variant_name or 'default'}",
                    "_variant_name": item.variant_name,
                    "_local_product": True,
                }
                for index, item in enumerate(local_variants, start=1)
            ]
        else:
            goods_list = self.get_selected_goods()
            if not goods_list:
                QMessageBox.warning(self, "提示", "请先选择实拍图目录")
                return
        try:
            settings = self.collect_publish_settings()
        except Exception as error:
            QMessageBox.critical(self, "配置错误", str(error))
            return
        self.save_settings()
        self.log_box.clear()
        self.append_log(f"已选择 {len(goods_list)} 个商品，将生成图片并逐轮上架")
        self.set_running_state(True)
        self.publish_worker = PublishWorker(goods_list, settings)
        self.publish_worker.log.connect(self.append_log)
        self.publish_worker.status.connect(self.status_label.setText)
        self.publish_worker.finished.connect(self.finish_publish)
        self.publish_worker.failed.connect(self.fail_publish)
        self.publish_worker.start()

    def toggle_pause(self) -> None:
        if self.publish_worker is None:
            return
        paused = self.publish_worker.pause_or_resume()
        self.pause_button.setText("继续运行" if paused else "暂停运行")
        self.append_log("用户已暂停运行" if paused else "用户已继续运行")

    def stop_publish(self) -> None:
        if self.publish_worker is not None:
            self.publish_worker.stop()
            self.append_log("已请求停止，当前步骤结束后会停止")
            self.stop_button.setEnabled(False)

    def finish_publish(self, message: str) -> None:
        self.append_log(message)
        self.set_running_state(False)
        QMessageBox.information(self, "完成", message)

    def fail_publish(self, message: str) -> None:
        self.append_log(f"执行结束: {message}")
        self.set_running_state(False)
        QMessageBox.critical(self, "执行结束", message)

    def set_running_state(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.pause_button.setEnabled(running)
        self.pause_button.setText("暂停运行")
        self.stop_button.setEnabled(running)
        self.search_button.setEnabled(not running and bool(self.selected_image_path))
        self.choose_button.setEnabled(not running)

    def append_log(self, message: str) -> None:
        if message.startswith("[AI]"):
            color = QColor("#55aaff")
        elif message.startswith("[自动化]"):
            color = QColor("#69d39b")
        elif "失败" in message or "错误" in message:
            color = QColor("#ff7272")
        else:
            color = QColor("#c8ced8")
        self.log_box.setTextColor(color)
        self.log_box.append(message)
        self.log_box.setTextColor(QColor("#c8ced8"))

    def check_for_updates(self) -> None:
        if not can_install_updates() or self.update_check_worker is not None:
            return

        self.update_access_blocked = True
        self.setEnabled(False)
        self.update_check_worker = UpdateCheckWorker(APP_VERSION)
        self.update_check_worker.manifest_ready.connect(self.handle_update_manifest)
        self.update_check_worker.failed.connect(self.fail_update_check)
        self.update_check_worker.finished.connect(self.release_update_check_worker)
        self.update_check_worker.start()

    def handle_update_manifest(self, manifest: UpdateManifest, from_cache: bool) -> None:
        newer_version = is_newer_version(manifest.version, APP_VERSION)
        update_required = is_update_required(manifest, APP_VERSION)
        version_disabled = is_version_disabled(manifest, APP_VERSION)

        if update_required:
            self.offer_required_update(manifest, newer_version, from_cache)
            return

        if from_cache:
            QMessageBox.critical(
                self,
                "无法验证版本状态",
                "当前无法连接更新服务器，不能确认该版本是否仍被允许使用。\n"
                "请检查网络连接后重新启动程序。",
            )
            QApplication.quit()
            return

        self.update_access_blocked = False
        self.setEnabled(True)
        if newer_version:
            self.offer_update(manifest)
        else:
            self.finish_update_check()

    def offer_update(self, manifest: UpdateManifest) -> None:
        notes = manifest.notes or "包含功能改进和问题修复"
        answer = QMessageBox.question(
            self,
            "发现新版本",
            f"发现新版本 v{manifest.version}，当前版本为 v{APP_VERSION}。\n\n"
            f"更新内容：\n{notes}\n\n是否立即下载并安装？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer == QMessageBox.Yes:
            self.download_update(manifest)

    def offer_required_update(
        self,
        manifest: UpdateManifest,
        newer_version: bool,
        from_cache: bool,
    ) -> None:
        message = manifest.message or "当前版本已停止服务，请升级后继续使用。"
        if from_cache:
            message += "\n\n当前无法连接更新服务器，已使用最近一次有效的停用策略。"

        if not newer_version:
            QMessageBox.critical(self, "当前版本已停用", message)
            QApplication.quit()
            return

        if not Path(sys.executable).resolve().with_name("XiYinUpdater.exe").is_file():
            QMessageBox.critical(
                self,
                "必须升级",
                f"{message}\n\n当前安装缺少更新程序，请下载安装最新完整版本。",
            )
            QApplication.quit()
            return

        answer = QMessageBox.question(
            self,
            "必须升级",
            f"{message}\n\n可升级到 v{manifest.version}，是否立即更新？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer == QMessageBox.Yes:
            self.download_update(manifest)
        else:
            QApplication.quit()

    def finish_update_check(self) -> None:
        self.append_log(f"[更新] 当前已是最新版本 v{APP_VERSION}")

    def fail_update_check(self, message: str) -> None:
        self.append_log(f"[更新] 检查失败: {message}")
        QMessageBox.critical(
            self,
            "无法验证版本状态",
            f"无法连接更新服务器，程序不能继续运行。\n\n{message}",
        )
        QApplication.quit()

    def release_update_check_worker(self) -> None:
        self.update_check_worker = None

    def download_update(self, manifest: UpdateManifest) -> None:
        if self.update_download_worker is not None:
            return

        dialog = QProgressDialog("正在下载更新包...", "", 0, 100, self)
        dialog.setWindowTitle(f"更新到 v{manifest.version}")
        dialog.setCancelButton(None)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setValue(0)
        self.update_progress_dialog = dialog

        self.update_download_worker = UpdateDownloadWorker(manifest)
        self.update_download_worker.progress_changed.connect(dialog.setValue)
        self.update_download_worker.completed.connect(self.install_downloaded_update)
        self.update_download_worker.failed.connect(self.fail_update_download)
        self.update_download_worker.finished.connect(self.release_update_download_worker)
        self.update_download_worker.start()

    def install_downloaded_update(self, manifest: UpdateManifest, archive_path: Path) -> None:
        if self.update_progress_dialog is not None:
            self.update_progress_dialog.setValue(100)
        try:
            launch_updater(archive_path, manifest.sha256)
        except Exception as error:
            QMessageBox.critical(self, "更新失败", str(error))
            return

        QMessageBox.information(
            self,
            "准备安装更新",
            "程序将关闭并安装更新，完成后会自动重新启动。",
        )
        QApplication.quit()

    def fail_update_download(self, message: str) -> None:
        if self.update_progress_dialog is not None:
            self.update_progress_dialog.close()
        QMessageBox.critical(self, "更新下载失败", message)
        if self.update_access_blocked:
            QApplication.quit()

    def release_update_download_worker(self) -> None:
        self.update_download_worker = None
        if self.update_progress_dialog is not None:
            self.update_progress_dialog.close()
            self.update_progress_dialog = None


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
