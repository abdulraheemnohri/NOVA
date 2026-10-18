import pytest
from fastapi import HTTPException

from nova import main
from nova.config import settings


def test_safe_path_rejects_symlinked_parent(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("outside", encoding="utf-8")
    (workspace / "linked").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(settings, "workspace", workspace)

    with pytest.raises(HTTPException) as exc:
        main._safe_path("linked/secret.txt")
    assert exc.value.status_code == 403


def test_safe_path_rejects_symlinked_leaf(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    workspace.mkdir()
    outside.write_text("outside", encoding="utf-8")
    (workspace / "link.txt").symlink_to(outside)
    monkeypatch.setattr(settings, "workspace", workspace)

    with pytest.raises(HTTPException) as exc:
        main._safe_path("link.txt")
    assert exc.value.status_code == 403


def test_safe_path_rejects_internal_snapshot_store(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(settings, "workspace", workspace)

    with pytest.raises(HTTPException) as exc:
        main._safe_path(".nova-snapshots/backup.bak")
    assert exc.value.status_code == 403


@pytest.mark.parametrize("relative_path", ["../escape.txt", "/absolute.txt", "nested/../../escape.txt"])
def test_safe_path_rejects_traversal_and_absolute_paths(tmp_path, monkeypatch, relative_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(settings, "workspace", workspace)

    with pytest.raises(HTTPException) as exc:
        main._safe_path(relative_path)
    assert exc.value.status_code == 403
