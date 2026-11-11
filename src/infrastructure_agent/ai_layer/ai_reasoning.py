#!/usr/bin/env python3
"""
AI reasoning layer for Infrastructure Agent

Uses the `ai` library (v0.9.0) with an OpenAI-compatible provider (Omniroute
server) for LLM-powered decision making. Provides a tool-use loop where the
LLM decides WHAT to do and the code (Deployer, SSH executor, network
discovery) executes it.

Tools exposed to the LLM:
  - analyze_github_repository: clone + detect stack of a GitHub repo
  - generate_deployment_config: produce Dockerfile/docker-compose from analysis
  - deploy_to_device: deploy a Docker app to a target device via SSH
  - discover_network_devices: scan the LAN for discoverable devices
  - execute_ssh_command: run an arbitrary command on a remote device
"""

import json
import logging
from typing import Dict, List, Any, Optional

try:
    from ai import (
        Agent,
        Model,
        Tool,
        Context,
        user_message,
        assistant_message,
        system_message,
        text_part,
        tool_message,
        tool_result_part,
        tool,
    )
    from ai.providers import OpenAICompatibleProvider
    from ai.types.messages import ToolCallPart, ToolResultPart
    from ai.types.events import ToolStart, ToolEnd, TextStart, TextEnd, ToolCallResult
except ImportError:  # The optional reasoning adapter must not break CLI/imports.
    Agent = Model = Tool = Context = None
    user_message = assistant_message = system_message = text_part = tool_message = (
        tool_result_part
    ) = tool = None
    OpenAICompatibleProvider = ToolCallPart = ToolResultPart = ToolStart = ToolEnd = TextStart = (
        TextEnd
    ) = ToolCallResult = None

from ..core.config import get_config
from ..deployment.deployer import Deployer, DeploymentResult
from ..deployment.ssh_executor import SSHExecutor, SSHResult
from ..discovery.network_discovery import NetworkDiscovery

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AIReasoningLayer:
    """AI reasoning layer that uses an OpenAI-compatible provider for decisions.

    The LLM decides what actions to take; this class wires those decisions to
    the Deployer, SSH executor, and network discovery components. Implements
    the `ai` library tool-use loop via Agent.run().
    """

    def __init__(self):
        self.config = get_config()
        ai_config = self.config.get("ai", {})
        self.provider = ai_config.get("provider", "openai_compatible")
        self.base_url = ai_config.get("base_url", "") or ""
        self.api_key = ai_config.get("api_key", "") or ""
        self.model_id = ai_config.get("model", "") or ""

        # Components wired at process_request time (avoids circular construction)
        self._deployer: Optional[Deployer] = None
        self._ssh_executor: Optional[SSHExecutor] = None
        self._network_discovery: Optional[NetworkDiscovery] = None

    # ------------------------------------------------------------------ setup

    def wire(
        self,
        deployer: Deployer,
        ssh_executor: SSHExecutor,
        network_discovery: NetworkDiscovery,
    ) -> None:
        """Wire the execution components the AI layer's tools delegate to."""
        self._deployer = deployer
        self._ssh_executor = ssh_executor
        self._network_discovery = network_discovery

    def _build_model(self) -> Model:
        """Construct a Model backed by the OpenAI-compatible provider."""
        if Model is None:
            raise RuntimeError(
                "AI reasoning adapter is not installed; install the optional AI extra"
            )
        if not self.model_id:
            raise RuntimeError(
                "AI model not configured. Set ai.model in config/agent_config.json "
                "(e.g. via OMNIROUTE_MODEL env var or edit the config file)."
            )
        if not self.base_url:
            raise RuntimeError(
                "AI base_url not configured. Set ai.base_url in config/agent_config.json "
                "(your Omniroute server URL)."
            )
        if not self.api_key:
            raise RuntimeError(
                "AI api_key not configured. Set ai.api_key in config/agent_config.json "
                "(your Omniroute API key)."
            )

        provider = OpenAICompatibleProvider(
            name=self.provider,
            default_base_url=self.base_url,
            api_key_value=self.api_key,
        )
        return Model(id=self.model_id, provider=provider)

    def _build_agent(self) -> Agent:
        """Build an Agent whose tools delegate to the wired components."""
        if Agent is None:
            raise RuntimeError(
                "AI reasoning adapter is not installed; install the optional AI extra"
            )
        deployer = self._deployer
        ssh = self._ssh_executor
        discovery = self._network_discovery

        if deployer is None or ssh is None or discovery is None:
            raise RuntimeError(
                "AIReasoningLayer not wired. Call wire(deployer, ssh, discovery) first."
            )

        # ------------------------------------------------------------------ tools

        @tool
        async def analyze_github_repository(github_url: str) -> Dict[str, Any]:
            """Analyze a GitHub repository to detect its stack and generate
            initial Docker configuration. Returns stack/language info plus
            paths to any existing Dockerfile/docker-compose.yml."""
            logger.info(f"AI tool: analyze_github_repository({github_url})")
            result = await deployer.analyze_repository(github_url)
            return {
                "success": result.success,
                "analysis": json.loads(result.stdout) if result.success and result.stdout else {},
                "error": result.stderr if not result.success else "",
            }

        @tool
        async def generate_deployment_config(repo_analysis: Dict[str, Any]) -> Dict[str, Any]:
            """Generate a Dockerfile and docker-compose.yml from a repository
            analysis. Returns the file contents plus build/start commands.
            Accepts either the full result dict from analyze_github_repository
            (which has an "analysis" key) or just the analysis sub-dict."""
            logger.info("AI tool: generate_deployment_config()")
            # Accept either the full result dict or just the analysis sub-dict
            analysis = (
                repo_analysis.get("analysis", repo_analysis)
                if isinstance(repo_analysis, dict)
                else repo_analysis
            )

            docker_config = await deployer.generate_docker_config(
                SSHResult(success=True, stdout=json.dumps(analysis))
            )
            return {
                "success": True,
                "dockerfile": docker_config.get("dockerfile", ""),
                "docker_compose": docker_config.get("docker_compose", ""),
                "language": docker_config.get("language", "unknown"),
                "build_command": docker_config.get("build_command"),
                "start_command": docker_config.get("start_command"),
            }

        @tool
        async def deploy_to_device(device_ip: str, docker_config: Dict[str, Any]) -> Dict[str, Any]:
            """Deploy a Docker application (described by docker_config) to a
            target device via SSH. Returns success/failure and health-check
            status."""
            logger.info(f"AI tool: deploy_to_device({device_ip})")
            result: DeploymentResult = await deployer.deploy_to_device(device_ip, docker_config)
            return result.to_dict()

        @tool
        async def discover_network_devices() -> Dict[str, Any]:
            """Scan the LAN for discoverable devices. Returns a list of
            device dicts with ip, hostname, os, open_ports, ssh_available."""
            logger.info("AI tool: discover_network_devices()")
            await discovery.discover_network()
            devices = discovery.get_all_devices()
            return {
                "success": True,
                "devices": [d.to_dict() for d in devices.values()],
                "count": len(devices),
            }

        @tool
        async def execute_ssh_command(device_ip: str, command: str) -> Dict[str, Any]:
            """Execute an arbitrary command on a remote device via SSH.
            Returns success, stdout, stderr, and exit code."""
            logger.info(f"AI tool: execute_ssh_command({device_ip}, {command})")
            result: SSHResult = await ssh.execute_command(device_ip, command)
            return result.to_dict()

        return Agent(
            tools=[
                analyze_github_repository,
                generate_deployment_config,
                deploy_to_device,
                discover_network_devices,
                execute_ssh_command,
            ]
        )

    # ------------------------------------------------------------------ main entry

    async def process_request(
        self,
        user_input: str,
        deployer: Deployer,
        ssh_executor: SSHExecutor,
        network_discovery: NetworkDiscovery,
    ) -> str:
        """Process a natural-language request through the AI tool-use loop.

        The LLM decides what to do (which tools to call, with what arguments);
        this method runs the loop, executes tool results, and returns the
        assistant's final text response.
        """
        self.wire(deployer, ssh_executor, network_discovery)

        model = self._build_model()
        agent = self._build_agent()

        messages: List = [user_message(text_part(user_input))]

        logger.info(f"Starting AI reasoning loop for: {user_input[:120]}")

        final_text_parts: List[str] = []
        tool_calls_made: List[str] = []

        try:
            async with agent.run(model, messages) as stream:
                async for event in stream:
                    if isinstance(event, ToolStart):
                        tool_calls_made.append(getattr(event, "tool_name", "unknown"))
                        logger.info(f"AI tool call: {event.tool_name}")
                    elif isinstance(event, ToolEnd):
                        logger.info(f"AI tool completed: {getattr(event, 'tool_name', 'unknown')}")
                    elif isinstance(event, TextStart):
                        pass  # streaming text, handled via final messages
                    elif isinstance(event, ToolCallResult):
                        # Tool execution result — logged; fed back to model automatically
                        pass

                # Extract the final assistant message text from the conversation
                for msg in reversed(stream.messages):
                    if msg.role == "assistant":
                        for part in msg.parts:
                            if hasattr(part, "text") and part.text:
                                final_text_parts.append(part.text)
                        break

        except Exception as e:
            logger.exception(f"AI reasoning loop failed: {e}")
            return f"AI reasoning failed: {e}"

        if not final_text_parts:
            if tool_calls_made:
                return (
                    "I executed the following tools on your behalf: "
                    + ", ".join(tool_calls_made)
                    + ". Please check the logs for detailed results."
                )
            return "I wasn't able to produce a response. Please check the logs."

        response = "\n".join(final_text_parts)
        if tool_calls_made:
            response += f"\n\nTools used: {', '.join(tool_calls_made)}"
        return response

    # ------------------------------------------------------------------ convenience wrappers (direct, no AI)

    async def analyze_repository(self, github_url: str) -> Dict[str, Any]:
        """Direct (non-AI) repository analysis via the Deployer."""
        if self._deployer is None:
            self._deployer = Deployer(ssh_executor=self._ssh_executor)
        result = await self._deployer.analyze_repository(github_url)
        return {
            "success": result.success,
            "analysis": json.loads(result.stdout) if result.success and result.stdout else {},
            "error": result.stderr if not result.success else "",
        }

    async def deploy_from_github(
        self, github_url: str, target_device_ip: Optional[str] = None
    ) -> Dict[str, Any]:
        """Direct (non-AI) end-to-end deployment via the Deployer."""
        if self._deployer is None:
            self._deployer = Deployer(ssh_executor=self._ssh_executor)
        result: DeploymentResult = await self._deployer.deploy_from_github(
            github_url, target_device_ip
        )
        return result.to_dict()
