"""Redirect persistence in tests with fake engines away from real user files."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
from unittest.mock import patch


def config_sandbox():
    stack = ExitStack()
    folder = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="mouser-config-test-")))
    for name, value in {"CONFIG_DIR": str(folder), "CONFIG_FILE": str(folder / "config.json"),
                        "CONFIG_BACKUP_DIR": str(folder / "config_backups"),
                        "_LAST_AUTO_BACKUP_AT": 0.0}.items():
        stack.enter_context(patch("core.config." + name, value))
    return stack
