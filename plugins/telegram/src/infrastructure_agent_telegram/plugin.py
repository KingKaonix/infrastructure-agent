"""Entry point that exposes the Telegram transport as an optional plugin."""

from __future__ import annotations

import argparse
import os
from typing import Any

from infrastructure_agent.plugins.base import ServiceContext

from .handler import TelegramCommandHandler
from .transport import TelegramBotTransport


class TelegramPlugin:
    name = "telegram"
    description = "Allowlisted Telegram bot transport"
    commands = ("telegram",)

    def register_cli(self, subparsers: Any) -> None:
        subparsers.add_parser(
            "telegram",
            help="Run the allowlisted Telegram bot transport (optional plugin)",
        )

    async def run(self, command: str, args: argparse.Namespace, services: ServiceContext) -> int:
        if command != "telegram":
            raise SystemExit(f"Unsupported command: {command}")
        token = os.getenv("INFRA_TELEGRAM_BOT_TOKEN", "")
        if not token:
            raise SystemExit("INFRA_TELEGRAM_BOT_TOKEN is required for the Telegram plugin")
        handler = TelegramCommandHandler(
            discovery=services.discovery,
            ssh=services.ssh,
            deployer=services.deployer,
            optimizer=services.optimizer,
        )
        allowed = services.config.get("telegram.allowed_chat_ids", [])
        await TelegramBotTransport(token, handler, allowed_chat_ids=allowed).run()
        return 0


plugin = TelegramPlugin()
