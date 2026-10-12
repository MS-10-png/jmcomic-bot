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

## 四、首次运行需要你自己配置

1. 复制 `.env.example` 为 `.env`，填入你的机器人 QQ 号
2. 把 DeepSeek API Key 写进 `.env.local`（格式：`DEEPSEEK_API_KEY=sk-...`）
3. 如需 Pixiv R18 图片，把 `PIXIV_PHPSESSID` 写进 `.env.local`
4. 运行 `Start_All.bat` 或管理面板，权限白名单在面板里重新设置（迁移时已清空）

## 五、审计报告

`docs/审计报告-2026-10-12.md` 是对本项目的一次代码审计：22 条缺陷与优化项，按 P0–P3 分级，每条附代码位置与最小修复方案。报告全文不含任何个人信息。
