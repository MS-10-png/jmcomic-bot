# 本仓库的脱敏说明

本仓库是 JMcomic_bot 的**脱敏发布副本**。原项目在作者本机运行过一段时间，包含真实的 QQ 号、群号、聊天记录、订阅/偏好库与 API 密钥。发布前已按下列规则清理，并做了自动化复核。

复核方式：对全部文本文件重新扫描「QQ 号 / 群号 / 邮箱 / Windows 用户名 / 绝对路径 / API Key / GitHub 账号 / 9–12 位长数字」，除下述白名单外零命中。

---

## 一、已删除的用户状态文件

这些文件是运行期产生的个人数据，应用在缺失时会自动重建默认值：

| 文件 | 原本含有什么 |
| --- | --- |
| `plugins/bot_control.json` | 白名单/黑名单里的真实 QQ 号与群号、单人功能开关 |
| `plugins/jm_preferences.json` | 各群/私聊看过的漫画编号与偏好权重 |
| `plugins/jm_subscriptions.json` | 订阅的漫画编号与推送目标 |
| `plugins/llm_history.json` | **聊天记录原文**与发言者 QQ 号 |
| `plugins/llm_user_prefs.db` | SQLite 聊天偏好库（按 QQ/群号建键） |
| `plugins/pixiv_age_verification.json` | 哪些 QQ 做过 R18 年龄确认 |
| `plugins/pixiv_preferences.json` | 各 QQ/群的出图偏好权重 |
| `plugins/pixiv_subscribers.json` | Pixiv 日榜推送目标群 |

上述文件同时已加入 `.gitignore`，避免以后再次误提交。

## 二、已替换的硬编码信息

| 位置 | 原内容 | 现内容 |
| --- | --- | --- |
| `BotManagerApp.cs` | 机器人 QQ 号 | `100000000`（占位） |
| `Run_NapCat_Shell.bat` | 机器人 QQ 号（2 处） | `100000000` |
| `Start_All.bat` | 机器人 QQ 号 | `100000000` |
| `setup_napcat_shell.ps1` | 机器人 QQ 号 | `100000000` |
| `.env`（已删除） | QQ 号、Pixiv Cookie 字段 | 见 `.env.example`（占位值，密钥留空） |

## 三、未包含的目录与文件

| 未包含 | 原因 |
| --- | --- |
| `.venv/` | 62 MB 虚拟环境，可用 `pip install -r requirements.txt` 重建 |
| `NapCat.Shell/` | 320 MB 第三方运行时（NapCat + QQ 注入壳），由 `setup_napcat_shell.ps1` 自动下载 |
| `plugins/download/`、`downloads/` | 运行期下载的漫画缓存（数百 MB，且属第三方内容） |
| `logs/` | 含真实聊天记录、QQ 号与群号 |
| `__pycache__/` | Python 编译缓存 |
| `JMComicBotManager.exe`、`JMComicBotManager.new.exe` | 编译产物，源码 `BotManagerApp.cs` 已在仓库中 |
| `_ghdesk_zh/` | 与本项目无关的第三方工具（GitHub Desktop 汉化），约 22 MB |
| `.env.local` | 含真实 DeepSeek API Key |

## 四、下载后如何跑起来（逐步实测过）

> 环境：Windows + Python 3.10~3.14。以下每一步都在全新克隆 + 全新虚拟环境里验证过。

**第 1 步 · 装依赖**

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

> ⚠️ 2026-10-12 修正：原 `requirements.txt` 写的是裸 `nonebot2`，缺少 FastAPI/websockets extra，
> 装完启动会直接报 `ImportError: Please install FastAPI first to use this driver`。
> 现已改为 `nonebot2[fastapi,websockets]>=2.4.4`，与 `pyproject.toml` 保持一致。
> 实测在 nonebot 2.5.0 + Python 3.14 下可正常启动。

**第 2 步 · 配置机器人账号**

复制 `.env.example` 为 `.env`，把 `QQ_BOT_ACCOUNT` 从占位值 `100000000` 改成你自己的 QQ 号。

另外这 4 个文件里也有同一个占位值，需要一并替换（脱敏时统一改成了 `100000000`）：

| 文件 | 行 |
| --- | --- |
| `BotManagerApp.cs` | 默认账号回退值 |
| `Run_NapCat_Shell.bat` | 2 处 |
| `Start_All.bat` | 登录提示行 |
| `setup_napcat_shell.ps1` | `$QQ` 变量 |

**第 3 步 · 获取 NapCat 运行时（约 118 MB，不随仓库分发）**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File setup_napcat_shell.ps1
```

脚本会从 NapCat 官方 release 下载 `NapCat.Shell.Windows.Node.zip` 并写入 OneBot 配置。

> ⚠️ 必须在启动前确认：**本机 QQ 的 build 号在 NapCat 支持列表内**。
> 取 `C:\Program Files\Tencent\QQNT\versions\config.json` 的 `curVersion`，
> 在 `NapCat.Shell\napcat\napcat.mjs` 里搜这个 build——搜不到就会注入失败、机器人收不到消息。
> 这个坑详见 `docs/审计报告-2026-10-12.md` 的 P0-1 / P0-5。

**第 4 步 · 编译管理面板（EXE 不随仓库分发）**

`启动管理面板.bat` / `.vbs` 会去跑 `JMComicBotManager.exe`，但该文件是编译产物，仓库里只有源码
`BotManagerApp.cs`。需要先编译：

```bat
C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo /codepage:65001 /target:winexe /optimize+ ^
  /out:JMComicBotManager.exe /lib:C:\Windows\Microsoft.NET\Framework64\v4.0.30319 ^
  /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll ^
  BotManagerApp.cs
```

**第 5 步 · 可选密钥**

写进 `.env.local`（不会进版本控制）：

```
DEEPSEEK_API_KEY=sk-...        # 不填 = 关闭 AI，回退规则解析
PIXIV_PHPSESSID=...            # 不填 = Pixiv R18/R18G 图片取不到
```

**第 6 步 · 启动**

双击 `Start_All.bat`（会顺带做依赖检查与 NapCat 安装），或先用管理面板。
启动日志出现 `Uvicorn running on http://127.0.0.1:8081` 即成功；
你本机的 OneBot 反向连接地址应为 `ws://127.0.0.1:8081/onebot/v11/ws`。

权限白名单在管理面板里重新设置（迁移时已清空）。

### 已知的启动现象

- `Application startup complete` 会等约 **20 秒**才打印（两次独立实测都一样），期间不是卡死，稍等即可。

## 五、审计报告

`docs/审计报告-2026-10-12.md` 是对本项目的一次代码审计：22 条缺陷与优化项，按 P0–P3 分级，每条附代码位置与最小修复方案。报告全文不含任何个人信息。

## 六、相对原版代码的改动（2026-10-12）

针对审计报告的 P0 全部 5 条，外加 P1-6，已在本仓库修复。

| 审计编号 | 问题 | 改动 | 涉及文件 |
| --- | --- | --- | --- |
| P0-1 | QQ 热更后 NapCat 失配，机器人静默变哑 | 新增 `check_napcat_compat.ps1`：读 `versions/config.json` 的 `curVersion`，与 `napcat.mjs` 里的支持列表比对；退出码 0/1/2/3 分别表示兼容/不兼容/NapCat 缺失/找不到 QQ | `check_napcat_compat.ps1`（新增） |
| P0-5 | 安装脚本只在文件缺失时下载，永不更新 | `setup_napcat_shell.ps1` 改为**以兼容性为判据**：不兼容即自动下载最新 NapCat；新增 `-Force`；更新前后各跑一次自检；替换前备份、替换后还原 `config` 目录与项目自定义 launcher 文件（避免重登 QQ / 重配 WebUI / 丢失定制脚本） | `setup_napcat_shell.ps1` |
| P0-2 | 管理面板把启动失败报成成功 | 启动后延迟 4 秒验证（NapCat 进程 / cmd 进程 / 日志三者交叉判断），失败弹出窗口并回显日志尾部；`StartManaged` 的文案从「已启动」改为「已提交启动（正在验证…）」 | `BotManagerApp.cs` |
| P0-4 | CHANGELOG 说用 launcher-noadmin，代码里写死 launcher.bat | `StartNapCat()` 按 `launcher-user.bat`（官方免提权）→ `launcher-noadmin.bat`（项目自带）→ `launcher.bat`（需管理员）顺序查找 | `BotManagerApp.cs` |
| P0-3 | 已编译的修复未部署 | 新增 `build_manager.bat` 一键编译（产物 `JMComicBotManager.new.exe`），配合已有 `apply_fix.bat` 完成部署 | `build_manager.bat`（新增） |
| P1-6 | `.env` 对插件层完全失效 | `bot.py` 的加载器改为依次读取 `.env.local`、`.env` 并写入 `os.environ`（`setdefault` 保证优先级：系统环境变量 > `.env.local` > `.env`） | `bot.py` |
| 附录 | 依赖声明缺 extra，按 README 装完起不来 | `requirements.txt` 与 `pyproject.toml` 对齐为 `nonebot2[fastapi,websockets]>=2.4.4` | `requirements.txt` |

### 实测记录

| 项目 | 结果 |
| --- | --- |
| `check_napcat_compat.ps1` 对真实环境判定 | `RESULT=UNSUPPORTED`（QQ `9.9.35-52892` vs 本地 NapCat 最高 `9.9.30-48517`）——准确复现了本次停机 |
| `setup_napcat_shell.ps1` 兼容分支 | 本地 NapCat 已兼容时打印 `Skipping download` 且不下载 |
| `setup_napcat_shell.ps1` 不兼容分支（完整跑通） | 自动下载 118 MB → 备份并还原 config → 替换 → 复查为 **`RESULT=OK`（QQ 9.9.35-52892 已支持，79 个 build）**。全程 139.5 秒 |
| `BotManagerApp.cs` 编译 | `csc.exe` 退出码 0 |
| `bot.py` 修复后 `os.environ` | `JM_CHAT_JUDGE=1`、`JM_SEARCH_SEND_COVERS=3`、`JM_CACHE_MAX_AGE_DAYS=30` 等全部就位（修复前均为 `None`） |
| 机器人启动（全新 venv / nonebot 2.5.0 / Python 3.14） | 12 个插件全部加载，监听 `127.0.0.1:8081` |

