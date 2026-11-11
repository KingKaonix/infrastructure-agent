"""Read-only host readiness checks for deploying the LAN daemon."""

from __future__ import annotations

import importlib.util
import ipaddress
import os
from pathlib import Path
from typing import Any

from .config import AgentConfig


def run_checks(config: AgentConfig | None = None) -> dict[str, Any]:
    config = config or AgentConfig()
    checks: dict[str, dict[str, Any]] = {}

    scan_range = config.get("network.scan_range", "")
    try:
        network = ipaddress.ip_network(scan_range, strict=False)
        checks["network_range"] = {
            "ok": network.prefixlen >= 16,
            "value": str(network),
            "message": "configured LAN range",
        }
    except ValueError:
        checks["network_range"] = {
            "ok": False,
            "value": scan_range,
            "message": "set network.scan_range to an explicit LAN CIDR",
        }

    known_hosts = Path(config.get("ssh.known_hosts", "~/.ssh/known_hosts")).expanduser()
    checks["ssh_known_hosts"] = {
        "ok": known_hosts.is_file(),
        "value": str(known_hosts),
        "message": "SSH host-key database exists"
        if known_hosts.is_file()
        else "missing SSH host-key database",
    }
    checks["asyncssh"] = {
        "ok": importlib.util.find_spec("asyncssh") is not None,
        "message": "asyncssh installed",
    }

    base_url = config.get("ai.base_url", "")
    model = config.get("ai.model", "")
    api_key = config.get("ai.api_key", "") or os.getenv("OPENAI_API_KEY", "")
    checks["ai_endpoint"] = {
        "ok": bool(base_url and model and api_key),
        "message": "AI endpoint, model, and key configured"
        if base_url and model and api_key
        else "set INFRA_AGENT_AI_BASE_URL, INFRA_AGENT_AI_MODEL, and OPENAI_API_KEY",
    }
    checks["telegram"] = {
        "ok": bool(os.getenv("INFRA_TELEGRAM_BOT_TOKEN")),
        "optional": True,
        "message": "Telegram token configured"
        if os.getenv("INFRA_TELEGRAM_BOT_TOKEN")
        else "optional",
    }
    state_path = Path(config.get("state.database", "state/agent.db")).expanduser()
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        writable = os.access(state_path.parent, os.W_OK)
    except OSError:
        writable = False
    checks["state"] = {
        "ok": writable,
        "value": str(state_path),
        "message": "state directory writable",
    }

    required = [name for name, check in checks.items() if not check.get("optional")]
    return {"ready": all(checks[name]["ok"] for name in required), "checks": checks}
