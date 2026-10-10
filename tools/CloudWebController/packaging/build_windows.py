"""Build, smoke-test and archive the Windows-only portable Qt experiment."""

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
APP_NAME = "MaaEnd-CloudWeb-Prototype"
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


def check_report(directory):
    report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    expected = {
        "maa_connection", "first_paint", "maa_click", "click_delivered", "maa_key",
        "key_delivered", "text_focus", "maa_text", "text_delivered",
        "local_video_frames", "decoded_frames_advance", "video_pixels_change", "inactive",
    }
    if report.get("result") != "passed" or not all(report.get("checks", {}).get(key) is True for key in expected):
        raise RuntimeError(f"Incomplete or failed smoke report: {directory}")
    if not report.get("os", "").startswith("Windows"):
        raise RuntimeError("Smoke report did not come from Windows")


def test_source():
    run("policy", [sys.executable, "-m", "unittest", "discover", "-s", str(SOURCE), "-p", "test_qt_policy.py"])
    run("lifecycle", [sys.executable, str(SOURCE / "test_qt_lifecycle.py")])
    directory = OUTPUT / "source-smoke"
    run("source-smoke", [sys.executable, str(SOURCE / "qt_launcher.py"), "--launcher-smoke", "--output", str(directory)])
    check_report(directory)


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
    for name in ("Start-CloudWeb.cmd", "WINDOWS-README.txt", "THIRD-PARTY-NOTICES.txt"):
        shutil.copy2(PACKAGING / name, BUNDLE / name)
    shutil.copy2(ROOT / "LICENSE", BUNDLE / "LICENSE")
    # Ship the corresponding experiment source and its reproducible build files.
    shutil.copytree(SOURCE, BUNDLE / "source" / "tools" / "CloudWebController",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"), dirs_exist_ok=True)
    shutil.copy2(ROOT / "LICENSE", BUNDLE / "source" / "LICENSE")
    workflow = BUNDLE / "source" / ".github" / "workflows"
    workflow.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / ".github" / "workflows" / "cloudweb-prototype.yml", workflow)
    copy_notices()
    info = {
        "experimental": True,
        "package_type": "portable one-folder, not an installer",
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


def test_frozen():
    directory = OUTPUT / "frozen-smoke"
    run("frozen-smoke", [str(BUNDLE / f"{APP_NAME}.exe"), "--launcher-smoke", "--output", str(directory)])
    check_report(directory)
    webrtc = OUTPUT / "frozen-webrtc"
    run("frozen-webrtc", [str(BUNDLE / f"{APP_NAME}.exe"), "--worker", "--video-source", "webrtc", "--output", str(webrtc)])
    check_report(webrtc)


def archive():
    # A ZIP is produced only after both actual frozen-app checks passed.
    for directory in ("source-smoke", "frozen-smoke", "frozen-webrtc"):
        check_report(OUTPUT / directory)
        shutil.copytree(OUTPUT / directory, BUNDLE / "validation" / directory, dirs_exist_ok=True)
    shutil.copytree(LOGS, BUNDLE / "validation" / "logs", dirs_exist_ok=True)
    commit = json.loads((BUNDLE / "build-info.json").read_text(encoding="utf-8"))["commit"]
    deliverables = OUTPUT / "deliverables"
    deliverables.mkdir(parents=True, exist_ok=True)
    filename = f"{APP_NAME}-windows-x64-{commit[:12]}"
    zip_path = Path(shutil.make_archive(str(deliverables / filename), "zip", BUNDLE.parent, BUNDLE.name))
    with zip_path.open("rb") as archive_file:
        checksum = hashlib.file_digest(archive_file, "sha256").hexdigest()
    (deliverables / f"{filename}.zip.sha256").write_text(f"{checksum}  {zip_path.name}\n", encoding="ascii")
    shutil.copy2(BUNDLE / "WINDOWS-README.txt", deliverables)
    print(f"Portable archive: {zip_path}\nSHA256: {checksum}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("test-source", "build", "test-frozen", "archive"))
    args = parser.parse_args()
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        parser.error("Build and validate this Windows x64 bundle on Windows x64")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    {"test-source": test_source, "build": build, "test-frozen": test_frozen, "archive": archive}[args.stage]()


if __name__ == "__main__":
    main()
