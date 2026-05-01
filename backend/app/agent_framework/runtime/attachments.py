from __future__ import annotations

import json
import mimetypes
import uuid
from pathlib import Path
from typing import Any

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
SUPPORTED_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/gif",
    "application/pdf",
    "text/plain",
    "text/markdown",
    "application/json",
    "text/csv",
}

_MIME_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "application/json": ".json",
    "text/csv": ".csv",
}


class AttachmentStore:
    def __init__(self, root: Path = Path("data/attachments")) -> None:
        self.root = root

    def save(self, session_id: str, *, filename: str, mime: str, data: bytes) -> dict[str, Any]:
        normalized_mime = mime.split(";", 1)[0].strip().lower()
        if normalized_mime not in SUPPORTED_MIME_TYPES:
            raise ValueError("Unsupported MIME type")
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise ValueError("Attachment exceeds 10 MB limit")

        attachment_id = uuid.uuid4().hex
        ext = (
            _MIME_EXTENSIONS.get(normalized_mime)
            or mimetypes.guess_extension(normalized_mime)
            or ".bin"
        )
        session_dir = self.root / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        path = session_dir / f"{attachment_id}{ext}"
        path.write_bytes(data)

        metadata = {
            "id": attachment_id,
            "mime": normalized_mime,
            "byte_size": len(data),
            "name": filename or path.name,
            "stored_path": str(path),
        }
        path.with_suffix(f"{path.suffix}.json").write_text(
            json.dumps(metadata, ensure_ascii=False),
            encoding="utf-8",
        )
        return metadata

    def load(self, attachment_id: str) -> tuple[bytes, str, str]:
        path = self.path_for(attachment_id)
        if path is None:
            raise FileNotFoundError(attachment_id)
        metadata = self._metadata_for(path)
        return (
            path.read_bytes(),
            str(metadata.get("mime") or "application/octet-stream"),
            str(metadata.get("name") or path.name),
        )

    def path_for(self, attachment_id: str) -> Path | None:
        if not attachment_id or "/" in attachment_id or "\\" in attachment_id:
            return None
        for path in self.root.glob(f"**/{attachment_id}.*"):
            if path.name.endswith(".json.json"):
                continue
            if path.is_file() and path.stem == attachment_id:
                return path
        return None

    def _metadata_for(self, path: Path) -> dict[str, Any]:
        metadata_path = path.with_suffix(f"{path.suffix}.json")
        if not metadata_path.exists():
            return {"mime": "application/octet-stream", "name": path.name}
        try:
            return json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"mime": "application/octet-stream", "name": path.name}


_attachment_store = AttachmentStore()
