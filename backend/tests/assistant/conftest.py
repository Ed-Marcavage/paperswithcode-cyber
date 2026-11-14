"""The local macOS tests do not run Linux deployment process accounting."""

import importlib
import os
import sys
from pathlib import Path
from unittest.mock import patch

if sys.platform != "linux":
    original_read = Path.read_text

    def local_process_stat(path, *args, **kwargs):
        if str(path) == f"/proc/{os.getpid()}/stat":
            return "1 (assistant-test) " + " ".join(["0"] * 20)
        return original_read(path, *args, **kwargs)

    # Only the import-time lifecycle singleton needs /proc. The deployed
    # runtime is Linux; keep its implementation and other file reads intact.
    with patch.object(Path, "read_text", local_process_stat):
        importlib.import_module("backend.services.deployment_lifecycle")
