"""本地"假更新源"，用来在不碰 GitHub 的情况下测试自动更新。

它只做两件事：
  * 提供 /version.json（版本号比当前程序高，指向本地安装包）
  * 提供 /EdgeIEManager.exe（按设定限速，方便观察进度条和测试取消）

用法（两个窗口）：

    窗口 1：
        py -3 tools/local_update_server.py --exe dist\\EdgeIEManager.exe --version 9.9.9 --kbps 800

    窗口 2：
        $env:EDGEIE_UPDATE_BASE_URL = "http://127.0.0.1:8765"
        .\\dist\\EdgeIEManager.exe

然后在程序里点"关于 → 检查更新"，会看到本地这个假版本的更新。
测完关掉窗口 2 的程序和窗口 1 的服务器，删掉环境变量即可。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ASSET_NAME = "EdgeIEManager.exe"
MANIFEST_NAME = "version.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _log(message: str) -> None:
    stamp = _dt.datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


def build_handler(options: "Options"):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定
            path = self.path.split("?", 1)[0]
            if path in (f"/{MANIFEST_NAME}", "/version.json"):
                self._serve_manifest()
            elif path == f"/{ASSET_NAME}":
                self._serve_asset()
            else:
                _log(f"404 {self.path}")
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

        def _serve_manifest(self) -> None:
            manifest = {
                "version": options.version,
                "notes": options.notes,
                "download": f"http://{options.host}:{options.port}/{ASSET_NAME}",
                "sha256": options.sha256,
                "size": options.size,
            }
            body = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
            _log(f"200 {MANIFEST_NAME} (version={options.version})")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _serve_asset(self) -> None:
            if options.connect_delay > 0:
                _log(f"模拟连接卡住 {options.connect_delay:.1f}s（用于复现“准备下载”不动的现象）")
                time.sleep(options.connect_delay)
            _log(
                f"200 {ASSET_NAME} ({options.size / 1024 / 1024:.1f} MB"
                f"{f', {options.kbps} KB/s' if options.kbps else ', 不限速'})"
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(options.size))
            self.end_headers()
            sent = 0
            started = time.monotonic()
            chunk = max(1024, options.chunk)
            with options.exe.open("rb") as handle:
                while True:
                    block = handle.read(chunk)
                    if not block:
                        break
                    try:
                        self.wfile.write(block)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        _log("客户端断开了连接（取消下载的预期表现）")
                        return
                    sent += len(block)
                    if options.kbps > 0:
                        expected = sent / (options.kbps * 1024)
                        delay = expected - (time.monotonic() - started)
                        if delay > 0:
                            time.sleep(delay)
            _log(f"传输完成 {sent} 字节")

        def log_message(self, *args) -> None:  # 关掉默认的逐行输出
            pass

    return Handler


class Options:
    def __init__(self, args: argparse.Namespace) -> None:
        self.host = args.host
        self.port = args.port
        self.version = args.version
        self.notes = args.notes
        self.kbps = args.kbps
        self.chunk = args.chunk
        self.connect_delay = args.connect_delay
        self.exe: Path = args.exe.resolve()
        self.size = self.exe.stat().st_size
        self.sha256 = sha256_file(self.exe)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="本地更新测试服务器（仅供开发测试）")
    parser.add_argument("--exe", required=True, type=Path, help="要作为“新版本”提供的 exe")
    parser.add_argument("--version", default="9.9.9", help="假版本号，默认 9.9.9")
    parser.add_argument(
        "--notes", default="本地测试版本（不会真的发布）。", help="更新说明文本"
    )
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8765, help="监听端口")
    parser.add_argument(
        "--kbps", type=int, default=0, help="限速（KB/s），0 表示不限速；限速便于测试取消"
    )
    parser.add_argument("--chunk", type=int, default=64 * 1024, help="每次发送的字节数")
    parser.add_argument(
        "--connect-delay",
        type=float,
        default=0.0,
        help="收到安装包请求后先等待多少秒再响应，用来模拟连接卡住",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    options = Options(parse_args(argv))
    if not options.exe.is_file():
        print(f"找不到文件：{options.exe}", file=sys.stderr)
        return 1

    server = ThreadingHTTPServer((options.host, options.port), build_handler(options))
    print("本地更新源已启动")
    print(f"  清单：http://{options.host}:{options.port}/{MANIFEST_NAME}")
    print(f"  安装包：http://{options.host}:{options.port}/{ASSET_NAME}")
    print(f"  版本：{options.version}  大小：{options.size / 1024 / 1024:.1f} MB")
    print(f"  sha256：{options.sha256[:16]}…")
    print()
    print("在另一个窗口设置环境变量后再启动要测试的程序：")
    print(f'  $env:EDGEIE_UPDATE_BASE_URL = "http://{options.host}:{options.port}"')
    print("  .\\dist\\EdgeIEManager.exe")
    print()
    print("按 Ctrl+C 停止。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
