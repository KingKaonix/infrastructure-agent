"""Explicit command safety policy; destructive commands require approval."""

from __future__ import annotations
import re
from dataclasses import dataclass

DESTRUCTIVE = (
    r"\bdocker\s+system\s+prune\b",
    r"\bsystemctl\s+(restart|stop|disable)\b",
    r"\b(apt|yum|dnf)\s+remove\b",
    r"\brm\s+-rf\b",
    r"\bmkfs\b",
)


@dataclass(frozen=True)
class CommandPolicy:
    allowed_hosts: tuple[str, ...] = ()
    require_approval_for_destructive: bool = True

    def check(self, host: str, command: str, *, approved: bool = False) -> None:
        if self.allowed_hosts and host not in self.allowed_hosts:
            raise PermissionError(f"SSH target is not allowlisted: {host}")
        if (
            self.require_approval_for_destructive
            and any(re.search(pattern, command, re.I) for pattern in DESTRUCTIVE)
            and not approved
        ):
            raise PermissionError("Destructive remote command requires explicit approval")
