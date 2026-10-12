# Pixiv 登录 Cookie 获取教程

Pixiv 的 R18/R18G 作品，未登录时 `ajax/illust/{pid}` 接口不会返回图片地址，
所以机器人会提示「需要登录 Cookie」。解决办法是：**用你自己的 Pixiv 账号登录一次浏览器，
把会话 Cookie 的 `PHPSESSID` 值填进 `.env`，再重启机器人。**

> 说明：PHPSESSID 是你登录后浏览器持有的会话凭证，只能由你本人登录产生；
> 它只用于让机器人以你的登录态获取图片地址，不会获取你的密码。

## 一、获取 PHPSESSID

1. 用**电脑浏览器**（Chrome / Edge 都行）打开 https://www.pixiv.net 并**登录**你的账号。
2. 按 `F12`（或右键 → 检查）打开开发者工具。
3. 切到 **Application（应用）** 标签（Edge 可能叫「应用程序」）。
4. 左侧展开 **Cookies** → 点击 `https://www.pixiv.net`。
5. 在右侧列表里找到名为 **`PHPSESSID`** 的一行，复制它 **Value（值）** 那一列的内容
   （一串很长的数字字母，形如 `12345678_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`）。

> 找不到 Application 标签的替代办法：
> F12 → 切到 **Network（网络）** → 刷新页面 → 点任意 `www.pixiv.net` 的请求 →
> 看 **Request Headers** 里的 `Cookie:`，复制其中 `PHPSESSID=xxxx` 后面的那段值。

## 二、填入配置

打开项目根目录的 `.env`，找到这两行，**二选一**填（推荐第一种，最简单）：

```text
# 方式 A：只填 PHPSESSID 的值（不含 "PHPSESSID=" 前缀）
PIXIV_PHPSESSID=你复制的值

# 方式 B：填完整 Cookie 字符串
PIXIV_COOKIE=PHPSESSID=你复制的值
```

例：

```text
PIXIV_PHPSESSID=12345678_abcdef1234567890abcdef12345678
```

## 三、重启并验证

1. 重启 NoneBot（管理面板点「更新重启 NoneBot」，或重启机器人）。
2. 在 QQ 里发：

```text
@机器人 pixiv登录状态
```

- 显示「已登录」= 配置成功，之后 R18/R18G 请求就能正常拿到图片地址。
- 显示「Cookie 无效/未登录」= PHPSESSID 填错或已过期，重新按上面步骤提取一次。

## 四、注意事项

- **PHPSESSID 会过期**（一般几周到几个月），失效后 R18/R18G 又会提示需要登录，重新提取填入即可。
- 如果你在别处登出了 Pixiv，或改了密码，PHPSESSID 也会失效。
- 建议只填 `PIXIV_PHPSESSID` 或 `PIXIV_COOKIE` 其中一个，不要两个都填。
- 普通（非 R18）图片不受影响，不配置 Cookie 也能正常使用。
