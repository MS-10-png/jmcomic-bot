import os
import random
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

import requests


class PixivLoginRequiredError(Exception):
    pass


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


class PixivAPI:
    def __init__(self):
        self.ranking_url = "https://www.pixiv.net/ranking.php"
        self.safe_mode = True
        self.random_ranking_modes = self.load_random_ranking_modes()
        self.random_ranking_pages = self.load_random_ranking_pages()
        self.headers = {
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.pixiv.net/ranking.php?mode=daily&content=illust",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                + env_value("PIXIV_USER_AGENT", "Chrome/130.0.0.0 Safari/537.36")
            ),
        }
        cookie = self.load_cookie_header()
        if cookie:
            self.headers["Cookie"] = cookie
        self.image_headers = {
            **self.headers,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": "https://www.pixiv.net/",
        }
        # 线程级 Session：复用 TCP/TLS 连接，降低连续请求延迟
        self._local = threading.local()

    def _session(self):
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=2, pool_maxsize=10, max_retries=0
            )
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            self._local.session = session
        return session

    def _request_get(self, url, **kwargs):
        """GET 请求，瞬时网络错误自动重试一次。"""
        session = self._session()
        last_error = None
        for attempt in range(2):
            try:
                response = session.get(url, **kwargs)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(0.4)
                    continue
                raise
        raise last_error

    def load_cookie_header(self):
        cookie = env_value("PIXIV_COOKIE", "").strip()
        if cookie:
            return cookie

        phpsessid = env_value("PIXIV_PHPSESSID", "").strip()
        if phpsessid:
            if phpsessid.lower().startswith("phpsessid="):
                return phpsessid
            return "PHPSESSID=" + phpsessid
        return ""

    def has_auth_cookie(self):
        return bool(self.headers.get("Cookie"))

    def check_login(self):
        """检测当前配置的 Cookie 是否有效。返回 (是否已登录, 说明)。"""
        if not self.has_auth_cookie():
            return False, "未配置 Cookie（.env 里的 PIXIV_COOKIE 或 PIXIV_PHPSESSID 为空）"

        try:
            response = self._request_get(
                "https://www.pixiv.net/ajax/user/self",
                headers={**self.headers, "Referer": "https://www.pixiv.net/"},
                timeout=15,
            )
            data = response.json()
        except Exception as exc:
            return False, f"验证失败（网络异常）：{exc}"

        if data.get("error"):
            return False, f"Cookie 无效：{data.get('message') or data.get('error')}"

        body = data.get("body") or {}
        name = body.get("userName") or body.get("pixivId") or body.get("userId") or ""
        if name:
            return True, f"已登录：{name}"
        return False, "Cookie 无效（可能已过期），请重新提取 PHPSESSID"

    def load_random_ranking_modes(self):
        raw = env_value(
            "PIXIV_RANDOM_RANKING_MODES",
            "daily,weekly,monthly,rookie,original,male,female",
        )
        modes = []
        for item in raw.split(","):
            mode = item.strip().lower()
            normalized = mode.replace("-", "").replace("_", "")
            if not mode or "r18" in normalized:
                continue
            if mode not in modes:
                modes.append(mode)
        return modes or ["daily", "weekly", "monthly"]

    def load_random_ranking_pages(self):
        try:
            pages = int(env_value("PIXIV_RANDOM_RANKING_PAGES", "3"))
        except ValueError:
            pages = 3
        return max(1, min(10, pages))

    def normalize_tags(self, value):
        if not value:
            return []
        if isinstance(value, list):
            return [str(tag).strip() for tag in value if str(tag).strip()]
        return [tag.strip() for tag in str(value).split(",") if tag.strip()]

    def is_age_restricted_artwork(self, artwork):
        tags = {tag.lower().replace(" ", "") for tag in artwork.get("tags") or []}
        blocked = {"r-18", "r18", "r-18g", "r18g"}
        if tags & blocked:
            return True

        try:
            return int(artwork.get("x_restrict") or 0) > 0
        except (TypeError, ValueError):
            return False

    def is_safe_artwork(self, artwork, allow_restricted=False):
        if allow_restricted:
            return True
        if not self.safe_mode:
            return True

        return not self.is_age_restricted_artwork(artwork)

    def parse_artwork(self, item, allow_restricted=False):
        artwork_id = str(item.get("illust_id") or item.get("id") or "").strip()
        image_url = item.get("url") or item.get("illust_url") or item.get("image")
        title = item.get("title") or item.get("illust_title") or "未命名"
        user_name = item.get("user_name") or item.get("author") or item.get("user") or "未知作者"
        tags = self.normalize_tags(item.get("tags"))

        if not artwork_id or not image_url:
            return None

        artwork = {
            "id": artwork_id,
            "title": title,
            "user_name": user_name,
            "tags": tags,
            "x_restrict": item.get("x_restrict") or item.get("xRestrict") or item.get("restrict"),
            "image_url": image_url,
            "page_url": f"https://www.pixiv.net/artworks/{artwork_id}",
        }
        artwork["age_restricted"] = self.is_age_restricted_artwork(artwork)
        return artwork if self.is_safe_artwork(artwork, allow_restricted=allow_restricted) else None

    def parse_search_artwork(self, item, fallback_tag="", allow_restricted=False):
        artwork_id = str(item.get("id") or item.get("illustId") or item.get("illust_id") or "").strip()
        image_url = (
            item.get("url")
            or item.get("illust_url")
            or item.get("image")
            or (item.get("urls") or {}).get("250x250")
            or (item.get("urls") or {}).get("360x360")
            or (item.get("urls") or {}).get("540x540")
        )
        title = item.get("title") or item.get("illustTitle") or item.get("illust_title") or "未命名"
        user_name = item.get("userName") or item.get("user_name") or item.get("author") or "未知作者"
        tags = self.normalize_tags(item.get("tags") or item.get("tag"))
        if fallback_tag and fallback_tag not in tags:
            tags.append(fallback_tag)

        if not artwork_id or not image_url:
            return None

        artwork = {
            "id": artwork_id,
            "title": title,
            "user_name": user_name,
            "tags": tags,
            "x_restrict": item.get("x_restrict") or item.get("xRestrict") or item.get("restrict"),
            "image_url": image_url,
            "page_url": f"https://www.pixiv.net/artworks/{artwork_id}",
        }
        artwork["age_restricted"] = self.is_age_restricted_artwork(artwork)
        return artwork if self.is_safe_artwork(artwork, allow_restricted=allow_restricted) else None

    def parse_detail_artwork(self, body, allow_restricted=False):
        artwork_id = str(body.get("illustId") or body.get("id") or "").strip()
        urls = body.get("urls") or {}
        image_url = (
            urls.get("regular")
            or urls.get("small")
            or urls.get("thumb")
            or urls.get("mini")
            or urls.get("original")
        )
        title = body.get("illustTitle") or body.get("title") or "未命名"
        user_name = body.get("userName") or body.get("user_name") or "未知作者"

        tags = []
        tag_body = body.get("tags") or {}
        for item in tag_body.get("tags") or []:
            tag = item.get("tag") if isinstance(item, dict) else item
            if tag:
                tags.append(str(tag).strip())

        if not artwork_id:
            return None

        artwork = {
            "id": artwork_id,
            "title": title,
            "user_name": user_name,
            "tags": self.normalize_tags(tags),
            "x_restrict": body.get("x_restrict") or body.get("xRestrict") or body.get("restrict"),
            "image_url": image_url or "",
            "missing_image_url": not bool(image_url),
            "page_url": f"https://www.pixiv.net/artworks/{artwork_id}",
        }
        artwork["age_restricted"] = self.is_age_restricted_artwork(artwork)
        return artwork if self.is_safe_artwork(artwork, allow_restricted=allow_restricted) else None

    def fetch_ranking(self, mode="daily", content="illust", limit=20, page=1, allow_restricted=False):
        mode = (mode or "daily").strip().lower()
        content = (content or "illust").strip()
        response = self._request_get(
            self.ranking_url,
            params={
                "mode": mode,
                "content": content,
                "format": "json",
                "p": page,
            },
            headers={
                **self.headers,
                "Referer": f"https://www.pixiv.net/ranking.php?mode={mode}&content={content}",
            },
            timeout=20,
        )
        data = response.json()
        raw_items = data.get("contents") or data.get("items") or []

        artworks = []
        for item in raw_items:
            artwork = self.parse_artwork(item, allow_restricted=allow_restricted)
            if artwork:
                artworks.append(artwork)
            if len(artworks) >= limit:
                break
        return artworks

    def fetch_daily_ranking(self, limit=20, page=1):
        return self.fetch_ranking(mode="daily", content="illust", limit=limit, page=page)

    def fetch_artwork_by_pid(self, pid, allow_restricted=False):
        pid = str(pid).strip()
        if not pid.isdigit():
            raise ValueError("PID 必须是数字")

        response = self._request_get(
            f"https://www.pixiv.net/ajax/illust/{pid}",
            params={"lang": "zh"},
            headers={
                **self.headers,
                "Referer": f"https://www.pixiv.net/artworks/{pid}",
            },
            timeout=20,
        )
        data = response.json()
        if data.get("error"):
            raise Exception(data.get("message") or "Pixiv 返回错误")

        artwork = self.parse_detail_artwork(data.get("body") or {}, allow_restricted=allow_restricted)
        if artwork is None:
            raise Exception("作品不存在、被限制，或没有可发送的安全预览图")
        if artwork.get("missing_image_url"):
            if artwork.get("age_restricted") and not self.has_auth_cookie():
                raise PixivLoginRequiredError(
                    "该作品是 R18/R18G，Pixiv 未登录状态不会返回图片地址。"
                    "请在 .env 配置 PIXIV_COOKIE 或 PIXIV_PHPSESSID 后重启机器人。"
                )
            raise Exception("Pixiv 没有返回该作品的图片地址，可能是作品被限制或需要登录。")
        return artwork

    def daily_recommendations(self, count=5):
        candidates = []
        for page in range(1, 4):
            if len(candidates) >= count:
                break
            try:
                candidates.extend(self.fetch_daily_ranking(limit=count * 2, page=page))
            except Exception:
                if candidates:
                    break
                raise

        unique = {}
        for artwork in candidates:
            unique.setdefault(artwork["id"], artwork)
        return list(unique.values())[:count]

    def random_pool(self, limit=80):
        unique = {}
        modes = list(self.random_ranking_modes)
        random.SystemRandom().shuffle(modes)
        target_size = max(limit * 4, len(modes) * 50, limit)
        first_error = None

        for page in range(1, self.random_ranking_pages + 1):
            for mode in modes:
                if len(unique) >= target_size:
                    break
                try:
                    artworks = self.fetch_ranking(mode=mode, content="illust", limit=50, page=page)
                except Exception as exc:
                    if first_error is None:
                        first_error = exc
                    if unique:
                        break
                    continue
                for artwork in artworks:
                    unique.setdefault(artwork["id"], artwork)
            if len(unique) >= target_size:
                break

        if not unique and first_error:
            raise first_error

        items = list(unique.values())
        random.SystemRandom().shuffle(items)
        return items[:limit]

    def tag_search_mode(self, tag, allow_restricted=False):
        if not allow_restricted:
            return "safe"
        normalized = (tag or "").lower().replace("-", "").replace("_", "").replace(" ", "")
        if "r18g" in normalized:
            return "r18g"
        if "r18" in normalized:
            return "r18"
        return "all"

    def search_by_tag(self, tag, limit=20, page=1, allow_restricted=False):
        tag = tag.strip()
        if not tag:
            return []

        response = self._request_get(
            f"https://www.pixiv.net/ajax/search/artworks/{quote(tag)}",
            params={
                "word": tag,
                "order": "date_d",
                "mode": self.tag_search_mode(tag, allow_restricted=allow_restricted),
                "p": page,
                "s_mode": "s_tag",
                "type": "illust_and_ugoira",
                "lang": "zh",
            },
            headers={
                **self.headers,
                "Referer": f"https://www.pixiv.net/tags/{quote(tag)}/artworks",
            },
            timeout=20,
        )
        data = response.json()
        body = data.get("body") or {}
        illust_manga = body.get("illustManga") or {}
        raw_items = illust_manga.get("data") or body.get("data") or []

        artworks = []
        for item in raw_items:
            artwork = self.parse_search_artwork(item, fallback_tag=tag, allow_restricted=allow_restricted)
            if artwork:
                artworks.append(artwork)
            if len(artworks) >= limit:
                break
        return artworks

    def tag_pool(self, tag, limit=80, allow_restricted=False):
        candidates = []
        page = 1
        while len(candidates) < limit and page <= 5:
            try:
                candidates.extend(self.search_by_tag(tag, limit=50, page=page, allow_restricted=allow_restricted))
            except Exception:
                if candidates:
                    break
                raise
            page += 1

        unique = {}
        for artwork in candidates:
            unique.setdefault(artwork["id"], artwork)

        items = list(unique.values())
        random.SystemRandom().shuffle(items)
        return items[:limit]

    def download_preview(self, artwork, cache_dir):
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)

        image_url = artwork.get("image_url")
        if not image_url:
            raise Exception("Pixiv 没有返回图片地址，无法下载预览图。")

        path = Path(urlsplit(image_url).path)
        suffix = path.suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            suffix = ".jpg"

        target_path = cache_dir / f"{artwork['id']}{suffix}"
        if target_path.exists() and target_path.stat().st_size > 0:
            return target_path

        response = self._request_get(image_url, headers=self.image_headers, timeout=20)
        if not response.content:
            raise Exception("Pixiv 图片响应为空")

        target_path.write_bytes(response.content)
        target_path.with_suffix(target_path.suffix + ".meta").write_text(
            f"source={artwork['page_url']}\ndownloaded_at={time.time()}\n",
            encoding="utf-8",
        )
        return target_path


pixiv_api = PixivAPI()
