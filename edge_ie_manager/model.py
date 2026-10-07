"""站点数据模型与网址规范化。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlsplit


class SiteMode(str, Enum):
    """站点在 Edge 中的打开方式，对应站点列表里的 <open-in> 取值。"""

    NEUTRAL = "neutral"
    IE = "ie"
    EDGE = "edge"


# <open-in> 的合法取值由微软 schema v.2 规定。
MODE_TO_OPEN_IN: dict[SiteMode, str] = {
    SiteMode.NEUTRAL: "None",
    SiteMode.IE: "IE11",
    SiteMode.EDGE: "MSEdge",
}

OPEN_IN_TO_MODE: dict[str, SiteMode] = {
    "": SiteMode.NEUTRAL,
    "none": SiteMode.NEUTRAL,
    "default": SiteMode.NEUTRAL,
    "ie11": SiteMode.IE,
    "ie": SiteMode.IE,
    "msedge": SiteMode.EDGE,
    "edge": SiteMode.EDGE,
}

MODE_LABELS: dict[str, str] = {
    SiteMode.NEUTRAL.value: "中性(跟随来源)",
    SiteMode.IE.value: "强制 IE 模式",
    SiteMode.EDGE.value: "强制 Edge",
}

MODE_DESCRIPTIONS: dict[str, str] = {
    SiteMode.NEUTRAL.value: "导航从哪个浏览器开始就用哪个，最安全，适合 SSO/单点登录域名。",
    SiteMode.IE.value: "在 Edge 里点开就自动切换到 IE 模式，适合必须用 IE 内核的老系统。",
    SiteMode.EDGE.value: "强制用 Edge 内核打开，适合需要把登录域名排除在 IE 之外的场景。",
}

_MODE_ALIASES: dict[str, SiteMode] = {
    "neutral": SiteMode.NEUTRAL,
    "none": SiteMode.NEUTRAL,
    "中间": SiteMode.NEUTRAL,
    "中性": SiteMode.NEUTRAL,
    "ie": SiteMode.IE,
    "ie11": SiteMode.IE,
    "ie模式": SiteMode.IE,
    "edge": SiteMode.EDGE,
    "msedge": SiteMode.EDGE,
    "chromium": SiteMode.EDGE,
    "现代": SiteMode.EDGE,
}

_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")


def mode_label(mode: SiteMode | str) -> str:
    value = mode.value if isinstance(mode, SiteMode) else str(mode)
    return MODE_LABELS.get(value, value)


def parse_mode(text: str | None, default: SiteMode = SiteMode.NEUTRAL) -> SiteMode:
    """把用户输入或配置文件里的值解析成 SiteMode。"""
    if text is None:
        return default
    if isinstance(text, SiteMode):
        return text
    key = str(text).strip().lower().replace(" ", "").replace("-", "")
    return _MODE_ALIASES.get(key, default)


def is_mode_alias(text: str | None) -> bool:
    if text is None:
        return False
    if isinstance(text, SiteMode):
        return True
    key = str(text).strip().lower().replace(" ", "").replace("-", "")
    return key in _MODE_ALIASES


def strip_scheme(url: str) -> str:
    """去掉 http(s):// 前缀。

    微软文档明确要求站点列表里的 url 不要带协议：写成 contoso.com 会同时
    匹配 http 与 https，带了协议反而只匹配其中一种。
    """
    return _SCHEME_RE.sub("", url.strip())


def normalize_url(url: str) -> str:
    """用于查重与比对的规范化形式（保留原始写法另存）。"""
    value = strip_scheme(url).strip()
    value = value.rstrip("/")
    return value.casefold()


def validate_url(url: str) -> tuple[str | None, str | None]:
    """校验站点列表里的网址。

    返回 (规范化后的值, 警告文本)。规范化后的值为 None 表示该输入不可用。
    """
    raw = url.strip()
    if not raw:
        return None, "网址不能为空。"

    if any(ch.isspace() for ch in raw):
        return None, "网址中不能包含空格或换行。"

    scheme = ""
    match = re.match(r"^([a-zA-Z][a-zA-Z0-9+.\-]*)://", raw)
    if match:
        scheme = match.group(1).lower()
        if scheme not in ("http", "https"):
            return None, f"不支持 {scheme}:// 这类协议，站点列表只接受 http/https 网页。"

    value = strip_scheme(raw)
    if value.startswith("/"):
        return None, "缺少域名，需要写成 域名/路径 的形式，例如 report.contoso.com/2026/10。"

    host_part = value.split("/", 1)[0]
    host_only = host_part.split(":", 1)[0]
    if not host_only or host_only.startswith(".") or "." not in host_only:
        if host_only not in ("localhost",):
            return None, f"“{value}”看起来不像有效域名，请检查是否漏了域名后缀。"

    warning = None
    if scheme:
        warning = (
            f"已自动去掉 {scheme}:// 前缀。站点列表不带协议时会同时匹配 http 与 https，"
            "带上协议反而缩小匹配范围。"
        )
    return value, warning


@dataclass
class Site:
    """站点列表中的一条记录。"""

    url: str
    mode: SiteMode = SiteMode.NEUTRAL
    compat_mode: str | None = None
    extra_xml: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def key(self) -> str:
        return normalize_url(self.url)

    def clone(self) -> "Site":
        return Site(
            url=self.url,
            mode=self.mode,
            compat_mode=self.compat_mode,
            extra_xml=list(self.extra_xml),
            note=self.note,
        )
