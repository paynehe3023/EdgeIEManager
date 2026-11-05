import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from edge_ie_manager import cli


class ElevateReportTests(unittest.TestCase):
    """提权子进程的控制台是隐藏的，失败原因只能靠 --report-file 回传。"""

    def test_install_shows_child_log_and_keeps_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            expected_report = Path(tmp) / "elevate-last.log"

            def fake_run_elevated(args, wait=True, report_file=None):
                if report_file:
                    Path(report_file).write_text(
                        "[i] 有效账户：DOMAIN\\user\n"
                        "[!] 写入策略失败：[WinError 5] 拒绝访问。\n",
                        encoding="utf-8",
                    )
                return True, 3

            out = io.StringIO()
            with mock.patch.object(cli.policy, "is_admin", return_value=False), mock.patch.object(
                cli.policy, "run_elevated", side_effect=fake_run_elevated
            ) as run_elevated:
                with redirect_stdout(out):
                    code = cli.main(
                        ["--config", str(config), "policy", "install", "--elevate"]
                    )

            self.assertEqual(code, 3)
            self.assertIn("返回错误码 3", out.getvalue())
            self.assertIn("拒绝访问", out.getvalue())
            report_arg = run_elevated.call_args.kwargs.get("report_file")
            self.assertEqual(Path(report_arg), expected_report)

    def test_uninstall_shows_child_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"

            def fake_run_elevated(args, wait=True, report_file=None):
                if report_file:
                    Path(report_file).write_text("[!] 提权失败\n", encoding="utf-8")
                return True, 2

            out = io.StringIO()
            with mock.patch.object(cli.policy, "is_admin", return_value=False), mock.patch.object(
                cli.policy, "run_elevated", side_effect=fake_run_elevated
            ):
                with redirect_stdout(out):
                    code = cli.main(
                        ["--config", str(config), "policy", "uninstall", "--elevate"]
                    )

            self.assertEqual(code, 2)
            self.assertIn("提权失败", out.getvalue())


if __name__ == "__main__":
    unittest.main()
