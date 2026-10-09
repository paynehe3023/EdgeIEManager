import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools import sync_version


class VersionHelpersTests(unittest.TestCase):
    def test_tuple_and_dotted_forms(self):
        self.assertEqual(sync_version.version_tuple4("1.0.7"), "1, 0, 7, 0")
        self.assertEqual(sync_version.version_dotted4("1.0.7"), "1.0.7.0")
        self.assertEqual(sync_version.version_tuple4("v2.3"), "2, 3, 0, 0")
        self.assertEqual(sync_version.version_dotted4("2.3.4.5.6"), "2.3.4.5")

    def test_read_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "version.py"
            path.write_text('__version__ = "9.9.9"\n', encoding="utf-8")
            self.assertEqual(sync_version.read_version(path), "9.9.9")


class SyncTests(unittest.TestCase):
    def test_sync_writes_resources_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            changed = sync_version.sync("1.2.3", root=root)
            self.assertEqual(len(changed), 4)

            main = (root / "packaging" / "version_main.txt").read_text(encoding="utf-8")
            self.assertIn("filevers=(1, 2, 3, 0)", main)
            self.assertIn("'FileVersion', '1.2.3.0'", main)
            self.assertIn("'Author', 'payne'", main)
            self.assertIn("947919822", main)

            manifest = json.loads((root / "version.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["version"], "1.2.3")
            self.assertEqual(manifest["sha256"], "")
            self.assertEqual(manifest["size"], 0)
            self.assertTrue(manifest["download"].endswith("EdgeIEManager.exe"))

    def test_artifact_fills_checksum_and_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "EdgeIEManager.exe"
            artifact.write_bytes(b"hello world")
            sync_version.sync("1.2.3", artifact=artifact, root=root)
            manifest = json.loads((root / "version.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["sha256"], hashlib.sha256(b"hello world").hexdigest())
            self.assertEqual(manifest["size"], 11)

    def test_sync_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sync_version.sync("1.2.3", root=root)
            self.assertEqual(sync_version.sync("1.2.3", root=root), [])


class RepoConsistencyTests(unittest.TestCase):
    def test_repo_version_files_match_version_py(self):
        version = sync_version.read_version()
        tuple4 = sync_version.version_tuple4(version)
        for entry in sync_version.EXECUTABLES:
            text = entry["resource"].read_text(encoding="utf-8")
            self.assertIn(f"filevers=({tuple4})", text, entry["resource"].name)
            self.assertIn(f"prodvers=({tuple4})", text, entry["resource"].name)
        manifest = json.loads((sync_version.ROOT / "version.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], version)


if __name__ == "__main__":
    unittest.main()
