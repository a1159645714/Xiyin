import sys
from pathlib import Path


if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
else:
    BASE_DIR = Path(__file__).resolve().parent
    RESOURCE_DIR = BASE_DIR

TARGET_URL = "https://sso.geiwohuo.com/#/mfrp/followsales-pro/list"
USER_DATA_DIR = BASE_DIR / "playwright_chrome_profile"
COOKIES_FILE = BASE_DIR / "cookies.json"
APP_SETTINGS_FILE = BASE_DIR / "app_settings.json"
CATEGORY_CATALOG_FILE = BASE_DIR / "category_catalog.json"
CATEGORY_CATALOG_BUNDLED_FILE = RESOURCE_DIR / "category_catalog.json"
CATEGORY_CATALOG_HOME_FILE = BASE_DIR / "category_catalog_home.json"
CATEGORY_CATALOG_HOME_BUNDLED_FILE = RESOURCE_DIR / "category_catalog_home.json"
CATEGORY_PATH_END_TEXT = "不继续选择下级类目"
DEFAULT_PRODUCT_ROOT_DIR = ""
CONFIG_FILE_NAME = "商品配置.json"
DEFAULT_PRODUCT_TITLE = (
    "6Pcs 红色创意西瓜造型挤压玩具，软绵绵的手工制作冰淇淋质感，"
    "清脆爽感，缓慢回弹缓解压力，脆脆的西瓜冰沙挤压玩具，"
    "缓解焦虑情绪的绝佳感官玩具，注意力缺陷多动障碍/自闭症指尖玩具，"
    "减压玩具，非常适合节日礼物，生日礼物，派对礼物，"
    "squishy，squishy toys，squishy stress toy，nee doh，dumpling squish"
)
VIEWPORT_WIDTH = 1920
VIEWPORT_HEIGHT = 1080

APP_TITLE = "希音平台全自动上品工具"
APP_VERSION = "1.0.5"
UPDATE_MANIFEST_URL = (
    "https://xiyin-updates-1302706245.cos.ap-chongqing.myqcloud.com/"
    "updates/update.json"
)
SCARCE_HOT_TAB_TEXT = "稀缺爆款"
PLATFORM_HOT_TAB_TEXT = "平台热卖"
POTENTIAL_TREND_TAB_TEXT = "潜力趋势"
OPPORTUNITY_TAB_OPTIONS = (
    SCARCE_HOT_TAB_TEXT,
    PLATFORM_HOT_TAB_TEXT,
    POTENTIAL_TREND_TAB_TEXT,
)
MARKET_HOT_TEXT = "市场爆款"
CATEGORY_ROOT_TEXT = "玩具&游戏"
CATEGORY_CHILD_TEXT = "儿童艺术和手工艺"
SEARCH_TEXT = "搜索"
PUBLISH_SAME_TEXT = "发布同款"
PUBLISH_ENTRY_TEXTS = (
    PUBLISH_SAME_TEXT,
)
KIDS_CRAFT_SET_TEXT = "儿童手工套装"
KIDS_FASHION_CRAFT_KIT_TEXT = "儿童时尚手工艺套件"
DEFAULT_PUBLISH_CATEGORY_PATH = (
    KIDS_CRAFT_SET_TEXT,
    KIDS_FASHION_CRAFT_KIT_TEXT,
)
CONFIRM_NEXT_TEXT = "确认，下一步"
I_KNOW_TEXT = "我知道了"
NEW_IMAGE_UPLOAD_TEXT = "新版图片上传"
OK_TEXT = "确定"
UPLOAD_TEXT = "上传"
EDIT_TEXT = "编辑"
SUBMIT_TEXT = "提交"
MULTI_COLOR_TEXT = "多色"
NO_MORE_UPLOAD_TEXT = "不再上传"
PUBLISH_AND_SIGN_UP_TEXT = "发布商品并报名"
EXPAND_VIDEO_TEXT = "展开添加【商品视频】，可获得更多精准流量"
USE_TEMPLATE_TEXT = "使用模板"
EDIT_STOCK_TEXT = "编辑库存"
PIECE_TYPE_TEXT = "单品"
STOCK_VALUE = "5000"
PRICE_MIN = 50
PRICE_MAX = 100

PRODUCT_ATTRIBUTES = [
    ("Hazard Category", "其他", None),
    ("Applicable Age", "3岁以上", None),
    ("Tariff Type", "解压玩具", None),
    ("Material", "TPR", None),
    ("Composition", "PU", "100"),
]

TOY_MANUAL_QUALIFICATION = "玩具说明书（五国语言）"
REAL_PHOTO_QUALIFICATION_KEYWORD = "产品批次号"
REAL_PHOTO_SECTION_TEXT = "实拍图类"
COMPLIANCE_INFO_SECTION_TEXT = "合规信息"
BODY_REAL_PHOTO_DIR_NAME = "本体"
PACKAGE_REAL_PHOTO_DIR_NAME = "包装"
EU_TOY_SAFETY_DIRECTIVE_TEXT = "欧盟玩具安全指令"
PRODUCT_IDENTIFIER_TEXT = "产品标识符"
US_CHOKING_HAZARD_TEXT = "美国玩具窒息危险提示"
TOY_TYPE_TEXT = "玩具类型"
OTHER_TEXT = "其他"
NOT_UNDER_3_TEXT = "不适合3岁以下儿童"
TOY_HAZARD_DESC_TEXT = "玩具危险性描述"
NO_CHOKING_WARNING_TEXT = "该玩具不含上述情况，无需展示窒息危险警告语"
CERTIFICATE_CONFIG_KEY = "证书列表"
CERTIFICATE_ENABLED_KEY = "是否启用"
CERTIFICATE_NAME_KEYS = [
    "证书名",
    "匹配证书名",
    "匹配关键词",
]
CONFIGURABLE_QUALIFICATIONS = [
    TOY_MANUAL_QUALIFICATION,
    "CPSIA报告",
    "TOY自符声明-EU（手动）",
    "欧洲玩具检测报告:EN71-1/2/3、REACH二甲酸酯含量",
    "玩具EN 71检测报告",
    "CPC证书（手动）",
    "ASTM F963报告",
    "韩国安全检测报告（儿童产品）",
    "TOY自符声明-UK（手动）",
    "POPs化学测试报告",
    "PPWR 包装化学测试报告",
    "REACH检测报告",
    "技术文件",
]

ATTRIBUTE_LABEL_MAP = {
    "敏感类别": "Hazard Category",
    "适用年龄": "Applicable Age",
    "关税种类": "Tariff Type",
    "材质": "Material",
    "次要材质": "Other Material",
    "成分": "Composition",
}

# Keep the original English labels first for existing publish pages, then try
# aliases used by newer page versions and the stable Chinese labels.
ATTRIBUTE_LABEL_ALIASES = {
    "Hazard Category": ("Hazard Category", "敏感类别"),
    "Applicable Age": ("Applicable Age", "Suitable Age", "适用年龄"),
    "Tariff Type": ("Tariff Type", "关税种类"),
    "Material": ("Material", "材质"),
    "Other Material": ("Other Material", "次要材质"),
    "Composition": ("Composition", "成分"),
}

COMPLIANCE_INFO_ROW_ALIASES = {
    EU_TOY_SAFETY_DIRECTIVE_TEXT: (EU_TOY_SAFETY_DIRECTIVE_TEXT,),
    PRODUCT_IDENTIFIER_TEXT: (PRODUCT_IDENTIFIER_TEXT,),
    US_CHOKING_HAZARD_TEXT: (US_CHOKING_HAZARD_TEXT,),
}
