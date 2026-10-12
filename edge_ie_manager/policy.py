"""通过 Edge 策略(注册表)注册企业模式站点列表。

策略依据：https://learn.microsoft.com/deployedge/microsoft-edge-browser-policies/internetexplorerintegrationsitelist

* 注册表路径：SOFTWARE\\Policies\\Microsoft\\Edge
* InternetExplorerIntegrationLevel = 1      -> 启用 IE 模式
* InternetExplorerIntegrationSiteList = URL  -> 站点列表地址
* Dynamic Policy Refresh: No - 需要重启浏览器

HKCU 为当前用户策略，不需要管理员；HKLM 为整机策略，需要管理员权限。
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .version import APP_NAME, __version__
from .runtime_env import stripped_bootstrap_environment

try:  # pragma: no cover - 非 Windows 平台
    import winreg
except ImportError:  # pragma: no cover
    winreg = None  # type: ignore[assignment]

POLICY_SUBKEY = r"SOFTWARE\Policies\Microsoft\Edge"

CREATE_NO_WINDOW = 0x08000000

VALUE_SITE_LIST = "InternetExplorerIntegrationSiteList"
VALUE_LEVEL = "InternetExplorerIntegrationLevel"
VALUE_REFRESH = "InternetExplorerIntegrationSiteListRefreshInterval"
VALUE_RELOAD_ALLOWED = "InternetExplorerIntegrationReloadInIEModeAllowed"
VALUE_KEEP_NAV = "InternetExplorerIntegrationKeepInPageNavigationInIEMode"

IE_MODE_LEVEL = 1

SCOPE_USER = "user"
SCOPE_MACHINE = "machine"
SCOPE_LABELS = {SCOPE_USER: "当前用户 (免管理员)", SCOPE_MACHINE: "整机 (需要管理员)"}
SCOPE_ROOT_NAMES = {SCOPE_USER: "HKEY_CURRENT_USER", SCOPE_MACHINE: "HKEY_LOCAL_MACHINE"}

# 本工具负责写入/清理的值，卸载时只动这几个，不影响 IT 下发的其它策略。
MANAGED_VALUES = (VALUE_SITE_LIST, VALUE_LEVEL, VALUE_REFRESH, VALUE_RELOAD_ALLOWED)


def is_supported() -> bool:
    return winreg is not None


def _root_and_path(scope: str, user_sid: str | None = None) -> tuple[int, str]:
    """返回 (注册表根键, 策略子键路径)。

    ``user_sid`` 只对用户范围有意义：给了就写 ``HKEY_USERS\\<SID>``。提权子进程
    会用这个把策略写回“原始用户”的账号，否则普通用户借用管理员账号提权时，
    策略会落到那个管理员名下，用户自己这边根本不生效。
    """
    if winreg is None:
        raise RuntimeError("当前环境不支持注册表操作。")
    if scope == SCOPE_MACHINE:
        return winreg.HKEY_LOCAL_MACHINE, POLICY_SUBKEY
    if user_sid:
        return winreg.HKEY_USERS, f"{user_sid}\\{POLICY_SUBKEY}"
    return winreg.HKEY_CURRENT_USER, POLICY_SUBKEY


def is_admin() -> bool:
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def current_user_sid() -> str | None:
    """返回当前登录账户的 SID（形如 S-1-5-21-...）。

    提权时会把原始用户的 SID 传给提权子进程，让它写 ``HKEY_USERS\\<SID>``。
    这样普通用户即使借别人的管理员账号提权，策略也会写回自己的账号。
    """
    if os.name != "nt":
        return None
    try:
        result = subprocess.run(
            ["whoami", "/user"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for token in (result.stdout or "").split():
        if token.upper().startswith("S-1-"):
            return token
    return None


def is_scope_writable(scope: str, user_sid: str | None = None) -> bool:
    """当前账户能否写入该范围的策略注册表（只探测权限，不改动注册表）。

    有的单位会把 HKCU\\SOFTWARE\\Policies 也锁成“只有管理员能写”，这时即使选
    “当前用户”范围也要提权。提前探测可以让界面把话说清楚，而不是等用户点了
    “写入 / 更新策略”才莫名其妙弹出 UAC。
    """
    if winreg is None:
        return False
    try:
        root, path = _root_and_path(scope, user_sid)
    except RuntimeError:
        return False
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_SET_VALUE):
            return True
    except FileNotFoundError:
        pass
    except OSError:
        return False
    # 策略键还不存在时，往上找最近一个存在的父键，看能否在其下创建子键。
    parts = path.split("\\")
    for end in range(len(parts) - 1, 0, -1):
        parent = "\\".join(parts[:end])
        try:
            with winreg.OpenKey(root, parent, 0, winreg.KEY_CREATE_SUB_KEY):
                return True
        except FileNotFoundError:
            continue
        except OSError:
            return False
    return False


@dataclass
class PolicyState:
    scope: str
    exists: bool = False
    site_list_url: str = ""
    level: int | None = None
    refresh_interval: int | None = None
    reload_allowed: int | None = None
    readable: bool = True
    error: str = ""
    extra_values: dict = field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        return bool(self.site_list_url) and self.level == IE_MODE_LEVEL

    def summary(self) -> str:
        if not self.readable:
            return f"无法读取（{self.error}）"
        if not self.exists:
            return "未配置"
        if not self.site_list_url:
            return "已配置但缺少站点列表地址"
        if self.level != IE_MODE_LEVEL:
            return f"站点列表已配置，但 IE 模式未启用 (Level={self.level})"
        return f"已启用 IE 模式，站点列表：{self.site_list_url}"


def read_policy(scope: str = SCOPE_USER, user_sid: str | None = None) -> PolicyState:
    state = PolicyState(scope=scope)
    if winreg is None:
        state.readable = False
        state.error = "非 Windows 环境"
        return state
    try:
        root, path = _root_and_path(scope, user_sid)
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ) as key:
            state.exists = True
            names = set()
            index = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, index)
                except OSError:
                    break
                names.add(name)
                if name == VALUE_SITE_LIST:
                    state.site_list_url = str(value)
                elif name == VALUE_LEVEL:
                    state.level = int(value)
                elif name == VALUE_REFRESH:
                    state.refresh_interval = int(value)
                elif name == VALUE_RELOAD_ALLOWED:
                    state.reload_allowed = int(value)
                else:
                    state.extra_values[name] = value
                index += 1
    except FileNotFoundError:
        state.exists = False
    except OSError as exc:
        state.readable = False
        state.error = str(exc)
    return state


def _write_value(
    scope: str, name: str, value, value_type: int, user_sid: str | None = None
) -> None:
    root, path = _root_and_path(scope, user_sid)
    with winreg.CreateKeyEx(root, path, 0, winreg.KEY_SET_VALUE | winreg.KEY_READ) as key:
        winreg.SetValueEx(key, name, 0, value_type, value)


def _delete_value(scope: str, name: str, user_sid: str | None = None) -> bool:
    if winreg is None:
        return False
    try:
        root, path = _root_and_path(scope, user_sid)
        with winreg.OpenKey(root, path, 0, winreg.KEY_SET_VALUE | winreg.KEY_READ) as key:
            winreg.DeleteValue(key, name)
        return True
    except FileNotFoundError:
        return False


def install_policy(
    scope: str,
    site_list_url: str,
    refresh_interval: int | None = None,
    allow_reload_in_ie: bool = True,
    user_sid: str | None = None,
) -> None:
    """写入启用 IE 模式所需的注册表策略。"""
    if scope not in (SCOPE_USER, SCOPE_MACHINE):
        raise ValueError(f"未知的范围：{scope}")
    if not site_list_url.strip():
        raise ValueError("站点列表地址不能为空。")

    _write_value(scope, VALUE_SITE_LIST, site_list_url.strip(), winreg.REG_SZ, user_sid)
    _write_value(scope, VALUE_LEVEL, IE_MODE_LEVEL, winreg.REG_DWORD, user_sid)
    _write_value(
        scope,
        VALUE_RELOAD_ALLOWED,
        1 if allow_reload_in_ie else 0,
        winreg.REG_DWORD,
        user_sid,
    )
    if refresh_interval and refresh_interval > 0:
        _write_value(
            scope,
            VALUE_REFRESH,
            int(refresh_interval),
            winreg.REG_DWORD,
            user_sid,
        )
    else:
        _delete_value(scope, VALUE_REFRESH, user_sid)


def uninstall_policy(scope: str, user_sid: str | None = None) -> list[str]:
    """删除本工具写入的注册表值，返回实际删除的值名。"""
    removed: list[str] = []
    for name in MANAGED_VALUES:
        if _delete_value(scope, name, user_sid):
            removed.append(name)
    return removed


def configured_scopes() -> list[PolicyState]:
    return [read_policy(SCOPE_USER), read_policy(SCOPE_MACHINE)]


def effective_state(preferred_scope: str = SCOPE_USER) -> PolicyState:
    """机器策略优先于用户策略；本工具默认按用户策略判断。"""
    states = {state.scope: state for state in configured_scopes()}
    machine = states[SCOPE_MACHINE]
    user = states[SCOPE_USER]
    if machine.enabled and user.enabled and machine.site_list_url != user.site_list_url:
        return machine
    return states.get(preferred_scope, user)


def export_reg_text(
    scope: str,
    site_list_url: str,
    refresh_interval: int | None = None,
    allow_reload_in_ie: bool = True,
) -> str:
    """生成可用于 regedit 导入的 .reg 文本（UTF-16 由调用方负责）。"""
    root = SCOPE_ROOT_NAMES.get(scope, "HKEY_CURRENT_USER")
    lines = [
        "Windows Registry Editor Version 5.00",
        "",
        f"[{root}\\{POLICY_SUBKEY}]",
        f'"{VALUE_SITE_LIST}"="{site_list_url}"',
        f'"{VALUE_LEVEL}"=dword:{IE_MODE_LEVEL:08x}',
        f'"{VALUE_RELOAD_ALLOWED}"=dword:{1 if allow_reload_in_ie else 0:08x}',
    ]
    if refresh_interval and refresh_interval > 0:
        lines.append(f'"{VALUE_REFRESH}"=dword:{int(refresh_interval):08x}')
    return "\n".join(lines) + "\n"


def export_reg_file(
    target: str | Path,
    scope: str,
    site_list_url: str,
    refresh_interval: int | None = None,
    allow_reload_in_ie: bool = True,
) -> Path:
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = export_reg_text(scope, site_list_url, refresh_interval, allow_reload_in_ie)
    path.write_text(text, encoding="utf-16")
    return path


def run_elevated(
    args: list[str],
    wait: bool = True,
    report_file: str | Path | None = None,
) -> tuple[bool, int]:
    """以管理员身份重新运行本工具，返回 (是否成功启动, 退出码)。"""
    argv = list(args)
    if report_file is not None:
        # --report-file 是全局选项，必须放在子命令之前。
        argv = ["--report-file", str(report_file), *argv]

    if getattr(sys, "frozen", False):
        # 打包后优先用同目录的命令行版可执行文件，它才认识这些参数。
        exe = Path(sys.executable)
        cli_candidate = exe.with_name("EdgeIEManager-CLI.exe")
        executable = str(cli_candidate) if cli_candidate.exists() else str(exe)
        params = subprocess.list2cmdline(argv)
    else:
        root = Path(__file__).resolve().parent.parent
        helper = root / "run_cli.py"
        executable = sys.executable
        # pythonw.exe 没有标准输出，会让命令行助手直接崩溃，换回同目录的 python.exe。
        exe_path = Path(executable)
        if exe_path.name.lower() == "pythonw.exe":
            console_python = exe_path.with_name("python.exe")
            if console_python.exists():
                executable = str(console_python)
        params = subprocess.list2cmdline([str(helper), *argv])

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("fMask", ctypes.c_ulong),
            ("hwnd", ctypes.c_void_p),
            ("lpVerb", ctypes.c_wchar_p),
            ("lpFile", ctypes.c_wchar_p),
            ("lpParameters", ctypes.c_wchar_p),
            ("lpDirectory", ctypes.c_wchar_p),
            ("nShow", ctypes.c_int),
            ("hInstApp", ctypes.c_void_p),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", ctypes.c_wchar_p),
            ("hkeyClass", ctypes.c_void_p),
            ("dwHotKey", ctypes.c_ulong),
            ("hIcon", ctypes.c_void_p),
            ("hProcess", ctypes.c_void_p),
        ]

    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SW_HIDE = 0

    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = executable
    info.lpParameters = params
    info.lpDirectory = str(Path.cwd())
    info.nShow = SW_HIDE

    # ShellExecuteExW 没有 env 参数，只能继承当前进程环境；先摘掉 _PYI_* 引导
    # 变量，否则提权起来的那一份会把自己当成老进程的子进程并报安全校验失败。
    with stripped_bootstrap_environment():
        launched = ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info))
    if not launched:
        return False, -1

    exit_code = 0
    if wait and info.hProcess:
        ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        code = ctypes.c_ulong(0)
        ctypes.windll.kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        exit_code = int(code.value)
        ctypes.windll.kernel32.CloseHandle(info.hProcess)
    return True, exit_code


def describe_scope(scope: str) -> str:
    return SCOPE_LABELS.get(scope, scope)
