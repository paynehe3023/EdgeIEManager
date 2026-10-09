import time
import unittest

from edge_ie_manager import update


class ParseVersionTests(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(update.parse_version("1.2.3"), (1, 2, 3))

    def test_strips_v_prefix(self):
        self.assertEqual(update.parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(update.parse_version("V2.0"), (2, 0))

    def test_ignores_prerelease_suffix(self):
        self.assertEqual(update.parse_version("1.2.0-beta.1"), (1, 2, 0))
        self.assertEqual(update.parse_version("1.2.3+build5"), (1, 2, 3))

    def test_missing_parts_and_garbage(self):
        self.assertEqual(update.parse_version("1"), (1,))
        self.assertEqual(update.parse_version(""), (0,))
        self.assertEqual(update.parse_version("abc"), (0,))


class IsNewerTests(unittest.TestCase):
    def test_basic_ordering(self):
        self.assertTrue(update.is_newer("1.0.1", "1.0.0"))
        self.assertTrue(update.is_newer("1.1.0", "1.0.9"))
        self.assertTrue(update.is_newer("2.0.0", "1.9.9"))
        self.assertFalse(update.is_newer("1.0.0", "1.0.0"))
        self.assertFalse(update.is_newer("0.9.9", "1.0.0"))

    def test_different_lengths_are_zero_padded(self):
        self.assertFalse(update.is_newer("1.0", "1.0.0"))
        self.assertTrue(update.is_newer("1.0.1", "1.0"))
        self.assertFalse(update.is_newer("1", "1.0.0"))

    def test_tag_style_input(self):
        self.assertTrue(update.is_newer("v1.2.0", "1.1.9"))


class UpdateInfoTests(unittest.TestCase):
    def test_display_adds_prefix(self):
        self.assertEqual(update.UpdateInfo(version="1.2.0", download_url="u").display, "v1.2.0")
        self.assertEqual(update.UpdateInfo(version="v1.2.0", download_url="u").display, "v1.2.0")


class CheckForUpdateTests(unittest.TestCase):
    def test_empty_repo_is_rejected_without_network(self):
        with self.assertRaises(update.UpdateError):
            update.check_for_update("")
        with self.assertRaises(update.UpdateError):
            update.check_for_update("   ")


class SelfUpdateTests(unittest.TestCase):
    def test_source_run_cannot_self_update(self):
        # 单元测试跑在源码环境（非 frozen），应当明确不支持自动替换
        self.assertIsNone(update.current_exe())
        self.assertFalse(update.can_self_update())


class DeadlineTests(unittest.TestCase):
    """urlopen 的 timeout 管不住 DNS 解析，_run_with_deadline 负责硬超时。"""

    def test_returns_value(self):
        self.assertEqual(update._run_with_deadline(lambda: 42, 5), 42)

    def test_propagates_exception(self):
        def boom():
            raise ValueError("坏掉了")

        with self.assertRaises(ValueError):
            update._run_with_deadline(boom, 5)

    def test_times_out_on_stuck_call(self):
        started = time.monotonic()
        with self.assertRaises(update.UpdateTimeout):
            update._run_with_deadline(lambda: time.sleep(30), 0.2)
        # 要在超时时间附近返回，而不是等满 30 秒
        self.assertLess(time.monotonic() - started, 5)


if __name__ == "__main__":
    unittest.main()
