import json
import sqlite3

import pytest

from infrastructure_agent.core.audit import AuditLog
from infrastructure_agent.core.policy import CommandPolicy
from infrastructure_agent.deployment.ssh_executor import SSHExecutor


class FakeSSHConnection:
    def __init__(self, result=None):
        self.result = result
        self.commands = []
        self.closed = False

    async def run_command(self, command, **kwargs):
        self.commands.append((command, kwargs))
        return self.result

    def close(self):
        self.closed = True


class FakeSSHClient:
    def __init__(self, connection):
        self.connection = connection
        self.connect_kwargs = None
        self.calls = 0

    async def connect(self, **kwargs):
        self.calls += 1
        self.connect_kwargs = kwargs
        return self.connection


class FakeCommandResult:
    def __init__(self, exit_status=0, stdout="", stderr="", duration=0.25):
        self.exit_status = exit_status
        self.stdout = stdout
        self.stderr = stderr
        self.duration = duration


def audit_events(path):
    with sqlite3.connect(path) as db:
        rows = db.execute(
            "SELECT id, action, target, outcome, details FROM audit_events ORDER BY id"
        ).fetchall()
    return [
        (event_id, action, target, outcome, json.loads(details))
        for event_id, action, target, outcome, details in rows
    ]


@pytest.mark.asyncio
async def test_connect_passes_host_key_and_auth_settings_to_fake_client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    connection = FakeSSHConnection()
    client = FakeSSHClient(connection)
    audit = AuditLog(tmp_path / "audit.db")
    executor = SSHExecutor(audit_log=audit, ssh_client=client)
    executor.config["ssh"].update(
        {"username": "default-user", "key_path": "~/.ssh/deploy_key", "known_hosts": "~/.ssh/known_hosts", "max_retries": 1}
    )

    assert await executor.connect("10.0.0.8", password="secret")

    assert client.connect_kwargs == {
        "host": "10.0.0.8",
        "username": "default-user",
        "client_keys": [str(tmp_path / ".ssh/deploy_key")],
        "known_hosts": str(tmp_path / ".ssh/known_hosts"),
        "timeout": 30,
        "password": "secret",
    }
    assert audit_events(tmp_path / "audit.db")[0][3] == "success"


@pytest.mark.asyncio
async def test_policy_denial_is_audited_without_connecting(tmp_path):
    client = FakeSSHClient(FakeSSHConnection())
    audit = AuditLog(tmp_path / "audit.db")
    executor = SSHExecutor(
        audit_log=audit,
        policy=CommandPolicy(allowed_hosts=("10.0.0.8",)),
        ssh_client=client,
    )

    result = await executor.execute_command("10.0.0.9", "docker ps")

    assert not result.success
    assert "allowlisted" in result.stderr
    assert client.calls == 0
    events = audit_events(tmp_path / "audit.db")
    assert events == [(1, "ssh.command", "10.0.0.9", "denied", {"command": "docker ps"})]


@pytest.mark.asyncio
async def test_command_result_and_audit_link_are_recorded(tmp_path):
    connection = FakeSSHConnection(FakeCommandResult(stdout="hello\n"))
    client = FakeSSHClient(connection)
    audit = AuditLog(tmp_path / "audit.db")
    executor = SSHExecutor(audit_log=audit, ssh_client=client)
    executor.config["ssh"]["max_retries"] = 1

    result = await executor.execute_command("10.0.0.8", "printf hello")

    assert result.to_dict() == {
        "success": True,
        "stdout": "hello\n",
        "stderr": "",
        "exit_code": 0,
        "execution_time": 0.25,
    }
    events = audit_events(tmp_path / "audit.db")
    assert events[0][1:4] == ("ssh.command", "10.0.0.8", "started")
    assert events[1][1:4] == ("ssh.connect", "10.0.0.8", "success")
    assert events[2][1:4] == ("ssh.command", "10.0.0.8", "success")
    assert events[2][4]["audit_id"] == events[0][0]
