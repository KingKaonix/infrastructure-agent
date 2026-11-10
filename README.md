# Infrastructure Agent

An always-on, AI-powered IT administrator for your machines and networks.

**Status:** 🟡 Planning phase — scaffold exists, not yet functional. See [docs/PLAN.md](docs/PLAN.md).

---

## Config decisions (locked by user)

| Decision | Value |
|----------|-------|
| AI provider | OpenAI-compatible endpoint — Omniroute server (provider-agnostic) |
| User interface | CLI + Telegram bot |
| Discovery scope | LAN only for now |
| Extensibility | Plugin system for major cloud/VM providers (AWS, GCP, DigitalOcean, etc.) — built in from Phase 1 |
| Autonomy | Full IT-admin autonomy; agent asks user only when genuinely stuck or about to do something destructive |

---

## What this is

A single agent that runs 24/7 on one machine and manages **every** machine and device on your **LAN** as your IT administrator would:

- **Discovers** all devices on LAN (via nmap/ARP/mDNS)
- **Executes** any admin command via SSH — updates, packages, services, networking, containers, GPU drivers, file transfers — same surface an IT admin has
- **Deploys** apps from a GitHub link with almost no input: clones the repo, reads it, figures out the stack, writes Docker config, deploys, verifies health
- **Optimizes** continuously: CPU, memory, disk I/O, application response time, and cost
- **Asks you** only when it's genuinely stuck or about to do something destructive

Operation is **hybrid**: a background daemon that's always looking for things to improve, plus on-demand requests from you (CLI or Telegram bot).

### Interface

- **CLI**: `infrastructure-agent` command and direct SSH execution
- **Telegram bot**: `/deploy <github_url>`, `/status`, `/optimize`, `/ssh <device> <command>`

---

## What it is NOT

- Not a multi-tenant platform — single admin (you)
- Not a replacement for your existing CI/CD — it complements it
- Not a dashboard-first product — it's CLI/chat-driven

---

## Requirements you've stated

1. All machines and devices on the network (LAN only for now)
2. Hybrid operation: background optimization + on-demand requests
3. Figures things out autonomously; asks when it needs input
4. Full IT-admin command surface via SSH
5. Tracks all performance metrics + cost
6. No access constraints — every device is available
7. Full autonomy: take over
8. Nothing pre-existing to integrate with
9. OpenAI-compatible provider (Omniroute server, extensible to any)
10. Plugin system for cloud/VM provider extensibility (future phases)
11. Telegram bot interface for remote management

---

## Architecture (target)

```
                    ┌──────────────────────────────┐
                    │   User interface (CLI / Telegram)   │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │     AI reasoning layer       │  ← LLM tool-use loop
                    │   (decides WHAT to do)       │
                    │   uses OpenAI-compatible provider │
                    └──────────────┬───────────────┘
                                   │
      ┌────────┬────────┬─────────┼─────────┬────────┐
      ▼        ▼         ▼         ▼         ▼        ▼
  Discovery  SSH     Deployer  Optimizer  State    Audit
  (nmap/ARP) (async- (Docker/  (metrics, (SQLite) (log)
              ssh)    github)   tuning)
```

### Components

1. **Network Discovery** — scans LAN for devices, identifies OS, open ports, SSH reachability. LAN-only for now; plugin system added in Phase 3+ for cloud VMs.
2. **SSH Executor** — pooled async SSH connections, key/password/token auth, command/script execution, file transfer, output streaming. This is the "any command" surface.
3. **AI Reasoning Layer** — the core. An LLM tool-use loop using OpenAI-compatible provider (Omniroute server, provider-agnostic). Reads a GitHub repo, infers the stack, and decides which SSH/Docker commands to run. Wired to CLI + Telegram bot.
4. **Deployment Engine** — installs Docker if absent, generates/adopts Dockerfile + docker-compose, builds, runs, maps ports/env/volumes, health-checks, rolls back on failure.
5. **Performance Optimizer** — periodic metric collection across all hosts. Applies safe auto-fixes: pruning unused containers, clearing caches, cleaning logs. Recommends/asks before destructive ones (restart services, downscale).
6. **State & Audit** — SQLite for inventory, configs, deployment history, optimization decisions. Append-only audit log of every command run and its result.

---

## Current state vs. target

The scaffold that exists covers rough drafts of components 1, 2, 4, 5 — but is **not importable, not installable, and has no AI layer** (component 3, the heart of the request). See `docs/PLAN.md` Phase 0 for the cleanup required before real building starts.

---

## Getting there

1. Phase 0 is done: project structure consolidated, all modules importable
2. ✅ Import test: `import infrastructure_agent; print('OK')` passes
3. ✅ CLI test: run `infrastructure-agent` and see startup message
4. Next: Phase 1 — AI reasoning layer with OpenAI-compatible provider

---

### Config reference (for future phases)

- **AI**: Omniroute server URL + API key environment variable, falls back to any OPENAI_API_KEY-compatible setup
- **Discovery**: LAN-only nmap/ARP/mDNS scans (configurable subnet). Cloud plugin interface defined in Phase 3, implementations optional.
- **Telegram**: Bot token in `config/telegram_bot_token` (or env var `INFRA_TELEGRAM_BOT_TOKEN`)
- **Plugins**: Package entry point `infrastructure.plugins` — any module exposing `discover()` / `optimize()` functions auto-loaded