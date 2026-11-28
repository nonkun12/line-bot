"""Provenance-aware, bounded knowledge memory for ASDI.

This module is deliberately provider-neutral: it performs no model calls,
network access, code execution, or automatic promotion of unverified evidence.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable

_SCHEMA_VERSION = 1
_MAX_RECORDS = 500
_MAX_STORE_BYTES = 4 * 1024 * 1024
_MAX_CLAIM = 2000
_MAX_EVIDENCE = 8000
_MAX_SOURCE_REF = 500
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_STATUSES = {"unverified", "verified", "rejected"}


class KnowledgeError(ValueError):
    """Invalid knowledge record or unsafe store state."""


def _timestamp(value: str, field: str) -> str:
    if not isinstance(value, str) or len(value) > 40:
        raise KnowledgeError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise KnowledgeError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise KnowledgeError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class KnowledgeRecord:
    record_id: str
    claim: str
    source_ref: str
    evidence: str
    evidence_sha256: str
    observed_at: str
    confidence: float
    validation_status: str = "unverified"
    expires_at: str | None = None
    supersedes: tuple[str, ...] = ()
    contradicts: tuple[str, ...] = ()
    schema_version: int = _SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != _SCHEMA_VERSION:
            raise KnowledgeError("unsupported knowledge schema version")
        if not isinstance(self.record_id, str) or not _ID_RE.fullmatch(self.record_id):
            raise KnowledgeError("invalid record_id")
        if not isinstance(self.claim, str) or not self.claim.strip() or len(self.claim) > _MAX_CLAIM:
            raise KnowledgeError("claim is empty or exceeds bounds")
        if (not isinstance(self.source_ref, str) or not self.source_ref.strip()
                or len(self.source_ref) > _MAX_SOURCE_REF
                or any(ch.isspace() for ch in self.source_ref)):
            raise KnowledgeError("source_ref must be a bounded, whitespace-free reference")
        if not isinstance(self.evidence, str) or not self.evidence.strip() or len(self.evidence) > _MAX_EVIDENCE:
            raise KnowledgeError("evidence is empty or exceeds bounds")
        actual = hashlib.sha256(self.evidence.encode("utf-8")).hexdigest()
        if not isinstance(self.evidence_sha256, str) or not _DIGEST_RE.fullmatch(self.evidence_sha256):
            raise KnowledgeError("invalid evidence digest")
        if actual != self.evidence_sha256:
            raise KnowledgeError("evidence digest mismatch")
        observed = _timestamp(self.observed_at, "observed_at")
        object.__setattr__(self, "observed_at", observed)
        if self.expires_at is not None:
            expiry = _timestamp(self.expires_at, "expires_at")
            if expiry <= observed:
                raise KnowledgeError("expires_at must be later than observed_at")
            object.__setattr__(self, "expires_at", expiry)
        if (not isinstance(self.confidence, (int, float)) or isinstance(self.confidence, bool)
                or not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0):
            raise KnowledgeError("confidence must be between 0 and 1")
        if self.validation_status not in _STATUSES:
            raise KnowledgeError("invalid validation_status")
        for field in ("supersedes", "contradicts"):
            values = getattr(self, field)
            if not isinstance(values, tuple) or len(values) > 20:
                raise KnowledgeError(f"{field} must be a tuple of at most 20 IDs")
            if any(not isinstance(item, str) or not _ID_RE.fullmatch(item) or item == self.record_id
                   for item in values) or len(set(values)) != len(values):
                raise KnowledgeError(f"invalid {field} references")


class ASDIKnowledgeStore:
    """Atomic JSONL store with bounded writes and provenance-aware retrieval."""

    def __init__(self, path: str | Path, *, max_records: int = _MAX_RECORDS) -> None:
        if not isinstance(max_records, int) or isinstance(max_records, bool) or not 1 <= max_records <= _MAX_RECORDS:
            raise ValueError("max_records must be between 1 and 500")
        self.path = Path(path)
        self.max_records = max_records

    @staticmethod
    def evidence_digest(evidence: str) -> str:
        if not isinstance(evidence, str):
            raise KnowledgeError("evidence must be text")
        return hashlib.sha256(evidence.encode("utf-8")).hexdigest()

    def add(self, record: KnowledgeRecord) -> KnowledgeRecord:
        if not isinstance(record, KnowledgeRecord):
            raise TypeError("record must be a KnowledgeRecord")
        records = self._read()
        for existing in records:
            if existing.record_id == record.record_id:
                if existing == record:
                    return existing
                raise KnowledgeError("record_id already exists with different content")
        records.append(record)
        self._write(records[-self.max_records:])
        return record

    def get(self, record_id: str) -> KnowledgeRecord | None:
        for record in self._read():
            if record.record_id == record_id:
                return record
        return None

    def search(
        self, query: str, *, limit: int = 5, now: datetime | None = None,
        include_unverified: bool = False,
    ) -> list[dict[str, object]]:
        if not isinstance(query, str) or not query.strip() or len(query) > 1000:
            raise KnowledgeError("query is empty or exceeds bounds")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise KnowledgeError("limit must be between 1 and 20")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise KnowledgeError("now must be timezone-aware")
        current_iso = current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        terms = tuple(dict.fromkeys([query.strip(), *query.split()]))
        records = self._read()
        by_id = {record.record_id: record for record in records}
        # Never promote either side of an unresolved contradiction. A record
        # explicitly superseded by another record is also excluded.
        conflicted_ids: set[str] = set()
        superseded_ids: set[str] = set()
        for record in records:
            for target in record.contradicts:
                conflicted_ids.add(record.record_id)
                conflicted_ids.add(target)
            superseded_ids.update(record.supersedes)
        matches: list[tuple[int, str, KnowledgeRecord]] = []
        for record in records:
            if record.record_id in conflicted_ids or record.record_id in superseded_ids:
                continue
            if record.validation_status == "rejected":
                continue
            if record.validation_status != "verified" and not include_unverified:
                continue
            if record.expires_at and record.expires_at <= current_iso:
                continue
            haystack = record.claim.casefold()
            score = sum(1 for term in terms if term and term.casefold() in haystack)
            if score:
                matches.append((score, record.observed_at, record))
        matches.sort(key=lambda item: (item[0], item[1], item[2].record_id), reverse=True)
        output = []
        for score, _, record in matches[:limit]:
            related = []
            for target in record.contradicts:
                related.append({"relation": "contradicts", "record_id": target,
                                "present": target in by_id})
            for target in record.supersedes:
                related.append({"relation": "supersedes", "record_id": target,
                                "present": target in by_id})
            for other in records:
                if record.record_id in other.contradicts and other.record_id not in record.contradicts:
                    related.append({"relation": "contradicted_by", "record_id": other.record_id,
                                    "present": True})
                if record.record_id in other.supersedes and other.record_id not in record.supersedes:
                    related.append({"relation": "superseded_by", "record_id": other.record_id,
                                    "present": True})
            output.append({
                "record_id": record.record_id, "claim": record.claim,
                "source_ref": record.source_ref, "evidence": record.evidence,
                "evidence_sha256": record.evidence_sha256, "observed_at": record.observed_at,
                "expires_at": record.expires_at, "confidence": record.confidence,
                "validation_status": record.validation_status, "score": score,
                "relations": related,
                "evidence_is_untrusted_data": True,
            })
        return output

    def _read(self) -> list[KnowledgeRecord]:
        if not self.path.exists():
            return []
        raw = self.path.read_bytes()
        if len(raw) > _MAX_STORE_BYTES:
            raise KnowledgeError("knowledge store exceeds size limit")
        records = []
        for line_number, line in enumerate(raw.splitlines(), 1):
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise KnowledgeError("record must be an object")
                allowed = set(KnowledgeRecord.__dataclass_fields__)
                if set(value) != allowed:
                    raise KnowledgeError("record fields do not match schema")
                value["supersedes"] = tuple(value["supersedes"])
                value["contradicts"] = tuple(value["contradicts"])
                records.append(KnowledgeRecord(**value))
            except (json.JSONDecodeError, TypeError, KeyError, KnowledgeError) as exc:
                raise KnowledgeError(f"invalid knowledge store line {line_number}") from exc
        if len(records) > self.max_records:
            raise KnowledgeError("knowledge store exceeds configured record limit")
        if len({item.record_id for item in records}) != len(records):
            raise KnowledgeError("duplicate record IDs in knowledge store")
        return records

    def _write(self, records: Iterable[KnowledgeRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_name = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                   prefix=f".{self.path.name}.", delete=False) as temp:
                temp_name = temp.name
                for record in records:
                    temp.write(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True) + "\n")
                temp.flush()
                os.fsync(temp.fileno())
            if os.path.getsize(temp_name) > _MAX_STORE_BYTES:
                raise KnowledgeError("knowledge store exceeds size limit")
            os.replace(temp_name, self.path)
            temp_name = None
        finally:
            if temp_name:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass


__all__ = ["KnowledgeRecord", "ASDIKnowledgeStore", "KnowledgeError"]
