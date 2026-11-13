# LAN operator runbook

This is the path from a clean host to a continuously running agent. The agent
must run on a trusted LAN host with an SSH key and `known_hosts` entries for
managed devices.

## Install as a service

Pick **one** install mode. Enabling both the user service and the system service
runs two daemons that scan the same LAN, duplicate audit writes, and multiply
SSH and model calls. Check with `systemctl is-active infrastructure-agent` and
`systemctl --user is-active infrastructure-agent`; exactly one must report
`active`.

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
key and `known_hosts`, and create `/var/lib/infrastructure-agent/agent_config.json`
with an explicit `network.scan_range`. The installer creates the environment
file but not the JSON config; without it the service runs on defaults and does
not record an explicit LAN range. Do not put API keys or passwords in the JSON
config or commit them to Git.

The service account reads its own config, so repository edits under
`config/agent_config.json` do not affect an installed system service. When the
package changes, rebuild and reinstall it into the service virtual environment
with `uv build --wheel` and `uv pip install --python
/var/lib/infrastructure-agent/.venv/bin/python --no-deps --force-reinstall`.

Run `infrastructure-agent doctor` before enabling the service. It reports the
exact missing host prerequisites without performing network or remote actions.

## Verify operation

```bash
systemctl status infrastructure-agent
systemctl --user status infrastructure-agent   # must be inactive
infrastructure-agent status
infrastructure-agent audit --limit 20
journalctl -u infrastructure-agent -f
```

### GitHub Actions on the LAN host

GitHub-hosted runners cannot reach a private LAN. Install a GitHub
self-hosted runner on the administrator host with labels `self-hosted`,
`linux`, and `lan-admin`, then grant that runner only the commands in
`deploy/infrastructure-agent-actions.sudoers.example`. The scheduled
`.github/workflows/lan-operations.yml` workflow will then run status checks
every 30 minutes and supports manual `verify` and `repair` dispatches.

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

The transport is a separate plugin package, not part of the core install:

```bash
uv pip install --no-deps -e ./plugins/telegram
systemctl --user restart infrastructure-agent   # or: sudo systemctl restart infrastructure-agent
```

Set `INFRA_TELEGRAM_BOT_TOKEN` in the service environment file and configure
`telegram.allowed_chat_ids` with the numeric operator chat IDs. An empty
allowlist accepts any chat that can reach the bot, so an allowlist is strongly
recommended. Run `infrastructure-agent plugins` to confirm the plugin is
discovered; `infrastructure-agent telegram` starts polling.

## First acceptance test

Use a disposable device or VM. Confirm that discovery records it, `ssh <host>
true` creates audit events, a Docker deployment can build and become healthy,
and an unhealthy deployment rolls back. A configured OpenCode CLI or
OpenAI-compatible endpoint is required for natural-language requests and
autonomous model review; the operational CLI works without one.
