#!/usr/bin/env python3
"""Project-scoped provenance ledger for claims and their sources.

The ledger is intentionally small and file-based so exported Agent Packages do
not need a database migration or a third-party service. It records what was
read, when it was read, how trustworthy it is, and which claims it supports.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _clean(value: Any, limit: int = 12000) -> Any:
    if isinstance(value, str):
        return value.strip()[:limit]
    if isinstance(value, list):
        return [_clean(item, limit) for item in value[:50]]
    if isinstance(value, dict):
        return {str(key): _clean(item, limit) for key, item in list(value.items())[:80]}
    return value


class EvidenceLedger:
    """CRUD for a single project's source and claim provenance."""

    def __init__(self, path: Path, project_id: str):
        self.path = path
        self.project_id = project_id

    @property
    def display_path(self) -> str:
        """Return a stable project-relative path instead of a local absolute path."""
        return ".workbench/evidence-ledger.json"

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {
                "schema_version": "1.0",
                "project_id": self.project_id,
                "updated_at": utc_now(),
                "sources": [],
                "claims": [],
            }
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"证据台账损坏: {exc}") from exc
        if not isinstance(value, dict) or value.get("project_id") != self.project_id:
            raise ValueError("证据台账项目绑定不一致")
        value.setdefault("sources", [])
        value.setdefault("claims", [])
        return value

    def _save(self, value: dict[str, Any]) -> None:
        value["updated_at"] = utc_now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(self.path)

    def list(self, status: str = "", source_type: str = "") -> dict[str, Any]:
        value = self._load()
        sources = [
            item for item in value["sources"]
            if (not status or item.get("access_status") == status)
            and (not source_type or item.get("source_type") == source_type)
        ]
        claims = [item for item in value["claims"] if not status or item.get("status") == status]
        return {
            "ok": True,
            "tool": "evidence_ledger",
            "action": "list",
            "project_id": self.project_id,
            "sources": sources[-100:],
            "claims": claims[-100:],
            "path": self.display_path,
        }

    def upsert_source(self, source: dict[str, Any]) -> dict[str, Any]:
        required = ("id", "url", "source_type", "access_status", "evidence_grade")
        missing = [key for key in required if not str(source.get(key) or "").strip()]
        if missing:
            raise ValueError(f"evidence_ledger.source 缺少字段: {', '.join(missing)}")
        locator = str(source["url"]).strip()
        if locator.startswith("project://"):
            relative = locator.removeprefix("project://")
            if not relative or relative.startswith("/") or ".." in Path(relative).parts:
                raise ValueError("evidence_ledger.source.url 的 project:// 路径必须是当前项目内的相对路径")
        elif not locator.startswith(("http://", "https://")):
            raise ValueError("evidence_ledger.source.url 必须是 http(s) URL 或 project:// 相对路径")
        if source["access_status"] not in {"verified", "partial", "unavailable", "login_required", "stale", "user_provided"}:
            raise ValueError("evidence_ledger.source.access_status 无效")
        if source["evidence_grade"] not in {"A", "B", "C", "unknown"}:
            raise ValueError("evidence_ledger.source.evidence_grade 无效")
        value = self._load()
        clean = _clean({**source, "updated_at": utc_now()})
        existing = next((item for item in value["sources"] if item.get("id") == clean["id"] or item.get("url") == clean["url"]), None)
        if existing is None:
            clean["created_at"] = utc_now()
            value["sources"].append(clean)
            operation = "created"
        else:
            existing.update(clean)
            operation = "updated"
            clean = existing
        self._save(value)
        return {"ok": True, "tool": "evidence_ledger", "action": "upsert_source", "operation": operation, "source": clean, "path": self.display_path}

    def upsert_claim(self, claim: dict[str, Any]) -> dict[str, Any]:
        required = ("id", "text", "classification", "evidence_grade", "source_ids", "status")
        missing = [key for key in required if key not in claim]
        if missing:
            raise ValueError(f"evidence_ledger.claim 缺少字段: {', '.join(missing)}")
        if claim["classification"] not in {"fact", "evidence", "assumption", "inference", "recommendation", "decision_candidate"}:
            raise ValueError("evidence_ledger.claim.classification 无效")
        if claim["evidence_grade"] not in {"A", "B", "C", "unknown"}:
            raise ValueError("evidence_ledger.claim.evidence_grade 无效")
        if claim["status"] not in {"active", "unverified", "superseded", "rejected"}:
            raise ValueError("evidence_ledger.claim.status 无效")
        if not isinstance(claim["source_ids"], list) or any(not isinstance(item, str) for item in claim["source_ids"]):
            raise ValueError("evidence_ledger.claim.source_ids 必须是字符串数组")
        value = self._load()
        known_sources = {item.get("id") for item in value["sources"]}
        missing_sources = sorted(set(claim["source_ids"]) - known_sources)
        if missing_sources:
            raise ValueError(f"claim 引用了不存在的 source_ids: {', '.join(missing_sources)}")
        clean = _clean({**claim, "updated_at": utc_now()})
        existing = next((item for item in value["claims"] if item.get("id") == clean["id"]), None)
        if existing is None:
            clean["created_at"] = utc_now()
            value["claims"].append(clean)
            operation = "created"
        else:
            existing.update(clean)
            operation = "updated"
            clean = existing
        self._save(value)
        return {"ok": True, "tool": "evidence_ledger", "action": "upsert_claim", "operation": operation, "claim": clean, "path": self.display_path}
