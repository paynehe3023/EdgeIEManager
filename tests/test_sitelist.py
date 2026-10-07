import tempfile
import unittest
from pathlib import Path

from edge_ie_manager.model import Site, SiteMode
from edge_ie_manager.sitelist import (
    SiteList,
    SiteListError,
    load_site_list,
    parse_xml,
    save_site_list,
    to_xml,
)

OFFICIAL_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<site-list version="205">
  <created-by>
    <tool>EnterpriseSitelistManager</tool>
    <version>10240</version>
    <date-created>20150728.135021</date-created>
  </created-by>
  <site url="www.cpandl.com">
    <compat-mode>IE8Enterprise</compat-mode>
    <open-in>MSEdge</open-in>
  </site>
  <site url="contoso.com/travel">
    <compat-mode>IE7</compat-mode>
    <open-in>IE11</open-in>
  </site>
  <site url="relecloud.com"/>
</site-list>
"""


class ParseTests(unittest.TestCase):
    def test_reads_official_sample(self):
        sl = parse_xml(OFFICIAL_SAMPLE)
        self.assertEqual(sl.version, 205)
        self.assertEqual(sl.created_by_tool, "EnterpriseSitelistManager")
        self.assertEqual(len(sl.sites), 3)
        self.assertIs(sl.sites[0].mode, SiteMode.EDGE)
        self.assertEqual(sl.sites[0].compat_mode, "IE8Enterprise")
        self.assertIs(sl.sites[1].mode, SiteMode.IE)
        self.assertEqual(sl.sites[1].url, "contoso.com/travel")
        self.assertIs(sl.sites[2].mode, SiteMode.NEUTRAL)

    def test_rejects_wrong_root(self):
        with self.assertRaises(SiteListError):
            parse_xml("<sites/>")

    def test_rejects_broken_xml(self):
        with self.assertRaises(SiteListError):
            parse_xml("<site-list>")

    def test_missing_version_defaults(self):
        sl = parse_xml("<site-list><site url='a.com'/></site-list>")
        self.assertEqual(sl.version, 1)


class WriteTests(unittest.TestCase):
    def test_roundtrip_keeps_values(self):
        sl = parse_xml(OFFICIAL_SAMPLE)
        text = to_xml(sl)
        again = parse_xml(text)
        self.assertEqual([s.url for s in again.sites], [s.url for s in sl.sites])
        self.assertEqual([s.mode for s in again.sites], [s.mode for s in sl.sites])
        self.assertEqual(again.sites[0].compat_mode, "IE8Enterprise")
        self.assertEqual(again.created_by_tool, "EnterpriseSitelistManager")

    def test_open_in_values(self):
        sl = SiteList(path=Path("x.xml"), version=1)
        sl.sites = [
            Site(url="a.com", mode=SiteMode.NEUTRAL),
            Site(url="b.com", mode=SiteMode.IE),
            Site(url="c.com", mode=SiteMode.EDGE),
        ]
        text = to_xml(sl)
        self.assertIn("<open-in>None</open-in>", text)
        self.assertIn("<open-in>IE11</open-in>", text)
        self.assertIn("<open-in>MSEdge</open-in>", text)


class DocumentTests(unittest.TestCase):
    def test_duplicate_and_replace(self):
        sl = SiteList(path=Path("x.xml"))
        self.assertEqual(sl.add(Site(url="a.com")), "added")
        self.assertEqual(sl.add(Site(url="https://A.com/")), "duplicate")
        self.assertEqual(sl.add(Site(url="a.com", mode=SiteMode.IE), replace=True), "updated")
        self.assertEqual(len(sl.sites), 1)
        self.assertIs(sl.sites[0].mode, SiteMode.IE)

    def test_remove(self):
        sl = SiteList(path=Path("x.xml"))
        sl.add(Site(url="a.com"))
        self.assertTrue(sl.remove("https://a.com/"))
        self.assertFalse(sl.remove("a.com"))


class SaveTests(unittest.TestCase):
    def test_save_bumps_version_and_makes_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sitelist.xml"
            sl = load_site_list(path)
            sl.add(Site(url="report.contoso.com/2026/10", mode=SiteMode.IE))
            save_site_list(sl, path)
            first_version = sl.version
            self.assertEqual(first_version, 1)

            sl.add(Site(url="report.contoso.com/2026/11", mode=SiteMode.IE))
            save_site_list(sl, path)
            self.assertEqual(sl.version, first_version + 1)

            backups = list((Path(tmp) / "backups").glob("sitelist.*.xml"))
            self.assertEqual(len(backups), 1)

            reloaded = load_site_list(path)
            self.assertEqual(len(reloaded.sites), 2)
            self.assertEqual(reloaded.version, 2)

    def test_notes_survive_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sitelist.xml"
            sl = load_site_list(path)
            sl.add(Site(url="a.com", mode=SiteMode.IE, note="月度报表"))
            save_site_list(sl, path)
            reloaded = load_site_list(path)
            self.assertEqual(reloaded.sites[0].note, "月度报表")
            self.assertNotIn("月度报表", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
