"""Telegram command parsing and the shared command handler."""

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


HELP_TEXT = (
    "*Infrastructure Agent - Telegram Help*\n\n"
    "Available commands:\n\n"
    "- `/help` - Show this help message\n"
    "- `/status` - List all discovered devices on the LAN\n"
    "- `/discover` - Trigger a one-time network discovery scan\n"
    "- `/optimize <device>` - Collect metrics and recommendations for a device\n"
    "  Example: `/optimize 192.168.12.42`\n\n"
    "- `/ssh <device> <command>` - Execute a policy-controlled SSH command\n"
    "  Example: `/ssh 192.168.12.42 uptime`\n\n"
    "- `/deploy <repository> <device>` - Deploy a Git repo to a device via Docker\n"
    "  Example: `/deploy https://github.com/example/app 192.168.12.42`\n\n"
    "*Notes:*\n"
    "- Only authorized chat IDs (configured in agent config) may use the bot\n"
    "- Destructive actions require explicit approval\n"
    "- SSH commands are subject to allowlists, timeouts, and audit logging"
)


class TelegramCommandHandler:
    def __init__(self, *, discovery, ssh, deployer, optimizer):
        self.discovery = discovery
        self.ssh = ssh
        self.deployer = deployer
        self.optimizer = optimizer

    async def handle(self, text: str) -> dict[str, Any] | str:
        command = parse_command(text)
        if command.name == "/help":
            return HELP_TEXT
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
