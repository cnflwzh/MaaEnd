"""Build the private Windows browser component for the full MaaEnd app."""

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


PACKAGING = Path(__file__).resolve().parent
SOURCE = PACKAGING.parent
ROOT = SOURCE.parents[1]
OUTPUT = ROOT / "build-cloudweb-windows"
LOGS = OUTPUT / "logs"
APP_NAME = "CloudWebHost"
BUNDLE = OUTPUT / "dist" / APP_NAME


def run(name, command, timeout=180):
    LOGS.mkdir(parents=True, exist_ok=True)
    path = LOGS / f"{name}.log"
    print(f"{name}: {command}", flush=True)
    with path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Terminate the whole test tree, including the WebEngine child.
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False)
            process.wait(timeout=30)
            raise RuntimeError(f"{name} timed out; see {path}") from None
    print(path.read_text(encoding="utf-8", errors="replace"), flush=True)
    if code:
        raise RuntimeError(f"{name} exited with {code}; see {path}")


def copy_notices():
    licenses = BUNDLE / "licenses"
    shutil.copytree(PACKAGING / "licenses", licenses, dirs_exist_ok=True)
    for distribution in metadata.distributions():
        name = distribution.metadata["Name"]
        target = licenses / f"{name}-{distribution.version}"
        target.mkdir(parents=True, exist_ok=True)
        (target / "METADATA.txt").write_text(distribution.read_text("METADATA") or "", encoding="utf-8")
        for entry in distribution.files or ():
            if not any(token in str(entry).lower() for token in ("license", "copying", "copyright", "notice")):
                continue
            original = Path(distribution.locate_file(entry))
            if original.is_file():
                # Preserve relative paths without allowing wheel ../ entries to
                # escape the license directory.
                relative = Path(*(part for part in entry.parts if part not in (".", "..")))
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, destination)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise RuntimeError("CPython LICENSE.txt is missing")
    shutil.copy2(python_license, licenses / "Python-LICENSE.txt")
    run("qt-notices", [sys.executable, str(PACKAGING / "collect_qt_notices.py"), str(licenses / "QtWebEngine-ThirdPartyNotices.txt")], timeout=600)


def build():
    run("pyinstaller", [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", str(OUTPUT / "dist"), "--workpath", str(OUTPUT / "pyinstaller"),
        str(PACKAGING / "cloudweb.spec"),
    ], timeout=1200)
    # Validate the actual output rather than assuming a packaging hook ran.
    for pattern in (
        "**/QtWebEngineProcess.exe", "**/qtwebengine_resources.pak", "**/en-US.pak",
        "**/platforms/qwindows.dll", "**/maa/bin/MaaFramework.dll", "**/maa/bin/MaaCustomControlUnit.dll",
        "**/fixture.html",
    ):
        if not any(BUNDLE.glob(pattern)):
            raise RuntimeError(f"Required portable runtime asset missing: {pattern}")
    for name in ("THIRD-PARTY-NOTICES.txt",):
        shutil.copy2(PACKAGING / name, BUNDLE / name)
    shutil.copy2(ROOT / "LICENSE", BUNDLE / "LICENSE")
    # Ship the corresponding experiment source and its reproducible build files.
    shutil.copytree(SOURCE, BUNDLE / "source" / "tools" / "CloudWebController",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"), dirs_exist_ok=True)
    shutil.copy2(ROOT / "LICENSE", BUNDLE / "source" / "LICENSE")
    copy_notices()
    info = {
        "experimental": True,
        "package_type": "internal MaaEnd component; not a standalone application",
        "source_repository": "https://github.com/cnflwzh/MaaEnd",
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": sys.version,
        "qt_platform_override": os.environ.get("QT_QPA_PLATFORM"),
        "dependencies": {item.metadata["Name"]: item.version for item in metadata.distributions()},
        "real_game_compatibility": "unverified",
    }
    (BUNDLE / "build-info.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("build",))
    args = parser.parse_args()
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        parser.error("Build and validate this Windows x64 bundle on Windows x64")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    build()


if __name__ == "__main__":
    main()
