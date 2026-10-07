"""启动图形界面。双击本文件或使用 start_gui.bat。"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def cli_args(argv: list[str] | None = None, config_path: str | None = None) -> list[str] | None:
    """带参数启动时返回要转交命令行的参数，否则返回 None（表示打开界面）。

    打包成 exe 后，提权子进程会用同一个可执行文件加参数再启动一次。这里必须把
    参数交给命令行接口，否则那一次启动会再弹出一个界面窗口。
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return None
    if config_path and "--config" not in args:
        args = ["--config", str(config_path), *args]
    return args


def _crash_log_path(config_path: str | None = None) -> Path:
    if config_path:
        return Path(config_path).resolve().parent / "gui-crash.log"
    try:
        from edge_ie_manager.config import default_base_dir

        return default_base_dir() / "gui-crash.log"
    except Exception:
        return ROOT / "gui-crash.log"


def main(config_path: str | None = None) -> int:
    args = cli_args(config_path=config_path)
    if args is not None:
        from edge_ie_manager.cli import main as cli_main

        return cli_main(args)

    try:
        from edge_ie_manager.gui import run

        return run(config_path)
    except Exception:
        text = traceback.format_exc()
        log_path = _crash_log_path(config_path)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(text, encoding="utf-8")
        except OSError:
            pass
        try:
            import tkinter.messagebox as messagebox

            messagebox.showerror(
                "Edge IE 模式站点管理器启动失败",
                f"{text[-1200:]}\n\n详细信息已写入：\n{log_path}",
            )
        except Exception:
            print(text, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
