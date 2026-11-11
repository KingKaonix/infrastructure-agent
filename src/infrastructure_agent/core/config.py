"""Configuration loading without import-time filesystem or secret writes."""

from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any, Dict

_SECRET_KEYS = {"api_key", "bot_token", "ssh_password", "password"}


class AgentConfig:
    def __init__(self, config_path: str | Path | None = None, *, create: bool = False):
        project_root = Path(__file__).resolve().parents[3]
        configured = config_path or os.getenv(
            "INFRA_AGENT_CONFIG", str(project_root / "config/agent_config.json")
        )
        self.config_path = Path(str(configured)).expanduser().resolve()
        self._config: Dict[str, Any] = self.get_default_config()
        self.load_config(create=create)

    @staticmethod
    def get_default_config() -> Dict[str, Any]:
        return {
            "network": {
                "discovery_interval": 300,
                "scan_range": "",
                "scan_private_only": False,
                "allowed_subnets": [],
            },
            "ssh": {
                "timeout": 30,
                "max_retries": 3,
                "retry_backoff": 0.5,
                "username": "",
                "key_path": "~/.ssh/id_rsa",
                "known_hosts": "~/.ssh/known_hosts",
            },
            "deployment": {"health_check_timeout": 60, "cleanup_old_containers": False},
            "optimization": {
                "check_interval": 1800,
                "cpu_threshold": 80,
                "memory_threshold": 85,
                "disk_threshold": 80,
                "auto_cleanup": False,
            },
            "logging": {"level": "INFO", "log_file": "logs/agent.log"},
            "ai": {"provider": "openai_compatible", "base_url": "", "model": ""},
        }

    def load_config(self, *, create: bool = False) -> None:
        if self.config_path.exists():
            with self.config_path.open(encoding="utf-8") as handle:
                self._merge(self._config, json.load(handle))
        elif create:
            self.save_config()
        self._apply_environment()

    def _merge(self, target: Dict[str, Any], source: Dict[str, Any]) -> None:
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                self._merge(target[key], value)
            else:
                target[key] = value

    def _apply_environment(self) -> None:
        mappings = {
            "INFRA_AGENT_SSH_USERNAME": "ssh.username",
            "INFRA_AGENT_SSH_KEY": "ssh.key_path",
            "INFRA_AGENT_SSH_KNOWN_HOSTS": "ssh.known_hosts",
            "OPENAI_API_KEY": "ai.api_key",
            "INFRA_AGENT_AI_BASE_URL": "ai.base_url",
            "INFRA_AGENT_AI_MODEL": "ai.model",
        }
        for env_name, key in mappings.items():
            if os.getenv(env_name):
                self._set_in_memory(key, os.environ[env_name])

    def _set_in_memory(self, key: str, value: Any) -> None:
        target = self._config
        parts = key.split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value

    def save_config(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        safe = json.loads(json.dumps(self._config))
        for section in safe.values():
            if isinstance(section, dict):
                for key in _SECRET_KEYS:
                    section.pop(key, None)
        self.config_path.write_text(json.dumps(safe, indent=2) + "\n", encoding="utf-8")

    def get(self, key: str, default: Any = None) -> Any:
        value: Any = self._config
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value

    def set(self, key: str, value: Any, *, persist: bool = False) -> None:
        self._set_in_memory(key, value)
        if persist:
            self.save_config()


_config: AgentConfig | None = None


def load_config() -> AgentConfig:
    global _config
    if _config is None:
        _config = AgentConfig()
    return _config


def get_config() -> Dict[str, Any]:
    return load_config()._config


def set_config(key: str, value: Any) -> None:
    load_config().set(key, value, persist=True)
