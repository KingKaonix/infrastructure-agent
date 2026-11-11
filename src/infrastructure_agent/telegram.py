"""Telegram command parsing and service adapter.

This module does not depend on a Telegram SDK. A webhook/long-poll transport
can pass message text to :class:`TelegramCommandHandler`, keeping business
logic shared with the CLI and HTTP interfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TelegramCommand:
    name: str
    arguments: tuple[str, ...]


def parse_command(text: str) -> TelegramCommand:
    parts = text.strip().split()
    if not parts or not parts[0].startswith("/"):
        raise ValueError("Expected a Telegram command")
    return TelegramCommand(parts[0].split("@", 1)[0].lower(), tuple(parts[1:]))


class TelegramCommandHandler:
    def __init__(self, *, discovery, ssh, deployer, optimizer):
        self.discovery = discovery
        self.ssh = ssh
        self.deployer = deployer
        self.optimizer = optimizer

    async def handle(self, text: str) -> dict[str, Any]:
        command = parse_command(text)
        if command.name == "/status":
            devices = self.discovery.get_all_devices()
            return {"ok": True, "devices": [device.to_dict() for device in devices.values()]}
        if command.name == "/discover":
            await self.discovery.discover_network()
            return {"ok": True, "count": len(self.discovery.get_all_devices())}
        if command.name == "/optimize":
            if len(command.arguments) != 1:
                raise ValueError("Usage: /optimize <device>")
            return (await self.optimizer.optimize_device(command.arguments[0])).to_dict()
        if command.name == "/ssh":
            if len(command.arguments) < 2:
                raise ValueError("Usage: /ssh <device> <command>")
            result = await self.ssh.execute_command(
                command.arguments[0], " ".join(command.arguments[1:])
            )
            return result.to_dict()
        if command.name == "/deploy":
            if len(command.arguments) != 2:
                raise ValueError("Usage: /deploy <repository> <device>")
            return (await self.deployer.deploy_from_github(*command.arguments)).to_dict()
        raise ValueError(f"Unknown command: {command.name}")
