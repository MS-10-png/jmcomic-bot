# OneBot 客户端配置说明

当前项目的漫画插件运行在 NoneBot 里，NoneBot 监听端口是 `8081`。

QQ 登录端请优先使用 NapCatQQ 或 Lagrange.OneBot，不建议继续使用旧版 go-cqhttp。

当前 Lagrange 签名地址使用：

```text
https://sign.lagrangecore.org/api/sign/30366
```

## 连接地址

在 NapCatQQ 或 Lagrange.OneBot 中配置反向 WebSocket，地址填：

```text
ws://127.0.0.1:8081/onebot/v11/ws
```

如果客户端拆成 Host / Port / Suffix 三项填写：

```text
Host: 127.0.0.1
Port: 8081
Suffix: /onebot/v11/ws
```

AccessToken 留空，因为当前项目 `.env` 和 OneBot 配置里没有设置 token。

## 启动顺序

1. 双击 `一键启动QQ漫画机器人.bat`（会同时拉起 NoneBot 和 NapCat；只想跑 NoneBot 核心可双击 `QQ_Bot.bat`），等待 NoneBot 启动完成。
2. 启动 NapCatQQ 或 Lagrange.OneBot。
3. 在客户端中登录 QQ。
4. 配置反向 WebSocket 到上面的地址。
5. 看到客户端提示 WebSocket 已连接后，在 QQ 里测试：

```text
@机器人 123456 封面
@机器人 123456 20页
@机器人 123456
```

## go-cqhttp 的 Code 45

如果 go-cqhttp 出现 `Code: 45`、`QQ版本过低`、`配置 SignServer`，说明 QQ 服务器拒绝了旧协议/旧签名。

这不是漫画插件问题，也不是二维码扫错了。继续重试通常没用，推荐换 NapCatQQ 或 Lagrange.OneBot。
