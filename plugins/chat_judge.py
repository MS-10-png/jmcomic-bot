# -*- coding: utf-8 -*-
"""自启动聊天判断模块：LLM 识别用户是否在和 bot 聊天，是才接话，否则安静。

- 随 bot 启动自动生效（on_message 监听群消息），无需 @、无需手动开启；
- 核心：LLM 结合最近群聊上下文，判断最新这条消息是不是在跟「小鱼」说话
  （提到名字 / 回应小鱼刚说的话 / 向小鱼提问使唤 / 群友等小鱼表态），
  是 → 以小鱼口吻接一句；不是 → 保持安静，不刷屏；
- 发完消息着重检测下一句：小鱼刚在群里发过话（默认 90 秒内），用户紧接着的
  下一句视为回复 bot，跳过冷却强制判断，并提示 LLM 重点判断；
  下一句会先按「任务需求」判断（第2页/下一页翻页、私发/群发、文件/图片/封面、
  全部、换一批、满意/换一张等续接指令，以及明确任务指令）——是任务就执行并结束，
  不是任务才走对话判断，做到「每句话都找是不是对话或任务需求」；
- 带冷却与每小时上限；提到小鱼/机器人名字时不受冷却限制，必然判断；
- 尊重「小鱼闭嘴」禁言机制、权限配置与聊天偏好；
- 平时不执行功能任务（任务走 at_comic / no_at_task 管线），
  唯独「bot 发完消息后的下一句」会先尝试任务需求，避免用户续任务被当成闲聊；
  Pixiv 互动短语（满意/换一张/我已满18岁等）由 pixiv_interactive 先处理，这里跳过。
"""
import json
import os
import random
import time

from nonebot import logger, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent

from . import llm_prefs
from .bot_control import check_event_access
from .group_chat import (
    _context,
    _is_chattable,
    _name_mentioned,
    _note_context,
    context_lines,
    group_key,
    last_bot_spoke_ts,
    try_handle_silence_command,
)
from .llm_chat import PERSONA_CORE, clean_reply, llm_chat, llm_enabled, parse_json_object


def _env_int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


CHAT_JUDGE_ENABLED = _env_int("JM_CHAT_JUDGE", 1) > 0
JUDGE_MIN_INTERVAL = max(10, _env_int("JM_CHAT_JUDGE_MIN_INTERVAL", 30))
JUDGE_MAX_PER_HOUR = max(1, _env_int("JM_CHAT_JUDGE_MAX_PER_HOUR", 10))
# 「发完消息后着重检测下一句」：bot 说完话后这个秒数内，用户下一句视为回复 bot，
# 跳过冷却强制判断，并提示 LLM 重点判断（默认 90 秒）
FOLLOWUP_WINDOW = max(10, _env_int("JM_CHAT_JUDGE_FOLLOWUP_SECONDS", 90))

# 冷却与频率：group_id -> 状态（与 group_chat 的旧概率接话相互独立）
_last_judge: dict = {}
_hour_counters: dict = {}


def last_bot_speak_ts(group_id):
    """扫描群上下文里「小鱼」（bot）最后一次说话的时间戳；没有则返回 0。

    无论 bot 是通过 chat_judge 接话、还是任务管线发结果（搜索/下载/推送等），
    只要记进了群上下文或 _bot_spoke_ts 打点，就能感知「bot 刚发完消息」，
    从而对用户的下一句话着重检测——下一句可能是对话，也可能是任务需求（第2页/私发/文件…）。
    """
    last = 0.0
    for ts, nickname, _text in _context.get(group_id, []):
        if nickname == "小鱼":
            last = max(last, float(ts))
    return max(last, last_bot_spoke_ts(group_id))


JUDGE_SYSTEM_PROMPT = (
    PERSONA_CORE
    + "你正潜伏在一个 QQ 群里。下面是最近的群聊记录，最后一条是刚发生的消息，"
    "每条前面是发言者昵称。\n"
    "请判断最新这条消息是不是在跟「小鱼」（你）说话、需要你回应。\n"
    "算「在和 bot 聊天」的情况：\n"
    "- 直接提到你（小鱼/肥鱼/鲸鱼/机器人/二号）；\n"
    "- 在回应你刚才说过的话（回答你的问题、接你的话茬、顺着你的梗继续聊）；\n"
    "- 在向你提问、使唤你（如「帮我找本…」「来点图」「推荐几本」即使没 @ 也是在叫你）；\n"
    "- 群友们在聊你或明显等你表态（如「小鱼你怎么看」「问问小鱼」「叫小鱼来」）。\n"
    "不算「在和 bot 聊天」：群友之间纯闲聊、互怼、报新闻、发链接，跟你无关；\n"
    "只是偶然提到数字或漫画话题但没有使唤你。\n"
    "拿不准的时候一律判定为 false（宁可沉默，也不要硬接话打扰群聊）。\n"
    "只输出一个 JSON 对象，不要输出其他文字：\n"
    '{"directed_to_bot": 是否在和 bot 聊天(true/false), "reply": "要接就说一句小鱼口吻的话，最多30字；不该接就空字符串"}\n'
    "回复要求：口语自然、像普通群友，不要客套、不要写动作描写、不要使用任何 markdown 符号、"
    "不要推销功能、不要编造群里没发生的事、不要重复小鱼自己刚说过的话。"
)


def _judge_rate_allows(group_id):
    now = time.time()
    last = _last_judge.get(group_id, 0.0)
    if now - last < JUDGE_MIN_INTERVAL:
        return False
    hour_start, count = _hour_counters.get(group_id, (0.0, 0))
    if now - hour_start > 3600:
        _hour_counters[group_id] = (now, 0)
    elif count >= JUDGE_MAX_PER_HOUR:
        return False
    return True


def _mark_judged(group_id):
    now = time.time()
    _last_judge[group_id] = now
    hour_start, count = _hour_counters.get(group_id, (now, 0))
    if now - hour_start > 3600:
        hour_start, count = now, 0
    _hour_counters[group_id] = (hour_start, count + 1)


async def judge_and_reply(group_id, group_key_id, followup_hint=""):
    """用 LLM 判断最新消息是否在和 bot 聊天；是则生成接话。返回 (directed, reply) 或 None。

    followup_hint：bot 刚发完消息、用户在窗口内回话时，附加给 LLM 的重点提示。
    """
    lines = context_lines(group_id)
    if not lines:
        return None

    directive = llm_prefs.style_directive(group_key_id)
    messages = [{"role": "system", "content": JUDGE_SYSTEM_PROMPT}]
    if directive:
        messages.append({"role": "system", "content": f"【聊天偏好，必须遵守】{directive}"})
    messages.append({"role": "user", "content": "最近的群聊记录（最后一条是最新消息）：\n" + "\n".join(lines)})
    final_prompt = "输出 JSON："
    if followup_hint:
        final_prompt = followup_hint + "\n\n输出 JSON："
    messages.append({"role": "user", "content": final_prompt})

    try:
        raw = llm_chat.chat_raw(messages, temperature=0.8)
    except Exception as exc:
        logger.warning(f"chat judge failed: {exc}")
        return None

    obj = parse_json_object(raw)
    directed = bool(obj.get("directed_to_bot"))
    reply = clean_reply(str(obj.get("reply") or "")).strip().strip('"').strip("“”「」")
    if not reply or len(reply) > 80:
        reply = ""
    if reply in {"空", "无", "（空）", "...", "…"}:
        reply = ""
    return directed, reply


chat_judge = on_message(priority=98, block=False)


@chat_judge.handle()
async def handle_chat_judge(bot: Bot, event: GroupMessageEvent):
    if not CHAT_JUDGE_ENABLED:
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
    if await try_handle_silence_command(chat_judge, event, text):
        return
    if llm_prefs.is_group_silenced(key):
        return

    # Pixiv 互动短语（满意/不满意/换一张/我已满18岁/来点图等）已由 pixiv_interactive（priority 35）
    # 先处理过，这里直接跳过，避免重复回复/重复发图。
    try:
        from .jmcomic_bot import is_pixiv_interactive_phrase
        if is_pixiv_interactive_phrase(text):
            return
    except Exception:
        pass

    # 「bot 发完消息后的下一句」：先算窗口（放在闲聊字数门槛之前，短指令也算任务候选）
    now = time.time()
    bot_ts = last_bot_speak_ts(event.group_id)
    is_followup = bot_ts > 0 and (now - bot_ts) <= FOLLOWUP_WINDOW

    # 下一句优先按「任务需求」判断：第2页/下一页/私发/群发/文件/图片/封面/全部/换一批/满意…
    # 是任务就执行并结束；不是任务（纯闲聊）才走下面的对话判断（跳过冷却强制判断）。
    # 这里不依赖 LLM：续接指令与确定性任务都是本地解析，LLM 不可用时也能干活。
    if is_followup:
        from .jmcomic_bot import try_followup_task
        try:
            if await try_followup_task(bot, event, chat_judge, text, key):
                _mark_judged(event.group_id)
                return
        except Exception as exc:
            logger.warning(f"followup task failed: {exc}")

    # 对话判断需要 LLM
    if not llm_enabled():
        return

    if not _is_chattable(text):
        return

    mentioned = _name_mentioned(text.lower())
    if not is_followup and not mentioned and not _judge_rate_allows(event.group_id):
        return

    followup_hint = ""
    if is_followup:
        seconds = max(1, int(now - bot_ts))
        followup_hint = (
            f"【判断提示】小鱼刚在群里发过消息（{seconds} 秒前），"
            "最新这条用户消息紧接着小鱼发言之后，极大概率是在回复小鱼。"
            "任务需求系统已先处理过，走到这里默认是闲聊；"
            "除非明显是群友之间互聊，否则 directed_to_bot 应为 true，并给出小鱼的接话。"
        )

    result = await judge_and_reply(event.group_id, key, followup_hint=followup_hint)
    if not result:
        return
    directed, reply = result
    _mark_judged(event.group_id)
    if not directed or not reply:
        return

    # 把自己说过的话也记进上下文，避免重复句式
    _note_context(event.group_id, "小鱼", reply)
    try:
        await chat_judge.send(reply)
    except Exception as exc:
        logger.warning(f"chat judge send failed: {exc}")
