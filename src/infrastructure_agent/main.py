"""CLI lifecycle. Importing this module has no runtime side effects."""

from __future__ import annotations
import argparse
import asyncio
import logging
import sys
from typing import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Infrastructure Agent")
    parser.add_argument("--request", "-r", help="Natural-language request to process")
    parser.add_argument(
        "--interactive", "-i", action="store_true", help="Run an interactive session"
    )
    return parser


async def async_main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from infrastructure_agent.core.config import AgentConfig
    from infrastructure_agent.discovery.network_discovery import NetworkDiscovery
    from infrastructure_agent.deployment.ssh_executor import SSHExecutor
    from infrastructure_agent.deployment.deployer import Deployer
    from infrastructure_agent.optimization.performance_optimizer import PerformanceOptimizer
    from infrastructure_agent.ai_layer.ai_reasoning import AIReasoningLayer

    config = AgentConfig()
    logging.basicConfig(
        level=getattr(logging, config.get("logging.level", "INFO")),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ssh = SSHExecutor()
    discovery = NetworkDiscovery()
    deployer = Deployer(ssh_executor=ssh)
    optimizer = PerformanceOptimizer(ssh_executor=ssh)
    ai_layer = AIReasoningLayer()
    tasks = [
        asyncio.create_task(optimizer.start_periodic_checks()),
        asyncio.create_task(discovery.start_discovery()),
    ]
    try:
        if args.interactive:
            print("Infrastructure Agent — AI reasoning mode")
            while True:
                try:
                    request = await asyncio.to_thread(input, "> ")
                except (EOFError, KeyboardInterrupt):
                    break
                if request.strip().lower() in {"quit", "exit", "q"}:
                    break
                if request.strip():
                    print(await ai_layer.process_request(request.strip(), deployer, ssh, discovery))
        elif args.request:
            print(await ai_layer.process_request(args.request, deployer, ssh, discovery))
        else:
            await asyncio.Event().wait()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await ssh.close_all_connections()
    return 0


def main() -> int:
    """Synchronous console-script entry point."""
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
