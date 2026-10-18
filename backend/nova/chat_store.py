from __future__ import annotations

import hashlib
import hmac
from io import BytesIO
import zipfile
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from pypdf import PdfReader

from nova.config import settings

router = APIRouter(prefix="/api/chat", tags=["chat"])
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".txt", ".md", ".markdown", ".csv", ".json", ".html", ".htm", ".py", ".js", ".ts", ".tsx", ".css", ".yaml", ".yml", ".toml", ".log", ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
TEXT_EXTENSIONS = ALLOWED_EXTENSIONS - {".pdf"} - IMAGE_EXTENSIONS
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _connect() -> sqlite3.Connection:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(settings.database_path)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS chat_conversations(
        id TEXT PRIMARY KEY, title TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS chat_messages(
        id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL,
        content TEXT NOT NULL, attachments_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        FOREIGN KEY(conversation_id) REFERENCES chat_conversations(id) ON DELETE CASCADE)""")
    con.execute("""CREATE TABLE IF NOT EXISTS chat_uploads(
        id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, original_name TEXT NOT NULL,
        stored_name TEXT NOT NULL, content_type TEXT NOT NULL, size_bytes INTEGER NOT NULL,
        sha256 TEXT NOT NULL, extracted_text TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
        FOREIGN KEY(conversation_id) REFERENCES chat_conversations(id) ON DELETE CASCADE)""")
    con.commit()
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conversation(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["archived"] = bool(item["archived"])
    return item


def _message(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["attachments"] = json.loads(item.pop("attachments_json"))
    return item


class ConversationCreate(BaseModel):
    title: str = Field(default="New chat", min_length=1, max_length=120)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    archived: bool | None = None


class MessageCreate(BaseModel):
    role: str = Field(pattern=r"^(user|assistant|system)$")
    content: str = Field(min_length=1, max_length=50000)
    attachments: list[str] = Field(default_factory=list, max_length=10)


def _require_conversation(con: sqlite3.Connection, conversation_id: str) -> sqlite3.Row:
    row = con.execute("SELECT * FROM chat_conversations WHERE id=?", (conversation_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Conversation not found.")
    return row


@router.get("/conversations")
def list_conversations(q: str | None = None, archived: bool = False):
    if q is not None and len(q) > 200:
        raise HTTPException(422, "Search query is limited to 200 characters.")
    con = _connect()
    try:
        rows = con.execute(
            "SELECT * FROM chat_conversations WHERE archived=? ORDER BY updated_at DESC LIMIT 500",
            (int(archived),),
        ).fetchall()
        items = [_conversation(row) for row in rows]
        if q and q.strip():
            needle = q.strip().casefold()
            items = [item for item in items if needle in item["title"].casefold()]
        return {"conversations": items}
    finally:
        con.close()


@router.post("/conversations", status_code=201)
def create_conversation(req: ConversationCreate):
    now, conversation_id = _now(), str(uuid.uuid4())
    con = _connect()
    try:
        con.execute("INSERT INTO chat_conversations(id,title,created_at,updated_at) VALUES(?,?,?,?)",
                    (conversation_id, req.title.strip(), now, now))
        con.commit()
        return _conversation(con.execute("SELECT * FROM chat_conversations WHERE id=?", (conversation_id,)).fetchone())
    finally:
        con.close()


@router.patch("/conversations/{conversation_id}")
def update_conversation(conversation_id: str, req: ConversationUpdate):
    if req.title is None and req.archived is None:
        raise HTTPException(422, "Provide a title or archived value.")
    con = _connect()
    try:
        _require_conversation(con, conversation_id)
        if req.title is not None:
            con.execute("UPDATE chat_conversations SET title=?,updated_at=? WHERE id=?",
                        (req.title.strip(), _now(), conversation_id))
        if req.archived is not None:
            con.execute("UPDATE chat_conversations SET archived=?,updated_at=? WHERE id=?",
                        (int(req.archived), _now(), conversation_id))
        con.commit()
        return _conversation(_require_conversation(con, conversation_id))
    finally:
        con.close()


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str):
    con = _connect()
    try:
        _require_conversation(con, conversation_id)
        # Delete stored uploads only after verifying each filename is a direct child of
        # the dedicated upload directory and is not a symlink.
        upload_dir = settings.workspace / "chat-uploads"
        rows = con.execute("SELECT stored_name FROM chat_uploads WHERE conversation_id=?", (conversation_id,)).fetchall()
        for row in rows:
            stored = Path(row["stored_name"])
            if len(stored.parts) != 1 or stored.name != row["stored_name"]:
                raise HTTPException(500, "Unsafe attachment metadata encountered; deletion stopped.")
            target = upload_dir / stored.name
            if target.is_symlink():
                raise HTTPException(500, "Attachment storage contains a symbolic link; deletion stopped.")
            target.unlink(missing_ok=True)
        # Delete child records explicitly because SQLite foreign keys are not globally enabled.
        con.execute("DELETE FROM chat_messages WHERE conversation_id=?", (conversation_id,))
        con.execute("DELETE FROM chat_uploads WHERE conversation_id=?", (conversation_id,))
        con.execute("DELETE FROM chat_conversations WHERE id=?", (conversation_id,))
        con.commit()
    finally:
        con.close()


@router.get("/conversations/{conversation_id}/messages")
def list_messages(conversation_id: str):
    con = _connect()
    try:
        _require_conversation(con, conversation_id)
        rows = con.execute("SELECT * FROM chat_messages WHERE conversation_id=? ORDER BY created_at,id",
                           (conversation_id,)).fetchall()
        return {"messages": [_message(row) for row in rows]}
    finally:
        con.close()


@router.post("/conversations/{conversation_id}/messages", status_code=201)
def save_message(conversation_id: str, req: MessageCreate):
    con = _connect()
    try:
        _require_conversation(con, conversation_id)
        if len(req.attachments) > 10:
            raise HTTPException(422, "A message may reference at most 10 attachments.")
        for attachment_id in req.attachments:
            if con.execute("SELECT 1 FROM chat_uploads WHERE id=? AND conversation_id=?",
                           (attachment_id, conversation_id)).fetchone() is None:
                raise HTTPException(422, "An attachment does not belong to this conversation.")
        message_id, now = str(uuid.uuid4()), _now()
        con.execute("INSERT INTO chat_messages(id,conversation_id,role,content,attachments_json,created_at) VALUES(?,?,?,?,?,?)",
                    (message_id, conversation_id, req.role, req.content,
                     json.dumps(req.attachments), now))
        con.execute("UPDATE chat_conversations SET updated_at=? WHERE id=?", (now, conversation_id))
        # Use the first user message as the default conversation title.
        if req.role == "user":
            row = con.execute("SELECT title FROM chat_conversations WHERE id=?", (conversation_id,)).fetchone()
            if row and row["title"] == "New chat":
                title = " ".join(req.content.split())[:72] or "New chat"
                con.execute("UPDATE chat_conversations SET title=? WHERE id=?", (title, conversation_id))
        con.commit()
        return _message(con.execute("SELECT * FROM chat_messages WHERE id=?", (message_id,)).fetchone())
    finally:
        con.close()


@router.get("/conversations/{conversation_id}/export")
def export_conversation(conversation_id: str, format: str = "json"):
    """Export one conversation and attachment metadata without embedding binary uploads."""
    if format not in {"json", "markdown", "zip"}:
        raise HTTPException(422, "Export format must be 'json', 'markdown', or 'zip'.")
    con = _connect()
    try:
        conversation = _require_conversation(con, conversation_id)
        messages = con.execute(
            "SELECT * FROM chat_messages WHERE conversation_id=? ORDER BY created_at,id",
            (conversation_id,),
        ).fetchall()
        upload_rows = con.execute(
            "SELECT id,original_name,stored_name,content_type,size_bytes,sha256,created_at,extracted_text "
            "FROM chat_uploads WHERE conversation_id=? ORDER BY created_at,id",
            (conversation_id,),
        ).fetchall()
        uploads = [dict(row) for row in upload_rows]
        message_items = [_message(row) for row in messages]
        payload = {
            "schema_version": 1,
            "exported_at": _now(),
            "conversation": _conversation(conversation),
            "messages": message_items,
            "attachments": [{key: value for key, value in item.items() if key != "stored_name"} for item in uploads],
            "attachment_policy": "Binary files are not embedded; use the original NOVA conversation to download them.",
        }
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "", conversation_id)[:80] or "conversation"
        if format == "json":
            body = json.dumps(payload, ensure_ascii=False, indent=2)
            return Response(
                content=body,
                media_type="application/json; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="nova-chat-{safe_id}.json"',
                         "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
            )
        lines = [
            f"# {conversation['title']}",
            "",
            f"- Conversation ID: {conversation_id}",
            f"- Created: {conversation['created_at']}",
            f"- Updated: {conversation['updated_at']}",
            f"- Exported: {payload['exported_at']}",
            "",
            "> Attachment files are not embedded in this Markdown export. Metadata and extracted text are included below where available.",
            "",
        ]
        attachment_map = {item["id"]: item for item in uploads}
        for item in message_items:
            lines.extend([f"## {item['role'].capitalize()}", "", item["content"], ""])
            for attachment_id in item["attachments"]:
                attachment = attachment_map.get(attachment_id)
                if attachment:
                    lines.extend([
                        f"- Attachment: **{attachment['original_name']}**",
                        f"  - Type: {attachment['content_type']}",
                        f"  - Size: {attachment['size_bytes']} bytes",
                        f"  - SHA-256: {attachment['sha256']}",
                    ])
            if item["attachments"]:
                lines.append("")
        lines.extend(["## Attachment inventory", ""])
        for attachment in uploads:
            lines.extend([
                f"### {attachment['original_name']}",
                "",
                f"- ID: {attachment['id']}",
                f"- Type: {attachment['content_type']}",
                f"- Size: {attachment['size_bytes']} bytes",
                f"- SHA-256: {attachment['sha256']}",
                "",
            ])
            if attachment["extracted_text"]:
                lines.extend(["<details>", "<summary>Extracted text</summary>", "",
                              attachment["extracted_text"], "", "</details>", ""])
        if format == "zip":
            upload_dir = settings.workspace / "chat-uploads"
            if upload_dir.is_symlink():
                raise HTTPException(403, "Upload storage must not be a symbolic link.")
            if len(uploads) > 100:
                raise HTTPException(413, "Chat backup is limited to 100 attachments.")
            archive_buffer = BytesIO()
            total_bytes = 0
            try:
                with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("conversation.json", json.dumps(payload, ensure_ascii=False, indent=2))
                    archive.writestr("conversation.md", "\n".join(lines))
                    for attachment in uploads:
                        stored_name = attachment["stored_name"]
                        stored = Path(stored_name)
                        if len(stored.parts) != 1 or stored.name != stored_name:
                            raise HTTPException(500, "Unsafe attachment metadata encountered; export stopped.")
                        path = upload_dir / stored_name
                        if path.is_symlink() or not path.is_file() or path.resolve().parent != upload_dir.resolve():
                            raise HTTPException(404, "A stored attachment is unavailable; backup stopped.")
                        total_bytes += path.stat().st_size
                        if total_bytes > 100 * 1024 * 1024:
                            raise HTTPException(413, "Chat backup attachment data is limited to 100 MiB.")
                        safe_name = _SAFE_NAME.sub("_", Path(attachment["original_name"]).name).strip("._") or "attachment"
                        archive.write(path, arcname="attachments/" + attachment["id"] + "_" + safe_name)
            except Exception:
                archive_buffer.close()
                raise
            return Response(
                content=archive_buffer.getvalue(),
                media_type="application/zip",
                headers={"Content-Disposition": f'attachment; filename="nova-chat-{safe_id}.zip"',
                         "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
            )
        return Response(
            content="\n".join(lines),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="nova-chat-{safe_id}.md"',
                     "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
        )
    finally:
        con.close()


@router.post("/import", status_code=201)
async def import_chat_backup(file: UploadFile = File(...)):
    """Restore a bounded NOVA ZIP backup; never extract archive paths directly."""
    archive_bytes = await file.read(110 * 1024 * 1024 + 1)
    await file.close()
    if len(archive_bytes) > 110 * 1024 * 1024:
        raise HTTPException(413, "Chat backup archive exceeds the 110 MiB limit.")
    if not archive_bytes:
        raise HTTPException(422, "Backup file is empty.")
    try:
        archive = zipfile.ZipFile(BytesIO(archive_bytes), "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise HTTPException(422, "Upload a valid NOVA ZIP backup.") from exc

    written_paths: list[Path] = []
    con = _connect()
    try:
        with archive:
            entries = archive.infolist()
            if len(entries) > 103:
                raise HTTPException(413, "Backup contains too many archive entries.")
            names: set[str] = set()
            total_uncompressed = 0
            for entry in entries:
                name = entry.filename
                path_parts = Path(name).parts
                if (not name or name.startswith(("/", "\\")) or "\\" in name
                        or any(part in {"", ".", ".."} for part in path_parts)
                        or name in names):
                    raise HTTPException(422, "Backup contains an unsafe or duplicate archive path.")
                names.add(name)
                # Reject Unix symbolic links and other non-regular file entries.
                mode = (entry.external_attr >> 16) & 0xFFFF
                if mode and (mode & 0o170000) not in {0, 0o100000, 0o040000}:
                    raise HTTPException(422, "Backup contains an unsupported filesystem entry.")
                total_uncompressed += entry.file_size
                if total_uncompressed > 110 * 1024 * 1024:
                    raise HTTPException(413, "Backup expands beyond the 110 MiB limit.")
            if "conversation.json" not in names:
                raise HTTPException(422, "Backup is missing conversation.json.")
            try:
                payload = json.loads(archive.read("conversation.json"))
            except (json.JSONDecodeError, UnicodeDecodeError, KeyError) as exc:
                raise HTTPException(422, "Backup conversation.json is invalid.") from exc
            if not isinstance(payload, dict) or payload.get("schema_version") != 1:
                raise HTTPException(422, "Unsupported NOVA backup schema version.")
            source_conversation = payload.get("conversation")
            source_messages = payload.get("messages")
            source_attachments = payload.get("attachments")
            if (not isinstance(source_conversation, dict) or not isinstance(source_messages, list)
                    or not isinstance(source_attachments, list) or len(source_messages) > 5000
                    or len(source_attachments) > 100):
                raise HTTPException(422, "Backup conversation structure is invalid or exceeds limits.")
            title = source_conversation.get("title")
            if not isinstance(title, str) or not title.strip() or len(title) > 120:
                raise HTTPException(422, "Backup conversation title is invalid.")

            attachment_map: dict[str, str] = {}
            restored_uploads: list[dict[str, Any]] = []
            upload_dir = settings.workspace / "chat-uploads"
            upload_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            if upload_dir.is_symlink():
                raise HTTPException(403, "Upload storage must not be a symbolic link.")
            total_upload_bytes = 0
            for metadata in source_attachments:
                if not isinstance(metadata, dict):
                    raise HTTPException(422, "Backup attachment metadata is invalid.")
                old_id = metadata.get("id")
                original_name = metadata.get("original_name")
                extension = Path(original_name or "").suffix.lower() if isinstance(original_name, str) else ""
                if (not isinstance(old_id, str) or not old_id or not isinstance(original_name, str)
                        or not original_name or len(original_name) > 255 or Path(original_name).name != original_name
                        or "/" in original_name or "\\" in original_name or extension not in ALLOWED_EXTENSIONS):
                    raise HTTPException(422, "Backup contains unsupported attachment metadata.")
                prefix = "attachments/" + old_id + "_"
                matches = [name for name in names if name.startswith(prefix)]
                if len(matches) != 1:
                    raise HTTPException(422, "Backup is missing an attachment or contains ambiguous attachment entries.")
                data = archive.read(matches[0])
                total_upload_bytes += len(data)
                if total_upload_bytes > 100 * 1024 * 1024:
                    raise HTTPException(413, "Restored attachment data is limited to 100 MiB.")
                expected_size = metadata.get("size_bytes")
                expected_digest = metadata.get("sha256")
                if (not isinstance(expected_size, int) or expected_size != len(data)
                        or not isinstance(expected_digest, str)
                        or not hmac.compare_digest(hashlib.sha256(data).hexdigest(), expected_digest)):
                    raise HTTPException(422, "Attachment size or SHA-256 validation failed.")
                new_id = str(uuid.uuid4())
                safe_stem = _SAFE_NAME.sub("_", Path(original_name).stem).strip("._")[:80] or "upload"
                stored_name = f"{new_id}_{safe_stem}{extension}"
                target = upload_dir / stored_name
                with target.open("xb") as stream:
                    stream.write(data)
                written_paths.append(target)
                attachment_map[old_id] = new_id
                restored_uploads.append({
                    "id": new_id, "original_name": original_name, "stored_name": stored_name,
                    "content_type": metadata.get("content_type") if isinstance(metadata.get("content_type"), str) else "application/octet-stream",
                    "size_bytes": len(data), "sha256": expected_digest,
                    "extracted_text": metadata.get("extracted_text") if isinstance(metadata.get("extracted_text"), str) else "",
                    "created_at": _now(),
                })

            restored_messages: list[tuple[str, str, str, str, str, str]] = []
            for item in source_messages:
                if not isinstance(item, dict) or item.get("role") not in {"user", "assistant", "system"}:
                    raise HTTPException(422, "Backup contains an invalid message.")
                content = item.get("content")
                old_refs = item.get("attachments", [])
                if not isinstance(content, str) or not content or len(content) > 50000 or not isinstance(old_refs, list) or len(old_refs) > 10:
                    raise HTTPException(422, "Backup message content or attachment references are invalid.")
                if any(not isinstance(ref, str) or ref not in attachment_map for ref in old_refs):
                    raise HTTPException(422, "Backup message references an attachment that is not included.")
                restored_messages.append((
                    str(uuid.uuid4()), "", item["role"], content,
                    json.dumps([attachment_map[ref] for ref in old_refs]), _now(),
                ))
            conversation_id = str(uuid.uuid4())
            con.execute("INSERT INTO chat_conversations(id,title,archived,created_at,updated_at) VALUES(?,?,?,?,?)",
                        (conversation_id, title.strip(), 0, now, now))
            for attachment in restored_uploads:
                con.execute(
                    "INSERT INTO chat_uploads(id,conversation_id,original_name,stored_name,content_type,size_bytes,sha256,extracted_text,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (attachment["id"], conversation_id, attachment["original_name"], attachment["stored_name"],
                     attachment["content_type"], attachment["size_bytes"], attachment["sha256"],
                     attachment["extracted_text"], attachment["created_at"]),
                )
            for message_id, _, role, content, refs_json, created_at in restored_messages:
                con.execute(
                    "INSERT INTO chat_messages(id,conversation_id,role,content,attachments_json,created_at) VALUES(?,?,?,?,?,?)",
                    (message_id, conversation_id, role, content, refs_json, created_at),
                )
            con.commit()
            return {"id": conversation_id, "title": title.strip(), "messages_restored": len(restored_messages),
                    "attachments_restored": len(restored_uploads), "archived": False}
    except HTTPException:
        con.rollback()
        for path in written_paths:
            path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        con.rollback()
        for path in written_paths:
            path.unlink(missing_ok=True)
        raise HTTPException(422, f"Could not restore this backup; no conversation was imported ({type(exc).__name__}: {exc}).") from exc
    finally:
        con.close()


@router.get("/conversations/{conversation_id}/attachments")
def list_attachments(conversation_id: str):
    con = _connect()
    try:
        _require_conversation(con, conversation_id)
        rows = con.execute("SELECT id,original_name,content_type,size_bytes,sha256,created_at FROM chat_uploads WHERE conversation_id=? ORDER BY created_at",
                           (conversation_id,)).fetchall()
        return {"attachments": [dict(row) for row in rows]}
    finally:
        con.close()


@router.post("/conversations/{conversation_id}/attachments", status_code=201)
async def upload_attachment(conversation_id: str, file: UploadFile = File(...)):
    original_name = Path(file.filename or "upload").name
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, "Unsupported file type. Allowed: text, code, CSV, JSON, HTML, YAML, TOML, logs, PDF, PNG, JPEG, WebP, and GIF.")
    # Read at most limit + 1 bytes so Content-Length cannot bypass the limit.
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if not data:
        raise HTTPException(422, "Empty files cannot be uploaded.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File exceeds the 10 MiB upload limit.")
    con = _connect()
    try:
        _require_conversation(con, conversation_id)
        attachment_id = str(uuid.uuid4())
        safe_stem = _SAFE_NAME.sub("_", Path(original_name).stem).strip("._")[:80] or "upload"
        stored_name = f"{attachment_id}_{safe_stem}{extension}"
        upload_dir = settings.workspace / "chat-uploads"
        upload_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if upload_dir.is_symlink():
            raise HTTPException(403, "Upload storage must not be a symbolic link.")
        target = upload_dir / stored_name
        # Exclusive creation avoids overwriting a pre-existing path.
        with target.open("xb") as stream:
            stream.write(data)
        extracted = ""
        extraction_note = ("Image stored for download and preview; image pixels are not yet sent to the model." if extension in IMAGE_EXTENSIONS else None)
        if extension in TEXT_EXTENSIONS:
            try:
                extracted = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                target.unlink(missing_ok=True)
                raise HTTPException(422, "Text files must use UTF-8 encoding.")
        elif extension == ".pdf":
            try:
                reader = PdfReader(BytesIO(data), strict=False)
                if reader.is_encrypted:
                    target.unlink(missing_ok=True)
                    raise HTTPException(422, "Encrypted PDFs are not supported. Upload an unlocked PDF.")
                if len(reader.pages) > 200:
                    target.unlink(missing_ok=True)
                    raise HTTPException(413, "PDF extraction is limited to 200 pages per file.")
                chunks: list[str] = []
                remaining = 200_000
                for page in reader.pages:
                    if remaining <= 0:
                        break
                    page_text = page.extract_text() or ""
                    if page_text:
                        piece = page_text[:remaining]
                        chunks.append(piece)
                        remaining -= len(piece)
                extracted = "\n\n".join(chunks)
                if not extracted.strip():
                    extraction_note = "PDF uploaded, but no selectable text was found. Scanned PDFs need OCR, which is not enabled."
                elif len(extracted) >= 200_000:
                    extraction_note = "PDF text was truncated to 200,000 characters."
            except HTTPException:
                raise
            except Exception as exc:
                target.unlink(missing_ok=True)
                raise HTTPException(422, "Could not read this PDF. Check that it is a valid, uncorrupted PDF.") from exc
        digest = hashlib.sha256(data).hexdigest()
        now = _now()
        con.execute("INSERT INTO chat_uploads(id,conversation_id,original_name,stored_name,content_type,size_bytes,sha256,extracted_text,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (attachment_id, conversation_id, original_name, stored_name,
                     file.content_type or "application/octet-stream", len(data), digest, extracted, now))
        con.commit()
        return {"id": attachment_id, "name": original_name, "content_type": file.content_type or "application/octet-stream",
                "size_bytes": len(data), "sha256": digest, "text_extracted": bool(extracted.strip()),
                "extracted_text": extracted[:200000] if extracted else "",
                "note": extraction_note}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


@router.get("/conversations/{conversation_id}/attachments/{attachment_id}/download")
def download_attachment(conversation_id: str, attachment_id: str):
    con = _connect()
    try:
        _require_conversation(con, conversation_id)
        row = con.execute("SELECT * FROM chat_uploads WHERE id=? AND conversation_id=?",
                          (attachment_id, conversation_id)).fetchone()
        if row is None:
            raise HTTPException(404, "Attachment not found.")
        upload_dir = settings.workspace / "chat-uploads"
        if upload_dir.is_symlink():
            raise HTTPException(403, "Upload storage must not be a symbolic link.")
        path = upload_dir / row["stored_name"]
        if path.is_symlink() or not path.is_file() or path.resolve().parent != upload_dir.resolve():
            raise HTTPException(404, "Stored attachment is unavailable.")
        return FileResponse(path, media_type=row["content_type"], filename=row["original_name"],
                            headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
    finally:
        con.close()


@router.get("/conversations/{conversation_id}/attachments/{attachment_id}")
def get_attachment(conversation_id: str, attachment_id: str):
    con = _connect()
    try:
        _require_conversation(con, conversation_id)
        row = con.execute("SELECT * FROM chat_uploads WHERE id=? AND conversation_id=?",
                          (attachment_id, conversation_id)).fetchone()
        if row is None:
            raise HTTPException(404, "Attachment not found.")
        path = settings.workspace / "chat-uploads" / row["stored_name"]
        if path.is_symlink() or not path.is_file():
            raise HTTPException(404, "Stored attachment is unavailable.")
        return {"id": row["id"], "name": row["original_name"], "content_type": row["content_type"],
                "size_bytes": row["size_bytes"], "sha256": row["sha256"],
                "extracted_text": row["extracted_text"][:200000]}
    finally:
        con.close()
