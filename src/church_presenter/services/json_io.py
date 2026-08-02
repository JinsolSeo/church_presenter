from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def read_json_object(path: Path) -> dict[str, Any]:
    """Read a UTF-8 JSON document whose root must be an object."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("JSON root must be an object")
    return payload


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Durably replace a JSON document without exposing a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def require_schema_version(
    payload: dict[str, Any],
    *,
    document_type: str,
    supported_versions: set[int],
) -> int:
    """Validate a document discriminator and reject unknown versions."""
    if payload.get("document_type") != document_type:
        raise ValueError(f"expected document_type {document_type!r}")
    version = payload.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise TypeError("schema_version must be an integer")
    if version not in supported_versions:
        supported = ", ".join(str(item) for item in sorted(supported_versions))
        raise ValueError(f"unsupported schema_version {version}; supported: {supported}")
    return version
