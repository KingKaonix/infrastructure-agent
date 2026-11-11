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

To keep a user service running after logout and across reboot, enable systemd
lingering once (this requires administrative access):

```bash
sudo loginctl enable-linger "$USER"
loginctl show-user "$USER" -p Linger
```

Without lingering, the service remains active only while the user session is
available. A root-managed service is the alternative for unattended hosts.

For a dedicated system account, use the root service below.

From the checkout, run the installer (it requires `sudo`):

```bash
sudo deploy/install-system-service.sh "$PWD"
```

The installer creates a locked system account, a private virtual environment,
and a hardened systemd unit. It does not copy SSH private keys or API secrets;
provision those separately as the `infrastructure-agent` user.

To provision the local self-management SSH key and host verification in one
idempotent step:

```bash
sudo deploy/provision-system-credentials.sh 192.168.12.229
```

If the host already has a working OpenCode local model, the provisioning script
automatically copies only the standalone binary and its service connection
metadata into the locked service account, with the metadata kept mode 0600.
Use `--no-local-opencode` to opt out:

```bash
sudo deploy/provision-system-credentials.sh 192.168.12.229 --no-local-opencode
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

The daemon performs periodic discovery, read-only optimization observations,
and (when configured) local OpenCode or OpenAI-compatible model reviews.
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
and an unhealthy deployment rolls back. A configured OpenCode CLI or
OpenAI-compatible endpoint is required for natural-language requests and
autonomous model review; the operational CLI works without one.
