# Android root 接入（实验性）

**简体中文** · [English](README.en.md)

让已安装的官方 Grok Bot Android App 连接自部署 Host。工具通过 root + adb 修改应用私有 Expo 缓存，保留原 APK 和签名；不输出可直接侧载的修改版 APK。每台手机使用自己的配对码和设备令牌。

已在一台 Android 11 / arm64 测试设备上完成 HTTPS 配对、会话列表与创建、文字发送及回复显示。支持范围仍是固定版本下的实验接入；其他系统版本和机型尚未验收。

## 准备条件

| 项目 | 要求 |
| --- | --- |
| 官方 App | `ai.x.grok.bot`，`1.19.1 (3050)`；工具校验 base APK 与嵌入 Hermes 98 bundle 的 SHA-256 |
| 手机 | 已 root、adb 已授权，App 安装在主用户（user 0）且能够正常打开 |
| 电脑 | Python 3.10+、Android platform-tools（adb） |
| Host | 从包含本功能的源码构建部署，已配置可用模型；旧镜像不接受 `platform: android` |
| 网络 | 手机与电脑都能访问同一个 HTTPS origin；手机信任该证书 |

请先关闭该 App 的 Google Play 自动更新，并在 LSPosed 中取消 Grok Bot 的模块作用域。在已测设备与应用组合上，即使 LSPosed 模块不注册 Hook，也会在 PairIP 内闪退。工具不会替你更改 LSPosed 配置，也不会重启手机。

优先使用手机系统已信任的 HTTPS 证书。有域名和可信 HTTPS 时不需要安装额外 CA；没有域名时，可参考 [Termius + 私有 HTTPS](SSH-TLS.md)。仅安装普通 Android 用户证书不一定能满足这个原包的信任策略。

固定输入哈希见 [hermes.py](tools/hermes.py)。若商店已提供新版本，或者本地已有未知 Expo 更新，工具会拒绝套用此配方；不要跳过哈希或数据库校验。

## 首次安装与配对

先按 [Host 部署指南](../host/docs/DEPLOYMENT.md)部署当前源码，配置模型与 `GROKBOT_PUBLIC_URL`。该值须等于手机和电脑使用的 HTTPS origin，例如 `https://bot.example.com`，不带 `/admin`、`/api` 或 `/v1`。

在手机上正常打开官方 App 一次，让它建立更新数据库；无需登录官方账号。从仓库根目录执行以下命令（adb 在 PATH 时可直接填 `adb`）：

```sh
adb devices
python android/tools/root_cache.py --adb adb diagnose
```

首次安装没有本工具的备份是正常的。确认版本匹配和 root 已授权后，在 Host 管理页“设备与通知”生成新的六位配对码，再执行：

```sh
python android/tools/root_cache.py --adb adb connect --host https://bot.example.com --name "Android phone"
```

配对码在终端交互输入，不进入命令行历史。多台设备连接时，在子命令前加 `--serial <adb序列号>`。私有 CA 的电脑端配对请求可加 `--ca-cert <CA.pem>`；它只改变该请求的信任，不安装手机证书。

安装器会停止 App、备份并校验 Expo 数据库，生成补丁、写入手机私有目录并冷启动验证。初次缓存未被选择时最多再冷启动一次。出现 `installed: true` 与 `patchedBundleMapped: true` 表示补丁已加载，接着完成实际聊天验收：

1. 打开 App，确认能看到 Host 上的 Bot，或者创建一个测试 Bot。
2. 发送“请只回复 ANDROID_HOST_OK，不调用工具、不操作文件。”。
3. 确认收到回复，再退出会话并重新打开，检查历史消息。

模型调用会使用你配置的供应商额度。安装器不会自动发送聊天或操作 Bot。`getHostSettings`、`listAgents` 和 `/events` 接通不足以单独证明模型回复正常。

## 日常检查与补丁更新

```sh
python android/tools/root_cache.py --adb adb status
python android/tools/root_cache.py --adb adb diagnose
python android/tools/root_cache.py --adb adb refresh
```

- `status` 检查受支持版本的运行状态、补丁映射和备份是否存在。
- `diagnose` 只读输出 APK 版本/哈希、补丁映射及恢复备份校验结果；即使 APK 已升级也能诊断。它不读取或输出设备令牌，`supported` 仅表示 APK 与当前配方匹配。
- `refresh` 更新已知的旧补丁，沿用现有配对和原恢复备份，保留当前 Expo 数据库其他记录。无需重新生成配对码；可处理本次“消息未送达：未登录”的发送路径修复。写入或启动失败时，会尝试恢复到更新前的缓存。

`gateway-send-v2` 除注入网关地址和令牌外，还让会话使用 App 内置的 `gateway.sendPrompt`。原发布版即使选择了开发网关，仍会指定要求官方账号的 BackendClient 发送器。

## 退出、升级与故障恢复

在**仍运行受支持的原 APK**时，退出此实验的步骤为：

1. 在 Host 管理页撤销这台设备，断开事件连接并使令牌失效。
2. 执行 `python android/tools/root_cache.py --adb adb restore`。
3. 确认 `restored: true`，再执行 `status`，应不再映射本工具的补丁。之后才升级官方 App。

`restore` 还原安装时保存的 Expo 数据库，并清除本工具的凭据、补丁和备份；它不会删除 Host 会话，也不会替代服务端撤销。若仅需升级补丁，使用 `refresh`，不要先 `restore`。

| 情况 | 处理 |
| --- | --- |
| `patchedBundleMapped: false` | 先正常停止并重开 App，再查 `status`；若仍未加载，运行 `diagnose` 并保存输出 |
| 配对返回 401 | 新安装使用未过期且未使用的配对码；如果安装器已留下备份，先按提示恢复并在管理页检查是否有已发放设备 |
| App 报“未登录” | 已安装早期网关补丁时执行 `refresh`；确认加载 `gateway-send-v2` 后重新发送 |
| TLS 或连接失败 | 检查 HTTPS 地址、证书和手机隧道；电脑能访问不等于手机能访问 |
| `Unknown cached update` | 停止安装/更新，保留现有数据库与备份供检查；`refresh` 不会覆盖未知 OTA 更新 |
| APK 已升级或哈希改变 | 先用 `diagnose` 保存版本与备份状态，在 Host 撤销设备；停止使用此配方，交由维护者评估新 runtime/schema 的迁移或清理方案 |

**当前不支持跨 APK 版本自动恢复。** `connect`、`refresh`、`restore` 都会拒绝未知版本，避免把旧数据库写入新 App。不要通过删库、清除 App 数据或强制修改版本校验“修复”；这些操作可能失去恢复点。失去 USB 连接或写入中断时，保留手机私有目录和错误输出，再诊断恢复状态。

## 可分享的内容与当前边界

可以分享仓库源码、工具和说明；其他使用者自行准备支持的官方 App，并独立配对。设备令牌和含令牌的 HBC 仅在电脑内存及手机私有目录处理，临时电脑文件只用于数据库快照。**不要分发手机上的 `connection.json`、修改后 HBC 或整份 App 数据。** 官方 APK、原始 bundle、签名材料、私有 CA 密钥和个人部署记录不进入提交。

- 已验证：固定版本的安装/恢复、HTTPS 配对、会话管理、发送请求到达 Host、文字回复在 App 显示。
- 尚未验收：其他手机/系统、长时间稳定性、网络切换、完整流式刷新行为、审批、附件、语音和远程桌面。
- Android 后台推送未实现；Host 对 Android 设备不赋予 APNs 能力。
- Expo 官方 OTA 仍可能覆盖补丁；关闭 Play 自动更新不会阻止 Expo OTA。尚未实现官方网络和遥测隔离，不能套用 Mac/iOS 的“已关闭自动更新和遥测”结论。
- 使用 Termius 时需保持隧道运行，并避免它被系统省电策略终止。

已知不可用的 LSPosed 原型保存在 [research/lsposed](research/lsposed/README.md)，不是安装入口，Java 旧配方也不包含消息发送修复。技术依据与验证范围见 [Android 评估](../docs/ANDROID-ASSESSMENT.md)。

## 开发验证

```sh
python -m unittest discover -s android/tests -p 'test_*.py' -v
node --test host/tests/android-pairing.test.mjs host/tests/admin-origin.test.mjs
# 安装 Host 依赖的 Linux 环境，或由当前源码构建的隔离 Host 镜像内：
node --test host/tests/android-http.test.mjs host/tests/admin-origin-http.test.mjs
```

在运行 Python 测试前，将 `PROKBOT_TEST_BUNDLE` 环境变量设为本地提取的原始 `index.android.bundle` 绝对路径；OpenSSL 不在 PATH 时设置 `PROKBOT_TEST_OPENSSL`。例如 PowerShell 中用 `$env:PROKBOT_TEST_BUNDLE = 'C:\private\index.android.bundle'`。缺少这些输入的相关测试会明确跳过，不能把跳过算成通过。

测试覆盖输入完整性、共享函数体保留、发送器选择、Expo 资源外键、旧配对保留、部分替换及启动失败的回滚、未知版本诊断与恢复拒绝，以及真实本地 TLS 的证书/地址/重定向校验。Host HTTP 测试使用临时数据和模拟上游，不访问生产模型或用户会话。
