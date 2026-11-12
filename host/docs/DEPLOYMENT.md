# 部署与备份

## 构建

需要 Python 3.10+、Docker 和 Compose。支持 Linux x86_64；Apple Silicon 可以构建 amd64 镜像。

```sh
python3 release/build-docker.py --host-archive /path/to/sand-host-bundle-d0a4baa.tgz
docker compose -f release/compose.yaml up -d
```

省略 `--host-archive` 时从固定来源下载。离线 Box 归档使用 `--box-archive /path/to/box.tar.gz`；构建工具校验后设置本地标签 `grokbot-box-input:9d2ac1b`，Compose 直接使用该镜像。原始资源严格校验，版本见 `recipes/host/manifest.json` 和 `release/build-docker.py`。

打开 `http://127.0.0.1:18080`，读取初始化码并设置管理员密码：

```sh
docker compose -f release/compose.yaml exec host cat /data/setup-key
```

在管理页配置模型，生成六位配对码，再从客户端连接。局域网部署可设置 `GROKBOT_LISTEN_ADDRESS=0.0.0.0`；端口由 `GROKBOT_PUBLIC_PORT` 设置。需要公网访问时使用 HTTPS 反向代理或启用 Tailcat。

## 数据与更新

Compose 持久保存 `host-data`、`box-home`、`box-workspace` 三个卷。备份工具暂停正在运行的容器，保存卷与摘要后恢复运行。恢复到一个新的 Compose 项目，不覆盖现有卷：

```sh
python3 release/backup.py backup --project grokbot --directory backups/2026-10-21 --image grokbot-host:local
python3 release/backup.py restore --project grokbot-restored --directory backups/2026-10-21 --image grokbot-host:local
docker compose -p grokbot-restored -f release/compose.yaml up -d
```

恢复时使用备份对应的镜像。恢复实例与原实例共享同一身份，切换前停止原实例。

## 独立执行电脑与插件

只部署 Host 使用 `release/compose.host.yaml`。另外一台电脑部署执行节点：

```sh
python3 release/build-docker.py --box-only
# 设置至少 32 位随机 GROKBOT_NODE_TOKEN；离线镜像可在上条命令增加 --box-archive
docker compose -f release/compose.execution.yaml up -d --build
```

在 Host 管理页填写执行节点地址和密钥。局域网可设置 `GROKBOT_NODE_LISTEN_ADDRESS=0.0.0.0`，端口默认 18443；启用内嵌网络使用 `GROKBOT_TAILCAT_ENABLED=1`，高级选项为 `GROKBOT_TAILCAT_RELAY` 和 `GROKBOT_TAILCAT_DERP_MAP_URL`。

应用统一在管理页导入、配置和导出分享。代码应用直接运行在现有执行电脑上，无需额外容器。

包格式、授权、附带技能见 [应用开发](../PLUGINS.md)。

`release/patch-host.py --archive ORIGINAL --output NEW_DIRECTORY` 可单独生成 Host 文件并记录补丁耗时。生成过程仅执行固定字节复制与新增规则，不调用 AI 或反编译软件。

## 仅使用远程 MCP，无自带 Box

构建包含 `GROKBOT_BOX_DISABLED` 支持的 Host 后，可使用 `release/compose.mcp.yaml`。沿用已有项目名以复用 Host 数据卷：

```sh
docker compose -p grokbot -f release/compose.yaml stop box
docker compose -p grokbot -f release/compose.mcp.yaml up -d host
```

此模式支持文字对话和管理页“应用”中的远程 HTTP/SSE MCP。原生 Box 的电脑、Shell、文件读写、桌面预览、本地 stdio MCP、代码应用、Box 文件库及技能同步不可用；附带本地文件的消息会明确报错。停用状态不会把执行回退到 Host 文件系统。原 Box 数据卷保留；切回原 Compose 配置即可恢复。

例如 Simular Box 应添加为远程应用：地址 `https://mcp.box.simular.ai/mcp`，协议 `Streamable HTTP`，认证 `Bearer Token`。在服务商的 Personal Keys 页面创建密钥后，通过 Host 管理页授权。MCP 服务地址不属于本项目的 `grokbot-execution/v1` 执行节点协议，不能填入执行节点地址。服务商 MCP 自己的文件和桌面能力取决于其授权及提供的工具。

### 外接 Box 的能力与提示词

设置 `GROKBOT_BOX_DISABLED=1` 后，Host 自动为主 Agent、精简提示词、自动任务及动态执行环境生成外接 MCP 指引。无需手动覆盖管理页的默认提示词。编码任务可以使用外接机器的命令和文件工具；只有实际发现已连接 Mac 的 Codex 工具且任务适合在该 Mac 上进行时，才使用 Mac 路径。

可以同时安装 Simular 和 InstaBox 等多个远程应用。Bot 会发现当次可用工具，按用户指定的服务和机器执行；未指定时沿用当前任务已确认的目标，目标有歧义时先确认。不同服务的机器 ID、会话和文件路径不能混用。仅有 `exec` 和文件工具的服务不会被当作拥有桌面工具，内置 `computerUse`/`browserUse` 也不会因此接管外接机器。

“内置能力”页同时显示保存的开关偏好和实际适用状态。仅外接模式下，原生浏览器子 Agent、浏览器交互表单、登录状态导入、通行密钥转发和演示任务不会生效；远程应用工具独立工作。普通聊天提问不依赖交互表单。没有在线桌面执行器时，不再向模型提供 `ExternalShell`、`ExternalRead` 等用户电脑工具；后来连接的桌面可在后续回合恢复对应工具。

Host 继续保存记忆、资料和自动任务，通过已有的 Host 工具修改。它们不会被挂载到外接机器。外接机器上的文件也不会因回复一个 `file://` 路径就自动传到手机：需要服务商实际提供的下载/导出能力，或直接在聊天中交付少量文本。

已有提示词编辑记录和对话保留。升级后会出现新的默认提示词变体；旧变体的自定义编辑不会自动迁移到新变体。需要保留的个性化规则可在“提示词”页对照后迁移，运行时的执行环境限制始终以实际能力为准。代码更新需重新构建并应用 Host 镜像；不需要重新配对或重启手机。

验证适配时，可先用 `release/patch-host.py` 从支持的原始包生成 seed，再将 `GROKBOT_TEST_RECOVERED_DIR` 指向生成的 `seed/release-reliability`，运行 `node --test tests/external-box*.test.mjs tests/disabled-box.test.mjs`。持久化及 HTTP 测试需要 Linux；在已准备好的 Host Linux 镜像内设置 `GROKBOT_TEST_FULL_RUNTIME=1` 可同时验证完整运行时工厂安装。验证不需要调用模型或远程 MCP 服务。
