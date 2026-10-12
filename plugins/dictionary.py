# -*- coding: utf-8 -*-
"""词语解释：查词典给出释义。

- 英文单词：优先 dictionaryapi.dev（免费公开词典 API，返回词性/释义/例句）；
- 中英文都能查：有道词典 suggest JSON 接口（无 Key、快、稳定）；
- 网络流行语 / 圈内黑话这种词典查不到完整意思的，由调用方再走联网搜索
  + AI 组织回答，本模块只负责把「词典释义」这层尽量查全；
- 全部失败返回空列表（调用方兜底，不影响聊天）。
"""
import re
import threading

try:
    import requests
except ImportError:
    requests = None


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
_local = threading.local()

_ENGLISH_ONLY = re.compile(r"^[A-Za-z][A-Za-z0-9' .\-]{1,40}$")


def _session():
    session = getattr(_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            }
        )
        _local.session = session
    return session


def _clean(text, limit=300):
    return re.sub(r"\s+", " ", (text or "").strip())[:limit]


def lookup_english(word, limit=2):
    """英文单词词典释义（dictionaryapi.dev）。返回 [{entry, phonetic, explain, source}]。"""
    if requests is None:
        return []
    try:
        response = _session().get(
            f"https://api.dictionaryapi.dev/api/v2/entries/en/{word.strip()}",
            timeout=10,
        )
        if response.status_code != 200:
            return []
        data = response.json()
    except Exception:
        return []

    if not isinstance(data, list):
        return []
    results = []
    for entry in data:
        entry_word = str(entry.get("word") or word).strip()
        phonetic = str(entry.get("phonetic") or "").strip()
        for meaning in entry.get("meanings") or []:
            pos = str(meaning.get("partOfSpeech") or "").strip()
            for definition in (meaning.get("definitions") or [])[:1]:
                text = str(definition.get("definition") or "").strip()
                if not text:
                    continue
                explain = f"{pos}. {text}" if pos else text
                example = str(definition.get("example") or "").strip()
                if example:
                    explain += f"（例：{_clean(example, 80)}）"
                results.append(
                    {
                        "entry": entry_word,
                        "phonetic": phonetic,
                        "explain": _clean(explain),
                        "source": "dictionaryapi",
                    }
                )
        if len(results) >= limit:
            break
    return results[:limit]


def lookup_youdao(word, limit=3):
    """有道词典词条（中英文都能查）。返回 [{entry, explain, source}]。"""
    if requests is None:
        return []
    word = (word or "").strip()
    if not word:
        return []
    language = "zh" if re.search(r"[\u4e00-\u9fff]", word) else "en"
    try:
        response = _session().get(
            "https://dict.youdao.com/suggest",
            params={
                "num": "8",
                "ver": "3.0",
                "doctype": "json",
                "cache": "false",
                "le": language,
                "q": word,
            },
            timeout=8,
        )
        if response.status_code != 200:
            return []
        data = response.json()
    except Exception:
        return []

    results = []
    lowered = word.lower()
    for entry in ((data.get("data") or {}).get("entries") or []):
        entry_word = str(entry.get("entry") or "").strip()
        explain = str(entry.get("explain") or "").strip()
        if not entry_word or not explain:
            continue
        # 只保留与查询词相关的词条（优先精确匹配）
        entry_lower = entry_word.lower()
        if entry_lower != lowered and not entry_lower.startswith(lowered):
            continue
        results.append({"entry": entry_word, "explain": _clean(explain), "source": "youdao"})
        if len(results) >= limit:
            break
    return results


def lookup_word(word, limit=3):
    """综合查词：英文走 dictionaryapi.dev（释义更全），中英文都补一条有道。

    返回去重后的 [{entry, phonetic?, explain, source}]；查不到返回空列表。
    """
    word = (word or "").strip()
    if not word:
        return []

    results = []
    if _ENGLISH_ONLY.match(word):
        results.extend(lookup_english(word, limit))
    results.extend(lookup_youdao(word, limit))

    seen = set()
    deduped = []
    for item in results:
        key = str(item.get("entry") or "").lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= limit:
            break
    return deduped
