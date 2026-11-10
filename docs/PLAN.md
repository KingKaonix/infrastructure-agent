# Infrastructure Agent — Plan

## Config decisions (locked)

| Decision | Value |
|----------|-------|
| AI provider | OpenAI-compatible endpoint — Omniroute server (must work with any OpenAI-compatible provider) |
| User interface | CLI + Telegram bot |
| Discovery scope | LAN only for now |
| Extensibility | Plugin system for major cloud/VM providers (AWS, GCP, DigitalOcean, etc.) — built in from Phase 1 |
| Autonomy | Full IT-admin autonomy; agent asks user only when genuinely stuck or about to do something destructive |

---

## Phase 0: Fix Project Structure (now)

The source files currently live in `/home/kaos/netgear/infrastructure_agent/` but the primary entry point and documentation are in `/home/kaos/netgear/infrastructure-agent/`. This leads to import failures and confusion.

### Goals

1. Consolidate into **one coherent source tree**.
2. Make the package importable (pip installable and runnable).
3. Fix broken imports (e.g., `from infrastructure_agent.core.config import ...`).
4. Remove duplicate/conflicting metadata (pyproject.toml, setup.py).

### Steps

| Step | Action | Why | Artifacts |
|------|--------|-----|------------|
| 0.1 | Choose the main directory (`infrastructure-agent` wins as CLI-facing, `infrastructure_agent` wins as code) | The `infrastructure-agent` contains `run.py` and the `docs/` tree; `infrastructure_agent` contains the actual source. Merge into one logical package. | Unified directory structure |
| 0.2 | Move all source files from `infrastructure_agent/` into `infrastructure-agent/src/infrastructure_agent/` | Set up a conventional Python package structure that pip/setuptools can recognize. | `src/infrastructure_agent/` with all modules |
| 0.3 | Rewrite `pyproject.toml` and `setup.py` to use a **single, canonical** entry point. | Remove conflicting metadata and provide a clean CLI interface. | Updated `pyproject.toml`/`setup.py` with `infrastructure-agent.main:main` entry point. |
| 0.4 | Update imports in all source files to be relative to the new package root (e.g., `from .core.config import ...`). | Fix broken imports that prevent the package from loading. | Working imports across the entire codebase. |
| 0.5 | Create a `main.py` in `src/infrastructure_agent/` as the real entrypoint (with async event loop). | Provide a runnable CLI entry point for the agent. | `src/infrastructure_agent/main.py` that calls existing `agent.main()` or a new orchestrator. |
| 0.6 | Run a dry import test to confirm the package imports correctly. | Validate that the package is now functional. | `python -c "import infrastructure_agent; print('OK')"` passes. |
| 0.7 | Update README.md and any documentation referencing the old structure. | Keep documentation in sync with code. | Updated README with correct paths and commands. |

---

## Phase 1: AI Reasoning Layer (once Phase 0 is done)

Build the heart of the agent: an LLM tool-use loop that:

- Receives a GitHub link (via CLI or Telegram bot)
- Clones the repo and analyzes the stack (framework, language, build/start commands)
- Looks at existing configuration (Dockerfile, docker-compose.yml, package.json, etc.)
- Writes safe deployment configs if missing (Dockerfile, docker-compose.yml)
- Generates a sequence of Docker commands via the SSH executor (including `docker build`, `docker compose up -d`, health-checks, cleanup)
- Executes those commands on the target device(s) and streams output back
- Returns a structured result to the user

### Deliverables

- `ai_layer.py` (in `src/infrastructure_agent/ai_layer/`)
- OpenAI-compatible client wrapper (Omniroute endpoint, provider-agnostic so any OpenAI-compatible API works)
- Tools for reasoning: `analyze_repo`, `generate_deployment_plan`, `execute_plan`
- Plugin skeleton for cloud/VM provider discovery (interface defined here, implementations later)
- Integration with the existing `Deployer` class to avoid duplication
- A small CLI surface + Telegram bot interface (`/deploy` POST with `{github_url, target_device_ip}`)

---

## Phase 2: State & Audit System

Add persistent state across restarts:

- SQLite database (`.infrastructure_agent.db`) with tables for devices, deployments, optimizations, audit logs
- Schema for devices: `id, ip, hostname, os, open_ports, ssh_available, discovered_at`
- Schema for deployments: `id, github_url, target_device_ip, status, container_id, start_time`
- Schema for audit logs: `id, timestamp, device_ip, command, result, execution_time`

---

## Phase 3: Enhanced Discovery

- Replace the manual `nmap` calls with `python-nmap` async wrappers.
- Add multi-format discovery: `mDNS` for local network services.
- Plugin system for cloud/VM provider discovery (AWS, GCP, DigitalOcean, etc.) — plugins are optional, LAN-only works standalone.
- Discover container instances on devices (Docker/Podman) and track them.

---

## Phase 4: Improved SSH Layer

- SSH connection pooling with health checks.
- Key exchange via SSH key, password, or tokens.
- Retry logic with exponential backoff.
- File transfer utilities (SFTP via asyncssh).
- Command streaming for real-time progress.

---

## Phase 5: Optimization Engine

- Continuous monitoring across devices (CPU, memory, I/O, network).
- Safe auto-fixes: pruning unused containers, clearing caches, cleaning logs.
- Recommendations for larger changes: restart services, update packages, resize resources.
- Rate limiting to avoid performance impact.

---

## Phase 6: CLI + Telegram Bot Interface

- Simple terminal interface for issuing commands to specific devices.
- Telegram bot for remote management: `/deploy <github_url>`, `/status`, `/optimize`, `/ssh <device> <command>`
- Health endpoint (`/health`) for monitoring and external integration.

---

## Metrics & Acceptance

- **Import test**: `import infrastructure_agent; print('OK')` passes.
- **CLI test**: Run `infrastructure-agent` and see the startup message.
- **Discovery test**: Manually run a network scan (or simulate the environment) and verify devices are found.
- **SSH test**: On a device with SSH, run a simple command (`uptime`).
- **Deployment test**: Clone a simple repo (like hello-world) and deploy to a device.
- **Telegram test**: Bot responds to `/deploy <github_url>` and returns structured result.
- **OpenAI test**: Agent successfully reasons through a deployment using the Omniroute endpoint.

---

## Costs & Resources

- **Time**: 3–5 days to get a functional prototype with Phases 0–1.
- **Compute**: For running the agent and testing on devices.
- **Storage**: A few GB for cloning repos and building images.
- **GPU**: Not required — this is a tool orchestrator, not model training.
- **Network**: Agent needs LAN access for nmap scans and SSH connections.

---

## How to proceed

1. **Phase 0** must be done first — the codebase cannot be built until imports and structure are fixed.
2. We can do Phase 0 incrementally: fix imports first, then package, then CLI.
3. I will inform you before moving to the next phase.
4. If you want to skip or reorder phases, let me know, but Phase 0 is foundational.

---

**Goal**: A working, importable Infrastructure Agent that you can run and test with real machines/devices (or a simulated environment), ready for Phase 1 AI reasoning and autonomous deployment via OpenAI-compatible provider, CLI, and Telegram bot.