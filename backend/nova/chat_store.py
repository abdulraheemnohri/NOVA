from __future__ import annotations

import hashlib
from io import BytesIO
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
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
        extraction_note = None
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
