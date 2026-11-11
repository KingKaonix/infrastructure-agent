"""Append-only SQLite audit trail for actions and outcomes."""

from __future__ import annotations
from pathlib import Path
from typing import Any

from .state import StateRepository


class AuditLog:
    def __init__(self, path: str | Path = "state/agent.db"):
        self.path = Path(path).expanduser().resolve()
        self.repository = StateRepository(self.path)

    def record(
        self,
        action: str,
        *,
        actor: str = "system",
        target: str = "",
        outcome: str = "started",
        details: Any = None,
    ) -> int:
        details_dict = details if isinstance(details, dict) else {"value": details}
        return self.repository.record_audit_event(
            str(details_dict.get("command", "")),
            device_ip=target,
            result=outcome,
            actor=actor,
            action=action,
            outcome=outcome,
            details=details_dict,
        )

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent events without exposing secrets from command output."""
        rows = self.repository.list_audit_events()
        return rows[-max(1, min(limit, 1000)) :][::-1]
