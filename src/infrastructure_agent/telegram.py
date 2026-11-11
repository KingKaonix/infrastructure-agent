"""Telegram command parsing and service adapter.

This module does not depend on a Telegram SDK. A webhook/long-poll transport
can pass message text to :class:`TelegramCommandHandler`, keeping business
logic shared with the CLI and HTTP interfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import asyncio
import json


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


class TelegramBotTransport:
    """Minimal long-polling Telegram transport with chat allowlisting."""

    def __init__(self, token: str, handler: TelegramCommandHandler, *, allowed_chat_ids=()):
        if not token:
            raise ValueError("Telegram bot token is required")
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.handler = handler
        self.allowed_chat_ids = {str(value) for value in allowed_chat_ids}

    async def _call(self, method: str, **payload: Any) -> dict[str, Any]:
        import httpx

        async with httpx.AsyncClient(timeout=35) as client:
            response = await client.post(f"{self.base_url}/{method}", json=payload)
            response.raise_for_status()
            data = response.json()
            if not data.get("ok"):
                raise RuntimeError(f"Telegram API error: {data}")
            return data

    async def run(self, stop_event: asyncio.Event | None = None) -> None:
        stop_event = stop_event or asyncio.Event()
        offset = 0
        while not stop_event.is_set():
            data = await self._call(
                "getUpdates", offset=offset, timeout=25, allowed_updates=["message"]
            )
            for update in data.get("result", []):
                offset = max(offset, int(update["update_id"]) + 1)
                message = update.get("message", {})
                chat_id = str(message.get("chat", {}).get("id", ""))
                text = message.get("text", "")
                if not chat_id or not text:
                    continue
                if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
                    await self._call("sendMessage", chat_id=chat_id, text="Unauthorized chat")
                    continue
                try:
                    result = await self.handler.handle(text)
                    reply = json.dumps(result, default=str)
                except Exception as exc:
                    reply = f"Error: {exc}"
                await self._call("sendMessage", chat_id=chat_id, text=reply[:4000])
