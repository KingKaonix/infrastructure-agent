"""Persistent SQLite state for inventory, deployments, optimization, and audit data."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any, default: Any) -> str:
    return json.dumps(default if value is None else value, default=str)


class StateRepository:
    """Small repository for the agent's durable SQLite state.

    A connection is opened per operation so the repository is safe to pass between
    the agent's synchronous service boundaries and does not retain a thread-bound
    SQLite connection.
    """

    LATEST_SCHEMA_VERSION = 1

    def __init__(self, path: str | Path = "state/agent.db") -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def migrate(self) -> None:
        """Apply all known migrations, safely and idempotently."""
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            applied = {row[0] for row in db.execute("SELECT version FROM schema_migrations")}
            if 1 not in applied:
                self._migration_one(db)
                db.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                    (1, _now()),
                )

    @staticmethod
    def _migration_one(db: sqlite3.Connection) -> None:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY,
                ip TEXT NOT NULL UNIQUE,
                hostname TEXT NOT NULL DEFAULT '',
                os TEXT NOT NULL DEFAULT '',
                open_ports TEXT NOT NULL DEFAULT '[]',
                ssh_available INTEGER NOT NULL DEFAULT 0,
                discovered_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS deployments (
                id INTEGER PRIMARY KEY,
                github_url TEXT NOT NULL,
                target_device_ip TEXT NOT NULL,
                status TEXT NOT NULL,
                container_id TEXT,
                start_time TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS optimization_cycles (
                id INTEGER PRIMARY KEY,
                device_ip TEXT NOT NULL,
                status TEXT NOT NULL,
                metrics TEXT NOT NULL DEFAULT '{}',
                recommendations TEXT NOT NULL DEFAULT '[]',
                started_at TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY,
                timestamp TEXT NOT NULL,
                device_ip TEXT NOT NULL DEFAULT '',
                command TEXT NOT NULL DEFAULT '',
                result TEXT NOT NULL DEFAULT '',
                execution_time REAL,
                created_at TEXT NOT NULL,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT,
                outcome TEXT NOT NULL,
                details TEXT NOT NULL
            );
            """
        )
        # AuditLog predates this repository and may have already created its
        # narrower table. Add only the columns introduced by this migration.
        columns = {row[1] for row in db.execute("PRAGMA table_info(audit_events)")}
        additions = {
            "timestamp": "TEXT",
            "device_ip": "TEXT NOT NULL DEFAULT ''",
            "command": "TEXT NOT NULL DEFAULT ''",
            "result": "TEXT NOT NULL DEFAULT ''",
            "execution_time": "REAL",
        }
        for name, definition in additions.items():
            if name not in columns:
                db.execute(f"ALTER TABLE audit_events ADD COLUMN {name} {definition}")

        # Backfill the new timestamp column when upgrading a database written by
        # core.audit.AuditLog.
        db.execute("UPDATE audit_events SET timestamp = COALESCE(timestamp, created_at)")

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def upsert_device(
        self,
        ip: str,
        *,
        hostname: str = "",
        os: str = "",
        open_ports: Iterable[int] | None = None,
        ssh_available: bool = False,
        discovered_at: str | None = None,
    ) -> int:
        """Insert a device or update the inventory record for its IP address."""
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO devices(ip, hostname, os, open_ports, ssh_available, discovered_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(ip) DO UPDATE SET
                    hostname=excluded.hostname, os=excluded.os,
                    open_ports=excluded.open_ports, ssh_available=excluded.ssh_available,
                    discovered_at=excluded.discovered_at
                """,
                (
                    ip,
                    hostname,
                    os,
                    _json(list(open_ports) if open_ports is not None else [], []),
                    int(ssh_available),
                    discovered_at or _now(),
                ),
            )
            row = db.execute("SELECT id FROM devices WHERE ip = ?", (ip,)).fetchone()
            assert row is not None
            return int(row[0])

    def get_device(self, device_id: int) -> dict[str, Any] | None:
        with self._connect() as db:
            return self._row(
                db.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
            )

    def list_devices(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM devices ORDER BY id")]

    def create_deployment(
        self,
        github_url: str,
        target_device_ip: str,
        *,
        status: str = "started",
        container_id: str | None = None,
        start_time: str | None = None,
    ) -> int:
        with self._connect() as db:
            cursor = db.execute(
                """
                INSERT INTO deployments(github_url, target_device_ip, status, container_id, start_time)
                VALUES(?, ?, ?, ?, ?)
                """,
                (github_url, target_device_ip, status, container_id, start_time or _now()),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return a deployment id")
            return cursor.lastrowid

    def update_deployment(self, deployment_id: int, **changes: Any) -> None:
        allowed = {"status", "container_id", "start_time"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"Unsupported deployment fields: {', '.join(sorted(unknown))}")
        if not changes:
            return
        assignments = ", ".join(f"{field} = ?" for field in changes)
        with self._connect() as db:
            db.execute(
                f"UPDATE deployments SET {assignments} WHERE id = ?",
                (*changes.values(), deployment_id),
            )

    def list_deployments(self, *, target_device_ip: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM deployments"
        parameters: tuple[Any, ...] = ()
        if target_device_ip is not None:
            query += " WHERE target_device_ip = ?"
            parameters = (target_device_ip,)
        query += " ORDER BY id"
        with self._connect() as db:
            return [dict(row) for row in db.execute(query, parameters)]

    def record_optimization_cycle(
        self,
        device_ip: str,
        *,
        status: str = "started",
        metrics: Mapping[str, Any] | None = None,
        recommendations: Iterable[Any] | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
    ) -> int:
        with self._connect() as db:
            cursor = db.execute(
                """
                INSERT INTO optimization_cycles
                    (device_ip, status, metrics, recommendations, started_at, completed_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    device_ip,
                    status,
                    _json(metrics, {}),
                    _json(list(recommendations) if recommendations is not None else [], []),
                    started_at or _now(),
                    completed_at,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return an optimization cycle id")
            return cursor.lastrowid

    def list_optimization_cycles(self, *, device_ip: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM optimization_cycles"
        parameters: tuple[Any, ...] = ()
        if device_ip is not None:
            query += " WHERE device_ip = ?"
            parameters = (device_ip,)
        query += " ORDER BY id"
        with self._connect() as db:
            return [dict(row) for row in db.execute(query, parameters)]

    def record_audit_event(
        self,
        command: str,
        *,
        device_ip: str = "",
        result: str = "",
        execution_time: float | None = None,
        actor: str = "system",
        action: str | None = None,
        outcome: str | None = None,
        details: Any = None,
    ) -> int:
        timestamp = _now()
        with self._connect() as db:
            cursor = db.execute(
                """
                INSERT INTO audit_events
                    (timestamp, device_ip, command, result, execution_time,
                     created_at, actor, action, target, outcome, details)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    device_ip,
                    command,
                    result,
                    execution_time,
                    timestamp,
                    actor,
                    action or command,
                    device_ip,
                    outcome or result,
                    _json(details, {}),
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return an audit event id")
            return cursor.lastrowid

    def list_audit_events(self, *, device_ip: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM audit_events"
        parameters: tuple[Any, ...] = ()
        if device_ip is not None:
            query += " WHERE device_ip = ?"
            parameters = (device_ip,)
        query += " ORDER BY id"
        with self._connect() as db:
            return [dict(row) for row in db.execute(query, parameters)]


SQLiteStateRepository = StateRepository
