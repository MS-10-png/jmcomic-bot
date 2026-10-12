import os
from pathlib import Path

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter


def load_env_files():
    """把 .env.local 与 .env 读进 os.environ，供插件层的 os.getenv 使用。

    为什么两个都要加载：
      NoneBot 的 nonebot.init() 只会把 .env 读进 driver.config（pydantic 配置），
      并不会写入 os.environ；而插件层（jmcomic_bot / chat_judge / group_chat /
      bot_control）全部用 os.getenv 读配置。如果这里只加载 .env.local，那么 .env
      里的十几个可调参数会全部落回代码里的硬编码默认值——
      典型症状是 JM_CHAT_JUDGE=0 关不掉 LLM 判断、JM_ANNOUNCE_ON_START=0 照样发公告、
      JM_SEND_DELAY_SECONDS 改了没反应。

    优先级：已存在的系统环境变量 > .env.local > .env
      （用 setdefault 实现，先加载的优先，所以 .env.local 先于 .env）
    """
    base = Path(__file__).resolve().parent
    for name in (".env.local", ".env"):
        env_path = base / name
        if not env_path.exists():
            continue
        try:
            for raw_line in env_path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and value:
                    os.environ.setdefault(key, value)
        except Exception:
            # 配置文件不可读不应阻断启动
            pass


load_env_files()

# 初始化NoneBot
nonebot.init()

# 注册适配器（QQ机器人用ONEBOT_V11）
driver = nonebot.get_driver()
driver.register_adapter(ONEBOT_V11Adapter)

# 加载插件（从plugins目录）
nonebot.load_plugins("plugins")

if __name__ == "__main__":
    nonebot.run()
