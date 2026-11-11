import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from infrastructure_agent.core.audit import AuditLog
from infrastructure_agent.core.config import AgentConfig
from infrastructure_agent.core.policy import CommandPolicy
from infrastructure_agent.optimization.performance_optimizer import PerformanceOptimizer


def test_config_is_project_aware_and_does_not_create_missing_file(tmp_path):
    path = tmp_path / "missing.json"
    config = AgentConfig(path)
    assert config.get("ssh.timeout") == 30
    assert not path.exists()


def test_config_environment_secret_is_not_persisted(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value")
    config = AgentConfig(path)
    config.save_config()
    assert "secret-value" not in path.read_text()


def test_policy_requires_approval_for_destructive_commands():
    policy = CommandPolicy()
    with pytest.raises(PermissionError):
        policy.check("host", "docker system prune --volumes")
    policy.check("host", "docker system prune --volumes", approved=True)


def test_audit_records_are_append_only(tmp_path):
    audit = AuditLog(tmp_path / "agent.db")
    event_id = audit.record("ssh.command", target="10.0.0.2", details={"command": "true"})
    assert event_id == 1


def test_metric_parsers_accept_machine_readable_output():
    assert PerformanceOptimizer.parse_cpu_usage("12.5\n") == 12.5
    assert PerformanceOptimizer.parse_memory_usage("100 25\n") == 25.0
    assert PerformanceOptimizer.parse_disk_usage("83\n") == 83.0


def test_help_does_not_start_runtime_or_require_ai():
    root = Path(__file__).parents[1]
    result = subprocess.run([sys.executable, "-m", "infrastructure_agent.main", "--help"], cwd=root, env={**os.environ, "PYTHONPATH": str(root / "src")}, capture_output=True, text=True)
    assert result.returncode == 0
    assert "Infrastructure Agent" in result.stdout
