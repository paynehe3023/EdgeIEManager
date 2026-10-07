"""环境诊断：Edge 安装情况、进程状态、策略与站点列表是否就绪。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from . import policy, sitelist
from .config import Config
from .version import APP_NAME, __version__

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

DEFAULT_EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def _run(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="mbcs" if os.name == "nt" else "utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def edge_executables() -> list[Path]:
    found: list[Path] = []
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "")
                if value:
                    found.append(Path(value))
        except (OSError, ImportError):
            pass

    for candidate in DEFAULT_EDGE_PATHS:
        path = Path(candidate)
        if path.exists() and path not in found:
            found.append(path)

    local = os.environ.get("LOCALAPPDATA")
    if local:
        path = Path(local) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        if path.exists() and path not in found:
            found.append(path)
    return found


def edge_primary_path() -> Path | None:
    found = edge_executables()
    return found[0] if found else None


def edge_version() -> str:
    path = edge_primary_path()
    if not path:
        return "未找到 Microsoft Edge"
    try:
        info = subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"(Get-Item '{path}').VersionInfo.ProductVersion"],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=CREATE_NO_WINDOW,
        )
        version = (info.stdout or "").strip()
        if version:
            return version
    except (OSError, subprocess.SubprocessError):
        pass
    return "未知"


def edge_running() -> bool:
    # 状态条每次刷新都会问一次，给个更短的超时，卡住的 tasklist 不会拖很久。
    result = _run(["tasklist", "/FI", "IMAGENAME eq msedge.exe", "/NH"], timeout=5)
    if result is None:
        return False
    return "msedge.exe" in (result.stdout or "")


def close_edge() -> tuple[bool, str]:
    """结束所有 Edge 进程，让新策略在下次启动时生效。"""
    result = _run(["taskkill", "/IM", "msedge.exe", "/F"])
    if result is None:
        return False, "无法调用 taskkill。"
    if result.returncode == 0:
        return True, "已关闭 Microsoft Edge。"
    output = (result.stdout or "") + (result.stderr or "")
    if "not found" in output.lower() or "没有运行" in output or "128" in output:
        return True, "Edge 当前没有运行。"
    return False, output.strip() or "关闭 Edge 失败。"


def launch_edge(urls: str | list[str] | None = None) -> tuple[bool, str]:
    """启动 Edge。传入网址时在新标签页打开，可一次传多个。"""
    path = edge_primary_path()
    if not path:
        return False, "未找到 Microsoft Edge。"
    args = [str(path)]
    if urls:
        if isinstance(urls, str):
            args.append(urls)
        else:
            args.extend(urls)
    try:
        subprocess.Popen(args, creationflags=CREATE_NO_WINDOW)
    except OSError as exc:
        return False, f"启动 Edge 失败：{exc}"
    return True, "已启动 Microsoft Edge。"


def restart_edge() -> tuple[bool, str]:
    ok, message = close_edge()
    if not ok:
        return False, message
    started, start_msg = launch_edge()
    if not started:
        return False, f"{message} {start_msg}"
    return True, "Edge 已重启，请重新打开需要 IE 模式的页面。"


def edge_user_data_dir() -> Path | None:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    path = Path(local) / "Microsoft" / "Edge" / "User Data"
    return path if path.exists() else None


def site_list_report(path: str | Path) -> dict:
    path = Path(path)
    report: dict = {
        "path": str(path),
        "exists": path.exists(),
        "entries": 0,
        "version": None,
        "ie_count": 0,
        "neutral_count": 0,
        "edge_count": 0,
        "error": "",
    }
    if not path.exists():
        return report
    try:
        sl = sitelist.load_site_list(path, create=False)
    except sitelist.SiteListError as exc:
        report["error"] = str(exc)
        return report

    report["entries"] = len(sl.sites)
    report["version"] = sl.version
    for site in sl.sites:
        if site.mode.value == "ie":
            report["ie_count"] += 1
        elif site.mode.value == "edge":
            report["edge_count"] += 1
        else:
            report["neutral_count"] += 1
    return report


def collect(cfg: Config) -> dict:
    site_list = site_list_report(cfg.site_list_file)
    user_state = policy.read_policy(policy.SCOPE_USER)
    machine_state = policy.read_policy(policy.SCOPE_MACHINE)

    expected_url = cfg.site_list_file.resolve().as_uri() if cfg.site_list_file.exists() else ""
    active = machine_state if machine_state.enabled else user_state

    warnings: list[str] = []
    if not site_list["exists"]:
        warnings.append("站点列表文件还不存在，先在工具里保存一次即可生成。")
    if site_list["error"]:
        warnings.append(f"站点列表文件有问题：{site_list['error']}")
    if not active.exists:
        warnings.append("尚未写入 IE 模式策略，点“写入 IE 模式策略”即可。")
    elif not active.enabled:
        warnings.append(f"策略未完全生效：{active.summary()}")
    elif expected_url and active.site_list_url != expected_url:
        warnings.append(
            "当前生效的站点列表地址和工具里配置的不一致，可能是 IT 下发的策略：\n"
            f"    生效：{active.site_list_url}\n    期望：{expected_url}"
        )
    if machine_state.enabled and user_state.enabled and machine_state.site_list_url != user_state.site_list_url:
        warnings.append("机器策略与本机用户策略指向了不同的站点列表，Edge 会以机器策略为准。")
    if site_list["entries"] and site_list["ie_count"] == 0 and site_list["edge_count"] == 0:
        warnings.append("所有站点都是“中性”，需要手动点“在 IE 模式下重新加载”；如需自动切换请改成“强制 IE 模式”。")

    return {
        "app": APP_NAME,
        "app_version": __version__,
        "admin": policy.is_admin(),
        "python": sys.executable,
        "edge_path": str(edge_primary_path() or ""),
        "edge_version": edge_version(),
        "edge_running": edge_running(),
        "scope": cfg.scope,
        "site_list": site_list,
        "expected_url": expected_url,
        "user_policy": user_state,
        "machine_policy": machine_state,
        "active_scope": active.scope,
        "warnings": warnings,
    }


def render_text(info: dict) -> str:
    sl = info["site_list"]
    lines = [
        f"{info['app']} v{info['app_version']}",
        f"Python：{info['python']}",
        f"管理员权限：{'是' if info['admin'] else '否'}",
        "",
        f"Microsoft Edge：{info['edge_version']}",
        f"Edge 路径：{info['edge_path'] or '未找到'}",
        f"Edge 进程：{'运行中' if info['edge_running'] else '未运行'}",
        "",
        f"站点列表文件：{sl['path']}",
        f"  存在：{'是' if sl['exists'] else '否'}  版本号：{sl['version']}  条目数：{sl['entries']}",
        f"  强制 IE：{sl['ie_count']}  强制 Edge：{sl['edge_count']}  中性：{sl['neutral_count']}",
    ]
    if sl["error"]:
        lines.append(f"  错误：{sl['error']}")

    lines += [
        "",
        "策略状态（注册表 SOFTWARE\\Policies\\Microsoft\\Edge）：",
        f"  当前用户(HKCU)：{info['user_policy'].summary()}",
        f"  整机(HKLM)：{info['machine_policy'].summary()}",
        "",
        "在 Edge 里核对：edge://policy 搜 InternetExplorerIntegration，"
        "以及 edge://compat/enterprise 查看已加载的站点列表。",
    ]
    if info["warnings"]:
        lines.append("")
        lines.append("需要注意：")
        lines += [f"  - {item}" for item in info["warnings"]]
    return "\n".join(lines)
