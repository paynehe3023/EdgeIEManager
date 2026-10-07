"""企业模式站点列表(Enterprise Mode Site List, schema v.2)的读写。

格式依据：https://learn.microsoft.com/internet-explorer/ie11-deploy-guide/enterprise-mode-schema-version-2-guidance

要点：
* 根节点 <site-list version="N"> 里的 version 是站点列表的修订号，Edge 靠它判断
  文件是否更新过，所以每次保存都要递增。
* 每条记录的 <open-in> 只能是 None / IE11 / MSEdge。
* url 属性不要写协议（http://），否则只会匹配该协议，且不符合官方建议。
* 本工具只写 schema v.2；v.2 才支持 IE 模式集成，v.1 只适用于 IE11 本体。
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from .model import (
    MODE_TO_OPEN_IN,
    OPEN_IN_TO_MODE,
    Site,
    normalize_url,
    validate_url,
)
from .version import __version__

MAX_BACKUPS = 20
CREATED_BY_TOOL = "EdgeIEManager"


class SiteListError(Exception):
    """站点列表文件无法解析或写入。"""


def meta_path_for(site_list_path: str | Path) -> Path:
    """备注等本地信息存在同目录的 *.meta.json，避免往 XML 里塞非标准元素。"""
    path = Path(site_list_path)
    return path.with_suffix(path.suffix + ".meta.json")


@dataclass
class SiteList:
    path: Path
    version: int = 1
    sites: list[Site] = field(default_factory=list)
    created_by_tool: str = CREATED_BY_TOOL
    created_by_version: str = __version__
    date_created: str = ""
    loaded: bool = False

    def index_of(self, url: str) -> int:
        key = normalize_url(url)
        for i, site in enumerate(self.sites):
            if site.key == key:
                return i
        return -1

    def find(self, url: str) -> Site | None:
        index = self.index_of(url)
        return self.sites[index] if index >= 0 else None

    def add(self, site: Site, replace: bool = False) -> str:
        """加入一条记录，返回 'added' / 'updated' / 'duplicate'。"""
        index = self.index_of(site.url)
        if index >= 0:
            if not replace:
                return "duplicate"
            existing_note = self.sites[index].note
            self.sites[index] = site
            if not site.note:
                self.sites[index].note = existing_note
            return "updated"
        self.sites.append(site)
        return "added"

    def remove(self, url: str) -> bool:
        index = self.index_of(url)
        if index < 0:
            return False
        del self.sites[index]
        return True


def timestamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d.%H%M%S")


def _now_iso() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_xml(text: str, path: str | Path = "") -> SiteList:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise SiteListError(f"XML 解析失败：{exc}") from exc

    if root.tag != "site-list":
        raise SiteListError(f"根节点应为 <site-list>，实际是 <{root.tag}>。")

    try:
        version = int((root.get("version") or "1").strip())
    except ValueError:
        version = 1

    sl = SiteList(path=Path(path) if path else Path("sitelist.xml"), version=version)

    created = root.find("created-by")
    if created is not None:
        tool = created.findtext("tool")
        if tool:
            sl.created_by_tool = tool.strip()
        ver = created.findtext("version")
        if ver:
            sl.created_by_version = ver.strip()
        date_created = created.findtext("date-created")
        if date_created:
            sl.date_created = date_created.strip()

    for element in root.findall("site"):
        url = (element.get("url") or "").strip()
        if not url:
            continue
        open_in = element.findtext("open-in") or ""
        compat = element.findtext("compat-mode")
        extra: list[str] = []
        for child in element:
            if child.tag in ("open-in", "compat-mode"):
                continue
            extra.append(ET.tostring(child, encoding="unicode").strip())
        sl.sites.append(
            Site(
                url=url,
                mode=OPEN_IN_TO_MODE.get(open_in.strip().lower(), None)
                or OPEN_IN_TO_MODE["none"],
                compat_mode=compat.strip() if compat else None,
                extra_xml=extra,
            )
        )

    sl.loaded = True
    return sl


def to_xml(sl: SiteList) -> str:
    date_created = sl.date_created or timestamp()
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<site-list version="{sl.version}">',
        "  <created-by>",
        f"    <tool>{escape(sl.created_by_tool)}</tool>",
        f"    <version>{escape(sl.created_by_version)}</version>",
        f"    <date-created>{escape(date_created)}</date-created>",
        "  </created-by>",
    ]
    for site in sl.sites:
        lines.append(f"  <site url={quoteattr(site.url)}>")
        if site.compat_mode:
            lines.append(f"    <compat-mode>{escape(site.compat_mode)}</compat-mode>")
        lines.append(f"    <open-in>{MODE_TO_OPEN_IN[site.mode]}</open-in>")
        for extra in site.extra_xml:
            lines.append(f"    {extra}")
        lines.append("  </site>")
    lines.append("</site-list>")
    return "\n".join(lines) + "\n"


def new_site_list(path: str | Path) -> SiteList:
    sl = SiteList(path=Path(path), version=0, date_created=timestamp())
    sl.loaded = True
    return sl


def load_site_list(path: str | Path, create: bool = True) -> SiteList:
    path = Path(path)
    if not path.exists():
        if not create:
            raise SiteListError(f"站点列表文件不存在：{path}")
        return new_site_list(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise SiteListError(f"无法读取站点列表：{exc}") from exc
    sl = parse_xml(text, path)
    sl.path = path
    _apply_meta(sl)
    return sl


def backup_site_list(path: str | Path, backups_dir: str | Path | None = None) -> Path | None:
    path = Path(path)
    if not path.exists():
        return None
    target_dir = Path(backups_dir) if backups_dir else path.parent / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = target_dir / f"{path.stem}.{stamp}{path.suffix or '.xml'}"
    shutil.copy2(path, target)
    _prune_backups(target_dir, path)
    return target


def _prune_backups(target_dir: Path, original: Path) -> None:
    pattern = f"{original.stem}.*{original.suffix or '.xml'}"
    files = sorted(target_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in files[MAX_BACKUPS:]:
        try:
            stale.unlink()
        except OSError:
            pass


def save_site_list(
    sl: SiteList,
    path: str | Path | None = None,
    bump_version: bool = True,
    make_backup: bool = True,
    backups_dir: str | Path | None = None,
) -> Path:
    """写回 XML。默认递增修订号并保留一份备份。"""
    target = Path(path or sl.path)
    target.parent.mkdir(parents=True, exist_ok=True)

    if bump_version:
        sl.version = max(int(sl.version or 0), 0) + 1
    if not sl.date_created:
        sl.date_created = timestamp()

    text = to_xml(sl)
    try:
        ET.fromstring(text)
    except ET.ParseError as exc:  # 理论上不会发生，作为最后一道保险
        raise SiteListError(f"生成的 XML 无效：{exc}") from exc

    if make_backup:
        backup_site_list(target, backups_dir)

    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temp, target)
    sl.path = target
    _write_meta(sl)
    return target


def check_urls(sites: list[Site]) -> list[tuple[Site, str]]:
    """返回不符合站点列表规范的记录列表。"""
    problems: list[tuple[Site, str]] = []
    for site in sites:
        _, warning = validate_url(site.url)
        if warning:
            problems.append((site, warning))
    return problems


def _apply_meta(sl: SiteList) -> None:
    meta_file = meta_path_for(sl.path)
    if not meta_file.exists():
        return
    try:
        data = json.loads(meta_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    notes = data.get("notes") or {}
    for site in sl.sites:
        note = notes.get(site.key)
        if note:
            site.note = str(note)


def _write_meta(sl: SiteList) -> None:
    notes = {site.key: site.note for site in sl.sites if site.note}
    meta_file = meta_path_for(sl.path)
    if not notes:
        if meta_file.exists():
            try:
                meta_file.unlink()
            except OSError:
                pass
        return
    payload = {
        "updated_at": _now_iso(),
        "notes": notes,
    }
    meta_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
