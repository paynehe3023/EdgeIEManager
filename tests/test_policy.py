import unittest

from edge_ie_manager import policy as policy_module
from edge_ie_manager.policy import (
    IE_MODE_LEVEL,
    export_reg_text,
    is_scope_writable,
    read_policy,
)


class ExportRegTests(unittest.TestCase):
    def test_user_scope(self):
        text = export_reg_text("user", "file:///C:/tmp/sitelist.xml")
        self.assertIn("Windows Registry Editor Version 5.00", text)
        self.assertIn(r"[HKEY_CURRENT_USER\SOFTWARE\Policies\Microsoft\Edge]", text)
        self.assertIn('"InternetExplorerIntegrationSiteList"="file:///C:/tmp/sitelist.xml"', text)
        self.assertIn(f'"InternetExplorerIntegrationLevel"=dword:{IE_MODE_LEVEL:08x}', text)

    def test_machine_scope_and_refresh(self):
        text = export_reg_text("machine", "file:///C:/a.xml", refresh_interval=60)
        self.assertIn(r"[HKEY_LOCAL_MACHINE\SOFTWARE\Policies\Microsoft\Edge]", text)
        self.assertIn('"InternetExplorerIntegrationSiteListRefreshInterval"=dword:0000003c', text)

    def test_no_refresh_line_when_zero(self):
        text = export_reg_text("user", "file:///C:/a.xml", refresh_interval=0)
        self.assertNotIn("RefreshInterval", text)


class ReadPolicyTests(unittest.TestCase):
    def test_read_user_scope_does_not_throw(self):
        state = read_policy("user")
        self.assertEqual(state.scope, "user")
        self.assertIsInstance(state.summary(), str)


class ScopeWritableTests(unittest.TestCase):
    def test_returns_bool_for_both_scopes(self):
        for scope in ("user", "machine"):
            self.assertIsInstance(is_scope_writable(scope), bool)

    def test_permission_denied_is_not_writable(self):
        from unittest import mock

        fake = mock.MagicMock()
        fake.OpenKey.side_effect = PermissionError(5, "拒绝访问")
        with mock.patch.object(policy_module, "winreg", fake):
            self.assertFalse(policy_module.is_scope_writable("user"))

    def test_missing_key_falls_back_to_parent_create_rights(self):
        from unittest import mock

        fake = mock.MagicMock()
        # 第一次“策略键不存在”，第二次探测父键的创建权限成功。
        fake.OpenKey.side_effect = [FileNotFoundError(), mock.MagicMock()]
        with mock.patch.object(policy_module, "winreg", fake):
            self.assertTrue(policy_module.is_scope_writable("user"))


if __name__ == "__main__":
    unittest.main()
