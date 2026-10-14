"""Minimal, dependency-free RAG retrieval store for LINE AI Secretary.

This is the retrieval foundation only: it does not call an LLM, mutate code,
or trigger deployments. Callers must choose a namespace to keep user data isolated.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


class RagStore:
    """SQLite keyword retrieval with source provenance and namespace isolation."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    namespace TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(namespace, source, source_id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rag_namespace_updated "
                "ON rag_documents(namespace, updated_at DESC)"
            )

    @staticmethod
    def _required_text(value: str, field: str, max_length: int = 20000) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{field} must be text")
        value = value.strip()
        if not value or len(value) > max_length or any(ord(c) < 32 and c not in "\n\t\r" for c in value):
            raise ValueError(f"{field} is empty or invalid")
        return value

    def add_document(
        self,
        *,
        namespace: str,
        source: str,
        source_id: str,
        content: str,
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Insert or refresh one source. Repeated imports do not create duplicates."""
        namespace = self._required_text(namespace, "namespace", 200)
        source = self._required_text(source, "source", 100)
        source_id = self._required_text(source_id, "source_id", 500)
        content = self._required_text(content, "content")
        title = title.strip() if isinstance(title, str) else ""
        if len(title) > 500:
            raise ValueError("title is too long")
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")

        # Reject obviously sensitive metadata keys before persistence.
        def has_sensitive_key(value: Any) -> bool:
            if isinstance(value, dict):
                for key, nested in value.items():
                    normalized = str(key).casefold().replace("-", "_")
                    if any(marker in normalized for marker in (
                        "token", "secret", "password", "passwd", "authorization",
                        "api_key", "private_key", "credential",
                    )):
                        return True
                    if has_sensitive_key(nested):
                        return True
            elif isinstance(value, list):
                return any(has_sensitive_key(item) for item in value)
            return False

        if has_sensitive_key(metadata):
            raise ValueError("metadata contains a sensitive field name")
        metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        if len(metadata_json) > 4096:
            raise ValueError("metadata is too large")
        digest = hashlib.sha256(
            (title + "\n" + content + "\n" + metadata_json).encode("utf-8")
        ).hexdigest()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO rag_documents
                    (namespace, source, source_id, title, content, metadata_json, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(namespace, source, source_id) DO UPDATE SET
                    title=excluded.title,
                    content=excluded.content,
                    metadata_json=excluded.metadata_json,
                    content_hash=excluded.content_hash,
                    updated_at=CURRENT_TIMESTAMP
                WHERE rag_documents.content_hash != excluded.content_hash
                """,
                (namespace, source, source_id, title, content, metadata_json, digest),
            )
            row = conn.execute(
                """
                SELECT id, namespace, source, source_id, title, content_hash, updated_at
                FROM rag_documents
                WHERE namespace=? AND source=? AND source_id=?
                """,
                (namespace, source, source_id),
            ).fetchone()
        return dict(row)

    def search(
        self, *, namespace: str, query: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Return ranked keyword matches only from the requested namespace."""
        namespace = self._required_text(namespace, "namespace", 200)
        query = self._required_text(query, "query", 1000)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 20:
            raise ValueError("limit must be an integer from 1 to 20")

        # Keep Japanese continuous phrases intact; also try whitespace-separated terms.
        terms = list(dict.fromkeys([query] + [part for part in query.split() if part != query]))
        clauses = []
        params: list[Any] = [namespace]
        for term in terms:
            clauses.append("(title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\')")
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.extend([f"%{escaped}%", f"%{escaped}%"])
        where = " OR ".join(clauses)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, namespace, source, source_id, title, content, metadata_json,
                       created_at, updated_at
                FROM rag_documents
                WHERE namespace=? AND ({where})
                ORDER BY updated_at DESC, id DESC
                LIMIT 200
                """,
                params,
            ).fetchall()

        results = []
        for row in rows:
            item = dict(row)
            haystack = (item["title"] + "\n" + item["content"]).casefold()
            item["score"] = sum(1 for term in terms if term.casefold() in haystack)
            if item["score"] <= 0:
                continue
            item["metadata"] = json.loads(item.pop("metadata_json"))
            item["snippet"] = self._snippet(item["content"], terms[0])
            results.append(item)
        results.sort(key=lambda item: (item["score"], item["updated_at"], item["id"]), reverse=True)
        return results[:limit]

    @staticmethod
    def _snippet(content: str, query: str, radius: int = 180) -> str:
        position = content.casefold().find(query.casefold())
        if position < 0:
            return content[: radius * 2].strip()
        start = max(0, position - radius)
        end = min(len(content), position + len(query) + radius)
        snippet = content[start:end].strip()
        if start:
            snippet = "…" + snippet
        if end < len(content):
            snippet += "…"
        return snippet
