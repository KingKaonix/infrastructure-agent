"""Configuration management for Infrastructure Agent"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

class AgentConfig:
    def __init__(self, config_path: str = "config/agent_config.json"):
        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self.load_config()

    def load_config(self) -> None:
        """Load configuration from file"""
        if self.config_path.exists():
            with open(self.config_path, 'r') as f:
                self._config = json.load(f)
        else:
            self._config = self.get_default_config()
            self.save_config()

    def get_default_config(self) -> Dict[str, Any]:
        """Return default configuration"""
        return {
            "network": {
                "discovery_interval": 300,  # 5 minutes
                "scan_range": "192.168.1.0/24",
                "scan_private_only": True,
                "allowed_subnets": ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
            },
            "ssh": {
                "timeout": 30,
                "max_retries": 3,
                "key_path": "~/.ssh/id_rsa"
            },
            "deployment": {
                "health_check_timeout": 60,
                "cleanup_old_containers": True
            },
            "optimization": {
                "check_interval": 1800,  # 30 minutes
                "cpu_threshold": 80,
                "memory_threshold": 85,
                "disk_threshold": 80
            },
            "logging": {
                "level": "INFO",
                "log_file": "logs/agent.log"
            },
            "ai": {
                "provider": "openai_compatible",
                "base_url": "",
                "api_key": "",
                "model": ""
            },
            "telegram": {
                "bot_token": "",
                "chat_id": ""
            }
        }

    def save_config(self) -> None:
        """Save configuration to file"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w') as f:
            json.dump(self._config, f, indent=2)

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by key"""
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def set(self, key: str, value: Any) -> None:
        """Set configuration value"""
        keys = key.split('.')
        target = self._config
        for i, k in enumerate(keys[:-1]):
            if k not in target:
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value
        self.save_config()

# Global config instance
_config = AgentConfig()


def load_config() -> AgentConfig:
    """Load global configuration"""
    return _config


def get_config() -> Dict[str, Any]:
    """Get configuration dictionary"""
    return _config._config


def set_config(key: str, value: Any) -> None:
    """Set configuration value"""
    _config.set(key, value)
