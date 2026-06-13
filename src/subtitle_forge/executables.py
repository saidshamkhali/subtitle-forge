from __future__ import annotations

import os
import shutil
from pathlib import Path


def resolve_executable(command: str) -> str | None:
    executable = shutil.which(command)
    if not executable:
        return None

    if os.name == "nt" and not Path(executable).suffix:
        for suffix in (".cmd", ".exe", ".bat"):
            candidate = f"{executable}{suffix}"
            if Path(candidate).exists():
                return candidate

    return executable
