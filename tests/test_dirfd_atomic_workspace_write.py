import os

import pytest
from fastapi import HTTPException

from nova import main
from nova.config import settings


@pytest.mark.skipif(os.name != "posix" or not hasattr(os, "O_NOFOLLOW"), reason="POSIX no-follow semantics required")
def test_atomic_write_does_not_follow_parent_swapped_to_symlink(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    nested = workspace / "nested"
    outside = tmp_path / "outside"
    nested.mkdir(parents=True)
    outside.mkdir()
    monkeypatch.setattr(settings, "workspace", workspace)

    target = main._safe_path("nested/created.txt")
    nested.rename(workspace / "original-nested")
    nested.symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError):
        main._atomic_write(target, b"must stay inside workspace")

    assert not (outside / "created.txt").exists()
    assert not (workspace / "nested" / "created.txt").exists()


@pytest.mark.skipif(os.name != "posix" or not hasattr(os, "O_NOFOLLOW"), reason="POSIX no-follow semantics required")
def test_atomic_write_creates_missing_parent_directories_safely(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(settings, "workspace", workspace)

    target = main._safe_path("new/nested/created.txt")
    main._atomic_write(target, b"safe content")

    assert (workspace / "new" / "nested" / "created.txt").read_bytes() == b"safe content"
