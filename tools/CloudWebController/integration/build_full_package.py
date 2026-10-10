"""Assemble the full MaaEnd GUI experiment from separately verified Windows builds."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from urllib.request import urlopen
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "build-cloudweb-full"
APP = OUT / "MaaEnd-CloudWeb"
INPUTS = ROOT / "build-cloudweb-inputs"
MXU_COMMIT = "9fa8cc51e8ff8cd89d99f3ea55fe3a7a82e6ede3"
FRAMEWORK_VERSION = "v5.14.2"
FRAMEWORK_URL = "https://github.com/MaaXYZ/MaaFramework/releases/download/v5.14.2/MAA-win-x86_64-v5.14.2.zip"
FRAMEWORK_SHA256 = "e279163bcdcab7c87ebe5a9dd157c47e169c78742dbdcc30d095de55ab0eaa9c"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(*args, cwd=ROOT):
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def download_framework():
    archive = ROOT / ".cache" / "cloudweb-downloads" / Path(FRAMEWORK_URL).name
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists() or digest(archive) != FRAMEWORK_SHA256:
        temporary = archive.with_suffix(".download")
        with urlopen(FRAMEWORK_URL, timeout=120) as response, temporary.open("wb") as target:
            shutil.copyfileobj(response, target, length=1024 * 1024)
        if digest(temporary) != FRAMEWORK_SHA256:
            raise RuntimeError("Official MaaFramework archive SHA256 mismatch")
        temporary.replace(archive)
    destination = ROOT / "deps"
    destination.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive) as source:
        for entry in source.infolist():
            if not (destination / entry.filename).resolve().is_relative_to(destination.resolve()):
                raise RuntimeError("Unsafe path in MaaFramework archive")
        source.extractall(destination)
    if not (destination / "bin" / "MaaFramework.dll").is_file():
        raise RuntimeError("MaaFramework SDK archive layout changed")
    print(f"Verified {archive.name}: {FRAMEWORK_SHA256}")


def apply_mxu():
    checkout = ROOT / "vendor" / "MXU"
    if git("rev-parse", "HEAD", cwd=checkout) != MXU_COMMIT:
        raise RuntimeError("MXU checkout does not match the reviewed pinned commit")
    patch = ROOT / "tools" / "CloudWebController" / "integration" / "mxu.patch"
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=checkout, check=True)
    subprocess.run(["git", "apply", str(patch)], cwd=checkout, check=True)
    print(f"Applied MXU patch SHA256 {digest(patch)} to {MXU_COMMIT}")


def install_framework():
    source = ROOT / "deps"
    destination = ROOT / "install" / "maafw"
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source / "bin", destination, dirs_exist_ok=True)
    shutil.copytree(source / "share" / "MaaAgentBinary", destination / "MaaAgentBinary", dirs_exist_ok=True)
    for entry in destination.glob("MaaNode*"):
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    # Preserve the SDK's own attribution/source materials alongside the runtime.
    notices = ROOT / "install" / "licenses" / "MaaFramework-SDK"
    for entry in source.rglob("*"):
        if entry.is_file() and any(word in entry.name.lower() for word in ("license", "notice", "copying")):
            target = notices / entry.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry, target)


def assemble():
    if APP.exists():
        raise RuntimeError("Refusing to overwrite an existing application; use --output with a new directory")
    runtime = INPUTS / "maaend-runtime"
    application = INPUTS / "mxu"
    host = INPUTS / "qt-host"
    packaging_commit = git("rev-parse", "HEAD")
    component_commit = os.environ.get("CLOUDWEB_COMPONENT_COMMIT", packaging_commit)
    component_root = ROOT / "component-source" if component_commit != packaging_commit else ROOT
    if git("rev-parse", "HEAD", cwd=component_root) != component_commit:
        raise RuntimeError("Component source checkout does not match the immutable build commit")
    shutil.copytree(runtime, APP, dirs_exist_ok=True)
    shutil.copy2(component_root / "assets" / "mxu-cloudweb.json", APP / "mxu-cloudweb.json")
    shutil.copy2(application / "mxu.exe", APP / "MaaEnd.exe")
    shutil.copytree(host, APP / "cloudweb-host", dirs_exist_ok=True)
    # The full app is the only documented entry point. The Qt selector is internal.
    for name in ("Start-CloudWeb.cmd", "WINDOWS-README.txt"):
        (APP / "cloudweb-host" / name).unlink(missing_ok=True)
    shutil.copy2(ROOT / "tools" / "CloudWebController" / "integration" / "WINDOWS-FULL-README.txt", APP / "WINDOWS-FULL-README.txt")
    shutil.copy2(component_root / "LICENSE", APP / "LICENSE")
    licenses = APP / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    shutil.copy2(application / "MXU-LICENSE", licenses / "MXU-LICENSE")
    source = APP / "source" / "CloudWebIntegration"
    source.mkdir(parents=True, exist_ok=True)
    shutil.copy2(component_root / "tools" / "CloudWebController" / "integration" / "mxu.patch", source / "mxu.patch")
    for name in ("build_full_package.py", "capture_window.ps1", "WINDOWS-FULL-README.txt"):
        shutil.copy2(ROOT / "tools" / "CloudWebController" / "integration" / name, source / name)
    formatted_patch = application / "build-evidence" / "mxu-formatted.patch"
    if not formatted_patch.is_file():
        raise RuntimeError("The actual formatted MXU build patch is missing")
    shutil.copy2(formatted_patch, source / "mxu-formatted.patch")
    required = (
        "MaaEnd.exe", "interface.json", "mxu-cloudweb.json", "agent/go-service.exe", "agent/cpp-algo.exe",
        "maafw/MaaFramework.dll", "maafw/MaaCustomControlUnit.dll",
        "cloudweb-host/CloudWebHost.exe",
    )
    for relative in required:
        if not (APP / relative).is_file():
            raise RuntimeError(f"Full MaaEnd bundle is missing {relative}")
    for pattern in ("tasks/*.json", "resource/pipeline/**/*.json", "resource/model/**/*"):
        if not any(path.is_file() for path in APP.glob(pattern)):
            raise RuntimeError(f"MaaEnd assets/models are missing: {pattern}")
    interface = json.loads((APP / "interface.json").read_text(encoding="utf-8"))
    if not interface.get("task") and not interface.get("import"):
        raise RuntimeError("Full MaaEnd task list is empty")
    for imported in interface.get("import", []):
        if not (APP / imported).is_file():
            raise RuntimeError(f"Imported MaaEnd task file is missing: {imported}")
    config = {
        "version": "1.0", "instances": [], "presetInitialized": False,
        "settings": {
            "theme": "system", "language": "zh-CN", "webServerEnabled": False,
            "allowLanAccess": False, "helpImproveSoftware": False,
            "autoRunOnLaunch": False, "minimizeToTray": False,
            "connectionPanelExpanded": True,
        },
    }
    config_dir = APP / "config"
    if config_dir.exists():
        shutil.rmtree(config_dir)
    config_dir.mkdir()
    (APP / "mxu-MaaEnd.json").unlink(missing_ok=True)
    (config_dir / "mxu-MaaEnd.json").write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    info = {
        "experimental": True,
        "product": "Full MaaEnd GUI with experimental CloudWeb connection",
        "entrypoint": "MaaEnd.exe",
        "package_type": "portable ZIP, not an installer",
        "maaend_repository": "https://github.com/cnflwzh/MaaEnd",
        "maaend_commit": component_commit,
        "component_source_commit": component_commit,
        "packaging_commit": packaging_commit,
        "component_build_run_id": os.environ.get("CLOUDWEB_COMPONENT_RUN_ID"),
        "component_artifact_ids": json.loads(os.environ.get("CLOUDWEB_COMPONENT_ARTIFACT_IDS", "{}")),
        "mxu_repository": "https://github.com/MistEO/MXU",
        "mxu_base_commit": MXU_COMMIT,
        "mxu_patch_sha256": digest(source / "mxu.patch"),
        "mxu_formatted_build_patch_sha256": digest(source / "mxu-formatted.patch"),
        "maafw_version": FRAMEWORK_VERSION,
        "maafw_archive_sha256": FRAMEWORK_SHA256,
        "maadeps_version": "v2.12.6",
        "platform": platform.platform(),
        "packaged_at_utc": datetime.now(timezone.utc).isoformat(),
        "files_sha256": {name: digest(APP / name) for name in required},
        "game_compatibility": "unverified; local fixture success does not establish live cloud-game compatibility",
    }
    (APP / "cloudweb-build-info.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    evidence = APP / "validation"
    evidence.mkdir(parents=True, exist_ok=True)
    for component in ("mxu", "maaend-runtime", "qt-host"):
        logs = INPUTS / component / "build-evidence"
        if logs.exists():
            shutil.copytree(logs, evidence / component, dirs_exist_ok=True)
    print(f"Assembled full MaaEnd at {APP}")


def test_native():
    evidence = OUT / "verification"
    evidence.mkdir(parents=True, exist_ok=True)
    report = evidence / "integration-report.json"
    command = [str(APP / "MaaEnd.exe"), "--cloudweb-self-test", "--report", str(report)]
    with (evidence / "native-self-test.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=APP, stdout=log, stderr=subprocess.STDOUT)
        try:
            code = process.wait(timeout=180)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False)
            raise RuntimeError("Full MaaEnd native Tasker self-test timed out") from None
    if code != 0:
        raise RuntimeError(f"Full MaaEnd native Tasker self-test exited {code}")
    result = json.loads(report.read_text(encoding="utf-8"))
    print(json.dumps(result, ensure_ascii=False))
    if result.get("result") != "passed":
        raise RuntimeError("Full MaaEnd native Tasker report did not pass")


def seed_ui_check():
    """Prepare a disposable CI config; restore it before producing the ZIP."""
    import json5

    config_path = APP / "config" / "mxu-MaaEnd.json"
    shutil.copy2(config_path, OUT / "clean-config.json")
    interface_path = APP / "interface.json"
    shutil.copy2(interface_path, OUT / "shipping-interface.json")
    interface = json.loads(interface_path.read_text(encoding="utf-8"))
    manifest = json.loads((APP / "mxu-cloudweb.json").read_text(encoding="utf-8"))
    compatible_tasks = set(manifest["compatible_tasks"])
    # Only the disposable screenshot run skips the remote welcome announcement.
    interface.pop("welcome", None)
    interface_path.write_text(json.dumps(interface, indent=2, ensure_ascii=False), encoding="utf-8")
    tasks = []
    for relative in interface.get("import", []):
        item = json5.loads((APP / relative).read_text(encoding="utf-8"))
        for task in item.get("task", []):
            if task["name"] in compatible_tasks:
                tasks.append({"id": f"ui-check-{len(tasks)}", "taskName": task["name"], "enabled": False, "optionValues": {}})
            if len(tasks) >= 5:
                break
        if len(tasks) >= 5:
            break
    if not tasks:
        raise RuntimeError("Client manifest does not match any existing task for UI verification")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config.update({
        "instances": [{"id": "cloudweb-verification", "name": "云网页实验", "controllerName": "CloudWeb",
                       "resourceName": interface["resource"][0]["name"], "tasks": tasks}],
        "lastActiveInstanceId": "cloudweb-verification", "presetInitialized": True,
    })
    config["settings"].update({"onboardingCompleted": True, "theme": "dark", "windowSize": {"width": 1200, "height": 800}})
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def archive(require_validation=True):
    if (APP / "config" / "cloudweb-profiles").exists():
        raise RuntimeError("Refusing to archive an application containing browser login profiles")
    evidence = OUT / "verification"
    if require_validation:
        # Native bridge/Tasker verification must produce its own successful report.
        report = json.loads((evidence / "integration-report.json").read_text(encoding="utf-8"))
        if report.get("result") != "passed":
            raise RuntimeError("Full MaaEnd integration verification did not pass")
        screenshot = evidence / "MaaEnd-window.png"
        if not screenshot.is_file():
            raise RuntimeError("Full MaaEnd window screenshot is missing")
        from PIL import Image
        with Image.open(screenshot) as captured:
            colors = captured.convert("RGB").resize((100, 100)).getcolors(10000) or []
            if captured.width < 500 or captured.height < 350 or len(colors) < 30:
                raise RuntimeError("Full MaaEnd window capture is blank or incomplete")
        # Never ship a verification run's selected tasks, browser cache or logs as
        # the user's starting configuration. Keep only the explicit evidence folder.
        # Remove run-generated backups/layout caches too, then restore only the
        # explicit shipping config under MXU's actual config directory.
        shutil.rmtree(APP / "config")
        (APP / "config").mkdir()
        shutil.copy2(OUT / "clean-config.json", APP / "config" / "mxu-MaaEnd.json")
        (APP / "mxu-MaaEnd.json").unlink(missing_ok=True)
        shutil.copy2(OUT / "shipping-interface.json", APP / "interface.json")
    for directory in ("cache", "debug"):
        if (APP / directory).exists():
            shutil.rmtree(APP / directory)
    if require_validation:
        shutil.copytree(evidence, APP / "validation" / "full-app", dirs_exist_ok=True)
    else:
        status = {"runtime_acceptance": "not performed on this final package", "reason": "User requested implementation and compilation only; user will test", "cloud_game_compatibility": "unverified"}
        (APP / "runtime-acceptance.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    deliverables = OUT / "deliverables"
    deliverables.mkdir(parents=True, exist_ok=True)
    info = json.loads((APP / "cloudweb-build-info.json").read_text(encoding="utf-8"))
    filename = f"MaaEnd-CloudWeb-full-windows-x64-{info['component_source_commit'][:12]}-pkg-{info['packaging_commit'][:12]}"
    archive_path = Path(shutil.make_archive(str(deliverables / filename), "zip", APP.parent, APP.name))
    checksum = digest(archive_path)
    (deliverables / f"{filename}.zip.sha256").write_text(f"{checksum}  {archive_path.name}\n", encoding="ascii")
    shutil.copy2(APP / "WINDOWS-FULL-README.txt", deliverables)
    print(f"Full MaaEnd portable ZIP: {archive_path}\nSHA256: {checksum}")


def main():
    global OUT, APP
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("download-framework", "apply-mxu", "install-framework", "assemble", "test-native", "seed-ui-check", "archive", "archive-unverified"))
    parser.add_argument("--output", type=Path, default=OUT, help="Fresh output directory; existing applications are never overwritten")
    args = parser.parse_args()
    OUT = args.output.resolve()
    APP = OUT / "MaaEnd-CloudWeb"
    OUT.mkdir(parents=True, exist_ok=True)
    {
        "download-framework": download_framework, "apply-mxu": apply_mxu,
        "install-framework": install_framework, "assemble": assemble,
        "test-native": test_native, "seed-ui-check": seed_ui_check, "archive": archive,
        "archive-unverified": lambda: archive(require_validation=False),
    }[args.stage]()


if __name__ == "__main__":
    main()
