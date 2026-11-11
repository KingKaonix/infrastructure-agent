import sqlite3

from infrastructure_agent.core.audit import AuditLog
from infrastructure_agent.core.state import StateRepository


def test_repository_creates_schema_and_persists_domain_records(tmp_path):
    repository = StateRepository(tmp_path / "agent.db")

    device_id = repository.upsert_device(
        "10.0.0.2", hostname="server", os="Linux", open_ports=[22, 443], ssh_available=True
    )
    deployment_id = repository.create_deployment("https://github.com/acme/app", "10.0.0.2")
    cycle_id = repository.record_optimization_cycle(
        "10.0.0.2", metrics={"cpu": 12.5}, recommendations=["none"]
    )
    event_id = repository.record_audit_event(
        "uptime", device_ip="10.0.0.2", result="ok", execution_time=0.2
    )

    assert repository.get_device(device_id)["open_ports"] == "[22, 443]"
    assert repository.list_deployments()[0]["id"] == deployment_id
    assert repository.list_optimization_cycles()[0]["id"] == cycle_id
    assert repository.list_audit_events()[0]["id"] == event_id

    with sqlite3.connect(tmp_path / "agent.db") as db:
        tables = {
            row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {"devices", "deployments", "optimization_cycles", "audit_events"} <= tables


def test_device_upsert_and_filters_are_idempotent(tmp_path):
    repository = StateRepository(tmp_path / "agent.db")
    first_id = repository.upsert_device("10.0.0.2", hostname="old")
    second_id = repository.upsert_device("10.0.0.2", hostname="new")
    repository.create_deployment("repo-a", "10.0.0.2")
    repository.create_deployment("repo-b", "10.0.0.3")

    assert first_id == second_id
    assert len(repository.list_devices()) == 1
    assert repository.get_device(first_id)["hostname"] == "new"
    assert [
        row["github_url"] for row in repository.list_deployments(target_device_ip="10.0.0.2")
    ] == ["repo-a"]


def test_migration_preserves_legacy_audit_log(tmp_path):
    path = tmp_path / "agent.db"
    AuditLog(path).record("ssh.command", target="10.0.0.2", details={"command": "true"})

    repository = StateRepository(path)
    event_id = repository.record_audit_event("uptime", device_ip="10.0.0.3", result="ok")
    events = repository.list_audit_events()

    assert len(events) == 2
    assert events[-1]["id"] == event_id
    assert events[0]["action"] == "ssh.command"
    assert events[0]["timestamp"] == events[0]["created_at"]


def test_migration_is_idempotent(tmp_path):
    repository = StateRepository(tmp_path / "agent.db")
    repository.migrate()
    repository.migrate()

    with sqlite3.connect(tmp_path / "agent.db") as db:
        assert db.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1
