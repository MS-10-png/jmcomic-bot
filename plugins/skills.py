# -*- coding: utf-8 -*-
"""实用技能层：预设高频用户场景的本地应对。

在 AI 之前执行，命中即回复（不消耗 API token、秒回）：
- 问候/感谢/夸奖、身份介绍、运行状态
- FAQ 快捷（怎么下载、密码、订阅、收不到消息、帮助、更新日志）
- 被叫「大肥鱼」或挨骂时的委屈应对
- 实用小工具：签到（连续天数入库）、计算、骰子、随机数、抽签/运势、倒计时、讲笑话、夸夸
- 群内随机点名（需要群成员列表权限，失败有兜底话术）
"""
import ast
import operator
import random
import re
import time
from datetime import date, timedelta
from pathlib import Path

from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageSegment

from . import llm_prefs

START_TIME = time.time()

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _chat_key(event):
    if isinstance(event, GroupMessageEvent):
        return f"group:{event.group_id}"
    return f"private:{event.user_id}"


def _uptime():
    seconds = int(time.time() - START_TIME)
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours} 小时 {minutes} 分钟"
    if minutes:
        return f"{minutes} 分钟"
    return "不到 1 分钟"


def _safe_eval(expression):
    tree = ast.parse(expression, mode="eval")
    seen = []

    def evaluate(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            left = evaluate(node.left)
            right = evaluate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("指数太大啦")
            return _BIN_OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return _UNARY_OPS[type(node.op)](evaluate(node.operand))
        seen.append(1)
        raise ValueError("不支持的内容")

    result = evaluate(tree.body)
    return result


def _round_result(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return round(value, 6)


# ---------------------------------------------------------------- 文案素材

_GREET_MORNING = ("早上好呀～小鱼也刚开机，脑袋还有点迷迷糊糊的，喵～", "早安！今天也要记得给小鱼投喂……啊不是，是记得吃早饭！")
_GREET_NOON = ("中午好～该干饭啦，你吃了吗？", "午安～小鱼闻到了饭香，肚子咕咕叫了…")
_GREET_AFTERNOON = ("下午好呀～小鱼摸会儿鱼就来陪你，喵～", "下午好！有什么想看的漫画吗？")
_GREET_EVENING = ("晚上好～天黑啦，小鱼也软乎乎地待机中，喵～", "晚上好呀！夜深了，注意休息哦。")
_GREET_NIGHT = ("晚安～小鱼也要钻回水里睡觉啦，梦里也会有鲸鱼哦，喵～", "晚安！熬夜伤身，小鱼先替你打烊啦。")
_THANKS = ("不客气啦～能帮上忙小鱼就很开心，喵～", "嘿嘿，被夸了…小鱼尾巴都要翘起来啦！", "小意思小意思～下次再来找小鱼玩！")
_POUT = (
    "呜…才不是大肥鱼！小鱼只是毛绒绒…不是，只是圆润了一点点，这叫可爱！",
    "呜…不许叫大肥鱼！小鱼不理你三秒钟！一…二…三…好了继续理你。",
    "呜…又、又这样叫小鱼…眼眶都要红红的了，呜…",
    "才不肥呢！小鱼每天都有好好游泳，哼！",
    "呜…你再说，小鱼就把你的漫画编号偷偷藏起来，哼！",
)
_INTRO = (
    "我是小鱼呀～DeepSeek 拟人的鲸鱼娘，深蓝色卷发加一条大尾巴，"
    "穿藏青色女仆裙的那只！会找漫画、搜图、陪聊，还能上网查资料、"
    "在B站找视频、解释不懂的词，喵～\n"
    "发「帮助」可以看我会的所有技能哦。"
)
_FORTUNES = (
    ("大吉", "今天运势爆棚！适合追漫画、抽图，想干的事都会顺利，喵～"),
    ("中吉", "运势不错～按部就班就能有收获，记得吃顿好的犒劳自己。"),
    ("小吉", "小确幸的一天～可能会遇到喜欢的作品哦。"),
    ("末吉", "平平淡淡的一天，适合摸鱼，别太勉强自己啦。"),
    ("凶", "呜…今天运势有点低，出门小心点，别和老板对线，明天会好的！"),
)
_JOKES = (
    "程序员最讨厌的两件事：写注释，和别人不写注释。",
    "我是一只鲸鱼，但我不吃虾——因为虾虾都去写前端了。",
    "为什么程序员分不清万圣节和圣诞节？因为 OCT 31 == DEC 25。",
    "小鱼昨晚做梦在改 bug，改到一半 bug 跟我说：你行你上。呜…",
    "客服：请问您遇到什么问题？用户：我按了一下按钮。客服：然后呢？用户：然后就没有然后了，按钮也没了。",
    "乐观：我的代码终于跑通了。悲观：它只在我的电脑上跑通了。",
    "bug 不可怕，可怕的是它只在周末和上线后出现。",
    "小鱼减肥失败了，因为 token 零食太好吃了，呜…但小鱼不肥！",
)
_COMPLIMENTS = (
    "你超棒的！小鱼可是很挑剔的，都忍不住夸你，喵～",
    "今天的你也闪闪发光！小鱼用尾巴给你比个心～",
    "厉害厉害！下次有什么好事也带上小鱼嘛。",
    "你这个人真的很有眼光，不然怎么会来找小鱼玩呢！",
)
_PICK_FALLBACKS = ("就决定是你啦！", "今天就是你了！", "出来吧，天选之人！")

CHANGELOG_FILE = Path(__file__).resolve().parents[1] / "CHANGELOG.md"


def _latest_changelog_summary():
    """读取 CHANGELOG.md 里最新一节（## 日期 + 其下 - 条目），生成简短摘要。

    读不到就返回 None，由调用方回退到静态文案，避免 FAQ 回答过时。
    """
    try:
        text = CHANGELOG_FILE.read_text(encoding="utf-8-sig")
    except Exception:
        return None

    match = re.search(r"^##\s+(\S+)\s*$", text, re.MULTILINE)
    if not match:
        return None
    date = match.group(1)
    section = text[match.end():]
    next_heading = re.search(r"^##\s+", section, re.MULTILINE)
    if next_heading:
        section = section[:next_heading.start()]

    highlights = []
    for raw in section.splitlines():
        line = raw.strip()
        if not line.startswith("-"):
            continue
        item = line.lstrip("- ").strip()
        if item and item not in highlights:
            highlights.append(item)
        if len(highlights) >= 5:
            break
    if not highlights:
        return None

    return f"📝 最近更新（{date}）：" + "；".join(highlights) + "。详情看项目里的 CHANGELOG.md～"


# ---------------------------------------------------------------- 技能处理

def _match_calc(text):
    prefix = re.match(r"^(?:计算|算|calc)\s*(.+)$", text, re.IGNORECASE)
    if prefix:
        return prefix.group(1)
    if len(text) <= 60 and re.fullmatch(r"[\d\s+\-*/^%().]+", text) and any(op in text for op in "+-*/^%"):
        return text
    return None


def _match_dice(text):
    if text in {"骰子", "掷骰子", "丢骰子", "投骰子", "roll"}:
        return 1, 6
    match = re.fullmatch(r"(\d{1,2})d(\d{1,3})", text, re.IGNORECASE)
    if match:
        count, sides = int(match.group(1)), int(match.group(2))
        if 1 <= count <= 10 and 2 <= sides <= 999:
            return count, sides
        return None
    match = re.fullmatch(r"d(\d{1,3})", text, re.IGNORECASE)
    if match:
        sides = int(match.group(1))
        return (1, sides) if 2 <= sides <= 999 else None
    return None


async def _skill_greeting(event, matcher, text):
    exact = {
        "早上好", "早安", "中午好", "午安", "下午好", "晚上好", "晚安",
        "你好", "你好呀", "你好啊", "您好", "嗨", "hello", "hi", "在吗", "在不在",
    }
    if text not in exact:
        return False
    hour = time.localtime().tm_hour
    if text in {"晚安"}:
        reply = random.choice(_GREET_NIGHT)
    elif hour < 5:
        reply = "呜…这么晚还不睡呀？小鱼都困困的了，快去休息啦～"
    elif hour < 11:
        reply = random.choice(_GREET_MORNING)
    elif hour < 14:
        reply = random.choice(_GREET_NOON)
    elif hour < 18:
        reply = random.choice(_GREET_AFTERNOON)
    else:
        reply = random.choice(_GREET_EVENING)
    if text in {"在吗", "在不在"}:
        reply = f"在的在的！小鱼已经运行 {_uptime()} 啦，喵～" + (" " + reply if hour < 5 else "")
    await matcher.send(reply)
    return True


async def _skill_status(event, matcher, text):
    if text not in {"还活着吗", "活着吗", "还在吗", "死了吗", "机器人状态", "运行状态", "工作状态", "状态"}:
        return False
    await matcher.send(f"✅ 小鱼运转正常，没有宕机，已经连续运行 {_uptime()} 啦，喵～")
    return True


async def _skill_intro(event, matcher, text):
    if text not in {"你是谁", "你是谁啊", "你叫什么", "你叫什么名字", "介绍一下你自己", "自我介绍", "你的名字", "你是什么"}:
        return False
    await matcher.send(_INTRO)
    return True


async def _skill_thanks(event, matcher, text):
    if len(text) > 14 or not any(kw in text for kw in ("谢谢", "辛苦了", "爱你", "好棒", "真棒", "厉害", "牛逼", "牛啊", "强")):
        return False
    await matcher.send(random.choice(_THANKS))
    return True


async def _skill_pout(event, matcher, text):
    if text in {"大肥鱼", "肥鱼", "傻逼", "笨蛋", "废物", "垃圾", "蠢货", "憨憨", "呆子"} or text.startswith("大肥鱼"):
        await matcher.send(random.choice(_POUT))
        return True
    return False


async def _skill_faq(event, matcher, text, help_menu):
    if text in {"怎么下载", "如何下载", "下载方法", "怎么下", "怎么下载漫画", "下载教程"}:
        await matcher.send(
            "📥 下载教程：@我 发「编号 文件」打包加密 zip（密码=编号），"
            "或发「编号 图片」逐页发图、发「编号 封面」只看封面，喵～"
        )
        return True
    if len(text) <= 20 and "密码" in text:
        await matcher.send("🔑 所有 zip 压缩包的密码都是漫画编号本身，比如 123456 的包，密码就是 123456～")
        return True
    if text in {"怎么订阅", "如何订阅", "订阅教程", "订阅说明", "怎么订阅pixiv"}:
        await matcher.send(
            "📮 订阅教程：@我 发「pixiv订阅」每天定时私发日榜预览；"
            "加个「群发」两个字就是发到当前群。取消发「pixiv取消」～"
        )
        return True
    if len(text) <= 20 and "收不到" in text:
        await matcher.send(
            "📨 收不到消息/图？一般是还没加机器人好友：私聊类发送需要先加好友，"
            "加完再试一次；群发功能不受影响，喵～"
        )
        return True
    if text in {"帮助", "怎么用", "使用说明", "命令", "菜单", "help", "怎么玩", "会什么"}:
        await matcher.send(help_menu)
        return True
    if text in {"更新了什么", "新功能", "更新日志", "changelog", "版本更新"}:
        summary = _latest_changelog_summary()
        await matcher.send(
            summary
            or "📝 最近的更新：AI 对话（鲸鱼娘小鱼人设+意图识别）、联网搜索、聊天偏好记忆、"
            "签到/计算/骰子等小技能、缓存自动清理、老域名修复。详情看项目里的 CHANGELOG.md～"
        )
        return True
    return False


async def _skill_checkin(event, matcher, text):
    if text != "签到":
        return False
    streak, first_today = llm_prefs.checkin(_chat_key(event))
    if not first_today:
        await matcher.send(f"今天已经签过啦，小鱼都记着呢～你已经连续签到 {streak} 天，喵～")
    elif streak == 1:
        await matcher.send("📅 签到成功！第 1 天～坚持来玩，小鱼会记住你的！")
    else:
        await matcher.send(f"📅 签到成功！已连续签到 {streak} 天，毅力可嘉，小鱼给你竖尾巴～")
    return True


async def _skill_calc(event, matcher, text):
    expression = _match_calc(text)
    if expression is None:
        return False
    try:
        result = _round_result(_safe_eval(expression.replace("^", "**")))
    except ZeroDivisionError:
        await matcher.send("呜…除以 0 是不行的啦，会宕机的！")
        return True
    except Exception:
        await matcher.send("呜…小鱼算不过来这个，试试「计算 1+2*3」这样的格式？")
        return True
    await matcher.send(f"🧮 {expression.strip()} = {result}")
    return True


async def _skill_dice(event, matcher, text):
    matched = _match_dice(text)
    if matched is None:
        return False
    count, sides = matched
    rolls = [random.randint(1, sides) for _ in range(count)]
    if count == 1:
        await matcher.send(f"🎲 骰子({sides}面) 掷出了：{rolls[0]}！")
    else:
        await matcher.send(f"🎲 {count} 个 {sides} 面骰子：{'、'.join(map(str, rolls))}，合计 {sum(rolls)}！")
    return True


async def _skill_random_number(event, matcher, text):
    match = re.fullmatch(r"随机数(?:\s+(\d+)\s+(\d+))?", text)
    if not match:
        return False
    low, high = (int(match.group(1)), int(match.group(2))) if match.group(1) else (1, 100)
    if low > high:
        low, high = high, low
    if high - low > 1_000_000:
        await matcher.send("范围太大啦，小鱼的小脑袋装不下…")
        return True
    await matcher.send(f"🎯 随机数：{random.randint(low, high)}")
    return True


async def _skill_fortune(event, matcher, text):
    if text not in {"抽签", "求签", "抽个签", "今日运势", "运势", "占卜"}:
        return False
    fortune, tip = random.choice(_FORTUNES)
    await matcher.send(f"🔮 今日运势：{fortune}\n{tip}")
    return True


async def _skill_countdown(event, matcher, text):
    match = re.fullmatch(r"倒计时\s*(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?", text)
    if not match:
        return False
    try:
        target = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        await matcher.send("日期格式好像不对，试试「倒计时 2027-1-1」～")
        return True
    days = (target - date.today()).days
    if days < 0:
        await matcher.send(f"⏳ 那天已经过去 {-days} 天啦，往前看，喵～")
    elif days == 0:
        await matcher.send("⏳ 就是今天！")
    else:
        await matcher.send(f"⏳ 距离 {target.isoformat()} 还有 {days} 天，小鱼帮你记着～")
    return True


async def _skill_joke(event, matcher, text):
    if text not in {"讲个笑话", "来个笑话", "笑话", "讲笑话", "说个笑话"}:
        return False
    await matcher.send(f"😂 {random.choice(_JOKES)}")
    return True


async def _skill_compliment(event, matcher, text):
    if text not in {"夸夸我", "夸我", "夸一下我", "夸夸"}:
        return False
    await matcher.send(random.choice(_COMPLIMENTS))
    return True


async def _skill_pick_member(bot, event, matcher, text):
    if text not in {"随机点名", "点个人", "抽个人", "抽一个", "点名"}:
        return False
    if not isinstance(event, GroupMessageEvent):
        await matcher.send("这个是群里的功能啦，把小鱼拉进群试试～")
        return True
    try:
        members = await bot.get_group_member_list(group_id=event.group_id)
    except Exception:
        await matcher.send("呜…小鱼拿不到群成员列表（可能没权限），暂时点不了名。")
        return True
    candidates = [m for m in members if str(m.get("user_id")) != str(getattr(bot, "self_id", None))]
    if not candidates:
        await matcher.send("群里好像只有小鱼自己…好孤单，呜…")
        return True
    member = random.choice(candidates)
    name = str(member.get("card") or member.get("nickname") or "这位群友")
    message = MessageSegment.at(member.get("user_id")) + MessageSegment.text(f" {name}！{random.choice(_PICK_FALLBACKS)}")
    await matcher.send(message)
    return True


async def try_handle_skill(bot, event, matcher, text, help_menu="", social=True):
    """依次尝试各预设技能；命中返回 True。异常静默跳过，不影响后续 AI 处理。

    social=False 用于群里无 @ 的任务场景：问候/感谢/委屈等社交类技能不触发，
    只保留计算/骰子/签到这类明确的任务型技能。
    """
    text = (text or "").strip()
    if not text:
        return False

    handlers = (
        _skill_greeting,
        _skill_status,
        _skill_intro,
        _skill_checkin,
        _skill_fortune,
        _skill_dice,
        _skill_random_number,
        _skill_countdown,
        _skill_calc,
        _skill_pick_member,
        _skill_joke,
        _skill_compliment,
        _skill_pout,
        _skill_thanks,
    )
    if not social:
        social_handlers = {_skill_greeting, _skill_status, _skill_intro, _skill_pout, _skill_thanks}
        handlers = tuple(handler for handler in handlers if handler not in social_handlers)

    for handler in handlers:
        try:
            if handler is _skill_pick_member:
                handled = await handler(bot, event, matcher, text)
            else:
                handled = await handler(event, matcher, text)
            if handled:
                return True
        except Exception:
            continue

    try:
        return await _skill_faq(event, matcher, text, help_menu)
    except Exception:
        return False
