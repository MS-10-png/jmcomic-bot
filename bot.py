import os
from pathlib import Path

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter


def load_local_env():
    """加载 .env.local（存放敏感密钥，不纳入版本控制）到环境变量。

    用 setdefault 保证：已存在的系统环境变量优先级最高，不会被本地文件覆盖。
    在 nonebot.init() 之前执行，NoneBot/pydantic 与各插件的 env 读取都能拿到。
    """
    env_path = Path(__file__).resolve().parent / ".env.local"
    if not env_path.exists():
        return
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
        pass


load_local_env()

# 初始化NoneBot
nonebot.init()

# 注册适配器（QQ机器人用ONEBOT_V11）
driver = nonebot.get_driver()
driver.register_adapter(ONEBOT_V11Adapter)

# 加载插件（从plugins目录）
nonebot.load_plugins("plugins")

if __name__ == "__main__":
    nonebot.run()