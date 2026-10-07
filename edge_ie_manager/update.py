"""从 GitHub 检查并安装新版本。

设计取舍：
* 版本号优先读仓库里的 version.json（raw.githubusercontent.com，CDN，没有接口限流）。
  单位里几十台电脑共用一个出口 IP，走 GitHub API 很容易撞上 60 次/小时的限制。
* 下载走 releases/latest/download/<固定文件名> 这个稳定地址，永远指向最新一版。
* 读不到 version.json 时才退回 GitHub Releases API。

替换正在运行的程序用的是“改名”而不是“删除”：Windows 允许给正在运行的 exe
改名，但不允许直接覆盖，所以先把旧文件改成 .old，再把新文件放到原位置。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .version import __version__

# 发行仓库，格式 owner/repo。留空时界面会提示“未配置更新源”。
DEFAULT_REPO = "paynehe3023/EdgeIEManager"

# version.json 所在分支，按顺序尝试
MANIFEST_BRANCHES = ("main", "master")
MANIFEST_NAME = "version.json"

# Release 里必须用这个名字上传主程序，更新器只认它
ASSET_NAME = "EdgeIEManager.exe"
CHECKSUM_ASSET = ASSET_NAME + ".sha256"
OLD_SUFFIX = ".old"

USER_AGENT = "EdgeIEManager-Updater"
CHECK_TIMEOUT = 12
DOWNLOAD_TIMEOUT = 180
CHUNK = 64 * 1024

RAW_URL = "https://raw.githubusercontent.com/{repo}/{branch}/{name}"
API_LATEST = "https://api.github.com/repos/{repo}/releases/latest"
STABLE_ASSET_URL = "https://github.com/{repo}/releases/latest/download/{name}"
RELEASES_PAGE = "https://github.com/{repo}/releases"


class UpdateError(RuntimeError):
    """检查或安装更新过程中的可展示错误。"""


@dataclass
class UpdateInfo:
    version: str
    download_url: str
    sha256: str = ""
    notes: str = ""
    size: int = 0
    page_url: str = ""

    @property
    def display(self) -> str:
        text = str(self.version).strip()
        return text if text.lower().startswith("v") else f"v{text}"


def parse_version(text: str) -> tuple[int, ...]:
    """把 v1.2.3 / 1.2 / 1.2.0-beta.1 解析成可比较的元组。

    遇到第一段带后缀的部分就停止，预发布信息（-beta、+build）不参与比较，
    否则 1.2.0-beta.1 会被当成 1.2.0.1，比正式版 1.2.0 还“新”。
    """
    cleaned = str(text or "").strip().lstrip("vV")
    parts: list[int] = []
    for chunk in cleaned.split("."):
        digits = ""
        for char in chunk:
            if char.isdigit():
                digits += char
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
        if len(digits) != len(chunk):
            break
    return tuple(parts) or (0,)


def is_newer(candidate: str, current: str = __version__) -> bool:
    left, right = parse_version(candidate), parse_version(current)
    width = max(len(left), len(right))
    left += (0,) * (width - len(left))
    right += (0,) * (width - len(right))
    return left > right


def _fetch(url: str, timeout: int = CHECK_TIMEOUT) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _load_manifest(repo: str) -> dict | None:
    """读 version.json；两个分支都 404 时返回 None。"""
    for branch in MANIFEST_BRANCHES:
        url = RAW_URL.format(repo=repo, branch=branch, name=MANIFEST_NAME)
        try:
            return json.loads(_fetch(url).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue
            if exc.code == 403:
                raise UpdateError("GitHub 暂时限流了，请稍后再试，或直接打开下载页。") from exc
            raise UpdateError(f"读取版本信息失败（HTTP {exc.code}）。") from exc
        except urllib.error.URLError as exc:
            raise UpdateError(f"连不上 GitHub：{exc.reason}") from exc
        except (ValueError, UnicodeDecodeError) as exc:
            raise UpdateError("version.json 内容不是合法的 JSON。") from exc
    return None


def _load_release(repo: str) -> dict:
    """退回 GitHub Releases API。"""
    try:
        return json.loads(_fetch(API_LATEST.format(repo=repo)).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("仓库或 Release 不存在，请检查更新源配置。") from exc
        if exc.code == 403:
            raise UpdateError("GitHub 接口暂时限流，请稍后再试，或直接打开下载页。") from exc
        raise UpdateError(f"查询 Release 失败（HTTP {exc.code}）。") from exc
    except urllib.error.URLError as exc:
        raise UpdateError(f"连不上 GitHub：{exc.reason}") from exc
    except (ValueError, UnicodeDecodeError) as exc:
        raise UpdateError("Release 信息解析失败。") from exc


def check_for_update(repo: str, current: str = __version__) -> UpdateInfo | None:
    """有新版本返回 UpdateInfo，已是最新返回 None，出错抛 UpdateError。"""
    repo = (repo or "").strip().strip("/")
    if not repo:
        raise UpdateError("还没有配置更新源（GitHub 仓库）。")

    manifest = _load_manifest(repo)
    if manifest is not None:
        latest = str(manifest.get("version") or "").strip()
        if not latest:
            raise UpdateError("version.json 里缺少 version 字段。")
        if not is_newer(latest, current):
            return None
        download = str(manifest.get("download") or "").strip() or STABLE_ASSET_URL.format(
            repo=repo, name=ASSET_NAME
        )
        return UpdateInfo(
            version=latest,
            download_url=download,
            sha256=str(manifest.get("sha256") or "").strip().lower(),
            notes=str(manifest.get("notes") or "").strip(),
            size=int(manifest.get("size") or 0),
            page_url=RELEASES_PAGE.format(repo=repo),
        )

    release = _load_release(repo)
    tag = str(release.get("tag_name") or "").strip()
    if not tag:
        raise UpdateError("Release 里没有版本号。")
    if not is_newer(tag, current):
        return None

    asset = None
    checksum_asset = None
    for item in release.get("assets") or []:
        name = str(item.get("name") or "")
        if name == ASSET_NAME:
            asset = item
        elif name == CHECKSUM_ASSET:
            checksum_asset = item
    if asset is None:
        raise UpdateError(
            f"这一版没有附带 {ASSET_NAME}，请到下载页手动获取。"
        )

    sha256 = ""
    if checksum_asset is not None:
        try:
            text = _fetch(str(checksum_asset.get("browser_download_url") or "")).decode(
                "utf-8", "replace"
            )
            sha256 = text.strip().split()[0].lower() if text.strip() else ""
        except (urllib.error.URLError, urllib.error.HTTPError, IndexError):
            sha256 = ""

    return UpdateInfo(
        version=tag,
        download_url=str(asset.get("browser_download_url") or ""),
        sha256=sha256,
        notes=str(release.get("body") or "").strip(),
        size=int(asset.get("size") or 0),
        page_url=str(release.get("html_url") or RELEASES_PAGE.format(repo=repo)),
    )


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def download(info: UpdateInfo, dest: str | Path, progress=None) -> Path:
    """下载安装包到 dest。progress(已下载, 总量) 可用于显示进度。"""
    target = Path(dest)
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        info.download_url, headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
            total = int(response.headers.get("Content-Length") or info.size or 0)
            done = 0
            with open(target, "wb") as handle:
                while True:
                    block = response.read(CHUNK)
                    if not block:
                        break
                    handle.write(block)
                    done += len(block)
                    if progress is not None:
                        progress(done, total)
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"下载失败（HTTP {exc.code}）。") from exc
    except urllib.error.URLError as exc:
        raise UpdateError(f"下载失败：{exc.reason}") from exc
    except OSError as exc:
        raise UpdateError(f"写入文件失败：{exc}") from exc

    if info.sha256:
        actual = sha256_file(target)
        if actual != info.sha256:
            try:
                target.unlink()
            except OSError:
                pass
            raise UpdateError(
                "校验失败，下载的文件不完整，已丢弃。\n"
                f"期望 {info.sha256[:16]}… 实际 {actual[:16]}…"
            )
    return target


def current_exe() -> Path | None:
    """打包运行时返回自身 exe；源码运行时返回 None（不支持自更新）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return None


def can_self_update() -> bool:
    exe = current_exe()
    return exe is not None and exe.name.lower() == ASSET_NAME.lower()


def apply_update(new_exe: str | Path, target_exe: str | Path) -> None:
    """把新版本换到 target_exe 的位置。旧文件改成 .old，下次启动时清理。"""
    new_path = Path(new_exe)
    target = Path(target_exe)
    backup = target.with_name(target.name + OLD_SUFFIX)
    try:
        if backup.exists():
            backup.unlink()
    except OSError:
        pass
    try:
        os.replace(target, backup)
    except OSError as exc:
        raise UpdateError(
            f"无法替换程序文件：{exc}\n如果程序装在系统目录里，请手动下载新版本。"
        ) from exc
    try:
        shutil.move(str(new_path), str(target))
    except OSError as exc:
        # 尽量回滚，避免用户手里没有可运行的程序
        try:
            os.replace(backup, target)
        except OSError:
            pass
        raise UpdateError(f"新版本写入失败：{exc}") from exc


def cleanup_old_files(directory: str | Path) -> None:
    """删除上次更新留下的 .old 文件，失败就算了（可能还被旧进程占着）。"""
    try:
        candidates = list(Path(directory).glob(f"*{OLD_SUFFIX}"))
    except OSError:
        return
    for item in candidates:
        try:
            item.unlink()
        except OSError:
            pass


def restart(exe: str | Path) -> None:
    target = Path(exe)
    subprocess.Popen([str(target)], cwd=str(target.parent), close_fds=True)


def open_releases_page(repo: str) -> None:
    url = RELEASES_PAGE.format(repo=(repo or "").strip().strip("/"))
    try:
        os.startfile(url)  # type: ignore[attr-defined]
    except OSError:
        pass
