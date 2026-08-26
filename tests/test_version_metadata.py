import subprocess
import unittest
from unittest.mock import patch

from core import version


class _FakeStartupInfo:
    def __init__(self):
        self.dwFlags = 0
        self.wShowWindow = None


class VersionMetadataTests(unittest.TestCase):
    def test_frozen_app_does_not_probe_git_for_commit(self):
        with (
            patch("core.version._is_frozen_app", return_value=True),
            patch("core.version.subprocess.check_output") as check_output,
        ):
            self.assertEqual(version._run_git(["rev-parse", "HEAD"]), "")

        check_output.assert_not_called()

    def test_frozen_app_does_not_probe_git_for_dirty_state(self):
        with (
            patch("core.version._is_frozen_app", return_value=True),
            patch("core.version.subprocess.run") as run,
        ):
            self.assertFalse(version._git_dirty())

        run.assert_not_called()

    def test_source_git_probe_hides_windows_console_window(self):
        with (
            patch("core.version._is_frozen_app", return_value=False),
            patch("core.version.sys.platform", "win32"),
            patch.object(subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True),
            patch.object(
                subprocess, "STARTF_USESHOWWINDOW", 0x00000001, create=True
            ),
            patch.object(subprocess, "SW_HIDE", 0, create=True),
            patch.object(subprocess, "STARTUPINFO", _FakeStartupInfo, create=True),
            patch(
                "core.version.subprocess.check_output",
                return_value="abc123\n",
            ) as check_output,
        ):
            self.assertEqual(version._run_git(["rev-parse", "HEAD"]), "abc123")

        kwargs = check_output.call_args.kwargs
        self.assertEqual(kwargs["creationflags"], 0x08000000)
        self.assertEqual(kwargs["startupinfo"].dwFlags, 0x00000001)
        self.assertEqual(kwargs["startupinfo"].wShowWindow, 0)


if __name__ == "__main__":
    unittest.main()
