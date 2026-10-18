import os

import pytest

from nova import main
from nova.config import settings


@pytest.mark.skipif(os.name != "posix" or not hasattr(os, "O_NOFOLLOW"), reason="POSIX no-follow semantics required")
def test_relative_read_refuses_symlinked_leaf(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    workspace.mkdir()
    outside.write_text("secret", encoding="utf-8")
    (workspace / "link.txt").symlink_to(outside)
    monkeypatch.setattr(settings, "workspace", workspace)

    with pytest.raises(OSError):
        main._read_relative_file("link.txt")


@pytest.mark.skipif(os.name != "posix" or not hasattr(os, "O_NOFOLLOW"), reason="POSIX no-follow semantics required")
def test_relative_read_refuses_symlinked_parent(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    (workspace / "link").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(settings, "workspace", workspace)

    with pytest.raises(OSError):
        main._read_relative_file("link/secret.txt")


def test_relative_read_accepts_regular_workspace_file(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_bytes(b"safe")
    monkeypatch.setattr(settings, "workspace", workspace)

    assert main._read_relative_file("notes.txt") == b"safe"


def test_snapshot_read_requires_internal_snapshot_prefix(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("not a snapshot", encoding="utf-8")
    monkeypatch.setattr(settings, "workspace", workspace)

    with pytest.raises(OSError):
        main._read_relative_file("notes.txt", allow_snapshot=True)
