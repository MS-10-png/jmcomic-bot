# -*- coding: utf-8 -*-
"""B站（哔哩哔哩）视频搜索。

实现方式：解析 https://search.bilibili.com/all 服务端渲染的搜索页（视频卡片 HTML）。
- 不需要登录 Cookie、不需要 B 站风控很高的 JSON 接口（api.bilibili.com 的搜索接口
  无 Cookie/TLS 指纹时会被「出错啦」风控页拦截，页面渲染路径更稳）；
- 任一环节失败静默返回空列表（由调用方兜底，不影响聊天）；
- 提供封面图下载，供 QQ 里发预览图用。
"""
import re
import threading
import time
from pathlib import Path
from urllib.parse import urljoin

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
SEARCH_URL = "https://search.bilibili.com/all"
BVID_PATTERN = re.compile(r"BV[0-9A-Za-z]{10}")
_local = threading.local()


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


def _clean(text, limit=200):
    return re.sub(r"\s+", " ", (text or "").strip())[:limit]


def search_video(keyword, limit=5):
    """搜索 B 站视频。

    返回列表，每项：
        {title, url, bvid, author, play, danmaku, duration, date, cover}
    title 为干净标题（去掉搜索词高亮标签）；play/danmaku 为「474.7万」这类展示文本；
    cover 为封面图完整 URL（可能为空）。
    """
    keyword = (keyword or "").strip()
    if not keyword or requests is None or BeautifulSoup is None:
        return []

    try:
        response = _session().get(
            SEARCH_URL,
            params={"keyword": keyword},
            timeout=12,
        )
        if response.status_code != 200:
            return []
        soup = BeautifulSoup(response.text, "html.parser")
    except Exception:
        return []

    results = []
    for card in soup.select(".bili-video-card"):
        item = _parse_card(card)
        if item:
            results.append(item)
        if len(results) >= limit:
            break
    return results


def _parse_card(card):
    """从一张视频卡片 HTML 里提取结构化信息；解析不出返回 None。"""
    anchor = card.select_one(".bili-video-card__wrap a[href]")
    if anchor is None:
        return None
    href = (anchor.get("href") or "").strip()
    if "video/BV" not in href:
        return None
    url = urljoin("https://www.bilibili.com", href)
    match = BVID_PATTERN.search(url)
    bvid = match.group(0) if match else ""
    if bvid:
        # 去掉 trackid/track_id/caid 等追踪参数，只留干净的视频页链接
        url = f"https://www.bilibili.com/video/{bvid}/"

    title_el = card.select_one(".bili-video-card__info--tit")
    title = ""
    if title_el is not None:
        title = (title_el.get("title") or "").strip() or _clean(title_el.get_text(" ", strip=True), 120)
    if not title:
        return None

    owner_el = card.select_one(".bili-video-card__info--owner")
    author = _clean(owner_el.get_text(" ", strip=True), 60) if owner_el is not None else ""
    date_el = card.select_one(".bili-video-card__info--date")
    date = _clean(date_el.get_text(" ", strip=True), 24) if date_el is not None else ""
    date = date.lstrip("·").strip()
    if author and date and author.endswith(date):
        author = author[: -len(date)].rstrip("· ").strip()

    duration_el = card.select_one(".bili-video-card__stats__duration")
    duration = _clean(duration_el.get_text(" ", strip=True), 24) if duration_el is not None else ""
    if not duration:
        # 直播/系列课程等卡片没有时长，用卡片文本里的标识兜底
        card_text = card.get_text(" ", strip=True)
        marker = re.search(r"(直播中|共\d{1,3}课时|已更\d{1,3}课时|连载中|全\d{1,3}话)", card_text)
        if marker:
            duration = marker.group(1)
        else:
            duration_match = re.search(r"\b(\d{1,3}:\d{2})\b", card_text)
            duration = duration_match.group(1) if duration_match else ""
    stats = [it.get_text(" ", strip=True) for it in card.select(".bili-video-card__stats--item")]
    play = _clean(stats[0], 24) if stats else ""
    danmaku = _clean(stats[1], 24) if len(stats) > 1 else ""

    img = card.select_one("img")
    cover = urljoin("https://www.bilibili.com", (img.get("src") or "")) if img is not None and img.get("src") else ""

    return {
        "title": title[:80],
        "url": url,
        "bvid": bvid,
        "author": author[:40],
        "play": play,
        "danmaku": danmaku,
        "duration": duration,
        "date": date[:24],
        "cover": cover,
    }


def format_video_list(videos):
    """把搜索结果格式化成 QQ 文本卡片。"""
    videos = videos or []
    if not videos:
        return "😣 小鱼在B站没找到相关视频…"
    lines = ["🎬 B站搜索结果，给你参考："]
    for index, video in enumerate(videos, start=1):
        title = video.get("title") or "无标题"
        author = video.get("author") or "未知UP主"
        play = video.get("play") or "?"
        duration = video.get("duration") or "?"
        lines.append(f"{index}. {title}\n　👤 {author} ｜ ▶ {play} ｜ ⏱ {duration}\n　🔗 {video.get('url') or ''}")
    return "\n".join(lines)


def download_cover(video, cache_dir):
    """下载视频封面到本地，返回文件路径；失败返回 None。"""
    cover = (video or {}).get("cover") or ""
    if not cover or requests is None:
        return None
    try:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        filename = "bili_" + (re.sub(r"\W", "", video.get("bvid") or "") or str(int(time.time()))) + ".jpg"
        path = cache_dir / filename
        if path.exists() and path.stat().st_size > 0:
            return path
        response = _session().get(cover, timeout=15)
        if response.status_code != 200:
            return None
        path.write_bytes(response.content)
        return path
    except Exception:
        return None
