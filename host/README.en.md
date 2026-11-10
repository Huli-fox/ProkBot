# ProkBot Host Patch

Self-host the Grok Bot server. Requires Python 3.10+ and Docker Compose; the runtime uses Linux amd64.

[简体中文](README.md)

## Use

```sh
python3 release/build-docker.py
docker compose -f release/compose.yaml up -d
docker compose -f release/compose.yaml exec host cat /data/setup-key
```

Open `http://127.0.0.1:18080`, use the setup code to create an administrator account, configure a model and create a six-character pairing code.

For LAN access, run `export GROKBOT_LISTEN_ADDRESS=0.0.0.0` before starting Compose.

When `GROKBOT_PUBLIC_URL` points to an HTTPS gateway and administrators use another URL, explicitly list trusted management origins in `GROKBOT_ADMIN_ORIGINS` (scheme, host and port; comma-separated). For a local page reached through SSH, use `GROKBOT_ADMIN_ORIGINS=http://127.0.0.1:18080`. An additional origin must also match the request Host. Authentication and the CSRF header remain required; HTTPS management sessions keep Secure cookies. This setting does not change pairing gateway URLs or trust forwarded headers. HTTP management origins are intended for local access or a protected tunnel, not public exposure.

[Remote access, separate deployment and backups](docs/DEPLOYMENT.en.md) · [Application development](PLUGINS.en.md)

## License and support

Noncommercial use only. See [LICENSE](LICENSE). Most code in this project was generated with AI assistance.
