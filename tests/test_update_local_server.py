"""用本地假更新源验证整条更新链路。

这里不碰 GitHub，也不依赖打包好的 exe：把任意文件当作"新版本安装包"，
检查清单读取、下载、取消三件事是否按预期工作。
"""

from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from edge_ie_manager import update  # noqa: E402

SERVER_SCRIPT = ROOT / "tools" / "local_update_server.py"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_ready(base_url: str, attempts: int = 60) -> bool:
    for _ in range(attempts):
        try:
            with urlopen(f"{base_url}/version.json", timeout=0.5) as response:
                response.read()
            return True
        except Exception:
            time.sleep(0.1)
    return False


class LocalUpdateServerTests(unittest.TestCase):
    """启动一个本地更新源，验证检查更新与下载行为。"""

    @classmethod
    def setUpClass(cls) -> None:
        if not SERVER_SCRIPT.is_file():
            raise unittest.SkipTest("找不到 tools/local_update_server.py")
        cls.asset_bytes = b"fake-installer-" + b"x" * 4096
        cls.tmp = tempfile.TemporaryDirectory()
        cls.asset = Path(cls.tmp.name) / "EdgeIEManager.exe"
        cls.asset.write_bytes(cls.asset_bytes)
        cls.port = _free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.server = subprocess.Popen(
            [
                sys.executable,
                str(SERVER_SCRIPT),
                "--exe",
                str(cls.asset),
                "--version",
                "9.9.9",
                "--port",
                str(cls.port),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not _wait_ready(cls.base):
            cls.server.kill()
            cls.tmp.cleanup()
            raise RuntimeError("本地更新源没有启动成功")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover
            cls.server.kill()
        cls.tmp.cleanup()

    def test_manifest_override_points_at_local_server(self) -> None:
        with mock.patch.dict(os.environ, {update.BASE_URL_ENV: self.base}):
            info = update.check_for_update("owner/repo")
        self.assertIsNotNone(info)
        assert info is not None  # for type checkers
        self.assertEqual(info.version, "9.9.9")
        self.assertEqual(info.download_url, f"{self.base}/{update.ASSET_NAME}")
        self.assertEqual(info.sha256, hashlib.sha256(self.asset_bytes).hexdigest())
        self.assertEqual(info.size, len(self.asset_bytes))

    def test_download_from_local_server_matches_payload(self) -> None:
        with mock.patch.dict(os.environ, {update.BASE_URL_ENV: self.base}):
            info = update.check_for_update("owner/repo")
            assert info is not None
            dest = Path(self.tmp.name) / "downloaded.exe"
            events: list[tuple[int, int]] = []
            update.download(info, dest, progress=lambda done, total: events.append((done, total)))
        self.assertEqual(dest.read_bytes(), self.asset_bytes)
        self.assertEqual(events[0], (0, -1))
        self.assertEqual(events[-1][0], len(self.asset_bytes))

    def test_sha256_mismatch_is_rejected_and_discarded(self) -> None:
        with mock.patch.dict(os.environ, {update.BASE_URL_ENV: self.base}):
            info = update.check_for_update("owner/repo")
            assert info is not None
            info.sha256 = "0" * 64
            dest = Path(self.tmp.name) / "bad.exe"
            with self.assertRaises(update.UpdateError):
                update.download(info, dest)
        self.assertFalse(dest.exists(), "校验失败后应当删除文件")


class CancelDownloadTests(unittest.TestCase):
    """限速下载，验证取消能中途生效且不留残留文件。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = b"y" * (2 * 1024 * 1024)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.asset = Path(cls.tmp.name) / "EdgeIEManager.exe"
        cls.asset.write_bytes(cls.payload)
        cls.port = _free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.server = subprocess.Popen(
            [
                sys.executable,
                str(SERVER_SCRIPT),
                "--exe",
                str(cls.asset),
                "--version",
                "9.9.9",
                "--port",
                str(cls.port),
                "--kbps",
                "400",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not _wait_ready(cls.base):
            cls.server.kill()
            cls.tmp.cleanup()
            raise RuntimeError("限速更新源没有启动成功")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover
            cls.server.kill()
        cls.tmp.cleanup()

    def test_cancel_stops_download_and_removes_partial_file(self) -> None:
        import threading

        with mock.patch.dict(os.environ, {update.BASE_URL_ENV: self.base}):
            info = update.check_for_update("owner/repo")
            assert info is not None
            dest = Path(self.tmp.name) / "cancelled.exe"
            token = update.CancelToken()
            threading.Timer(0.4, token.cancel).start()
            started = time.monotonic()
            with self.assertRaises(update.UpdateCancelled):
                update.download(info, dest, progress=lambda *_: None, token=token)
            elapsed = time.monotonic() - started
        self.assertFalse(dest.exists(), "取消后不应残留半成品文件")
        # 2MB 限速 400KB/s 需要约 5 秒，能在 3 秒内结束说明确实被打断了
        self.assertLess(elapsed, 3.0, f"取消耗时 {elapsed:.2f}s，像是没有真正中断")


if __name__ == "__main__":
    unittest.main()
