"""Launch the operator-configured LiteRT-LM server without invoking a shell."""
from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from nova.config import settings


def main() -> None:
    command = settings.litert_lm_command.strip()
    if not command:
        raise SystemExit(
            "NOVA_LITERT_LM_COMMAND is not configured. Add the exact server command "
            "to the local .env after checking the installed LiteRT-LM release."
        )
    try:
        argv = shlex.split(command, posix=True)
    except ValueError as exc:
        raise SystemExit("NOVA_LITERT_LM_COMMAND has invalid quoting.") from exc
    if not argv or not argv[0]:
        raise SystemExit("NOVA_LITERT_LM_COMMAND is empty.")
    executable = shutil.which(argv[0])
    if not executable or not os.path.isfile(executable) or not os.access(executable, os.X_OK):
        raise SystemExit("The configured LiteRT-LM executable was not found or is not executable.")
    argv[0] = executable
    os.execvpe(executable, argv, os.environ)


if __name__ == "__main__":
    main()
