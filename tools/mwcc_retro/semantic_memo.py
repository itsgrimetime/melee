"""Memory-bounded memo storage for exact x86 semantic analysis."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import zlib
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


READABLE_GLOBAL_EFFECT_SEMANTICS = "readable-global-effect-v1"
_STORE_SCHEMA = "mwcc-retro-readable-global-effect-cache-v1"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_DEPENDENCY_KINDS = frozenset(
    {"function", "global-slot", "dynamic-field"}
)

DependencyRows = tuple[tuple[str, int, str], ...]


@dataclass(frozen=True, slots=True)
class DependencyMemoEntry:
    """One memo result bound to its exact analysis dependencies."""

    image_sha256: str
    dependencies: DependencyRows
    result: Any


@dataclass(frozen=True, slots=True)
class ReadableGlobalEffectKey:
    """Canonical semantic identity of one readable-global call summary."""

    call_target: int
    slot: int
    field_path: tuple[int, ...]
    exact_call_contexts: tuple[tuple[int, int, int], ...]
    summary_fact_signature: tuple[int, ...]
    control_flow_revision: int
    analysis_semantics: str = READABLE_GLOBAL_EFFECT_SEMANTICS


class ReadableGlobalEffectMemoStore(Protocol):
    """Storage boundary used by readable-global semantic summaries."""

    def get(
        self,
        key: ReadableGlobalEffectKey,
    ) -> DependencyMemoEntry | None: ...

    def put(
        self,
        key: ReadableGlobalEffectKey,
        entry: DependencyMemoEntry,
    ) -> None: ...

    def __len__(self) -> int: ...

    def close(self) -> None: ...


class SemanticMemoStoreError(ValueError):
    """Raised when persistent semantic memo state is not trustworthy."""


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _strict_json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise SemanticMemoStoreError(
                    f"{label} has duplicate key {key!r}"
                )
            value[key] = item
        return value

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
        )
    except SemanticMemoStoreError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SemanticMemoStoreError(f"{label} is malformed JSON") from exc
    if not isinstance(value, dict):
        raise SemanticMemoStoreError(f"{label} must be a JSON object")
    return value


def _compressed_json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        decoded = zlib.decompress(raw)
    except zlib.error as exc:
        raise SemanticMemoStoreError(
            f"{label} is not valid compressed data"
        ) from exc
    return _strict_json_object(decoded, label=label)


def _require_exact_keys(
    value: dict[str, Any],
    expected: frozenset[str],
    *,
    label: str,
) -> None:
    if set(value) != expected:
        raise SemanticMemoStoreError(f"{label} has an unexpected schema")


def _intern_entry(
    dependency_pool: dict[DependencyRows, DependencyRows],
    entry: DependencyMemoEntry,
) -> DependencyMemoEntry:
    dependencies = dependency_pool.setdefault(
        entry.dependencies,
        entry.dependencies,
    )
    if dependencies is entry.dependencies:
        return entry
    return DependencyMemoEntry(
        image_sha256=entry.image_sha256,
        dependencies=dependencies,
        result=entry.result,
    )


class InMemoryReadableGlobalEffectMemoStore:
    """Dictionary memo with canonical shared dependency tuples."""

    def __init__(self) -> None:
        self.entries: dict[
            ReadableGlobalEffectKey,
            DependencyMemoEntry,
        ] = {}
        self.dependency_pool: dict[DependencyRows, DependencyRows] = {}

    def _intern_entry(
        self,
        entry: DependencyMemoEntry,
    ) -> DependencyMemoEntry:
        return _intern_entry(self.dependency_pool, entry)

    def get(
        self,
        key: ReadableGlobalEffectKey,
    ) -> DependencyMemoEntry | None:
        return self.entries.get(key)

    def put(
        self,
        key: ReadableGlobalEffectKey,
        entry: DependencyMemoEntry,
    ) -> None:
        self.entries[key] = self._intern_entry(entry)

    def __len__(self) -> int:
        return len(self.entries)

    def close(self) -> None:
        """Release no resources; provided for store-interface symmetry."""


def _key_payload(key: ReadableGlobalEffectKey) -> dict[str, Any]:
    if key.analysis_semantics != READABLE_GLOBAL_EFFECT_SEMANTICS:
        raise SemanticMemoStoreError(
            "readable-global memo key analysis semantics mismatch"
        )
    scalar_fields = (
        key.call_target,
        key.slot,
        key.control_flow_revision,
    )
    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in scalar_fields
    ):
        raise SemanticMemoStoreError(
            "readable-global memo key contains an invalid scalar"
        )
    if (
        not isinstance(key.field_path, tuple)
        or any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in key.field_path
        )
        or not isinstance(key.exact_call_contexts, tuple)
        or any(
            not isinstance(row, tuple)
            or len(row) != 3
            or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                for value in row
            )
            for row in key.exact_call_contexts
        )
        or not isinstance(key.summary_fact_signature, tuple)
        or any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in key.summary_fact_signature
        )
    ):
        raise SemanticMemoStoreError(
            "readable-global memo key contains an invalid sequence"
        )
    return {
        "analysis_semantics": key.analysis_semantics,
        "call_target": key.call_target,
        "slot": key.slot,
        "field_path": list(key.field_path),
        "exact_call_contexts": [
            list(row) for row in key.exact_call_contexts
        ],
        "summary_fact_signature": list(key.summary_fact_signature),
        "control_flow_revision": key.control_flow_revision,
    }


def _dependency_payload(
    dependencies: DependencyRows,
) -> list[dict[str, Any]]:
    if not isinstance(dependencies, tuple):
        raise SemanticMemoStoreError(
            "dependency payload is not a canonical tuple"
        )
    payload = []
    for row in dependencies:
        if (
            not isinstance(row, tuple)
            or len(row) != 3
            or row[0] not in _DEPENDENCY_KINDS
            or isinstance(row[1], bool)
            or not isinstance(row[1], int)
            or not isinstance(row[2], str)
            or _SHA256_PATTERN.fullmatch(row[2]) is None
        ):
            raise SemanticMemoStoreError(
                "dependency payload contains an invalid row"
            )
        payload.append(
            {
                "kind": row[0],
                "identifier": row[1],
                "fingerprint": row[2],
            }
        )
    if dependencies != tuple(sorted(set(dependencies))):
        raise SemanticMemoStoreError(
            "dependency payload is not a canonical tuple"
        )
    return payload


def _decode_dependencies(raw: bytes) -> DependencyRows:
    try:
        value = json.loads(
            zlib.decompress(raw).decode("utf-8"),
            object_pairs_hook=lambda pairs: _unique_object(
                pairs,
                label="dependency payload",
            ),
        )
    except SemanticMemoStoreError:
        raise
    except (zlib.error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SemanticMemoStoreError(
            "dependency payload is malformed"
        ) from exc
    if not isinstance(value, list):
        raise SemanticMemoStoreError(
            "dependency payload must be a JSON list"
        )
    rows = []
    for item in value:
        if not isinstance(item, dict):
            raise SemanticMemoStoreError(
                "dependency payload contains a non-object row"
            )
        _require_exact_keys(
            item,
            frozenset({"kind", "identifier", "fingerprint"}),
            label="dependency payload row",
        )
        rows.append(
            (
                item["kind"],
                item["identifier"],
                item["fingerprint"],
            )
        )
    dependencies = tuple(rows)
    _dependency_payload(dependencies)
    return dependencies


def _unique_object(pairs, *, label: str) -> dict[str, Any]:
    value = {}
    for key, item in pairs:
        if key in value:
            raise SemanticMemoStoreError(
                f"{label} has duplicate key {key!r}"
            )
        value[key] = item
    return value


def _result_payload(result: Any) -> dict[str, Any]:
    if result is None:
        return {"status": "blocked"}
    if (
        not isinstance(result, tuple)
        or len(result) != 2
        or not isinstance(result[0], frozenset)
        or any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= 0xFF
            for value in result[0]
        )
        or not isinstance(result[1], str)
        or not result[1]
    ):
        raise SemanticMemoStoreError(
            "result payload cannot encode the memo result"
        )
    return {
        "status": "finite",
        "values": sorted(result[0]),
        "provenance": result[1],
    }


def _decode_result(raw: bytes) -> Any:
    value = _compressed_json_object(raw, label="result payload")
    status = value.get("status")
    if status == "blocked":
        _require_exact_keys(
            value,
            frozenset({"status"}),
            label="result payload",
        )
        return None
    if status != "finite":
        raise SemanticMemoStoreError(
            "result payload has an unknown status"
        )
    _require_exact_keys(
        value,
        frozenset({"status", "values", "provenance"}),
        label="result payload",
    )
    values = value["values"]
    provenance = value["provenance"]
    if (
        not isinstance(values, list)
        or any(
            isinstance(item, bool)
            or not isinstance(item, int)
            or not 0 <= item <= 0xFF
            for item in values
        )
        or values != sorted(set(values))
        or not isinstance(provenance, str)
        or not provenance
    ):
        raise SemanticMemoStoreError("result payload is malformed")
    return frozenset(values), provenance


class SqliteReadableGlobalEffectMemoStore:
    """Strict normalized durable store with bounded hot entries."""

    def __init__(
        self,
        path: Path,
        *,
        image_sha256: str,
        lru_entries: int = 512,
    ) -> None:
        if (
            not isinstance(image_sha256, str)
            or _SHA256_PATTERN.fullmatch(image_sha256) is None
        ):
            raise ValueError("image_sha256 must be lowercase SHA-256")
        if (
            isinstance(lru_entries, bool)
            or not isinstance(lru_entries, int)
            or lru_entries <= 0
        ):
            raise ValueError("lru_entries must be a positive int")
        self.path = Path(path)
        self.image_sha256 = image_sha256
        self.lru_entries = lru_entries
        self.lru: OrderedDict[
            ReadableGlobalEffectKey,
            DependencyMemoEntry,
        ] = OrderedDict()
        self.dependency_pool: dict[DependencyRows, DependencyRows] = {}
        self.connection: sqlite3.Connection | None = None
        is_new = not self.path.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.connection = sqlite3.connect(self.path)
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
            self.connection.execute("PRAGMA foreign_keys=ON")
            self.connection.execute("PRAGMA cache_size=-8192")
            if is_new:
                self._create_schema()
            else:
                self._validate_existing()
        except (sqlite3.DatabaseError, SemanticMemoStoreError) as exc:
            if self.connection is not None:
                self.connection.close()
                self.connection = None
            if isinstance(exc, SemanticMemoStoreError):
                raise
            raise SemanticMemoStoreError(
                f"semantic memo SQLite open failed: {exc}"
            ) from exc

    def _connection(self) -> sqlite3.Connection:
        if self.connection is None:
            raise SemanticMemoStoreError(
                "semantic memo SQLite store is closed"
            )
        return self.connection

    def _create_schema(self) -> None:
        connection = self._connection()
        with connection:
            connection.execute(
                "CREATE TABLE metadata("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE dependencies("
                "dependency_sha256 TEXT PRIMARY KEY, "
                "payload BLOB NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE memo("
                "key_sha256 TEXT PRIMARY KEY, "
                "key_payload BLOB NOT NULL, "
                "dependency_sha256 TEXT NOT NULL, "
                "result_payload BLOB NOT NULL, "
                "FOREIGN KEY(dependency_sha256) "
                "REFERENCES dependencies(dependency_sha256))"
            )
            connection.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                {
                    "schema": _STORE_SCHEMA,
                    "image_sha256": self.image_sha256,
                    "analysis_semantics": (
                        READABLE_GLOBAL_EFFECT_SEMANTICS
                    ),
                }.items(),
            )

    def _validate_existing(self) -> None:
        connection = self._connection()
        quick_check = connection.execute(
            "PRAGMA quick_check(1)"
        ).fetchone()
        if quick_check != ("ok",):
            raise SemanticMemoStoreError(
                "semantic memo SQLite quick_check failed"
            )
        try:
            metadata = dict(
                connection.execute(
                    "SELECT key, value FROM metadata"
                )
            )
        except sqlite3.DatabaseError as exc:
            raise SemanticMemoStoreError(
                "semantic memo SQLite metadata is unreadable"
            ) from exc
        expected_keys = {
            "schema",
            "image_sha256",
            "analysis_semantics",
        }
        if set(metadata) != expected_keys:
            raise SemanticMemoStoreError(
                "semantic memo metadata keys mismatch"
            )
        if metadata["schema"] != _STORE_SCHEMA:
            raise SemanticMemoStoreError(
                "semantic memo metadata schema mismatch"
            )
        if metadata["image_sha256"] != self.image_sha256:
            raise SemanticMemoStoreError(
                "semantic memo compiler SHA mismatch"
            )
        if (
            metadata["analysis_semantics"]
            != READABLE_GLOBAL_EFFECT_SEMANTICS
        ):
            raise SemanticMemoStoreError(
                "semantic memo analysis semantics mismatch"
            )

    def _remember(
        self,
        key: ReadableGlobalEffectKey,
        entry: DependencyMemoEntry,
    ) -> DependencyMemoEntry:
        entry = _intern_entry(self.dependency_pool, entry)
        self.lru[key] = entry
        self.lru.move_to_end(key)
        while len(self.lru) > self.lru_entries:
            self.lru.popitem(last=False)
        return entry

    def get(
        self,
        key: ReadableGlobalEffectKey,
    ) -> DependencyMemoEntry | None:
        cached = self.lru.get(key)
        if cached is not None:
            self.lru.move_to_end(key)
            return cached
        key_bytes = _canonical_json_bytes(_key_payload(key))
        key_sha256 = hashlib.sha256(key_bytes).hexdigest()
        try:
            row = self._connection().execute(
                "SELECT memo.key_payload, "
                "memo.dependency_sha256, "
                "dependencies.payload, "
                "memo.result_payload "
                "FROM memo JOIN dependencies "
                "ON dependencies.dependency_sha256 "
                "= memo.dependency_sha256 "
                "WHERE memo.key_sha256 = ?",
                (key_sha256,),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise SemanticMemoStoreError(
                "semantic memo SQLite lookup failed"
            ) from exc
        if row is None:
            return None
        try:
            stored_key = zlib.decompress(row[0])
        except zlib.error as exc:
            raise SemanticMemoStoreError(
                "semantic memo key payload is not valid compressed data"
            ) from exc
        if hashlib.sha256(stored_key).hexdigest() != key_sha256:
            raise SemanticMemoStoreError(
                "semantic memo key payload digest mismatch"
            )
        if stored_key != key_bytes:
            raise SemanticMemoStoreError(
                "semantic memo key payload mismatch"
            )
        try:
            dependency_bytes = zlib.decompress(row[2])
        except zlib.error as exc:
            raise SemanticMemoStoreError(
                "semantic memo dependency payload is not valid "
                "compressed data"
            ) from exc
        if hashlib.sha256(dependency_bytes).hexdigest() != row[1]:
            raise SemanticMemoStoreError(
                "semantic memo dependency payload digest mismatch"
            )
        dependencies = _decode_dependencies(row[2])
        result = _decode_result(row[3])
        return self._remember(
            key,
            DependencyMemoEntry(
                image_sha256=self.image_sha256,
                dependencies=dependencies,
                result=result,
            ),
        )

    def put(
        self,
        key: ReadableGlobalEffectKey,
        entry: DependencyMemoEntry,
    ) -> None:
        if entry.image_sha256 != self.image_sha256:
            raise SemanticMemoStoreError(
                "semantic memo entry compiler SHA mismatch"
            )
        key_bytes = _canonical_json_bytes(_key_payload(key))
        key_sha256 = hashlib.sha256(key_bytes).hexdigest()
        dependency_bytes = _canonical_json_bytes(
            _dependency_payload(entry.dependencies)
        )
        dependency_sha256 = hashlib.sha256(
            dependency_bytes
        ).hexdigest()
        result_bytes = _canonical_json_bytes(
            _result_payload(entry.result)
        )
        compressed_key = zlib.compress(key_bytes, level=1)
        compressed_dependencies = zlib.compress(
            dependency_bytes,
            level=1,
        )
        compressed_result = zlib.compress(result_bytes, level=1)
        connection = self._connection()
        try:
            with connection:
                existing_dependency = connection.execute(
                    "SELECT payload FROM dependencies "
                    "WHERE dependency_sha256 = ?",
                    (dependency_sha256,),
                ).fetchone()
                if existing_dependency is None:
                    connection.execute(
                        "INSERT INTO dependencies("
                        "dependency_sha256, payload) VALUES (?, ?)",
                        (
                            dependency_sha256,
                            compressed_dependencies,
                        ),
                    )
                else:
                    try:
                        existing_dependency_bytes = zlib.decompress(
                            existing_dependency[0]
                        )
                    except zlib.error as exc:
                        raise SemanticMemoStoreError(
                            "semantic memo dependency payload is not "
                            "valid compressed data"
                        ) from exc
                    if existing_dependency_bytes != dependency_bytes:
                        raise SemanticMemoStoreError(
                            "semantic memo dependency digest collision"
                        )
                existing_key = connection.execute(
                    "SELECT key_payload FROM memo "
                    "WHERE key_sha256 = ?",
                    (key_sha256,),
                ).fetchone()
                if existing_key is not None:
                    try:
                        existing_key_bytes = zlib.decompress(
                            existing_key[0]
                        )
                    except zlib.error as exc:
                        raise SemanticMemoStoreError(
                            "semantic memo key payload is not valid "
                            "compressed data"
                        ) from exc
                    if existing_key_bytes != key_bytes:
                        raise SemanticMemoStoreError(
                            "semantic memo key digest collision"
                        )
                connection.execute(
                    "INSERT INTO memo("
                    "key_sha256, key_payload, "
                    "dependency_sha256, result_payload) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(key_sha256) DO UPDATE SET "
                    "key_payload=excluded.key_payload, "
                    "dependency_sha256=excluded.dependency_sha256, "
                    "result_payload=excluded.result_payload",
                    (
                        key_sha256,
                        compressed_key,
                        dependency_sha256,
                        compressed_result,
                    ),
                )
        except sqlite3.DatabaseError as exc:
            raise SemanticMemoStoreError(
                "semantic memo SQLite write failed"
            ) from exc
        self._remember(key, entry)

    def __len__(self) -> int:
        try:
            return self._connection().execute(
                "SELECT COUNT(*) FROM memo"
            ).fetchone()[0]
        except sqlite3.DatabaseError as exc:
            raise SemanticMemoStoreError(
                "semantic memo SQLite count failed"
            ) from exc

    def __enter__(self) -> SqliteReadableGlobalEffectMemoStore:
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def close(self) -> None:
        if self.connection is None:
            return
        connection = self.connection
        self.connection = None
        try:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            connection.close()
