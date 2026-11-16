"""
Run tests/dashboard.html in headless Chrome/Chromium and verify all assertions pass.
"""
from __future__ import annotations

import functools
import http.server
import json
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def find_browser() -> str:
    candidates = [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for candidate in candidates:
        path = shutil.which(candidate) or (candidate if Path(candidate).is_file() else None)
        if path:
            return path
    raise RuntimeError("Headless browser (Chrome / Chromium) not found.")


def main() -> int:
    done = threading.Event()
    payload: dict | None = None

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_POST(self) -> None:
            nonlocal payload
            if self.path != "/__report__":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            self.send_response(204)
            self.end_headers()
            done.set()

        def log_message(self, format: str, *args: object) -> None:
            pass

    handler = functools.partial(Handler, directory=str(ROOT_DIR))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    browser = find_browser()
    profile_dir = tempfile.mkdtemp(prefix="ttm-browser-test-")
    proc = subprocess.Popen(
        [
            browser,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            f"--user-data-dir={profile_dir}",
            f"http://127.0.0.1:{port}/tests/dashboard.html",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        if not done.wait(timeout=20) or payload is None:
            print("❌ Browser tests timed out before reporting results.", file=sys.stderr)
            return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        server.shutdown()
        shutil.rmtree(profile_dir, ignore_errors=True)

    for item in payload.get("results", []):
        mark = "PASS" if item.get("passed") else "FAIL"
        detail = f" ({item['error']})" if item.get("error") else ""
        print(f"[{mark}] {item.get('name')}{detail}")

    if payload.get("error"):
        print(payload["error"], file=sys.stderr)
        return 1

    passed = int(payload.get("passed", 0))
    failed = int(payload.get("failed", 1))
    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 and passed > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
