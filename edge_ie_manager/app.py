"""不依赖界面的高层操作，CLI 与 GUI 共用。"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path

from . import diagnostics, policy, sitelist
from .config import Config, load_config, save_config
from .model import Site, SiteMode, mode_label, validate_url
from .sitelist import SiteList, SiteListError
from .templates import UrlTemplate, add_months, render_template


@dataclass
class OperationResult:
    ok: bool
    message: str
    level: str = "info"
    details: list[str] = field(default_factory=list)
    # 为 True 表示这次操作因为权限不足失败，调用方可以用管理员权限重试。
    needs_admin: bool = False


class Manager:
    """把配置、站点列表与策略串起来的门面。"""

    def __init__(self, config: Config | None = None, config_path: Path | None = None):
        self.config = config or load_config(config_path)
        self._site_list: SiteList | None = None

    # ------------------------------------------------------------------ 配置
    def save_config(self) -> None:
        save_config(self.config)

    # -------------------------------------------------------------- 站点列表
    @property
    def site_list(self) -> SiteList:
        if self._site_list is None:
            self._site_list = sitelist.load_site_list(self.config.site_list_file)
        return self._site_list

    def reload(self) -> None:
        self._site_list = None

    def save(self, bump_version: bool = True) -> OperationResult:
        try:
            path = sitelist.save_site_list(self.site_list, bump_version=bump_version)
        except (SiteListError, OSError) as exc:
            return OperationResult(False, f"保存失败：{exc}", "error")
        return OperationResult(
            True,
            f"已保存 {len(self.site_list.sites)} 条记录到 {path}（修订号 {self.site_list.version}）。",
        )

    def add_site(
        self,
        url: str,
        mode: SiteMode | str = SiteMode.IE,
        note: str = "",
        replace: bool = False,
        save: bool = True,
    ) -> OperationResult:
        value, warning = validate_url(url)
        if not value:
            return OperationResult(False, warning or "网址无效。", "error")

        site = Site(url=value, mode=SiteMode(mode) if not isinstance(mode, SiteMode) else mode, note=note)
        status = self.site_list.add(site, replace=replace)
        if status == "duplicate":
            return OperationResult(
                False,
                f"站点列表里已经有 {value}，如需修改请先选中它再点“更新”。",
                "warning",
            )

        details = []
        if warning:
            details.append(warning)
        if save:
            result = self.save()
            if not result.ok:
                return result
            details.append(result.message)

        action = "已更新" if status == "updated" else "已添加"
        message = f"{action}：{value}（{mode_label(site.mode)}）"
        return OperationResult(True, message, "info", details)

    def remove_site(self, url: str, save: bool = True) -> OperationResult:
        if not self.site_list.remove(url):
            return OperationResult(False, f"站点列表里没有 {url}。", "warning")
        details = []
        if save:
            result = self.save()
            if not result.ok:
                return result
            details.append(result.message)
        return OperationResult(True, f"已删除：{url}", "info", details)

    def remove_sites(self, urls: list[str], save: bool = True) -> OperationResult:
        """一次删除多条记录，只保存一次（列表里不存在的条目跳过并说明）。"""
        removed: list[str] = []
        missing: list[str] = []
        for url in urls:
            if self.site_list.remove(url):
                removed.append(url)
            else:
                missing.append(url)
        if not removed:
            return OperationResult(False, "选中的记录都已经不在列表里了。", "warning")
        details = []
        if missing:
            preview = "；".join(missing[:5])
            suffix = " 等" if len(missing) > 5 else ""
            details.append(f"{len(missing)} 条没有找到，已跳过：{preview}{suffix}")
        if save:
            result = self.save()
            if not result.ok:
                return result
            details.append(result.message)
        message = f"已删除 {len(removed)} 条记录。"
        return OperationResult(True, message, "info", details)

    def update_site(
        self,
        old_url: str,
        new_url: str,
        mode: SiteMode | str,
        note: str = "",
        save: bool = True,
    ) -> OperationResult:
        value, warning = validate_url(new_url)
        if not value:
            return OperationResult(False, warning or "网址无效。", "error")

        index = self.site_list.index_of(old_url)
        if index < 0:
            return OperationResult(False, f"站点列表里没有 {old_url}。", "warning")

        existing = self.site_list.sites[index]
        conflict = self.site_list.index_of(value)
        if conflict >= 0 and conflict != index:
            return OperationResult(False, f"{value} 已存在，不能改成重复项。", "warning")

        existing.url = value
        existing.mode = SiteMode(mode) if not isinstance(mode, SiteMode) else mode
        existing.note = note

        details = [warning] if warning else []
        if save:
            result = self.save()
            if not result.ok:
                return result
            details.append(result.message)
        return OperationResult(True, f"已保存：{value}", "info", details)

    @staticmethod
    def bulk_parse(text: str) -> tuple[list[str], list[str]]:
        """把多行文本拆成网址，返回 (有效项, 无效项)。"""
        good: list[str] = []
        bad: list[str] = []
        for raw in text.splitlines():
            line = raw.strip().strip(",").strip()
            if not line or line.startswith("#"):
                continue
            value, _ = validate_url(line)
            if value:
                good.append(value)
            else:
                bad.append(raw.strip())
        return good, bad

    def add_many(
        self,
        urls: list[str],
        mode: SiteMode | str = SiteMode.IE,
        note: str = "",
        save: bool = True,
    ) -> OperationResult:
        added = 0
        updated = 0
        skipped: list[str] = []
        mode_value = SiteMode(mode) if not isinstance(mode, SiteMode) else mode

        for url in urls:
            value, _ = validate_url(url)
            if not value:
                skipped.append(url)
                continue
            status = self.site_list.add(Site(url=value, mode=mode_value, note=note))
            if status == "duplicate":
                skipped.append(value)
            elif status == "updated":
                updated += 1
            else:
                added += 1

        details: list[str] = []
        if save and (added or updated):
            result = self.save()
            if not result.ok:
                return result
            details.append(result.message)

        message = f"新增 {added} 条，更新 {updated} 条"
        if skipped:
            message += f"，跳过 {len(skipped)} 条（已存在或无效）"
        return OperationResult(True, message, "info", details + skipped[:10])

    # ---------------------------------------------------------------- 模板
    def render_templates(self, month_offset: int = 0, only_enabled: bool = False) -> list[tuple[UrlTemplate, str]]:
        today = _dt.date.today()
        target = add_months(today.replace(day=1), month_offset)
        result: list[tuple[UrlTemplate, str]] = []
        for tpl in self.config.templates:
            if only_enabled and not tpl.enabled:
                continue
            result.append((tpl, render_template(tpl.template, target)))
        return result

    def add_from_templates(self, month_offset: int = 0, save: bool = True) -> OperationResult:
        rendered = self.render_templates(month_offset=month_offset, only_enabled=True)
        if not rendered:
            return OperationResult(False, "没有启用中的模板。", "warning")

        added = 0
        skipped: list[str] = []
        for tpl, url in rendered:
            value, _ = validate_url(url)
            if not value:
                skipped.append(f"{tpl.name}: {url}")
                continue
            from .model import parse_mode

            status = self.site_list.add(
                Site(url=value, mode=parse_mode(tpl.mode, SiteMode.IE), note=tpl.note)
            )
            if status == "duplicate":
                skipped.append(f"{tpl.name}: 已存在")
            else:
                added += 1

        details: list[str] = []
        if save and added:
            result = self.save()
            if not result.ok:
                return result
            details.append(result.message)

        target = add_months(_dt.date.today().replace(day=1), month_offset)
        label = f"{target.year} 年 {target.month} 月"
        message = f"{label}：新增 {added} 条"
        if skipped:
            message += f"，跳过 {len(skipped)} 条"
        return OperationResult(True, message, "info", details + skipped)

    # ---------------------------------------------------------------- 策略
    def site_list_url(self) -> str:
        path = self.config.site_list_file
        try:
            return path.resolve().as_uri()
        except ValueError:
            return str(path)

    def install_policy(self, scope: str | None = None, elevate: bool = False) -> OperationResult:
        scope = scope or self.config.scope
        url = self.site_list_url()
        if not self.config.site_list_file.exists():
            result = self.save(bump_version=False)
            if not result.ok:
                return result

        if elevate:
            report = self._elevate_report_path()
            args = self._elevate_args_prefix()
            args += [
                "--site-list",
                str(self.config.site_list_file),
                "policy",
                "install",
                "--scope",
                scope,
                "--refresh",
                str(self.config.refresh_interval),
            ]
            started, code = policy.run_elevated(args, report_file=report)
            if not started:
                return OperationResult(False, "提权被取消或失败。", "error")
            if code != 0:
                return OperationResult(
                    False,
                    f"提权进程返回错误码 {code}。",
                    "error",
                    details=self._elevate_log_details(report),
                )
            return OperationResult(
                True,
                f"已通过管理员权限写入 {policy.describe_scope(scope)} 策略，重启 Edge 后生效。",
            )

        if scope == policy.SCOPE_MACHINE and not policy.is_admin():
            return OperationResult(
                False,
                "写入整机策略需要管理员权限。",
                "error",
                needs_admin=True,
            )

        try:
            policy.install_policy(
                scope,
                url,
                refresh_interval=self.config.refresh_interval or None,
                allow_reload_in_ie=self.config.allow_reload_in_ie,
            )
        except PermissionError as exc:
            root = policy.SCOPE_ROOT_NAMES.get(scope, "")
            return OperationResult(
                False,
                f"写入策略失败：{exc}",
                "error",
                details=[
                    f"当前账户对 {root}\\{policy.POLICY_SUBKEY} 没有写入权限，"
                    "通常是被单位的安全策略锁定了。可用管理员权限重试。"
                ],
                needs_admin=True,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            return OperationResult(False, f"写入策略失败：{exc}", "error")

        return OperationResult(
            True,
            f"已写入 {policy.describe_scope(scope)} 的 IE 模式策略，重启 Edge 后生效。",
        )

    def uninstall_policy(self, scope: str | None = None, elevate: bool = False) -> OperationResult:
        scope = scope or self.config.scope

        if elevate:
            report = self._elevate_report_path()
            started, code = policy.run_elevated(
                [*self._elevate_args_prefix(), "policy", "uninstall", "--scope", scope],
                report_file=report,
            )
            if not started:
                return OperationResult(False, "提权被取消或失败。", "error")
            if code != 0:
                return OperationResult(
                    False,
                    f"提权进程返回错误码 {code}。",
                    "error",
                    details=self._elevate_log_details(report),
                )
            return OperationResult(True, "已通过管理员权限删除策略。")

        if scope == policy.SCOPE_MACHINE and not policy.is_admin():
            return OperationResult(
                False, "删除整机策略需要管理员权限。", "error", needs_admin=True
            )

        try:
            removed = policy.uninstall_policy(scope)
        except PermissionError as exc:
            return OperationResult(
                False,
                f"删除策略失败：{exc}",
                "error",
                needs_admin=True,
            )
        except OSError as exc:
            return OperationResult(False, f"删除策略失败：{exc}", "error")
        if not removed:
            return OperationResult(False, "没有找到本工具写入的策略值。", "warning")
        return OperationResult(True, "已删除：" + "、".join(removed))

    # ---------------------------------------------------------------- 诊断
    def _elevate_args_prefix(self) -> list[str]:
        """提权子进程要用的全局参数：让它读写同一份配置与数据目录。"""
        if self.config.config_path:
            return ["--config", str(self.config.config_path)]
        return []

    def _elevate_report_path(self) -> Path:
        """提权子进程的输出文件，用于失败时把真实原因带回界面。"""
        return self.config.base_dir / "elevate-last.log"

    @staticmethod
    def _elevate_log_details(report: Path, limit: int = 12) -> list[str]:
        try:
            text = report.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return []
        if not text:
            return []
        lines = [line for line in text.splitlines() if line.strip()]
        return ["提权进程输出（" + str(report) + "）："] + lines[-limit:]

    def report(self) -> dict:
        return diagnostics.collect(self.config)

    def restart_edge(self) -> OperationResult:
        ok, message = diagnostics.restart_edge()
        return OperationResult(ok, message, "info" if ok else "error")
