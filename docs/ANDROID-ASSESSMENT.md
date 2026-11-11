# Android 官方客户端接入自部署 Host 的可行性评估

**固定版本的 root 缓存路线已在一台 Android 11 / arm64 测试设备上完成 HTTPS 配对、会话管理及文字收发验证。** 当前交付为实验性 root + adb 工具；其他机型、官方 OTA 隔离及附件、语音、推送等仍未完成。LSPosed 原型在已测组合上不可用，保留在研究归档中。

本文记录可复现的技术依据、验证结果和限制。安装、更新与恢复步骤见 [Android 安装说明](../android/README.md)。

## 1. 已核实的应用结构

| 项目 | 实测值 |
| --- | --- |
| 包名 | `ai.x.grok.bot` |
| 版本 | `1.19.1`，versionCode `3050` |
| 设备系统及 ABI | Android 11，arm64-v8a |
| root | 缓存安装需要已授权的 root + adb |
| 安装组成 | `base.apk` 及 ABI、屏幕密度、语言配置分包 |
| JavaScript 框架 | React Native `0.86.2`，Expo SDK `57.0.0` |
| JavaScript 资源 | `assets/index.android.bundle`，23,889,920 字节 |
| 字节码 | Hermes 98；依赖标识 `hermes-android:250829098.0.16` |
| 启动保护 | `com.pairip.application.Application`、`SignatureCheck`、`libpairipcore.so`、许可检查 |
| 热更新 | Expo Updates 已启用，含代码签名证书和签名元数据 |

版本锚点：

```text
base.apk SHA-256
61f821dc88cf5939e99f9d135c57f6ef9b4aa91a916b5fab7449b20fee486e30

assets/index.android.bundle SHA-256
e4e58266c8380d6ac4696ece4f293eca872bd6dc3e470d2db33fb3d44b0f3290
```

APK 签名校验通过。上述哈希用于锁定本次输入；它不意味着已经独立核验了发行方公布的证书指纹。校验对象为嵌入包；运行时还需检查是否加载了 Expo 缓存更新。

## 2. 已定位到明确的连接入口

使用与应用完全匹配的 Hermes 官方格式定义，解析了函数表和字符串表，对全部 74,354 个函数进行了线性指令解码，未遇到指令解析失败；原 bundle 的 SHA-1 尾部校验也通过。线性解码不等同于完整反编译或全部行为验证。

关键结果不是只发现了字符串，而是核对到了以下调用关系：

1. `DevGatewayOverride.read()` 在该发布版中固定返回 `undefined`。
2. 启动构建逻辑调用该方法；当返回值存在时，调用 `enterDevGatewaySession(...)`，使用内置的 `dev-gateway@localhost` 开发会话身份。
3. 网关构建逻辑同样读取该返回值。解析路由时，存在 override 就使用其中的 `url` 和 `token`；缺省时才进入官方 `ensureSandBox` 路径。
4. HTTP RPC 组装 `/api/<method>` 路径，事件连接组装 `/events?channels=...&surface=mobile`，两者均有 Bearer 认证逻辑。

这使得“让客户端使用自部署 Host 发放的设备令牌”有具体的实现入口，无需先实现整套官方账号和云电脑分配服务。

仅适用于本次 bundle 的定位信息：

| 目标 | 函数编号 / 文件偏移 | 行为 |
| --- | --- | --- |
| `DevGatewayOverride.read` | 函数 `20928`，函数头 `251264`，原函数体 `9817452` | 4 字节：加载 undefined 并返回 |
| 会话构建 | 函数 `14960`，相关指令 `12721406` | 读取 override，随后选择开发会话分支 |
| `enterDevGatewaySession` | 函数 `15829` | 更新当前会话状态 |
| 网关构建 | 函数 `25715`，相关指令 `13615792` | 读取 override |
| 路由解析 | 函数 `68135`，相关指令 `20165731` | 从 override 读取 `url`、`token` |

原来的 4 字节函数体被 631 个函数共享。**不能直接覆盖这个共享位置。** 本次实验为目标函数分配独立函数体，仅修改其函数头指向，并更新文件长度和 SHA-1 尾部。原共享函数体保持原样。

不存在“发现隐藏链接就能直接配置 Host”的证据：本次发布版的入口读取函数已被编译成恒定 undefined。没有理由仅凭 `grokbotinternal:` 等字符串就宣称 deep link 可以启用它。

## 3. root 缓存实现与消息发送修复

在 LSPosed 对目标应用停用的情况下，工具修改应用私有 Expo 更新目录：

1. 停止应用，备份 `updates.db` 及 WAL，并通过 SQLite 生成一致快照。
2. 校验 base APK、Hermes bundle、Room schema、runtime 和嵌入更新 ID。
3. 新增本地更新及 JS 资源记录，保留嵌入更新，复用图片和字体等资源引用。
4. 将固定版本补丁写入 `.expo-internal`，由原 Expo 加载器在冷启动时读取。
5. 用进程文件映射验证补丁被加载；恢复时还原原数据库并清除工具的补丁和凭据。

该路线保留原 APK 和签名，运行时不依赖 Frida/LSPosed。

本版本的缓存配方：

| 项目 | 值 |
| --- | --- |
| runtime | `2938e8288ad0e03aa42443541b21c250fde0fa3d` |
| 原嵌入更新 | `4727f432-0be1-4c13-bad4-a8a121597e9f` |
| Room schema hash | `f2331836f27deacc936e75b3f1a360bd` |
| 工具新增更新 | `b1e722c3-9174-4be8-a05c-725b4bc75d37` |
| 工具新增文件 | `prokbot-gateway-3050.hbc` |

仅注入网关地址和令牌仍会导致发送时报“消息未送达：未登录”：`buildLive`（f25715）无条件指定要求官方账号的 BackendClient 发送器。

`gateway-send-v2` 将偏移 `13618478` 的 `DefineOwnById options.grokBotSendSource` 源寄存器从 `r24` 改为该函数中保持 undefined 的 `r1`。经 `stampSender`（f25720）传递后，`ChatSession`（f27940）选择已有的 `gateway.sendPrompt` 适配器（f55296）。指令长度、分支和共享函数体保持不变。

`refresh` 沿用原配对及恢复备份，支持从已知旧补丁更新；替换或启动失败时尝试回滚。`diagnose` 可在 APK 变化后只读报告兼容性和备份完整性，不读取设备令牌。修改操作拒绝未知 APK 和未知 Expo 更新，尚不支持跨 APK 版本自动恢复。

实现见 [root_cache.py](../android/tools/root_cache.py)、[hermes.py](../android/tools/hermes.py) 和 [expo_cache.py](../android/tools/expo_cache.py)。

## 4. Host 配对与 HTTPS

Host 已增加 Android 配对平台、设备类型及管理页名称。`POST /connect/pair` 发放设备令牌；RPC 和 SSE 使用 Bearer 认证，设备撤销后令牌失效并关闭事件连接。Android 推送尚未实现，不赋予 APNs 能力。

测试原包 target SDK 为 36，未声明明文放行或用户 CA 信任。在已测 Android 11 环境中，loopback HTTP 被拒绝，普通用户证书也不足以满足默认信任策略。优先使用系统已信任的 HTTPS；无域名时可按 [SSH 与私有 HTTPS 指南](../android/SSH-TLS.md) 配置隧道和专用 CA。

`connect --ca-cert` 仅为电脑上的配对请求指定 CA，保留证书链、地址和重定向检查。可选系统 CA 安装器仅支持 Android 11，安装前须取得设备所有者同意；其信任范围影响整台手机。手机模块只包含 CA 公共证书，CA 私钥应保存在受限目录。

管理页与配对网关使用不同 origin 时，通过 `GROKBOT_ADMIN_ORIGINS` 显式配置管理来源，并保留登录、Host 匹配和 CSRF 检查。具体配置见 [Host 说明](../host/README.md)。

## 5. 验证结果与限制

已测组合为官方 Android 1.19.1 (3050)、Android 11 / arm64 和支持 Android 配对的 Host。以下为既有验证结果：

- 缓存补丁在连续三次冷启动及前后台切换后保持映射；恢复后原应用正常启动且不再映射补丁，APK 哈希保持一致。
- 默认 `HttpsURLConnection` 使用系统 CA 完成证书链和地址校验并返回 HTTP 200；App 使用无权限探针令牌时返回预期的 401。
- 正式配对后，设置、会话列表、创建会话和事件连接可用；应用新版发送修复后，`sendPrompt` 返回 200，文字回复在 App 中显示。
- Python 测试覆盖字节码完整性、共享函数体和发送器选择、数据库一致性、配对保留、失败回滚、未知版本诊断，以及真实本地 TLS 的错误 CA、地址不匹配和跨地址重定向拒绝。
- Host 单元及 HTTP 测试覆盖平台校验、一次性配对、RPC 转发、SSE、设备撤销和管理来源校验。测试使用临时数据和模拟上游。

测试命令及原始 bundle、OpenSSL 等输入要求见 [开发验证](../android/README.md#开发验证)。缺少输入而跳过的测试不算通过。

上述结果不覆盖其他系统和机型、长期稳定性、网络切换、完整流式 UI、审批、附件、语音及远程桌面。Expo OTA 仍可能覆盖本地补丁；关闭 Play 自动更新不会阻止 Expo OTA。尚未实现官方网络和遥测隔离。

## 6. 未采用的路线

### LSPosed 对照实验

在 Android 11 / arm64、Grok Bot 1.19.1 (3050)、LSPosed 1.9.2 (7024) / API 100 的已测组合中，仅加载模块、不注册 Hook 仍会在 `libpairipcore.so + 0x5a0a8` 发生 `SIGSEGV`。单点启动探针也未解决问题，崩溃发生在 Hermes 替换和配对逻辑执行前。该结果支持早期注入冲突的判断，尚不能确定具体检测机制。

[LSPosed 研究归档](../android/research/lsposed/README.md) 默认拒绝构建，须显式选择研究标志。其 Java 配方没有新版消息发送修复，不能作为可用客户端交付。

### Frida 运行时原型

早期 Frida 原型以无权限测试令牌验证了 `/events`、`/api/getHostSettings` 和 `/api/listAgents` 的网关替换。探针仅记录方法、路径和测试令牌匹配结果，统一返回 HTTP 401，不验证正式配对或聊天。

分离后出现 `SIGBUS/BUS_ADRALN`，随后冷启动出现 PairIP `SIGSEGV`；重启后恢复。现有证据不足以确定是热重载、注入生命周期还是其他因素造成，不适合作为长期运行方案。

### 重签名与独立客户端

重签名涉及 PairIP、许可校验、多分包签名、Expo 更新签名及包名关联组件；不能直接覆盖同包名且签名不同的官方安装。独立客户端还需实现对话、审批、附件和远程桌面等完整协议与界面，均不属于当前交付。

## 7. 分发边界与参考

每台设备独立配对，设备令牌仅在电脑内存和手机私有目录处理。生成的 HBC 含令牌，不能与 `connection.json` 或应用数据一起公开分发。官方 APK、原始 bundle、私钥、数据库快照及原始诊断日志应保存在忽略目录中，不进入提交。

Hermes 格式参考来自官方仓库的 [`hermes-v250829098.0.16`](https://github.com/facebook/hermes/tree/hermes-v250829098.0.16/include/hermes/BCGen/HBC) 标签。线性指令解码不等于完整反编译；PairIP 内部行为未完整恢复。iOS 与 Android 即使使用相同 HBC 版本，也不能通用函数编号、偏移和版本校验。
