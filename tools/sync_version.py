"""把版本号同步到各个副本文件，避免手工维护多处导致版本漂移。

版本号的唯一来源是 ``edge_ie_manager/version.py``。其它地方需要版本号时都由
这个脚本生成，不要再手改：

* packaging/version_main.txt   —— 主程序 exe 的版本资源
* packaging/version_cli.txt    —— 命令行版 exe 的版本资源
* packaging/version_clean.txt  —— 便携版 exe 的版本资源
* version.json                 —— 更新检查用的清单（version / notes / download / sha256 / size）

用法::

    py -3 tools/sync_version.py
        # 只同步版本号；sha256 和 size 置空（构建前跑这个）

    py -3 tools/sync_version.py --artifact dist/EdgeIEManager.exe
        # 同步版本号并写入安装包的 sha256 和大小（构建后、打包 Release 前跑这个）

脚本打印实际改动的文件，没有改动时保持安静，方便在构建脚本里反复调用。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "edge_ie_manager" / "version.py"
MANIFEST_FILE = ROOT / "version.json"

# 作者信息，写进 Windows 文件属性，改动需谨慎。
AUTHOR = "payne"
CONTACT = "947919822"

_VERSION_RE = re.compile(r'__version__\s*=\s*["\']([^"\']+)["\']')

# 每份版本资源对应一个可执行文件。
EXECUTABLES = (
    {
        "resource": ROOT / "packaging" / "version_main.txt",
        "filename": "EdgeIEManager.exe",
        "internal": "EdgeIEManager",
        "description": "Edge IE 模式站点管理器",
    },
    {
        "resource": ROOT / "packaging" / "version_cli.txt",
        "filename": "EdgeIEManager-CLI.exe",
        "internal": "EdgeIEManager-CLI",
        "description": "Edge IE 模式站点管理器 命令行工具",
    },
    {
        "resource": ROOT / "packaging" / "version_clean.txt",
        "filename": "EdgeIEManager-Clean.exe",
        "internal": "EdgeIEManager-Clean",
        "description": "Edge IE 模式站点管理器（干净版）",
    },
)

_RESOURCE_TEMPLATE = """# -*- coding: utf-8 -*-
# Version resource for {filename}
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({tuple4}),
    prodvers=({tuple4}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
    ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        '080404B0',
        [StringStruct('CompanyName', '{author}'),
        StringStruct('FileDescription', '{description}'),
        StringStruct('FileVersion', '{dotted}'),
        StringStruct('InternalName', '{internal}'),
        StringStruct('LegalCopyright', 'Copyright (C) {year} {author}'),
        StringStruct('OriginalFilename', '{filename}'),
        StringStruct('ProductName', 'Edge IE 模式站点管理器'),
        StringStruct('ProductVersion', '{dotted}'),
        StringStruct('Comments', '作者：{author}，联系方式：{contact}'),
        StringStruct('Author', '{author}'),
        StringStruct('Contact', '{contact}')])
      ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""


def read_version(version_file: Path = VERSION_FILE) -> str:
    """从 version.py 读出 ``__version__``，这是全项目唯一的版本来源。"""
    match = _VERSION_RE.search(version_file.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"在 {version_file} 里找不到 __version__。")
    return match.group(1).strip()


def version_tuple4(version: str) -> str:
    """把 1.0.7 这类版本号补成 Windows 资源要求的 4 段：1, 0, 7, 0。"""
    return ", ".join(str(part) for part in _version_parts(version))


def version_dotted4(version: str) -> str:
    """Windows 资源里的字符串版本号格式：1.0.7.0。"""
    return ".".join(str(part) for part in _version_parts(version))


def _version_parts(version: str) -> list[int]:
    parts: list[int] = []
    for chunk in str(version).strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 4:
        parts.append(0)
    return parts[:4]


def render_resource(entry: dict, version: str) -> str:
    return _RESOURCE_TEMPLATE.format(
        filename=entry["filename"],
        internal=entry["internal"],
        description=entry["description"],
        tuple4=version_tuple4(version),
        dotted=version_dotted4(version),
        author=AUTHOR,
        contact=CONTACT,
        year=date.today().year,
    )


def _write_if_changed(path: Path, text: str, changed: list[str], root: Path = ROOT) -> None:
    # 统一用 LF：仓库里的这些文件本来就是 LF，Windows 文本模式默认会写成
    # CRLF，导致每次同步都会让 git 以为文件被改动。这里按“实际字节”比较，
    # 只有真的不一样才重写，反复运行不会产生多余改动。
    payload = text.encode("utf-8")
    try:
        current = path.read_bytes()
    except OSError:
        current = None
    if current == payload:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    try:
        changed.append(str(path.relative_to(root)))
    except ValueError:
        changed.append(str(path))


def sync_resources(version: str | None = None, root: Path = ROOT) -> list[str]:
    """重写三份版本资源文件，返回改动过的文件（相对 root）。"""
    version = version or read_version(root / "edge_ie_manager" / "version.py")
    changed: list[str] = []
    for entry in EXECUTABLES:
        rel = entry["resource"].relative_to(ROOT)
        target = root / rel
        _write_if_changed(target, render_resource(entry, version), changed, root)
    return changed


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sync_manifest(
    version: str | None = None,
    artifact: Path | None = None,
    root: Path = ROOT,
) -> list[str]:
    """更新 version.json 的版本号；给了安装包就同时写入 sha256 和大小。"""
    version = version or read_version(root / "edge_ie_manager" / "version.py")
    manifest_path = root / "version.json"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}

    manifest = {
        "version": version,
        "notes": "",
        "download": (
            "https://github.com/paynehe3023/EdgeIEManager/releases/latest/download/EdgeIEManager.exe"
        ),
        "sha256": "",
        "size": 0,
    }
    # 保留人工维护的字段（更新说明、下载地址等），只覆盖版本号与校验信息。
    for key in ("notes", "download"):
        value = data.get(key)
        if value:
            manifest[key] = value
    for key, value in data.items():
        manifest.setdefault(key, value)

    if artifact is not None:
        artifact = Path(artifact)
        if not artifact.exists():
            raise SystemExit(f"找不到安装包：{artifact}")
        manifest["sha256"] = _sha256(artifact)
        manifest["size"] = artifact.stat().st_size
    else:
        manifest["sha256"] = ""
        manifest["size"] = 0

    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    changed: list[str] = []
    _write_if_changed(manifest_path, text, changed, root)
    return changed


def sync(
    version: str | None = None,
    artifact: Path | None = None,
    root: Path = ROOT,
) -> list[str]:
    changed = sync_resources(version, root)
    changed += sync_manifest(version, artifact, root)
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="同步版本号到各个副本文件")
    parser.add_argument(
        "--artifact",
        type=Path,
        default=None,
        help="构建好的 EdgeIEManager.exe，用于写入 sha256 和大小",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="没有任何改动时不打印提示",
    )
    args = parser.parse_args(argv)

    version = read_version()
    changed = sync(version, args.artifact)
    if changed:
        print(f"版本号已同步为 v{version}：")
        for name in changed:
            print(f"  - {name}")
    elif not args.quiet:
        print(f"版本号已经是 v{version}，无需改动。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
