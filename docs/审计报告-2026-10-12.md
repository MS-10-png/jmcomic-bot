# JMcomic_bot 代码审计报告

> 审计日期：2026-10-12
> 审计对象：JMcomic_bot（NoneBot2 + OneBot v11 的 QQ 漫画机器人，含 WinForms 管理面板与 NapCat 注入层）
> 审计方式：两轮独立模块审计（主机器人模块 / 辅助模块）+ 审计人对本机的实测复核
> 报告范围：缺陷与优化项 **22 条**，按 P0–P3 分级，每条附代码位置与最小修复方案

---

## 0. 结论摘要

**主干设计是健康的，问题集中在三处边缘：运行前提（QQ/NapCat 版本）、配置生效链路（`.env`）、以及状态持久化（JSON 文件的并发与原子性）。**

审计时机器人处于**停机**状态——最后一次成功运行是 2026-10-09 23:24，此后再未起来。停机原因不是 NoneBot、也不是业务代码，而是 QQ 自动热更新到了 NapCat 尚未适配的 build（P0-1）。

三个最该先处理的方向：

1. **让它能跑起来**：升级 NapCat，并补上「启动前版本兼容自检」（P0-1 ~ P0-5）
2. **让配置真正生效**：`.env` 目前对插件层完全不可见，十几个可调参数全部落回硬编码默认值（P1-6）
3. **别丢数据、别泄漏**：订阅读写竞态、私发失败转群，这两条会实际造成损失（P1-8、P1-9）

---

## 1. 环境快照（审计时实测）

| 项目 | 实测值 |
| --- | --- |
| 本机 QQ 版本目录 | 仅 `9.9.35-52892`（2026-09-09 创建） |
| 本地 NapCat 支持的最高 build | `9.9.30-48517`（支持列表共 66 个 build；不含 52892，也不含开发备忘记录的 51246） |
| 本地 NapCat.Shell 文件时间 | 2026-05-15 |
| 机器人最后成功运行 | 2026-10-09 23:24（其后 WebSocket 断开、进程退出） |
| Python | 3.12.13（`.venv`） |
| JM API | **正常**：域名刷新成功，刷新后搜索 1.73s 返回结果 |
| DeepSeek API | **可用**：实测 0.87s 返回 |
| 联网搜索 / B站搜索 / 词典 | **可用**：实测分别 0.30s / 0.65s / 0.06s 返回 |
| Pixiv | 直连 `www.pixiv.net` 超时；走系统代理 `127.0.0.1:7897` 0.28s 成功 |
| 缓存体积 | `plugins/download` 460 MB（其中可重生的 zip 226 MB、图片 234 MB） |

---

## 2. 优先级总表

| 编号 | 级别 | 问题 | 位置 |
| --- | --- | --- | --- |
| 1 | P0 | QQ 版本与 NapCat 不匹配，机器人无法运行 | `NapCat.Shell/napcat/napcat.mjs` |
| 2 | P0 | 管理面板把 NapCat 启动失败报成成功 | `BotManagerApp.cs:1806` |
| 3 | P0 | 已编译的修复未部署，线上仍是旧 exe | `JMComicBotManager.new.exe` |
| 4 | P0 | CHANGELOG 承诺的 launcher-noadmin 在代码里不存在 | `BotManagerApp.cs:1595` |
| 5 | P0 | 安装脚本永不更新 NapCat（本轮停机根因） | `setup_napcat_shell.ps1:74` |
| 6 | P1 | `.env` 对插件层完全失效 | `bot.py:31` |
| 7 | P1 | 封面开关设 0 关不掉（与 README 矛盾） | `plugins/jmcomic_bot.py:94` |
| 8 | P1 | 订阅巡检读-改-写覆盖用户操作；状态文件非原子写 | `plugins/jmcomic_bot.py:1021/1040/941` |
| 9 | P1 | 私发失败自动改为群发（隐私） | `plugins/jmcomic_bot.py:2004` |
| 10 | P1 | 权限校验缺口：R18 确认分支与启动公告 | `plugins/jmcomic_bot.py:1463`、`plugins/group_chat.py:397` |
| 11 | P1 | 消息提到 bot 名字即绕过每小时上限 | `plugins/chat_judge.py:218` |
| 12 | P1 | AI 不可用时裸数字直接触发下载 | `plugins/jmcomic_bot.py:3875` |
| 13 | P2 | 每条群消息建一次 SQLite 表 | `plugins/llm_prefs.py:22-31` |
| 14 | P2 | `llm_history.json` 每条 @ 消息 3 读 1 全量写且无限增长 | `plugins/llm_chat.py:345-404` |
| 15 | P2 | 每条消息 150+ 次正则扫描 | `plugins/jmcomic_bot.py:2935-2939` |
| 16 | P2 | 意图判断白背 1.5k 字人设（纯 token 浪费） | `plugins/chat_judge.py:76` |
| 17 | P2 | 订阅巡检串行无上限；JM 域名刷新一次失败即永久放弃 | `plugins/jmcomic_bot.py:1019`、`plugins/jm_api.py:281` |
| 18 | P3 | 缓存 460 MB；部分目录不在清理范围 | `plugins/jmcomic_bot.py:1613` |
| 19 | P3 | 日志不轮转；面板读全文件只显示尾部 | `BotManagerApp.cs:1982` |
| 20 | P3 | 帮助菜单写的命令与匹配表不一致 | `plugins/jmcomic_bot.py:236,2301` |
| 21 | P3 | 无关文件 22 MB（汉化工具、token 监控脚本） | 仓库根目录 |
| 22 | P3 | 后台任务未持引用、无优雅关闭 | `plugins/jmcomic_bot.py:1698-1701` |

---

## 3. P0 · 阻断：机器人现在起不来

### P0-1 QQ 自动更新到 NapCat 未适配的 build

**证据**

- 本机 `C:\Program Files\Tencent\QQNT\versions\` 下只有 `9.9.35-52892`（创建于 2026-09-09），`versions/config.json` 的 `curVersion` 指向它。
- `NapCat.Shell/napcat/napcat.mjs` 内的支持列表共 66 个 build，**最高为 `9.9.30-48517`**；不含 `9.9.35-52892`，也不含开发备忘中记录的 `9.9.32-51246`。
- `logs/manager_app/napcat.log` 最后若干条均为 `Starting: cmd.exe /c call "...\launcher.bat"` → 3 秒后 `Process exited: 0`。
- `logs/manager_app/nonebot.log` 最后一条为 `Process exited: 1073807364`（2026-10-09 23:24）。

**影响**

NapCat 的 Hook 偏移按 QQ buildId 硬编码，build 不在支持列表内即注入失败，NoneBot 收不到任何消息。这是项目已知的头号风险（见 `开发备忘.md` 第一节），本次再次发生。

**最小修复**

1. 更新 `NapCat.Shell` 到支持当前 QQ build 的版本（官方 release 取 `NapCat.Shell.Windows.Node.zip` 覆盖）。
2. 增加启动前自检：读 `versions/config.json` 的 `curVersion`，在 `napcat.mjs` 的支持列表里查找，未命中则拦下并给出升级指引——否则每次 QQ 热更都会重演一次。

### P0-2 管理面板把启动失败报成成功

**证据**

- `BotManagerApp.cs:1806`：`SetMessage(key + " 已启动，PID " + process.Id);`
- `BotManagerApp.cs:1605-1606`：实际启动的是 `cmd.exe /c call launcher.bat`。
- `logs/manager_app/napcat.log`：`10:03:17 Starting ...` → `10:03:20 Process exited: 0`
- `logs/manager_app/manager.log`：同期写入 `napcat 已启动，PID 24908`

**影响**

PID 属于 `cmd.exe`，而 cmd 在 `launcher.bat` 打印 `Please run this script in administrator mode.` 后立即退出（`NapCat.Shell/napcat/launcher.bat:5-10`）。面板显示运行中，实际什么都没跑，排障时会严重误导。

**最小修复**

启动后延迟 2–3 秒做存活探测（进程是否仍在 / 3000 端口是否监听 / 日志是否出现注入成功标志），失败则显式报错并回显 launcher 输出。

### P0-3 已编译的修复未部署

**证据**

| 文件 | 大小 | 修改时间 |
| --- | --- | --- |
| `BotManagerApp.cs` | 81730 | 2026-08-19 19:41 |
| `JMComicBotManager.new.exe` | 46592 | 2026-08-19 19:41 |
| `JMComicBotManager.exe`（线上） | 45056 | 2026-08-19 10:36 |

两者哈希不同；仓库中不存在 `JMComicBotManager.exe.bak`，说明 `apply_fix.bat` 从未执行。

**影响**

源码已经改好、新 exe 已经编译好，但一直在用 9 小时前的旧版运行——所有「改了但没生效」的困惑都源于此。

**最小修复**

执行 `apply_fix.bat`（会备份旧 exe 并重启面板），并在开发备忘的检查清单里把「编译后必须部署」变成脚本化步骤。

### P0-4 CHANGELOG 承诺的 launcher-noadmin 在代码里不存在

**证据**

- `CHANGELOG.md`（2026-08-19）称：「管理器『启动 NapCat』优先使用它（`launcher-noadmin.bat`），不再依赖 UAC 提权」。
- `BotManagerApp.cs:1595`：`Directory.GetFiles(napcatRoot, "launcher.bat", SearchOption.AllDirectories).FirstOrDefault()`
- 全仓库 `.cs` 文件中检索 `launcher-noadmin`：**零命中**。该 bat 文件确实存在于 `NapCat.Shell/napcat/`，但没有任何代码调用它。

**影响**

文档与实现不一致。用户按 CHANGELOG 预期「不需要管理员权限」，实际仍在调用需要提权的 `launcher.bat`——这正是 P0-2 里反复出现 `Please run this script in administrator mode.` 的直接原因。

**最小修复**

二选一并同步文档：要么在 `StartNapCat()` 里真正优先使用 `launcher-noadmin.bat`（失败再回退 `launcher.bat`），要么删掉该 bat 与 CHANGELOG 中的相关表述。

### P0-5 安装脚本永不更新 NapCat（本轮停机根因）

**证据**

`setup_napcat_shell.ps1:74-76`：

```powershell
$Launcher = Get-ChildItem -Path $ShellDir -Recurse -Filter "launcher.bat" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $Launcher) {
    Write-Host "[INFO] Downloading NapCat Shell Windows Node package..."
```

**影响**

只有 `launcher.bat` **不存在**时才去下载。目录一旦存在，脚本永远走不到下载分支——项目里不存在任何 NapCat 更新路径。这就是「QQ 每次热更 → NapCat 失配 → 机器人死掉 → 只能人工处理」这条循环的结构性原因。

**最小修复**

把判定条件从「文件是否存在」改成「版本是否兼容」：解析本地 NapCat 支持的 build 列表与当前 QQ build 比对，不匹配就提示（或一键）下载最新包覆盖。

---

## 4. P1 · 会丢数据、会泄漏、关不掉

### P1-6 `.env` 对插件层完全失效

**证据**

- `bot.py:14-31`：`load_local_env()` 只读取 `.env.local` 并写入 `os.environ`。
- 实测（`import bot` 之后打印 `os.environ`）：`JM_CHAT_JUDGE`、`JM_SEARCH_SEND_COVERS`、`JM_CACHE_MAX_AGE_DAYS`、`JM_SILENCE_SECONDS`、`LLM_HISTORY_MAX`、`QQ_BOT_ACCOUNT` 等**全部为 `None`**；而 `get_driver().config` 里能读到这些值（NoneBot 会把 `.env` 读进自己的 pydantic 配置）。
- 插件层读取方式：`plugins/jmcomic_bot.py:92-129`、`plugins/chat_judge.py:42-54`、`plugins/group_chat.py:29-49` 全部使用 `os.getenv`。

**影响**

`.env` 里那十几行注释都在教用户调参，实际上一个都不生效：`JM_CHAT_JUDGE=0` 关不掉 LLM 判断、`JM_ANNOUNCE_ON_START=0` 照发公告、`JM_SEND_DELAY_SECONDS` 改不动。当前 `.env` 里的值恰好都等于代码默认值，所以**症状被掩盖了**——一旦有人按注释去调，就会发现调了没用。

**最小修复**

`bot.py` 的 loader 遍历 `(".env", ".env.local")` 并 `os.environ.setdefault(...)`（保持「系统环境变量 > `.env.local` > `.env`」的优先级）。一行逻辑，一次性修复所有 `os.getenv` 调用点。

### P1-7 封面开关设 0 关不掉

**证据**

`plugins/jmcomic_bot.py:92-96`：

```python
def get_env_int(name, default):
    try:
        return max(1, int(os.getenv(name, str(default))))
```

而 `:124` 注释写 `0 = 关闭`，`:128` 同样写 `0 = 只发文字`，`README.md` 也明确写「把 `JM_SEARCH_SEND_COVERS`、`JM_RECOMMEND_SEND_COVERS` 设为 `0`」。三处开关（`:125/:126/:129`）都被 `max(1, ...)` 抬高到 1。

**影响**

文档承诺的关闭功能不存在。用户按 README 关掉封面仍会每次多发 1–3 张图（叠加 P1-6，即使写成 0 也先被 `.env` 失效挡一层，双重失效）。

**最小修复**

这三个开关改用 `max(0, int(...))`；`get_env_int` 保留给确实需要下界的参数（如巡检间隔）。

### P1-8 订阅巡检读-改-写覆盖用户操作

**证据**

`plugins/jmcomic_bot.py`：

- `:1021` `data = load_jm_subscriptions()`（一次读取）
- `:1023-1039` 对每本漫画逐个 `jm_api.load_comic_info(comic_id)` 发网络请求（最坏 4 域名 × 2 次 × 15s 超时）
- `:1040` `save_jm_subscriptions(data)`（整体回写）

调用点在 `:1684` 的 `asyncio.to_thread(check_jm_subscriptions)`；同一期间用户触发的 `add_jm_subscription`（`:968`）/`remove_jm_subscription`（`:980`）会写同一个文件。

另：`save_jm_subscriptions:941` 使用 `write_text`（先截断后写，非原子），读取侧 `except Exception: data = {}`（`:933`）会把「读到半截文件」当成「空配置」，下一次保存就把全部订阅清零。同样的模式出现在 `:602/:624/:649/:913`。

**影响**

巡检耗时越长，用户在这段时间里的 jm订阅/jm取消 越可能被静默回滚——表现为「我明明订了，列表里没有」。

**最小修复**

1. JSON 读写加模块级 `threading.Lock`，保存前重新读取并与内存变更合并（或改为操作级增量写）。
2. 落盘改成 `tmp` + `os.replace()` 原子替换。
3. 解析失败**不要**返回空 dict，应抛错或回退备份文件。

### P1-9 私发失败自动改为群发

**证据**

`plugins/jmcomic_bot.py:1992-2012`：私聊上传失败后，紧接着调用 `upload_group_file(group_id=event.group_id, ...)`，并只发一句「私聊文件上传失败，已改为上传到当前群文件。」

**影响**

用户明确要求「私发」的文件（可能是 R18 内容）在上传失败时被**自动公开到整个群**，且是事后告知。这是本报告里唯一一条会造成不可逆后果的隐私问题。

**最小修复**

私发失败即返回失败信息（附本地路径），是否转群由用户下次显式指令决定；确需自动降级时应要求显式同意。

### P1-10 权限校验缺口：R18 确认分支与启动公告

**证据**

- `plugins/jmcomic_bot.py:1456-1466`：`handle_pixiv_interactive_message` 的前两个分支（`is_pixiv_adult_cancel_text` / `is_pixiv_adult_confirm_text`）直接执行并回复，**没有任何 `check_event_access`**；直到 `:1468-1472` 的抽图/评分分支才做权限判断。其余 handler 均调用 `ensure_bot_control`。
- `plugins/group_chat.py:397-410`：启动公告把 `bot.get_group_list()` 返回的**全部群**加入发送集合，发送前不过滤 `blocked_groups` / `access_mode`。同文件的 `handle_group_increase`（`:286`）同样未走 `check_event_access`。

**影响**

被拉黑/禁用的用户仍可写入年龄验证状态并得到回复；公告会发进已经明确拉黑的群。

**最小修复**

在 `handle_pixiv_interactive_message` 入口统一做一次权限校验；公告发送前用 `bot_control` 的配置过滤群列表。

### P1-11 消息提到 bot 名字即绕过每小时上限

**证据**

`plugins/chat_judge.py:218`：

```python
if not is_followup and not mentioned and not _judge_rate_allows(event.group_id):
    return
```

**影响**

冷却（`JUDGE_MIN_INTERVAL` 30s）与每小时上限（`JUDGE_MAX_PER_HOUR` 10 次）在消息包含「小鱼」等名字时**全部跳过**。群里反复刷名字即可无限触发 DeepSeek 调用并无上限接话，同时是刷屏与费用风险。

**最小修复**

小时上限始终生效，仅在「提到名字」时放开最小间隔：`if not _judge_hour_allows(...) : return` 与 `if not mentioned and not _judge_min_interval_allows(...): return` 分开判断。

### P1-12 AI 不可用时裸数字直接触发下载

**证据**

`plugins/jmcomic_bot.py:3872-3875`（`handle_at_comic` 尾部）：

```python
if await handle_llm_message(bot, event, text, at_comic_cmd):
    return
await run_deterministic_task(bot, event, at_comic_cmd, text, strict=False, help_fallback=True)
```

`run_deterministic_task:3529`：`strict=False` 时走 `parse_at_comic_request(text)`，而该函数（`:517-522`）只要求命中 `COMIC_ID_PATTERN`（3 位以上数字）即可构造下载请求。

**影响**

「闲聊里夹编号不会误触发」这条安全闸门实际位于 LLM 意图层；`DEEPSEEK_API_KEY` 为空、超时或接口异常导致回退时，`@机器人 我买了 123 元的皮肤` 这类消息会直接去下载编号 123。CHANGELOG 中「闲聊里夹编号仍不会误触发」的表述只在 LLM 可用时成立。

**最小修复**

`handle_at_comic` 的回退路径改用 `explicit_comic_command(text, require_mode=True)`（与无 @ 场景一致），即裸数字不触发，必须带功能词。

---

## 5. P2 · 每条消息的固定开销与成本

### P2-13 每条群消息建一次 SQLite 表

**证据**

`plugins/llm_prefs.py:20-33`：`_connect()` 每次都执行 `sqlite3.connect` + 两条 `CREATE TABLE IF NOT EXISTS` + `commit`。该函数在 `get_styles` / `record_chat_stats` / `is_group_silenced` 中被反复调用；群消息路径上经 `plugins/chat_judge.py:181` 命中。

**影响**

每条群消息都要付一次连接与 DDL 开销；且未设置 `busy_timeout` / WAL，锁冲突时 `OperationalError` 会直接抛到调用点。

**最小修复**

schema 只建一次（模块级 `_ensure_schema()` 或进程内连接复用），`PRAGMA busy_timeout=3000`；纯时间戳状态（如 `silenced_until`）可直接放内存 dict。

### P2-14 `llm_history.json` 每条 @ 消息 3 读 1 全量写且无限增长

**证据**

`plugins/llm_chat.py:345-404`：`_load_history()` 每次 `json.loads` 整个文件，`_save_history()` 每次整体重写。调用点包括 `:3087`（build_llm_messages）、`:3121`、`:3150`。
`_prune():365-373` 只按 TTL 过滤**当前 key** 的条目；`:393` `data[key] = entries[-HISTORY_MAX:]` 在清空后仍会留下空数组 key，其它 key 的过期条目永不清理。

**影响**

文件大小随「历史见过的群数」单调增长，单条消息的读写成本线性上升；长期运行后每条 @ 消息都要做一次全文件 JSON 解析与序列化。

**最小修复**

改为内存 dict + 定期/退出时落盘，`_save_history` 时顺带清理全表过期 key 与空 key；或直接迁移到已有的 SQLite 偏好库。

### P2-15 每条消息 150+ 次正则扫描

**证据**

`plugins/jmcomic_bot.py:2935-2939`：

```python
for word in sorted(set(mode_words), key=len, reverse=True):
    cleaned = re.sub(re.escape(word), " ", cleaned, flags=re.IGNORECASE)
for word in sorted(set(EXPLICIT_FILLER_WORDS), key=len, reverse=True):
    cleaned = re.sub(re.escape(word), " ", cleaned, flags=re.IGNORECASE)
```

约 78 个关键词逐个执行 `re.sub`。而 `explicit_comic_command` 在一次消息处理中会被调用多次：`:3001`、`:3030`、`:3529`、`:3717`。加上 `run_deterministic_task:3433-3527` 的十余个 parse 探针，单条群消息累计上百次正则扫描，全部发生在唯一的事件循环线程上。

**最小修复**

把词表编译成**一个**按长度降序的 alternation 正则，一次 `sub` 完成；把解析结果缓存在 event/contextvar 上供后续复用，避免同一条消息重复解析。

### P2-16 意图判断白背 1.5k 字人设

**证据**

`plugins/chat_judge.py:75-92`：`JUDGE_SYSTEM_PROMPT = PERSONA_CORE + ...`，而 `PERSONA_CORE`（`plugins/llm_chat.py:28-61`）是完整的人设与说话规范；而该调用只需要输出 `{"directed_to_bot": bool, "reply": str}`。

**影响**

每次群聊判断都为一段 ~1.5k 字符的系统提示付 token，且这个调用是高频路径（受频率限制后仍为每群 30s 一次的上限）。

**最小修复**

judge 使用精简版人设（保留语气要求即可），完整 `PERSONA_CORE` 只留给实际生成回复的 compose 阶段。

### P2-17 订阅巡检串行无上限；域名刷新一次失败即永久放弃

**证据**

- `plugins/jmcomic_bot.py:1019-1041`：巡检对所有订阅**串行**逐个 `load_comic_info`；`add_jm_subscription:968` 对每个目标的订阅数量没有上限。
- `plugins/jm_api.py:281-283`：`if not self.domain_refresh_attempted: self.domain_refresh_attempted = True` —— **标志位在刷新之前置位**，若 `refresh_api_domains()` 抛错，整个进程生命周期内再也不会刷新域名。

**影响**

订阅数增长后巡检耗时线性上升（最坏每本 4 域名 × 2 次 × 15s）；而域名是 JM 侧随时会变的量，一次启动抖动就会让后续所有请求都撞在失效域名上（虽有 `api_domains` 轮询兜底，但失去刷新能力）。

**最小修复**

域名刷新改为时间戳节流（如 30 分钟最多一次）；巡检加每目标订阅上限并用 `asyncio.gather` + `Semaphore` 并发。

---

## 6. P3 · 运维与体验

### P3-18 缓存 460 MB；部分目录不在清理范围

**证据**

- 实测 `plugins/download` 共 460 MB：zip 226 MB（可由图片重新生成）、图片 234 MB。
- `plugins/jmcomic_bot.py:1613`：`for base in (JM_QQ_CACHE_DIR, PIXIV_CACHE_DIR)` —— 只清理 `download/qq` 与 `download/pixiv`。
- 实测 `plugins/download/<comic_id>`（单目录约 2 MB）位于清理范围之外，属于 `download_comic`（`:2507`）写入的目录。

**最小修复**

把 `plugins/download/<id>` 纳入清理；`rglob` 与随后的 `os.walk` 合并为单次遍历，并跳过缓存根目录自身。

### P3-19 日志不轮转；面板读全文件只显示尾部

**证据**

- 实测 `logs/manager_app/nonebot.log` 已达 1 MB 且无轮转。
- `BotManagerApp.cs:1982-1986`：`ReadSharedText(path)` 读入**整个文件**，再截取最后 30000 字符。

**最小修复**

加日志轮转（按大小/天数）；面板改为从文件尾部反向读取固定字节数。

### P3-20 帮助菜单写的命令与匹配表不一致

**证据**

- `plugins/jmcomic_bot.py:236`：菜单文案 `· 看详情：123456 详情 ｜ 我的历史：最近看过什么`
- `plugins/jmcomic_bot.py:2301`：`VIEWED_HISTORY_PHRASES = ("我的历史", "最近看过", "浏览历史", "我的浏览", "看过什么", "下载历史")`
- 匹配方式为精确相等（`:3763/:3795/:3867` 的 `text in VIEWED_HISTORY_PHRASES`）。

**影响**

用户照抄菜单里的「最近看过什么」不会有任何反应。

**最小修复**

把该串加入元组，或把匹配改为「包含关键词」的子串匹配。

### P3-21 无关文件 22 MB

**证据**

仓库根目录存在与机器人无关且无人引用的内容：`_ghdesk_zh/`（22.3 MB，GitHub Desktop 汉化工具，含 `7zr.exe` 与两个 2.4–2.9 MB 的渲染脚本）、`token_monitor.py`（Ollama token 监控 + 桌面 widget）、`test_ollama_api.py`。全仓库对 `token_monitor` 的引用仅存在于其自身文件内。

**最小修复**

移出仓库或删除；同时项目当前**没有 git 仓库**，建议尽快纳入版本控制（`.gitignore` 已覆盖 `.env*`、`logs/`、`downloads/`、`plugins/download/`、`*.db`、`NapCat.Shell/`）。

### P3-22 后台任务未持引用、无优雅关闭

**证据**

`plugins/jmcomic_bot.py:1696-1701`：

```python
@driver.on_startup
async def start_background_tasks():
    asyncio.create_task(pixiv_daily_push_loop())
    asyncio.create_task(cache_prune_loop())
    asyncio.create_task(refresh_jm_endpoints_once())
    asyncio.create_task(jm_subscription_loop())
```

四个 task 未保存引用，也没有对应的 `on_shutdown` 取消逻辑。

**最小修复**

存入模块级列表并在 `on_shutdown` 中 `cancel()` + `await asyncio.gather(..., return_exceptions=True)`；或用 `TaskGroup`。

---

## 7. 健康项：这些部分工作正常，不要动

- **JM API 层**：`refresh_api_domains()` 实测 1.32s 成功，旧域名（`cdntwice` / `cdnsha` / `cdnaspa` / `cdnntr`）确实已失效，刷新后域名可用，`search_comics` 1.73s 返回结果。响应 BOM 兼容（`plugins/jm_api.py:186-196`）与图片分块还原（`:384-430`）实现正确，`.jmdecoded` 是标记文件而非图片副本，不浪费磁盘。
- **AI 层**：`DEEPSEEK_API_KEY` 有效，实测 0.87s 返回结构化意图；`plugins/llm_chat.py:207-234` 的宽容 JSON 解析（围栏/前后杂字/纯文本回退）设计稳健。
- **抓取层**：联网搜索 0.30s、B站搜索 0.65s、词典 0.06s 均实测可用。
- **后台循环的异常保护**：`jm_subscription_loop`、`cache_prune_loop`、`pixiv_daily_push_loop` 都在 `while` 内用 try/except 包裹，单次失败不会杀死循环。
- **隐私开关**：`PIXIV_COOKIE` / `PIXIV_PHPSESSID` 走 `.env.local`（已 gitignore），`.env` 中留空并附注释，密钥管理方向正确。

---

## 8. 建议的修复顺序

| 阶段 | 内容 | 目标 |
| --- | --- | --- |
| 第一步 | P0-5 → P0-1 → P0-2 → P0-3 → P0-4 | 让机器人能跑起来；并让「版本失配」这件事从此可被自动发现 |
| 第二步 | P1-6 → P1-7 | 让 `.env` 与文档描述一致，恢复可调参能力（一行改动，收益最大） |
| 第三步 | P1-8 → P1-9 → P1-10 → P1-11 → P1-12 | 消除数据丢失、隐私泄漏与费用/刷屏失控 |
| 第四步 | P2-13 → P2-14 → P2-15 | 每条消息的固定开销瘦身 |
| 第五步 | P3 全部 | 运维与仓库卫生 |

---

## 附录 A：验证命令

```bash
# .env 是否真的进入了进程环境变量（P1-6）
python -c "import bot, os; print(os.environ.get('JM_CHAT_JUDGE'))"   # 实测输出 None

# 本机 QQ build 与 NapCat 支持列表比对（P0-1）
type "C:\Program Files\Tencent\QQNT\versions\config.json"
findstr /C:"9.9.35-52892" NapCat.Shell\napcat\napcat.mjs   # 无命中 = 不支持

# Pixiv 连通性（P1 相关网络问题）
python -c "import requests; s=requests.Session(); s.trust_env=False; s.get('https://www.pixiv.net/robots.txt', timeout=10)"
```

## 附录 B：审计方法与局限

- 审计分两轮独立进行：一轮覆盖主模块 `plugins/jmcomic_bot.py`（3896 行）与 `plugins/jm_api.py`、`plugins/llm_prefs.py`；另一轮覆盖 `plugins/` 下其余 8 个模块与管理层配置。两轮结论去重后合并。
- 报告中标注「实测」的条目由审计人本机运行验证（进程环境变量探针、网络连通性、缓存体积统计、日志时间线比对）；其余条目为代码走查得出，已在正文给出准确行号，便于复核。
- 未修改被审计项目的任何文件。
- 本报告的判断基于 2026-10-12 的代码与运行状态；`.env` 各键的取值仅统计键名与是否为空，未记录任何密钥内容。
