#!/usr/bin/env python3
"""OpenAI-compatible reasoning and tool dispatch for the infrastructure agent.

The model chooses from a small, explicit tool set. Tool execution remains in
the existing service objects, so their policy, approval, and audit boundaries
continue to apply. The OpenAI client is injected at the boundary to keep the
adapter deterministic and testable without a live model endpoint.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol

try:
    from openai import AsyncOpenAI
except ImportError:  # Keep CLI/help and direct non-AI usage import-safe.
    AsyncOpenAI = None  # type: ignore[assignment,misc]

from ..core.config import get_config
from ..deployment.deployer import Deployer, DeploymentResult
from ..deployment.ssh_executor import SSHExecutor, SSHResult
from ..discovery.network_discovery import NetworkDiscovery

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ChatCompletionClient(Protocol):
    """The small async client surface used by this adapter and its tests."""

    @property
    def chat(self) -> Any: ...


ToolHandler = Callable[..., Awaitable[Dict[str, Any]]]


class AIReasoningLayer:
    """Reason over requests using an OpenAI-compatible chat completion API."""

    def __init__(self, client: Optional[ChatCompletionClient] = None):
        self.config = get_config()
        ai_config = self.config.get("ai", {})
        self.provider = ai_config.get("provider", "openai_compatible")
        self.base_url = ai_config.get("base_url", "") or ""
        self.api_key = ai_config.get("api_key", "") or ""
        self.model_id = ai_config.get("model", "") or ""
        self._client = client
        self._deployer: Optional[Deployer] = None
        self._ssh_executor: Optional[SSHExecutor] = None
        self._network_discovery: Optional[NetworkDiscovery] = None

    def wire(
        self,
        deployer: Deployer,
        ssh_executor: SSHExecutor,
        network_discovery: NetworkDiscovery,
    ) -> None:
        """Wire the service objects delegated to by model-selected tools."""
        self._deployer = deployer
        self._ssh_executor = ssh_executor
        self._network_discovery = network_discovery

    def _build_client(self) -> ChatCompletionClient:
        """Create the OpenAI client lazily, after configuration is validated."""
        if self._client is not None:
            return self._client
        if AsyncOpenAI is None:
            raise RuntimeError("OpenAI reasoning adapter is not installed")
        if not self.model_id:
            raise RuntimeError(
                "AI model not configured. Set ai.model in config/agent_config.json "
                "(e.g. via INFRA_AGENT_AI_MODEL)."
            )
        if not self.base_url:
            raise RuntimeError(
                "AI base_url not configured. Set ai.base_url in config/agent_config.json."
            )
        if not self.api_key:
            raise RuntimeError(
                "AI api_key not configured. Set OPENAI_API_KEY or ai.api_key in config/agent_config.json."
            )
        self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    @staticmethod
    def _tool_definitions() -> List[Dict[str, Any]]:
        """Return stable JSON schemas understood by OpenAI-compatible servers."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "analyze_github_repository",
                    "description": "Analyze a GitHub repository and detect its application stack.",
                    "parameters": {
                        "type": "object",
                        "properties": {"github_url": {"type": "string"}},
                        "required": ["github_url"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "generate_deployment_config",
                    "description": "Generate Docker configuration from repository analysis.",
                    "parameters": {
                        "type": "object",
                        "properties": {"repo_analysis": {"type": "object"}},
                        "required": ["repo_analysis"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "deploy_to_device",
                    "description": "Deploy a Docker application to a target device via SSH.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "device_ip": {"type": "string"},
                            "docker_config": {"type": "object"},
                        },
                        "required": ["device_ip", "docker_config"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "discover_network_devices",
                    "description": "Scan the configured LAN for discoverable devices.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "execute_ssh_command",
                    "description": "Execute a non-approved remote SSH command. Destructive commands require explicit approval outside the model.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "device_ip": {"type": "string"},
                            "command": {"type": "string"},
                        },
                        "required": ["device_ip", "command"],
                        "additionalProperties": False,
                    },
                },
            },
        ]

    def _handlers(self) -> Dict[str, ToolHandler]:
        deployer = self._deployer
        ssh = self._ssh_executor
        discovery = self._network_discovery
        if deployer is None or ssh is None or discovery is None:
            raise RuntimeError(
                "AIReasoningLayer not wired. Call wire(deployer, ssh, discovery) first."
            )

        async def analyze_github_repository(github_url: str) -> Dict[str, Any]:
            result = await deployer.analyze_repository(github_url)
            return {
                "success": result.success,
                "analysis": json.loads(result.stdout) if result.success and result.stdout else {},
                "error": result.stderr if not result.success else "",
            }

        async def generate_deployment_config(repo_analysis: Dict[str, Any]) -> Dict[str, Any]:
            analysis = repo_analysis.get("analysis", repo_analysis)
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

        async def deploy_to_device(device_ip: str, docker_config: Dict[str, Any]) -> Dict[str, Any]:
            result: DeploymentResult = await deployer.deploy_to_device(device_ip, docker_config)
            return result.to_dict()

        async def discover_network_devices() -> Dict[str, Any]:
            await discovery.discover_network()
            devices = discovery.get_all_devices()
            return {
                "success": True,
                "devices": [d.to_dict() for d in devices.values()],
                "count": len(devices),
            }

        async def execute_ssh_command(device_ip: str, command: str) -> Dict[str, Any]:
            # Never let model output grant approval; SSHExecutor applies policy and audits denial.
            result: SSHResult = await ssh.execute_command(device_ip, command, approved=False)
            return result.to_dict()

        return {
            "analyze_github_repository": analyze_github_repository,
            "generate_deployment_config": generate_deployment_config,
            "deploy_to_device": deploy_to_device,
            "discover_network_devices": discover_network_devices,
            "execute_ssh_command": execute_ssh_command,
        }

    async def _dispatch_tool(self, name: str, arguments: str) -> Dict[str, Any]:
        handlers = self._handlers()
        handler = handlers.get(name)
        if handler is None:
            return {"success": False, "error": f"Unknown AI tool: {name}"}
        try:
            parsed = json.loads(arguments or "{}")
            if not isinstance(parsed, dict):
                raise ValueError("tool arguments must be a JSON object")
            return await handler(**parsed)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return {"success": False, "error": f"Invalid arguments for {name}: {exc}"}
        except Exception as exc:
            logger.exception("AI tool %s failed", name)
            return {"success": False, "error": str(exc)}

    async def process_request(
        self,
        user_input: str,
        deployer: Deployer,
        ssh_executor: SSHExecutor,
        network_discovery: NetworkDiscovery,
    ) -> str:
        """Run bounded model/tool turns and return the final assistant text."""
        self.wire(deployer, ssh_executor, network_discovery)
        client = self._build_client()
        if not self.model_id:
            raise RuntimeError("AI model not configured for the injected client")

        messages: List[Dict[str, Any]] = [{"role": "user", "content": user_input}]
        tool_calls_made: List[str] = []
        try:
            for _ in range(8):
                completion = await client.chat.completions.create(
                    model=self.model_id,
                    messages=messages,
                    tools=self._tool_definitions(),
                    tool_choice="auto",
                )
                message = completion.choices[0].message
                tool_calls = message.tool_calls or []
                messages.append(
                    {
                        "role": "assistant",
                        "content": message.content,
                        "tool_calls": [
                            {
                                "id": call.id,
                                "type": "function",
                                "function": {
                                    "name": call.function.name,
                                    "arguments": call.function.arguments,
                                },
                            }
                            for call in tool_calls
                        ]
                        or None,
                    }
                )
                if not tool_calls:
                    return (
                        message.content
                        or "I wasn't able to produce a response. Please check the logs."
                    )
                for call in tool_calls:
                    tool_calls_made.append(call.function.name)
                    result = await self._dispatch_tool(call.function.name, call.function.arguments)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": json.dumps(result),
                        }
                    )
        except Exception as exc:
            logger.exception("AI reasoning loop failed: %s", exc)
            return f"AI reasoning failed: {exc}"

        return (
            "I executed the following tools on your behalf: "
            + ", ".join(tool_calls_made)
            + ". Please check the logs for detailed results."
        )

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
        result = await self._deployer.deploy_from_github(github_url, target_device_ip)
        return result.to_dict()
