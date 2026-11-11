# LAN operator runbook

This is the path from a clean host to a continuously running agent. The agent
must run on a trusted LAN host with an SSH key and `known_hosts` entries for
managed devices.

## Install as a service

For a non-root install in a user session:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/infrastructure-agent-user.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now infrastructure-agent
```

For a dedicated system account, use the root service below.

```bash
sudo useradd --system --home /var/lib/infrastructure-agent infrastructure-agent
sudo install -d -o infrastructure-agent -g infrastructure-agent /var/lib/infrastructure-agent
sudo python -m pip install --prefix /usr/local .
sudo install -d -m 0750 /etc/infrastructure-agent
sudo install -o root -g infrastructure-agent -m 0640 deploy/agent.env.example /etc/infrastructure-agent/agent.env
sudo install -o root -g root -m 0644 deploy/infrastructure-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now infrastructure-agent
```

Before starting, edit `/etc/infrastructure-agent/agent.env`, provision the SSH
key and `known_hosts`, and set an explicit LAN CIDR in the agent config. Do not
put API keys or passwords in the JSON config or commit them to Git.

Run `infrastructure-agent doctor` before enabling the service. It reports the
exact missing host prerequisites without performing network or remote actions.

## Verify operation

```bash
systemctl status infrastructure-agent
infrastructure-agent status
infrastructure-agent audit --limit 20
journalctl -u infrastructure-agent -f
```

The daemon performs periodic discovery and read-only optimization observations.
Destructive commands remain blocked until an operator explicitly approves them.

## Optional status API

Run the API separately on localhost or behind an authenticated reverse proxy:

```bash
infrastructure-agent serve --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/status
```

Do not expose the control API directly to an untrusted network without adding
authentication and TLS at the proxy layer.

## Optional Telegram transport

Set `INFRA_TELEGRAM_BOT_TOKEN` and configure `telegram.allowed_chat_ids` with
the numeric operator chat IDs, then run `infrastructure-agent telegram`. An
empty allowlist accepts any chat that can reach the bot, so an allowlist is
strongly recommended.

## First acceptance test

Use a disposable device or VM. Confirm that discovery records it, `ssh <host>
true` creates audit events, a Docker deployment can build and become healthy,
and an unhealthy deployment rolls back. A live model endpoint is required only
for natural-language requests; the operational CLI works without one.
