"""扁平配色主题：浅色 / 深色两套，用纯 ttk 实现，不依赖第三方库。

思路和 ttkbootstrap 一样——统一换掉 ttk 的 clam 主题配色；区别是我们自己
维护色板，省掉一个依赖（这工具要发到单位电脑上，少一个依赖少一分风险）。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

LIGHT = "light"
DARK = "dark"
THEMES = (LIGHT, DARK)
FONT = "Microsoft YaHei UI"

PALETTES: dict[str, dict[str, str]] = {
    LIGHT: {
        "bg": "#eef2f7",
        "card": "#ffffff",
        "fg": "#20262e",
        "muted": "#6b7683",
        "border": "#d7dee7",
        "accent": "#2f6fed",
        "accent_active": "#1f5fd8",
        "accent_fg": "#ffffff",
        "btn_bg": "#dde3ea",
        "btn_active": "#cfd8e3",
        "btn_fg": "#20262e",
        "heading_bg": "#e3e9f1",
        "ok": "#1f9254",
        "warn": "#b7791f",
        "err": "#c0392b",
        "row_ie": "#fdf6e8",
        "row_neutral": "#f4f6f9",
        "row_edge": "#e9f0fe",
        "select_bg": "#2f6fed",
        "select_fg": "#ffffff",
    },
    DARK: {
        "bg": "#161a1f",
        "card": "#1e242c",
        "fg": "#e7ecf3",
        "muted": "#94a3b3",
        "border": "#2c343e",
        "accent": "#3b82f6",
        "accent_active": "#2f6fed",
        "accent_fg": "#ffffff",
        "btn_bg": "#2c343e",
        "btn_active": "#3a444f",
        "btn_fg": "#e7ecf3",
        "heading_bg": "#252d37",
        "ok": "#45c17c",
        "warn": "#e0a33a",
        "err": "#ef6b62",
        "row_ie": "#2a2519",
        "row_neutral": "#222a33",
        "row_edge": "#1b2a42",
        "select_bg": "#2f6fed",
        "select_fg": "#ffffff",
    },
}


def normalize(name: str | None) -> str:
    return DARK if str(name).lower() == DARK else LIGHT


def palette(name: str | None) -> dict[str, str]:
    return PALETTES[normalize(name)]


def row_tag_colors(name: str | None) -> dict[str, str]:
    """Treeview 按打开方式着色用的底色。"""
    pal = palette(name)
    return {
        "ie": pal["row_ie"],
        "neutral": pal["row_neutral"],
        "edge": pal["row_edge"],
    }


def apply(root: tk.Tk, name: str | None) -> dict[str, str]:
    """把整套配色应用到 ttk 样式，返回当前色板。"""
    pal = palette(name)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:  # pragma: no cover - 极端情况下没有 clam
        pass

    root.configure(bg=pal["bg"])
    # ttk.Combobox 的下拉列表是原生 Tk listbox，只能用 option 数据库着色。
    root.option_add("*TCombobox*Listbox.background", pal["card"])
    root.option_add("*TCombobox*Listbox.foreground", pal["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", pal["select_bg"])
    root.option_add("*TCombobox*Listbox.selectForeground", pal["select_fg"])
    root.option_add("*Toplevel.background", pal["bg"])

    style.configure(".", background=pal["bg"], foreground=pal["fg"], font=(FONT, 9))
    style.configure("TFrame", background=pal["bg"])
    style.configure("Card.TFrame", background=pal["card"])
    style.configure("TLabel", background=pal["bg"], foreground=pal["fg"])
    style.configure("Card.TLabel", background=pal["card"], foreground=pal["fg"])
    style.configure("Muted.TLabel", background=pal["bg"], foreground=pal["muted"])
    style.configure("CardMuted.TLabel", background=pal["card"], foreground=pal["muted"])
    style.configure(
        "Heading.TLabel", background=pal["bg"], foreground=pal["fg"], font=(FONT, 10, "bold")
    )
    style.configure(
        "CardHeading.TLabel", background=pal["card"], foreground=pal["fg"], font=(FONT, 10, "bold")
    )
    style.configure("Status.TLabel", background=pal["bg"], foreground=pal["muted"], font=(FONT, 9))
    style.configure("CardStatus.TLabel", background=pal["card"], foreground=pal["muted"], font=(FONT, 9))
    # 顶部状态芯片专用样式（都放在卡片底色的横条上）
    style.configure("Chip.TLabel", background=pal["card"], foreground=pal["fg"], font=(FONT, 9))
    style.configure("ChipOk.TLabel", background=pal["card"], foreground=pal["ok"], font=(FONT, 9))
    style.configure("ChipWarn.TLabel", background=pal["card"], foreground=pal["warn"], font=(FONT, 9))
    style.configure("ChipErr.TLabel", background=pal["card"], foreground=pal["err"], font=(FONT, 9))
    style.configure("Ok.TLabel", background=pal["card"], foreground=pal["ok"])
    style.configure("Warn.TLabel", background=pal["card"], foreground=pal["warn"])
    style.configure("Err.TLabel", background=pal["card"], foreground=pal["err"])

    style.configure(
        "TButton",
        background=pal["btn_bg"],
        foreground=pal["btn_fg"],
        bordercolor=pal["border"],
        lightcolor=pal["btn_bg"],
        darkcolor=pal["btn_bg"],
        borderwidth=1,
        focusthickness=0,
        focuscolor=pal["btn_bg"],
        padding=(11, 6),
    )
    style.map(
        "TButton",
        background=[("disabled", pal["bg"]), ("pressed", pal["btn_active"]), ("active", pal["btn_active"])],
        foreground=[("disabled", pal["muted"])],
    )
    style.configure(
        "Accent.TButton",
        background=pal["accent"],
        foreground=pal["accent_fg"],
        bordercolor=pal["accent"],
        lightcolor=pal["accent"],
        darkcolor=pal["accent"],
        borderwidth=0,
        padding=(15, 7),
        font=(FONT, 9, "bold"),
    )
    style.map(
        "Accent.TButton",
        background=[("disabled", pal["btn_bg"]), ("pressed", pal["accent_active"]), ("active", pal["accent_active"])],
        foreground=[("disabled", pal["muted"])],
    )

    style.configure(
        "TLabelframe",
        background=pal["card"],
        bordercolor=pal["border"],
        lightcolor=pal["card"],
        darkcolor=pal["card"],
        relief="solid",
        borderwidth=1,
    )
    style.configure(
        "TLabelframe.Label",
        background=pal["card"],
        foreground=pal["fg"],
        font=(FONT, 9, "bold"),
    )
    style.configure("TSeparator", background=pal["border"])
    style.configure("TProgressbar", background=pal["accent"], troughcolor=pal["card"])

    style.configure(
        "TEntry",
        fieldbackground=pal["card"],
        foreground=pal["fg"],
        bordercolor=pal["border"],
        lightcolor=pal["border"],
        darkcolor=pal["border"],
        insertcolor=pal["fg"],
        padding=5,
    )
    style.map("TEntry", foreground=[("disabled", pal["muted"])])
    style.configure(
        "TCombobox",
        fieldbackground=pal["card"],
        background=pal["btn_bg"],
        foreground=pal["fg"],
        bordercolor=pal["border"],
        arrowcolor=pal["fg"],
        lightcolor=pal["border"],
        darkcolor=pal["border"],
        padding=4,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", pal["card"]), ("disabled", pal["bg"])],
        foreground=[("readonly", pal["fg"]), ("disabled", pal["muted"])],
        background=[("readonly", pal["btn_bg"])],
        arrowcolor=[("disabled", pal["muted"])],
    )

    for base in ("TCheckbutton", "TRadiobutton"):
        style.configure(
            base,
            background=pal["card"],
            foreground=pal["fg"],
            indicatorcolor=pal["card"],
            focuscolor=pal["card"],
            bordercolor=pal["border"],
        )
        style.map(
            base,
            background=[("active", pal["card"])],
            foreground=[("disabled", pal["muted"])],
            indicatorcolor=[
                ("selected", pal["accent"]),
                ("!selected", pal["card"]),
            ],
        )

    style.configure(
        "Treeview",
        background=pal["card"],
        fieldbackground=pal["card"],
        foreground=pal["fg"],
        bordercolor=pal["border"],
        lightcolor=pal["card"],
        darkcolor=pal["card"],
        rowheight=26,
        borderwidth=0,
    )
    style.map(
        "Treeview",
        background=[("selected", pal["select_bg"])],
        foreground=[("selected", pal["select_fg"])],
    )
    style.configure(
        "Treeview.Heading",
        background=pal["heading_bg"],
        foreground=pal["fg"],
        bordercolor=pal["border"],
        lightcolor=pal["heading_bg"],
        darkcolor=pal["heading_bg"],
        relief="flat",
        padding=(6, 7),
        font=(FONT, 9, "bold"),
    )
    style.map("Treeview.Heading", background=[("active", pal["btn_active"])])

    style.configure(
        "Vertical.TScrollbar",
        background=pal["btn_bg"],
        troughcolor=pal["bg"],
        bordercolor=pal["bg"],
        arrowcolor=pal["fg"],
        lightcolor=pal["btn_bg"],
        darkcolor=pal["btn_bg"],
    )
    style.map("Vertical.TScrollbar", background=[("active", pal["btn_active"])])
    style.configure(
        "Horizontal.TScrollbar",
        background=pal["btn_bg"],
        troughcolor=pal["bg"],
        bordercolor=pal["bg"],
        arrowcolor=pal["fg"],
    )
    return pal


def style_text_widget(widget: tk.Text, pal: dict[str, str]) -> None:
    """给原生 tk.Text 上色（ttk 管不到它）。"""
    widget.configure(
        background=pal["card"],
        foreground=pal["fg"],
        insertbackground=pal["fg"],
        selectbackground=pal["select_bg"],
        selectforeground=pal["select_fg"],
        highlightthickness=1,
        highlightbackground=pal["border"],
        highlightcolor=pal["accent"],
        relief="flat",
        borderwidth=0,
    )


def style_list_widget(widget: tk.Listbox, pal: dict[str, str]) -> None:
    widget.configure(
        background=pal["card"],
        foreground=pal["fg"],
        selectbackground=pal["select_bg"],
        selectforeground=pal["select_fg"],
        highlightthickness=1,
        highlightbackground=pal["border"],
        highlightcolor=pal["accent"],
        relief="flat",
        borderwidth=0,
    )
