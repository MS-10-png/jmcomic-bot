# -*- coding: utf-8 -*-
"""联网搜索：Bing → DuckDuckGo → Baidu 依次尝试，取第一个有结果的引擎。

任何引擎失败都静默切换到下一个；全部失败返回空列表（由调用方兜底，不影响聊天）。
Baidu 页面结构多变，解析用通用规则：从结果块里提取 标题链接 + 就近文本摘要。
"""
import re
import threading
from urllib.parse import unquote, urlsplit

try:
    import requests
except ImportError:
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
_local = threading.local()

_SKIP_TITLES = ("下一页", "上一页", "百度首页", "登录", "注册", "更多", "相关搜索")


def _session():
    session = getattr(_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            }
        )
        _local.session = session
    return session


def _clean(text, limit=300):
    return re.sub(r"\s+", " ", (text or "").strip())[:limit]


def _ddg_url(href):
    if "uddg=" in href:
        try:
            return unquote(href.split("uddg=", 1)[1].split("&", 1)[0])
        except Exception:
            return href
    return href


def search_duckduckgo(query, limit=5):
    if requests is None or BeautifulSoup is None:
        return []
    response = _session().post(
        "https://html.duckduckgo.com/html/",
        data={"q": query},
        timeout=6,
    )
    if response.status_code != 200:
        return []
    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    for anchor in soup.select("a.result__a"):
        title = _clean(anchor.get_text(), 120)
        url = _ddg_url(anchor.get("href") or "")
        if not title or not url:
            continue
        snippet_el = anchor.find_next(class_="result__snippet")
        snippet = _clean(snippet_el.get_text()) if snippet_el else ""
        results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= limit:
            break
    return results


def _parse_baidu_html(html, limit=5):
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text(" ", strip=True)
    if any(kw in page_text for kw in ("百度安全验证", "安全验证", "网络不给力", "页面出错了")):
        return []

    results = []
    seen = set()
    blocks = soup.select("div.result, div.c-container, div.result-op, article")
    if not blocks:
        blocks = [soup]

    for block in blocks:
        anchor = None
        for tag in block.find_all("a"):
            href = tag.get("href") or ""
            title = _clean(tag.get_text(), 120)
            if len(title) >= 8 and ("http" in href or href.startswith("//")):
                anchor = tag
                break
        if anchor is None:
            continue

        title = _clean(anchor.get_text(), 120)
        if not title or title in _SKIP_TITLES:
            continue
        href = anchor.get("href") or ""
        if href.startswith("//"):
            url = "https:" + href
        elif href.startswith("http"):
            url = href
        else:
            continue
        if urlsplit(url).netloc.endswith("baidu.com") and "/s?" in url:
            continue

        key = (title, url)
        if key in seen:
            continue
        seen.add(key)

        block_text = _clean(block.get_text(" ", strip=True), 600)
        snippet = block_text[len(title):] if block_text.startswith(title) else block_text
        snippet = _clean(snippet, 200)
        results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= limit:
            break
    return results


def search_bing(query, limit=5):
    if requests is None or BeautifulSoup is None:
        return []
    response = _session().get(
        "https://cn.bing.com/search",
        params={"q": query},
        timeout=10,
    )
    if response.status_code != 200:
        return []
    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    for item in soup.select("li.b_algo"):
        anchor = item.select_one("h2 a")
        if anchor is None:
            continue
        title = _clean(anchor.get_text(), 120)
        url = anchor.get("href") or ""
        if not title or not url.startswith("http"):
            continue
        snippet_el = item.select_one("p")
        snippet = _clean(snippet_el.get_text()) if snippet_el else ""
        results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= limit:
            break
    return results


def search_baidu(query, limit=5):
    if requests is None or BeautifulSoup is None:
        return []
    for endpoint, params in (
        ("https://www.baidu.com/s", {"wd": query, "rn": 10}),
        ("https://m.baidu.com/s", {"word": query}),
    ):
        try:
            response = _session().get(endpoint, params=params, timeout=10)
            if response.status_code != 200:
                continue
            results = _parse_baidu_html(response.text, limit)
            if results:
                return results
        except Exception:
            continue
    return []


def search_web(query, limit=5):
    """搜索网页；依次尝试 Bing → DuckDuckGo → Baidu，取第一个有结果的引擎。"""
    query = (query or "").strip()
    if not query:
        return []
    for engine in (search_bing, search_duckduckgo, search_baidu):
        try:
            results = engine(query, limit)
        except Exception:
            results = []
        if results:
            return results
    return []
