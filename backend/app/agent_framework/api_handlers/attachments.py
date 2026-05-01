from __future__ import annotations

from typing import Any

from fastapi import HTTPException, UploadFile
from fastapi.responses import Response

from ..runtime.attachments import MAX_ATTACHMENT_BYTES


async def upload_attachment_impl(
    store, attachment_store, session_id: str, file: UploadFile
) -> dict[str, Any]:
    if store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    data = await file.read()
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="Attachment exceeds 10 MB limit")
    try:
        saved = attachment_store.save(
            session_id,
            filename=file.filename or "attachment",
            mime=file.content_type or "application/octet-stream",
            data=data,
        )
    except ValueError as exc:
        status_code = 415 if str(exc) == "Unsupported MIME type" else 413
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    attachment_id = str(saved["id"])
    return {
        "id": attachment_id,
        "mime": saved["mime"],
        "byte_size": saved["byte_size"],
        "name": saved["name"],
        "thumbnail_url": f"/api/attachments/{attachment_id}",
    }


def get_attachment_impl(attachment_store, attachment_id: str) -> Response:
    try:
        data, mime, _filename = attachment_store.load(attachment_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Attachment not found") from exc
    return Response(
        content=data,
        media_type=mime,
        headers={"Cache-Control": "private, max-age=300"},
    )
