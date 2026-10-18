from contextlib import contextmanager
from io import BytesIO

from pypdf import PdfWriter

from fastapi.testclient import TestClient

from nova.config import settings
from nova.main import app


@contextmanager
def _client():
    with TestClient(app) as client:
        token = settings.api_token_file.read_text(encoding="utf-8").strip()
        client.headers.update({"Authorization": f"Bearer {token}"})
        yield client


def _configure_temp_store(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "api_token_file", tmp_path / "api.token")
    monkeypatch.setattr(settings, "workspace", tmp_path / "workspace")
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    settings.workspace.mkdir(parents=True, exist_ok=True)


def test_conversation_messages_and_attachment_lifecycle(monkeypatch, tmp_path):
    _configure_temp_store(monkeypatch, tmp_path)
    with _client() as client:
        created = client.post("/api/chat/conversations", json={"title": "New chat"})
        assert created.status_code == 201, created.text
        conversation_id = created.json()["id"]

        uploaded = client.post(
            f"/api/chat/conversations/{conversation_id}/attachments",
            files={"file": ("notes.txt", b"Local-first chat notes", "text/plain")},
        )
        assert uploaded.status_code == 201, uploaded.text
        attachment = uploaded.json()
        assert attachment["text_extracted"] is True
        assert attachment["extracted_text"] == "Local-first chat notes"

        saved = client.post(
            f"/api/chat/conversations/{conversation_id}/messages",
            json={"role": "user", "content": "Summarize this file", "attachments": [attachment["id"]]},
        )
        assert saved.status_code == 201, saved.text
        listed = client.get(f"/api/chat/conversations/{conversation_id}/messages")
        assert listed.status_code == 200
        assert listed.json()["messages"][0]["attachments"] == [attachment["id"]]

        download = client.get(
            f"/api/chat/conversations/{conversation_id}/attachments/{attachment['id']}/download"
        )
        assert download.status_code == 200
        assert download.content == b"Local-first chat notes"

        deleted = client.delete(f"/api/chat/conversations/{conversation_id}")
        assert deleted.status_code == 204
        assert client.get(f"/api/chat/conversations/{conversation_id}/messages").status_code == 404
        upload_dir = settings.workspace / "chat-uploads"
        assert not list(upload_dir.iterdir())


def test_chat_upload_rejects_unsupported_type_and_oversized_file(monkeypatch, tmp_path):
    _configure_temp_store(monkeypatch, tmp_path)
    with _client() as client:
        conversation = client.post("/api/chat/conversations", json={"title": "Uploads"}).json()
        cid = conversation["id"]
        unsupported = client.post(
            f"/api/chat/conversations/{cid}/attachments",
            files={"file": ("program.exe", b"not executable", "application/octet-stream")},
        )
        assert unsupported.status_code == 415
        oversized = client.post(
            f"/api/chat/conversations/{cid}/attachments",
            files={"file": ("large.txt", b"x" * (10 * 1024 * 1024 + 1), "text/plain")},
        )
        assert oversized.status_code == 413


def test_chat_message_cannot_reference_another_conversations_attachment(monkeypatch, tmp_path):
    _configure_temp_store(monkeypatch, tmp_path)
    with _client() as client:
        first = client.post("/api/chat/conversations", json={"title": "First"}).json()
        second = client.post("/api/chat/conversations", json={"title": "Second"}).json()
        uploaded = client.post(
            f"/api/chat/conversations/{first['id']}/attachments",
            files={"file": ("notes.md", b"private attachment", "text/markdown")},
        ).json()
        response = client.post(
            f"/api/chat/conversations/{second['id']}/messages",
            json={"role": "user", "content": "Read it", "attachments": [uploaded["id"]]},
        )
        assert response.status_code == 422



def test_pdf_upload_extracts_text_or_reports_scanned_pdf_limit(monkeypatch, tmp_path):
    _configure_temp_store(monkeypatch, tmp_path)
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    pdf = BytesIO()
    writer.write(pdf)
    with _client() as client:
        conversation = client.post("/api/chat/conversations", json={"title": "PDF"}).json()
        response = client.post(
            f"/api/chat/conversations/{conversation['id']}/attachments",
            files={"file": ("blank.pdf", pdf.getvalue(), "application/pdf")},
        )
        assert response.status_code == 201, response.text
        attachment = response.json()
        assert attachment["text_extracted"] is False
        assert "OCR" in attachment["note"]

        malformed = client.post(
            f"/api/chat/conversations/{conversation['id']}/attachments",
            files={"file": ("broken.pdf", b"not a PDF", "application/pdf")},
        )
        assert malformed.status_code == 422



def test_image_attachment_is_stored_and_downloadable_without_text_decoding(monkeypatch, tmp_path):
    _configure_temp_store(monkeypatch, tmp_path)
    # Minimal PNG signature; this endpoint stores files and does not decode image pixels.
    png = b"\x89PNG\r\n\x1a\n" + b"image-payload"
    with _client() as client:
        conversation = client.post("/api/chat/conversations", json={"title": "Images"}).json()
        cid = conversation["id"]
        uploaded = client.post(
            f"/api/chat/conversations/{cid}/attachments",
            files={"file": ("diagram.png", png, "image/png")},
        )
        assert uploaded.status_code == 201, uploaded.text
        attachment = uploaded.json()
        assert attachment["content_type"] == "image/png"
        assert attachment["text_extracted"] is False
        assert "image pixels" in (attachment["note"] or "")
        downloaded = client.get(
            f"/api/chat/conversations/{cid}/attachments/{attachment['id']}/download"
        )
        assert downloaded.status_code == 200
        assert downloaded.content == png


def test_chat_exports_json_and_markdown_without_embedding_upload_bytes(monkeypatch, tmp_path):
    _configure_temp_store(monkeypatch, tmp_path)
    with _client() as client:
        conversation = client.post("/api/chat/conversations", json={"title": "Export me"}).json()
        cid = conversation["id"]
        uploaded = client.post(
            f"/api/chat/conversations/{cid}/attachments",
            files={"file": ("notes.txt", b"private extracted text", "text/plain")},
        )
        assert uploaded.status_code == 201, uploaded.text
        attachment = uploaded.json()
        saved = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"role": "user", "content": "Please keep this", "attachments": [attachment["id"]]},
        )
        assert saved.status_code == 201

        json_export = client.get(f"/api/chat/conversations/{cid}/export?format=json")
        assert json_export.status_code == 200
        assert "attachment; filename=" in json_export.headers["content-disposition"]
        payload = json_export.json()
        assert payload["schema_version"] == 1
        assert payload["conversation"]["title"] == "Export me"
        assert payload["messages"][0]["content"] == "Please keep this"
        assert payload["messages"][0]["attachments"] == [attachment["id"]]
        assert payload["attachments"][0]["sha256"] == attachment["sha256"]
        assert "binary files are not embedded" in payload["attachment_policy"].lower()

        markdown_export = client.get(f"/api/chat/conversations/{cid}/export?format=markdown")
        assert markdown_export.status_code == 200
        assert "text/markdown" in markdown_export.headers["content-type"]
        assert "# Export me" in markdown_export.text
        assert "Please keep this" in markdown_export.text
        assert "notes.txt" in markdown_export.text
        assert "private extracted text" in markdown_export.text

        invalid = client.get(f"/api/chat/conversations/{cid}/export?format=html")
        assert invalid.status_code == 422
        missing = client.get("/api/chat/conversations/not-a-real-id/export")
        assert missing.status_code == 404


def test_chat_zip_backup_contains_transcript_and_original_attachment(monkeypatch, tmp_path):
    import json
    import zipfile
    from io import BytesIO

    _configure_temp_store(monkeypatch, tmp_path)
    with _client() as client:
        conversation = client.post("/api/chat/conversations", json={"title": "Zip backup"}).json()
        cid = conversation["id"]
        uploaded = client.post(
            f"/api/chat/conversations/{cid}/attachments",
            files={"file": ("backup-notes.txt", b"archive payload", "text/plain")},
        )
        assert uploaded.status_code == 201, uploaded.text
        attachment = uploaded.json()
        client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"role": "user", "content": "Export all of this", "attachments": [attachment["id"]]},
        )
        response = client.get(f"/api/chat/conversations/{cid}/export?format=zip")
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("application/zip")
        with zipfile.ZipFile(BytesIO(response.content)) as archive:
            names = archive.namelist()
            assert "conversation.json" in names
            assert "conversation.md" in names
            attachment_name = next(name for name in names if name.startswith("attachments/"))
            assert archive.read(attachment_name) == b"archive payload"
            payload = json.loads(archive.read("conversation.json"))
            assert payload["conversation"]["title"] == "Zip backup"
            assert payload["messages"][0]["content"] == "Export all of this"
