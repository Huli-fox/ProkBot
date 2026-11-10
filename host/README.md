# ProkBot Host Patch

自建 Grok Bot 服务端。需要 Python 3.10+、Docker Compose，运行架构为 Linux amd64。

[English](README.en.md)

## 使用

```sh
python3 release/build-docker.py
docker compose -f release/compose.yaml up -d
docker compose -f release/compose.yaml exec host cat /data/setup-key
```

打开 `http://127.0.0.1:18080`，用初始化码设置管理员账号，配置模型并生成六位配对码。

需要局域网访问时，先设置 `export GROKBOT_LISTEN_ADDRESS=0.0.0.0`，再运行 Compose。

若 `GROKBOT_PUBLIC_URL` 指向 HTTPS 网关，但管理页通过另一个地址访问，可用 `GROKBOT_ADMIN_ORIGINS` 显式列出可信管理来源（完整协议、主机、端口，多个值用逗号分隔）。例如通过 SSH 隧道保留本地管理页时设置 `GROKBOT_ADMIN_ORIGINS=http://127.0.0.1:18080`。额外来源还必须与请求的 Host 一致，管理操作仍要求登录和 CSRF 请求头；HTTPS 管理会话仍使用 Secure Cookie。此选项不改变配对返回的网关地址，不自动信任代理头。HTTP 管理来源只适用于本机或受保护的隧道，不能代替公网 HTTPS。

[远程访问、分开部署与备份](docs/DEPLOYMENT.md) · [应用开发](PLUGINS.md)

## 许可与支持

仅限非商业使用，见 [LICENSE](LICENSE)。本项目多数代码由 AI 辅助生成。
