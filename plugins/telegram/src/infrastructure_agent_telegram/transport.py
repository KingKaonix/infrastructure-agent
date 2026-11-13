"""Minimal long-polling Telegram transport with chat allowlisting."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from .handler import TelegramCommandHandler


def compact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop unset optional fields instead of sending JSON null to Telegram."""
    return {key: value for key, value in payload.items() if value is not None}


class TelegramBotTransport:
    def __init__(self, token: str, handler: TelegramCommandHandler, *, allowed_chat_ids=()):
        if not token:
            raise ValueError("Telegram bot token is required")
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.handler = handler
        self.allowed_chat_ids = {str(value) for value in allowed_chat_ids}

    async def _call(self, method: str, **payload: Any) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=35) as client:
            response = await client.post(f"{self.base_url}/{method}", json=compact_payload(payload))
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
                    if isinstance(result, str):
                        reply, parse_mode = result, "Markdown"
                    else:
                        reply, parse_mode = json.dumps(result, default=str), None
                except Exception as exc:
                    reply, parse_mode = f"Error: {exc}", None
                await self._call(
                    "sendMessage",
                    chat_id=chat_id,
                    text=reply[:4000],
                    parse_mode=parse_mode,
                )
