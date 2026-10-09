import tempfile
import unittest
from pathlib import Path

from edge_ie_manager.app import Manager
from edge_ie_manager.config import Config


def _manager(tmp: str) -> Manager:
    base = Path(tmp)
    cfg = Config(scope="user", site_list_path=str(base / "sitelist.xml"))
    cfg.config_path = str(base / "config.json")
    return Manager(config=cfg)


class RemoveSitesTests(unittest.TestCase):
    def test_removes_selected_and_skips_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = _manager(tmp)
            manager.add_site("a.example.com")
            manager.add_site("b.example.com")
            result = manager.remove_sites(["a.example.com", "missing.example.com"])
            self.assertTrue(result.ok)
            self.assertIn("已删除 1 条", result.message)
            self.assertTrue(any("跳过" in detail for detail in result.details))
            urls = [site.url for site in manager.site_list.sites]
            self.assertNotIn("a.example.com", urls)
            self.assertIn("b.example.com", urls)

    def test_nothing_found_is_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = _manager(tmp)
            result = manager.remove_sites(["nope.example.com"])
            self.assertFalse(result.ok)
            self.assertEqual(result.level, "warning")


if __name__ == "__main__":
    unittest.main()
