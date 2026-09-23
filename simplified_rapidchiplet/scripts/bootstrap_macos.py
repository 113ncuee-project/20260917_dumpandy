#!/usr/bin/env python3
"""Prepare the pinned RapidChiplet core and start the local GUI on macOS."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse


PROJECT_DIR = Path(__file__).resolve().parents[1]
RUNTIME_DIR = PROJECT_DIR / ".runtime"
LOCK_FILE = PROJECT_DIR / "packaging" / "runtime-lock.json"
ALLOWED_HOSTS = {"raw.githubusercontent.com"}
MAX_ASSET_BYTES = 16 * 1024 * 1024
SYSTEM_CURL = Path("/usr/bin/curl")
CURL_BIN = str(SYSTEM_CURL) if SYSTEM_CURL.is_file() else shutil.which("curl")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_verified(url: str, target: Path, expected_sha256: str, offline: bool) -> None:
    if target.is_file() and sha256_file(target) == expected_sha256:
        return
    if offline:
        raise RuntimeError(f"離線模式下找不到有效的官方核心檔案：{target.name}")

    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise RuntimeError(f"拒絕未核准的下載來源：{url}")
    if CURL_BIN is None:
        raise RuntimeError("找不到 macOS curl，請確認系統的 /usr/bin/curl 可用。")

    last_error: Exception | None = None
    for attempt in range(1, 4):
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=f".{target.name}.", suffix=".partial",
                dir=target.parent, delete=False,
            ) as stream:
                temp_path = Path(stream.name)

            result = subprocess.run(
                [
                    CURL_BIN,
                    "--silent", "--show-error", "--fail", "--location",
                    "--max-redirs", "5", "--proto", "=https", "--proto-redir", "=https",
                    "--connect-timeout", "20", "--max-time", "180",
                    "--max-filesize", str(MAX_ASSET_BYTES),
                    "--output", str(temp_path), "--write-out", "%{url_effective}", url,
                ],
                capture_output=True,
                text=True,
                timeout=190,
                check=False,
            )
            if result.returncode != 0:
                details = result.stderr.strip() or f"curl 結束代碼 {result.returncode}"
                raise OSError(details)

            final_url = urlparse(result.stdout.strip())
            if final_url.scheme != "https" or final_url.hostname not in ALLOWED_HOSTS:
                raise RuntimeError(f"下載重新導向到未核准的來源：{result.stdout.strip()}")
            if temp_path.stat().st_size > MAX_ASSET_BYTES:
                raise RuntimeError(f"下載檔案超過大小上限：{target.name}")
            if sha256_file(temp_path) != expected_sha256:
                raise RuntimeError(f"SHA-256 不符：{target.name}；不會執行此下載檔案。")
            temp_path.replace(target)
            print(f"已準備 {target.name}")
            return
        except RuntimeError:
            raise
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                print(f"下載 {target.name} 失敗，正在重試（{attempt}/3）……")
                time.sleep(attempt)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    raise RuntimeError(
        f"無法下載 {target.name}：{last_error}\n"
        "請確認網路可連線至 raw.githubusercontent.com，然後重新啟動。"
    )


def prepare_runtime(offline: bool) -> None:
    lock = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    core_dir = RUNTIME_DIR / "rapidchiplet"
    core_dir.mkdir(parents=True, exist_ok=True)

    lock_path = RUNTIME_DIR / "setup_macos.lock"
    with lock_path.open("a+b") as setup_lock:
        try:
            fcntl.flock(setup_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("另一個啟動器正在準備環境，請稍候再試。") from exc

        for asset in lock["rapidchiplet"]["files"]:
            print(f"檢查 {asset['name']}……")
            download_verified(asset["url"], core_dir / asset["name"], asset["sha256"], offline)

    print(
        "官方 RapidChiplet 核心已就緒 "
        f"（{lock['rapidchiplet']['commit'][:12]}）。"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=PROJECT_DIR)
    parser.add_argument("--port", type=int, default=0, help="本機 GUI 連接埠；0 代表自動選擇")
    parser.add_argument("--no-browser", action="store_true", help="啟動伺服器但不自動開啟瀏覽器")
    parser.add_argument("--offline", action="store_true", help="只使用已下載且雜湊正確的核心檔案")
    parser.add_argument("--setup-only", action="store_true", help="只準備執行環境，不啟動 GUI")
    args = parser.parse_args()

    if sys.platform != "darwin":
        parser.error("此啟動器僅供 macOS 使用。")
    if platform.machine() not in {"arm64", "x86_64"}:
        parser.error(f"不支援的 Mac 處理器架構：{platform.machine()}")
    if sys.version_info < (3, 10):
        parser.error("需要 Python 3.10 或更新版本。")
    if not 0 <= args.port <= 65535:
        parser.error("--port 必須介於 0 至 65535。")

    project_dir = args.project.resolve()
    if project_dir != PROJECT_DIR:
        parser.error("--project 必須指向此啟動器所在的簡化專案資料夾。")

    try:
        prepare_runtime(args.offline)
        if args.setup_only:
            print(f"環境準備完成：Python {platform.python_version()}。")
            return 0

        command = [
            sys.executable, "-X", "utf8", str(project_dir / "gui.py"),
            "--port", str(args.port),
        ]
        if args.no_browser:
            command.append("--no-browser")
        return subprocess.run(command, cwd=project_dir, check=False).returncode
    except KeyboardInterrupt:
        print("\nChiplet Lab 已停止。")
        return 130
    except Exception as exc:
        print(f"\nChiplet Lab 無法啟動：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
