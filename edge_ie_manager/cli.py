"""命令行入口，主要供提权调用与脚本化使用。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import diagnostics, policy, sitelist
from .app import Manager
from .config import load_config
from .model import SiteMode, is_mode_alias, mode_label, parse_mode
from .version import APP_TITLE, __version__


def _emit(text: str = "") -> None:
    stream = sys.stdout
    if stream is None:
        # pythonw.exe 这类没有控制台的进程没有标准输出，直接跳过即可。
        return
    try:
        stream.write(text + "\n")
    except UnicodeEncodeError:  # 老式代码页控制台
        encoding = getattr(stream, "encoding", None) or "utf-8"
        stream.write(text.encode(encoding, "replace").decode(encoding, "replace") + "\n")


def _print_result(result) -> int:
    prefix = {True: "[OK]", False: "[!]"}.get(result.ok, "[i]")
    _emit(f"{prefix} {result.message}")
    for detail in result.details:
        _emit(f"    {detail}")
    return 0 if result.ok else 1


def _manager(args) -> Manager:
    config = load_config(Path(args.config) if getattr(args, "config", None) else None)
    if getattr(args, "site_list", None):
        config.site_list_path = str(Path(args.site_list))
    return Manager(config=config)


def cmd_list(args) -> int:
    manager = _manager(args)
    sl = manager.site_list
    _emit(f"站点列表：{sl.path}")
    _emit(f"修订号：{sl.version}    条目：{len(sl.sites)}")
    if not sl.sites:
        _emit("（空）")
    for site in sl.sites:
        note = f"    # {site.note}" if site.note else ""
        _emit(f"  {site.url:<48} {mode_label(site.mode)}{note}")
    return 0


def cmd_add(args) -> int:
    manager = _manager(args)
    if not is_mode_alias(args.mode):
        _emit(f"[!] 无法识别的打开方式：{args.mode}（可用：neutral / ie / edge）")
        return 2
    mode = parse_mode(args.mode, SiteMode.IE)
    result = manager.add_site(
        args.url,
        mode=mode,
        note=args.note or "",
        replace=args.replace,
    )
    return _print_result(result)


def cmd_remove(args) -> int:
    manager = _manager(args)
    return _print_result(manager.remove_site(args.url))


def cmd_add_month(args) -> int:
    manager = _manager(args)
    return _print_result(manager.add_from_templates(month_offset=args.month_offset))


def cmd_policy_install(args) -> int:
    manager = _manager(args)
    if args.scope:
        manager.config.scope = args.scope
    if getattr(args, "refresh", None) is not None:
        manager.config.refresh_interval = int(args.refresh)

    if getattr(args, "elevate", False) and not policy.is_admin():
        forwarded = _forward_global_args(args) + [
            "policy",
            "install",
            "--scope",
            manager.config.scope,
        ]
        if getattr(args, "refresh", None) is not None:
            forwarded += ["--refresh", str(args.refresh)]
        started, code = policy.run_elevated(forwarded)
        if not started:
            _emit("[!] 提权被取消或失败。")
            return 1
        return code

    result = manager.install_policy(scope=manager.config.scope)
    return _print_result(result)


def cmd_policy_uninstall(args) -> int:
    manager = _manager(args)
    if args.scope:
        manager.config.scope = args.scope

    if getattr(args, "elevate", False) and not policy.is_admin():
        forwarded = _forward_global_args(args) + [
            "policy",
            "uninstall",
            "--scope",
            manager.config.scope,
        ]
        started, code = policy.run_elevated(forwarded)
        if not started:
            _emit("[!] 提权被取消或失败。")
            return 1
        return code

    return _print_result(manager.uninstall_policy(scope=manager.config.scope))


def _forward_global_args(args) -> list[str]:
    """把全局选项复制成可放在子命令之前的形式，便于提权子进程使用。"""
    forwarded: list[str] = []
    if getattr(args, "config", None):
        forwarded += ["--config", str(args.config)]
    if getattr(args, "site_list", None):
        forwarded += ["--site-list", str(args.site_list)]
    return forwarded


def cmd_policy_status(args) -> int:
    manager = _manager(args)
    for state in policy.configured_scopes():
        _emit(f"{policy.describe_scope(state.scope)}：{state.summary()}")
    _emit("")
    _emit(f"工具期望的站点列表地址：{manager.site_list_url()}")
    return 0


def cmd_policy_export(args) -> int:
    manager = _manager(args)
    scope = args.scope or manager.config.scope
    target = Path(args.output) if args.output else manager.config.base_dir / "edge-ie-mode.reg"
    path = policy.export_reg_file(
        target,
        scope,
        manager.site_list_url(),
        refresh_interval=manager.config.refresh_interval or None,
        allow_reload_in_ie=manager.config.allow_reload_in_ie,
    )
    _emit(f"[OK] 已导出注册表文件：{path}")
    _emit("     双击导入即可（整机策略请右键“以管理员身份运行”导入）。")
    return 0


def cmd_check(args) -> int:
    manager = _manager(args)
    sl = manager.site_list
    problems = sitelist.check_urls(sl.sites)
    if not problems:
        _emit(f"[OK] {len(sl.sites)} 条记录都符合站点列表规范。")
        return 0
    _emit(f"[!] {len(problems)} 条记录需要留意：")
    for site, message in problems:
        _emit(f"    {site.url}: {message}")
    return 1


def cmd_diagnose(args) -> int:
    manager = _manager(args)
    info = manager.report()
    _emit(diagnostics.render_text(info))
    return 0


def cmd_restart(args) -> int:
    manager = _manager(args)
    return _print_result(manager.restart_edge())


def cmd_gui(args) -> int:
    from .gui import run

    return run(args.config)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edge-ie",
        description=f"{APP_TITLE} (v{__version__})",
    )
    parser.add_argument(
        "--config",
        help="配置文件路径（默认 %%LOCALAPPDATA%%\\EdgeIEManager\\config.json）",
    )
    parser.add_argument("--site-list", help="站点列表 XML 路径")
    parser.add_argument(
        "--report-file",
        help="把本次运行的输出写入指定文件（提权子进程用它回传日志）",
    )
    sub = parser.add_subparsers(dest="command")

    p_gui = sub.add_parser("gui", help="打开图形界面")
    p_gui.set_defaults(func=cmd_gui)

    p_list = sub.add_parser("list", help="列出站点列表内容")
    p_list.set_defaults(func=cmd_list)

    p_add = sub.add_parser("add", help="添加一条网址")
    p_add.add_argument("url")
    p_add.add_argument(
        "--mode",
        default="ie",
        help="打开方式：ie(默认) / neutral / edge，大小写不敏感",
    )
    p_add.add_argument("--note", default="")
    p_add.add_argument("--replace", action="store_true", help="已存在时覆盖")
    p_add.set_defaults(func=cmd_add)

    p_remove = sub.add_parser("remove", help="删除一条网址")
    p_remove.add_argument("url")
    p_remove.set_defaults(func=cmd_remove)

    p_month = sub.add_parser("add-month", help="按模板添加本月/下月网址")
    p_month.add_argument("--month-offset", type=int, default=0, help="0=本月, 1=下月")
    p_month.set_defaults(func=cmd_add_month)

    p_check = sub.add_parser("check", help="检查网址是否符合站点列表规范")
    p_check.set_defaults(func=cmd_check)

    p_diag = sub.add_parser("diagnose", help="输出环境诊断")
    p_diag.set_defaults(func=cmd_diagnose)

    p_restart = sub.add_parser("restart-edge", help="重启 Microsoft Edge")
    p_restart.set_defaults(func=cmd_restart)

    p_policy = sub.add_parser("policy", help="写入/清理 IE 模式策略")
    policy_sub = p_policy.add_subparsers(dest="policy_command")

    for name, func, help_text in (
        ("install", cmd_policy_install, "写入策略"),
        ("uninstall", cmd_policy_uninstall, "删除策略"),
        ("status", cmd_policy_status, "查看策略状态"),
    ):
        sp = policy_sub.add_parser(name, help=help_text)
        sp.add_argument("--scope", choices=["user", "machine"], default=None)
        if name in ("install", "uninstall"):
            sp.add_argument(
                "--elevate",
                action="store_true",
                help="需要管理员时直接弹出 UAC 提权重试",
            )
        if name == "install":
            sp.add_argument(
                "--refresh",
                type=int,
                default=None,
                help="站点列表自动刷新间隔（分钟），省略表示不设置",
            )
        sp.set_defaults(func=func)

    p_export = policy_sub.add_parser("export-reg", help="导出 .reg 文件")
    p_export.add_argument("--scope", choices=["user", "machine"], default=None)
    p_export.add_argument("-o", "--output", default=None)
    p_export.set_defaults(func=cmd_policy_export)

    return parser


def main(argv: list[str] | None = None) -> int:
    # 图形版 exe 带的命令行模式没有控制台，sys.stdout/stderr 会是 None。
    # 先补上空设备，argparse 报错时才不会因为写 None 而崩掉。
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = sys.stdout

    parser = build_parser()
    args = parser.parse_args(argv)

    report_handle = None
    if getattr(args, "report_file", None):
        try:
            report_handle = open(args.report_file, "w", encoding="utf-8", errors="replace")
            sys.stdout = report_handle
            sys.stderr = report_handle
        except OSError:
            report_handle = None

    try:
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(errors="replace")  # type: ignore[union-attr]
            except (AttributeError, ValueError):
                pass

        if report_handle is not None:
            user = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}"
            _emit(f"[i] 有效账户：{user}")
            _emit(f"[i] 管理员权限：{'是' if policy.is_admin() else '否'}")

        func = getattr(args, "func", None)
        if func is None:
            from .gui import run

            return run(args.config)
        return int(func(args) or 0)
    finally:
        if report_handle is not None:
            try:
                report_handle.flush()
                report_handle.close()
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
