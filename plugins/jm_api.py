import hashlib
import base64
import json
import os
import random
import threading
import time
from pathlib import Path
from urllib.parse import quote_plus, urlsplit

try:
    import requests
except ImportError as exc:
    requests = None
    REQUESTS_IMPORT_ERROR = exc
else:
    REQUESTS_IMPORT_ERROR = None

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
except ImportError as exc:
    AES = None
    CRYPTO_IMPORT_ERROR = exc
else:
    CRYPTO_IMPORT_ERROR = None

try:
    from PIL import Image
except ImportError as exc:
    Image = None
    PIL_IMPORT_ERROR = exc
else:
    PIL_IMPORT_ERROR = None


class MissingDependencyError(RuntimeError):
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


def env_csv(name, default_items):
    raw = env_value(name, "")
    if not raw:
        return list(default_items)
    items = []
    for item in raw.split(","):
        item = item.strip().strip("/")
        if item.startswith("https://"):
            item = urlsplit(item).netloc
        if item and item not in items:
            items.append(item)
    return items or list(default_items)


class JMAPI:
    def __init__(self):
        self.name = "禁漫天堂"
        self.key = "jm"
        self.version = env_value("JM_APP_VERSION", "1.4.0")
        self.jm_version = env_value("JM_WEB_VERSION", "2.0.16")
        self.jm_pkg_name = env_value("JM_PACKAGE_NAME", "com.example.app")
        self.fallback_servers = [
            "www.cdntwice.org",
            "www.cdnsha.org",
            "www.cdnaspa.cc",
            "www.cdnntr.cc",
        ]
        self.domain_config_url = env_value(
            "JM_DOMAIN_CONFIG_URL",
            "https://rup4a04-c02.tos-cn-hongkong.bytepluses.com/newsvr-2025.txt",
        )
        self.domain_secret = env_value("JM_DOMAIN_CONFIG_SECRET", "diosfjckwpqpdfjkvnqQjsik")
        self.image_url = env_value("JM_IMAGE_HOST", "https://cdn-msp.jmapinodeudzn.net").rstrip("/")
        self.ua = "Mozilla/5.0 (Linux; Android 10; K; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/130.0.0.0 Mobile Safari/537.36"
        self.api_domains = env_csv("JM_API_DOMAINS", self.fallback_servers)
        self.api_domain_index = 0
        self.domain_refresh_attempted = False
        # 线程级 Session：复用 TCP/TLS 连接，避免每张图片都重新握手
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
    
    @property
    def base_url(self):
        return f"https://{self.api_domains[self.api_domain_index]}"
    
    @property
    def base_headers(self):
        return {
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive",
            "Origin": "https://localhost",
            "Referer": "https://localhost/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site",
            "X-Requested-With": self.jm_pkg_name,
        }
    
    def get_api_headers(self, time_val):
        jm_auth_key = "18comicAPPContent"
        token = self.md5(f"{time_val}{jm_auth_key}")
        
        return {
            **self.base_headers,
            "Authorization": "Bearer",
            "Sec-Fetch-Storage-Access": "active",
            "token": token,
            "tokenparam": f"{time_val},{self.jm_version}",
            "User-Agent": self.ua,
        }
    
    def get_img_headers(self):
        return {
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive",
            "Referer": "https://localhost/",
            "Sec-Fetch-Dest": "image",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Storage-Access": "active",
            "User-Agent": self.ua,
            "X-Requested-With": self.jm_pkg_name,
        }
    
    def get_cover_url(self, id):
        return f"{self.image_url}/media/albums/{id}_3x4.jpg"
    
    def get_image_url(self, id, image_name):
        return f"{self.image_url}/media/photos/{id}/{image_name}"
    
    def md5(self, text):
        return hashlib.md5(text.encode('utf-8')).hexdigest()

    def ensure_requests(self):
        if requests is None:
            raise MissingDependencyError(
                "缺少依赖 requests，请先执行：pip install -r requirements.txt"
            ) from REQUESTS_IMPORT_ERROR

    def ensure_pillow(self):
        if Image is None:
            raise MissingDependencyError(
                "缺少依赖 pillow，无法还原 JM 图片，请先执行：pip install -r requirements.txt"
            ) from PIL_IMPORT_ERROR
    
    def convert_data(self, input_data, secret):
        # 上游服务器可能用错误编码返回带 UTF-8 BOM 的响应（如 ISO-8859-1 解码成 ï»¿），
        # 这里统一按字节处理，避免 BOM 导致 base64 解码失败
        if isinstance(input_data, bytes):
            if input_data.startswith(b"\xef\xbb\xbf"):
                input_data = input_data[3:]
            input_data = input_data.decode("utf-8", errors="ignore")

        stripped = input_data.lstrip("\ufeff").strip()
        if stripped.startswith(("{", "[")):
            return stripped

        if AES is None:
            raise MissingDependencyError(
                "缺少依赖 pycryptodome，无法解密 JM API 响应，请先执行：pip install -r requirements.txt"
            ) from CRYPTO_IMPORT_ERROR

        key = self.md5(secret).encode("utf-8")
        encrypted = base64.b64decode(input_data)
        decrypted = AES.new(key, AES.MODE_ECB).decrypt(encrypted)
        try:
            decrypted = unpad(decrypted, AES.block_size)
        except ValueError:
            pass

        text = decrypted.decode("utf-8", errors="ignore")
        start = 0
        while start < len(text) and text[start] not in "{[":
            start += 1
        end = len(text) - 1
        while end > start and text[end] not in "}]":
            end -= 1
        if start >= len(text) or end <= start:
            raise ValueError("JM API 解密后未找到有效 JSON")
        return text[start:end + 1]

    def build_api_url(self, endpoint, domain):
        if endpoint.startswith(("http://", "https://")):
            parsed = urlsplit(endpoint)
            return f"{parsed.scheme}://{domain}{parsed.path}" + (f"?{parsed.query}" if parsed.query else "")
        if not endpoint.startswith("/"):
            endpoint = f"/{endpoint}"
        return f"https://{domain}{endpoint}"

    def request_api(self, method, endpoint, body=None):
        self.ensure_requests()
        time_val = int(time.time())
        k_jm_secret = "185Hcomic3PAPP7R"
        headers = {
            **self.get_api_headers(time_val),
        }
        if method == "POST":
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        session = self._session()
        last_error = None
        start_index = self.api_domain_index
        for offset in range(len(self.api_domains)):
            index = (start_index + offset) % len(self.api_domains)
            self.api_domain_index = index
            url = self.build_api_url(endpoint, self.api_domains[index])

            # 同一域名上瞬时网络错误重试一次，再换下一个域名
            for attempt in range(2):
                try:
                    if method == "GET":
                        response = session.get(url, headers=headers, timeout=15)
                    else:
                        response = session.post(url, headers=headers, data=body, timeout=15)

                    if response.status_code != 200:
                        if response.status_code == 401:
                            try:
                                json_data = response.json()
                                message = json_data.get('errorMsg')
                            except ValueError:
                                message = None
                            raise Exception(message or f'Invalid Status Code: {response.status_code}')
                        raise Exception(f'Invalid Status Code: {response.status_code}')

                    json_data = response.json()
                    data = json_data.get('data')
                    if not isinstance(data, str):
                        raise Exception('Invalid Data')

                    return self.convert_data(data, f"{time_val}{k_jm_secret}")
                except requests.RequestException as exc:
                    last_error = exc
                    if attempt == 0:
                        time.sleep(0.4)
                        continue
                except Exception as e:
                    last_error = e
                    break

        if not self.domain_refresh_attempted:
            self.domain_refresh_attempted = True
            try:
                self.refresh_api_domains()
                return self.request_api(method, endpoint, body)
            except Exception as e:
                last_error = e

        raise last_error or Exception("JM API 请求失败")

    def get(self, endpoint):
        return self.request_api("GET", endpoint)

    def post(self, endpoint, body):
        return self.request_api("POST", endpoint, body)

    def download_image(self, url, target_path):
        self.ensure_requests()
        target_path = Path(target_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        session = self._session()
        last_error = None
        for attempt in range(2):
            try:
                response = session.get(url, headers=self.get_img_headers(), timeout=20)
            except requests.RequestException as exc:
                last_error = Exception(f"图片下载失败: {exc}")
                if attempt == 0:
                    time.sleep(0.4)
                    continue
                break

            if response.status_code != 200:
                last_error = Exception(f"图片下载失败: HTTP {response.status_code}")
                retry_url = self.retry_image_url(url)
                if retry_url and retry_url != url and attempt == 0:
                    url = retry_url
                    continue
                break

            if not response.content:
                last_error = Exception("图片下载失败: 响应内容为空")
                if attempt == 0:
                    time.sleep(0.4)
                    continue
                break

            target_path.write_bytes(response.content)
            self.ensure_image_decoded(url, target_path)
            return target_path

        raise last_error or Exception("图片下载失败")

    def retry_image_url(self, url):
        old_host = self.image_url
        new_host = self.refresh_img_url()
        if not new_host or new_host == old_host:
            return ""
        parsed = urlsplit(url)
        return new_host.rstrip("/") + parsed.path

    def decode_marker_path(self, image_path):
        image_path = Path(image_path)
        return image_path.with_name(f"{image_path.name}.jmdecoded")

    def get_scramble_num(self, chapter_id, image_url):
        scramble_id = 220980
        try:
            ep_id = int(chapter_id)
        except (TypeError, ValueError):
            return 0

        if ep_id < scramble_id:
            return 0
        if ep_id < 268850:
            return 10

        basename = Path(urlsplit(image_url).path).name
        if not basename:
            return 0

        lower_name = basename.lower()
        if lower_name.endswith((".webp", ".jpeg")):
            picture_name = basename[:-5]
        elif "." in basename:
            picture_name = basename.rsplit(".", 1)[0]
        else:
            picture_name = basename

        hash_str = self.md5(f"{ep_id}{picture_name}")
        remainder_base = 8 if ep_id > 421926 else 10
        remainder = ord(hash_str[-1]) % remainder_base
        return remainder * 2 + 2

    def get_chapter_id_from_image_url(self, image_url):
        parts = [part for part in urlsplit(image_url).path.split("/") if part]
        try:
            photos_index = parts.index("photos")
            return parts[photos_index + 1]
        except (ValueError, IndexError):
            return None

    def ensure_image_decoded(self, image_url, image_path):
        image_path = Path(image_path)
        marker_path = self.decode_marker_path(image_path)
        if marker_path.exists():
            return image_path

        if image_path.suffix.lower() == ".gif":
            marker_path.write_text("gif-skip", encoding="utf-8")
            return image_path

        chapter_id = self.get_chapter_id_from_image_url(image_url)
        num = self.get_scramble_num(chapter_id, image_url)
        if num <= 1:
            marker_path.write_text("no-scramble", encoding="utf-8")
            return image_path

        self.ensure_pillow()

        with Image.open(image_path) as image:
            image.load()
            width, height = image.size
            block_size = height // num
            remainder = height % num
            blocks = []
            for i in range(num):
                start = i * block_size
                end = start + block_size + (0 if i != num - 1 else remainder)
                blocks.append((start, end))

            restored = Image.new(image.mode, image.size)
            y = 0
            for start, end in reversed(blocks):
                block = image.crop((0, start, width, end))
                restored.paste(block, (0, y))
                y += end - start

            save_kwargs = {}
            suffix = image_path.suffix.lower()
            if suffix in {".jpg", ".jpeg"}:
                if restored.mode not in {"RGB", "L"}:
                    restored = restored.convert("RGB")
                save_kwargs = {"quality": 95, "optimize": True}
            elif suffix == ".webp":
                save_kwargs = {"quality": 95}

            restored.save(image_path, **save_kwargs)

        marker_path.write_text(f"decoded:{num}", encoding="utf-8")
        return image_path
    
    def refresh_api_domains(self, show_confirm_dialog=False):
        env_domains = env_csv("JM_API_DOMAINS", [])
        if env_domains:
            self.api_domains = env_domains
            self.api_domain_index = 0
            return env_domains

        url = self.domain_config_url
        domain_secret = self.domain_secret
        servers = []
        domains = []
        
        try:
            self.ensure_requests()
            response = self._session().get(url, headers=self.base_headers, timeout=10)
            if response.status_code == 200:
                data = self.convert_data(response.content, domain_secret)
                json_data = json.loads(data)
                if "Server" in json_data:
                    servers = json_data["Server"][:4]
        except:
            pass
        
        if not servers:
            servers = self.fallback_servers
        
        for server in servers:
            domains.append(server)
        
        self.api_domains = domains
        self.api_domain_index = 0
        return domains
    
    def refresh_img_url(self, show_message=False):
        env_host = env_value("JM_IMAGE_HOST", "")
        if env_host:
            self.image_url = env_host.rstrip("/")
            return self.image_url

        image_stream = 1  # 默认使用第一个图片分流
        try:
            response = self.get(f"/setting?app_img_shunt={image_stream}&express=")
            setting = json.loads(response)
            if "img_host" in setting:
                self.image_url = str(setting["img_host"]).rstrip("/")
                return self.image_url
        except:
            pass
        return self.image_url
    
    def parse_comic(self, comic):
        id = str(comic.get('id', ''))
        author = comic.get('author', '')
        title = comic.get('name', '')
        description = comic.get('description', '')
        cover = self.get_cover_url(id)
        tags = []

        category = comic.get('category') or {}
        category_sub = comic.get('category_sub') or {}
        if category.get('title') and category['title'] not in tags:
            tags.append(category['title'])
        if category_sub.get('title') and category_sub['title'] not in tags:
            tags.append(category_sub['title'])
        
        return {
            'id': id,
            'title': title,
            'subTitle': author,
            'cover': cover,
            'tags': tags,
            'description': description
        }
    
    def load_comic_info(self, id):
        if id.startswith('jm'):
            id = id[2:]
        
        try:
            response = self.get(f"/album?id={id}")
            data = json.loads(response)
            
            author = data.get('author', [])
            works = data.get('works', [])
            actors = data.get('actors', [])
            chapters = {}
            series = sorted(data.get('series') or [], key=lambda x: x.get('sort', 0))
            
            for e in series:
                title = e.get('name', '').strip()
                if not title:
                    title = f"第{e.get('sort', 0)}話"
                chapter_id = str(e.get('id', ''))
                chapters[chapter_id] = title
            
            if not chapters:
                chapters[id] = '第1話'
            
            tags = data.get('tags', [])
            related = []
            for e in data.get('related_list') or []:
                related.append({
                    'id': str(e.get('id', '')),
                    'title': e.get('name', ''),
                    'subtitle': e.get('author', ''),
                    'cover': self.get_cover_url(e.get('id', '')),
                    'description': e.get('description', '')
                })
            
            update_timestamp = int(data.get('addtime') or 0)
            date = time.localtime(update_timestamp)
            update_date = f"{date.tm_year}-{date.tm_mon}-{date.tm_mday}"
            
            return {
                'title': data.get('name', ''),
                'cover': self.get_cover_url(id),
                'description': data.get('description', ''),
                'likesCount': int(data.get('likes') or 0),
                'chapters': chapters,
                'tags': {
                    'Author': author,
                    'Tag': tags,
                    'Work': works,
                    'Actor': actors,
                    'View': [data.get('total_views', '')] if data.get('total_views') else [],
                },
                'recommend': related,
                'isFavorite': data.get('is_favorite', False),
                'isLiked': data.get('liked', False),
                'updateTime': update_date,
            }
        except Exception as e:
            raise Exception(f"加载漫画信息失败: {str(e)}")
    
    def load_chapter_images(self, chapter_id):
        try:
            response = self.get(f"/chapter?id={chapter_id}")
            data = json.loads(response)
            images = [self.get_image_url(chapter_id, e) for e in data.get('images', [])]
            return {'images': images}
        except Exception as e:
            raise Exception(f"加载章节图片失败: {str(e)}")
    
    def search_comics(self, keyword, page=1):
        keyword = quote_plus(keyword.strip())
        url = f"/search?search_query={keyword}&o=mr"
        if page > 1:
            url += f"&page={page}"
        
        try:
            response = self.get(url)
            data = json.loads(response)
            total = int(data.get('total') or 0)
            max_page = (total + 79) // 80
            comics = [self.parse_comic(e) for e in data.get('content') or []]
            return {'comics': comics, 'maxPage': max_page}
        except Exception as e:
            raise Exception(f"搜索漫画失败: {str(e)}")

    def load_promote_comics(self, page=0):
        try:
            response = self.get(f"/promote?page={page}")
            data = json.loads(response)
            comics = []
            for section in data:
                if section.get("type") in {"library", "novels"}:
                    continue
                for comic in section.get("content") or []:
                    comics.append(self.parse_comic(comic))
            return comics
        except Exception as e:
            raise Exception(f"加载首页推荐失败: {str(e)}")

    def get_categories(self):
        """获取 JM 分类列表（顶级分类 + 子分类）。用于「分类」浏览命令。"""
        try:
            response = self.get("/categories")
            data = json.loads(response)
        except Exception as e:
            raise Exception(f"加载分类列表失败: {str(e)}")

        result = []
        for item in data.get("categories") or []:
            result.append(
                {
                    "id": str(item.get("id")),
                    "name": item.get("name") or "",
                    "slug": item.get("slug") or "",
                    "total_albums": item.get("total_albums") or 0,
                    "subs": [
                        {
                            "cid": str(sub.get("CID")),
                            "name": sub.get("name"),
                            "slug": sub.get("slug"),
                        }
                        for sub in (item.get("sub_categories") or [])
                    ],
                }
            )
        return result

    def load_category_comics(self, category="0", order="mv_t", page=1):
        category = quote_plus(str(category))
        try:
            response = self.get(f"/categories/filter?o={order}&c={category}&page={page}")
            data = json.loads(response)
            total = int(data.get("total") or 0)
            max_page = (total + 79) // 80
            comics = [self.parse_comic(e) for e in data.get("content") or []]
            return {"comics": comics, "maxPage": max_page}
        except Exception as e:
            raise Exception(f"加载分类漫画失败: {str(e)}")

    def random_pool(self, limit=80):
        candidates = []

        try:
            candidates.extend(self.load_promote_comics(page=0))
        except Exception:
            pass

        for order in ("mv_t", "mv_w", "mr"):
            if len(candidates) >= limit:
                break
            try:
                candidates.extend(self.load_category_comics("0", order, 1)["comics"])
            except Exception:
                continue

        unique = {}
        for comic in candidates:
            comic_id = comic.get("id")
            title = comic.get("title")
            if comic_id and title and comic_id not in unique:
                unique[comic_id] = comic

        if not unique:
            raise Exception("未获取到可推荐的漫画")

        items = list(unique.values())
        random.SystemRandom().shuffle(items)
        return items[:limit]

    def random_recommendations(self, count=5):
        items = self.random_pool(max(count * 3, count))
        return items[:count]

    def daily_recommendations(self, count=5):
        return self.random_recommendations(count)

# 创建全局API实例
jm_api = JMAPI()
