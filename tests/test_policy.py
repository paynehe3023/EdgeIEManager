import unittest

from edge_ie_manager.policy import (
    IE_MODE_LEVEL,
    export_reg_text,
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


if __name__ == "__main__":
    unittest.main()
