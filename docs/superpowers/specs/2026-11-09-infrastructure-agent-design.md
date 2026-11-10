# Infrastructure Agent Design Document
**Date:** 2026-11-09  
**Topic:** AI-powered IT administrator agent for autonomous infrastructure management

## Intent and Why

Build an always-on AI agent that acts as a full IT administrator across all machines and devices on the user's network. It discovers systems, runs any admin command via SSH, deploys applications autonomously from GitHub links, and continuously optimizes performance — with minimal user input.

## Goals

1. **Discovery**: Automatically discover all machines/devices on the network (physical, cloud, IoT)
2. **Full SSH access**: Execute any IT admin command (same as an IT admin) via SSH with no constraints
3. **Autonomous deployment**: Give it a GitHub link → it figures out the stack, writes Docker configs, deploys
4. **Continuous optimization**: 24/7 performance tuning — CPU, memory, disk I/O, network latency, cost
5. **Hybrid operation**: Background monitoring + on-demand user requests
6. **Full autonomy**: The agent can restart services, modify configs, downscale resources, etc. — it takes over

## Non-Goals

- Multi-tenant platform (single admin user)
- GUI/dashboard as primary interface (CLI/chat-driven)
- Replacing existing CI/CD pipelines (agent complements them)

## Anti-Goals

- Breaking production systems without user awareness
- Requiring constant user input for routine tasks
- Being limited to only Docker or only one cloud provider

## Constraints

- All machines are available to the agent; no access constraints
- Must work with any OS on any machine
- Must handle unknown/unfamiliar application stacks autonomously
- Must be safe: log all actions, make reversible changes where possible

## Architecture (to be built)

### Core Components

1. **Network Discovery** — scans network for devices, identifies OS, open ports, SSH accessibility
2. **SSH Executor** — runs arbitrary commands via SSH on discovered hosts, streams output
3. **Application Analyzer** — reads a GitHub repo, detects stack (Node/Python/Go/etc.), generates Dockerfile/docker-compose
4. **Deployment Engine** — provisions hosts, pulls images, configures networking, health-checks
5. **Performance Optimizer** — monitors metrics, recommends/applies optimizations (restart services, tune configs, right-size resources)
6. **Autonomy Engine** — decides what to do without user input; asks user only when genuinely stuck
7. **Memory/State** — persists device inventory, configs, deployment history, optimization decisions

### Tech Stack (default, to confirm)

- **Language**: Python 3.13 (excellent SSH/automation libs, async support)
- **Orchestration**: asyncio + FastAPI (webhook endpoint for GitHub links)
- **SSH**: asyncssh or paramiko
- **Discovery**: nmap/python-nmap, ARP scanning, mDNS
- **Container**: Docker SDK for Python
- **AI**: AI SDK 7 via Vercel AI Gateway (provider-agnostic model strings)
- **Scheduling**: APScheduler for periodic optimization checks
- **Storage**: SQLite for state (lightweight, single-file)
- **Deployment target**: Any machine running Docker

### Operational Flow

1. Agent starts → discovers network → builds device inventory
2. Periodically: checks performance metrics across all devices → applies optimizations
3. User gives GitHub link → agent analyzes repo → generates Docker/deploy config → deploys → verifies health
4. User asks via chat/CLI → agent executes via SSH → reports results

## What's Left to the Builder

- Confirm tech stack choices (Python vs Node, specific libraries)
- Confirm whether a chat interface (CLI, Slack, Discord, web) is needed beyond GitHub-link deployment
- Confirm discovery scope: LAN-only, or also cloud VMs reachable via public IP
- Confirm the model/provider for AI reasoning (Vercel AI Gateway default, or direct provider)

---

This is your call to review. Say what's wrong or missing, and I'll revise before building.