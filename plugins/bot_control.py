import json
import threading
from copy import deepcopy
from pathlib import Path


CONTROL_FILE = Path(__file__).resolve().parent / "bot_control.json"

# 配置缓存：按文件 mtime+size 失效。管理面板保存配置后会自动读到新值，
# 机器人每条消息不再重复读盘解析 JSON。
_CONFIG_CACHE_LOCK = threading.Lock()
_CONFIG_CACHE = {"stamp": None, "config": None}

FEATURES = {
    "jm_image": "JM 图片发送",
    "jm_file": "JM 加密压缩包",
    "jm_cover": "JM 封面",
    "jm_search": "JM 关键词搜索",
    "jm_recommend": "JM 随机推荐",
    "pixiv_recommend": "Pixiv 推荐/订阅推送",
    "pixiv_search": "Pixiv TAG/PID 搜图",
    "pixiv_random": "Pixiv 来点图",
    "pixiv_rating": "评分偏好系统",
}

DEFAULT_CONFIG = {
    "access_mode": "all",
    "allowed_users": [],
    "blocked_users": [],
    "allowed_groups": [],
    "blocked_groups": [],
    "features": {name: True for name in FEATURES},
    "user_features": {},
}


def normalize_id(value):
    return str(value).strip()


def normalize_id_list(values):
    result = []
    for value in values or []:
        item = normalize_id(value)
        if item and item not in result:
            result.append(item)
    return result


def merge_config(data):
    config = deepcopy(DEFAULT_CONFIG)
    if isinstance(data, dict):
        config.update({key: value for key, value in data.items() if key not in {"features", "user_features"}})
        features = deepcopy(DEFAULT_CONFIG["features"])
        features.update(data.get("features") or {})
        config["features"] = {name: bool(features.get(name, True)) for name in FEATURES}
        config["user_features"] = normalize_user_features(data.get("user_features") or {})

    if config.get("access_mode") not in {"all", "allowlist"}:
        config["access_mode"] = "all"

    for key in ("allowed_users", "blocked_users", "allowed_groups", "blocked_groups"):
        config[key] = normalize_id_list(config.get(key))

    return config


def normalize_user_features(value):
    result = {}
    if not isinstance(value, dict):
        return result

    for raw_user_id, raw_features in value.items():
        user_id = normalize_id(raw_user_id)
        if not user_id or not isinstance(raw_features, dict):
            continue

        features = {}
        for feature in FEATURES:
            if feature in raw_features:
                features[feature] = bool(raw_features[feature])
        if features:
            result[user_id] = features
    return result


def _file_stamp():
    try:
        stat = CONTROL_FILE.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def load_control_config():
    stamp = _file_stamp()
    with _CONFIG_CACHE_LOCK:
        if stamp is not None and _CONFIG_CACHE["stamp"] == stamp and _CONFIG_CACHE["config"] is not None:
            return deepcopy(_CONFIG_CACHE["config"])

    if stamp is None:
        config = save_control_config(DEFAULT_CONFIG)
        with _CONFIG_CACHE_LOCK:
            _CONFIG_CACHE["stamp"] = _file_stamp()
            _CONFIG_CACHE["config"] = config
        return deepcopy(config)

    try:
        data = json.loads(CONTROL_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        return deepcopy(DEFAULT_CONFIG)

    config = merge_config(data)
    with _CONFIG_CACHE_LOCK:
        _CONFIG_CACHE["stamp"] = _file_stamp()
        _CONFIG_CACHE["config"] = config
    return deepcopy(config)


def save_control_config(config):
    config = merge_config(config)
    CONTROL_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with _CONFIG_CACHE_LOCK:
        _CONFIG_CACHE["stamp"] = _file_stamp()
        _CONFIG_CACHE["config"] = config
    return config


def feature_label(feature):
    return FEATURES.get(feature, feature or "未知功能")


def is_feature_enabled(feature):
    if not feature:
        return True
    config = load_control_config()
    return bool(config["features"].get(feature, True))


def event_identity(event):
    user_id = normalize_id(getattr(event, "user_id", ""))
    group_id = normalize_id(getattr(event, "group_id", ""))
    return user_id, group_id


def check_event_access(event, feature=None):
    config = load_control_config()
    user_id, group_id = event_identity(event)

    if user_id and user_id in config["blocked_users"]:
        return False, "你暂时没有使用权限，请联系管理员。"

    if group_id and group_id in config["blocked_groups"]:
        return False, "当前群暂时没有使用权限，请联系管理员。"

    if config["access_mode"] == "allowlist":
        allowed = False
        if user_id and user_id in config["allowed_users"]:
            allowed = True
        if group_id and group_id in config["allowed_groups"]:
            allowed = True
        if not allowed:
            return False, "你还没有被加入机器人使用名单，请联系管理员。"

    if feature and not config["features"].get(feature, True):
        return False, f"{feature_label(feature)} 已在管理面板中关闭。"

    user_features = config.get("user_features") or {}
    if feature and user_id and isinstance(user_features.get(user_id), dict):
        if user_features[user_id].get(feature, True) is False:
            return False, f"你没有使用 {feature_label(feature)} 的权限，请联系管理员。"

    return True, ""
