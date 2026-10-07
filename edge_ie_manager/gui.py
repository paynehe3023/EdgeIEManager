"""图形界面：日常维护站点列表只需要点几下。"""

from __future__ import annotations

import datetime as _dt
import queue
import sys
import tempfile
import threading
import time as _time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import diagnostics, policy, sitelist, theme, update
from .app import Manager
from .config import load_config, save_config
from .model import (
    MODE_DESCRIPTIONS,
    MODE_LABELS,
    SiteMode,
    mode_label,
    parse_mode,
)
from .sitelist import SiteListError
from .templates import UrlTemplate, add_months, render_template
from .version import APP_TITLE, __version__

LABEL_TO_MODE = {label: value for value, label in MODE_LABELS.items()}
MODE_CHOICES = [MODE_LABELS[key] for key in ("neutral", "ie", "edge")]
APP_USER_MODEL_ID = "4FP.EdgeIEManager"
# 日志窗口只保留最近这么多行，避免长时间运行后无限堆积。
LOG_MAX_LINES = 500


def _format_bytes(size: int) -> str:
    if size < 1024 * 1024:
        return f"{max(0, size) / 1024:.0f} KB"
    return f"{max(0, size) / 1024 / 1024:.1f} MB"


def _enable_dpi_awareness() -> None:
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # pragma: no cover - 老系统或非 Windows
        pass


def _set_app_user_model_id() -> None:
    """让 Windows 任务栏把本程序识别为独立应用。"""
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:  # pragma: no cover - 非 Windows
        pass


def _asset_path(filename: str) -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / "image" / filename
    return Path(__file__).resolve().parent.parent / "image" / filename


def _set_window_icon(root: tk.Tk) -> None:
    """使用多尺寸 ICO 自适应标题栏、任务栏和不同 DPI。"""
    ico_path = _asset_path("appIcon.ico")
    if ico_path.exists():
        try:
            root.iconbitmap(str(ico_path))
            root.iconbitmap(default=str(ico_path))
            return
        except tk.TclError:
            pass

    png_path = _asset_path("appIcon.png")
    try:
        photo = tk.PhotoImage(file=str(png_path))
        factor = max(1, (max(photo.width(), photo.height()) + 255) // 256)
        if factor > 1:
            photo = photo.subsample(factor, factor)
        root.iconphoto(True, photo)
        root._edge_app_icon = photo  # type: ignore[attr-defined]
    except (OSError, tk.TclError):
        pass


class _Tooltip:
    """轻量悬浮提示：chip 只放短文字，完整内容悬停查看。"""

    def __init__(self, widget: tk.Widget) -> None:
        self.widget = widget
        self.text = ""
        self._tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def set_text(self, text: str) -> None:
        self.text = (text or "").strip()

    def _show(self, _event=None) -> None:
        if not self.text or self._tip is not None:
            return
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        tk.Label(
            self._tip,
            text=self.text,
            justify="left",
            background="#ffffe1",
            foreground="#1b1b1b",
            relief="solid",
            borderwidth=1,
            padx=6,
            pady=4,
            wraplength=560,
        ).pack()

    def _hide(self, _event=None) -> None:
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


class App:
    def __init__(self, root: tk.Tk, config_path: str | None = None):
        self.root = root
        self.manager = Manager(config=load_config(Path(config_path) if config_path else None))
        self.site_list_error = ""
        self.tree_items: dict[str, str] = {}
        self.filter_text = tk.StringVar()
        # 后台任务回传队列：工作线程只往队列里放回调，界面线程定时取出执行。
        self._task_queue: queue.Queue = queue.Queue()
        self._status_inflight = False
        self._diagnose_inflight = False
        self._update_inflight = False
        self._pending_update = None
        self._download_log_milestone = -1
        self._about_dot: tk.Label | None = None
        self._download_frame: ttk.Frame | None = None
        self._download_label: ttk.Label | None = None
        self._download_progress: ttk.Progressbar | None = None
        self._download_cancel_button: ttk.Button | None = None
        self._download_token: update.CancelToken | None = None
        self._cancel_requested = False
        self._error_dialog_open = False
        self._error_dialogs_shown = 0
        self._closing = False
        # 状态芯片的圆点颜色角色（ok / warn / err / idle）
        self._chip_role: dict[str, str] = {"list": "idle", "policy": "idle", "edge": "idle"}
        self._menus: list[tk.Menu] = []
        # 列表排序状态
        self._sort_column = "url"
        self._sort_reverse = False

        root.title(f"{APP_TITLE} v{__version__}")
        _set_window_icon(root)
        root.geometry("1180x780")
        root.minsize(1020, 700)

        self._build_styles()
        self._build_top()
        self._build_template_bar()
        # 底部固定区域先布局，中间的列表最后占用剩余空间。
        self._build_actions()
        self._build_log()
        self._build_body()

        self.reload_all(first=True)
        self._refresh_status()
        self._apply_theme_widgets()
        self.root.after(150, self._poll_tasks)
        self._update_timer = self.root.after(2500, self._startup_update_work)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------ 界面
    def _build_styles(self) -> None:
        """先把 ttk 样式铺好，再建控件，否则控件会先按默认主题画出来。"""
        self._palette = theme.apply(self.root, self.manager.config.theme)

    def _apply_theme_widgets(self) -> None:
        """给 ttk 管不到的原生控件（Text/Listbox/Menu/标签色）上色。"""
        pal = self._palette
        theme.style_text_widget(self.log_text, pal)
        theme.style_text_widget(self.bulk_text, pal)
        self.log_text.tag_configure("info", foreground=pal["muted"])
        self.log_text.tag_configure("ok", foreground=pal["ok"])
        self.log_text.tag_configure("warn", foreground=pal["warn"])
        self.log_text.tag_configure("err", foreground=pal["err"])
        for tag, color in theme.row_tag_colors(self.manager.config.theme).items():
            self.tree.tag_configure(tag, background=color)
        for menu in self._menus:
            menu.configure(
                background=pal["card"],
                foreground=pal["fg"],
                activebackground=pal["select_bg"],
                activeforeground=pal["select_fg"],
                borderwidth=0,
            )
        for key, dot in self._chip_dots.items():
            role = self._chip_role.get(key, "idle")
            dot.configure(bg=pal["card"], fg=pal[f"{role}"] if role in pal else pal["muted"])
        if self._about_dot is not None:
            self._about_dot.configure(bg=pal["bg"], fg=pal["err"])

    def on_toggle_theme(self) -> None:
        self.manager.config.theme = theme.DARK if self.theme_var.get() else theme.LIGHT
        try:
            save_config(self.manager.config)
        except OSError:
            pass
        self._build_styles()
        self._apply_theme_widgets()
        self.log(f"已切换到{'深色' if self.theme_var.get() else '浅色'}主题。")

    def _build_top(self) -> None:
        bar = ttk.Frame(self.root, padding=(14, 12, 14, 8), style="Card.TFrame")
        bar.pack(fill="x")
        self.top_bar = bar

        # 右侧操作区先布局，保证主按钮一定拿得到位置，不会被长状态文字挤掉。
        self.theme_var = tk.BooleanVar(value=self.manager.config.theme == theme.DARK)
        ttk.Checkbutton(
            bar, text="深色模式", variable=self.theme_var, command=self.on_toggle_theme
        ).pack(side="right", padx=(10, 0))
        ttk.Button(bar, text="刷新状态", command=self._refresh_status).pack(side="right")
        self._diagnose_button = ttk.Button(bar, text="环境诊断", command=self.on_diagnose)
        self._diagnose_button.pack(side="right", padx=(0, 6))
        self._install_button = ttk.Button(
            bar, text="写入 / 更新策略", style="Accent.TButton", command=self.on_install_policy
        )
        self._install_button.pack(side="right", padx=(0, 8))
        # 三个状态芯片：彩色圆点 + 短文字，完整内容悬停查看
        self.status_labels: dict[str, ttk.Label] = {}
        self._chip_dots: dict[str, tk.Label] = {}
        self._chip_tips: dict[str, _Tooltip] = {}
        for key in ("list", "policy", "edge"):
            frame = ttk.Frame(bar, style="Card.TFrame")
            frame.pack(side="left", padx=(0, 16))
            dot = tk.Label(frame, text="\u25cf", bd=0, font=("Segoe UI", 11))
            dot.pack(side="left", padx=(0, 5))
            label = ttk.Label(frame, text="检查中…", style="Chip.TLabel")
            label.pack(side="left")
            self.status_labels[key] = label
            self._chip_dots[key] = dot
            self._chip_tips[key] = _Tooltip(label)

    def _build_template_bar(self) -> None:
        bar = ttk.Frame(self.root, padding=(14, 0, 14, 8), style="Card.TFrame")
        bar.pack(fill="x")
        self.template_bar = bar

        ttk.Label(bar, text="月度模板", style="CardHeading.TLabel").pack(side="left", padx=(0, 8))
        self.month_var = tk.StringVar(value="本月")
        month_combo = ttk.Combobox(
            bar, textvariable=self.month_var, values=["本月", "下月", "下下月"], state="readonly", width=7
        )
        month_combo.pack(side="left")
        month_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_templates())

        self.template_var = tk.StringVar()
        self.template_combo = ttk.Combobox(bar, textvariable=self.template_var, state="readonly", width=46)
        self.template_combo.pack(side="left", padx=8)

        ttk.Button(bar, text="生成到输入框", command=self.on_use_template).pack(side="left")
        ttk.Button(bar, text="一键添加该月全部", command=self.on_add_templates).pack(side="left", padx=6)
        ttk.Button(bar, text="管理模板", command=self.open_template_manager).pack(side="left")

        self.template_hint = ttk.Label(bar, text="", style="CardMuted.TLabel")
        self.template_hint.pack(side="right")

    def _build_body(self) -> None:
        body = ttk.Frame(self.root, padding=(14, 6, 14, 6))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=5)
        body.columnconfigure(1, weight=3)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        search = ttk.Frame(left)
        search.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(search, text="筛选：").pack(side="left")
        entry_filter = ttk.Entry(search, textvariable=self.filter_text)
        entry_filter.pack(side="left", fill="x", expand=True)
        entry_filter.bind("<KeyRelease>", lambda _event: self.refresh_tree())
        ttk.Button(search, text="清空", command=lambda: (self.filter_text.set(""), self.refresh_tree())).pack(
            side="left", padx=(6, 0)
        )

        columns = ("url", "mode", "note")
        self.tree = ttk.Treeview(
            left,
            columns=columns,
            show="headings",
            selectmode="extended",
            height=10,
        )
        self._tree_headings = {
            "url": "网址（站点列表条目）",
            "mode": "打开方式",
            "note": "备注",
        }
        self.tree.heading("url", text=self._tree_headings["url"], command=lambda: self.sort_tree("url"))
        self.tree.heading("mode", text=self._tree_headings["mode"], command=lambda: self.sort_tree("mode"))
        self.tree.heading("note", text=self._tree_headings["note"], command=lambda: self.sort_tree("note"))
        self.tree.column("url", width=330, anchor="w")
        self.tree.column("mode", width=120, anchor="center")
        self.tree.column("note", width=150, anchor="w")
        self.tree.grid(row=1, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<Double-1>", self.on_tree_select)

        scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)

        right = ttk.LabelFrame(body, text=" 添加 / 修改 ", padding=(12, 10))
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(1, weight=1)

        row = 0
        ttk.Label(right, text="网址").grid(row=row, column=0, sticky="w")
        self.url_var = tk.StringVar()
        ttk.Entry(right, textvariable=self.url_var).grid(row=row, column=1, sticky="ew", padx=(8, 0))
        row += 1
        ttk.Label(
            right,
            text="写 域名/路径 即可，不用带 http://（自动去掉）。",
            style="CardMuted.TLabel",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(2, 10))
        row += 1

        ttk.Label(right, text="打开方式").grid(row=row, column=0, sticky="nw")
        self.mode_var = tk.StringVar(value="ie")
        modes = ttk.Frame(right)
        modes.grid(row=row, column=1, sticky="w", padx=(8, 0))
        for value in ("ie", "neutral", "edge"):
            ttk.Radiobutton(
                modes, text=MODE_LABELS[value], value=value, variable=self.mode_var,
                command=self.on_mode_change,
            ).pack(side="left", padx=(0, 10))
        row += 1

        self.mode_hint = ttk.Label(right, text="", style="CardMuted.TLabel", wraplength=340, justify="left")
        self.mode_hint.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))
        row += 1

        ttk.Label(right, text="备注").grid(row=row, column=0, sticky="w")
        self.note_var = tk.StringVar()
        ttk.Entry(right, textvariable=self.note_var).grid(row=row, column=1, sticky="ew")
        row += 1

        buttons = ttk.Frame(right)
        buttons.grid(row=row, column=0, columnspan=2, sticky="w", pady=(12, 4))
        ttk.Button(buttons, text="添加", command=self.on_add).pack(side="left")
        ttk.Button(buttons, text="更新选中", command=self.on_update).pack(side="left", padx=6)
        self.delete_button = ttk.Button(buttons, text="删除选中", command=self.on_delete)
        self.delete_button.pack(side="left")
        row += 1

        ttk.Separator(right).grid(row=row, column=0, columnspan=2, sticky="ew", pady=2)
        row += 1

        ttk.Label(right, text="批量粘贴（每行一个网址）", style="CardHeading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1
        self.bulk_text = tk.Text(right, height=4, wrap="none")
        self.bulk_text.grid(row=row, column=0, columnspan=2, sticky="nsew", pady=(4, 4))
        row += 1
        bulk_buttons = ttk.Frame(right)
        bulk_buttons.grid(row=row, column=0, columnspan=2, sticky="ew")
        ttk.Button(bulk_buttons, text="批量添加", command=self.on_bulk_add).pack(side="left")
        ttk.Button(bulk_buttons, text="从剪贴板粘贴", command=self.on_paste_clipboard).pack(side="left", padx=6)

        self.on_mode_change()

    def _build_log(self) -> None:
        frame = ttk.LabelFrame(self.root, text=" 日志 ", padding=(10, 6))
        frame.pack(side="bottom", fill="x", padx=14, pady=(4, 6))
        self.log_frame = frame

        self._download_frame = ttk.Frame(frame, style="Card.TFrame")
        self._download_label = ttk.Label(
            self._download_frame, text="准备下载…", style="CardMuted.TLabel"
        )
        self._download_label.pack(side="left")
        self._download_progress = ttk.Progressbar(
            self._download_frame,
            orient="horizontal",
            mode="determinate",
            maximum=100,
            length=320,
        )
        self._download_progress.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self._download_cancel_button = ttk.Button(
            self._download_frame,
            text="取消下载",
            width=9,
            command=self._cancel_download,
        )
        self._download_cancel_button.pack(side="right", padx=(8, 0))

        body = ttk.Frame(frame)
        body.pack(fill="both", expand=True)
        self._log_body = body
        self.log_text = tk.Text(body, height=6, wrap="word", state="disabled")
        self.log_text.pack(side="left", fill="both", expand=True)

        side = ttk.Frame(body)
        side.pack(side="right", fill="y", padx=(6, 0))
        self.autoscroll_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(side, text="自动滚动", variable=self.autoscroll_var).pack(side="top")
        ttk.Button(side, text="清空日志", width=8, command=self.on_clear_log).pack(side="top", pady=(6, 0))
        ttk.Label(side, text=f"最多 {LOG_MAX_LINES} 行", style="CardMuted.TLabel").pack(side="top", pady=(4, 0))

    def _build_actions(self) -> None:
        bar = ttk.Frame(self.root, padding=(14, 0, 14, 12))
        bar.pack(side="bottom", fill="x")
        self.action_bar = bar

        ttk.Button(bar, text="移除策略", command=self.on_uninstall_policy).pack(side="left")
        ttk.Button(bar, text="重启 Edge 生效", command=self.on_restart_edge).pack(side="left", padx=6)
        ttk.Button(bar, text="打开检查页", command=self.on_open_check_pages).pack(side="left")
        ttk.Button(bar, text="导出 .reg", command=self.on_export_reg).pack(side="left", padx=6)

        self._menus: list[tk.Menu] = []
        more = ttk.Menubutton(bar, text="更多 \u25be")
        more_menu = tk.Menu(more, tearoff=False)
        more_menu.add_command(label="复制列表路径", command=self.on_copy_path)
        more_menu.add_command(label="打开数据文件夹", command=self.on_open_folder)
        more.configure(menu=more_menu)
        more.pack(side="left")
        self._menus.append(more_menu)

        # “关于”放在“更多”旁边，下拉里放版本号和检查更新
        self._about_dot = tk.Label(
            bar,
            text="",
            width=1,
            bd=0,
            font=("Segoe UI", 9),
            background=self._palette["bg"],
            foreground=self._palette["err"],
        )
        self._about_dot.pack(side="left", padx=(6, 0))
        self._about_button = ttk.Menubutton(bar, text="关于 \u25be")
        about_menu = tk.Menu(self._about_button, tearoff=False)
        about_menu.add_command(label=f"版本 v{__version__}", state="disabled")
        about_menu.add_separator()
        about_menu.add_command(label="检查更新", command=self.on_check_update)
        about_menu.add_command(
            label="打开下载页",
            command=lambda: update.open_releases_page(self.update_repo()),
        )
        self._about_button.configure(menu=about_menu)
        self._about_button.pack(side="left", padx=(2, 0))
        self._menus.append(about_menu)

        self.autosave_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="改动后自动保存", variable=self.autosave_var).pack(
            side="right", padx=(10, 0)
        )

        self.scope_var = tk.StringVar(
            value=policy.SCOPE_LABELS.get(self.manager.config.scope, policy.SCOPE_LABELS[policy.SCOPE_USER])
        )
        scope_combo = ttk.Combobox(
            bar,
            textvariable=self.scope_var,
            values=[policy.SCOPE_LABELS[policy.SCOPE_USER], policy.SCOPE_LABELS[policy.SCOPE_MACHINE]],
            state="readonly",
            width=18,
        )
        scope_combo.pack(side="right", padx=(6, 0))
        scope_combo.bind("<<ComboboxSelected>>", self.on_scope_change)
        ttk.Label(bar, text="策略范围").pack(side="right")

    # ------------------------------------------------------------------ 数据
    def reload_all(self, first: bool = False) -> None:
        self.manager.reload()
        self.site_list_error = ""
        try:
            _ = self.manager.site_list
        except SiteListError as exc:
            self.site_list_error = str(exc)
            self.manager._site_list = sitelist.new_site_list(self.manager.config.site_list_file)
            self.log(f"[!] 站点列表读取失败：{exc}")
            self.log("    已按空列表处理，保存时会先备份原文件。")

        self.refresh_tree()
        self.refresh_templates()
        if first:
            self.log(f"{APP_TITLE} v{__version__} 已就绪。")
            self.log(f"站点列表文件：{self.manager.config.site_list_file}")

    def refresh_tree(self) -> None:
        """按当前筛选与排序重建列表，并按打开方式给整行上底色。"""
        self.tree.delete(*self.tree.get_children())
        self.tree_items.clear()
        keyword = self.filter_text.get().strip().lower()
        sites = [
            site
            for site in self.manager.site_list.sites
            if not keyword
            or keyword in site.url.lower()
            or keyword in (site.note or "").lower()
        ]

        def sort_key(site):
            if self._sort_column == "mode":
                return mode_label(site.mode)
            if self._sort_column == "note":
                return (site.note or "").lower()
            return site.url.lower()

        sites.sort(key=sort_key, reverse=self._sort_reverse)

        for site in sites:
            item = self.tree.insert(
                "",
                "end",
                values=(site.url, mode_label(site.mode), site.note or ""),
                tags=(site.mode.value,),
            )
            self.tree_items[item] = site.url

        for column, text in self._tree_headings.items():
            arrow = ""
            if column == self._sort_column:
                arrow = " \u25b2" if not self._sort_reverse else " \u25bc"
            self.tree.heading(column, text=text + arrow)

    def sort_tree(self, column: str) -> None:
        if column == self._sort_column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column
            self._sort_reverse = False
        self.refresh_tree()

    def refresh_templates(self) -> None:
        """把该月渲染出来的模板填进下拉框，并统计可一键添加的数量。"""
        self._template_cache = self.manager.render_templates(month_offset=self.month_offset())
        labels = []
        for tpl, url in self._template_cache:
            flag = "●" if tpl.enabled else "○"
            labels.append(f"{flag} {tpl.name}  →  {url}")
        self.template_combo.configure(values=labels)
        if labels:
            self.template_combo.current(0)
        else:
            self.template_var.set("")
        enabled = sum(1 for tpl, _url in self._template_cache if tpl.enabled)
        self.template_hint.configure(
            text=f"● 可一键添加 {enabled} 条；○ 仅预览" if labels else "还没有模板，点右侧“管理模板”新增"
        )

    def month_offset(self) -> int:
        return {"本月": 0, "下月": 1, "下下月": 2}.get(self.month_var.get(), 0)

    def log(self, message: str, level: str = "info") -> None:
        """写一行日志。level 决定颜色：info / ok / warn / err。"""
        if level == "info" and message.startswith("[!]"):
            level = "warn"
        self.log_text.configure(state="normal")
        self.log_text.insert(
            "end", f"[{_dt.datetime.now().strftime('%H:%M:%S')}] {message}\n", level
        )
        self._trim_log()
        if getattr(self, "autoscroll_var", None) is None or self.autoscroll_var.get():
            self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _trim_log(self) -> None:
        """超出上限就从最旧的一行开始删，保证日志框占用的内存封顶。"""
        try:
            line_count = int(self.log_text.index("end-1c").split(".")[0])
        except (tk.TclError, ValueError):
            return
        if line_count > LOG_MAX_LINES:
            self.log_text.delete("1.0", f"{line_count - LOG_MAX_LINES + 1}.0")

    def on_clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.log("日志已清空。")

    def report(self, result) -> None:
        if result.details:
            for detail in result.details:
                if detail:
                    self.log(f"    {detail}")
        self.log(result.message)
        if not result.ok and result.level == "error":
            messagebox.showerror(APP_TITLE, result.message)

    def _refresh_status(self) -> None:
        """刷新顶部状态条。

        读注册表和探测 Edge 进程都会起子进程，放在界面线程里会让窗口卡住甚至
        “未响应”。这里丢到后台线程，结果通过队列回到界面线程再更新。
        """
        if self._status_inflight:
            return
        self._status_inflight = True
        scope = self.current_scope()
        threading.Thread(target=self._status_worker, args=(scope,), daemon=True).start()

    def _status_worker(self, scope: str) -> None:
        payload: dict = {}
        try:
            try:
                sl = self.manager.site_list
                payload["list_text"] = f"站点列表 {len(sl.sites)} 条 · 修订 {sl.version}"
                payload["list_tip"] = str(self.manager.config.site_list_file)
                payload["list_role"] = "ok"
            except Exception as exc:  # 站点列表损坏时也不能把界面拖垮
                payload["list_text"] = "站点列表读取失败"
                payload["list_tip"] = f"站点列表读取失败：{exc}"
                payload["list_role"] = "err"

            try:
                state = policy.read_policy(scope)
                summary = state.summary()
                payload["policy_tip"] = summary
                if state.enabled:
                    payload["policy_text"] = "策略已启用 IE 模式"
                    payload["policy_role"] = "ok"
                elif state.exists:
                    payload["policy_text"] = "策略未完全生效"
                    payload["policy_role"] = "warn"
                elif not state.readable:
                    payload["policy_text"] = "策略无法读取"
                    payload["policy_role"] = "err"
                else:
                    payload["policy_text"] = "策略未配置"
                    payload["policy_role"] = "idle"
            except Exception as exc:
                payload["policy_text"] = "策略读取出错"
                payload["policy_tip"] = f"读取策略失败：{exc}"
                payload["policy_role"] = "err"

            try:
                payload["running"] = diagnostics.edge_running()
            except Exception:
                payload["running"] = False
        except BaseException:
            pass

        self._task_queue.put(lambda: self._apply_status(payload))

    def _apply_status(self, payload: dict) -> None:
        try:
            self._set_chip(
                "list",
                payload.get("list_text", "-"),
                payload.get("list_role", "idle"),
                payload.get("list_tip", ""),
            )
            self._set_chip(
                "policy",
                payload.get("policy_text", "-"),
                payload.get("policy_role", "idle"),
                payload.get("policy_tip", ""),
            )
            running = bool(payload.get("running"))
            self._set_chip(
                "edge",
                "Edge 运行中" if running else "Edge 未运行",
                "warn" if running else "idle",
                "Edge 正在运行：改动策略后需要重启 Edge 才会生效。"
                if running
                else "Edge 未运行：下次启动 Edge 时策略自动生效。",
            )
        finally:
            self._status_inflight = False

    def _set_chip(self, key: str, text: str, role: str, full_text: str = "") -> None:
        """更新顶部状态芯片：短文字 + 圆点颜色，完整内容放到悬停提示。"""
        self._chip_role[key] = role
        style = {
            "ok": "ChipOk.TLabel",
            "warn": "ChipWarn.TLabel",
            "err": "ChipErr.TLabel",
        }.get(role, "Chip.TLabel")
        self.status_labels[key].configure(text=text, style=style)
        tip = self._chip_tips.get(key)
        if tip is not None:
            tip.set_text(full_text)
        dot = self._chip_dots.get(key)
        if dot is not None:
            pal = self._palette
            dot.configure(bg=pal["card"], fg=pal.get(role, pal["muted"]))

    def _poll_tasks(self) -> None:
        """界面线程定时取出后台线程排队的回调，保证只有主线程碰控件。"""
        if self._closing:
            return
        try:
            while True:
                task = self._task_queue.get_nowait()
                try:
                    task()
                except Exception:
                    pass
        except queue.Empty:
            pass
        try:
            self.root.after(150, self._poll_tasks)
        except tk.TclError:
            pass

    def current_scope(self) -> str:
        label = self.scope_var.get()
        for scope, text in policy.SCOPE_LABELS.items():
            if text == label:
                return scope
        return policy.SCOPE_USER

    # ------------------------------------------------------------------ 事件
    def selected_url(self) -> str | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self.tree_items.get(selection[0])

    def on_tree_select(self, _event=None) -> None:
        url = self.selected_url()
        if not url:
            return
        site = self.manager.site_list.find(url)
        if not site:
            return
        self.url_var.set(site.url)
        self.mode_var.set(site.mode.value)
        self.note_var.set(site.note or "")
        self.on_mode_change()

    def on_mode_change(self, _event=None) -> None:
        self.mode_hint.configure(text=MODE_DESCRIPTIONS.get(self.mode_var.get(), ""))

    def on_scope_change(self, _event=None) -> None:
        self.manager.config.scope = self.current_scope()
        save_config(self.manager.config)
        self._refresh_status()
        self.log(f"策略范围已切换为：{policy.describe_scope(self.current_scope())}")

    def on_add(self) -> None:
        url = self.url_var.get().strip()
        if not url:
            messagebox.showinfo(APP_TITLE, "请先填写网址。")
            return
        mode = parse_mode(self.mode_var.get(), SiteMode.IE)
        result = self.manager.add_site(url, mode=mode, note=self.note_var.get().strip(), save=self.autosave_var.get())
        self.report(result)
        if result.ok:
            self.url_var.set("")
            self.note_var.set("")
            self._after_change()

    def on_update(self) -> None:
        old_url = self.selected_url()
        if not old_url:
            messagebox.showinfo(APP_TITLE, "请先在左侧选中要修改的记录。")
            return
        mode = parse_mode(self.mode_var.get(), SiteMode.IE)
        result = self.manager.update_site(
            old_url,
            self.url_var.get().strip(),
            mode,
            self.note_var.get().strip(),
            save=self.autosave_var.get(),
        )
        self.report(result)
        if result.ok:
            self._after_change()

    def on_delete(self) -> None:
        url = self.selected_url()
        if not url:
            messagebox.showinfo(APP_TITLE, "请先在左侧选中要删除的记录。")
            return
        if not messagebox.askyesno(APP_TITLE, f"确定要从站点列表里删除吗？\n\n{url}"):
            return
        result = self.manager.remove_site(url, save=self.autosave_var.get())
        self.report(result)
        self._after_change()

    def on_bulk_add(self) -> None:
        text = self.bulk_text.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo(APP_TITLE, "请先粘贴要添加的网址，每行一个。")
            return
        urls, bad = self.manager.bulk_parse(text)
        if bad:
            self.log(f"[!] 以下 {len(bad)} 行无法识别，已忽略：{'; '.join(bad[:5])}")
        if not urls:
            messagebox.showwarning(APP_TITLE, "没有解析出有效网址。")
            return
        mode = parse_mode(self.mode_var.get(), SiteMode.IE)
        result = self.manager.add_many(urls, mode=mode, note=self.note_var.get().strip(), save=self.autosave_var.get())
        self.report(result)
        self.bulk_text.delete("1.0", "end")
        self._after_change()

    def on_paste_clipboard(self) -> None:
        try:
            data = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showinfo(APP_TITLE, "剪贴板里没有文本。")
            return
        self.bulk_text.delete("1.0", "end")
        self.bulk_text.insert("1.0", data)
        self.log("已从剪贴板填入，检查无误后点“批量添加”。")

    def on_use_template(self) -> None:
        index = self.template_combo.current()
        if index < 0 or index >= len(self._template_cache):
            messagebox.showinfo(APP_TITLE, "请先在上方的模板下拉框里选一个模板。")
            return
        tpl, url = self._template_cache[index]
        self.url_var.set(url)
        self.mode_var.set(parse_mode(tpl.mode, SiteMode.IE).value)
        self.note_var.set(tpl.note or tpl.name)
        self.on_mode_change()
        self.log(f"已生成网址：{url}", "ok")

    def on_add_templates(self) -> None:
        result = self.manager.add_from_templates(
            month_offset=self.month_offset(), save=self.autosave_var.get()
        )
        self.report(result)
        self._after_change()

    def _after_change(self) -> None:
        self.refresh_tree()
        self.refresh_templates()
        self._refresh_status()

    # ------------------------------------------------------------------ 动作
    def on_install_policy(self) -> None:
        scope = self.current_scope()
        result = self.manager.install_policy(scope=scope)
        if not result.ok and result.needs_admin:
            if not self._confirm_elevation(
                "写入这条策略需要管理员权限。\n\n"
                "当前账户对注册表的 Policies 位置只有只读权限（常见于单位统一管控的电脑），"
                "需要弹出 UAC 提示，以管理员身份重试。\n\n继续吗？"
            ):
                self.report(result)
                return
            result = self.manager.install_policy(scope=scope, elevate=True)
        self.report(result)
        self._refresh_status()
        if result.ok:
            self.log("提示：Edge 需要重启才能读取新策略；可在 edge://compat/enterprise 查看已加载的站点列表。")

    def on_uninstall_policy(self) -> None:
        scope = self.current_scope()
        if not messagebox.askyesno(
            APP_TITLE,
            "确定要删除本工具写入的 IE 模式策略吗？\n\n"
            "删除后需要重启 Edge，才会恢复系统原有的 IE 模式行为。",
        ):
            return
        result = self.manager.uninstall_policy(scope=scope)
        if not result.ok and result.needs_admin:
            if not self._confirm_elevation(
                "删除这条策略需要管理员权限，是否弹出 UAC 提示并以管理员身份重试？"
            ):
                self.report(result)
                return
            result = self.manager.uninstall_policy(scope=scope, elevate=True)
        self.report(result)
        self._refresh_status()

    def _confirm_elevation(self, message: str) -> bool:
        return messagebox.askyesno(APP_TITLE, message)

    def on_restart_edge(self) -> None:
        if not messagebox.askyesno(
            APP_TITLE,
            "将强制关闭所有 Edge 窗口后重新启动，未保存的网页内容可能丢失。继续吗？",
        ):
            return
        result = self.manager.restart_edge()
        self.report(result)
        self._refresh_status()

    def on_open_check_pages(self) -> None:
        """打开 Edge 内部检查页，并把“应该看到什么”一起写进日志。"""
        if not diagnostics.edge_primary_path():
            messagebox.showerror(APP_TITLE, "没有找到 Microsoft Edge，无法打开检查页。")
            return

        expected = self.manager.site_list_url()
        ok, message = diagnostics.launch_edge(["edge://policy", "edge://compat/enterprise"])
        if not ok:
            self.log(f"[!] {message}")
            messagebox.showerror(APP_TITLE, message)
            return

        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(expected)
            copied = expected
        except tk.TclError:
            copied = ""

        self.log("已打开两个检查页，请对照下面的值核对：")
        self.log(f"  edge://policy → 搜 InternetExplorerIntegrationSiteList，值应为：{expected}")
        self.log("    其中 InternetExplorerIntegrationLevel 应为 1。")
        self.log("  edge://compat/enterprise → 看“站点列表”里是否就是本工具的条目。")
        if copied:
            self.log(f"  站点列表地址已复制到剪贴板：{copied}")

    def on_export_reg(self) -> None:
        scope = self.current_scope()
        default = str(self.manager.config.base_dir / f"edge-ie-mode-{scope}.reg")
        target = filedialog.asksaveasfilename(
            title="导出注册表文件",
            defaultextension=".reg",
            initialfile=Path(default).name,
            initialdir=str(self.manager.config.base_dir),
            filetypes=[("注册表文件", "*.reg")],
        )
        if not target:
            return
        try:
            path = policy.export_reg_file(
                target,
                scope,
                self.manager.site_list_url(),
                refresh_interval=self.manager.config.refresh_interval or None,
                allow_reload_in_ie=self.manager.config.allow_reload_in_ie,
            )
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"导出失败：{exc}")
            return
        self.log(f"已导出：{path}")
        messagebox.showinfo(APP_TITLE, f"已导出注册表文件：\n{path}\n\n双击导入即可（整机策略需以管理员身份导入）。")

    def on_diagnose(self) -> None:
        """环境诊断：收集环境信息。中间要起 PowerShell/tasklist，放后台跑。"""
        if self._diagnose_inflight:
            return
        self._diagnose_inflight = True
        self._diagnose_button.state(["disabled"])
        self.log("正在收集环境诊断信息…")
        threading.Thread(target=self._diagnose_worker, daemon=True).start()

    def _diagnose_worker(self) -> None:
        try:
            text = diagnostics.render_text(self.manager.report())
        except Exception as exc:
            text = f"[!] 环境诊断失败：{exc}"
        self._task_queue.put(lambda: self._apply_diagnose(text))

    def _apply_diagnose(self, text: str) -> None:
        try:
            self.log(text)
            self._refresh_status()
        finally:
            self._diagnose_inflight = False
            self._diagnose_button.state(["!disabled"])

    def on_open_folder(self) -> None:
        path = self.manager.config.site_list_file.parent
        path.mkdir(parents=True, exist_ok=True)
        try:
            import os

            os.startfile(str(path))  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"无法打开文件夹：{exc}")

    def on_copy_path(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.manager.site_list_url())
        self.log(f"已复制站点列表地址：{self.manager.site_list_url()}")

    # ------------------------------------------------------------------ 更新
    def update_repo(self) -> str:
        """当前使用的更新源：配置里填了就用配置的，否则用内置默认值。"""
        return (self.manager.config.update_repo or update.DEFAULT_REPO).strip()

    def _startup_update_work(self) -> None:
        """启动后清理上次更新残留，并按需静默检查一次。"""
        exe = update.current_exe()
        if exe is not None:
            update.cleanup_old_files(exe.parent)
        if self.manager.config.update_auto_check and self.update_repo():
            self._check_update(silent=True)

    def on_check_update(self) -> None:
        """按钮入口：已经查到新版本就直接进入升级流程，否则重新检查。"""
        if self._pending_update is not None:
            self._prompt_update(self._pending_update)
            return
        self._check_update(silent=False)

    def _check_update(self, silent: bool) -> None:
        repo = self.update_repo()
        if not repo:
            if not silent:
                messagebox.showinfo(
                    APP_TITLE,
                    "还没有配置更新源。\n\n请在 config.json 里填写 update_repo（格式 owner/repo）。",
                )
            return
        if self._update_inflight:
            return
        self._update_inflight = True
        if not silent:
            self.log("正在检查更新…")
        threading.Thread(
            target=self._update_check_worker, args=(repo, silent), daemon=True
        ).start()

    def _update_check_worker(self, repo: str, silent: bool) -> None:
        try:
            info = update.check_for_update(repo)
        except Exception as exc:
            self._task_queue.put(lambda: self._update_check_failed(str(exc), silent))
            return
        self._task_queue.put(lambda: self._update_check_done(info, silent))

    def _update_check_failed(self, message: str, silent: bool) -> None:
        self._update_inflight = False
        self.log(f"[!] 检查更新失败：{message}", "warn")
        if not silent:
            messagebox.showwarning(APP_TITLE, f"检查更新失败：\n{message}")

    def _update_check_done(self, info, silent: bool) -> None:
        self._update_inflight = False
        if info is None:
            self._pending_update = None
            self._set_update_available(False)
            self.log(f"已是最新版本 v{__version__}。", "ok")
            if not silent:
                messagebox.showinfo(APP_TITLE, f"当前已是最新版本 v{__version__}。")
            return

        self._pending_update = info
        self._set_update_available(True)
        self.log(f"发现新版本 {info.display}（当前 v{__version__}）。", "ok")
        if not silent:
            self._prompt_update(info)

    def _set_update_available(self, available: bool) -> None:
        if self._about_dot is not None:
            self._about_dot.configure(text="\u25cf" if available else "")

    def _prompt_update(self, info) -> None:
        lines = [f"当前版本：v{__version__}", f"最新版本：{info.display}"]
        if info.notes:
            notes = info.notes.strip()
            if len(notes) > 600:
                notes = notes[:600] + "…"
            lines += ["", "更新说明：", notes]

        if not update.can_self_update():
            lines += ["", "当前运行的版本不支持自动替换（便携版或源码运行），请到下载页手动下载。"]
            if messagebox.askyesno(APP_TITLE, "\n".join(lines) + "\n\n要打开下载页吗？"):
                update.open_releases_page(self.update_repo())
            return

        if not messagebox.askyesno(
            APP_TITLE,
            "\n".join(lines) + "\n\n现在下载并更新吗？完成后程序会自动重启。",
        ):
            return
        self._install_update(info)

    def _install_update(self, info) -> None:
        exe = update.current_exe()
        if exe is None:
            update.open_releases_page(self.update_repo())
            return
        if self._update_inflight:
            return
        self._update_inflight = True
        self._cancel_requested = False
        self._download_token = update.CancelToken()
        self._begin_download_progress()
        self.log(f"开始下载 {info.display}…")
        threading.Thread(
            target=self._update_download_worker, args=(info, exe), daemon=True
        ).start()

    def _update_download_worker(self, info, exe) -> None:
        target = exe.with_name(update.ASSET_NAME + ".new")
        state = {"last": None, "time": 0.0}

        def progress(done: int, total: int) -> None:
            now = _time.monotonic()
            if total <= 0:
                # 总量未知：按时间节流，避免每 64KB 就往界面塞一条消息。
                if now - state["time"] < 0.2:
                    return
                state["time"] = now
            else:
                percent = int(done * 100 / total)
                if percent == state["last"]:
                    return
                state["last"] = percent
            self._task_queue.put(lambda d=done, t=total: self._set_download_progress(d, t))

        try:
            update.download(info, target, progress=progress, token=self._download_token)
            if self._cancel_requested:
                raise update.UpdateCancelled("已取消下载。")
            update.apply_update(target, exe)
        except update.UpdateCancelled:
            self._task_queue.put(self._download_cancelled)
            return
        except Exception as exc:
            if self._cancel_requested:
                self._task_queue.put(self._download_cancelled)
            else:
                self._task_queue.put(lambda: self._update_install_failed(str(exc)))
            return
        self._task_queue.put(lambda: self._update_install_done(exe))

    def _begin_download_progress(self) -> None:
        if (
            self._download_frame is None
            or self._download_label is None
            or self._download_progress is None
        ):
            return
        self._download_log_milestone = -1
        self._download_label.configure(text="正在连接下载服务器…")
        self._download_progress.stop()
        self._download_progress.configure(mode="indeterminate", maximum=100, value=0)
        self._download_progress.start(12)
        if self._download_cancel_button is not None:
            self._download_cancel_button.configure(state="normal", text="取消下载")
        if not self._download_frame.winfo_manager():
            self._download_frame.pack(fill="x", before=self._log_body, pady=(0, 6))

    def _set_download_progress(self, done: int, total: int) -> None:
        if (
            self._download_label is None
            or self._download_progress is None
            or self._download_frame is None
        ):
            return
        if total <= 0:
            self._download_progress.configure(mode="indeterminate")
            self._download_progress.start(12)
            if done <= 0:
                self._download_label.configure(text="正在连接下载服务器…")
            else:
                self._download_label.configure(text=f"正在下载 {_format_bytes(done)}…")
            return

        percent = max(0, min(100, int(done * 100 / total)))
        self._download_progress.stop()
        self._download_progress.configure(mode="determinate", maximum=100, value=percent)
        self._download_label.configure(
            text=f"正在下载 {percent}%  {_format_bytes(done)} / {_format_bytes(total)}"
        )
        milestone = percent // 20
        if milestone > self._download_log_milestone:
            self._download_log_milestone = milestone
            self.log(f"  已下载 {percent}%")

    def _finish_download_progress(self) -> None:
        if self._download_progress is not None:
            self._download_progress.stop()
        if self._download_cancel_button is not None:
            self._download_cancel_button.configure(state="disabled")
        self._download_token = None
        if self._download_frame is not None and self._download_frame.winfo_manager():
            self._download_frame.pack_forget()

    def _cancel_download(self) -> None:
        """用户点了取消：立刻断开连接，剩下的交给下载线程收尾。"""
        if not self._update_inflight or self._download_token is None:
            return
        self._cancel_requested = True
        self._download_token.cancel()
        if self._download_label is not None:
            self._download_label.configure(text="正在取消下载…")
        if self._download_cancel_button is not None:
            self._download_cancel_button.configure(state="disabled")
        self.log("正在取消下载…", "warn")

    def _download_cancelled(self) -> None:
        self._update_inflight = False
        self._cancel_requested = False
        self._finish_download_progress()
        self.log("已取消更新下载，文件已清理。", "warn")

    def _update_install_failed(self, message: str) -> None:
        self._update_inflight = False
        self._finish_download_progress()
        self.log(f"[!] 更新失败：{message}", "warn")
        messagebox.showerror(
            APP_TITLE, f"更新失败：\n{message}\n\n也可以到下载页手动获取新版本。"
        )

    def _update_install_done(self, exe) -> None:
        self._update_inflight = False
        self._pending_update = None
        self._set_update_available(False)
        self._finish_download_progress()
        self.log("更新完成，正在重启程序…", "ok")
        try:
            update.restart(exe)
        except OSError as exc:
            self.log(f"[!] 自动重启失败，请手动重新打开程序：{exc}", "warn")
            return
        self.on_close()

    def on_close(self) -> None:
        self._closing = True
        try:
            self.manager.config.scope = self.current_scope()
            save_config(self.manager.config)
        except OSError:
            pass
        self.root.destroy()

    # ------------------------------------------------------------ 模板对话框
    def open_template_manager(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("月度模板管理")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("720x420")

        ttk.Label(
            dialog,
            text="模板示例：report.contoso.com/{yyyy}{MM}/index.html",
            style="Status.TLabel",
        ).pack(anchor="w", padx=10, pady=(10, 2))
        ttk.Label(
            dialog,
            text="可用占位符：{yyyy} {yy} {MM} {M} {QQ} {Q} {dd}",
            style="Status.TLabel",
        ).pack(anchor="w", padx=10)

        panes = ttk.Frame(dialog, padding=10)
        panes.pack(fill="both", expand=True)

        listbox = tk.Listbox(panes, width=34, exportselection=False)
        listbox.pack(side="left", fill="both", expand=False)

        form = ttk.Frame(panes, padding=(10, 0))
        form.pack(side="left", fill="both", expand=True)
        form.columnconfigure(1, weight=1)

        name_var = tk.StringVar()
        tpl_var = tk.StringVar()
        mode_var = tk.StringVar(value=MODE_LABELS["ie"])
        note_var = tk.StringVar()
        enabled_var = tk.BooleanVar(value=True)

        def add_row(row: int, label: str, widget: tk.Widget) -> None:
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=3)
            widget.grid(row=row, column=1, sticky="ew", pady=3)

        add_row(0, "名称", ttk.Entry(form, textvariable=name_var))
        add_row(1, "模板", ttk.Entry(form, textvariable=tpl_var))
        add_row(
            2,
            "打开方式",
            ttk.Combobox(
                form,
                textvariable=mode_var,
                values=[MODE_LABELS[v] for v in ("ie", "neutral", "edge")],
                state="readonly",
            ),
        )
        add_row(3, "备注", ttk.Entry(form, textvariable=note_var))
        ttk.Checkbutton(form, text="纳入“一键添加该月全部”", variable=enabled_var).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=3
        )
        preview = ttk.Label(form, text="", style="Status.TLabel", wraplength=320, justify="left")
        preview.grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

        def refresh_list(select: int | None = None) -> None:
            listbox.delete(0, "end")
            for item in self.manager.config.templates:
                flag = "●" if item.enabled else "○"
                listbox.insert("end", f"{flag} {item.name}")
            if select is not None and 0 <= select < listbox.size():
                listbox.selection_set(select)

        def load_selection(_event=None) -> None:
            selection = listbox.curselection()
            if not selection:
                return
            item = self.manager.config.templates[selection[0]]
            name_var.set(item.name)
            tpl_var.set(item.template)
            mode_var.set(MODE_LABELS[parse_mode(item.mode, SiteMode.IE).value])
            note_var.set(item.note)
            enabled_var.set(item.enabled)
            update_preview()

        def update_preview(*_args) -> None:
            rendered = render_template(tpl_var.get() or "", _dt.date.today())
            preview.configure(text=f"本月预览：{rendered}" if tpl_var.get() else "")

        listbox.bind("<<ListboxSelect>>", load_selection)
        tpl_var.trace_add("write", update_preview)
        refresh_list(0)
        load_selection()

        def new_item() -> None:
            name_var.set("新模板")
            tpl_var.set("report.example.com/{yyyy}{MM}")
            mode_var.set(MODE_LABELS["ie"])
            note_var.set("")
            enabled_var.set(True)
            listbox.selection_clear(0, "end")
            update_preview()

        def save_item() -> None:
            selection = listbox.curselection()
            item = UrlTemplate(
                name=name_var.get().strip() or "未命名模板",
                template=tpl_var.get().strip(),
                mode=parse_mode(LABEL_TO_MODE.get(mode_var.get(), mode_var.get()), SiteMode.IE).value,
                note=note_var.get().strip(),
                enabled=bool(enabled_var.get()),
            )
            if not item.template:
                messagebox.showwarning(APP_TITLE, "模板内容不能为空。", parent=dialog)
                return
            if selection:
                index = selection[0]
                self.manager.config.templates[index] = item
            else:
                index = len(self.manager.config.templates)
                self.manager.config.templates.append(item)
            save_config(self.manager.config)
            refresh_list(index)
            self.refresh_templates()
            self.log(f"模板已保存：{item.name}")

        def delete_item() -> None:
            selection = listbox.curselection()
            if not selection:
                return
            if not messagebox.askyesno(APP_TITLE, "确定删除该模板？", parent=dialog):
                return
            index = selection[0]
            del self.manager.config.templates[index]
            save_config(self.manager.config)
            refresh_list(max(0, index - 1))
            load_selection()
            self.refresh_templates()

        buttons = ttk.Frame(form)
        buttons.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(buttons, text="新增", command=new_item).pack(side="left")
        ttk.Button(buttons, text="保存", command=save_item).pack(side="left", padx=4)
        ttk.Button(buttons, text="删除", command=delete_item).pack(side="left")
        ttk.Button(buttons, text="关闭", command=dialog.destroy).pack(side="right")

        # 同步月份选择的变化到模板预览列表
        self.root.after(200, self.refresh_templates)


def build_app(config_path: str | None = None) -> tuple[tk.Tk, App]:
    _enable_dpi_awareness()
    _set_app_user_model_id()
    root = tk.Tk()
    app = App(root, config_path=config_path)

    def _excepthook(exc_type, exc_value, exc_tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        lines = text.strip().splitlines()
        summary = lines[-1] if lines else repr(exc_value)
        try:
            app.log("[!] 界面异常：" + summary)
        except Exception:
            pass

        try:
            crash = app.manager.config.base_dir / "gui-crash.log"
            crash.parent.mkdir(parents=True, exist_ok=True)
            with crash.open("a", encoding="utf-8") as handle:
                handle.write(f"\n--- {_dt.datetime.now():%Y-%m-%d %H:%M:%S} ---\n{text}\n")
        except Exception:
            pass

        # 某个回调反复出错时，messagebox 会嵌套进事件循环，一层层叠出新的错误
        # 窗口，最后关都关不掉。这里限制成“同一时刻一个、全程最多 3 个”。
        if app._error_dialog_open or app._error_dialogs_shown >= 3:
            return
        app._error_dialogs_shown += 1
        app._error_dialog_open = True
        try:
            messagebox.showerror(APP_TITLE, text[-1500:], parent=root)
        except Exception:
            pass
        finally:
            app._error_dialog_open = False

    root.report_callback_exception = _excepthook
    return root, app


def run(config_path: str | None = None) -> int:
    root, _app = build_app(config_path)
    root.mainloop()
    return 0


def smoke_test(config_path: str | None = None) -> list[str]:
    """构建界面但不显示，用于自动化自检。默认用临时目录，不碰真实数据。"""
    _enable_dpi_awareness()
    _set_app_user_model_id()
    temp_dir: tempfile.TemporaryDirectory | None = None
    if config_path is None:
        temp_dir = tempfile.TemporaryDirectory()
        config_path = str(Path(temp_dir.name) / "config.json")
    root = tk.Tk()
    root.withdraw()
    app = App(root, config_path=config_path)
    notes: list[str] = []
    try:
        # 自检不打网络：取消启动后的自动检查更新
        try:
            root.after_cancel(app._update_timer)
        except (tk.TclError, AttributeError):
            pass
        app.refresh_templates()
        app._refresh_status()
        notes.append("界面构建成功")
        app.log("smoke test")

        # 等后台状态刷新把结果送回界面，确认异步链路通。
        deadline = _dt.datetime.now() + _dt.timedelta(seconds=15)
        while app._status_inflight and _dt.datetime.now() < deadline:
            try:
                app._task_queue.get_nowait()()
            except queue.Empty:
                root.update()
                _time.sleep(0.03)
        notes.append("状态刷新完成" if not app._status_inflight else "状态刷新超时")

        # 日志上限：灌进去远超上限的行数，确认最终被裁剪到 LOG_MAX_LINES。
        for index in range(LOG_MAX_LINES + 300):
            app.log(f"压力行 {index}")
        lines = int(app.log_text.index("end-1c").split(".")[0])
        notes.append(f"日志上限：{LOG_MAX_LINES}，实际保留 {lines} 行")

        app.on_clear_log()
        notes.append(f"清空日志后剩 {int(app.log_text.index('end-1c').split('.')[0])} 行")

        root.update_idletasks()
        notes.append(f"模板数量：{len(app._template_cache)}")
        notes.append(f"站点数量：{len(app.manager.site_list.sites)}")
    finally:
        root.destroy()
        if temp_dir is not None:
            temp_dir.cleanup()
    return notes


if __name__ == "__main__":
    raise SystemExit(run())
