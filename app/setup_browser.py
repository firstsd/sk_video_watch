"""One-time video-browser setup, including local Debian/Ubuntu libraries if needed.

Run: uv run python -m app.setup_browser
No system package installation or sudo is performed.
"""

import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import Error, sync_playwright

from app.media import browser_environment


def check_browser():
    with sync_playwright() as automation:
        browser = automation.chromium.launch(
            channel="chromium", headless=True, env=browser_environment()
        )
        browser.close()


def main():
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    try:
        check_browser()
        print("Video discovery browser is ready.")
        return
    except Error:
        if (
            platform.system() != "Linux"
            or not shutil.which("apt-get")
            or not shutil.which("dpkg-deb")
        ):
            raise SystemExit(
                "Browser startup failed. Run: uv run playwright install --with-deps chromium"
            ) from None

    # These libraries are commonly absent on minimal Ubuntu/Debian hosts. Their
    # official distro packages are extracted locally; package scripts are not run.
    sound = "libasound2t64"
    result = subprocess.run(["apt-cache", "show", sound], capture_output=True, check=False)
    if result.returncode or not result.stdout:
        sound = "libasound2"
    root = Path(__file__).resolve().parent.parent / ".runtime"
    root.mkdir(exist_ok=True)
    destination = root / "chromium-libs"
    destination.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as temporary:
        subprocess.run(
            ["apt-get", "download", "libnspr4", "libnss3", sound], cwd=temporary, check=True
        )
        for package in Path(temporary).glob("*.deb"):
            subprocess.run(["dpkg-deb", "-x", str(package), str(destination)], check=True)
    try:
        check_browser()
    except Error:
        raise SystemExit(
            "More system libraries are required on this host. Run: uv run playwright install --with-deps chromium"
        ) from None
    print("Video discovery browser is ready using project-local libraries. Restart the app.")


if __name__ == "__main__":
    main()
