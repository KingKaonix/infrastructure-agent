# Infrastructure Agent

Infrastructure Agent is a Python 3.12+ CLI for safely managing Docker workloads and SSH-accessible devices on a LAN. It combines bounded network discovery, policy-controlled remote execution, repository analysis, deployment health checks, optimization recommendations, and an append-only SQLite audit trail.

> **Status:** early foundation release. Packaging, the CLI lifecycle, safety boundaries, deployment pipeline, and validation suite are working; Telegram, cloud plugins, and a production AI tool-use adapter are planned work.

## What is implemented

- Installable `src/` package with the `infrastructure-agent` console command.
- Import-safe CLI: `--help` does not create logs, config files, network tasks, or connections.
- SSH with `known_hosts` verification, key/password authentication, bounded retries, timeouts, target allowlists, and command auditing.
- Explicit command policy: destructive actions such as Docker prune, service stop/restart, package removal, `rm -rf`, and filesystem formatting require approval.
- Repository analysis and Docker deployment with unique remote directories, source checkout, build/start health checks, and rollback on failure.
- LAN discovery with explicit ranges, concurrency limits, per-host timeouts, cancellation, and bounded inventory behavior.
- Read-only-by-default performance observations using machine-readable metrics. Cleanup is recommendation-only unless explicitly approved.
- SQLite audit records for remote actions and outcomes.
- GitHub Actions on pushes, pull requests, manual runs, and a weekly scheduled validation.

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
```

The AI reasoning adapter is optional at runtime. Configure an OpenAI-compatible endpoint through environment variables before using natural-language requests:

```bash
export OPENAI_API_KEY="..."
export INFRA_AGENT_AI_BASE_URL="https://your-endpoint.example/v1"
export INFRA_AGENT_AI_MODEL="your-model"
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

## Development

```bash
uv pip install -e '.[dev]'
ruff format --check src tests
ruff check src tests
mypy src
pytest -q
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

## Roadmap

1. Expand SQLite inventory and persisted deployment/optimization history.
2. Add a production-ready OpenAI-compatible tool-use adapter with approval propagation.
3. Add FastAPI health/status endpoints.
4. Add Telegram commands through the shared service layer.
5. Add cloud/provider plugins after the LAN inventory contract is stable.
