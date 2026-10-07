"""配置与本地文件位置。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .templates import DEFAULT_TEMPLATES, UrlTemplate
from .version import APP_NAME

CONFIG_VERSION = 1


def default_base_dir() -> Path:
    """默认工作目录：%LOCALAPPDATA%\\EdgeIEManager。

    放在用户目录下，这样每月修改站点列表不需要管理员权限。
    """
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def default_site_list_path(base_dir: Path | None = None) -> Path:
    base = base_dir or default_base_dir()
    return base / "sitelist.xml"


@dataclass
class Config:
    scope: str = "user"
    site_list_path: str = ""
    refresh_interval: int = 0
    allow_reload_in_ie: bool = True
    templates: list[UrlTemplate] = field(default_factory=list)
    last_month_offset: int = 0
    # 界面主题："light" 或 "dark"
    theme: str = "light"
    # 更新源：GitHub 仓库 owner/repo，留空表示未配置
    update_repo: str = ""
    # 启动后是否自动静默检查更新
    update_auto_check: bool = True
    config_path: str = ""

    @property
    def site_list_file(self) -> Path:
        return Path(self.site_list_path)

    @property
    def base_dir(self) -> Path:
        if self.config_path:
            return Path(self.config_path).parent
        return default_base_dir()

    def to_dict(self) -> dict:
        return {
            "config_version": CONFIG_VERSION,
            "scope": self.scope,
            "site_list_path": self.site_list_path,
            "refresh_interval": self.refresh_interval,
            "allow_reload_in_ie": self.allow_reload_in_ie,
            "last_month_offset": self.last_month_offset,
            "theme": self.theme,
            "update_repo": self.update_repo,
            "update_auto_check": self.update_auto_check,
            "templates": [t.to_dict() for t in self.templates],
        }


def load_config(path: Path | None = None, base_dir: Path | None = None) -> Config:
    base = base_dir or default_base_dir()
    config_path = path or (base / "config.json")
    cfg = Config(config_path=str(config_path))

    data: dict = {}
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}

    cfg.scope = str(data.get("scope", "user"))
    cfg.site_list_path = str(
        data.get("site_list_path") or (config_path.parent / "sitelist.xml")
    )
    cfg.refresh_interval = int(data.get("refresh_interval", 0) or 0)
    cfg.allow_reload_in_ie = bool(data.get("allow_reload_in_ie", True))
    cfg.last_month_offset = int(data.get("last_month_offset", 0) or 0)
    cfg.theme = "dark" if str(data.get("theme", "light")).lower() == "dark" else "light"
    cfg.update_repo = str(data.get("update_repo", "") or "").strip()
    cfg.update_auto_check = bool(data.get("update_auto_check", True))

    templates = [UrlTemplate.from_dict(d) for d in data.get("templates", [])]
    cfg.templates = templates or list(DEFAULT_TEMPLATES)
    return cfg


def save_config(cfg: Config, path: Path | None = None) -> Path:
    config_path = Path(path or cfg.config_path or (default_base_dir() / "config.json"))
    config_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(cfg.to_dict(), ensure_ascii=False, indent=2)
    config_path.write_text(text + "\n", encoding="utf-8")
    cfg.config_path = str(config_path)
    return config_path
