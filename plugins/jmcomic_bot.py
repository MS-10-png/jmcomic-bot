from nonebot import get_bots, get_driver, logger, on_command, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent, Message, MessageSegment
from nonebot.params import CommandArg
from nonebot.rule import to_me
import asyncio
import threading
from dataclasses import dataclass
from datetime import datetime
import json
import os
import random
import re
import struct
import time
import zlib
from pathlib import Path

# 导入新的API模块
from .jm_api import jm_api
from .pixiv_api import pixiv_api
from .bot_control import check_event_access, is_feature_enabled
from . import llm_prefs
from .llm_chat import (
    append_chat_history,
    build_llm_messages,
    clear_chat_history,
    compose_dict_answer,
    compose_web_answer,
    get_chat_history,
    llm_chat,
    llm_enabled,
)
from . import bilibili
from . import dictionary
from . import web_search
from .group_chat import mark_bot_spoke, try_handle_silence_command
from .skills import try_handle_skill

# 创建命令处理器
download_cmd = on_command("下载漫画", aliases={"dl漫画", "漫画下载"})
help_cmd = on_command("jm帮助", aliases={"jmhelp", "漫画帮助", "漫画菜单"})
image_cmd = on_command("jm图片", aliases={"漫画图片", "jm图"})
file_cmd = on_command("jm文件", aliases={"漫画文件", "jmzip", "jm压缩包"})
cover_cmd = on_command("jm封面", aliases={"漫画封面"})
search_cmd = on_command("jm搜索", aliases={"搜索漫画", "查漫画", "漫画搜索", "搜漫画", "搜索编号", "查编号"})
recommend_cmd = on_command("jm推荐", aliases={"随机推荐", "漫画推荐", "jm随机", "jm随机推荐", "每日推荐", "今日推荐", "jm每日推荐"})
pixiv_recommend_cmd = on_command("pixiv推荐", aliases={"p站推荐", "pixiv日榜", "p站日榜", "pixiv每日推荐"})
pixiv_tag_cmd = on_command("pixiv搜图", aliases={"p站搜图", "pixiv标签", "p站tag", "pixivtag", "搜p站"})
pixiv_pid_cmd = on_command("pixivpid", aliases={"pid", "pixiv作品", "pixiv编号", "p站pid", "p站编号"})
pixiv_subscribe_cmd = on_command("pixiv订阅", aliases={"p站订阅", "订阅pixiv", "订阅p站"})
pixiv_unsubscribe_cmd = on_command("pixiv取消", aliases={"pixiv退订", "p站取消", "取消pixiv", "取消p站"})
pixiv_status_cmd = on_command("pixiv订阅状态", aliases={"p站订阅状态", "pixiv状态"})
pixiv_age_cmd = on_command("pixiv年龄认证", aliases={"p站年龄认证", "成人认证", "18认证", "r18认证", "R18认证"})
pixiv_login_cmd = on_command("pixiv登录状态", aliases={"pixiv登录", "检查pixiv登录", "pixiv cookie状态", "pixiv登录检测"})
jm_subscribe_cmd = on_command("jm订阅", aliases={"订阅漫画", "漫画订阅", "jm收藏", "收藏漫画", "关注漫画"})
jm_unsubscribe_cmd = on_command("jm取消", aliases={"jm退订", "退订漫画", "取消订阅", "取消收藏", "取关漫画"})
jm_subscribe_status_cmd = on_command("jm订阅状态", aliases={"jm订阅列表", "我的订阅", "订阅列表", "我的收藏"})
jm_detail_cmd = on_command("jm详情", aliases={"漫画详情", "查详情", "查看详情", "漫画信息"})
category_cmd = on_command("分类", aliases={"jm分类", "漫画分类", "分类浏览", "浏览分类", "看分类"})
at_comic_cmd = on_message(rule=to_me(), priority=20, block=True)
pixiv_interactive_cmd = on_message(priority=35, block=False)

INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
COMIC_ID_PATTERN = re.compile(r"\b(?:jm\s*)?(\d{3,})\b", re.IGNORECASE)
PAGE_LIMIT_PATTERN = re.compile(r"(\d+)\s*(?:页|p|张|page|pages)?", re.IGNORECASE)
SEND_DELAY_SECONDS = float(os.getenv("JM_SEND_DELAY_SECONDS", "1"))
FILE_OUTPUT_KEYWORDS = ("文件", "压缩包", "打包", "下载", "zip", "file", "archive")
IMAGE_OUTPUT_KEYWORDS = ("图片", "图", "逐页", "image", "img")
COVER_KEYWORDS = ("封面", "cover", "只发封面", "只要封面")
ALL_PAGE_KEYWORDS = ("all", "全部", "全册", "完整")
GROUP_DELIVERY_KEYWORDS = ("群发", "发群", "群里", "本群", "当前群", "group")
PRIVATE_DELIVERY_KEYWORDS = ("私发", "私聊", "私信", "private", "dm")
SEARCH_PREFIXES = (
    "搜索漫画",
    "漫画搜索",
    "搜漫画",
    "搜索编号",
    "查编号",
    "查漫画",
    "搜索",
    "关键词",
    "search",
    "keyword",
    "搜",
    "查",
)
RECOMMEND_KEYWORDS = ("随机推荐", "漫画推荐", "jm推荐", "jm随机", "jm随机推荐", "推荐", "random", "每日推荐", "今日推荐")
PIXIV_RECOMMEND_KEYWORDS = ("pixiv推荐", "pixiv日榜", "pixiv每日推荐", "p站推荐", "p站日榜")
PIXIV_TAG_PREFIXES = ("pixiv搜图", "p站搜图", "pixiv标签", "p站tag", "搜p站", "pixivtag")
PIXIV_PID_PREFIXES = ("pixivpid", "pid", "pixiv作品", "pixiv编号", "p站pid", "p站编号")
PIXIV_DAILY_TIME = os.getenv("PIXIV_DAILY_TIME", "09:00")
def get_env_int(name, default):
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


PIXIV_DAILY_COUNT = get_env_int("PIXIV_DAILY_COUNT", 5)
PIXIV_SUBSCRIBERS_FILE = Path(__file__).resolve().parent / "pixiv_subscribers.json"
PIXIV_PREFERENCES_FILE = Path(__file__).resolve().parent / "pixiv_preferences.json"
PIXIV_AGE_FILE = Path(__file__).resolve().parent / "pixiv_age_verification.json"
JM_PREFERENCES_FILE = Path(__file__).resolve().parent / "jm_preferences.json"
JM_SUBSCRIPTIONS_FILE = Path(__file__).resolve().parent / "jm_subscriptions.json"
PIXIV_CACHE_DIR = Path(__file__).resolve().parent / "download" / "pixiv"
JM_QQ_CACHE_DIR = Path(__file__).resolve().parent / "download" / "qq"
PIXIV_RANDOM_POOL_SIZE = get_env_int("PIXIV_RANDOM_POOL_SIZE", 80)
JM_RANDOM_POOL_SIZE = get_env_int("JM_RANDOM_POOL_SIZE", 80)
PIXIV_ADULT_PENDING_SECONDS = get_env_int("PIXIV_ADULT_PENDING_SECONDS", 600)
# JM 订阅更新巡检间隔（秒），默认 30 分钟
JM_SUBSCRIPTION_CHECK_SECONDS = get_env_int("JM_SUBSCRIPTION_CHECK_MINUTES", 30) * 60


def get_env_float(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


# 缓存自动清理：清理超过 N 天未使用的 qq/pixiv 临时缓存；0 = 关闭
CACHE_MAX_AGE_DAYS = get_env_float("JM_CACHE_MAX_AGE_DAYS", 30.0)

# 美化的封面预览：搜索/推荐时附带几张封面图，0 = 关闭
RECOMMEND_SEND_COVERS = get_env_int("JM_RECOMMEND_SEND_COVERS", 5)
SEARCH_SEND_COVERS = get_env_int("JM_SEARCH_SEND_COVERS", 3)
COVER_CACHE_DIR = JM_QQ_CACHE_DIR / "_covers"
# B 站搜索附带封面预览数（0 = 只发文字）
BILI_SEND_COVERS = get_env_int("JM_BILI_SEND_COVERS", 3)
BILI_COVER_DIR = JM_QQ_CACHE_DIR / "_bili_covers"

_NUMBER_EMOJI = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟")


# 会话级"进行中任务"记忆：像人一样记得自己正在干什么，
# 用户追问「在找吗/好了吗/还不发我」时能说出真实进度而不是空口安慰。
# key = pixiv_preference_key(event)，value = {"desc": 任务描述, "ts": 开始时间, "tag": 类型标签}
_ONGOING_TASKS: dict[str, dict] = {}
_ONGOING_TASKS_LOCK = threading.Lock()


def remember_ongoing_task(key, desc, tag=""):
    """记录当前会话正在进行的任务（下载/搜索/推荐等）。"""
    if not key:
        return
    with _ONGOING_TASKS_LOCK:
        _ONGOING_TASKS[key] = {"desc": str(desc), "ts": time.time(), "tag": str(tag)}


def forget_ongoing_task(key):
    with _ONGOING_TASKS_LOCK:
        _ONGOING_TASKS.pop(key, None)


def peek_ongoing_task(key, max_age=1800):
    """取最近任务的描述；超过 max_age 秒视为已过期（防止老任务永远挡着）。"""
    if not key:
        return None
    with _ONGOING_TASKS_LOCK:
        item = _ONGOING_TASKS.get(key)
        if not item:
            return None
        if time.time() - float(item.get("ts") or 0) > max_age:
            _ONGOING_TASKS.pop(key, None)
            return None
        return dict(item)


# 会话级「最近一次任务」上下文：记录本会话刚做过的任务（搜索关键词/漫画请求参数），
# 供 chat_judge 判断「bot 发完消息后的下一句话」时续接省略指令（第2页/私发/群发/文件/图片/封面）。
_last_task_ctx: dict[str, dict] = {}
_last_task_ctx_lock = threading.Lock()


def remember_last_task(key, **fields):
    """记录本会话最近一次任务的上下文（key = group:xxx / private:xxx）。"""
    if not key:
        return
    with _last_task_ctx_lock:
        _last_task_ctx[key] = {"ts": time.time(), **fields}


def peek_last_task(key, max_age=1800):
    """取最近一次任务上下文；超过 max_age 秒视为已过期。"""
    if not key:
        return None
    with _last_task_ctx_lock:
        item = _last_task_ctx.get(key)
        if not item:
            return None
        if time.time() - float(item.get("ts") or 0) > max_age:
            _last_task_ctx.pop(key, None)
            return None
        return dict(item)


def number_emoji(index):
    return _NUMBER_EMOJI[index - 1] if 1 <= index <= len(_NUMBER_EMOJI) else f"{index}."
PIXIV_RANDOM_PROMPTS = ("来点图", "来张图", "随机图", "抽张图", "来点pixiv", "来点p站")
PIXIV_POSITIVE_RATINGS = ("满意", "喜欢", "好看", "不错", "可以", "赞", "爱了")
PIXIV_NEGATIVE_RATINGS = ("不满意", "不喜欢", "不好看", "不行", "难看", "一般", "换一张", "换张", "换图")
PIXIV_ADULT_CONFIRM_PHRASES = (
    "我已满18岁",
    "我已满18",
    "确认满18",
    "确认已满18岁",
    "本人已满18岁",
    "我已成年",
    "确认成年",
)
PIXIV_ADULT_CANCEL_PHRASES = ("取消成人认证", "取消18认证", "取消r18认证", "撤销成人认证")
PIXIV_ADULT_TOKEN_PATTERN = re.compile(r"(?<![a-z0-9])r\s*-?\s*18\s*g?(?![a-z0-9])", re.IGNORECASE)
HELP_MENU = (
    "✦┄┄┄┄┄ 🐳 JM 二号 · 鲸鱼娘小鱼 ┄┄┄┄┄✦\n"
    "群里 @我 或直接发下面的格式都可以，喵～\n"
    "\n"
    "📚 JM 漫画\n"
    "① 123456 文件 ─── 全册加密 zip（密码=编号）\n"
    "② 123456 图片 ─── 逐页发图\n"
    "③ 123456 20页 文件 只打包前 20 页\n"
    "④ 123456 封面 ─── 只发封面\n"
    "⑤ 搜索 关键词 ─── 找相关编号（加「第2页」翻页）\n"
    "⑥ 随机推荐 [关键词] ── 随机 5 本（可指定口味）\n"
    "\n"
    "🎨 Pixiv\n"
    "⑦ 来点图 [TAG] ─── 按你的口味随机抽图\n"
    "⑧ pixiv搜图 TAG ── TAG 搜图\n"
    "⑨ pid 12345678 ── PID 查图\n"
    "⑩ 满意/不满意/换一张 调教出图偏好\n"
    "\n"
    "✨ 可选词\n"
    "· 加「群发」发到本群 ｜ 加「私发」私聊给你\n"
    "· R18/R18G 先发「我已满18岁」，发「取消18认证」撤销\n"
    "· 订阅日榜：pixiv订阅 ｜ 退订：pixiv取消\n"
    "· 追更漫画：jm订阅 123456 ｜ 退订：jm取消 123456 ｜ 查看：jm订阅列表\n"
    "· 看详情：123456 详情 ｜ 我的历史：最近看过什么\n"
    "· 逛分类：分类 ｜ 分类 韩漫 ｜ 分类 韩漫 第2页\n"
    "· 也支持斜杠命令：/jm文件 123456、/pixiv搜图 TAG\n"
    "\n"
    "🎲 日常小技能（@我使用）\n"
    "· 签到 ｜ 计算 1+2*3 ｜ 骰子 或 2d20 ｜ 随机数 1 100\n"
    "· 抽签 ｜ 倒计时 2027-1-1 ｜ 随机点名 ｜ 讲个笑话\n"
    "\n"
    "🌐 联网技能（@我使用）\n"
    "· b站 关键词 ── 在B站找视频（如「b站 猫咪」「bilibili 新番推荐」）\n"
    "· 「XX是什么意思」── 查词解释，网络流行语/英文单词都能查（如「破防是什么意思」）\n"
    "· 问新闻/天气/时事会自动联网查 ｜ 发「少说token」调教我的聊天风格"
)


async def ensure_bot_control(matcher, event, feature=None):
    allowed, message = check_event_access(event, feature)
    if not allowed:
        await matcher.send(message)
        return False
    return True


async def ensure_bot_control_message(bot, event, feature=None):
    allowed, message = check_event_access(event, feature)
    if not allowed:
        await bot.send(event=event, message=message)
        return False
    return True


def get_default_send_image_limit():
    raw_limit = os.getenv("JM_SEND_IMAGE_LIMIT", "10").strip().lower()
    if raw_limit in {"all", "全部", "0"}:
        return None
    try:
        return max(1, int(raw_limit))
    except ValueError:
        return 10


DEFAULT_SEND_IMAGE_LIMIT = get_default_send_image_limit()


@dataclass
class DownloadResult:
    title: str
    download_dir: Path
    cover_path: Path
    image_paths: list[Path]


@dataclass
class AtComicRequest:
    comic_id: str
    page_limit: int | None
    cover_only: bool
    output_mode: str = "image"
    delivery_mode: str = "private"


def safe_filename(value, fallback="untitled"):
    value = INVALID_FILENAME_CHARS.sub("_", str(value)).strip().strip(".")
    return value[:80] or fallback


def parse_download_args(text):
    parts = text.split()
    if not parts:
        return "", DEFAULT_SEND_IMAGE_LIMIT

    comic_id = parts[0].strip()
    send_limit = DEFAULT_SEND_IMAGE_LIMIT
    if len(parts) >= 2:
        raw_limit = parts[1].strip().lower()
        if raw_limit in {"all", "全部", "0"}:
            send_limit = None
        else:
            try:
                send_limit = max(1, int(raw_limit))
            except ValueError:
                raise ValueError("页数参数应为数字，或使用 all / 全部")
    return comic_id, send_limit


def path_to_onebot_uri(path):
    return Path(path).resolve().as_uri()


def parse_delivery_mode(text):
    lowered = text.lower()
    if any(keyword in lowered for keyword in GROUP_DELIVERY_KEYWORDS):
        return "group"
    if any(keyword in lowered for keyword in PRIVATE_DELIVERY_KEYWORDS):
        return "private"
    return "private"


def parse_search_keyword(text):
    text = text.strip()
    if not text:
        return ""

    lowered = text.lower()
    for prefix in SEARCH_PREFIXES:
        if lowered == prefix:
            return ""
        if lowered.startswith(prefix):
            return text[len(prefix):].strip(" ：:，,")
    return ""


SEARCH_PAGE_PATTERN = re.compile(r"(?:第\s*(\d{1,3})\s*页|\b(\d{1,3})\s*页)$", re.IGNORECASE)


def parse_search_page(text):
    """从「关键词 第2页 / 关键词 2页」里拆出关键词和第几页，默认第 1 页。"""
    text = (text or "").strip()
    match = SEARCH_PAGE_PATTERN.search(text)
    if not match:
        return text, 1
    page = int(match.group(1) or match.group(2) or 1)
    keyword = text[:match.start()].strip(" ：:，,")
    return keyword, max(1, min(50, page))


# B 站视频搜索前缀（长前缀在前，避免「b站搜索」被「b站」吃掉）
BILI_PREFIXES = (
    "b站搜索", "bilibili搜索", "bili搜索", "哔哩哔哩搜索",
    "b站搜", "bilibili搜", "搜b站", "搜B站", "b站找", "bilibili找",
    "b站", "bilibili", "哔哩哔哩", "bili", "B站",
)


def parse_bili_search(text):
    """解析「b站 关键词」「bilibili搜 XX」等。返回关键词或 None。"""
    text = (text or "").strip()
    if not text:
        return None
    lowered = text.lower()
    for prefix in BILI_PREFIXES:
        if lowered == prefix:
            return ""
        if lowered.startswith(prefix):
            return text[len(prefix):].strip(" ：:，,、")
    return None


# 查词句式：后缀型（XX是什么意思）+ 前缀型（解释一下XX）。
# 注意：不用「查查/查一下」做前缀，它们历史上是 JM 漫画搜索触发词（「查查 女仆」=搜漫画）。
_DICT_SUFFIX = re.compile(
    r"(?P<word>[^\s，。！？!?,.;；:：]{1,30}?)"
    r"(?:是什么意思|什么意思|是什么含义|什么含义|是啥意思|啥意思|是啥子意思|啥子意思|"
    r"是啥|指什么|指啥|指的是什么|指的是啥)(?:[啊呀呢吗么哦诶哈吧？！!?。,\s]*)$"
)
_DICT_PREFIX = re.compile(
    r"^(?:帮我解释一下|给我解释一下|帮我解释解释|帮我解释下|帮我解释|给我解释|"
    r"解释一下|解释解释|解释下|解释)"
    r"[：:，,\s]*(?P<word>\S{1,30})$"
)


def parse_dict_query(text):
    """解析「破防是什么意思」「abyss啥意思」「解释一下 YOLO」等。返回要查的词或 None。"""
    text = (text or "").strip()
    if not text:
        return None
    match = _DICT_SUFFIX.search(text)
    if match:
        return match.group("word").strip()
    match = _DICT_PREFIX.match(text)
    if match:
        return match.group("word").strip()
    return None


def is_recommend_request(text):
    lowered = text.strip().lower()
    if lowered in RECOMMEND_KEYWORDS:
        return True
    return any(lowered.startswith(keyword) for keyword in ("随机推荐", "漫画推荐", "jm推荐", "jm随机"))


RECOMMEND_PREFIXES = ("随机推荐", "漫画推荐", "jm推荐", "jm随机推荐", "jm随机", "每日推荐", "今日推荐")


def parse_recommend_keyword(text):
    """从「随机推荐 女仆」里提取关键词；纯推荐返回空串，不是推荐请求返回 None。"""
    text = (text or "").strip()
    if not text:
        return None
    lowered = text.lower()
    for prefix in RECOMMEND_PREFIXES:
        if lowered == prefix:
            return ""
        if lowered.startswith(prefix):
            return text[len(prefix):].strip(" ：:，,")
    return None


DETAIL_KEYWORDS = ("详情", "简介", "介绍", "信息", "detail", "info")
DETAIL_PREFIXES = ("jm详情", "漫画详情", "查详情", "查看详情")


def parse_comic_detail_request(text):
    """识别「123456 详情」「jm详情 123456」等，返回 comic_id 或 None。

    只有消息里同时出现详情类关键词和编号才返回，避免闲聊提到「详情」误触发。
    """
    text = _cjk_digit_space(text or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if not any(keyword in lowered for keyword in DETAIL_KEYWORDS):
        return None
    match = COMIC_ID_PATTERN.search(text)
    if not match:
        return None
    return match.group(1)


CATEGORY_PREFIXES = ("分类", "jm分类", "漫画分类", "分类浏览", "浏览分类", "看分类")


def parse_category_command(text):
    """解析「分类」「分类 韩漫」「分类 5 第2页」等。返回 (分类名或ID, 页码) 或 None。

    - 只发「分类」→ ("", 1)，表示显示分类列表；
    - 「分类 韩漫」→ ("韩漫", 1)；
    - 「分类 韩漫 第2页」→ ("韩漫", 2)。
    """
    text = (text or "").strip()
    if not text:
        return None
    lowered = text.lower()
    for prefix in CATEGORY_PREFIXES:
        if lowered == prefix:
            return "", 1
        if lowered.startswith(prefix):
            rest = text[len(prefix):].strip(" ：:，,")
            name, page = parse_search_page(rest)
            return name, page
    return None


def resolve_category_id(name):
    """把分类名/slug/ID 解析成 JM 分类 ID；找不到返回 None。"""
    name = (name or "").strip().lower()
    if not name:
        return None
    try:
        cats = jm_api.get_categories()
    except Exception:
        return None

    # 精确匹配中文名
    for cat in cats:
        if (cat.get("name") or "").strip().lower() == name:
            return cat["id"]
    # 精确匹配 slug
    for cat in cats:
        if (cat.get("slug") or "").strip().lower() == name:
            return cat["id"]
    # 匹配 ID
    for cat in cats:
        if cat["id"] == name:
            return cat["id"]
    # 模糊包含匹配中文名（如「韩漫」匹配「韩漫」；「漫」可匹配多个，取第一个有内容的）
    for cat in cats:
        cat_name = (cat.get("name") or "").strip().lower()
        if cat_name and (name in cat_name or cat_name in name):
            return cat["id"]
    return None


def _cjk_digit_space(text):
    """中文与数字紧贴时补空格（如「帮我下载123456」「123456发我」），让编号正则能识别。"""
    text = re.sub(r"(?<=[\u4e00-\u9fff])(?=\d)", " ", text or "")
    return re.sub(r"(?<=\d)(?=[\u4e00-\u9fff])", " ", text)


def parse_at_comic_request(text):
    text = _cjk_digit_space(text).strip()
    if not text:
        return None

    id_match = COMIC_ID_PATTERN.search(text)
    if not id_match:
        return None

    comic_id = id_match.group(1)
    rest = f"{text[:id_match.start()]} {text[id_match.end():]}"
    lowered = rest.lower()
    cover_only = any(keyword in lowered for keyword in COVER_KEYWORDS)
    output_mode = "file" if any(keyword in lowered for keyword in FILE_OUTPUT_KEYWORDS) else "image"
    if any(keyword in lowered for keyword in IMAGE_OUTPUT_KEYWORDS):
        output_mode = "image"
    delivery_mode = parse_delivery_mode(rest)

    if cover_only:
        page_limit = 0
    elif any(keyword in lowered for keyword in ALL_PAGE_KEYWORDS):
        page_limit = None
    else:
        page_match = PAGE_LIMIT_PATTERN.search(rest)
        page_limit = max(1, int(page_match.group(1))) if page_match else None

    return AtComicRequest(
        comic_id=comic_id,
        page_limit=page_limit,
        cover_only=cover_only,
        output_mode=output_mode,
        delivery_mode=delivery_mode,
    )


def parse_mode_command_request(text, output_mode, cover_only=False):
    request = parse_at_comic_request(text)
    if request is None:
        return None

    return AtComicRequest(
        comic_id=request.comic_id,
        page_limit=0 if cover_only else request.page_limit,
        cover_only=cover_only or request.cover_only,
        output_mode=output_mode,
        delivery_mode=request.delivery_mode,
    )


def comic_request_feature(request):
    if request.cover_only:
        return "jm_cover"
    if request.output_mode == "file":
        return "jm_file"
    return "jm_image"


async def send_to_requester(bot, event, message, delivery_mode="private"):
    if isinstance(event, GroupMessageEvent) and delivery_mode != "group":
        await bot.send_private_msg(user_id=event.user_id, message=message)
    else:
        await bot.send(event=event, message=message)


async def notify_current_chat(bot, event, message):
    await bot.send(event=event, message=message)


def load_pixiv_subscriptions():
    if not PIXIV_SUBSCRIBERS_FILE.exists():
        return {"private": [], "group": [], "last_sent_date": ""}

    try:
        data = json.loads(PIXIV_SUBSCRIBERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}

    return {
        "private": [str(item) for item in data.get("private") or []],
        "group": [str(item) for item in data.get("group") or []],
        "last_sent_date": str(data.get("last_sent_date") or ""),
    }


def save_pixiv_subscriptions(data):
    PIXIV_SUBSCRIBERS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_pixiv_preferences():
    if not PIXIV_PREFERENCES_FILE.exists():
        return {"profiles": {}}

    try:
        data = json.loads(PIXIV_PREFERENCES_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}

    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}
    return {"profiles": profiles}


def save_pixiv_preferences(data):
    PIXIV_PREFERENCES_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_pixiv_age_verifications():
    if not PIXIV_AGE_FILE.exists():
        return {"verified_users": {}, "pending_users": {}}

    try:
        data = json.loads(PIXIV_AGE_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        data = {}

    verified_users = data.get("verified_users")
    pending_users = data.get("pending_users")
    if not isinstance(verified_users, dict):
        verified_users = {}
    if not isinstance(pending_users, dict):
        pending_users = {}
    return {"verified_users": verified_users, "pending_users": pending_users}


def save_pixiv_age_verifications(data):
    PIXIV_AGE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def pixiv_user_id(event):
    return str(getattr(event, "user_id", "") or "").strip()


def is_pixiv_adult_verified(event):
    user_id = pixiv_user_id(event)
    if not user_id:
        return False
    data = load_pixiv_age_verifications()
    return user_id in (data.get("verified_users") or {})


def mark_pixiv_adult_pending(event):
    user_id = pixiv_user_id(event)
    if not user_id:
        return
    data = load_pixiv_age_verifications()
    pending = data.setdefault("pending_users", {})
    pending[user_id] = {
        "requested_at": time.time(),
        "group_id": str(getattr(event, "group_id", "") or ""),
    }
    save_pixiv_age_verifications(data)


def has_pixiv_adult_pending(event):
    user_id = pixiv_user_id(event)
    if not user_id:
        return False
    data = load_pixiv_age_verifications()
    item = (data.get("pending_users") or {}).get(user_id)
    if not isinstance(item, dict):
        return False
    requested_at = float(item.get("requested_at") or 0)
    return requested_at > 0 and time.time() - requested_at <= PIXIV_ADULT_PENDING_SECONDS


def verify_pixiv_adult_user(event):
    user_id = pixiv_user_id(event)
    if not user_id:
        return False
    data = load_pixiv_age_verifications()
    data.setdefault("verified_users", {})[user_id] = {
        "verified_at": time.time(),
        "method": "self_confirmed",
    }
    data.setdefault("pending_users", {}).pop(user_id, None)
    save_pixiv_age_verifications(data)
    return True


def cancel_pixiv_adult_verification(event):
    user_id = pixiv_user_id(event)
    if not user_id:
        return False
    data = load_pixiv_age_verifications()
    changed = False
    if user_id in data.get("verified_users", {}):
        data["verified_users"].pop(user_id, None)
        changed = True
    if user_id in data.get("pending_users", {}):
        data["pending_users"].pop(user_id, None)
        changed = True
    if changed:
        save_pixiv_age_verifications(data)
    return changed


def pixiv_text_requests_adult(text):
    return bool(PIXIV_ADULT_TOKEN_PATTERN.search(text or ""))


def pixiv_artwork_requires_adult(artwork):
    if not artwork:
        return False
    if bool(artwork.get("age_restricted")):
        return True
    tags = " ".join(str(tag) for tag in artwork.get("tags") or [])
    if pixiv_text_requests_adult(tags):
        return True
    try:
        return int(artwork.get("x_restrict") or 0) > 0
    except (TypeError, ValueError):
        return False


def is_pixiv_adult_confirm_text(text):
    normalized = (text or "").strip()
    return normalized in PIXIV_ADULT_CONFIRM_PHRASES


def is_pixiv_adult_cancel_text(text):
    normalized = (text or "").strip()
    return normalized in PIXIV_ADULT_CANCEL_PHRASES


async def ensure_pixiv_adult_verified(bot, event):
    if is_pixiv_adult_verified(event):
        return True

    mark_pixiv_adult_pending(event)
    await bot.send(
        event=event,
        message=(
            "🔞 该 Pixiv 请求包含 R18/R18G 内容。为防止未成年人接触成人内容，"
            "请先回复「我已满18岁」完成年龄确认；确认前不会发送图片。"
        ),
    )
    return False


def pixiv_preference_key(event):
    if isinstance(event, GroupMessageEvent):
        return f"group:{event.group_id}"
    return f"private:{event.user_id}"


def get_pixiv_profile(data, key):
    profiles = data.setdefault("profiles", {})
    profile = profiles.setdefault(key, {})
    profile.setdefault("tag_weights", {})
    profile.setdefault("history", [])
    profile.setdefault("last_artwork", None)
    return profile


def pixiv_artwork_tags(artwork):
    tags = []
    for tag in artwork.get("tags") or []:
        tag = str(tag).strip()
        if tag and tag.lower() not in {"r-18", "r18", "r-18g", "r18g"}:
            tags.append(tag)
    return tags[:8]


def pixiv_artwork_weight(artwork, profile, history=None):
    tags = pixiv_artwork_tags(artwork)
    tag_weights = profile.get("tag_weights") or {}
    if tags:
        weight = sum(float(tag_weights.get(tag, 1.0)) for tag in tags) / len(tags)
    else:
        weight = 1.0

    if history is None:
        history = set(profile.get("history") or [])
    if artwork.get("id") in history:
        weight *= 0.35
    return max(0.05, weight)


def choose_pixiv_artwork(candidates, profile):
    if not candidates:
        return None
    history = set(profile.get("history") or [])
    weights = [pixiv_artwork_weight(artwork, profile, history) for artwork in candidates]
    return random.choices(candidates, weights=weights, k=1)[0]


def store_pixiv_last_artwork(key, artwork, event=None):
    data = load_pixiv_preferences()
    profile = get_pixiv_profile(data, key)
    profile["last_artwork"] = {
        "id": artwork.get("id"),
        "title": artwork.get("title"),
        "user_name": artwork.get("user_name"),
        "tags": pixiv_artwork_tags(artwork),
        "page_url": artwork.get("page_url"),
        "requester_user_id": str(getattr(event, "user_id", "")) if event is not None else "",
        "sent_at": time.time(),
    }

    history = [item for item in profile.get("history") or [] if item != artwork.get("id")]
    history.insert(0, artwork.get("id"))
    profile["history"] = history[:30]
    save_pixiv_preferences(data)


def update_pixiv_preference(key, rating, event=None):
    data = load_pixiv_preferences()
    profile = get_pixiv_profile(data, key)
    last_artwork = profile.get("last_artwork")
    if not last_artwork:
        return None

    requester_user_id = str(last_artwork.get("requester_user_id") or "")
    current_user_id = str(getattr(event, "user_id", "")) if event is not None else ""
    if requester_user_id and current_user_id and requester_user_id != current_user_id:
        return "owner_mismatch"

    tags = pixiv_artwork_tags(last_artwork)
    if not tags:
        return last_artwork

    tag_weights = profile.setdefault("tag_weights", {})
    for tag in tags:
        current = float(tag_weights.get(tag, 1.0))
        if rating == "positive":
            tag_weights[tag] = round(min(5.0, current * 1.25 + 0.1), 3)
        else:
            tag_weights[tag] = round(max(0.2, current * 0.72), 3)

    save_pixiv_preferences(data)
    return last_artwork


def is_pixiv_random_prompt(text):
    return parse_pixiv_random_tag(text) is not None


def parse_pixiv_random_tag(text):
    text = text.strip()
    lowered = text.lower()
    for prompt in PIXIV_RANDOM_PROMPTS:
        if lowered == prompt:
            return ""
        if lowered.startswith(prompt):
            return text[len(prompt):].strip(" ：:，,")
    return None


def parse_pixiv_rating(text):
    lowered = text.strip().lower()
    if lowered in PIXIV_NEGATIVE_RATINGS:
        return "negative"
    if lowered in PIXIV_POSITIVE_RATINGS:
        return "positive"
    return None


def has_pixiv_last_artwork(key):
    data = load_pixiv_preferences()
    profile = get_pixiv_profile(data, key)
    return bool(profile.get("last_artwork"))


def pixiv_last_sent_at(key):
    data = load_pixiv_preferences()
    profile = get_pixiv_profile(data, key)
    last_artwork = profile.get("last_artwork") or {}
    return float(last_artwork.get("sent_at") or 0)


def load_jm_preferences():
    if not JM_PREFERENCES_FILE.exists():
        return {"profiles": {}}

    try:
        data = json.loads(JM_PREFERENCES_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}

    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}
    return {"profiles": profiles}


def save_jm_preferences(data):
    JM_PREFERENCES_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------- JM 订阅

JM_SUBSCRIBE_PREFIXES = ("jm订阅", "订阅漫画", "漫画订阅", "jm收藏", "收藏漫画", "关注漫画")
JM_UNSUBSCRIBE_PREFIXES = ("jm取消", "jm退订", "退订漫画", "取消订阅", "取消收藏", "取关漫画")
JM_SUBSCRIBE_STATUS_PHRASES = ("jm订阅列表", "jm订阅状态", "我的订阅", "订阅列表", "我的收藏")


def load_jm_subscriptions():
    if not JM_SUBSCRIPTIONS_FILE.exists():
        return {"private": {}, "group": {}}

    try:
        data = json.loads(JM_SUBSCRIPTIONS_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        data = {}

    return {
        "private": data.get("private") if isinstance(data.get("private"), dict) else {},
        "group": data.get("group") if isinstance(data.get("group"), dict) else {},
    }


def save_jm_subscriptions(data):
    JM_SUBSCRIPTIONS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def jm_subscription_destination(event, text=""):
    """订阅推送到群还是私聊：群里带「群发」→ 当前群，否则私聊给订阅者。"""
    if isinstance(event, GroupMessageEvent) and parse_delivery_mode(text) == "group":
        return "group", str(event.group_id)
    return "private", str(event.user_id)


def _jm_subscription_entry(comic_id):
    """拉一次漫画信息，返回订阅条目；失败抛异常由调用方兜底。"""
    comic_id = comic_id.strip().lower()
    if comic_id.startswith("jm"):
        comic_id = comic_id[2:]
    info = jm_api.load_comic_info(comic_id)
    return {
        "title": info.get("title") or comic_id,
        "chapter_count": len(info.get("chapters") or {}),
        "subscribed_at": time.time(),
    }


def add_jm_subscription(destination_type, destination_id, comic_id):
    data = load_jm_subscriptions()
    bucket = data[destination_type].setdefault(destination_id, {})
    comic_id = comic_id.strip()
    if comic_id in bucket:
        return False, None
    entry = _jm_subscription_entry(comic_id)
    bucket[comic_id] = entry
    save_jm_subscriptions(data)
    return True, entry


def remove_jm_subscription(destination_type, destination_id, comic_id):
    data = load_jm_subscriptions()
    bucket = data[destination_type].get(destination_id, {})
    comic_id = comic_id.strip()
    if comic_id in bucket:
        bucket.pop(comic_id, None)
        if not bucket:
            data[destination_type].pop(destination_id, None)
        save_jm_subscriptions(data)
        return True
    return False


def list_jm_subscriptions(destination_type, destination_id):
    data = load_jm_subscriptions()
    bucket = data[destination_type].get(destination_id, {})
    return [(comic_id, meta) for comic_id, meta in bucket.items()]


def parse_jm_subscribe_action(text):
    """解析「jm订阅 123456」「jm取消 350235」等指令。返回 (op, comic_id, raw_text)。"""
    text = (text or "").strip()
    lowered = text.lower()

    for prefix in JM_SUBSCRIBE_PREFIXES:
        if lowered == prefix or lowered.startswith(prefix):
            rest = text[len(prefix):].strip(" ：:，,")
            match = COMIC_ID_PATTERN.search(rest)
            return "subscribe", (match.group(1) if match else ""), text

    for prefix in JM_UNSUBSCRIBE_PREFIXES:
        if lowered == prefix or lowered.startswith(prefix):
            rest = text[len(prefix):].strip(" ：:，,")
            match = COMIC_ID_PATTERN.search(rest)
            return "unsubscribe", (match.group(1) if match else ""), text

    return None


def check_jm_subscriptions():
    """巡检所有订阅，返回检测到更新章节的条目列表。"""
    data = load_jm_subscriptions()
    updates = []
    for destination_type, buckets in data.items():
        for destination_id, subs in buckets.items():
            for comic_id, meta in list(subs.items()):
                try:
                    info = jm_api.load_comic_info(comic_id)
                except Exception:
                    continue
                new_count = len(info.get("chapters") or {})
                old_count = int(meta.get("chapter_count") or 0)
                title = info.get("title") or meta.get("title") or comic_id
                if new_count > old_count:
                    updates.append(
                        (destination_type, destination_id, comic_id, title, old_count, new_count)
                    )
                # 同步最新章节数与标题，避免下次重复提醒
                meta["chapter_count"] = new_count
                meta["title"] = title
    save_jm_subscriptions(data)
    return updates


def jm_preference_key(event):
    if isinstance(event, GroupMessageEvent):
        return f"group:{event.group_id}"
    return f"private:{event.user_id}"


def get_jm_profile(data, key):
    profiles = data.setdefault("profiles", {})
    profile = profiles.setdefault(key, {})
    profile.setdefault("tag_weights", {})
    profile.setdefault("history", [])
    profile.setdefault("last_comics", [])
    profile.setdefault("last_sent_at", 0)
    profile.setdefault("viewed", [])
    return profile


def record_jm_viewed(event, comic_id, title):
    """记录该会话最近浏览/下载过的漫画（最多 20 条，供「我的历史」查询）。"""
    if event is None:
        return
    key = jm_preference_key(event)
    data = load_jm_preferences()
    profile = get_jm_profile(data, key)
    viewed = [item for item in profile.get("viewed") or [] if item.get("id") != comic_id]
    viewed.insert(0, {"id": str(comic_id), "title": title or str(comic_id), "ts": time.time()})
    profile["viewed"] = viewed[:20]
    save_jm_preferences(data)


def jm_comic_tags(comic):
    tags = comic.get("tags") or []
    if isinstance(tags, dict):
        values = []
        for key in ("Tag", "Author", "Work", "Actor"):
            values.extend(tags.get(key) or [])
        tags = values
    return [str(tag).strip() for tag in tags if str(tag).strip()][:12]


def jm_comic_weight(comic, profile, history=None):
    tags = jm_comic_tags(comic)
    tag_weights = profile.get("tag_weights") or {}
    if tags:
        weight = sum(float(tag_weights.get(tag, 1.0)) for tag in tags) / len(tags)
    else:
        weight = 1.0

    if history is None:
        history = set(profile.get("history") or [])
    if comic.get("id") in history:
        weight *= 0.5
    return max(0.05, weight)


def choose_jm_comics(candidates, profile, count=5):
    pool = list(candidates)
    chosen = []
    history = set(profile.get("history") or [])
    while pool and len(chosen) < count:
        weights = [jm_comic_weight(comic, profile, history) for comic in pool]
        comic = random.choices(pool, weights=weights, k=1)[0]
        chosen.append(comic)
        pool = [item for item in pool if item.get("id") != comic.get("id")]
    return chosen


def store_jm_last_comics(key, comics, event=None):
    data = load_jm_preferences()
    profile = get_jm_profile(data, key)
    profile["last_comics"] = [
        {
            "id": comic.get("id"),
            "title": comic.get("title"),
            "tags": jm_comic_tags(comic),
        }
        for comic in comics
    ]
    profile["last_requester_user_id"] = str(getattr(event, "user_id", "")) if event is not None else ""
    profile["last_sent_at"] = time.time()

    history = [item for item in profile.get("history") or [] if item not in {comic.get("id") for comic in comics}]
    history = [comic.get("id") for comic in comics if comic.get("id")] + history
    profile["history"] = history[:50]
    save_jm_preferences(data)


def update_jm_preference(key, rating, event=None):
    data = load_jm_preferences()
    profile = get_jm_profile(data, key)
    last_comics = profile.get("last_comics") or []
    if not last_comics:
        return None

    requester_user_id = str(profile.get("last_requester_user_id") or "")
    current_user_id = str(getattr(event, "user_id", "")) if event is not None else ""
    if requester_user_id and current_user_id and requester_user_id != current_user_id:
        return "owner_mismatch"

    tag_weights = profile.setdefault("tag_weights", {})
    changed = 0
    for comic in last_comics:
        for tag in jm_comic_tags(comic):
            current = float(tag_weights.get(tag, 1.0))
            if rating == "positive":
                tag_weights[tag] = round(min(5.0, current * 1.2 + 0.1), 3)
            else:
                tag_weights[tag] = round(max(0.2, current * 0.75), 3)
            changed += 1

    save_jm_preferences(data)
    return {"comics": last_comics, "changed": changed}


def jm_last_sent_at(key):
    data = load_jm_preferences()
    profile = get_jm_profile(data, key)
    return float(profile.get("last_sent_at") or 0)


def resolve_pixiv_destination(event, text=""):
    delivery_mode = parse_delivery_mode(text)
    if isinstance(event, GroupMessageEvent) and delivery_mode == "group":
        return "group", str(event.group_id)
    return "private", str(event.user_id)


def pixiv_destination_label(destination_type, destination_id):
    if destination_type == "group":
        return f"群 {destination_id}"
    return f"用户 {destination_id}"


def add_pixiv_subscription(destination_type, destination_id):
    data = load_pixiv_subscriptions()
    entries = data[destination_type]
    if destination_id not in entries:
        entries.append(destination_id)
        save_pixiv_subscriptions(data)
        return True
    return False


def remove_pixiv_subscription(destination_type, destination_id):
    data = load_pixiv_subscriptions()
    entries = data[destination_type]
    if destination_id in entries:
        entries.remove(destination_id)
        save_pixiv_subscriptions(data)
        return True
    return False


def pixiv_subscribers():
    data = load_pixiv_subscriptions()
    destinations = [("private", user_id) for user_id in data["private"]]
    destinations.extend(("group", group_id) for group_id in data["group"])
    return destinations


def parse_pixiv_daily_time():
    try:
        hour_text, minute_text = PIXIV_DAILY_TIME.split(":", 1)
        hour = min(23, max(0, int(hour_text)))
        minute = min(59, max(0, int(minute_text)))
        return hour, minute
    except Exception:
        return 9, 0


def is_pixiv_daily_due(data):
    now = datetime.now()
    hour, minute = parse_pixiv_daily_time()
    if (now.hour, now.minute) < (hour, minute):
        return False
    return data.get("last_sent_date") != now.strftime("%Y-%m-%d")


def mark_pixiv_daily_sent():
    data = load_pixiv_subscriptions()
    data["last_sent_date"] = datetime.now().strftime("%Y-%m-%d")
    save_pixiv_subscriptions(data)


def is_pixiv_recommend_request(text):
    lowered = text.strip().lower()
    return any(keyword in lowered for keyword in PIXIV_RECOMMEND_KEYWORDS)


def parse_pixiv_tag_search(text):
    text = text.strip()
    lowered = text.lower()
    for prefix in PIXIV_TAG_PREFIXES:
        if lowered == prefix:
            return ""
        if lowered.startswith(prefix):
            return text[len(prefix):].strip(" ：:，,")
    return None


def parse_pixiv_pid_search(text):
    text = text.strip()
    lowered = text.lower()
    for prefix in PIXIV_PID_PREFIXES:
        if lowered == prefix:
            return ""
        if lowered.startswith(prefix):
            rest = text[len(prefix):].strip(" ：:，,")
            match = re.search(r"\d{5,}", rest)
            return match.group(0) if match else ""
    return None


def format_pixiv_artwork(artwork, index):
    tags = "、".join(artwork.get("tags") or []) or "无"
    return (
        f"🎨 Pixiv 推荐 #{index}\n"
        "────────────\n"
        f"📖《{artwork.get('title') or '未命名'}》\n"
        f"👤 作者：{artwork.get('user_name') or '未知作者'}\n"
        f"🆔 ID：{artwork.get('id')}\n"
        f"🏷 TAG：{tags}\n"
        f"🔗 {artwork.get('page_url')}"
    )


def format_pixiv_random_artwork(artwork):
    tags = "、".join(artwork.get("tags") or []) or "无"
    return (
        "🎨 来点图 · 你的专属抽图结果\n"
        "────────────\n"
        f"📖《{artwork.get('title') or '未命名'}》\n"
        f"👤 作者：{artwork.get('user_name') or '未知作者'}\n"
        f"🆔 ID：{artwork.get('id')}\n"
        f"🏷 TAG：{tags}\n"
        f"🔗 {artwork.get('page_url')}\n"
        "────────────\n"
        "👍 满意 提高这类图概率 ｜ 👎 不满意/换一张 降低"
    )


async def send_pixiv_destination(bot, destination_type, destination_id, message):
    if destination_type == "group":
        await bot.send_group_msg(group_id=int(destination_id), message=message)
    else:
        await bot.send_private_msg(user_id=int(destination_id), message=message)


async def send_pixiv_recommendations(bot, destination_type, destination_id, count=PIXIV_DAILY_COUNT):
    artworks = await asyncio.to_thread(pixiv_api.daily_recommendations, count)
    if not artworks:
        await send_pixiv_destination(bot, destination_type, destination_id, "😢 Pixiv 暂时没有可发送的推荐，稍后再试试吧～")
        return

    await send_pixiv_destination(
        bot,
        destination_type,
        destination_id,
        f"🎨 Pixiv 日榜推荐\n"
        f"────────────\n"
        f"共 {len(artworks)} 张预览图 · 已附原链接",
    )
    for index, artwork in enumerate(artworks, start=1):
        await send_pixiv_destination(bot, destination_type, destination_id, format_pixiv_artwork(artwork, index))
        try:
            image_path = await asyncio.to_thread(pixiv_api.download_preview, artwork, PIXIV_CACHE_DIR)
            await send_pixiv_destination(
                bot,
                destination_type,
                destination_id,
                MessageSegment.image(path_to_onebot_uri(image_path)),
            )
        except Exception as exc:
            await send_pixiv_destination(
                bot,
                destination_type,
                destination_id,
                f"⚠️ 图片预览下载失败：{exc}\n可打开原链接查看：{artwork.get('page_url')}",
            )
        if SEND_DELAY_SECONDS > 0:
            await asyncio.sleep(SEND_DELAY_SECONDS)


async def send_pixiv_tag_search(bot, event, tag, count=5):
    tag = tag.strip()
    if not tag:
        await bot.send(event=event, message="🔍 请输入 Pixiv TAG，例如：/pixiv搜图 初音ミク")
        return
    if tag.isdigit() and len(tag) >= 5:
        await send_pixiv_pid_search(bot, event, tag)
        return

    allow_restricted = pixiv_text_requests_adult(tag)
    if allow_restricted and not await ensure_pixiv_adult_verified(bot, event):
        return

    await bot.send(event=event, message=f"🔍 正在搜索 Pixiv TAG：{tag}")
    artworks = await asyncio.to_thread(pixiv_api.search_by_tag, tag, count, 1, allow_restricted)
    if not artworks:
        await bot.send(event=event, message=f"😢 没有找到 TAG「{tag}」的可发送图片。")
        return

    for index, artwork in enumerate(artworks, start=1):
        await bot.send(event=event, message=format_pixiv_artwork(artwork, index))
        try:
            image_path = await asyncio.to_thread(pixiv_api.download_preview, artwork, PIXIV_CACHE_DIR)
            await bot.send(event=event, message=MessageSegment.image(path_to_onebot_uri(image_path)))
        except Exception as exc:
            await bot.send(event=event, message=f"图片预览下载失败：{exc}\n可打开原链接查看：{artwork.get('page_url')}")
        if SEND_DELAY_SECONDS > 0:
            await asyncio.sleep(SEND_DELAY_SECONDS)


async def send_pixiv_pid_search(bot, event, pid):
    pid = str(pid).strip()
    if not pid:
        await bot.send(event=event, message="请输入 Pixiv PID，例如：/pixivpid 12345678")
        return
    if not pid.isdigit():
        await bot.send(event=event, message="Pixiv PID 必须是数字。")
        return

    await bot.send(event=event, message=f"🔍 正在查询 Pixiv PID：{pid}")
    artwork = await asyncio.to_thread(pixiv_api.fetch_artwork_by_pid, pid, True)
    if pixiv_artwork_requires_adult(artwork) and not await ensure_pixiv_adult_verified(bot, event):
        return

    await bot.send(event=event, message=format_pixiv_artwork(artwork, 1))

    try:
        image_path = await asyncio.to_thread(pixiv_api.download_preview, artwork, PIXIV_CACHE_DIR)
        await bot.send(event=event, message=MessageSegment.image(path_to_onebot_uri(image_path)))
    except Exception as exc:
        await bot.send(event=event, message=f"⚠️ 图片预览下载失败：{exc}\n可打开原链接查看：{artwork.get('page_url')}")


async def send_pixiv_random_artwork(bot, event, tag=""):
    key = pixiv_preference_key(event)
    data = load_pixiv_preferences()
    profile = get_pixiv_profile(data, key)
    allow_restricted = pixiv_text_requests_adult(tag)
    if allow_restricted and not await ensure_pixiv_adult_verified(bot, event):
        return

    if tag:
        await bot.send(event=event, message=f"🎰 正在按你的偏好从 Pixiv TAG「{tag}」里抽图...")
        candidates = await asyncio.to_thread(pixiv_api.tag_pool, tag, PIXIV_RANDOM_POOL_SIZE, allow_restricted)
    else:
        await bot.send(event=event, message="🎰 正在按你的偏好从 Pixiv 抽图...")
        candidates = await asyncio.to_thread(pixiv_api.random_pool, PIXIV_RANDOM_POOL_SIZE)

    artwork = choose_pixiv_artwork(candidates, profile)
    if artwork is None:
        await bot.send(event=event, message="😢 Pixiv 暂时没有可发送的图片，稍后再试试吧～")
        return

    store_pixiv_last_artwork(key, artwork, event)
    await bot.send(event=event, message=format_pixiv_random_artwork(artwork))

    try:
        image_path = await asyncio.to_thread(pixiv_api.download_preview, artwork, PIXIV_CACHE_DIR)
        await bot.send(event=event, message=MessageSegment.image(path_to_onebot_uri(image_path)))
    except Exception as exc:
        await bot.send(event=event, message=f"⚠️ 图片预览下载失败：{exc}\n可打开原链接查看。")


async def rate_pixiv_last_artwork(bot, event, rating):
    key = pixiv_preference_key(event)
    last_artwork = update_pixiv_preference(key, rating, event)
    if not last_artwork:
        await bot.send(event=event, message="🤔 还没有可评价的上一张图，先发「来点图」抽一张。")
        return
    if last_artwork == "owner_mismatch":
        await bot.send(event=event, message="🙅 只能评价自己触发的上一张图。")
        return

    if rating == "positive":
        await bot.send(event=event, message="👍 收到，已提高这类 TAG 的出图概率。")
    else:
        await bot.send(event=event, message="👎 收到，已降低这类 TAG 的出图概率。")


async def rate_jm_last_recommendation(bot, event, rating):
    key = jm_preference_key(event)
    result = update_jm_preference(key, rating, event)
    if not result:
        await bot.send(event=event, message="🤔 还没有可评价的 JM 推荐，先发「/jm推荐」。")
        return
    if result == "owner_mismatch":
        await bot.send(event=event, message="🙅 只能评价自己触发的上一批 JM 推荐。")
        return

    if rating == "positive":
        await bot.send(event=event, message="👍 收到，已提高这批 JM 漫画 TAG 的推荐概率。")
    else:
        await bot.send(event=event, message="👎 收到，已降低这批 JM 漫画 TAG 的推荐概率。")


async def rate_latest_preference(bot, event, rating):
    pixiv_time = pixiv_last_sent_at(pixiv_preference_key(event))
    jm_time = jm_last_sent_at(jm_preference_key(event))
    if pixiv_time <= 0 and jm_time <= 0:
        return None

    if pixiv_time >= jm_time:
        await rate_pixiv_last_artwork(bot, event, rating)
        return "pixiv"
    else:
        await rate_jm_last_recommendation(bot, event, rating)
        return "jm"


async def handle_pixiv_interactive_message(bot, event, text):
    if is_pixiv_adult_cancel_text(text):
        if cancel_pixiv_adult_verification(event):
            await bot.send(event=event, message="✅ 已取消你的 Pixiv R18/R18G 年龄确认记录。")
            return True
        return False

    if is_pixiv_adult_confirm_text(text):
        verify_pixiv_adult_user(event)
        await bot.send(event=event, message="✅ 已记录：你确认自己已满 18 岁。现在可以重新发送 Pixiv R18/R18G 请求。")
        return True

    if is_pixiv_random_prompt(text) or parse_pixiv_rating(text):
        allowed, message = check_event_access(event)
        if not allowed:
            await bot.send(event=event, message=message)
            return True

    random_tag = parse_pixiv_random_tag(text)
    if random_tag is not None:
        if not await ensure_bot_control_message(bot, event, "pixiv_random"):
            return True
        await send_pixiv_random_artwork(bot, event, random_tag)
        return True

    rating = parse_pixiv_rating(text)
    if rating:
        if not await ensure_bot_control_message(bot, event, "pixiv_rating"):
            return True
        if not has_pixiv_last_artwork(pixiv_preference_key(event)) and jm_last_sent_at(jm_preference_key(event)) <= 0:
            return False
        target = await rate_latest_preference(bot, event, rating)
        if target == "pixiv" and any(keyword in text.strip().lower() for keyword in ("换一张", "换张", "换图")):
            await send_pixiv_random_artwork(bot, event)
        return True

    return False


async def try_handle_jm_subscription(bot, event, matcher, text):
    """本地处理 JM 订阅指令（jm订阅/取消/列表），命中返回 True，不走 AI。"""
    text = (text or "").strip()
    if not text:
        return False

    destination_type, destination_id = jm_subscription_destination(event, text)

    async def send_subscription_list():
        subs = list_jm_subscriptions(destination_type, destination_id)
        if not subs:
            await matcher.send(
                "📭 你还没有订阅任何 JM 漫画。\n"
                "发「jm订阅 123456」即可关注更新；加「群发」订阅到本群。"
            )
            return
        lines = [f"📚 你的 JM 订阅（{len(subs)} 本）", "────────────"]
        for comic_id, meta in subs:
            lines.append(
                f"· 《{meta.get('title') or comic_id}》 编号 {comic_id} · 当前 {meta.get('chapter_count', 0)} 话"
            )
        lines.append("💡 发「jm取消 编号」退订")
        await matcher.send("\n".join(lines))

    # 状态/列表查询
    if text in JM_SUBSCRIBE_STATUS_PHRASES:
        if not await ensure_bot_control_message(bot, event, "jm_search"):
            return True
        await send_subscription_list()
        return True

    action = parse_jm_subscribe_action(text)
    if action is None:
        return False

    op, comic_id, _ = action
    if not await ensure_bot_control_message(bot, event, "jm_search"):
        return True

    # 裸「jm订阅」= 查看当前订阅
    if op == "subscribe" and not comic_id:
        await send_subscription_list()
        return True

    if op == "subscribe":
        try:
            added, entry = await asyncio.to_thread(
                add_jm_subscription, destination_type, destination_id, comic_id
            )
        except Exception as exc:
            await matcher.send(f"❌ 订阅失败：{exc}")
            return True
        if not added:
            await matcher.send(f"ℹ️ 你已经订阅过编号 {comic_id} 啦～")
            return True
        label = "本群" if destination_type == "group" else "私聊"
        await matcher.send(
            f"✅ 已订阅漫画更新（推送到{label}）：\n"
            f"📖《{entry.get('title') or comic_id}》\n"
            f"🔢 编号 {comic_id} · 当前 {entry.get('chapter_count', 0)} 话\n"
            f"🔄 有新章节时小鱼会来提醒你；发「jm取消 {comic_id}」退订。"
        )
        return True

    if op == "unsubscribe":
        if not comic_id:
            await matcher.send("ℹ️ 格式：jm取消 123456")
            return True
        removed = remove_jm_subscription(destination_type, destination_id, comic_id)
        if removed:
            await matcher.send(f"✅ 已退订漫画 {comic_id}，之后不会再推送它的更新。")
        else:
            await matcher.send(f"ℹ️ 你还没有订阅编号 {comic_id}。")
        return True

    return False


# 推送失败的「目标已失效」特征：机器人被移出群、群已解散、对方已注销等。
# 这类失败重试多少次都不会成功，继续留着订阅只会每天白报一次错（实测：
# 「发送失败，你已被移出该群，请重新加群。」），所以遇到就自动把订阅清掉。
PUSH_GONE_MARKERS = (
    "已被移出", "被移出", "重新加群", "不在该群", "不在群里", "群不存在",
    "群号无效", "不是好友", "user not found", "group not found", "not in group",
)


def push_target_gone(exc):
    """区分「推送目标已失效」和「网络抖动」——只有前者才该自动取消订阅。"""
    text = str(exc or "")
    lowered = text.lower()
    return any(marker in text or marker.lower() in lowered for marker in PUSH_GONE_MARKERS)


async def pixiv_daily_push_once():
    if not is_feature_enabled("pixiv_recommend"):
        return

    data = load_pixiv_subscriptions()
    destinations = pixiv_subscribers()
    if not destinations or not is_pixiv_daily_due(data):
        return

    bots = get_bots()
    if not bots:
        return

    bot = next(iter(bots.values()))
    for destination_type, destination_id in destinations:
        try:
            await send_pixiv_recommendations(bot, destination_type, destination_id, PIXIV_DAILY_COUNT)
        except Exception as exc:
            if push_target_gone(exc) and remove_pixiv_subscription(destination_type, destination_id):
                logger.warning(
                    f"Pixiv 日榜推送失败且目标已失效，已自动取消订阅 "
                    f"{destination_type}:{destination_id}：{exc}"
                )
            else:
                logger.warning(f"Pixiv daily push failed for {destination_type}:{destination_id}: {exc}")

    mark_pixiv_daily_sent()


async def pixiv_daily_push_loop():
    await asyncio.sleep(15)
    while True:
        try:
            await pixiv_daily_push_once()
        except Exception as exc:
            logger.warning(f"Pixiv daily push loop failed: {exc}")
        await asyncio.sleep(60)


def prune_expired_cache_files():
    """删除超过 CACHE_MAX_AGE_DAYS 天未使用的 qq/pixiv 临时缓存。返回删除数量。"""
    if CACHE_MAX_AGE_DAYS <= 0:
        return 0
    age_seconds = max(1.0, CACHE_MAX_AGE_DAYS) * 86400
    cutoff = time.time() - age_seconds
    removed = 0
    for base in (JM_QQ_CACHE_DIR, PIXIV_CACHE_DIR):
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                continue
        for dirpath, _dirnames, _filenames in os.walk(base, topdown=False):
            try:
                Path(dirpath).rmdir()
            except OSError:
                pass
    return removed


async def cache_prune_loop():
    await asyncio.sleep(30)
    while True:
        try:
            removed = await asyncio.to_thread(prune_expired_cache_files)
            if removed:
                logger.info(
                    f"缓存清理完成：删除 {removed} 个超过 {CACHE_MAX_AGE_DAYS:g} 天未使用的缓存文件。"
                )
        except Exception as exc:
            logger.warning(f"缓存清理失败: {exc}")
        await asyncio.sleep(6 * 3600)


async def refresh_jm_endpoints_once():
    """启动后主动刷新 JM 域名和图片地址，避免每次先撞一遍已失效的旧域名。"""
    await asyncio.sleep(5)
    try:
        await asyncio.to_thread(jm_api.refresh_api_domains)
        await asyncio.to_thread(jm_api.refresh_img_url)
    except Exception as exc:
        logger.warning(f"JM 域名刷新失败: {exc}")


async def push_jm_subscription_updates(updates):
    """把巡检到的漫画更新推送给对应订阅者/订阅群。"""
    bots = get_bots()
    if not bots:
        return
    bot = next(iter(bots.values()))
    for destination_type, destination_id, comic_id, title, old_count, new_count in updates:
        message = (
            f"📬 你订阅的漫画更新啦！\n"
            f"────────────\n"
            f"📖《{title}》\n"
            f"🔢 编号：{comic_id}\n"
            f"🆕 章节：{old_count} → {new_count}（新增 {new_count - old_count} 话）\n"
            f"💡 发「{comic_id} 文件」或「{comic_id} 图片」取最新内容"
        )
        try:
            if destination_type == "group":
                await bot.send_group_msg(group_id=int(destination_id), message=message)
            else:
                await bot.send_private_msg(user_id=int(destination_id), message=message)
        except Exception as exc:
            if push_target_gone(exc) and remove_jm_subscription(destination_type, destination_id, comic_id):
                logger.warning(
                    f"JM 订阅推送失败且目标已失效，已自动取消该订阅 "
                    f"{destination_type}:{destination_id} 漫画 {comic_id}：{exc}"
                )
            else:
                logger.warning(f"JM 订阅推送失败 {destination_type}:{destination_id}: {exc}")


async def jm_subscription_loop():
    """周期性巡检 JM 订阅漫画是否新增章节，有更新就推送。"""
    await asyncio.sleep(45)
    while True:
        try:
            updates = await asyncio.to_thread(check_jm_subscriptions)
            if updates:
                logger.info(f"JM 订阅检测到 {len(updates)} 个更新")
                await push_jm_subscription_updates(updates)
        except Exception as exc:
            logger.warning(f"JM 订阅巡检失败: {exc}")
        await asyncio.sleep(JM_SUBSCRIPTION_CHECK_SECONDS)


driver = get_driver()


@driver.on_startup
async def start_background_tasks():
    asyncio.create_task(pixiv_daily_push_loop())
    asyncio.create_task(cache_prune_loop())
    asyncio.create_task(refresh_jm_endpoints_once())
    asyncio.create_task(jm_subscription_loop())


def get_qq_download_dir(comic_id, title):
    return Path(__file__).resolve().parent / "download" / "qq" / f"{safe_filename(comic_id)}_{safe_filename(title)}"


async def download_image_thread(image_url, image_path):
    return await asyncio.to_thread(jm_api.download_image, image_url, image_path)


async def ensure_image_ready_thread(image_url, image_path):
    return await asyncio.to_thread(jm_api.ensure_image_decoded, image_url, image_path)


def prepare_comic_files(comic_id, image_limit=None, include_pages=True):
    comic_info = jm_api.load_comic_info(comic_id)
    title = comic_info.get("title") or comic_id
    download_dir = get_qq_download_dir(comic_id, title)
    download_dir.mkdir(parents=True, exist_ok=True)

    cover_path = download_dir / "cover.jpg"
    if not cover_path.exists() or cover_path.stat().st_size == 0:
        jm_api.download_image(comic_info["cover"], cover_path)

    image_paths = []
    if not include_pages:
        return DownloadResult(
            title=title,
            download_dir=download_dir,
            cover_path=cover_path,
            image_paths=image_paths,
        )

    chapters = comic_info.get("chapters") or {}
    for chapter_index, (chapter_id, chapter_title) in enumerate(chapters.items(), start=1):
        if image_limit is not None and len(image_paths) >= image_limit:
            break

        chapter_dir = download_dir / f"{chapter_index:03d}_{safe_filename(chapter_title, f'chapter_{chapter_id}')}"
        chapter_dir.mkdir(parents=True, exist_ok=True)

        chapter_images = jm_api.load_chapter_images(chapter_id)
        images = chapter_images.get("images") or []
        for image_index, image_url in enumerate(images, start=1):
            if image_limit is not None and len(image_paths) >= image_limit:
                break

            image_path = chapter_dir / f"{image_index:03d}.jpg"
            if not image_path.exists() or image_path.stat().st_size == 0:
                jm_api.download_image(image_url, image_path)
            else:
                jm_api.ensure_image_decoded(image_url, image_path)
            image_paths.append(image_path)

    return DownloadResult(
        title=title,
        download_dir=download_dir,
        cover_path=cover_path,
        image_paths=image_paths,
    )


def build_crc_table():
    table = []
    for value in range(256):
        crc = value
        for _ in range(8):
            if crc & 1:
                crc = 0xEDB88320 ^ (crc >> 1)
            else:
                crc >>= 1
        table.append(crc & 0xFFFFFFFF)
    return tuple(table)


CRC_TABLE = build_crc_table()


def crc32_update_byte(crc, value):
    return ((crc >> 8) ^ CRC_TABLE[(crc ^ value) & 0xFF]) & 0xFFFFFFFF


class ZipCrypto:
    def __init__(self, password):
        self.keys = [0x12345678, 0x23456789, 0x34567890]
        for value in password:
            self.update_keys(value)

    def update_keys(self, value):
        self.keys[0] = crc32_update_byte(self.keys[0], value)
        self.keys[1] = (self.keys[1] + (self.keys[0] & 0xFF)) & 0xFFFFFFFF
        self.keys[1] = (self.keys[1] * 134775813 + 1) & 0xFFFFFFFF
        self.keys[2] = crc32_update_byte(self.keys[2], (self.keys[1] >> 24) & 0xFF)

    def decrypt_byte(self):
        temp = self.keys[2] | 2
        return ((temp * (temp ^ 1)) >> 8) & 0xFF

    def encrypt(self, data):
        output = bytearray()
        for value in data:
            output.append(value ^ self.decrypt_byte())
            self.update_keys(value)
        return bytes(output)


def dos_time_date(timestamp):
    date = time.localtime(timestamp)
    year = min(2107, max(1980, date.tm_year))
    dos_time = (date.tm_hour << 11) | (date.tm_min << 5) | (date.tm_sec // 2)
    dos_date = ((year - 1980) << 9) | (date.tm_mon << 5) | date.tm_mday
    return dos_time, dos_date


def deflate_raw(data):
    compressor = zlib.compressobj(level=9, method=zlib.DEFLATED, wbits=-15)
    return compressor.compress(data) + compressor.flush()


def encrypt_zip_payload(data, password, crc):
    header = os.urandom(11) + bytes([(crc >> 24) & 0xFF])
    return ZipCrypto(password).encrypt(header + data)


def write_encrypted_zip(zip_path, members, password):
    password = str(password).encode("utf-8")
    zip_path = Path(zip_path)
    central_records = []
    flags = 0x0801  # encrypted + UTF-8 file names
    method = 8

    with zip_path.open("wb") as fp:
        for arcname, payload, timestamp in members:
            arcname = arcname.replace("\\", "/").lstrip("/")
            name_bytes = arcname.encode("utf-8")
            # payload 支持 Path：逐个成员读入，整包内存占用不超过单张图片大小
            data = payload.read_bytes() if isinstance(payload, Path) else bytes(payload)
            crc = zlib.crc32(data) & 0xFFFFFFFF
            compressed = deflate_raw(data)
            encrypted = encrypt_zip_payload(compressed, password, crc)
            compressed_size = len(encrypted)
            uncompressed_size = len(data)
            mod_time, mod_date = dos_time_date(timestamp)
            local_offset = fp.tell()

            local_header = struct.pack(
                "<IHHHHHIIIHH",
                0x04034B50,
                20,
                flags,
                method,
                mod_time,
                mod_date,
                crc,
                compressed_size,
                uncompressed_size,
                len(name_bytes),
                0,
            )
            fp.write(local_header)
            fp.write(name_bytes)
            fp.write(encrypted)

            central_records.append(
                struct.pack(
                    "<IHHHHHHIIIHHHHHII",
                    0x02014B50,
                    20,
                    20,
                    flags,
                    method,
                    mod_time,
                    mod_date,
                    crc,
                    compressed_size,
                    uncompressed_size,
                    len(name_bytes),
                    0,
                    0,
                    0,
                    0,
                    0x20,
                    local_offset,
                )
                + name_bytes
            )

        central_offset = fp.tell()
        for record in central_records:
            fp.write(record)
        central_size = fp.tell() - central_offset
        fp.write(
            struct.pack(
                "<IHHHHIIH",
                0x06054B50,
                0,
                0,
                len(central_records),
                len(central_records),
                central_size,
                central_offset,
                0,
            )
        )


def comic_zip_name(comic_id, title, page_limit):
    limit_tag = "all" if page_limit is None else f"{page_limit}p"
    return f"{safe_filename(comic_id)}_{safe_filename(title)}_{limit_tag}.zip"


def _zip_input_files(result):
    files = []
    if result.cover_path.exists():
        files.append(result.cover_path)
    files.extend(path for path in result.image_paths if path.exists())
    return files


def comic_zip_is_fresh(zip_path, result):
    """已存在的压缩包是否比所有源图片都新，是的话可以跳过重新打包。"""
    try:
        if not zip_path.exists() or zip_path.stat().st_size == 0:
            return False
        zip_mtime = zip_path.stat().st_mtime_ns
    except OSError:
        return False

    for path in _zip_input_files(result):
        try:
            if path.stat().st_mtime_ns > zip_mtime:
                return False
        except OSError:
            return False
    return True


def build_comic_zip(result, comic_id, page_limit=None, force=False):
    zip_name = comic_zip_name(comic_id, result.title, page_limit)
    zip_path = result.download_dir / zip_name

    if not force and comic_zip_is_fresh(zip_path, result):
        return zip_path

    now = time.time()
    members = []
    if result.cover_path.exists():
        members.append(("000_cover.jpg", result.cover_path, result.cover_path.stat().st_mtime))
    for image_path in result.image_paths:
        if image_path.exists():
            members.append(
                (
                    image_path.relative_to(result.download_dir).as_posix(),
                    image_path,
                    image_path.stat().st_mtime,
                )
            )
    members.append(
        (
            "info.txt",
            (
                f"title: {result.title}\n"
                f"comic_id: {comic_id}\n"
                f"pages: {len(result.image_paths)}\n"
                f"zip_password: {comic_id}\n"
            ).encode("utf-8"),
            now,
        )
    )

    write_encrypted_zip(zip_path, members, password=comic_id)

    return zip_path


async def send_file_to_requester(bot, event, file_path, display_name, delivery_mode="private"):
    file_path = str(Path(file_path).resolve())
    errors = []

    if isinstance(event, GroupMessageEvent) and delivery_mode == "group":
        try:
            await bot.call_api(
                "upload_group_file",
                group_id=event.group_id,
                file=file_path,
                name=display_name,
            )
            return True
        except Exception as exc:
            errors.append(f"群文件上传失败：{exc}")
    elif isinstance(event, GroupMessageEvent):
        try:
            await bot.call_api(
                "upload_private_file",
                user_id=event.user_id,
                file=file_path,
                name=display_name,
            )
            return True
        except Exception as exc:
            errors.append(f"私聊文件上传失败：{exc}")

        try:
            await bot.call_api(
                "upload_group_file",
                group_id=event.group_id,
                file=file_path,
                name=display_name,
            )
            await notify_current_chat(bot, event, "私聊文件上传失败，已改为上传到当前群文件。")
            return True
        except Exception as exc:
            errors.append(f"群文件上传失败：{exc}")
    else:
        try:
            await bot.call_api(
                "upload_private_file",
                user_id=event.user_id,
                file=file_path,
                name=display_name,
            )
            return True
        except Exception as exc:
            errors.append(f"私聊文件上传失败：{exc}")

    await send_to_requester(
        bot,
        event,
        "⚠️ 文件已生成，但 QQ 上传失败。\n"
        f"📁 本地文件：{file_path}\n"
        f"💥 错误：{'；'.join(errors)}",
        delivery_mode,
    )
    return False


_comic_build_locks: dict[str, asyncio.Lock] = {}


def get_comic_build_lock(key):
    """同一本漫画的打包任务串行执行，避免并发重复下载/重复打包互相踩文件。"""
    lock = _comic_build_locks.get(key)
    if lock is None:
        lock = _comic_build_locks.setdefault(key, asyncio.Lock())
    return lock


async def send_comic_file_to_requester(bot, event, request):
    include_pages = not request.cover_only
    page_limit = None if request.page_limit is None else max(0, request.page_limit)

    if isinstance(event, GroupMessageEvent):
        mode_text = "上传到当前群" if request.delivery_mode == "group" else "私聊发给请求者"
        await notify_current_chat(
            bot,
            event,
            f"📦 已收到漫画 {request.comic_id}，开始打包加密文件。完成后会{mode_text}。",
        )

    await send_to_requester(
        bot,
        event,
        f"📦 开始打包：{request.comic_id}\n"
        f"🔑 压缩包密码：{request.comic_id}",
        request.delivery_mode,
    )
    async with get_comic_build_lock(f"file:{request.comic_id}"):
        result = await asyncio.to_thread(
            prepare_comic_files,
            request.comic_id,
            page_limit,
            include_pages,
        )
        zip_path = await asyncio.to_thread(build_comic_zip, result, request.comic_id, page_limit)
    await send_to_requester(
        bot,
        event,
        f"✅ 打包完成：《{result.title}》\n"
        f"📄 页数：{len(result.image_paths)} ｜ 🔑 密码：{request.comic_id}\n"
        "🚀 正在上传文件...",
        request.delivery_mode,
    )
    await send_file_to_requester(bot, event, zip_path, zip_path.name, request.delivery_mode)
    record_jm_viewed(event, request.comic_id, result.title)
    return zip_path


async def stream_comic_to_requester(bot, event, request):
    comic_info = await asyncio.to_thread(jm_api.load_comic_info, request.comic_id)
    title = comic_info.get("title") or request.comic_id
    record_jm_viewed(event, request.comic_id, title)
    download_dir = get_qq_download_dir(request.comic_id, title)
    download_dir.mkdir(parents=True, exist_ok=True)

    cover_path = download_dir / "cover.jpg"
    if not cover_path.exists() or cover_path.stat().st_size == 0:
        await download_image_thread(comic_info["cover"], cover_path)

    if isinstance(event, GroupMessageEvent):
        if request.delivery_mode == "group":
            notice = f"📬 已收到漫画 {request.comic_id}，开始在本群发送。"
        else:
            notice = f"📬 已收到漫画 {request.comic_id}，开始私聊发送给你。若收不到，请先添加机器人为好友。"
        await notify_current_chat(
            bot,
            event,
            notice,
        )

    await send_to_requester(bot, event, f"📚 开始发送：《{title}》\n🔢 编号：{request.comic_id}", request.delivery_mode)
    await send_to_requester(bot, event, MessageSegment.image(path_to_onebot_uri(cover_path)), request.delivery_mode)

    if request.cover_only:
        await send_to_requester(bot, event, "✅ 封面发送完成。", request.delivery_mode)
        return 0

    sent_pages = 0
    chapters = comic_info.get("chapters") or {}
    for chapter_index, (chapter_id, chapter_title) in enumerate(chapters.items(), start=1):
        if request.page_limit is not None and sent_pages >= request.page_limit:
            break

        await send_to_requester(
            bot,
            event,
            f"📖 章节 {chapter_index}/{len(chapters)}：{chapter_title}",
            request.delivery_mode,
        )
        chapter_dir = download_dir / f"{chapter_index:03d}_{safe_filename(chapter_title, f'chapter_{chapter_id}')}"
        chapter_dir.mkdir(parents=True, exist_ok=True)

        chapter_images = await asyncio.to_thread(jm_api.load_chapter_images, chapter_id)
        images = list(chapter_images.get("images") or [])
        prefetch_task = None
        for image_index, image_url in enumerate(images, start=1):
            if request.page_limit is not None and sent_pages >= request.page_limit:
                break

            image_path = chapter_dir / f"{image_index:03d}.jpg"
            if prefetch_task is not None:
                await prefetch_task
                prefetch_task = None
            elif not image_path.exists() or image_path.stat().st_size == 0:
                await download_image_thread(image_url, image_path)
            else:
                await ensure_image_ready_thread(image_url, image_path)

            # 发送当前页的同时预取下一页，隐藏网络延迟
            next_image_index = image_index + 1
            if next_image_index <= len(images) and (
                request.page_limit is None or sent_pages + 1 < request.page_limit
            ):
                next_url = images[next_image_index - 1]
                next_path = chapter_dir / f"{next_image_index:03d}.jpg"
                if not next_path.exists() or next_path.stat().st_size == 0:
                    prefetch_task = asyncio.create_task(download_image_thread(next_url, next_path))
                else:
                    prefetch_task = asyncio.create_task(ensure_image_ready_thread(next_url, next_path))

            await send_to_requester(bot, event, MessageSegment.image(path_to_onebot_uri(image_path)), request.delivery_mode)
            sent_pages += 1
            if SEND_DELAY_SECONDS > 0:
                await asyncio.sleep(SEND_DELAY_SECONDS)

        if prefetch_task is not None and not prefetch_task.done():
            prefetch_task.cancel()

    await send_to_requester(bot, event, f"🎉 发送完成：《{title}》\n📄 共发送 {sent_pages} 页。", request.delivery_mode)
    return sent_pages


async def run_comic_request(bot, event, matcher, request):
    if request.cover_only:
        desc = "只发封面"
    elif request.page_limit is None:
        desc = "全册"
    else:
        desc = f"前 {request.page_limit} 页"

    output_desc = "文件" if request.output_mode == "file" else "图片"
    delivery_desc = "群发" if request.delivery_mode == "group" else "私发"
    await matcher.send(
        f"📥 收到请求：{request.comic_id}\n"
        f"🎁 输出：{output_desc} ｜ 📮 发送：{delivery_desc} ｜ 📄 范围：{desc}"
    )

    key = pixiv_preference_key(event)
    # 记住最近一次漫画请求：bot 发完消息后用户说「私发/群发/文件/图片/封面」能按新方式重发
    remember_last_task(
        key,
        type="comic",
        comic_id=request.comic_id,
        page_limit=request.page_limit,
        cover_only=request.cover_only,
        output_mode=request.output_mode,
        delivery_mode=request.delivery_mode,
    )
    remember_ongoing_task(
        key,
        f"正在下载漫画 {request.comic_id}（{output_desc}）",
        tag="comic",
    )
    try:
        if request.output_mode == "file":
            await send_comic_file_to_requester(bot, event, request)
        else:
            await stream_comic_to_requester(bot, event, request)
    finally:
        forget_ongoing_task(key)


def cover_cache_path(comic):
    comic_id = str(comic.get("id") or "").strip()
    if not comic_id:
        return None
    return COVER_CACHE_DIR / f"{safe_filename(comic_id)}.jpg"


async def send_comic_covers(matcher, comics, count):
    """给搜索结果/推荐附带封面预览图；单张失败不影响文字结果。"""
    sent = 0
    for comic in comics[:count]:
        cover = comic.get("cover")
        if not cover:
            continue
        path = cover_cache_path(comic)
        if path is None:
            continue
        try:
            if not path.exists() or path.stat().st_size == 0:
                await asyncio.to_thread(jm_api.download_image, cover, path)
            await matcher.send(MessageSegment.image(path_to_onebot_uri(path)))
            sent += 1
        except Exception:
            continue
        if SEND_DELAY_SECONDS > 0:
            await asyncio.sleep(SEND_DELAY_SECONDS)
    return sent


def format_comic_detail(comic_id, comic):
    """把 load_comic_info 的结果整理成详情卡片。"""
    title = comic.get("title") or "未命名"
    tags = comic.get("tags") if isinstance(comic.get("tags"), dict) else {}
    author = "、".join(tags.get("Author") or []) or "未知"
    tag_list = "、".join(tags.get("Tag") or []) or "无"
    work_list = "、".join(tags.get("Work") or [])
    actor_list = "、".join(tags.get("Actor") or [])
    chapter_count = len(comic.get("chapters") or {})
    update_time = comic.get("updateTime") or "未知"
    likes = comic.get("likesCount") or 0
    description = (comic.get("description") or "").strip()

    lines = ["📖 漫画详情", "────────────", f"《{title}》"]
    lines.append(f"🔢 编号：{comic_id}")
    lines.append(f"👤 作者：{author}")
    lines.append(f"🏷 标签：{tag_list}")
    if work_list:
        lines.append(f"📚 系列：{work_list}")
    if actor_list:
        lines.append(f"🎭 演员：{actor_list}")
    lines.append(f"📄 章节数：{chapter_count} 话")
    lines.append(f"🕒 更新时间：{update_time}")
    lines.append(f"❤️ 点赞：{likes}")
    if description:
        lines.append(f"📝 简介：{short_text(description, 120)}")
    lines.append("\n💡 发「编号 文件」下载 ｜ 发「编号 图片」逐页看 ｜ 发「编号 封面」只看封面")
    return "\n".join(lines)


async def send_comic_detail(matcher, comic_id):
    """查询并发送某本漫画的详情卡片 + 封面。"""
    comic_id = comic_id.strip().lower()
    if comic_id.startswith("jm"):
        comic_id = comic_id[2:]
    if not comic_id:
        await matcher.send("ℹ️ 格式：jm详情 123456")
        return

    await matcher.send(f"🔍 正在查询漫画 {comic_id} 详情...")
    try:
        info = await asyncio.to_thread(jm_api.load_comic_info, comic_id)
    except Exception as exc:
        await matcher.send(f"❌ 查询详情失败：{exc}")
        return

    await matcher.send(format_comic_detail(comic_id, info))
    cover = info.get("cover")
    if cover:
        try:
            path = cover_cache_path({"id": comic_id, "cover": cover})
            if path is not None:
                if not path.exists() or path.stat().st_size == 0:
                    await asyncio.to_thread(jm_api.download_image, cover, path)
                await matcher.send(MessageSegment.image(path_to_onebot_uri(path)))
        except Exception:
            pass


VIEWED_HISTORY_PHRASES = ("我的历史", "最近看过", "浏览历史", "我的浏览", "看过什么", "下载历史")


async def send_viewed_history(matcher, event):
    """展示该会话最近浏览/下载过的漫画记录。"""
    key = jm_preference_key(event)
    data = load_jm_preferences()
    profile = get_jm_profile(data, key)
    viewed = profile.get("viewed") or []
    if not viewed:
        await matcher.send("🤔 你还没有下载/浏览过漫画，发「编号 文件」或「编号 图片」试试吧～")
        return
    lines = [f"📚 你最近看过的漫画（{len(viewed)} 本）", "────────────"]
    for item in viewed:
        comic_id = item.get("id") or "未知"
        title = short_text(item.get("title") or "未命名", 30)
        lines.append(f"· 《{title}》 编号 {comic_id}")
    lines.append("\n💡 想看就发「编号 文件」或「编号 图片」")
    await matcher.send("\n".join(lines))


def format_category_list(cats):
    """格式化 JM 分类列表（跳过特殊聚合分类）。"""
    lines = ["🗂 JM 漫画分类", "────────────"]
    shown = 0
    for cat in cats or []:
        cid = str(cat.get("id") or "")
        name = (cat.get("name") or "").strip()
        if not name or cid == "0":
            continue
        try:
            total_int = int(cat.get("total_albums") or 0)
        except (TypeError, ValueError):
            total_int = 0
        total_text = f" · {total_int:,} 本" if total_int else ""
        lines.append(f"· {name}{total_text}")
        shown += 1
    if shown == 0:
        lines.append("(分类列表为空)")
    lines.append("\n💡 发「分类 名称」浏览，如「分类 韩漫」；加「第2页」翻页")
    return "\n".join(lines)


def format_category_comics(name, result, page):
    """格式化某个分类下的漫画列表。"""
    comics = result.get("comics") or []
    if not comics:
        return f"🗂 分类「{name}」这一页没有更多内容啦，换个分类试试吧～"
    try:
        max_page = max(1, int(result.get("maxPage") or 1))
    except (TypeError, ValueError):
        max_page = 1

    shown = comics[:10]
    page_tag = f"（第 {page}/{max_page} 页）" if max_page > 1 else ""
    lines = [f"🗂 分类「{name}」 · 前 {len(shown)} 本{page_tag}"]
    for index, comic in enumerate(shown, start=1):
        comic_id = comic.get("id") or "未知"
        title = short_text(comic.get("title") or "未命名")
        author = short_text(comic.get("subTitle") or "未知", 20)
        lines.append(f"\n{number_emoji(index)} 编号 {comic_id} ·《{title}》")
        lines.append(f"　　👤 {author}")
    lines.append("\n💡 发「编号 文件」下载 ｜ 发「编号 详情」看简介")
    if max_page > 1 and page < max_page:
        lines.append(f"💡 看更多发「分类 {name} 第{page + 1}页」")
    return "\n".join(lines)


async def send_category_list(matcher):
    """发送 JM 分类列表。"""
    await matcher.send("🗂 正在加载分类列表...")
    try:
        cats = await asyncio.to_thread(jm_api.get_categories)
    except Exception as exc:
        await matcher.send(f"❌ 加载分类失败：{exc}")
        return
    await matcher.send(format_category_list(cats))


async def send_category_comics(matcher, name, page=1):
    """浏览某个分类下的漫画。name 为空时回退到分类列表。"""
    name = (name or "").strip()
    if not name:
        await send_category_list(matcher)
        return

    page = max(1, int(page or 1))
    category_id = await asyncio.to_thread(resolve_category_id, name)
    if category_id is None:
        await matcher.send(f"🤔 没找到分类「{name}」。发「分类」查看有哪些分类。")
        return

    await matcher.send(f"🗂 正在浏览分类「{name}」...")
    try:
        result = await asyncio.to_thread(jm_api.load_category_comics, category_id, "mv_t", page)
    except Exception as exc:
        await matcher.send(f"❌ 浏览分类失败：{exc}")
        return
    await matcher.send(format_category_comics(name, result, page))


def short_text(value, limit=40):
    value = str(value or "").strip()
    return value if len(value) <= limit else value[:limit] + "…"


def format_search_results(keyword, result, covers=None, page=1):
    covers = SEARCH_SEND_COVERS if covers is None else covers
    comics = result.get("comics") or []
    if not comics:
        if page > 1:
            return "🔍 这一页没有更多结果啦，换个关键词或回到第 1 页试试吧～"
        return "🔍 没有找到相关漫画，换个关键词试试吧～"

    try:
        max_page = max(1, int(result.get("maxPage") or 1))
    except (TypeError, ValueError):
        max_page = 1

    shown = comics[:10]
    page_tag = f"（第 {page}/{max_page} 页）" if max_page > 1 else ""
    lines = [f"🔍 搜索「{keyword}」 · 前 {len(shown)} 个相关编号{page_tag}"]
    for index, comic in enumerate(shown, start=1):
        comic_id = comic.get("id") or ""
        title = short_text(comic.get("title") or "未命名")
        author = short_text(comic.get("subTitle") or "未知", 20)
        tags = "、".join(comic.get("tags") or [])
        lines.append(f"\n{number_emoji(index)} 编号 {comic_id} ·《{title}》")
        lines.append(f"　　👤 {author}" + (f" ｜ 🏷 {tags}" if tags else ""))
    lines.append("\n💡 发「编号 文件」取加密 zip，发「编号 图片」逐页看图")
    if max_page > 1 and page < max_page:
        lines.append(f"💡 看更多结果发「搜索 {keyword} 第{page + 1}页」")
    if covers > 0:
        lines.append(f"🖼 正在发送前 {min(covers, len(shown))} 个封面预览...")
    return "\n".join(lines)


async def search_and_send(matcher, keyword, send_covers=None, page=1, event=None):
    covers = SEARCH_SEND_COVERS if send_covers is None else (SEARCH_SEND_COVERS if send_covers else 0)
    if not keyword:
        await matcher.send("🔍 请输入关键词，例如：/jm搜索 女仆")
        return

    page = max(1, int(page or 1))
    page_hint = f"（第 {page} 页）" if page > 1 else ""
    await matcher.send(f"🔍 正在搜索：{keyword}{page_hint}")
    result = await asyncio.to_thread(jm_api.search_comics, keyword, page)
    await matcher.send(format_search_results(keyword, result, covers, page))
    if covers > 0:
        comics = result.get("comics") or []
        if comics:
            await send_comic_covers(matcher, comics, covers)
    # 记住最近一次搜索：bot 发完消息后用户说「第2页/下一页」能续着翻页
    if event is not None:
        remember_last_task(
            pixiv_preference_key(event),
            type="search",
            keyword=keyword,
            page=page,
        )


def format_random_recommendations(comics, covers=None, keyword=None):
    covers = RECOMMEND_SEND_COVERS if covers is None else covers
    header = f"🎲 随机推荐 · 按「{keyword}」挑了这些" if keyword else "🎲 随机推荐 · 按你的口味挑了这些"
    lines = [header]
    for index, comic in enumerate(comics, start=1):
        title = comic.get("title") or "未命名"
        comic_id = comic.get("id") or "未知"
        tags = "、".join(comic.get("tags") or []) or "无"
        lines.append(f"\n{number_emoji(index)}《{title}》")
        lines.append(f"　　📖 编号 {comic_id}")
        lines.append(f"　　🏷 TAG：{tags}")
    lines.append("\n💡 想看就发「编号 文件」或「编号 图片」")
    if covers > 0:
        lines.append("🖼 正在发送封面预览...")
    return "\n".join(lines)


async def random_recommend_and_send(matcher, event, send_covers=None, keyword=None):
    covers = RECOMMEND_SEND_COVERS if send_covers is None else (RECOMMEND_SEND_COVERS if send_covers else 0)
    key = jm_preference_key(event)
    data = load_jm_preferences()
    profile = get_jm_profile(data, key)
    if keyword:
        await matcher.send(f"🎲 正在按「{keyword}」挑选漫画...")
        search_result = await asyncio.to_thread(jm_api.search_comics, keyword)
        candidates = search_result.get("comics") or []
    else:
        await matcher.send("🎲 正在按你的口味挑选...")
        candidates = await asyncio.to_thread(jm_api.random_pool, JM_RANDOM_POOL_SIZE)
    comics = choose_jm_comics(candidates, profile, 5)
    if not comics:
        await matcher.send("😢 没找到合适的漫画，换个关键词试试吧～")
        return
    store_jm_last_comics(key, comics, event)
    remember_last_task(key, type="recommend", keyword=keyword or "")
    await matcher.send(format_random_recommendations(comics, covers, keyword))
    if covers > 0:
        await send_comic_covers(matcher, comics, covers)


def download_comic(comic_id, image_limit=DEFAULT_SEND_IMAGE_LIMIT):
    """下载漫画"""
    # 创建下载目录
    safe_comic_id = safe_filename(comic_id)
    download_dir = Path(__file__).resolve().parent / "download" / safe_comic_id
    download_dir.mkdir(parents=True, exist_ok=True)
    
    # 获取漫画信息
    comic_info = jm_api.load_comic_info(comic_id)
    
    # 下载封面
    cover_url = comic_info['cover']
    cover_path = download_dir / "cover.jpg"
    jm_api.download_image(cover_url, cover_path)
    
    # 下载每个章节
    image_paths = []
    chapters = comic_info['chapters']
    for chapter_id, chapter_title in chapters.items():
        chapter_dir = download_dir / safe_filename(chapter_title, f"chapter_{chapter_id}")
        chapter_dir.mkdir(parents=True, exist_ok=True)
        
        # 获取章节图片
        chapter_images = jm_api.load_chapter_images(chapter_id)
        images = chapter_images['images']
        
        # 下载每张图片
        for i, image_url in enumerate(images):
            if image_limit is not None and len(image_paths) >= image_limit:
                return DownloadResult(
                    title=comic_info.get('title') or comic_id,
                    download_dir=download_dir,
                    cover_path=cover_path,
                    image_paths=image_paths,
                )

            image_path = chapter_dir / f"{i+1:03d}.jpg"
            if not image_path.exists() or image_path.stat().st_size == 0:
                jm_api.download_image(image_url, image_path)
            else:
                jm_api.ensure_image_decoded(image_url, image_path)
            image_paths.append(image_path)
    
    return DownloadResult(
        title=comic_info.get('title') or comic_id,
        download_dir=download_dir,
        cover_path=cover_path,
        image_paths=image_paths,
    )

@download_cmd.handle()
async def handle_download(event: MessageEvent, msg: Message = CommandArg()):
    if not await ensure_bot_control(download_cmd, event, "jm_image"):
        return

    arg_text = msg.extract_plain_text().strip()
    if not arg_text:
        await download_cmd.send("ℹ️ 请输入要下载的漫画ID，格式：下载漫画 <漫画ID>")
        return
    
    try:
        comic_id, send_limit = parse_download_args(arg_text)
    except ValueError as e:
        await download_cmd.send(f"❌ 参数错误：{e}")
        return

    if not comic_id:
        await download_cmd.send("❌ 请输入有效的漫画ID！")
        return
    
    await download_cmd.send(f"📥 开始下载漫画 ID：{comic_id}...")
    
    try:
        # 下载漫画
        result = await asyncio.to_thread(download_comic, comic_id, send_limit)
        await download_cmd.send(f"✅ 下载成功：《{result.title}》\n📁 本地路径：{result.download_dir}")

        await download_cmd.send(MessageSegment.image(path_to_onebot_uri(result.cover_path)))
        for image_path in result.image_paths:
            await download_cmd.send(MessageSegment.image(path_to_onebot_uri(image_path)))

        if not result.image_paths:
            await download_cmd.send("⚠️ 未获取到章节图片。")
        elif send_limit is not None:
            await download_cmd.send(f"📄 已发送前 {len(result.image_paths)} 张图片；如需全部发送：下载漫画 {comic_id} all")
    except Exception as e:
        await download_cmd.send(f"❌ 下载失败！错误原因：{str(e)}")


@help_cmd.handle()
async def handle_help():
    await help_cmd.send(HELP_MENU)


@recommend_cmd.handle()
async def handle_recommend(event: MessageEvent, msg: Message = CommandArg()):
    if not await ensure_bot_control(recommend_cmd, event, "jm_recommend"):
        return

    raw = msg.extract_plain_text().strip()
    keyword = parse_recommend_keyword(raw) or None
    try:
        await random_recommend_and_send(recommend_cmd, event, keyword=keyword)
    except Exception as e:
        await recommend_cmd.send(f"❌ 随机推荐失败：{str(e)}")


@pixiv_recommend_cmd.handle()
async def handle_pixiv_recommend(bot: Bot, event: MessageEvent, msg: Message = CommandArg()):
    if not await ensure_bot_control(pixiv_recommend_cmd, event, "pixiv_recommend"):
        return

    arg_text = msg.extract_plain_text().strip()
    destination_type, destination_id = resolve_pixiv_destination(event, arg_text)

    if isinstance(event, GroupMessageEvent) and destination_type == "private":
        await pixiv_recommend_cmd.send("📨 开始私发 Pixiv 推荐给你；如果收不到，请先添加机器人为好友。")
    else:
        await pixiv_recommend_cmd.send("🎨 开始获取 Pixiv 日榜推荐。")

    try:
        await send_pixiv_recommendations(bot, destination_type, destination_id, PIXIV_DAILY_COUNT)
    except Exception as e:
        await pixiv_recommend_cmd.send(f"❌ Pixiv 推荐失败：{str(e)}")


@pixiv_tag_cmd.handle()
async def handle_pixiv_tag(bot: Bot, event: MessageEvent, msg: Message = CommandArg()):
    if not await ensure_bot_control(pixiv_tag_cmd, event, "pixiv_search"):
        return

    tag = msg.extract_plain_text().strip()
    try:
        await send_pixiv_tag_search(bot, event, tag, 5)
    except Exception as e:
        await pixiv_tag_cmd.send(f"❌ Pixiv TAG 搜索失败：{str(e)}")


@pixiv_pid_cmd.handle()
async def handle_pixiv_pid(bot: Bot, event: MessageEvent, msg: Message = CommandArg()):
    if not await ensure_bot_control(pixiv_pid_cmd, event, "pixiv_search"):
        return

    pid = msg.extract_plain_text().strip()
    try:
        await send_pixiv_pid_search(bot, event, pid)
    except Exception as e:
        await pixiv_pid_cmd.send(f"❌ Pixiv PID 搜索失败：{str(e)}")


@pixiv_subscribe_cmd.handle()
async def handle_pixiv_subscribe(event: MessageEvent, msg: Message = CommandArg()):
    if not await ensure_bot_control(pixiv_subscribe_cmd, event, "pixiv_recommend"):
        return

    arg_text = msg.extract_plain_text().strip()
    destination_type, destination_id = resolve_pixiv_destination(event, arg_text)
    added = add_pixiv_subscription(destination_type, destination_id)
    label = pixiv_destination_label(destination_type, destination_id)
    if added:
        await pixiv_subscribe_cmd.send(
            f"✅ 已订阅 Pixiv 每日自动推送：{label}\n"
            f"⏰ 每天 {PIXIV_DAILY_TIME} 左右发送 {PIXIV_DAILY_COUNT} 张日榜预览图。"
        )
    else:
        await pixiv_subscribe_cmd.send(f"ℹ️ {label} 已经订阅过 Pixiv 自动推送啦～")


@pixiv_unsubscribe_cmd.handle()
async def handle_pixiv_unsubscribe(event: MessageEvent, msg: Message = CommandArg()):
    if not await ensure_bot_control(pixiv_unsubscribe_cmd, event, "pixiv_recommend"):
        return

    arg_text = msg.extract_plain_text().strip()
    destination_type, destination_id = resolve_pixiv_destination(event, arg_text)
    removed = remove_pixiv_subscription(destination_type, destination_id)
    label = pixiv_destination_label(destination_type, destination_id)
    if removed:
        await pixiv_unsubscribe_cmd.send(f"✅ 已取消 Pixiv 自动推送：{label}")
    else:
        await pixiv_unsubscribe_cmd.send(f"ℹ️ {label} 没有 Pixiv 自动推送订阅记录。")


@pixiv_status_cmd.handle()
async def handle_pixiv_status(event: MessageEvent):
    if not await ensure_bot_control(pixiv_status_cmd, event, "pixiv_recommend"):
        return

    data = load_pixiv_subscriptions()
    private_count = len(data["private"])
    group_count = len(data["group"])
    await pixiv_status_cmd.send(
        f"📮 Pixiv 自动推送状态\n"
        "────────────\n"
        f"📨 私发订阅：{private_count}\n"
        f"👥 群发订阅：{group_count}\n"
        f"⏰ 发送时间：每天 {PIXIV_DAILY_TIME} 左右\n"
        f"🖼 每次数量：{PIXIV_DAILY_COUNT} 张"
    )


@jm_subscribe_cmd.handle()
async def handle_jm_subscribe(bot: Bot, event: MessageEvent, msg: Message = CommandArg()):
    arg_text = msg.extract_plain_text().strip()
    # 复用文本指令处理器，保持斜杠命令与 @ 指令行为一致
    await try_handle_jm_subscription(bot, event, jm_subscribe_cmd, "jm订阅 " + arg_text)


@jm_unsubscribe_cmd.handle()
async def handle_jm_unsubscribe(bot: Bot, event: MessageEvent, msg: Message = CommandArg()):
    arg_text = msg.extract_plain_text().strip()
    await try_handle_jm_subscription(bot, event, jm_unsubscribe_cmd, "jm取消 " + arg_text)


@jm_subscribe_status_cmd.handle()
async def handle_jm_subscribe_status(bot: Bot, event: MessageEvent):
    await try_handle_jm_subscription(bot, event, jm_subscribe_status_cmd, "jm订阅状态")


@jm_detail_cmd.handle()
async def handle_jm_detail(event: MessageEvent, msg: Message = CommandArg()):
    if not await ensure_bot_control(jm_detail_cmd, event, "jm_search"):
        return
    raw = msg.extract_plain_text().strip()
    match = COMIC_ID_PATTERN.search(_cjk_digit_space(raw))
    comic_id = match.group(1) if match else ""
    if not comic_id:
        await jm_detail_cmd.send("ℹ️ 格式：jm详情 123456")
        return
    await send_comic_detail(jm_detail_cmd, comic_id)


@category_cmd.handle()
async def handle_category(event: MessageEvent, msg: Message = CommandArg()):
    if not await ensure_bot_control(category_cmd, event, "jm_search"):
        return
    parsed = parse_category_command(msg.extract_plain_text().strip())
    name, page = parsed if parsed is not None else ("", 1)
    await send_category_comics(category_cmd, name, page)


@pixiv_age_cmd.handle()
async def handle_pixiv_age(bot: Bot, event: MessageEvent, msg: Message = CommandArg()):
    if not await ensure_bot_control(pixiv_age_cmd, event, "pixiv_search"):
        return

    text = msg.extract_plain_text().strip()
    if is_pixiv_adult_cancel_text(text):
        if cancel_pixiv_adult_verification(event):
            await pixiv_age_cmd.send("✅ 已取消你的 Pixiv R18/R18G 年龄确认记录。")
        else:
            await pixiv_age_cmd.send("ℹ️ 你当前没有 Pixiv R18/R18G 年龄确认记录。")
        return

    if is_pixiv_adult_confirm_text(text):
        verify_pixiv_adult_user(event)
        await pixiv_age_cmd.send("✅ 已记录：你确认自己已满 18 岁。之后你主动请求 Pixiv R18/R18G 内容时才会放行。")
        return

    if is_pixiv_adult_verified(event):
        await pixiv_age_cmd.send("✅ 你已经完成 Pixiv R18/R18G 年龄确认。发送「取消18认证」可以撤销。")
        return

    mark_pixiv_adult_pending(event)
    await pixiv_age_cmd.send(
        "🔞 Pixiv R18/R18G 内容需要先确认年龄。若你已满 18 岁，请回复「我已满18岁」；"
        "确认前不会发送成人内容。"
    )


@pixiv_login_cmd.handle()
async def handle_pixiv_login(event: MessageEvent):
    if not await ensure_bot_control(pixiv_login_cmd, event, "pixiv_search"):
        return

    await pixiv_login_cmd.send("🔍 正在检测 Pixiv 登录状态...")
    ok, message = await asyncio.to_thread(pixiv_api.check_login)
    if ok:
        await pixiv_login_cmd.send(f"✅ Pixiv 登录状态：{message}")
    else:
        await pixiv_login_cmd.send(
            f"⚠️ Pixiv 登录状态：{message}\n"
            "配置方法见项目根目录《Pixiv登录Cookie获取教程.md》，填好后重启机器人即可。"
        )


@pixiv_interactive_cmd.handle()
async def handle_pixiv_interactive(bot: Bot, event: MessageEvent):
    text = event.get_message().extract_plain_text().strip()
    if not text:
        return
    await handle_pixiv_interactive_message(bot, event, text)


@image_cmd.handle()
async def handle_image_command(bot: Bot, event: MessageEvent, msg: Message = CommandArg()):
    request = parse_mode_command_request(msg.extract_plain_text().strip(), "image")
    if request is None:
        await image_cmd.send("ℹ️ 格式：/jm图片 123456\n可选：/jm图片 123456 20页 群发")
        return

    if not await ensure_bot_control(image_cmd, event, comic_request_feature(request)):
        return

    try:
        await run_comic_request(bot, event, image_cmd, request)
    except Exception as e:
        await image_cmd.send(f"❌ 发送失败：{str(e)}")


@file_cmd.handle()
async def handle_file_command(bot: Bot, event: MessageEvent, msg: Message = CommandArg()):
    request = parse_mode_command_request(msg.extract_plain_text().strip(), "file")
    if request is None:
        await file_cmd.send("ℹ️ 格式：/jm文件 123456\n可选：/jm文件 123456 20页 群发\n🔑 压缩包密码就是漫画编号。")
        return

    if not await ensure_bot_control(file_cmd, event, comic_request_feature(request)):
        return

    try:
        await run_comic_request(bot, event, file_cmd, request)
    except Exception as e:
        await file_cmd.send(f"❌ 文件发送失败：{str(e)}")


@cover_cmd.handle()
async def handle_cover_command(bot: Bot, event: MessageEvent, msg: Message = CommandArg()):
    request = parse_mode_command_request(msg.extract_plain_text().strip(), "image", cover_only=True)
    if request is None:
        await cover_cmd.send("ℹ️ 格式：/jm封面 123456")
        return

    if not await ensure_bot_control(cover_cmd, event, comic_request_feature(request)):
        return

    try:
        await run_comic_request(bot, event, cover_cmd, request)
    except Exception as e:
        await cover_cmd.send(f"❌ 封面发送失败：{str(e)}")


LLM_RESET_PHRASES = (
    "重置记忆",
    "清空记忆",
    "清除记忆",
    "忘记之前",
    "重置对话",
    "清空对话",
    "清空聊天记录",
)

# 纯文本动作（不会发图/发文件）：AI 可以直接触发
LLM_TEXT_ONLY_ACTIONS = {"chat", "help", "jm_search", "jm_recommend"}

# 明确指令识别用的填充词：混在指令里的常见口语词
EXPLICIT_FILLER_WORDS = (
    "把", "给", "我", "你", "的", "到", "下", "一下", "来", "发", "发到", "这", "那", "了",
    "请", "帮", "在", "本", "就", "吧", "哦", "啊", "嘛", "呀", "呢", "啦", "哈", "吗",
    "下载", "看", "看看", "要", "想", "说", "过", "之", "前", "后", "那个", "这个", "可以",
    "里", "内", "行", "能", "有", "呗",
    "好不好", "行不行", "能不能", "可不可以", "可以不",
)

LLM_GATED_REPLY = (
    "呜…这条消息小鱼怕理解错，就没有乱动功能，只陪你聊天嘛～"
    "要下载发「编号 文件」、搜图发「pixiv搜图 TAG」、看推荐发「随机推荐」这样的明确格式哦，喵～"
)


def handle_llm_reset_request(text):
    return (text or "").strip() in LLM_RESET_PHRASES


# 聊天风格偏好指令：用户可以直接跟小鱼说，写入本地偏好库
STYLE_SHOW_PHRASES = ("查看偏好", "我的偏好", "小鱼偏好", "聊天偏好", "查看聊天偏好", "偏好设置")
STYLE_LOW_WORDS = ("少说", "少点", "少来", "别老", "别一直", "别", "不要", "少", "禁止", "别总是")
STYLE_HIGH_WORDS = ("多来点", "多一点", "多点", "多来", "喜欢", "可以多", "多")
TOKEN_THEME_WORDS = ("token", "干饭", "吃饭", "投喂", "零食", "饿了", "吃货", "小鱼零食")
ACTION_THEME_WORDS = ("动作描写", "动作戏", "小剧场", "描写", "演绎")


def parse_style_command(text):
    """解析「少说token」「多动作描写」「查看偏好」等偏好指令。返回 (主题, 方向) 或 None。"""
    text = (text or "").strip()
    if text in STYLE_SHOW_PHRASES:
        return "show", None

    low = any(word in text for word in STYLE_LOW_WORDS)
    high = any(word in text for word in STYLE_HIGH_WORDS)
    if not (low or high):
        return None
    direction = "low" if low else "high"

    lowered = text.lower()
    token_theme = any(word in lowered for word in TOKEN_THEME_WORDS)
    action_theme = any(word in text for word in ACTION_THEME_WORDS)
    if token_theme and not action_theme:
        return "token", direction
    if action_theme and not token_theme:
        return "action", direction
    return None


def explicit_comic_command(text, require_mode=False):
    """只有消息是纯漫画指令（编号 + 功能词/页数/收发词等）时才返回解析结果，否则 None。

    用于防止闲聊里夹个编号（如「123456 这本书我看过」）被误判成下载指令。
    require_mode=True 时还要求消息里必须出现明确功能词（文件/图片/封面等），
    用于群里无 @ 的场景，避免光秃秃一个数字就触发任务。
    """
    text = _cjk_digit_space(text or "")
    id_match = COMIC_ID_PATTERN.search(text)
    if not id_match:
        return None

    if require_mode:
        lowered = (text or "").lower()
        has_mode = any(
            keyword in lowered
            for keyword in FILE_OUTPUT_KEYWORDS + IMAGE_OUTPUT_KEYWORDS + COVER_KEYWORDS
        )
        if not has_mode:
            return None

    rest = f"{text[:id_match.start()]} {text[id_match.end():]}"
    cleaned = re.sub(r"\d+\s*(?:页|p|张|page|pages)?", " ", rest, flags=re.IGNORECASE)
    mode_words = (
        FILE_OUTPUT_KEYWORDS + IMAGE_OUTPUT_KEYWORDS + COVER_KEYWORDS
        + ALL_PAGE_KEYWORDS + GROUP_DELIVERY_KEYWORDS + PRIVATE_DELIVERY_KEYWORDS
    )
    # 长的关键字先匹配，避免「发群」吃掉「发群里」的「群」导致残留
    for word in sorted(set(mode_words), key=len, reverse=True):
        cleaned = re.sub(re.escape(word), " ", cleaned, flags=re.IGNORECASE)
    # 长的填充词先匹配，避免「下」先吃掉「一下」的「一」
    for word in sorted(set(EXPLICIT_FILLER_WORDS), key=len, reverse=True):
        cleaned = re.sub(re.escape(word), " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[，。！？!?,.、~～]", " ", cleaned)
    if re.sub(r"\s+", "", cleaned):
        return None
    return parse_at_comic_request(text)


def _pixiv_random_mentioned(text):
    lowered = (text or "").lower()
    return any(prompt in lowered for prompt in PIXIV_RANDOM_PROMPTS)


def _pixiv_pid_mentioned(text):
    return bool(re.search(r"(?:pixiv\s*pid|\bpid)\s*\d{5,}", text or "", re.IGNORECASE))


def _pixiv_tag_search_mentioned(text):
    return bool(
        re.search(
            r"pixiv\s*搜图|p站\s*搜图|pixiv\s*标签|p站\s*tag|pixiv\s*tag|搜p站",
            text or "",
            re.IGNORECASE,
        )
    )


def _comic_id_in_recent_history(key, comic_id):
    """指代场景：用户说「之前说的那本/刚才那个」时，编号应在本会话最近的聊天历史里出现过。

    返回 True 表示编号有据可查（LLM 推断出的编号可信），避免凭空编造编号触发下载。
    """
    if not comic_id:
        return False
    try:
        for item in get_chat_history(key):
            content = str(item.get("content") or "")
            if re.search(re.escape(comic_id), content):
                return True
    except Exception:
        return False
    return False


def llm_action_gate(text, action, args, key=""):
    """AI 意图的安全闸门：返回 (是否允许执行, 是否明确指令)。

    - 纯文本动作（chat/help/jm_search/jm_recommend）允许，但非明确指令时附带封面不发图；
    - 发图/发文件动作必须由用户消息里的明确指令背书，或编号出自本会话聊天历史（指代场景），
      否则拦截并降级为聊天。
    """
    if action in {"chat", "help"}:
        return True, False
    if action in {"web_search", "bili_search", "dict_query"}:
        return True, True
    if action == "jm_search":
        return True, bool(parse_search_keyword(text))
    if action == "jm_recommend":
        return True, is_recommend_request(text)

    if action in {"jm_file", "jm_image", "jm_cover"}:
        # 放宽格式要求：消息里有明确编号且没有多余无关词即可执行，
        # 具体输出方式（文件/图片/封面）由 AI 根据用户表述决定。
        parsed = explicit_comic_command(text)
        if parsed is not None and parsed.comic_id == (args.get("comic_id") or ""):
            return True, True
        # 指代场景：消息里没有编号，但 AI 从聊天历史推断出了编号且确实出现过 → 允许
        comic_id = (args.get("comic_id") or "").strip()
        if comic_id and _comic_id_in_recent_history(key, comic_id):
            return True, True
        return False, False

    if action == "pixiv_random":
        return _pixiv_random_mentioned(text), True
    if action == "pixiv_search":
        return _pixiv_tag_search_mentioned(text), True
    if action == "pixiv_pid":
        return _pixiv_pid_mentioned(text), True
    if action == "pixiv_recommend":
        return is_pixiv_recommend_request(text), True
    return False, False


def explicit_deterministic_task(text):
    """消息是否是确定性规则解析器能直接执行的明确任务。

    用于 AI 把明确指令误判成闲聊（如被聊天历史带偏，光答应不干活）时回退：
    这些句式 run_deterministic_task 一定能解析执行。
    """
    text = (text or "").strip()
    if not text:
        return False
    if explicit_comic_command(text) is not None:
        return True
    if parse_search_keyword(text):
        return True
    if is_recommend_request(text):
        return True
    if parse_comic_detail_request(text) is not None:
        return True
    if parse_category_command(text) is not None:
        return True
    if parse_pixiv_pid_search(text) is not None:
        return True
    if parse_pixiv_tag_search(text) is not None:
        return True
    if is_pixiv_recommend_request(text):
        return True
    if parse_bili_search(text) is not None:
        return True
    if parse_dict_query(text) is not None:
        return True
    return False


_PROGRESS_FOLLOWUP_HINTS = (
    "好了吗", "好了没", "好没好", "还没好", "好了嘛",
    "在找吗", "在找吗", "找到没", "找到吗", "找了吗",
    "还在吗", "还在弄", "还没发", "还不发", "怎么还不发", "还没出来",
    "多久", "要多久", "等到什么时候", "还要等", "等多久", "还要多久",
    "完成了吗", "完成了没", "弄好了吗", "弄好了没", "搞定了吗", "搞定没",
    "发了吗", "发了吗", "发了没", "发我了吗", "打包好了吗", "打包好了没",
    "进度", "进展", "怎么还没", "还没弄好",
)


def is_progress_followup(text):
    """用户是否在追问正在进行的任务进度（「在找吗/好了吗/还不发我」）。"""
    text = (text or "").strip()
    if not text or len(text) > 40:
        return False
    lowered = text.lower()
    return any(hint in lowered for hint in _PROGRESS_FOLLOWUP_HINTS)


async def handle_llm_message(bot, event, text, matcher, silent_on_gate=False, followup_hint="", task_only=False):
    """把消息交给 DeepSeek 理解并执行意图；未启用或出错返回 False，回退到规则解析。

    silent_on_gate=True（群里无 @ 的场景）：意图被安全闸门拦截时保持沉默，
    不在群里刷无关提示，避免误伤普通聊天。
    followup_hint：bot 发完消息后的下一句时附加的重点提示（让 AI 判断是任务还是闲聊）。
    task_only=True（bot 发完消息后的下一句）：只执行任务动作，判定为纯闲聊时不回复、
    返回 False，把对话交给 chat_judge 的对话判断处理，避免重复接话。
    """
    if not llm_enabled() or not text:
        return False

    key = pixiv_preference_key(event)
    try:
        messages = await asyncio.to_thread(build_llm_messages, key, text)
        if followup_hint:
            messages.append({"role": "system", "content": followup_hint})
        intent = await asyncio.to_thread(llm_chat.chat_intent, messages)
    except Exception as exc:
        logger.warning(f"DeepSeek chat failed: {exc}")
        return False

    action = intent.get("action") or "chat"
    args = intent.get("args") or {}
    reply = str(intent.get("reply") or "").strip()

    # 安全闸门：AI 猜出的发图/发文件动作没有明确指令背书时，降级为纯聊天
    allowed, explicit = llm_action_gate(text, action, args, key)
    if not allowed:
        if silent_on_gate:
            return True
        action = "chat"
        args = {}
        explicit = False
        reply = LLM_GATED_REPLY

    # task_only：纯闲聊不回复，交给对话判断
    if task_only and action == "chat" and not explicit_deterministic_task(text):
        return False

    # AI 把明确指令误判成闲聊（如被聊天历史带偏，光答应不干活）时，
    # 保留人设回复（聊天），同时回退到确定性规则解析真正执行任务（干活），
    # 聊天与任务结合，而不是二选一。
    if action == "chat" and explicit_deterministic_task(text):
        logger.info(f"LLM 把明确任务误判为闲聊，回退规则解析：{text!r}")
        if reply and not silent_on_gate:
            await matcher.send(reply)
        await run_deterministic_task(bot, event, matcher, text, strict=False, help_fallback=False)
        append_chat_history(key, text, reply)
        llm_prefs.record_chat_stats(key, text, reply)
        return True

    # 联网搜索：两步走（搜索 → 拿结果再让 AI 组织回答），结果写回聊天记忆
    if action == "web_search":
        query = (args.get("query") or "").strip()
        final_reply = await run_llm_web_search(matcher, key, text, query, reply)
        append_chat_history(key, text, final_reply or reply)
        llm_prefs.record_chat_stats(key, text, final_reply or reply)
        return True

    # B 站视频搜索：搜索 → 发结果卡片 + 封面预览
    if action == "bili_search":
        keyword = (args.get("keyword") or "").strip()
        final_reply = await run_llm_bili_search(matcher, key, text, keyword, reply)
        append_chat_history(key, text, final_reply or reply)
        llm_prefs.record_chat_stats(key, text, final_reply or reply)
        return True

    # 查词：词典 + 联网资料 → AI 口语化解释
    if action == "dict_query":
        word = (args.get("word") or "").strip()
        final_reply = await run_llm_dict_query(matcher, key, text, word, reply)
        append_chat_history(key, text, final_reply or reply)
        llm_prefs.record_chat_stats(key, text, final_reply or reply)
        return True

    handled = await dispatch_llm_action(bot, event, matcher, action, args, reply, explicit)
    append_chat_history(key, text, reply)
    llm_prefs.record_chat_stats(key, text, reply)
    return handled


async def run_llm_web_search(matcher, key, user_text, query, reply):
    """执行联网搜索并用 AI 组织回答；返回最终发送的文本。"""
    if not query:
        message = reply or "🌐 小鱼想上网查查，但没弄清要查什么…"
        await matcher.send(message)
        return message

    await matcher.send(reply or f"🌐 小鱼上网查一下「{query}」…")
    try:
        results = await asyncio.to_thread(web_search.search_web, query, 5)
    except Exception as exc:
        logger.warning(f"web search failed: {exc}")
        message = "😣 联网搜索失败了，小鱼先凭记忆陪你聊…"
        await matcher.send(message)
        return message

    if not results:
        message = "😣 小鱼没搜到什么有用的内容，换个说法问问？"
        await matcher.send(message)
        return message

    try:
        answer = await asyncio.to_thread(compose_web_answer, key, user_text, results)
    except Exception as exc:
        logger.warning(f"compose_web_answer failed: {exc}")
        answer = ""

    if answer:
        await matcher.send(answer)
        return answer

    lines = ["🌐 小鱼找到这些，给你参考："]
    for index, item in enumerate(results[:3], start=1):
        lines.append(f"{index}. {item.get('title') or '无标题'}\n　 {item.get('url') or ''}")
    message = "\n".join(lines)
    await matcher.send(message)
    return message


async def send_bili_search_results(matcher, keyword):
    """搜索 B 站视频并发送：结果卡片 + 前几张封面预览。返回最终发送的文本。"""
    videos = await asyncio.to_thread(bilibili.search_video, keyword, 5)
    if not videos:
        message = "😣 小鱼在B站没找到相关视频，换个关键词试试？"
        await matcher.send(message)
        return message

    text_message = bilibili.format_video_list(videos)
    await matcher.send(text_message)

    # 附带封面预览（可配：JM_BILI_SEND_COVERS，0 关闭）
    for video in videos[: max(0, BILI_SEND_COVERS)]:
        try:
            cover_path = await asyncio.to_thread(bilibili.download_cover, video, BILI_COVER_DIR)
            if cover_path:
                await matcher.send(MessageSegment.image(path_to_onebot_uri(cover_path)))
        except Exception as exc:
            logger.warning(f"bilibili cover failed: {exc}")
        if SEND_DELAY_SECONDS > 0:
            await asyncio.sleep(SEND_DELAY_SECONDS)
    return text_message


async def send_dict_query_results(matcher, key, word, user_text=""):
    """查词：先查词典，再联网补充，LLM 可用时组织成口语化解释。返回最终文本。"""
    dict_results = await asyncio.to_thread(dictionary.lookup_word, word, 3)
    web_results = await asyncio.to_thread(web_search.search_web, f"{word} 是什么意思", 5)

    if not dict_results and not web_results:
        message = "😣 小鱼没查到这个词，换个说法问问？"
        await matcher.send(message)
        return message

    if llm_enabled() and key:
        try:
            answer = await asyncio.to_thread(
                compose_dict_answer, key, user_text or f"{word}是什么意思", word, dict_results, web_results
            )
            if answer:
                await matcher.send(answer)
                return answer
        except Exception as exc:
            logger.warning(f"compose_dict_answer failed: {exc}")

    # 兜底：直接贴词典释义（无 LLM / 组织失败时也能用）
    lines = [f"📖「{word}」的解释："]
    for item in dict_results:
        lines.append(f"· {item.get('entry') or word}：{item.get('explain') or ''}")
    if not dict_results:
        for index, item in enumerate(web_results[:3], start=1):
            lines.append(f"{index}. {item.get('title') or '无标题'}\n　 {item.get('url') or ''}")
    message = "\n".join(lines)
    await matcher.send(message)
    return message


async def run_llm_bili_search(matcher, key, user_text, keyword, reply):
    """执行 B 站视频搜索并发送结果；返回最终发送的文本。"""
    if not keyword:
        message = reply or "🎬 想找什么视频？发「b站 关键词」告诉我，比如「b站 猫咪」"
        await matcher.send(message)
        return message
    await matcher.send(reply or f"🎬 小鱼去B站找找「{keyword}」…")
    try:
        return await send_bili_search_results(matcher, keyword)
    except Exception as exc:
        logger.warning(f"bilibili search failed: {exc}")
        message = "😣 B站搜索失败了，稍后再试试…"
        await matcher.send(message)
        return message


async def run_llm_dict_query(matcher, key, user_text, word, reply):
    """执行查词并发送结果；返回最终发送的文本。"""
    if not word:
        message = reply or "📖 想问哪个词的意思？比如「破防是什么意思」「abyss什么意思」"
        await matcher.send(message)
        return message
    await matcher.send(reply or f"📖 小鱼查一下「{word}」…")
    try:
        return await send_dict_query_results(matcher, key, word, user_text)
    except Exception as exc:
        logger.warning(f"dict query failed: {exc}")
        message = "😣 查词失败了，稍后再试试…"
        await matcher.send(message)
        return message


async def dispatch_llm_action(bot, event, matcher, action, args, reply, explicit=False):
    """按 AI 输出的意图执行既有功能；所有动作都走原有权限检查。

    explicit=False 表示消息没有明确指令（如「帮我找找女仆漫画」），
    此时搜索/推荐只发文字卡片，不附带封面图。
    """
    async def say(message):
        await matcher.send(message)

    if action == "help":
        await say(HELP_MENU)
        return True

    if action == "chat":
        # 像人一样记得正在做的事：追问进度时给真实状态，而不是空口安慰
        key = pixiv_preference_key(event)
        ongoing = peek_ongoing_task(key)
        if ongoing and is_progress_followup(text):
            elapsed = max(0, int(time.time() - float(ongoing.get("ts") or time.time())))
            await say(
                f"呜…{ongoing.get('desc') or '小鱼在忙'}中，已经 {elapsed} 秒啦，"
                "弄好马上发你，别急嘛～"
            )
            return True
        await say(reply or "呜…小鱼在听呢，喵～")
        return True

    if action == "jm_search":
        keyword = (args.get("keyword") or "").strip()
        if not keyword:
            await say(reply or "🔍 想搜什么？发「搜索 关键词」告诉我")
            return True
        if not await ensure_bot_control(matcher, event, "jm_search"):
            return True
        if reply:
            await say(reply)
        try:
            await search_and_send(matcher, keyword, send_covers=explicit, event=event)
        except Exception as exc:
            await say(f"❌ 搜索失败：{exc}")
        return True

    if action in {"jm_file", "jm_image", "jm_cover"}:
        comic_id = (args.get("comic_id") or "").strip()
        if not comic_id:
            await say(reply or "🤔 我没看到漫画编号，发「123456 文件」这样的格式就行～")
            return True
        request = AtComicRequest(
            comic_id=comic_id,
            page_limit=0 if action == "jm_cover" else args.get("page_limit"),
            cover_only=(action == "jm_cover"),
            output_mode="file" if action == "jm_file" else "image",
            delivery_mode=args.get("delivery") or "private",
        )
        if not await ensure_bot_control(matcher, event, comic_request_feature(request)):
            return True
        if reply:
            await say(reply)
        try:
            await run_comic_request(bot, event, matcher, request)
        except Exception as exc:
            await say(f"❌ 发送失败：{exc}")
        return True

    if action == "jm_recommend":
        if not await ensure_bot_control(matcher, event, "jm_recommend"):
            return True
        if reply:
            await say(reply)
        key = pixiv_preference_key(event)
        remember_ongoing_task(key, "正在翻书库挑漫画", tag="jm_recommend")
        try:
            await random_recommend_and_send(matcher, event, send_covers=explicit)
        except Exception as exc:
            await say(f"❌ 随机推荐失败：{exc}")
        finally:
            forget_ongoing_task(key)
        return True

    if action == "pixiv_random":
        tag = (args.get("tag") or "").strip()
        if not await ensure_bot_control(matcher, event, "pixiv_random"):
            return True
        if reply:
            await say(reply)
        key = pixiv_preference_key(event)
        remember_ongoing_task(key, f"正在图库挑图{'「' + tag + '」' if tag else ''}", tag="pixiv_random")
        try:
            await send_pixiv_random_artwork(bot, event, tag)
        except Exception as exc:
            await say(f"❌ 来点图失败：{exc}")
        finally:
            forget_ongoing_task(key)
        return True

    if action == "pixiv_search":
        tag = (args.get("tag") or "").strip()
        if not tag:
            await say(reply or "🔍 想搜什么 TAG？例如「pixiv搜图 初音ミク」")
            return True
        if not await ensure_bot_control(matcher, event, "pixiv_search"):
            return True
        if reply:
            await say(reply)
        try:
            await send_pixiv_tag_search(bot, event, tag, 5)
        except Exception as exc:
            await say(f"❌ Pixiv 搜图失败：{exc}")
        return True

    if action == "pixiv_pid":
        pid = (args.get("pid") or "").strip()
        if not pid:
            await say(reply or "🔍 把作品 PID 发给我，例如「pid 12345678」")
            return True
        if not await ensure_bot_control(matcher, event, "pixiv_search"):
            return True
        if reply:
            await say(reply)
        try:
            await send_pixiv_pid_search(bot, event, pid)
        except Exception as exc:
            await say(f"❌ Pixiv PID 查询失败：{exc}")
        return True

    if action == "pixiv_recommend":
        if not await ensure_bot_control(matcher, event, "pixiv_recommend"):
            return True
        destination_type, destination_id = resolve_pixiv_destination(
            event, "群发" if args.get("delivery") == "group" else ""
        )
        if reply:
            await say(reply)
        try:
            await send_pixiv_recommendations(bot, destination_type, destination_id, PIXIV_DAILY_COUNT)
        except Exception as exc:
            await say(f"❌ Pixiv 推荐失败：{exc}")
        return True

    # 未知动作按闲聊处理
    await say(reply or "呜…小鱼在听呢，喵～")
    return True


async def run_deterministic_task(bot, event, matcher, text, strict=False, help_fallback=True):
    """确定性任务解析（不发 AI）：Pixiv/JM 搜索推荐/漫画指令。返回 True 表示已处理。

    strict=True 用于群里无 @ 的场景：漫画指令必须带明确功能词（文件/图片/封面），
    光秃秃一个数字不触发；未匹配时不弹帮助菜单（help_fallback=False）。
    """
    pixiv_pid = parse_pixiv_pid_search(text)
    if pixiv_pid is not None:
        if not await ensure_bot_control(matcher, event, "pixiv_search"):
            return True
        try:
            await send_pixiv_pid_search(bot, event, pixiv_pid)
        except Exception as e:
            await matcher.send(f"❌ Pixiv PID 搜索失败：{str(e)}")
        return True

    # B 站视频搜索（不需要 AI）
    bili_keyword = parse_bili_search(text)
    if bili_keyword is not None:
        if not await ensure_bot_control(matcher, event):
            return True
        if not bili_keyword:
            await matcher.send("🎬 想找什么视频？发「b站 关键词」告诉我，比如「b站 猫咪」")
            return True
        try:
            await send_bili_search_results(matcher, bili_keyword)
        except Exception as e:
            await matcher.send(f"❌ B站搜索失败：{str(e)}")
        return True

    # 查词：XX是什么意思 / 解释一下XX（词典优先，LLM 可用时组织解释）
    dict_word = parse_dict_query(text)
    if dict_word is not None:
        if not await ensure_bot_control(matcher, event):
            return True
        key = pixiv_preference_key(event)
        try:
            await send_dict_query_results(matcher, key, dict_word, text)
        except Exception as e:
            await matcher.send(f"❌ 查词失败：{str(e)}")
        return True

    pixiv_tag = parse_pixiv_tag_search(text)
    if pixiv_tag is not None:
        if not await ensure_bot_control(matcher, event, "pixiv_search"):
            return True
        try:
            await send_pixiv_tag_search(bot, event, pixiv_tag, 5)
        except Exception as e:
            await matcher.send(f"❌ Pixiv TAG 搜索失败：{str(e)}")
        return True

    if is_pixiv_recommend_request(text):
        if not await ensure_bot_control(matcher, event, "pixiv_recommend"):
            return True
        destination_type, destination_id = resolve_pixiv_destination(event, text)
        if isinstance(event, GroupMessageEvent) and destination_type == "private":
            await matcher.send("📨 开始私发 Pixiv 推荐给你；如果收不到，请先添加机器人为好友。")
        else:
            await matcher.send("🎨 开始获取 Pixiv 日榜推荐。")
        try:
            await send_pixiv_recommendations(bot, destination_type, destination_id, PIXIV_DAILY_COUNT)
        except Exception as e:
            await matcher.send(f"❌ Pixiv 推荐失败：{str(e)}")
        return True

    if is_recommend_request(text):
        if not await ensure_bot_control(matcher, event, "jm_recommend"):
            return True
        keyword = parse_recommend_keyword(text) or None
        try:
            await random_recommend_and_send(matcher, event, keyword=keyword)
        except Exception as e:
            await matcher.send(f"❌ 随机推荐失败：{str(e)}")
        return True

    detail_id = parse_comic_detail_request(text)
    if detail_id:
        if not await ensure_bot_control(matcher, event, "jm_search"):
            return True
        await send_comic_detail(matcher, detail_id)
        return True

    category_parsed = parse_category_command(text)
    if category_parsed is not None:
        if not await ensure_bot_control(matcher, event, "jm_search"):
            return True
        name, page = category_parsed
        await send_category_comics(matcher, name, page)
        return True

    keyword = parse_search_keyword(text)
    if keyword:
        if not await ensure_bot_control(matcher, event, "jm_search"):
            return True
        keyword, page = parse_search_page(keyword)
        try:
            await search_and_send(matcher, keyword, page=page, event=event)
        except Exception as e:
            await matcher.send(f"❌ 搜索失败：{str(e)}")
        return True

    request = explicit_comic_command(text, require_mode=strict) if strict else parse_at_comic_request(text)
    if request is None:
        if help_fallback:
            await matcher.send(HELP_MENU)
            return True
        return False

    if not await ensure_bot_control(matcher, event, comic_request_feature(request)):
        return True

    try:
        await run_comic_request(bot, event, matcher, request)
    except Exception as e:
        await matcher.send(f"❌ 发送失败：{str(e)}")
    return True


# ---------------------------------------------------------------- bot 发完消息后的下一句：任务需求续接

# 「第2页 / 2页 / 下一页 / 下页 / 翻页 / 再翻一页」
_FOLLOWUP_PAGE_RE = re.compile(r"^(?:第\s*)?(\d{1,3})\s*页$|^(?:下一页|下页|翻页|再翻一页|往后翻)$")


def parse_followup_page(text):
    """解析「第2页/2页/下一页/翻页」→ 页码（int）或 "next"（下一页）或 None。"""
    text = (text or "").strip()
    if not text or len(text) > 12:
        return None
    m = _FOLLOWUP_PAGE_RE.match(text)
    if not m:
        return None
    if m.group(1):
        return max(1, min(50, int(m.group(1))))
    return "next"


def is_pixiv_interactive_phrase(text):
    """是否属于 pixiv_interactive（priority 35）已处理的短语（满意/换一张/我已满18岁/来点图等）。"""
    return (
        is_pixiv_random_prompt(text)
        or parse_pixiv_rating(text) is not None
        or is_pixiv_adult_confirm_text(text)
        or is_pixiv_adult_cancel_text(text)
    )


async def try_task_continuation(bot, event, matcher, text, key):
    """bot 发完消息后的下一句：续接最近一次任务（搜索翻页/漫画改收发改输出/换一批推荐）。

    命中并执行返回 True；不是续接指令返回 False。
    """
    ctx = peek_last_task(key)
    if not ctx:
        return False
    text = (text or "").strip()
    if not text or len(text) > 30:
        return False
    task_type = ctx.get("type")

    # 搜索续接：第2页 / 下一页
    if task_type == "search":
        page = parse_followup_page(text)
        if page is None:
            return False
        keyword = str(ctx.get("keyword") or "")
        if not keyword:
            return False
        if page == "next":
            page = int(ctx.get("page") or 1) + 1
        if not await ensure_bot_control(matcher, event, "jm_search"):
            return True
        try:
            await search_and_send(matcher, keyword, page=page, event=event)
        except Exception as exc:
            await matcher.send(f"❌ 翻页失败：{exc}")
        return True

    # 漫画续接：私发/群发/文件/图片/封面/全部
    if task_type == "comic":
        lowered = text.lower()
        delivery = None
        if any(word in lowered for word in GROUP_DELIVERY_KEYWORDS):
            delivery = "group"
        elif any(word in lowered for word in PRIVATE_DELIVERY_KEYWORDS):
            delivery = "private"
        cover = any(word in lowered for word in COVER_KEYWORDS)
        output_mode = None
        if any(word in lowered for word in FILE_OUTPUT_KEYWORDS):
            output_mode = "file"
        elif any(word in lowered for word in IMAGE_OUTPUT_KEYWORDS):
            output_mode = "image"
        wants_all = any(word in lowered for word in ALL_PAGE_KEYWORDS)

        if delivery is None and output_mode is None and not cover and not wants_all:
            return False

        comic_id = str(ctx.get("comic_id") or "")
        if not comic_id:
            return False
        if cover:
            page_limit = 0
        elif wants_all:
            page_limit = None
        else:
            page_limit = ctx.get("page_limit")
        # 与上次完全一致（收发/输出/范围都没变）就不重复重发
        if (
            (delivery or ctx.get("delivery_mode") or "private") == (ctx.get("delivery_mode") or "private")
            and (output_mode or ctx.get("output_mode") or "image") == (ctx.get("output_mode") or "image")
            and bool(cover) == bool(ctx.get("cover_only"))
            and page_limit == ctx.get("page_limit")
        ):
            return False
        request = AtComicRequest(
            comic_id=comic_id,
            page_limit=page_limit,
            cover_only=cover or bool(ctx.get("cover_only")),
            output_mode=output_mode or ctx.get("output_mode") or "image",
            delivery_mode=delivery or ctx.get("delivery_mode") or "private",
        )
        if not await ensure_bot_control(matcher, event, comic_request_feature(request)):
            return True
        try:
            await run_comic_request(bot, event, matcher, request)
        except Exception as exc:
            await matcher.send(f"❌ 发送失败：{exc}")
        return True

    # 推荐续接：换一批
    if task_type == "recommend":
        if text.strip() not in {"换一批", "再换一批", "换换", "再来点", "换一批推荐"}:
            return False
        if not await ensure_bot_control(matcher, event, "jm_recommend"):
            return True
        try:
            await random_recommend_and_send(matcher, event)
        except Exception as exc:
            await matcher.send(f"❌ 换一批失败：{exc}")
        return True

    return False


async def try_followup_task(bot, event, matcher, text, key):
    """bot 发完消息后的下一句：优先按「任务需求」处理，命中执行返回 True。

    顺序：续接最近一次任务 → 确定性任务（不发 AI）→ LLM 意图（task_only，只执行任务）。
    纯闲聊时返回 False，由调用方（chat_judge）走对话判断，避免重复接话。
    """
    # 1) 续接最近一次任务：搜索翻页/漫画改收发改输出/换一批
    if await try_task_continuation(bot, event, matcher, text, key):
        return True

    # 2) 确定性任务（搜索关键词/漫画指令/查词/B站/技能等，不发 AI）
    if await run_deterministic_task(bot, event, matcher, text, strict=False, help_fallback=False):
        return True

    # 3) LLM 意图（task_only）：是任务需求就执行；纯闲聊不回复返回 False
    if llm_enabled():
        hint = (
            "【判断提示】小鱼刚在群里发过消息，这句话紧接着小鱼发言，极大概率是在回复小鱼。"
            "请判断这是任务需求还是闲聊：有需求就输出对应 action 真正执行；"
            "纯闲聊不输出任何 action，保持 chat。"
        )
        if await handle_llm_message(bot, event, text, matcher, followup_hint=hint, task_only=True):
            return True

    return False


def task_like_message(text):
    """群里无 @ 时，只有明显是任务的句式才进入任务管线，闲聊一律不碰。"""
    text = (text or "").strip()
    if not text or len(text) > 120:
        return False

    # 小技能任务句式
    if re.search(
        r"^(?:计算|算|calc)\b|^骰子$|^掷骰子$|^丢骰子$|^\d{1,2}d\d{1,3}$|^d\d{1,3}$"
        r"|^随机数\b|^签到$|^抽签$|^求签$|^抽个签$|^今日运势$|^运势$"
        r"|^倒计时\s|^随机点名$|^点个人$|^抽个人$|^点名$"
        r"|^讲个笑话$|^来个笑话$|^笑话$|^夸夸我$|^夸我$",
        text,
        re.IGNORECASE,
    ):
        return True

    # 漫画任务：编号 + 明确功能词
    if explicit_comic_command(text, require_mode=True) is not None:
        return True

    # 搜索/推荐/Pixiv 触发词
    if parse_search_keyword(text) or is_recommend_request(text):
        return True
    if (
        _pixiv_pid_mentioned(text)
        or _pixiv_tag_search_mentioned(text)
        or _pixiv_random_mentioned(text)
        or is_pixiv_recommend_request(text)
    ):
        return True

    # B 站视频搜索 / 查词（XX是什么意思）
    if parse_bili_search(text) is not None:
        return True
    if parse_dict_query(text) is not None:
        return True

    # 自然语言任务词（交给 AI 判断，安全闸门兜底）
    if re.search(r"(下载|打包)", text) or (
        re.search(r"(帮我|帮忙|找找|找一下|查一下|推荐)", text)
        and re.search(r"(漫画|本子|图|p站|pixiv|编号|视频|几本|看看|一部)", text, re.IGNORECASE)
    ):
        return True

    # FAQ 类
    if text in {"帮助", "菜单", "怎么下载", "如何下载", "下载方法", "密码是多少"}:
        return True
    if len(text) <= 20 and "密码" in text:
        return True

    # JM 订阅/退订/列表
    if text in JM_SUBSCRIBE_STATUS_PHRASES or parse_jm_subscribe_action(text) is not None:
        return True

    # 漫画详情查询
    if parse_comic_detail_request(text) is not None:
        return True

    # 分类浏览
    if parse_category_command(text) is not None:
        return True

    # 浏览历史查询
    if text in VIEWED_HISTORY_PHRASES:
        return True
    return False


async def _task_like_rule(event: MessageEvent) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False
    if str(event.user_id) == str(event.self_id):
        return False
    return task_like_message(event.get_message().extract_plain_text())


no_at_task_cmd = on_message(rule=_task_like_rule, priority=25, block=True)


@no_at_task_cmd.handle()
async def handle_no_at_task(bot: Bot, event: MessageEvent):
    """群里不用 @ 也能接任务：只有明显任务句式才进来，安全闸门照常生效。"""
    text = event.get_message().extract_plain_text().strip()
    if not await ensure_bot_control(no_at_task_cmd, event):
        return

    # 小技能（无 @ 场景只启用任务型技能，不启用问候/感谢/委屈等社交类）
    if await try_handle_skill(bot, event, no_at_task_cmd, text, help_menu=HELP_MENU, social=False):
        return

    # JM 订阅/退订/列表（本地确定性处理）
    if await try_handle_jm_subscription(bot, event, no_at_task_cmd, text):
        return

    # 浏览历史查询（本地处理）
    if text in VIEWED_HISTORY_PHRASES:
        await send_viewed_history(no_at_task_cmd, event)
        return

    # 确定性任务
    if await run_deterministic_task(bot, event, no_at_task_cmd, text, strict=True, help_fallback=False):
        return

    # AI 意图（闸门拦截时保持沉默，避免在群里刷无关消息）
    await handle_llm_message(bot, event, text, no_at_task_cmd, silent_on_gate=True)


@at_comic_cmd.handle()
async def handle_at_comic(bot: Bot, event: MessageEvent):
    text = event.get_message().extract_plain_text().strip()
    if not await ensure_bot_control(at_comic_cmd, event):
        return

    if await handle_pixiv_interactive_message(bot, event, text):
        return

    # 记忆重置：本地清除，不走 AI
    if handle_llm_reset_request(text):
        clear_chat_history(pixiv_preference_key(event))
        await at_comic_cmd.send("🧹 小鱼把聊天记忆清空啦～呜…这下要重新认识你惹")
        return

    # 闭嘴/解禁指令：被 @ 说闭嘴 → 委屈安静；说解禁 → 复出
    if await try_handle_silence_command(at_comic_cmd, event, text):
        return

    # 聊天偏好指令：本地记录，不走 AI（「少说token」「多动作描写」「查看偏好」）
    style_cmd = parse_style_command(text)
    if style_cmd:
        theme, direction = style_cmd
        key = pixiv_preference_key(event)
        if theme == "show":
            token_label, action_label, stats = llm_prefs.style_summary(key)
            await at_comic_cmd.send(
                "🐟 小鱼记下的你的聊天偏好\n"
                "────────────\n"
                f"· token/干饭梗：{token_label}\n"
                f"· 动作描写：{action_label}\n"
                f"· 已聊 {stats['user_msgs']} 条，你提过 token 主题 {stats['user_token_mentions']} 次\n"
                "想改就说「少说token」「多动作描写」这类话，小鱼会记住～"
            )
        else:
            llm_prefs.set_style(key, theme, direction)
            if theme == "token":
                message = (
                    "呜…好嘛，小鱼以后少提 token 和干饭，专心陪你聊天～（已记住）"
                    if direction == "low"
                    else "好耶！那小鱼可以多念叨点 token 小鱼零食啦，记住咯～"
                )
            else:
                message = (
                    "呜…知道啦，小鱼以后不做动作描写，直接说话～（已记住）"
                    if direction == "low"
                    else "好耶！小鱼可以多来点小动作小剧场啦，记住咯～"
                )
            await at_comic_cmd.send(message)
        return

    # 预设技能层：高频场景本地秒回（问候/FAQ/计算/骰子/签到等），不走 AI 不烧 token
    if await try_handle_skill(bot, event, at_comic_cmd, text, help_menu=HELP_MENU):
        return

    # JM 订阅/退订/列表：本地确定性处理，不走 AI
    if await try_handle_jm_subscription(bot, event, at_comic_cmd, text):
        return

    # 浏览历史查询：本地处理
    if text in VIEWED_HISTORY_PHRASES:
        await send_viewed_history(at_comic_cmd, event)
        return

    # 所有消息先交给 AI 理解意图；AI 未启用/出错时回退到下面的规则解析
    if await handle_llm_message(bot, event, text, at_comic_cmd):
        return

    await run_deterministic_task(bot, event, at_comic_cmd, text, strict=False, help_fallback=True)

# 搜索漫画命令
@search_cmd.handle()
async def handle_search(event: MessageEvent, msg: Message = CommandArg()):
    if not await ensure_bot_control(search_cmd, event, "jm_search"):
        return

    raw = msg.extract_plain_text().strip()
    keyword, page = parse_search_page(raw)

    try:
        await search_and_send(search_cmd, keyword, page=page, event=event)
    except Exception as e:
        await search_cmd.send(f"❌ 搜索失败：{str(e)}")

# 启动命令
test_cmd = on_command("测试机器人", aliases={"test", "测试"})

@test_cmd.handle()
async def handle_test(event: MessageEvent):
    await test_cmd.send("✅ 小鱼运转正常，没有宕机，喵～")
