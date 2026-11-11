"""Append-only SQLite audit trail for actions and outcomes."""
from __future__ import annotations
import json, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

class AuditLog:
    def __init__(self, path: str | Path = "state/agent.db"):
        self.path = Path(path).expanduser().resolve(); self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS audit_events (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, target TEXT, outcome TEXT NOT NULL, details TEXT NOT NULL)")
    def record(self, action: str, *, actor: str = "system", target: str = "", outcome: str = "started", details: Any = None) -> int:
        with sqlite3.connect(self.path) as db:
            cur = db.execute("INSERT INTO audit_events(created_at,actor,action,target,outcome,details) VALUES(?,?,?,?,?,?)", (datetime.now(timezone.utc).isoformat(), actor, action, target, outcome, json.dumps(details or {}, default=str)))
            return int(cur.lastrowid)
