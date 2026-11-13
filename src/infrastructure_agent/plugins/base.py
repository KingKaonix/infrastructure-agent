"""Stable contract for optional Infrastructure Agent interfaces.

Plugins are discovered through the ``infrastructure_agent.plugins``
entry-point group. The core package imports only this module so a bare
install never depends on the packages a plugin brings with it.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ServiceContext:
    """Service objects a plugin may use instead of constructing its own."""

    config: Any
    audit: Any
    discovery: Any
    ssh: Any
    deployer: Any
    optimizer: Any


class Plugin(Protocol):
    """Interface every optional plugin implements."""

    name: str
    description: str
    commands: tuple[str, ...]

    def register_cli(self, subparsers: Any) -> None:
        """Add this plugin's command parsers to the CLI."""

    async def run(self, command: str, args: argparse.Namespace, services: ServiceContext) -> int:
        """Execute a plugin command and return a process exit code."""
