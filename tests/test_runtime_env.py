"""PyInstaller 引导变量清理逻辑的回归测试。"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from edge_ie_manager import policy, runtime_env, update


class CleanEnvironmentTests(unittest.TestCase):
    def test_strips_pyinstaller_variables(self) -> None:
        env = {
            "_PYI_ARCHIVE_FILE": r"C:\tools\EdgeIEManager.exe",
            "_PYI_PARENT_PROCESS_LEVEL": "1",
            "_PYI_APPLICATION_HOME_DIR": r"C:\Temp\_MEI12345678",
            "_PYI_SPLASH_IPC": "0",
            "_MEIPASS2": r"C:\Temp\_MEI12345678",
            "PATH": r"C:\Windows",
            "LOCALAPPDATA": r"C:\Users\payne\AppData\Local",
        }
        cleaned = runtime_env.clean_environment(env)
        self.assertEqual(sorted(cleaned), ["LOCALAPPDATA", "PATH"])

    def test_matches_prefix_case_insensitively(self) -> None:
        env = {"_pyi_archive_file": "x", "KEEP": "y"}
        self.assertEqual(runtime_env.clean_environment(env), {"KEEP": "y"})

    def test_defaults_to_process_environment(self) -> None:
        with mock.patch.dict(
            os.environ, {"_PYI_ARCHIVE_FILE": "x", "EDGE_IE_SPECIAL": "y"}, clear=False
        ):
            cleaned = runtime_env.clean_environment()
        self.assertNotIn("_PYI_ARCHIVE_FILE", cleaned)
        self.assertEqual(cleaned["EDGE_IE_SPECIAL"], "y")


class StrippedEnvironmentTests(unittest.TestCase):
    def test_removes_then_restores(self) -> None:
        with mock.patch.dict(
            os.environ, {"_PYI_ARCHIVE_FILE": "x", "KEEP": "y"}, clear=False
        ):
            with runtime_env.stripped_bootstrap_environment():
                self.assertNotIn("_PYI_ARCHIVE_FILE", os.environ)
                self.assertEqual(os.environ["KEEP"], "y")
            self.assertEqual(os.environ["_PYI_ARCHIVE_FILE"], "x")

    def test_restores_even_when_body_raises(self) -> None:
        with mock.patch.dict(os.environ, {"_PYI_ARCHIVE_FILE": "x"}, clear=False):
            with self.assertRaises(RuntimeError):
                with runtime_env.stripped_bootstrap_environment():
                    raise RuntimeError("boom")
            self.assertEqual(os.environ["_PYI_ARCHIVE_FILE"], "x")


class RestartTests(unittest.TestCase):
    def test_restart_spawns_with_cleaned_environment(self) -> None:
        dirty = {
            "_PYI_ARCHIVE_FILE": r"C:\tools\EdgeIEManager.exe",
            "_PYI_PARENT_PROCESS_LEVEL": "1",
            "_PYI_APPLICATION_HOME_DIR": r"C:\Temp\_MEI1",
            "KEEP_ME": "1",
        }
        with mock.patch.dict(os.environ, dirty, clear=False):
            with mock.patch.object(update.subprocess, "Popen") as popen:
                update.restart(r"C:\tools\EdgeIEManager.exe")

        args, kwargs = popen.call_args
        self.assertEqual(args[0], [r"C:\tools\EdgeIEManager.exe"])
        self.assertNotIn("_PYI_ARCHIVE_FILE", kwargs["env"])
        self.assertNotIn("_PYI_PARENT_PROCESS_LEVEL", kwargs["env"])
        self.assertNotIn("_PYI_APPLICATION_HOME_DIR", kwargs["env"])
        self.assertEqual(kwargs["env"]["KEEP_ME"], "1")


class RunElevatedTests(unittest.TestCase):
    def test_elevation_hides_bootstrap_variables(self) -> None:
        seen: dict[str, bool] = {}

        def fake_shell_execute(_info) -> int:
            seen["leaked"] = "_PYI_ARCHIVE_FILE" in os.environ
            return 1

        with mock.patch.dict(os.environ, {"_PYI_ARCHIVE_FILE": "x"}, clear=False):
            with mock.patch.object(
                policy.ctypes.windll.shell32,
                "ShellExecuteExW",
                side_effect=fake_shell_execute,
            ):
                started, code = policy.run_elevated(["--help"], wait=False)
            self.assertEqual(os.environ["_PYI_ARCHIVE_FILE"], "x")

        self.assertTrue(started)
        self.assertEqual(code, 0)
        self.assertFalse(seen["leaked"])


if __name__ == "__main__":
    unittest.main()
