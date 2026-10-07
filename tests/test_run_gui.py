import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run_gui


class CliArgsTests(unittest.TestCase):
    def test_no_args_opens_gui(self):
        self.assertIsNone(run_gui.cli_args([]))
        self.assertIsNone(run_gui.cli_args([], config_path=None))

    def test_args_are_forwarded(self):
        args = run_gui.cli_args(["policy", "status"])
        self.assertEqual(args, ["policy", "status"])

    def test_config_is_injected_for_clean_build(self):
        args = run_gui.cli_args(["policy", "status"], config_path=r"C:\data\config.json")
        self.assertEqual(args[:2], ["--config", r"C:\data\config.json"])
        self.assertIn("policy", args)

    def test_explicit_config_is_respected(self):
        args = run_gui.cli_args(
            ["--config", r"D:\other.json", "policy", "status"],
            config_path=r"C:\data\config.json",
        )
        self.assertEqual(args.count("--config"), 1)
        self.assertIn(r"D:\other.json", args)
        self.assertNotIn(r"C:\data\config.json", args)


if __name__ == "__main__":
    unittest.main()
