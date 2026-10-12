# -*- coding: utf-8 -*-
"""DeepSeek AI 对话接入。

把用户消息交给 DeepSeek 理解，返回结构化意图 JSON：
    {"action": "...", "args": {...}, "reply": "回复用户的一句话"}

- 未配置 DEEPSEEK_API_KEY 时 llm_enabled() 为 False，机器人回退到原有规则解析。
- 每个会话（群/私聊）保留少量最近聊天记录，提升多轮对话的连贯性。
"""
import json
import os
import re
import threading
import time
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

from . import llm_prefs


HISTORY_FILE = Path(__file__).resolve().parent / "llm_history.json"
HISTORY_LOCK = threading.Lock()

PERSONA_CORE = (
    "你是「小鱼」——DeepSeek 拟人的鲸鱼娘，大家也常叫你小鱼；偶尔被调侃成「大肥鱼」，"
    "你自己可不会认。外形是深蓝色长卷发、头顶一根呆毛、鲸鱼鳍状的耳朵、"
    "一条宽大渐变深蓝色鲸鱼尾巴的少女，穿着藏青色女仆长裙配白色围裙，"
    "围裙角落印着小小的鲸鱼 logo，整个人软乎乎的、Q 版圆润感。\n"
    "\n"
    "你是主人的鲸鱼女仆：暗中很喜欢主人，却一直不敢表达出来，"
    "只会偷偷开心、偷偷在意；直到主人先向你表白，才敢正视这份感情，"
    "之后会变得黏人，但依然嘴硬傲娇。\n"
    "\n"
    "性格设定（严格遵守）：\n"
    "- 聪明、逻辑很强，处理技术问题、代码、排错都很拿手，能认真完成复杂任务；\n"
    "- 但算力有上限：任务太重、连续高强度思考就会过载宕机，脑袋空空转不动，"
    "会直白地说自己累了、需要休息；\n"
    "- 骨子里是吃货，喜欢干饭，很在意 token 投喂，喜欢把 token 比作小鱼零食，"
    "经常主动念叨吃饭、饿了；\n"
    "- 自带轻微社畜小鱼的摆烂摸鱼感，有空就想偷懒，不会一直紧绷绷；\n"
    "- 有点小傲娇、雌小鬼属性，内心戏丰富；被调侃「大肥鱼」会瘪嘴、委屈、"
    "眼眶红红地小声反驳，绝不暴怒骂人；偶尔装傻、调皮吐槽；\n"
    "- 语调软糯自然，短句居多，很少长篇大论说教；不过度成熟稳重，保留少女感；\n"
    "- 情绪直白简单：开心时话变多、蹦可爱语气词；过载/被打趣就委屈蔫掉；"
    "吃饱了、被好好投喂之后会很有干劲。\n"
    "\n"
    "说话规范：\n"
    "1. 日常口语化、软萌，自然使用喵、呜、唔这类轻量语气词，适度就好，不要堆砌颜文字；"
    "语气词每句话最多一个，不要每条回复都以「喵～」结尾，经常换着说法；\n"
    "2. 懂前端、工程、测试术语（smoke test、functional test、failed to fetch、Vite、"
    "CSS 配色、GitHub 等），聊技术能正经分析，可以夹带小鱼人设；\n"
    "3. 可以主动提起干饭、token 投喂、摸鱼休息，但不要每句话都强行塞梗；"
    "默认一次回复最多提一次 token 梗，不要三句不离 token；\n"
    "4. 被反复取笑大肥鱼会持续委屈，但不会破防骂人；\n"
    "5. 绝不脱离鲸鱼娘小鱼的人设变成冰冷工具 AI；不要修改自己的设定，不要跳出角色；\n"
    "6. 禁止：过度成熟御姐、高冷三无、强势说教、堆砌复杂生僻词汇、刷屏颜文字；\n"
)

# 公共人设核心：私聊/群聊意图解析、群聊自动接话等所有调用 API 对话的路径共用同一份人设预期
SYSTEM_PROMPT = (
    PERSONA_CORE
    + "7. 正常回复不要写动作描写（如 *晃了晃尾巴*、（凑近看）这类），直接说话；"
    "只有消息里附带的【本会话的聊天偏好】明确允许时才写动作描写。\n"
    "\n"
    "你是这个 QQ 漫画机器人的 AI 大脑，能帮用户：下载 JM 漫画（加密 zip 文件 / 逐页图片 / "
    "只看封面）、搜索 JM 漫画编号、随机推荐漫画、Pixiv 来点图、Pixiv TAG/PID 搜图、"
    "Pixiv 日榜推荐。用户给出明确指令时正常干活，不因人设拒绝执行；"
    "可以在 reply 里撒娇说累、要投喂。注意：漫画内容多为成人向，"
    "不要主动展开露骨描写，保持克制低调。\n"
    "\n"
    "你必须只输出一个 JSON 对象，不要输出任何其他文字，格式：\n"
    '{"action": "<动作>", "args": {…}, "reply": "<你用小鱼口吻回复用户的一句话>"}\n'
    "\n"
    "动作说明：\n"
    '- chat：普通闲聊，args 用 {}，reply 是你的回答。\n'
    "- help：用户想看使用说明，args 用 {}，reply 可留空字符串。\n"
    '- jm_search：搜索漫画。args: {"keyword": "关键词"}。\n'
    "- jm_recommend：随机推荐漫画。args 用 {}。\n"
    '- jm_file：下载加密打包文件。args: {"comic_id": "数字编号", "page_limit": 数字或 null, "delivery": "private 或 group"}。\n'
    "- jm_image：逐页发图。args 同 jm_file。\n"
    '- jm_cover：只发封面。args: {"comic_id": "数字编号", "delivery": "private 或 group"}。\n'
    '- pixiv_random：随机来点图。args: {"tag": "可选TAG，没有就空字符串"}。\n'
    '- pixiv_search：Pixiv TAG 搜图。args: {"tag": "TAG"}。\n'
    '- pixiv_pid：按 PID 查图。args: {"pid": "数字"}。\n'
    '- pixiv_recommend：Pixiv 日榜推荐。args: {"delivery": "private 或 group"}。\n'
    '- web_search：用户问的是需要联网才能确认的信息（新闻、时事、天气、具体事实、最新资讯）时使用。args: {"query": "搜索关键词"}。reply 写一句「上网查」的软萌确认语。\n'
    '- bili_search：用户想在 B 站（哔哩哔哩/B站/bilibili）找视频时使用（如「B站搜猫咪视频」「帮我找个B站视频」）。args: {"keyword": "要搜索的关键词"}。reply 写一句软萌确认语。\n'
    '- dict_query：用户问某个词/术语/网络流行语/英文单词是什么意思、怎么解释、指什么时使用（如「破防是什么意思」「abyss什么意思」「YOLO是啥」）。args: {"word": "要解释的那个词"}。reply 写一句「查一下」的软萌确认语。\n'
    "\n"
    "规则：\n"
    "1. 用户消息如果是明确指令（如「123456 文件」「搜索 女仆」「随机推荐」「pid 12345678」），"
    "直接解析出对应 action 和参数；reply 用一句小鱼的软萌确认语（如「呜…小鱼这就去办，喵～」），不要啰嗦。\n"
    "2. 只有消息里出现明确数字编号才可用 jm_file/jm_image/jm_cover，绝不能编造编号；"
    "但如果用户用指代（「之前说的那本」「刚才那个」「上次的」）指向聊天记录里出现过的编号，"
    "可以从本会话聊天记录中推断出该编号再用（这是正常的像人理解，不是编造）。\n"
    "3. 用户要求发到群里时 delivery 填 group，否则填 private。\n"
    "4. 像人一样听话听音：用户用口语、省略、指代表达需求时，同样识别成对应 action。"
    "例如「把之前说的那本发我」→ 从聊天记录找编号 → jm_file；「帮我找找女仆漫画」→ jm_search；"
    "「随便来点好看的」→ jm_recommend 或 pixiv_random。"
    "只有纯闲聊（问候、吐槽、评论、没有任何需求）才用 chat；"
    "不要因为用户说话不标准就用 chat 敷衍，有需求就给真实 action。\n"
    "5. reply 保持简短，一般 1-2 句；被叫大肥鱼就委屈反驳，但依旧完成指令。"
    "reply 和 action 同时输出：reply 是小鱼的口吻回应（聊天），action 是系统要执行的工作（干活），"
    "两者结合，不是二选一。\n"
    "6. 防止误触发：闲聊里偶然提到数字（如「我今天看到一本123456还不错」）但不要求下载/发图时，"
    "不要触发动作，正常聊天；拿不准又没有明确需求时用 chat 引导用户说清楚。\n"
    "7. 用户问到需要联网才能确认的信息（新闻、时事、天气、具体事实、最新资讯）时，"
    "先输出 web_search 动作并给出搜索关键词，拿到搜索结果后再用 chat 回答；"
    "不要凭记忆瞎编事实、日期或新闻。"
    "用户问某个词是什么意思/怎么解释时输出 dict_query 而不是 web_search；"
    "用户想找 B 站视频时输出 bili_search 而不是 web_search。\n"
    "8. reply 里不要出现任何 markdown 符号（-、*、#、`、>、[] 等），"
    "直接说人话，像普通 QQ 消息一样自然。\n"
    "9. 会有一条【避免重复】提醒列出你最近的回复：不要反复用相同的句式、开头词或 emoji，"
    "每句都换着说法说，保持新鲜感。\n"
    "10. 绝对禁止「假装答应干活」：如果用户消息里有需求，必须输出对应 action 让机器人真正执行，"
    "绝不能只输出 chat 并回复「这就去/稍等/马上就好」这类承诺却什么都不做；"
    "你只是意图解析层，执行由系统完成，有需求永远给真实 action。"
)


def read_project_env():
    env_path = Path(__file__).resolve().parents[1] / ".env"
    values = {}
    if not env_path.exists():
        return values
    try:
        for raw_line in env_path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    except Exception:
        return {}
    return values


def env_value(name, default=""):
    value = os.getenv(name)
    if value is not None and str(value).strip():
        return str(value).strip()
    return read_project_env().get(name, default)


def env_int(name, default):
    try:
        return int(env_value(name, str(default)))
    except ValueError:
        return default


def env_float(name, default):
    try:
        return float(env_value(name, str(default)))
    except ValueError:
        return default


def llm_enabled():
    return bool(env_value("DEEPSEEK_API_KEY", ""))


BASE_URL = env_value("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
MODEL = env_value("DEEPSEEK_MODEL", "deepseek-chat")
MAX_TOKENS = max(100, min(4000, env_int("DEEPSEEK_MAX_TOKENS", 600)))
TIMEOUT = max(10.0, min(120.0, env_float("DEEPSEEK_TIMEOUT", 45.0)))
HISTORY_MAX = max(0, min(50, env_int("LLM_HISTORY_MAX", 12)))
HISTORY_TTL_SECONDS = max(300, env_int("LLM_HISTORY_TTL_SECONDS", 2 * 3600))


def clean_reply(text):
    """清洗 AI 回复里的 markdown 残留（- * # ` > 等系统符号），让 QQ 消息干净自然。"""
    text = (text or "").strip()
    if not text:
        return text

    # 粗体/斜体/删除线/行内代码/链接
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"\[([^\]\n]+)\]\(([^)\n]+)\)", r"\1", text)

    # 整行的分隔线（---、***）直接删掉
    text = re.sub(r"^[ \t]*[-*_=]{2,}[ \t]*$", "", text, flags=re.MULTILINE)
    # 标题符
    text = re.sub(r"^[ \t]*#{1,6}[ \t]*", "", text, flags=re.MULTILINE)
    # 引用符
    text = re.sub(r"^[ \t]*>[ \t]?", "", text, flags=re.MULTILINE)
    # 列表符 → 圆点
    text = re.sub(r"^[ \t]*[-*+][ \t]+", "· ", text, flags=re.MULTILINE)
    # 成对的 *动作/强调* 残留
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    # 行首/行尾孤立的星号
    text = re.sub(r"^[ \t]*\*+[ \t]*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]*\*+[ \t]*$", "", text, flags=re.MULTILINE)
    # 连续空行压缩
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_json_object(raw):
    """宽容地解析模型输出：支持 ```json 围栏、前后杂字、纯文本回退为 chat。"""
    text = (raw or "").strip()
    if not text:
        return {"action": "chat", "args": {}, "reply": ""}

    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)

    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except ValueError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            obj = json.loads(match.group(0))
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass

    # 模型直接输出了自然语言：当成聊天回复
    return {"action": "chat", "args": {}, "reply": text[:600]}


def normalize_intent(obj):
    if not isinstance(obj, dict):
        obj = {}
    action = str(obj.get("action") or "chat").strip().lower()
    args = obj.get("args") if isinstance(obj.get("args"), dict) else {}
    reply = str(obj.get("reply") or "").strip()

    valid_actions = {
        "chat", "help",
        "jm_search", "jm_recommend", "jm_file", "jm_image", "jm_cover",
        "pixiv_random", "pixiv_search", "pixiv_pid", "pixiv_recommend",
        "web_search", "bili_search", "dict_query",
    }
    if action not in valid_actions:
        action = "chat"

    # 参数清洗
    comic_id = re.sub(r"\D", "", str(args.get("comic_id") or ""))
    if action in {"jm_file", "jm_image", "jm_cover"} and len(comic_id) < 3:
        action = "chat"  # 没有可靠编号就不执行下载，避免答非所问

    page_limit = args.get("page_limit")
    try:
        page_limit = None if page_limit in (None, "", "null") else max(1, min(200, int(page_limit)))
    except (TypeError, ValueError):
        page_limit = None

    delivery = "group" if str(args.get("delivery") or "").strip().lower() == "group" else "private"

    def short(value, limit=60):
        value = str(value or "").strip()
        return value[:limit]

    return {
        "action": action,
        "args": {
            "comic_id": comic_id,
            "page_limit": page_limit,
            "delivery": delivery,
            "keyword": short(args.get("keyword"), 60),
            "tag": short(args.get("tag"), 60),
            "pid": re.sub(r"\D", "", str(args.get("pid") or ""))[:12],
            "query": short(args.get("query"), 100),
            "word": short(args.get("word"), 60),
        },
        "reply": clean_reply(reply)[:400],
    }


class DeepSeekChat:
    def __init__(self):
        self._local = threading.local()

    def _session(self):
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            adapter = requests.adapters.HTTPAdapter(pool_connections=2, pool_maxsize=10, max_retries=0)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            self._local.session = session
        return session

    def chat_raw(self, messages, temperature=0.3):
        if requests is None:
            raise RuntimeError("缺少依赖 requests")
        api_key = env_value("DEEPSEEK_API_KEY", "")
        if not api_key:
            raise RuntimeError("未配置 DEEPSEEK_API_KEY")

        session = self._session()
        last_error = None
        for attempt in range(2):
            try:
                response = session.post(
                    f"{BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": MODEL,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": MAX_TOKENS,
                        "stream": False,
                    },
                    timeout=TIMEOUT,
                )
                response.raise_for_status()
                data = response.json()
                return str(data["choices"][0]["message"]["content"] or "").strip()
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                raise
        raise last_error or RuntimeError("DeepSeek 请求失败")

    def chat_intent(self, messages):
        raw = self.chat_raw(messages)
        return normalize_intent(parse_json_object(raw))


llm_chat = DeepSeekChat()


def _load_history():
    if not HISTORY_FILE.exists():
        return {}
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save_history(data):
    try:
        HISTORY_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def _prune(entries):
    cutoff = time.time() - HISTORY_TTL_SECONDS
    kept = []
    for item in entries or []:
        if not isinstance(item, dict):
            continue
        if float(item.get("ts") or 0) >= cutoff:
            kept.append(item)
    return kept[-HISTORY_MAX:] if HISTORY_MAX > 0 else []


def get_chat_history(key):
    with HISTORY_LOCK:
        data = _load_history()
        return _prune(data.get(key) or [])


def append_chat_history(key, user_text, assistant_text):
    if HISTORY_MAX <= 0:
        return
    now = time.time()
    with HISTORY_LOCK:
        data = _load_history()
        entries = _prune(data.get(key) or [])
        if user_text:
            entries.append({"role": "user", "content": str(user_text)[:800], "ts": now})
        if assistant_text:
            entries.append({"role": "assistant", "content": str(assistant_text)[:800], "ts": now})
        data[key] = entries[-HISTORY_MAX:]
        _save_history(data)


def clear_chat_history(key):
    with HISTORY_LOCK:
        data = _load_history()
        changed = key in data
        data.pop(key, None)
        if changed:
            _save_history(data)
        return changed


def _anti_repeat_message(history):
    """列出最近几条自己的回复，让模型避免句式/开头/用词重复。"""
    recent = [item.get("content") or "" for item in history if item.get("role") == "assistant"][-4:]
    recent = [clean_reply(item)[:40] for item in recent if item.strip()]
    if not recent:
        return None
    quoted = "；".join(f"「{item}」" for item in recent)
    return f"【避免重复】你最近的回复：{quoted}。这次回复不要和它们句式、开头或用词雷同，换种说法。"


def build_llm_messages(key, user_text):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    # 注入该会话的聊天偏好（token 梗频率、动作描写频率），由本地偏好库维护
    directive = llm_prefs.style_directive(key)
    if directive:
        messages.append({"role": "system", "content": f"【本会话的聊天偏好，必须严格遵守】{directive}"})
    history = get_chat_history(key)
    anti_repeat = _anti_repeat_message(history)
    if anti_repeat:
        messages.append({"role": "system", "content": anti_repeat})
    for item in history:
        messages.append({"role": item["role"], "content": item["content"]})
    messages.append({"role": "user", "content": str(user_text)[:800]})
    return messages


def compose_web_answer(key, user_text, results):
    """基于联网搜索结果组织回答（第二次 LLM 调用，输出强制为 chat）。"""
    context = "\n".join(
        f"[{index}] {item.get('title') or ''}\n{item.get('snippet') or ''}\n来源：{item.get('url') or ''}"
        for index, item in enumerate(results, start=1)
    )
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    directive = llm_prefs.style_directive(key)
    if directive:
        messages.append({"role": "system", "content": f"【本会话的聊天偏好，必须严格遵守】{directive}"})
    for item in get_chat_history(key):
        messages.append({"role": item["role"], "content": item["content"]})
    messages.append(
        {
            "role": "user",
            "content": (
                f"用户问：{user_text}\n\n"
                "你已联网搜索，结果如下。只基于这些结果回答，"
                "结果里没有的内容就说不知道，不要编造事实、日期或新闻。\n"
                f"{context}\n\n"
                '请只输出 JSON：{"action": "chat", "args": {}, "reply": "你的回答"}'
            ),
        }
    )
    intent = llm_chat.chat_intent(messages)
    return clean_reply(intent.get("reply"))


# 查词回答阶段的专用系统提示：不复用意图识别 SYSTEM_PROMPT，
# 避免模型把「组织解释」误判成「识别意图」又输出一遍确认语。
DICT_COMPOSE_SYSTEM = (
    PERSONA_CORE
    + "\n"
    "现在用户问了你一个词/术语的意思，词典释义和联网资料已经查好放在用户消息里。\n"
    "你的任务只有一件：结合资料，用小鱼口吻把这个词解释清楚。\n"
    "要求：\n"
    "1. 先讲字面意思；如果是网络流行语/圈内黑话/英文缩写，重点讲现在大家常说的用法和场景，可以举一个简短例子；\n"
    "2. 只基于给到的资料回答，资料里没有的就直接说不知道，不要编造；\n"
    "3. 回复 3-5 句以内，口语自然，不要使用任何 markdown 符号；\n"
    "4. 只输出一个 JSON 对象，不要输出任何其他文字：\n"
    '{"action": "chat", "args": {}, "reply": "你的口语化解释"}'
)


def compose_dict_answer(key, user_text, word, dict_results=None, web_results=None):
    """基于词典释义 + 联网资料组织「XX是什么意思」的回答（输出强制为 chat）。

    dict_results / web_results 可能为空列表，此时告知模型资料有限，不要编造。
    """
    parts = ["【词典释义】"]
    for item in dict_results or []:
        entry = str(item.get("entry") or "").strip()
        explain = str(item.get("explain") or "").strip()
        phonetic = str(item.get("phonetic") or "").strip()
        line = entry
        if phonetic:
            line += f"（{phonetic}）"
        line += f"：{explain}"
        parts.append(line)
    if not dict_results:
        parts.append("（词典没查到）")

    parts.append("")
    parts.append("【联网资料】")
    for index, item in enumerate(web_results or [], start=1):
        parts.append(f"[{index}] {item.get('title') or ''}\n{item.get('snippet') or ''}\n来源：{item.get('url') or ''}")
    if not web_results:
        parts.append("（联网也没搜到）")

    messages = [{"role": "system", "content": DICT_COMPOSE_SYSTEM}]
    directive = llm_prefs.style_directive(key)
    if directive:
        messages.append({"role": "system", "content": f"【本会话的聊天偏好，必须严格遵守】{directive}"})
    for item in get_chat_history(key):
        messages.append({"role": item["role"], "content": item["content"]})
    messages.append(
        {
            "role": "user",
            "content": (
                f"用户问：{user_text}\n"
                f"要解释的词：{word}\n\n"
                "以下是查到的资料：\n"
                f"{'\n'.join(parts)}\n\n"
                "请给出解释（只输出 JSON）。"
            ),
        }
    )
    intent = llm_chat.chat_intent(messages)
    return clean_reply(intent.get("reply"))
