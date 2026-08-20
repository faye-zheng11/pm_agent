#!/usr/bin/env python3
"""Local, project-isolated memory shared by PM Agent entry points.

The hub deliberately keeps the raw conversation and derived memories separate.
Raw turns are append-only; derived memories can be superseded or rejected.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class MemoryHub:
    """A small local memory store with project and user namespaces."""

    def __init__(self, path: Path | None = None):
        configured = os.environ.get("PM_MEMORY_DB", "").strip()
        self.path = Path(configured).expanduser() if configured else (
            Path.home() / ".config" / "pm-workbench" / "memory-hub.db"
        )
        if path is not None:
            self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, source, external_id)
                );
                CREATE INDEX IF NOT EXISTS sessions_project_idx ON sessions(project_id, updated_at);
                CREATE TABLE IF NOT EXISTS turns (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    idempotency_key TEXT UNIQUE,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                );
                CREATE INDEX IF NOT EXISTS turns_project_idx ON turns(project_id, created_at);
                CREATE INDEX IF NOT EXISTS turns_session_idx ON turns(session_id, created_at);
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'candidate',
                    confidence TEXT NOT NULL DEFAULT 'medium',
                    source_session_id TEXT,
                    source_turn_id TEXT,
                    valid_from TEXT NOT NULL,
                    valid_until TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS memories_project_idx ON memories(project_id, status, updated_at);
                CREATE INDEX IF NOT EXISTS memories_type_idx ON memories(project_id, memory_type, status);
                """
            )

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:16]}"

    @staticmethod
    def _metadata(value: Any) -> str:
        return json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=False, sort_keys=True)

    def open_session(
        self,
        project_id: str,
        source: str = "codex",
        external_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project_id = str(project_id).strip()
        source = str(source or "unknown").strip()[:80]
        external_id = str(external_id or uuid.uuid4().hex).strip()[:160]
        if not project_id:
            raise ValueError("project_id 不能为空")
        now = utc_now()
        session_id = self._id("session")
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO sessions(id, project_id, source, external_id, metadata_json, started_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(project_id, source, external_id) DO UPDATE SET updated_at=excluded.updated_at""",
                (session_id, project_id, source, external_id, self._metadata(metadata), now, now),
            )
            row = connection.execute(
                "SELECT * FROM sessions WHERE project_id=? AND source=? AND external_id=?",
                (project_id, source, external_id),
            ).fetchone()
        return self._session(row)

    @staticmethod
    def _session(row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            raise ValueError("记忆会话不存在")
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "source": row["source"],
            "external_id": row["external_id"],
            "status": row["status"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "started_at": row["started_at"],
            "updated_at": row["updated_at"],
        }

    def append_turn(
        self,
        project_id: str,
        role: str,
        content: str,
        *,
        session_id: str = "",
        source: str = "codex",
        external_session_id: str = "",
        metadata: dict[str, Any] | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        content = str(content or "").strip()
        role = str(role or "user").strip()
        if not content:
            raise ValueError("记忆 turn 内容不能为空")
        if role not in {"user", "assistant", "tool", "system"}:
            raise ValueError("记忆 turn role 无效")
        if not session_id:
            session_id = self.open_session(project_id, source, external_session_id)["id"]
        now = utc_now()
        turn_id = self._id("turn")
        key = idempotency_key.strip() or hashlib.sha256(
            f"{project_id}\0{session_id}\0{role}\0{content}".encode("utf-8")
        ).hexdigest()
        with self.connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO turns(id, project_id, session_id, source, role, content, metadata_json, created_at, idempotency_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (turn_id, project_id, session_id, source, role, content[:100000], self._metadata(metadata), now, key),
            )
            row = connection.execute("SELECT * FROM turns WHERE idempotency_key=?", (key,)).fetchone()
            connection.execute("UPDATE sessions SET updated_at=? WHERE id=? AND project_id=?", (now, session_id, project_id))
        return self._turn(row)

    @staticmethod
    def _turn(row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            raise ValueError("记忆 turn 不存在")
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "session_id": row["session_id"],
            "source": row["source"],
            "role": row["role"],
            "content": row["content"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "created_at": row["created_at"],
        }

    def propose_memory(
        self,
        project_id: str,
        memory_type: str,
        content: str,
        *,
        scope: str = "project",
        confidence: str = "medium",
        source_session_id: str = "",
        source_turn_id: str = "",
        metadata: dict[str, Any] | None = None,
        status: str = "candidate",
    ) -> dict[str, Any]:
        if scope not in {"project", "user"}:
            raise ValueError("memory scope 无效")
        if memory_type not in {"conversation", "fact", "evidence", "decision", "assumption", "question", "preference", "action", "rejected", "tool_observation"}:
            raise ValueError("memory_type 无效")
        if status not in {"active", "rejected", "superseded", "candidate"}:
            raise ValueError("记忆状态无效")
        content = str(content or "").strip()
        if not content:
            raise ValueError("memory content 不能为空")
        now = utc_now()
        memory_id = self._id("memory")
        with self.connect() as connection:
            existing = connection.execute(
                """SELECT * FROM memories
                   WHERE project_id=? AND scope=? AND memory_type=? AND content=?
                     AND status IN ('active', 'candidate')
                   ORDER BY updated_at DESC LIMIT 1""",
                (project_id, scope, memory_type, content[:50000]),
            ).fetchone()
            if existing is not None:
                return self._memory(existing)
            connection.execute(
                """INSERT INTO memories(id, project_id, scope, memory_type, content, status, confidence, source_session_id, source_turn_id, valid_from, metadata_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (memory_id, project_id, scope, memory_type, content[:50000], status, confidence, source_session_id or None, source_turn_id or None, now, self._metadata(metadata), now, now),
            )
            row = connection.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        return self._memory(row)

    @staticmethod
    def _memory(row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            raise ValueError("记忆不存在")
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "scope": row["scope"],
            "memory_type": row["memory_type"],
            "content": row["content"],
            "status": row["status"],
            "confidence": row["confidence"],
            "source_session_id": row["source_session_id"],
            "source_turn_id": row["source_turn_id"],
            "valid_from": row["valid_from"],
            "valid_until": row["valid_until"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def update_memory(self, memory_id: str, status: str, *, replacement_id: str = "") -> dict[str, Any]:
        if status not in {"active", "rejected", "superseded", "candidate"}:
            raise ValueError("记忆状态无效")
        now = utc_now()
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
            if row is None:
                raise ValueError("记忆不存在")
            connection.execute("UPDATE memories SET status=?, valid_until=?, updated_at=? WHERE id=?", (status, now if status in {"superseded", "rejected"} else None, now, memory_id))
            if replacement_id:
                connection.execute("UPDATE memories SET status='superseded', valid_until=?, updated_at=? WHERE id=?", (now, now, replacement_id))
            row = connection.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        return self._memory(row)

    @staticmethod
    def _terms(query: str) -> list[str]:
        text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", str(query or "").casefold())
        pieces = [item for item in text.split() if len(item) >= 2]
        if not pieces and text.strip():
            pieces = [char for char in text.strip() if "\u4e00" <= char <= "\u9fff"]
        return list(dict.fromkeys(pieces[:12]))

    def search(self, project_id: str, query: str = "", *, limit: int = 12, include_user: bool = True) -> dict[str, Any]:
        limit = max(1, min(int(limit), 50))
        terms = self._terms(query)
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM memories WHERE status='active' AND (project_id=? OR (?=1 AND scope='user')) ORDER BY updated_at DESC LIMIT 200",
                (project_id, 1 if include_user else 0),
            ).fetchall()
            turn_rows = connection.execute(
                "SELECT * FROM turns WHERE project_id=? ORDER BY created_at DESC LIMIT 120", (project_id,)
            ).fetchall()
        memories = [self._memory(row) for row in rows]
        turns = [self._turn(row) for row in turn_rows]
        if terms:
            def score(value: str) -> int:
                lowered = value.casefold()
                return sum(lowered.count(term) for term in terms)
            memories.sort(key=lambda item: (score(item["content"]), item["updated_at"]), reverse=True)
            turns.sort(key=lambda item: (score(item["content"]), item["created_at"]), reverse=True)
        return {"memories": memories[:limit], "turns": turns[:limit]}

    def context(self, project_id: str, query: str = "", *, limit: int = 8) -> str:
        value = self.search(project_id, query, limit=limit)
        lines = ["## PM Memory Hub", "以下内容来自当前项目的本机长期记忆；原始讨论不是事实，除非 memory_type 已明确标记。"]
        if value["memories"]:
            lines.append("### 已沉淀记忆")
            for item in value["memories"]:
                scope = "用户级" if item["scope"] == "user" else "项目级"
                lines.append(f"- [{scope}/{item['memory_type']}/{item['confidence']}] {item['content']}（{item['updated_at']}）")
        if value["turns"]:
            lines.append("### 相关历史讨论")
            for item in value["turns"][:limit]:
                lines.append(f"- [{item['source']}/{item['role']}/{item['created_at']}] {item['content'][:1200]}")
        return "\n".join(lines)

    def record_task_start(self, task: dict[str, Any]) -> dict[str, Any]:
        session = self.open_session(task["project_id"], task.get("memory_source", "codex"), task.get("memory_session_id") or f"task:{task['id']}")
        return self.append_turn(
            task["project_id"], "user", task["goal"], session_id=session["id"], source=session["source"],
            metadata={"task_id": task["id"], "agent_id": task["assigned_agent"], "task_type": task["task_type"]},
            idempotency_key=f"task:{task['id']}:input",
        )

    def record_task_result(self, task: dict[str, Any], result: dict[str, Any], *, status: str = "completed") -> dict[str, Any]:
        session = self.open_session(
            task["project_id"],
            task.get("memory_source", "codex"),
            task.get("memory_session_id") or f"task:{task['id']}",
        )
        summary = {"status": status, "summary": result.get("summary"), "conclusions": result.get("conclusions", []), "open_questions": result.get("open_questions", []), "artifacts": result.get("artifacts", [])}
        turn = self.append_turn(
            task["project_id"], "assistant", json.dumps(summary, ensure_ascii=False), session_id=session["id"], source=session["source"],
            metadata={"task_id": task["id"], "agent_id": task["assigned_agent"], "task_type": task["task_type"]},
            idempotency_key=f"task:{task['id']}:result",
        )
        if result.get("summary"):
            self.propose_memory(task["project_id"], "conversation", str(result["summary"]), source_session_id=session["id"], source_turn_id=turn["id"], confidence="medium", metadata={"task_id": task["id"]})
        # Keep durable candidate memories for conclusions from all agents. They
        # remain candidates until the PM explicitly confirms them, so casual
        # discussion cannot silently become project canon.
        type_map = {
            "fact": "fact",
            "evidence": "evidence",
            "assumption": "assumption",
            "decision_candidate": "decision",
            "recommendation": "action",
        }
        for item in result.get("conclusions") or []:
            if not isinstance(item, dict):
                continue
            content = str(item.get("statement") or "").strip()
            memory_type = type_map.get(str(item.get("classification") or ""))
            if not content or not memory_type:
                continue
            self.propose_memory(
                task["project_id"],
                memory_type,
                content,
                source_session_id=session["id"],
                source_turn_id=turn["id"],
                confidence=str(item.get("confidence") or "medium"),
                metadata={"task_id": task["id"], "agent_id": task["assigned_agent"], "evidence_refs": item.get("evidence_refs") or []},
                status="candidate",
            )
        for item in result.get("open_questions") or []:
            if isinstance(item, str) and item.strip():
                self.propose_memory(task["project_id"], "question", item, source_session_id=session["id"], source_turn_id=turn["id"], confidence="medium", metadata={"task_id": task["id"]})
        return turn
