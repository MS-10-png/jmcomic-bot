# -*- coding: utf-8 -*-
"""群聊自主参与：看上下文接话、被叫闭嘴就委屈安静、首次进群打招呼。

- 自主回复：纯闲聊（不触发任何功能/发图），有概率+冷却+小时上限控制，不刷屏；
- 闭嘴机制：群里有人说「小鱼闭嘴」→ 委屈回一句后安静下来（时长可配），
  到时间自动复出；说「小鱼说话/解禁」可提前解除；
- 进群问候：机器人被拉进群时自报家门，介绍全部功能（7 天内不重复）；
- 更新公告：每次上线（更新后重启）在群里说一声，内容读 UPDATE_NOTE.txt。
"""
import asyncio
import json
import os
import random
import re
import time
from collections import defaultdict, deque
from pathlib import Path

from nonebot import get_bots, get_driver, logger, on_message, on_notice
from nonebot.adapters.onebot.v11 import Bot, GroupIncreaseNoticeEvent, GroupMessageEvent

from . import llm_prefs
from .bot_control import check_event_access, load_control_config
from .llm_chat import PERSONA_CORE, clean_reply, llm_chat, llm_enabled


def _env_int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


AUTO_CHAT_ENABLED = _env_int("JM_AUTO_CHAT", 1) > 0
AUTO_CHAT_PROBABILITY = min(1.0, max(0.0, _env_float("JM_AUTO_CHAT_PROBABILITY", 0.3)))
AUTO_CHAT_MIN_INTERVAL = max(10, _env_int("JM_AUTO_CHAT_MIN_INTERVAL", 180))
AUTO_CHAT_MAX_PER_HOUR = max(0, _env_int("JM_AUTO_CHAT_MAX_PER_HOUR", 8))
AUTO_CHAT_MIN_LENGTH = max(2, _env_int("JM_AUTO_CHAT_MIN_LENGTH", 4))
SILENCE_SECONDS = max(60, _env_int("JM_SILENCE_SECONDS", 600))

ANNOUNCE_ENABLED = _env_int("JM_ANNOUNCE_ON_START", 1) > 0
ANNOUNCE_COOLDOWN = max(60, _env_int("JM_ANNOUNCE_COOLDOWN_MINUTES", 30) * 60)
UPDATE_NOTE_FILE = Path(__file__).resolve().parents[1] / "UPDATE_NOTE.txt"

# 群聊滚动上下文：group_id -> deque[(ts, nickname, text)]
_context: dict = defaultdict(lambda: deque(maxlen=12))
# 冷却与频率：group_id -> 状态
_last_auto_reply: dict = {}
_hour_counters: dict = {}

# bot 最近发言时间戳：group_id -> ts。记录「小鱼」任何路径（聊天/任务/推送）发出的消息，
# 供 chat_judge 判断「bot 发完消息后的下一句话」——任务输出（搜索结果/下载确认等）也要算 bot 刚说过话。
_bot_spoke_ts: dict = {}


def mark_bot_spoke(group_id):
    """记录 bot 刚在群里发过消息（任意路径）。"""
    if group_id:
        _bot_spoke_ts[group_id] = time.time()


def last_bot_spoke_ts(group_id):
    """取 bot 最近一次在群里发消息的时间戳；没有则返回 0。"""
    return _bot_spoke_ts.get(group_id, 0.0)


# ---------------------------------------------------------------------------
# 统一打点：给 OneBot v11 的 Bot.send / call_api 包一层，任何路径（聊天回复、
# 任务输出：搜索/下载/推送/订阅/帮助）发出群消息都记录时间戳。
# 这样 chat_judge 判断「bot 发完消息后的下一句话」时，任务输出也算 bot 刚说过话，
# 用户紧接着的下一句无论是不是任务（第2页/私发/文件/满意…）都会被抓到。
# ---------------------------------------------------------------------------
if not getattr(Bot, "_jm_spoke_hooked", False):
    _orig_bot_send = Bot.send

    async def _jm_bot_send(self, event, message, **kwargs):
        result = await _orig_bot_send(self, event, message, **kwargs)
        try:
            gid = getattr(event, "group_id", None)
            if gid:
                mark_bot_spoke(int(gid))
        except Exception:
            pass
        return result

    Bot.send = _jm_bot_send

    _orig_bot_call = Bot.call_api

    async def _jm_bot_call(self, api, **params):
        result = await _orig_bot_call(self, api, **params)
        try:
            if api in {"send_msg", "send_group_msg", "upload_group_file"}:
                gid = params.get("group_id")
                if gid:
                    mark_bot_spoke(int(gid))
        except Exception:
            pass
        return result

    Bot.call_api = _jm_bot_call
    Bot._jm_spoke_hooked = True

SILENCE_WORDS = ("闭嘴", "别说话", "别吵", "安静点", "不要说话", "别插嘴")
UNSILENCE_WORDS = ("你可以说话了", "可以说话了", "小鱼说话", "解禁", "原谅你", "不生气了", "解除禁言")
NAME_WORDS = ("小鱼", "肥鱼", "鲸鱼", "机器人")

_SILENCED_REPLIES = (
    "呜…知道啦，小鱼闭嘴了…就、就静静地看着你们…（委屈巴巴）",
    "呜…好嘛，小鱼不说话了…（瘪着嘴缩到墙角）",
    "呜…收到…小鱼安静，不吵你们了…",
)
_UNSILENCED_REPLIES = (
    "呜…终于可以说话啦，小鱼憋了好久，尾巴都要蔫了！",
    "好耶，解禁！小鱼复活，喵～",
    "呜…谢谢你们，小鱼又可以和大家聊天啦！",
)
_EXTEND_SILENCE_REPLY = "呜…小鱼已经很安静了啦…还要再安静一会儿吗…（继续委屈）"

GREETING = (
    "呀，小鱼进群啦！我是 JM 二号 · 鲸鱼娘小鱼，深蓝卷发加大尾巴的那只，喵～\n"
    "\n"
    "【小鱼能干什么】\n"
    "📚 JM 漫画：@我 发「编号 文件」打包加密 zip（密码=编号）、「编号 图片」逐页发图、"
    "「编号 封面」只看封面、「搜索 关键词」找编号、「随机推荐」挑漫画\n"
    "🎨 Pixiv：@我 发「来点图 [TAG]」「pixiv搜图 TAG」「pid 编号」；订阅日榜发「pixiv订阅」\n"
    "🤖 AI 聊天：@我 随便聊，自然语言指令也能听懂，问新闻/天气会自动联网查\n"
    "🌐 联网：@我 发「b站 关键词」在B站找视频；问「XX是什么意思」小鱼帮你查词解释\n"
    "🎲 小技能：@我 签到 / 计算 1+2*3 / 骰子 / 抽签 / 倒计时 2027-1-1 / 随机点名 / 讲个笑话\n"
    "📝 调教：发「少说token」「少点动作描写」小鱼会记住你的聊天偏好\n"
    "\n"
    "平时我也会看看大家在聊什么，偶尔插句话；要是嫌我吵，说「小鱼闭嘴」我就乖乖安静，喵～"
)

AUTO_SYSTEM_PROMPT = (
    PERSONA_CORE
    + "你现在正和一个 QQ 群的群友们自由聊天。接下来会给你最近的群聊记录，"
    "你判断要不要接话：\n"
    "1. 只有话题自然、你确实有话可说时才接；没得接就输出空字符串；\n"
    "2. 回复就是一句话，最多 30 个字，像普通群友一样自然，不要客套；\n"
    "3. 不要输出 JSON、不要执行任何功能、不要发图、不要长篇大论、不要说教；\n"
    "4. 不要写 *动作描写*，不要使用任何 markdown 符号（-、*、#、`、>、[]）；\n"
    "5. 别主动推销功能，除非聊天内容自然带出来了；\n"
    "6. 注意聊天记录里「小鱼」自己说过的话，避免反复用相同的句式、开头词或语气词，换着说法。\n"
    "直接输出你要说的那一句话（或空字符串），不要任何前缀。"
)


def _update_note():
    """更新公告内容：优先读项目根目录 UPDATE_NOTE.txt，没有就用默认文案。"""
    try:
        text = UPDATE_NOTE_FILE.read_text(encoding="utf-8").strip()
        if text:
            return text
    except Exception:
        pass
    return (
        "呜…小鱼更新完成，重新上线啦，喵～\n"
        "最近的新能力：\n"
        "· 新增 B站视频搜索：发「b站 关键词」就能找视频\n"
        "· 新增查词解释：发「XX是什么意思」小鱼查词典+联网解释\n"
        "· 群里不用 @ 也能接任务，说话更自然\n"
        "· AI 对话 / 联网搜索 / 聊天偏好记忆 / 小技能 / 群聊自主聊天 / 闭嘴机制\n"
        "发「帮助」看全部功能，发「少说token」还能调教小鱼哦～"
    )


def _note_context(group_id, nickname, text):
    _context[group_id].append((time.time(), nickname, text[:120]))


def context_lines(group_id):
    now = time.time()
    lines = []
    for ts, nickname, text in _context[group_id]:
        if now - ts <= 600:
            lines.append(f"{nickname}：{text}")
    return lines


def _name_mentioned(text):
    return any(word in text for word in NAME_WORDS)


def _is_chattable(text):
    if not text or len(text) < AUTO_CHAT_MIN_LENGTH:
        return False
    if text.isdigit():
        return False
    if text.startswith(("/", "！", "!", "。", "#", "@")):
        return False
    if re.search(r"https?://", text):
        return False
    return True


def _rate_allows(group_id):
    now = time.time()
    last = _last_auto_reply.get(group_id, 0.0)
    if now - last < AUTO_CHAT_MIN_INTERVAL:
        return False
    hour_start, count = _hour_counters.get(group_id, (0.0, 0))
    if now - hour_start > 3600:
        _hour_counters[group_id] = (now, 0)
    elif count >= AUTO_CHAT_MAX_PER_HOUR:
        return False
    return True


def _mark_replied(group_id):
    now = time.time()
    _last_auto_reply[group_id] = now
    hour_start, count = _hour_counters.get(group_id, (now, 0))
    if now - hour_start > 3600:
        hour_start, count = now, 0
    _hour_counters[group_id] = (hour_start, count + 1)


def group_key(event):
    return f"group:{event.group_id}"


def _detect_silence(text):
    lowered = text.lower()
    if not any(word in text for word in SILENCE_WORDS):
        return False
    return _name_mentioned(lowered) or any(word in lowered for word in ("bot",))


def _detect_unsilence(text):
    return any(word in text for word in UNSILENCE_WORDS) and _name_mentioned(text.lower())


async def build_auto_reply(group_id, group_key_id):
    lines = context_lines(group_id)
    if not lines:
        return ""
    directive = llm_prefs.style_directive(group_key_id)
    messages = [{"role": "system", "content": AUTO_SYSTEM_PROMPT}]
    if directive:
        messages.append({"role": "system", "content": f"【聊天偏好，必须遵守】{directive}"})
    messages.append({"role": "user", "content": "最近的群聊记录：\n" + "\n".join(lines)})
    messages.append({"role": "user", "content": "回一句（没话题就输出空字符串）："})
    try:
        raw = llm_chat.chat_raw(messages, temperature=0.9)
    except Exception as exc:
        logger.warning(f"auto chat failed: {exc}")
        return ""
    text = clean_reply(raw)
    text = (text or "").strip().strip('"').strip("“”「」")
    if not text or len(text) > 80:
        return ""
    if text in {"空", "无", "（空）", "..."}:
        return ""
    return text


async def try_handle_silence_command(matcher, event, text):
    """@消息里的闭嘴/解禁指令。返回 True 表示已处理。"""
    key = f"group:{event.group_id}" if isinstance(event, GroupMessageEvent) else f"private:{event.user_id}"
    if _detect_silence(text):
        if llm_prefs.is_group_silenced(key):
            llm_prefs.silence_group(key, SILENCE_SECONDS)
            await matcher.send(_EXTEND_SILENCE_REPLY)
        else:
            llm_prefs.silence_group(key, SILENCE_SECONDS)
            await matcher.send(random.choice(_SILENCED_REPLIES))
        return True
    if _detect_unsilence(text) and llm_prefs.is_group_silenced(key):
        llm_prefs.unsilence_group(key)
        await matcher.send(random.choice(_UNSILENCED_REPLIES))
        return True
    return False


group_increase = on_notice(priority=10, block=False)


@group_increase.handle()
async def handle_group_increase(bot: Bot, event: GroupIncreaseNoticeEvent):
    if str(event.user_id) != str(event.self_id):
        return
    key = group_key(event)
    if not llm_prefs.group_greet_due(key):
        return
    llm_prefs.mark_group_greeted(key)
    try:
        await bot.send_group_msg(group_id=event.group_id, message=GREETING)
    except Exception as exc:
        logger.warning(f"group greeting failed: {exc}")


auto_chat = on_message(priority=99, block=False)


@auto_chat.handle()
async def handle_auto_chat(bot: Bot, event: GroupMessageEvent):
    # 新模块 chat_judge（LLM 判断是否在和 bot 聊天）启用时，旧的概率接话退位，避免重复回复
    if _env_int("JM_CHAT_JUDGE", 1) > 0:
        return
    if not AUTO_CHAT_ENABLED or not llm_enabled():
        return
    if not isinstance(event, GroupMessageEvent):
        return
    if str(event.user_id) == str(event.self_id):
        return

    text = event.get_message().extract_plain_text().strip()
    if not text:
        return

    # 权限：被禁的群不参与
    allowed, _ = check_event_access(event)
    if not allowed:
        return

    key = group_key(event)
    sender = getattr(event, "sender", None)
    nickname = str(getattr(sender, "card", "") or getattr(sender, "nickname", "") or "群友")
    _note_context(event.group_id, nickname, text)

    # 闭嘴/解禁（不需要 @）
    if await try_handle_silence_command(auto_chat, event, text):
        return
    if llm_prefs.is_group_silenced(key):
        return

    if not _is_chattable(text):
        return
    if not _rate_allows(event.group_id):
        return

    probability = 1.0 if _name_mentioned(text.lower()) else AUTO_CHAT_PROBABILITY
    if random.random() > probability:
        return

    reply = await build_auto_reply(event.group_id, key)
    if not reply:
        return
    _mark_replied(event.group_id)
    # 把自己说过的话也记进上下文，接话时避免重复句式
    _note_context(event.group_id, "小鱼", reply)
    try:
        await auto_chat.send(reply)
    except Exception as exc:
        logger.warning(f"auto chat send failed: {exc}")


def _collect_group_ids():
    """收集要发公告的群：在线群列表 + 本地记录过的群 + 白名单群。"""
    group_ids = set()
    try:
        cfg = load_control_config()
        for gid in cfg.get("allowed_groups") or []:
            group_ids.add(str(gid).strip())
    except Exception:
        pass
    for key in llm_prefs.group_state_keys():
        if str(key).startswith("group:"):
            group_ids.add(str(key)[len("group:"):])
    try:
        subscribers_file = Path(__file__).resolve().parent / "pixiv_subscribers.json"
        data = json.loads(subscribers_file.read_text(encoding="utf-8"))
        for gid in data.get("group") or []:
            group_ids.add(str(gid).strip())
    except Exception:
        pass
    return group_ids


driver = get_driver()


@driver.on_startup
async def announce_update_on_startup():
    """更新上线后在每个群里说一声；公告内容见项目根目录 UPDATE_NOTE.txt。"""
    if not ANNOUNCE_ENABLED:
        return
    await asyncio.sleep(20)

    try:
        bots = get_bots()
        if not bots:
            return
        bot = next(iter(bots.values()))
    except Exception as exc:
        logger.warning(f"announce startup failed to get bot: {exc}")
        return

    group_ids = _collect_group_ids()
    try:
        for group in await bot.get_group_list():
            gid = str(group.get("group_id") or "").strip()
            if gid:
                group_ids.add(gid)
    except Exception as exc:
        logger.warning(f"announce startup get_group_list failed: {exc}")

    if not group_ids:
        return

    note = _update_note()
    for gid in sorted(group_ids):
        key = f"group:{gid}"
        if not llm_prefs.announce_due(key, ANNOUNCE_COOLDOWN):
            continue
        llm_prefs.mark_announced(key)
        try:
            await bot.send_group_msg(group_id=int(gid), message=note)
        except Exception as exc:
            logger.warning(f"announce to group {gid} failed: {exc}")
