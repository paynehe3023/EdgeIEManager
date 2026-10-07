import unittest

from edge_ie_manager.model import (
    SiteMode,
    normalize_url,
    parse_mode,
    strip_scheme,
    validate_url,
)


class StripSchemeTests(unittest.TestCase):
    def test_removes_http_and_https(self):
        self.assertEqual(strip_scheme("https://report.contoso.com/2026/10"), "report.contoso.com/2026/10")
        self.assertEqual(strip_scheme("http://report.contoso.com"), "report.contoso.com")

    def test_keeps_plain_host(self):
        self.assertEqual(strip_scheme("report.contoso.com/a"), "report.contoso.com/a")


class NormalizeUrlTests(unittest.TestCase):
    def test_case_and_scheme_insensitive(self):
        self.assertEqual(
            normalize_url("HTTPS://Report.Contoso.com/2026/10/"),
            normalize_url("report.contoso.com/2026/10"),
        )


class ValidateUrlTests(unittest.TestCase):
    def test_accepts_plain_host(self):
        value, warning = validate_url("report.contoso.com/2026/10")
        self.assertEqual(value, "report.contoso.com/2026/10")
        self.assertIsNone(warning)

    def test_strips_scheme_with_warning(self):
        value, warning = validate_url("https://report.contoso.com")
        self.assertEqual(value, "report.contoso.com")
        self.assertIsNotNone(warning)

    def test_rejects_other_scheme(self):
        value, warning = validate_url("ftp://files.contoso.com")
        self.assertIsNone(value)
        self.assertIn("ftp", warning or "")

    def test_rejects_spaces_and_empty(self):
        self.assertIsNone(validate_url("   ")[0])
        self.assertIsNone(validate_url("report contoso.com")[0])

    def test_rejects_host_without_dot(self):
        self.assertIsNone(validate_url("intranet")[0])

    def test_allows_localhost(self):
        self.assertEqual(validate_url("localhost:8080/app")[0], "localhost:8080/app")

    def test_allows_port(self):
        self.assertEqual(validate_url("report.contoso.com:8080/x")[0], "report.contoso.com:8080/x")


class ParseModeTests(unittest.TestCase):
    def test_alias(self):
        self.assertIs(parse_mode("IE11"), SiteMode.IE)
        self.assertIs(parse_mode("MSEdge"), SiteMode.EDGE)
        self.assertIs(parse_mode("None"), SiteMode.NEUTRAL)
        self.assertIs(parse_mode("IE模式"), SiteMode.IE)

    def test_unknown_falls_back(self):
        self.assertIs(parse_mode("???", SiteMode.EDGE), SiteMode.EDGE)


if __name__ == "__main__":
    unittest.main()
