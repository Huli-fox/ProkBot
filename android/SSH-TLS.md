# 通过 Termius 私有 SSH 隧道连接

这是无域名接入的可选方案：Host HTTP 监听服务器 `127.0.0.1:18080`，HTTPS 代理只监听 `127.0.0.1:18443`，手机通过 Termius 转发访问。已在 Android 11 真机验证默认 TLS、官方 App 的 HTTPS 配对及文字回复。该原包没有声明用户 CA 信任，且实测拒绝 loopback HTTP；有系统已信任的公网 HTTPS 时无需本方案的私有 CA。

## 连接路径

```text
Grok Bot → https://127.0.0.1:18443（手机）
         → Termius 本地端口转发 → SSH
         → https://127.0.0.1:18443（服务器的 HTTPS 代理）
         → http://127.0.0.1:18080（现有 Host）
```

手机和服务器的 `127.0.0.1` 各指本机，通过 SSH 转发相连。服务器只需原有 SSH 入口，不需要公开 Host HTTP/HTTPS 端口。Termius 必须保持连接；隧道断开或被手机后台管理终止后，客户端会断线。

## 证书与服务端配置

准备专用私有 CA 和由其签发的服务器证书。叶证书需包含 `subjectAltName=IP:127.0.0.1`，可另含 `DNS:localhost`，并带有 `serverAuth` 用途。CA 私钥单独保管；服务器使用叶证书私钥，手机只需要 CA 公共证书。私钥及生成物应位于忽略目录或受限的运维目录，不进入源码或可分发 APK。

HTTPS 代理模板见 [nginx.conf](ssh-tls/nginx.conf)。模板监听服务器 `127.0.0.1:18443`，转发到原 Host，并为 SSE 关闭响应缓冲、支持 WebSocket Upgrade。新环境需先准备 nginx，检查已有站点和端口；启用代理前确认没有因默认站点额外暴露公网 HTTP/HTTPS。

[prepare_ssh_tls.py](tools/prepare_ssh_tls.py) 生成专用 CA、带正确 SAN 的服务器证书及仅含公共 CA 的 Magisk 安装包。输出目录必须不存在，Windows ACL 会限制为运行账户与 SYSTEM；由独立沙箱账户执行时，可用 `--owner-sid` 保留运维账户访问权。CA 有效期 10 年，服务器证书有效期 1 年，需在到期前续签并重载代理。生成脚本不部署或安装证书。

在电脑仓库根目录执行（OpenSSL 不在 PATH 时加 `--openssl <路径>`）：

```sh
python android/tools/prepare_ssh_tls.py --output output.noindex/android-ssh-tls
```

通过自己的 SSH 连接部署下列文件。模板使用 `/opt/prokbot`，不同部署目录需同步调整 nginx 配置：

| 电脑文件 | 服务器位置 | 权限 |
| --- | --- | --- |
| `output.noindex/android-ssh-tls/server-chain.pem` | `/opt/prokbot/ssh-tls/server-chain.pem` | root 所有，644 |
| `output.noindex/android-ssh-tls/private/server-key.pem` | `/opt/prokbot/ssh-tls/server-key.pem` | root 所有，600 |
| `android/ssh-tls/nginx.conf` | `/etc/nginx/conf.d/prokbot-ssh.conf` | root 所有，644 |

服务器证书目录设为 root 所有、700。CA 私钥 `private/ca-key.pem` 不上传服务器或手机。先执行 `sudo nginx -t`，通过后启用或重载 nginx，并用 `sudo ss -lntp` 核对 `18443` 仅绑定 loopback。按服务器的服务管理方式启用 nginx 开机启动。

Host 的 `.env` 需设置：

```dotenv
GROKBOT_PUBLIC_URL=https://127.0.0.1:18443
# 若还通过本地 HTTP 隧道使用管理页：
GROKBOT_ADMIN_ORIGINS=http://127.0.0.1:18080,http://localhost:18080
```

这会改变 Host 对配对客户端公布的地址，适用于使用同一转发端口的设备。沿用当前 Compose 项目和数据卷重建 Host 以加载环境变量。代理的 `X-Forwarded-Proto` 本身不足以让当前 Host 返回 HTTPS 网关地址。

`GROKBOT_ADMIN_ORIGINS` 需要使用包含管理来源修复的 Host 镜像。它只允许显式列出的管理来源且请求 Host 必须匹配，登录与 CSRF 检查保留；手机配对仍返回上方 HTTPS 地址。HTTP 管理入口仅适用于本机或受保护的 SSH 隧道。

## 手机信任

普通 Android 用户证书安装不足以满足这个原包的默认信任策略。当前方案是在已 root 的 Android 11 上安装可卸载的 Magisk 系统证书模块，只包含本次 CA 的公共证书及模块元数据，不注册 LSPosed Hook。模块 ID 为 `prokbot_ssh_ca`，显示名称为 `ProkBot SSH CA`。

**系统证书信任会影响整台手机，不仅是 Grok Bot。安装前须向用户说明并取得确认。** 私有 CA 签发的证书仍需通过地址、有效期和证书链校验；不能将其描述为仅对 Grok Bot 生效的信任。不要启用“信任所有用户证书”或关闭 TLS 校验来替代这个步骤。

手机所有者同意增加这份系统信任后，执行：

```sh
python android/tools/install_ssh_ca.py --adb adb --directory output.noindex/android-ssh-tls
```

[install_ssh_ca.py](tools/install_ssh_ca.py) 校验安装包和 Android 版本，调用 Magisk 暂存模块并核实证书校验和，输出 `phone-install.json`；它不会发起重启。安装成功后等待用户手动重启，再验证系统 CA 是否实际出现在目标应用可见的证书目录中。已有同名模块或证书路径时工具拒绝覆盖；不要重新生成 CA 来升级已有证书。

需核实 Magisk 的挂载/排除配置是否让目标应用可见该证书，并在实际 HTTPS 握手后再宣布可用。根据 Magisk 的安装流程可能需要用户重启手机。撤销时卸载该证书模块并按需重启；同时在 Host 管理页撤销测试设备，使用 `root_cache.py restore` 恢复本工具修改的 Expo 缓存。

## Termius 转发字段

| 字段 | 值 |
| --- | --- |
| 类型 | Local / 本地转发 |
| SSH Host | 用户现有的服务器连接 |
| 本地绑定地址 | `127.0.0.1`（如有此字段） |
| 本地端口 | `18443` |
| 目标地址 | `127.0.0.1`，由 SSH 服务器连接 |
| 目标端口 | `18443` |

将转发限制为手机 loopback，不启用面向局域网的共享监听。此配置需等服务器 HTTPS 入口和手机证书就绪后才能访问。

电脑也需要自己的转发，配对脚本无法通过手机的 loopback 直接访问 Host。把 `user@your-server` 换成自己的服务器连接，以下命令保持前台运行：

```sh
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L 127.0.0.1:18443:127.0.0.1:18443 -L 127.0.0.1:18080:127.0.0.1:18080 user@your-server
```

在另一个电脑终端验证证书及健康状态（Windows 可使用 `curl.exe`）：

```sh
curl --cacert output.noindex/android-ssh-tls/ca.pem https://127.0.0.1:18443/healthz
```

应得到 `"ok":true`，不使用跳过证书校验的选项。这个命令不修改电脑系统信任。其他使用者应使用自己的服务器与 CA，仓库不包含个人部署脚本、SSH 密钥或证书生成物。

## 电脑配对

电脑同时建立 `127.0.0.1:18443` 到服务器 `127.0.0.1:18443` 的 SSH 转发。此前的 `18080` 隧道可继续用于管理页；两个转发用途不同。通过 `--ca-cert` 让这一条配对请求信任专用 CA：

```powershell
python android/tools/root_cache.py --adb '路径/adb.exe' connect `
  --host https://127.0.0.1:18443 `
  --ca-cert 'output.noindex/android-ssh-tls/ca.pem' `
  --name 'Android phone'
```

配对码仍交互输入。此参数只控制电脑上该工具的 TLS 上下文，不安装电脑或手机系统证书，不关闭证书链或地址校验。返回网关必须与 `--host` 完全同源；跨地址重定向仍被拒绝。

## 验收范围

先验证手机信任正确证书，再按 [README](README.md) 完成独立配对和一条文字回复验收。HTTP 200 或浏览器手动继续访问不能代替证书与聊天验证。此 HTTPS 接入不解决 Expo OTA 覆盖补丁、附件、推送或语音支持。

开发验证曾使用默认 `HttpsURLConnection` 探针，从 `AndroidCAStore` 找到系统 CA，证书链及地址校验后返回 HTTP 200，服务端证书指纹与部署相符。探针源码见 [TlsProbe.java](probes/TlsProbe.java)，不覆盖信任管理器或地址校验器。Python 本地 TLS 测试另覆盖错误 CA、地址不匹配和跨地址重定向的拒绝行为。

高级诊断可在未配对的 App 使用 `root_cache.py probe --host https://127.0.0.1:18443` 注入无权限令牌，App 请求预期返回 401。探针后先 `restore`，再正式配对；已配对手机不应为测试 TLS 而重装探针。正式配对与 `gateway-send-v2` 安装后，已验证 App 的 `sendPrompt` 返回 200 且显示文字回复。

续签服务器证书时保留原 CA，重新签发包含相同 SAN、`serverAuth` 用途的叶证书；替换服务器证书/私钥后先验证 `nginx -t`，再重载并完成 HTTPS 健康检查。只换叶证书通常不需要更换手机 CA。私有 CA 到期或撤销时需安排替换手机信任，重启仍由用户手动执行。
