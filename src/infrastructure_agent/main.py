#!/usr/bin/env python3
"""Main entry point for Infrastructure Agent"""

import asyncio
import argparse
import logging
import sys
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(os.path.dirname(__file__), '..', '..', 'logs', 'agent.log'))
    ]
)

# Import core modules
from infrastructure_agent.core.config import AgentConfig, get_config
from infrastructure_agent.discovery.network_discovery import NetworkDiscovery
from infrastructure_agent.deployment.ssh_executor import SSHExecutor
from infrastructure_agent.deployment.deployer import Deployer
from infrastructure_agent.optimization.performance_optimizer import PerformanceOptimizer
from infrastructure_agent.ai_layer.ai_reasoning import AIReasoningLayer

logging.info("Infrastructure Agent starting...")

# Load configuration
config = AgentConfig()

# Initialize core components
network_discovery = NetworkDiscovery()
ssh_executor = SSHExecutor()
deployer = Deployer(ssh_executor=ssh_executor)
optimizer = PerformanceOptimizer(ssh_executor=ssh_executor)
ai_layer = AIReasoningLayer()

logging.info("Infrastructure Agent components initialized")


async def process_ai_request(user_input: str) -> str:
    """Route a natural-language request through the AI reasoning layer."""
    return await ai_layer.process_request(
        user_input, deployer, ssh_executor, network_discovery
    )


async def interactive_cli():
    """Interactive CLI: type natural-language requests, AI decides what to do."""
    print("Infrastructure Agent — AI reasoning mode")
    print("Type a request (e.g. 'deploy https://github.com/user/repo to 192.168.1.50')")
    print("Type 'quit' or 'exit' to leave.\n")
    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break
        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye.")
            break
        print("---")
        response = await process_ai_request(user_input)
        print(response)
        print("---")


async def main():
    """Main entry point for the agent"""
    parser = argparse.ArgumentParser(description="Infrastructure Agent")
    parser.add_argument(
        "--request", "-r",
        help="A single natural-language request to process via the AI layer",
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Run an interactive CLI session with the AI reasoning layer",
    )
    args = parser.parse_args()

    # Start background optimization loop
    asyncio.create_task(optimizer.start_periodic_checks())

    # Start network discovery
    asyncio.create_task(network_discovery.start_discovery())

    if args.interactive:
        await interactive_cli()
    elif args.request:
        response = await process_ai_request(args.request)
        print(response)
    else:
        # Main event loop (background daemon mode)
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logging.info("Shutting down agent...")

    network_discovery.stop_discovery()
    await ssh_executor.close_all_connections()
    logging.info("Agent stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.exception(f"Fatal error: {e}")
        sys.exit(1)
