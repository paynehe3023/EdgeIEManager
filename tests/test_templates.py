import datetime as dt
import unittest

from edge_ie_manager.templates import (
    UrlTemplate,
    add_months,
    render_template,
    unknown_placeholders,
)


class AddMonthsTests(unittest.TestCase):
    def test_rolls_over_year(self):
        self.assertEqual(add_months(dt.date(2026, 12, 1), 1), dt.date(2027, 1, 1))

    def test_clamps_day(self):
        self.assertEqual(add_months(dt.date(2026, 1, 31), 1), dt.date(2026, 2, 28))


class RenderTemplateTests(unittest.TestCase):
    def test_placeholders(self):
        when = dt.date(2026, 9, 6)
        self.assertEqual(render_template("a/{yyyy}/{MM}/{M}/{yy}", when), "a/2026/09/9/26")

    def test_quarter(self):
        self.assertEqual(render_template("{yyyy}{QQ}", dt.date(2026, 10, 1)), "2026Q4")

    def test_unknown_left_untouched(self):
        self.assertEqual(render_template("{unknown}/{MM}", dt.date(2026, 1, 1)), "{unknown}/01")
        self.assertEqual(unknown_placeholders("{unknown}/{MM}"), ["unknown"])

    def test_month_offset_pipeline(self):
        template = "report.contoso.com/{yyyy}{MM}"
        next_month = add_months(dt.date(2026, 12, 1), 1)
        self.assertEqual(render_template(template, next_month), "report.contoso.com/202701")


class UrlTemplateTests(unittest.TestCase):
    def test_roundtrip(self):
        item = UrlTemplate(name="月报", template="a.com/{yyyy}{MM}", mode="ie", note="n", enabled=True)
        restored = UrlTemplate.from_dict(item.to_dict())
        self.assertEqual(restored, item)

    def test_render(self):
        item = UrlTemplate(name="月报", template="a.com/{MM}")
        self.assertEqual(item.render(dt.date(2026, 3, 1)), "a.com/03")


if __name__ == "__main__":
    unittest.main()
