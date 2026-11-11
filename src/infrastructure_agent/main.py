"""CLI lifecycle and operational command surface."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Infrastructure Agent")
    parser.add_argument("--request", "-r", help="Natural-language request to process")
    parser.add_argument(
        "--interactive", "-i", action="store_true", help="Run an interactive session"
    )
    commands = parser.add_subparsers(dest="command")

    commands.add_parser("discover", help="Scan the configured network once")
    commands.add_parser("status", help="Show discovered devices")
    serve = commands.add_parser("serve", help="Run the FastAPI status/control service")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    commands.add_parser("telegram", help="Run the allowlisted Telegram bot transport")
    ssh = commands.add_parser("ssh", help="Execute a policy-controlled SSH command")
    ssh.add_argument("target")
    ssh.add_argument("remote_command", nargs=argparse.REMAINDER)
    ssh.add_argument("--approved", action="store_true", help="Approve a destructive command")
    deploy = commands.add_parser("deploy", help="Deploy a Git repository to a device")
    deploy.add_argument("repository")
    deploy.add_argument("target")
    optimize = commands.add_parser("optimize", help="Collect metrics and recommendations")
    optimize.add_argument("target", nargs="?")
    approve = commands.add_parser("approve", help="Record an explicit action approval")
    approve.add_argument("action")
    approve.add_argument("target", nargs="?")
    audit = commands.add_parser("audit", help="Show recent audit events")
    audit.add_argument("--limit", type=int, default=100)
    return parser


def _services():
    from infrastructure_agent.core.config import AgentConfig
    from infrastructure_agent.discovery.network_discovery import NetworkDiscovery
    from infrastructure_agent.deployment.ssh_executor import SSHExecutor
    from infrastructure_agent.deployment.deployer import Deployer
    from infrastructure_agent.optimization.performance_optimizer import PerformanceOptimizer
    from infrastructure_agent.core.audit import AuditLog

    config = AgentConfig()
    audit = AuditLog(config.get("state.database", "state/agent.db"))
    discovery = NetworkDiscovery()
    ssh = SSHExecutor(audit_log=audit, device_registry=discovery)
    return (
        config,
        audit,
        discovery,
        ssh,
        Deployer(ssh_executor=ssh),
        PerformanceOptimizer(ssh_executor=ssh),
    )


async def async_main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config, audit, discovery, ssh, deployer, optimizer = _services()
    logging.basicConfig(
        level=getattr(logging, config.get("logging.level", "INFO")),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    background: list[asyncio.Task] = []
    try:
        if args.command == "discover":
            await discovery.discover_network()
            print(json.dumps({"count": len(discovery.get_all_devices())}))
        elif args.command == "status":
            print(
                json.dumps(
                    {"devices": [d.to_dict() for d in discovery.get_all_devices().values()]},
                    indent=2,
                )
            )
        elif args.command == "serve":
            import uvicorn
            from infrastructure_agent.api import create_app

            server = uvicorn.Server(
                uvicorn.Config(
                    create_app(discovery=discovery, ssh=ssh, deployer=deployer),
                    host=args.host,
                    port=args.port,
                )
            )
            await server.serve()
        elif args.command == "telegram":
            import os
            from infrastructure_agent.telegram import TelegramBotTransport, TelegramCommandHandler

            handler = TelegramCommandHandler(
                discovery=discovery, ssh=ssh, deployer=deployer, optimizer=optimizer
            )
            token = os.getenv("INFRA_TELEGRAM_BOT_TOKEN", "")
            allowed = config.get("telegram.allowed_chat_ids", [])
            await TelegramBotTransport(token, handler, allowed_chat_ids=allowed).run()
        elif args.command == "ssh":
            if not args.remote_command:
                raise SystemExit("ssh requires a command")
            result = await ssh.execute_command(
                args.target, " ".join(args.remote_command), approved=args.approved
            )
            print(json.dumps(result.to_dict(), indent=2))
            return 0 if result.success else 1
        elif args.command == "deploy":
            result = await deployer.deploy_from_github(args.repository, args.target)
            print(json.dumps(result.to_dict(), indent=2))
            return 0 if result.success else 1
        elif args.command == "optimize":
            if args.target:
                result = await optimizer.optimize_device(args.target)
                print(json.dumps(result.to_dict(), indent=2))
            else:
                await optimizer.run_optimization_cycle()
        elif args.command == "approve":
            event_id = audit.record(
                "approval.granted",
                actor="cli",
                target=args.target or "",
                details={"action": args.action},
            )
            print(json.dumps({"approved": True, "event_id": event_id}))
        elif args.command == "audit":
            print(json.dumps(audit.list(limit=args.limit), indent=2))
        elif args.interactive or args.request:
            from infrastructure_agent.ai_layer.ai_reasoning import AIReasoningLayer

            ai_layer = AIReasoningLayer()
            if args.request:
                print(await ai_layer.process_request(args.request, deployer, ssh, discovery))
            else:
                print("Infrastructure Agent — AI reasoning mode")
                while True:
                    try:
                        request = await asyncio.to_thread(input, "> ")
                    except (EOFError, KeyboardInterrupt):
                        break
                    if request.strip().lower() in {"quit", "exit", "q"}:
                        break
                    if request.strip():
                        print(
                            await ai_layer.process_request(
                                request.strip(), deployer, ssh, discovery
                            )
                        )
        else:
            background = [
                asyncio.create_task(discovery.start_discovery()),
                asyncio.create_task(optimizer.start_periodic_checks()),
            ]
            print("Infrastructure Agent daemon running. Press Ctrl-C to stop.")
            await asyncio.gather(*background)
    finally:
        optimizer.stop()
        stop_task = discovery.stop_discovery()
        for task in background:
            task.cancel()
        if background:
            await asyncio.gather(*background, return_exceptions=True)
        await stop_task
        await ssh.close_all_connections()
    return 0


def main() -> int:
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
