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


@pytest.mark.skipif(os.name != "posix" or not hasattr(os, "O_NOFOLLOW"), reason="POSIX no-follow semantics required")
def test_relative_unlink_refuses_symlinked_parent_and_preserves_outside_file(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("preserve", encoding="utf-8")
    (workspace / "link").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(settings, "workspace", workspace)

    with pytest.raises(OSError):
        main._unlink_relative_file("link/secret.txt")
    assert secret.read_text(encoding="utf-8") == "preserve"


@pytest.mark.skipif(os.name != "posix" or not hasattr(os, "O_NOFOLLOW"), reason="POSIX no-follow semantics required")
def test_relative_unlink_removes_leaf_symlink_not_its_target(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("preserve", encoding="utf-8")
    (workspace / "link.txt").symlink_to(outside)
    monkeypatch.setattr(settings, "workspace", workspace)

    assert main._unlink_relative_file("link.txt") is True
    assert not (workspace / "link.txt").exists()
    assert outside.read_text(encoding="utf-8") == "preserve"


def test_relative_unlink_missing_target_is_idempotent(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(settings, "workspace", workspace)

    assert main._unlink_relative_file("missing.txt") is False


@pytest.mark.skipif(os.name != "posix" or not hasattr(os, "O_NOFOLLOW"), reason="POSIX no-follow semantics required")
def test_snapshot_directory_creation_refuses_symlink(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / ".nova-snapshots").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(settings, "workspace", workspace)

    with pytest.raises(OSError):
        main._ensure_snapshot_directory()
    assert list(outside.iterdir()) == []


def test_snapshot_directory_is_created_with_private_permissions(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(settings, "workspace", workspace)

    result = main._ensure_snapshot_directory()
    assert result == workspace / ".nova-snapshots"
    assert result.is_dir()
    if os.name == "posix":
        assert result.stat().st_mode & 0o077 == 0


def test_snapshot_backup_atomic_write_uses_reserved_store_safely(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(settings, "workspace", workspace)
    main._ensure_snapshot_directory()

    backup = workspace.resolve() / ".nova-snapshots" / "test.bak"
    main._atomic_write(backup, b"recovery-state")
    assert main._read_relative_file(".nova-snapshots/test.bak", allow_snapshot=True) == b"recovery-state"
