"""Append-only audit trail and case store (SQLite).

Every agent step, recommendation and human decision is written here with a
timestamp, so any outcome can be reconstructed for an auditor or regulator.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.getenv("AMANAH_DB", Path(__file__).resolve().parent.parent / "artifacts" / "amanah.db"))
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY, customer_id TEXT, created_at TEXT, status TEXT,
    recommendation TEXT, risk_level TEXT, summary TEXT, payload TEXT,
    decision TEXT, reviewer TEXT, review_note TEXT, decided_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, ts TEXT, agent TEXT,
    action TEXT, detail TEXT, latency_ms INTEGER, model TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


class Audit:
    def __init__(self, path: Path | None = None):
        self.con = connect(path)

    def log(self, case_id: str, agent: str, action: str, detail: dict | None = None,
            latency_ms: int = 0, model: str = "") -> None:
        with _lock:
            self.con.execute(
                "INSERT INTO events (case_id, ts, agent, action, detail, latency_ms, model) VALUES (?,?,?,?,?,?,?)",
                (case_id, _now(), agent, action, json.dumps(detail or {}, ensure_ascii=False, default=str), latency_ms, model))
            self.con.commit()

    def open_case(self, case_id: str, customer_id: str) -> None:
        with _lock:
            self.con.execute("INSERT OR IGNORE INTO cases (case_id, customer_id, created_at, status) VALUES (?,?,?,?)",
                             (case_id, customer_id, _now(), "in_progress"))
            self.con.commit()

    def propose(self, case_id: str, recommendation: str, risk_level: str, summary: str, payload: dict) -> None:
        with _lock:
            self.con.execute(
                "UPDATE cases SET status='awaiting_review', recommendation=?, risk_level=?, summary=?, payload=? WHERE case_id=?",
                (recommendation, risk_level, summary, json.dumps(payload, ensure_ascii=False, default=str), case_id))
            self.con.commit()

    def decide(self, case_id: str, decision: str, reviewer: str, note: str) -> None:
        with _lock:
            self.con.execute(
                "UPDATE cases SET status='closed', decision=?, reviewer=?, review_note=?, decided_at=? WHERE case_id=?",
                (decision, reviewer, note, _now(), case_id))
            self.con.commit()

    def cases(self, status: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM cases", ()
        if status:
            q, args = q + " WHERE status=?", (status,)
        return [dict(r) for r in self.con.execute(q + " ORDER BY created_at DESC", args)]

    def case(self, case_id: str) -> dict | None:
        r = self.con.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
        return dict(r) if r else None

    def events(self, case_id: str) -> list[dict]:
        return [dict(r) for r in self.con.execute("SELECT * FROM events WHERE case_id=? ORDER BY id", (case_id,))]
