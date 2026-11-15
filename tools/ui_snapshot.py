"""Start the app on a free local port and screenshot pages at phone and desktop widths.

usage: uv run python tools/ui_snapshot.py <out_dir>

Pages come from tools/ui_pages.txt, one path per line. Lines starting with "#" are skipped.
Each page is captured at 360, 390 and 1280 px wide, in light and dark color schemes.
Writes report.txt with HTTP status, horizontal overflow and console errors per capture.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
WIDTHS = (360, 390, 1280)
SCHEMES = ("light", "dark")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_up(base: str, proc: subprocess.Popen, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"app exited with code {proc.returncode}")
        try:
            httpx.get(base + "/", timeout=2)
            return
        except httpx.HTTPError:
            time.sleep(0.5)
    raise SystemExit("app did not start within 60 s")


def main() -> int:
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    pages_file = ROOT / "tools" / "ui_pages.txt"
    if not pages_file.exists():
        print("no tools/ui_pages.txt; nothing to capture")
        return 0
    pages = [
        p.strip()
        for p in pages_file.read_text().splitlines()
        if p.strip() and not p.startswith("#")
    ]
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = {**os.environ, "DB_PATH": str(out / "snapshot.db"), "LLM_ENABLED": "0"}
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=(out / "server.log").open("w"),
        stderr=subprocess.STDOUT,
    )
    lines = []
    try:
        wait_up(base, proc)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for path in pages:
                for width in WIDTHS:
                    for scheme in SCHEMES:
                        ctx = browser.new_context(
                            viewport={"width": width, "height": 900}, color_scheme=scheme
                        )
                        page = ctx.new_page()
                        errors: list[str] = []
                        page.on(
                            "console",
                            lambda m, e=errors: e.append(m.text) if m.type == "error" else None,
                        )
                        resp = page.goto(base + path, wait_until="networkidle")
                        overflow = page.evaluate(
                            "document.documentElement.scrollWidth > window.innerWidth"
                        )
                        name = (path.strip("/").replace("/", "_") or "home") + f"_{width}_{scheme}"
                        page.screenshot(path=str(out / f"{name}.png"), full_page=True)
                        status = resp.status if resp else "none"
                        lines.append(
                            f"{name}: status={status} h_overflow={overflow} console_errors={errors}"
                        )
                        ctx.close()
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    (out / "report.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
