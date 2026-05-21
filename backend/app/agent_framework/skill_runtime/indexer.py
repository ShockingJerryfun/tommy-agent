from __future__ import annotations

from pathlib import Path
from typing import Any

from ..memory_platform import EMBEDDING_DIM
from .metadata import parse_skill_markdown
from .types import SkillDocument, SkillMetadata


class SkillIndexer:
    def __init__(self, *, store: Any, embedder: Any | None = None) -> None:
        self._store = store
        self._embedder = embedder

    def sync(self, agent_id: str, skills_root: str | Path) -> dict[str, Any]:
        root = Path(skills_root).resolve()
        diagnostics: list[dict[str, str]] = []
        registered_rows: list[dict[str, Any]] = []
        seen_paths: set[str] = set()

        if not root.exists() or not root.is_dir():
            return {
                "agent_id": agent_id,
                "skills_root": str(root),
                "registered": 0,
                "skills": [],
                "diagnostics": [
                    {
                        "path": "",
                        "severity": "error",
                        "message": f"skills root does not exist: {root}",
                    }
                ],
            }

        for path in sorted(root.glob("**/SKILL.md")):
            relative_path = path.relative_to(root).as_posix()
            resolved_path = path.resolve()
            if not _is_within(resolved_path, root):
                diagnostics.append(
                    {
                        "path": relative_path,
                        "severity": "error",
                        "message": f"unsafe skill path escapes skills root: {relative_path}",
                    }
                )
                continue
            try:
                document = parse_skill_markdown(
                    resolved_path.read_text(encoding="utf-8", errors="replace"),
                    source_path=relative_path,
                )
                _validate_document(document)
            except Exception as exc:  # noqa: BLE001 - sync must continue across bad skills.
                diagnostics.append(
                    {
                        "path": relative_path,
                        "severity": "error",
                        "message": str(exc),
                    }
                )
                continue

            metadata_json = {
                "normalized": _metadata_json(document.metadata),
                "diagnostics": [],
                "source": {
                    "relative_path": relative_path,
                    "absolute_path": str(resolved_path),
                    "size_bytes": resolved_path.stat().st_size,
                },
            }
            row = self._store.skill_catalog.register_skill(
                agent_id=agent_id,
                name=document.metadata.name or path.parent.name,
                relative_path=relative_path,
                description=document.metadata.description or "",
                signature=document.signature_text,
                tool_chain=list(document.metadata.required_tools),
                status="active",
                metadata=metadata_json,
            )
            row = self._ensure_active(row)
            self._update_signature_embedding(row, document.signature_text)
            registered_rows.append(row)
            seen_paths.add(relative_path)

        self._retire_missing_skills(
            agent_id=agent_id,
            root=root,
            seen_paths=seen_paths,
            diagnostics=diagnostics,
        )

        return {
            "agent_id": agent_id,
            "skills_root": str(root),
            "registered": len(registered_rows),
            "skills": registered_rows,
            "diagnostics": diagnostics,
        }

    def _ensure_active(self, row: dict[str, Any]) -> dict[str, Any]:
        if row.get("status", "active") == "active":
            return row
        set_status = getattr(self._store.skill_catalog, "set_status", None)
        if set_status is None or not row.get("id"):
            return {**row, "status": "active"}
        updated = set_status(row["id"], "active")
        return updated or {**row, "status": "active"}

    def _update_signature_embedding(self, row: dict[str, Any], signature: str) -> None:
        if self._embedder is None or not signature or not row.get("id"):
            return
        update = getattr(self._store.skill_catalog, "update_signature_embedding", None)
        if update is None:
            return
        try:
            embedding = self._embedder.embed(signature)
        except Exception:  # noqa: BLE001 - vector indexing is a best-effort recall path.
            return
        if not embedding or len(embedding) != EMBEDDING_DIM:
            return
        update(
            row["id"],
            embedding=embedding,
            model=getattr(self._embedder, "model", "embedder"),
        )

    def _retire_missing_skills(
        self,
        *,
        agent_id: str,
        root: Path,
        seen_paths: set[str],
        diagnostics: list[dict[str, str]],
    ) -> None:
        catalog = self._store.skill_catalog
        list_skills = getattr(catalog, "list_skills", None)
        set_status = getattr(catalog, "set_status", None)
        if list_skills is None or set_status is None:
            return
        try:
            rows = list_skills(agent_id=agent_id, status="active", limit=1000)
        except Exception:  # noqa: BLE001 - stale cleanup must not break indexing.
            return
        for row in rows:
            relative_path = _source_relative_path(row)
            if not relative_path or relative_path in seen_paths:
                continue
            source_path = (root / relative_path).resolve()
            if not _is_within(source_path, root) or source_path.exists():
                continue
            skill_id = row.get("id")
            if not skill_id:
                continue
            try:
                set_status(skill_id, "retired")
            except Exception:  # noqa: BLE001 - keep processing other catalog rows.
                continue
            diagnostics.append(
                {
                    "path": relative_path,
                    "severity": "warning",
                    "message": "retired indexed skill because SKILL.md is no longer present",
                }
            )


def list_indexed_skill_summaries(
    *,
    store: Any,
    agent_id: str,
    skills_root: str | Path,
    status: str | None = "active",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return UI/API skill summaries from the runtime catalog.

    The filesystem remains the human-editable source for skill package content, but API
    listings should reflect the same indexed catalog that runtime loading uses.
    """

    root = Path(skills_root)
    if root.exists():
        try:
            SkillIndexer(store=store).sync(agent_id, root)
        except Exception:
            pass
    try:
        rows = store.skill_catalog.list_skills(agent_id=agent_id, status=status, limit=limit)
    except Exception:
        return []
    return [_summary_from_row(row) for row in rows]


def _summary_from_row(row: dict[str, Any]) -> dict[str, Any]:
    relative_path = str(row.get("relative_path") or "")
    return {
        "name": row.get("name") or relative_path,
        "path": relative_path,
        "description": row.get("description") or "",
        "updated_at": row.get("updated_at") or "",
        "status": row.get("status") or "active",
    }


def _validate_document(document: SkillDocument) -> None:
    if not document.metadata.name or not document.metadata.name.strip():
        raise ValueError("missing required metadata field: name")


def _metadata_json(metadata: SkillMetadata) -> dict[str, Any]:
    return {
        "name": metadata.name,
        "description": metadata.description,
        "source_path": metadata.source_path,
        "required_tools": list(metadata.required_tools),
        "triggers": list(metadata.triggers),
        "domains": list(metadata.domains),
        "platforms": list(metadata.platforms),
        "safety_notes": list(metadata.safety_notes),
        "allowed_tools": list(metadata.allowed_tools),
        "user_invocable": metadata.user_invocable,
        "disable_model_invocation": metadata.disable_model_invocation,
        "hermes": _json_value(metadata.hermes),
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _source_relative_path(row: dict[str, Any]) -> str:
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        return str(row.get("relative_path") or "")
    source = metadata.get("source")
    if not isinstance(source, dict):
        return str(row.get("relative_path") or "")
    value = source.get("relative_path")
    return str(value) if value else str(row.get("relative_path") or "")


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents
