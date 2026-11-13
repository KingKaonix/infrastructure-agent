# Infrastructure Agent

Infrastructure Agent is a Python 3.12+ CLI for safely managing Docker workloads and SSH-accessible devices on a LAN. It combines bounded network discovery, policy-controlled remote execution, repository analysis, deployment health checks, optimization recommendations, and an append-only SQLite audit trail.

> **Status:** early operational release. Packaging, the CLI lifecycle, safety boundaries, deployment pipeline, SQLite state, OpenAI-compatible tool dispatch, and validation suite are working. The Telegram transport ships as an optional plugin package.

## What is implemented

- Installable `src/` package with the `infrastructure-agent` console command.
- Import-safe CLI: `--help` does not create logs, config files, network tasks, or connections.
- SSH with `known_hosts` verification, key/password authentication, bounded retries, timeouts, target allowlists, and command auditing.
- Explicit command policy: destructive actions such as Docker prune, service stop/restart, package removal, `rm -rf`, and filesystem formatting require approval.
- Repository analysis and Docker deployment with unique remote directories, source checkout, build/start health checks, and rollback on failure.
- LAN discovery with explicit ranges, concurrency limits, per-host timeouts, cancellation, and bounded inventory behavior.
- Read-only-by-default performance observations using machine-readable metrics. Cleanup is recommendation-only unless explicitly approved.
- Autonomous supervisor cycles that discover devices, collect observations, persist results, and optionally ask the configured model to review them.
- SQLite audit records for remote actions and outcomes.
- GitHub Actions on pushes, pull requests, manual runs, and a weekly scheduled validation.
- A systemd unit and LAN operator runbook for running the daemon continuously.

## Install

Requires Python 3.12 or newer.

```bash
python -m pip install .
# Development tools and tests:
python -m pip install -e '.[dev]'
```

For an isolated development environment, [uv](https://docs.astral.sh/uv/) works well:

```bash
uv venv
uv pip install -e '.[dev]'
```

## Run

```bash
infrastructure-agent --help
infrastructure-agent --request "show the status of 192.168.1.20"
infrastructure-agent --interactive
infrastructure-agent discover
infrastructure-agent status
infrastructure-agent doctor
infrastructure-agent ssh 192.168.1.20 uptime
infrastructure-agent deploy https://github.com/example/app 192.168.1.20
infrastructure-agent optimize 192.168.1.20
infrastructure-agent audit --limit 25
infrastructure-agent serve --host 127.0.0.1 --port 8000
infrastructure-agent plugins
```

`telegram` is not part of the core install. It appears in `--help` only after
installing the optional plugin described below.

The AI reasoning adapter is optional at runtime. Configure an OpenAI-compatible endpoint through environment variables before using natural-language requests:

```bash
export OPENAI_API_KEY="..."
export INFRA_AGENT_AI_BASE_URL="https://your-endpoint.example/v1"
export INFRA_AGENT_AI_MODEL="your-model"
export INFRA_TELEGRAM_BOT_TOKEN="..."
```

For a host that already runs OpenCode, the agent can use its configured local
models without storing another provider key:

```bash
export INFRA_AGENT_AI_PROVIDER="opencode_cli"
export INFRA_AGENT_AI_MODEL="opencode/beam-free"
export INFRA_AGENT_OPENCODE_BIN="/path/to/opencode"
```

No secret is written to JSON configuration. SSH credentials and host verification can be configured with `INFRA_AGENT_SSH_USERNAME`, `INFRA_AGENT_SSH_KEY`, and `INFRA_AGENT_SSH_KNOWN_HOSTS`.

## Configuration and state

Configuration is read from `config/agent_config.json` by default, or from `INFRA_AGENT_CONFIG`. Missing configuration is kept in memory and is not created during import. Runtime state and audit data are stored under `state/` when components are initialized.

Important defaults:

- Discovery does not scan all RFC1918 space. Set an explicit `network.scan_range` or `network.allowed_subnets`.
- SSH host-key verification uses `~/.ssh/known_hosts` by default.
- Destructive optimization and cleanup are disabled by default.
- Remote commands are audited with actor, target, action, outcome, and details.

Never commit API keys, passwords, private keys, or other credentials.

## Optional plugins

Interfaces that need extra dependencies ship as separate packages that register
through the `infrastructure_agent.plugins` entry-point group. The core CLI never
imports them, so a bare install stays dependency-light.

```bash
uv pip install --no-deps -e ./plugins/telegram
infrastructure-agent plugins
export INFRA_TELEGRAM_BOT_TOKEN="..."
infrastructure-agent telegram
```

Installed plugins add their commands to `--help`. A plugin that fails to import
is logged and skipped; it cannot prevent the core CLI from starting. Removing the
package removes the command again.

## Development

```bash
uv pip install -e '.[dev]'
uv pip install --no-deps -e ./plugins/telegram
ruff format --check src tests plugins
ruff check src tests plugins
mypy src
pytest -q
pytest -q plugins/telegram
```

Tests use fake/local boundaries and do not require a real LAN, SSH host, Docker daemon, GitHub repository, or model endpoint.

## Architecture

```text
CLI
 ├─ configuration and lifecycle
 ├─ discovery ──────── inventory/state
 ├─ SSH executor ───── policy + audit
 ├─ deployer ────────── source/build/health/rollback
 └─ optimizer ──────── observation/recommendation
```

The CLI is the supported interface today. Future interfaces should call these same service boundaries rather than duplicate SSH or deployment logic.

## HTTP and Telegram adapters

The thin FastAPI adapter is created with `infrastructure_agent.api.create_app()` and exposes:

- `GET /health`
- `GET /status`
- `POST /ssh` with `{ "target", "command", "approved" }`
- `POST /deploy` with `{ "repository", "target" }`

`plugins/telegram` provides `infrastructure_agent_telegram.TelegramCommandHandler`
and the allowlisted long-polling transport behind `infrastructure-agent telegram`.
Both reuse the core discovery, SSH, deployment, and optimization services, so
command policy and audit behavior stay identical to the CLI. See
[docs/RUNBOOK.md](docs/RUNBOOK.md) for continuous-host installation.

## Roadmap

1. Publish the plugin contract as a documented, versioned interface for cloud providers.
2. Add richer discovery backends (ARP, mDNS, and optional nmap adapters).
3. Run live model, SSH, Docker, and LAN acceptance tests on a disposable lab device.
4. Add cloud/provider plugins after the LAN inventory contract is stable.
