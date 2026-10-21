"""Optional Linux bubblewrap launch policy for MCP stdio child processes.

This provides write-containment defense-in-depth, not a complete sandbox:
host files remain readable and networking is not isolated. Use a dedicated
low-privilege NOVA account as well.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path


class SandboxUnavailableError(RuntimeError):
    """Raised when a requested sandbox cannot be used safely."""


def build_mcp_command(executable: str, args: list[str], workspace: Path, mode: str, *, bwrap_path: str | None = None) -> list[str]:
    """Build argv for an MCP child; requested sandboxing never silently falls back."""
    if mode == "off":
        return [executable, *args]
    if mode != "bwrap-readonly-root":
        raise SandboxUnavailableError("Unknown MCP sandbox mode.")
    if not sys.platform.startswith("linux"):
        raise SandboxUnavailableError("bubblewrap MCP mode is supported only on Linux.")
    resolved_bwrap = bwrap_path if bwrap_path is not None else shutil.which("bwrap")
    if not resolved_bwrap:
        raise SandboxUnavailableError("MCP sandbox mode requires bubblewrap ('bwrap') installed and usable on PATH.")
    workspace_path = str(Path(workspace).resolve())
    return [resolved_bwrap, "--die-with-parent", "--new-session", "--ro-bind", "/", "/", "--bind", workspace_path, workspace_path, "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--chdir", workspace_path, "--", executable, *args]
