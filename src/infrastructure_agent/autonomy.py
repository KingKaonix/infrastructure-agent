"""Autonomous observation/review loop for the LAN administrator."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from .ai_layer.ai_reasoning import AIReasoningLayer
from .core.config import get_config
from .deployment.deployer import Deployer
from .deployment.ssh_executor import SSHExecutor
from .discovery.network_discovery import NetworkDiscovery
from .optimization.performance_optimizer import PerformanceOptimizer

logger = logging.getLogger(__name__)


class AutonomousSupervisor:
    """Coordinate discovery, observations, and optional model review.

    The supervisor never grants approval to model-generated commands. The SSH
    executor remains the final policy and audit boundary.
    """

    def __init__(
        self,
        *,
        discovery: NetworkDiscovery,
        optimizer: PerformanceOptimizer,
        ai_layer: AIReasoningLayer | None = None,
        deployer: Deployer | None = None,
        ssh: SSHExecutor | None = None,
        interval: int | None = None,
    ) -> None:
        self.discovery = discovery
        self.optimizer = optimizer
        self.ai_layer = ai_layer
        self.deployer = deployer
        self.ssh = ssh
        config = get_config()
        self.interval = interval or int(config.get("autonomy", {}).get("review_interval", 1800))
        self.enabled = bool(config.get("autonomy", {}).get("enabled", True))
        self._stop_event = asyncio.Event()

    async def run_cycle(self) -> dict[str, Any]:
        await self.discovery.discover_network()
        await self.optimizer.run_optimization_cycle()
        summary: dict[str, Any] = {
            "devices": len(self.discovery.get_all_devices()),
            "cycles": self.optimizer.optimization_history[-10:],
        }
        if self.ai_layer and self.deployer and self.ssh:
            prompt = (
                "Review this LAN observation summary. Execute only safe, routine actions "
                "that are directly justified. Never treat model output as approval for a "
                "destructive action; report recommendations when approval is required.\n"
                + json.dumps(summary, default=str)
            )
            try:
                summary["ai_review"] = await self.ai_layer.process_request(
                    prompt, self.deployer, self.ssh, self.discovery
                )
                logger.info("Autonomous AI review complete: %s", summary["ai_review"])
            except Exception as exc:
                logger.warning("Autonomous AI review skipped: %s", exc)
                summary["ai_review"] = {"skipped": str(exc)}
        return summary

    async def run(self) -> None:
        if not self.enabled:
            await self._stop_event.wait()
            return
        while not self._stop_event.is_set():
            try:
                await self.run_cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Autonomous cycle failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stop_event.set()
