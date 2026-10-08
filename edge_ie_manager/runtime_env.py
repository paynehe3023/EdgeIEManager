"""清理 PyInstaller 运行期环境变量。

onefile 打包的程序启动时，引导器会往环境里写三个变量：

* ``_PYI_ARCHIVE_FILE``          当前可执行文件的路径
* ``_PYI_PARENT_PROCESS_LEVEL``  本进程在 onefile 进程树里的层级
* ``_PYI_APPLICATION_HOME_DIR``  解包出来的临时目录

程序用同一个 exe 再启动一份自己（自更新重启、提权重启）时，这些变量会被子
进程原样继承。子进程的引导器发现 ``_PYI_ARCHIVE_FILE`` 与自身路径相同，就
判定“应该复用父进程的解包目录”，于是跳过解包、转去校验父进程。父进程这个
时候往往已经退出，校验失败，子进程弹框报错并直接退出：

    Security validation failure: failed to obtain executable path for parent process!

启动子进程前把这些变量擦干净，子进程就会当自己是全新实例，正常解包启动。
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator, Mapping

# PyInstaller 6.x 用 _PYI_ 前缀；_MEIPASS 前缀兼容旧版本的 _MEIPASS2。
BOOTSTRAP_ENV_PREFIXES = ("_PYI_", "_MEIPASS")


def _is_bootstrap_variable(key: str) -> bool:
    return key.upper().startswith(BOOTSTRAP_ENV_PREFIXES)


def clean_environment(
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """返回去掉 PyInstaller 引导变量的环境副本，可直接传给 ``subprocess``。"""
    source = os.environ if env is None else env
    return {
        key: value for key, value in source.items() if not _is_bootstrap_variable(key)
    }


@contextlib.contextmanager
def stripped_bootstrap_environment() -> Iterator[None]:
    """临时从 ``os.environ`` 里摘掉引导变量，退出时原样放回。

    给 ShellExecuteEx 这类没有 ``env`` 参数、只能继承当前进程环境的接口用。
    """
    saved = {
        key: os.environ.pop(key)
        for key in list(os.environ)
        if _is_bootstrap_variable(key)
    }
    try:
        yield
    finally:
        os.environ.update(saved)
