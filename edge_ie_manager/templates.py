"""按月生成网址模板。

很多内部系统的地址形如 http://report.contoso.com/2026/10/index.html，
把其中的年月换成占位符存成模板，之后每月只要点一下就能生成当月网址。
"""

from __future__ import annotations

import calendar
import datetime as _dt
import re
from dataclasses import dataclass

PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z]+)\}")

PLACEHOLDER_HELP = [
    ("{yyyy}", "四位年份，例：2026"),
    ("{yy}", "两位年份，例：26"),
    ("{MM}", "两位月份，例：09"),
    ("{M}", "不补零月份，例：9"),
    ("{QQ}", "季度，例：Q3"),
    ("{Q}", "季度数字，例：3"),
    ("{dd}", "两位日期，例：06"),
]


def add_months(when: _dt.date, months: int) -> _dt.date:
    """按自然月偏移，日期取该月 1 号或原有日号（自动夹取到月末）。"""
    month_index = when.month - 1 + months
    year = when.year + month_index // 12
    month = month_index % 12 + 1
    day = min(when.day, calendar.monthrange(year, month)[1])
    return when.replace(year=year, month=month, day=day)


def render_template(template: str, when: _dt.date | None = None) -> str:
    """把模板里的时间占位符替换成 when（默认今天）对应的值。"""
    when = when or _dt.date.today()
    quarter = (when.month - 1) // 3 + 1

    replacements = {
        "yyyy": f"{when.year:04d}",
        "yy": f"{when.year % 100:02d}",
        "MM": f"{when.month:02d}",
        "M": str(when.month),
        "month": f"{when.month:02d}",
        "QQ": f"Q{quarter}",
        "Q": str(quarter),
        "q": str(quarter),
        "dd": f"{when.day:02d}",
        "d": str(when.day),
    }

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        return replacements.get(name, match.group(0))

    return PLACEHOLDER_RE.sub(_sub, template)


def unknown_placeholders(template: str) -> list[str]:
    known = {
        "yyyy",
        "yy",
        "MM",
        "M",
        "month",
        "QQ",
        "Q",
        "q",
        "dd",
        "d",
    }
    return sorted({m for m in PLACEHOLDER_RE.findall(template) if m not in known})


@dataclass
class UrlTemplate:
    """一条可复用的地址模板。"""

    name: str
    template: str
    mode: str = "ie"
    note: str = ""
    enabled: bool = True

    def render(self, when: _dt.date | None = None) -> str:
        return render_template(self.template, when)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "template": self.template,
            "mode": self.mode,
            "note": self.note,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UrlTemplate":
        return cls(
            name=str(data.get("name", "")).strip() or "未命名模板",
            template=str(data.get("template", "")).strip(),
            mode=str(data.get("mode", "ie")),
            note=str(data.get("note", "")),
            enabled=bool(data.get("enabled", True)),
        )


DEFAULT_TEMPLATES: list[UrlTemplate] = [
    UrlTemplate(
        name="示例：月度报表",
        template="report.example.com/{yyyy}{MM}",
        mode="ie",
        note="把域名和路径换成你实际的月度系统地址",
        enabled=False,
    ),
]
