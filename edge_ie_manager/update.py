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
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .version import __version__
from .runtime_env import clean_environment

# 发行仓库，格式 owner/repo。留空时界面会提示“未配置更新源”。
DEFAULT_REPO = "paynehe3023/EdgeIEManager"

# version.json 所在分支，按顺序尝试
MANIFEST_BRANCHES = ("main", "master")
MANIFEST_NAME = "version.json"

# 仅用于开发/测试：把更新源临时指向本机或测试服务器。
# 例如：set EDGEIE_UPDATE_BASE_URL=http://127.0.0.1:8765
# 生产环境不要设置这些变量，留空时一律走上面的正式 GitHub 地址。
BASE_URL_ENV = "EDGEIE_UPDATE_BASE_URL"
MANIFEST_URL_ENV = "EDGEIE_UPDATE_MANIFEST_URL"

# Release 里必须用这个名字上传主程序，更新器只认它
ASSET_NAME = "EdgeIEManager.exe"
CHECKSUM_ASSET = ASSET_NAME + ".sha256"
OLD_SUFFIX = ".old"

USER_AGENT = "EdgeIEManager-Updater"
CHECK_TIMEOUT = 12
# 这个超时是“单次网络读写的等待时间”，不是整次下载的总时长。
# 网速慢但一直在传的下载不会被它打断，只有连接/读取卡住才会触发。
DOWNLOAD_TIMEOUT = 30
CHUNK = 64 * 1024

RAW_URL = "https://raw.githubusercontent.com/{repo}/{branch}/{name}"
API_LATEST = "https://api.github.com/repos/{repo}/releases/latest"
STABLE_ASSET_URL = "https://github.com/{repo}/releases/latest/download/{name}"
RELEASES_PAGE = "https://github.com/{repo}/releases"


class UpdateError(RuntimeError):
    """检查或安装更新过程中的可展示错误。"""


class UpdateCancelled(UpdateError):
    """用户主动取消了下载，界面按“提示”而不是“报错”处理。"""


class CancelToken:
    """下载取消开关。

    取消时除了标记状态，还会直接关掉底层响应对象，让阻塞在网络读取上的
    下载线程立刻返回，而不是等超时（否则点了取消要几秒到几十秒才有反应）。
    """

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._response = None

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()
        with self._lock:
            response = self._response
        if response is not None:
            try:
                response.close()
            except Exception:  # pragma: no cover - 关闭失败不影响取消语义
                pass

    def bind(self, response) -> bool:
        """绑定当前响应对象；若此前已经取消过则返回 True。"""
        with self._lock:
            self._response = response
            return self._event.is_set()


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


def _test_base_url() -> str:
    """测试用更新源根地址；没有设置时返回空串。"""
    return os.environ.get(BASE_URL_ENV, "").strip().rstrip("/")


def _manifest_urls(repo: str) -> list[str]:
    """按顺序给出 version.json 的候选地址。"""
    base = _test_base_url()
    if base:
        return [f"{base}/{MANIFEST_NAME}"]
    override = os.environ.get(MANIFEST_URL_ENV, "").strip()
    if override:
        return [override]
    return [
        RAW_URL.format(repo=repo, branch=branch, name=MANIFEST_NAME)
        for branch in MANIFEST_BRANCHES
    ]


def _load_manifest(repo: str) -> dict | None:
    """读 version.json；两个分支都 404 时返回 None。"""
    for url in _manifest_urls(repo):
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
        download = str(manifest.get("download") or "").strip()
        if not download:
            base = _test_base_url()
            download = (
                f"{base}/{ASSET_NAME}"
                if base
                else STABLE_ASSET_URL.format(repo=repo, name=ASSET_NAME)
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


def download(
    info: UpdateInfo,
    dest: str | Path,
    progress=None,
    token: CancelToken | None = None,
) -> Path:
    """下载安装包到 dest。

    progress(已下载, 总量)：总量未知时传 -1，界面据此切成不确定进度动画。
    下载一开始就会回调一次 progress(0, -1)，让界面立刻进入“正在连接”状态，
    而不是一直停在“准备下载”不动（GitHub 下载会先重定向，连接阶段可能很久）。
    token 传入 CancelToken 时支持中途取消。
    """
    target = Path(dest)
    target.parent.mkdir(parents=True, exist_ok=True)
    cancel = token if token is not None else CancelToken()
    if progress is not None:
        progress(0, -1)

    def _discard() -> None:
        try:
            target.unlink()
        except OSError:
            pass

    request = urllib.request.Request(
        info.download_url, headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
            if cancel.bind(response):
                raise UpdateCancelled("已取消下载。")
            total = int(response.headers.get("Content-Length") or info.size or 0)
            done = 0
            with open(target, "wb") as handle:
                while True:
                    if cancel.cancelled:
                        raise UpdateCancelled("已取消下载。")
                    block = response.read(CHUNK)
                    if not block:
                        break
                    handle.write(block)
                    done += len(block)
                    if progress is not None:
                        progress(done, total)
    except UpdateCancelled:
        _discard()
        raise
    except urllib.error.HTTPError as exc:
        _discard()
        raise UpdateError(
            f"下载失败（HTTP {exc.code}）。请确认 Release 里已经上传 {ASSET_NAME}。"
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        _discard()
        raise UpdateError(
            "下载超时：连不上 GitHub 的下载服务器（常见于网络被拦截或太慢）。\n"
            "可以稍后重试，或点“打开发布页”手动下载。"
        ) from exc
    except urllib.error.URLError as exc:
        _discard()
        if cancel.cancelled:
            raise UpdateCancelled("已取消下载。") from exc
        raise UpdateError(f"下载失败：{exc.reason}") from exc
    except OSError as exc:
        _discard()
        if cancel.cancelled:
            raise UpdateCancelled("已取消下载。") from exc
        raise UpdateError(f"写入文件失败：{exc}") from exc

    if info.sha256:
        actual = sha256_file(target)
        if actual != info.sha256:
            _discard()
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
    # 必须换掉环境：直接继承会把 _PYI_* 引导变量带过去，新进程会把自己当成
    # 老进程的子进程，跳过解包后卡在父进程校验上（见 runtime_env 模块注释）。
    subprocess.Popen(
        [str(target)],
        cwd=str(target.parent),
        close_fds=True,
        env=clean_environment(),
    )


def open_releases_page(repo: str) -> None:
    url = RELEASES_PAGE.format(repo=(repo or "").strip().strip("/"))
    try:
        os.startfile(url)  # type: ignore[attr-defined]
    except OSError:
        pass
