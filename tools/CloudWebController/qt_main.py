"""Experimental three-platform embedded host; run directly with Python 3.12+."""

import argparse
import json
import os
from pathlib import Path
import platform
import queue
import sys
import threading
import time
import traceback
from urllib.parse import urlsplit

import numpy as np
from PIL import Image
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QWidget
from PySide6.QtNetwork import QNetworkProxy

from qt_controller import EmbeddedWebController
from qt_host import QtBrowserHost
from service_adapters import EAGLE_PUBLIC_DEMO, ManualServiceAdapter


VIDEO_PROBE = """JSON.stringify(Array.from(document.querySelectorAll('video')).map(v => ({
    width:v.videoWidth, height:v.videoHeight, ready:v.readyState,
    time:v.currentTime, paused:v.paused,
    frames:v.getVideoPlaybackQuality ? v.getVideoPlaybackQuality().totalVideoFrames : 0
})))"""


def observed(host, predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def videos(host):
    return json.loads(host.evaluate_readonly(VIDEO_PROBE))


def job_ok(job):
    return job.wait().succeeded


def save_capture(controller, directory, name):
    if Path(name).name != name or not name.endswith(".png"):
        raise ValueError("Screenshot name must be a plain PNG filename")
    job = controller.post_screencap().wait()
    if not job.succeeded:
        raise RuntimeError(controller.last_error or "Maa screenshot failed")
    image = job.get()
    if image is None or image.shape != (720, 1280, 3) or image.dtype != np.uint8:
        raise RuntimeError("Maa did not produce a 1280x720 BGR8 image")
    Image.fromarray(image[:, :, ::-1]).save(directory / name)
    return image


def smoke(host, controller, directory, report):
    def check(name, condition):
        report["checks"][name] = bool(condition)
        if not condition:
            raise RuntimeError(name + " failed: " + controller.last_error)

    check("first_paint", observed(host, lambda: np.array_equal(host.capture()[10, 10], [32, 18, 11])))
    save_capture(controller, directory, "01-before.png")
    check("maa_click", job_ok(controller.post_click(250, 360)))
    check("click_delivered", observed(host, lambda: host.title() == "MaaEnd bridge: clicked 1"))
    check("maa_key", job_ok(controller.post_click_key(ord("W"))))
    check("key_delivered", observed(host, lambda: host.title() == "MaaEnd bridge: key W 1"))
    check("text_focus", job_ok(controller.post_click(220, 593)))
    check("maa_text", job_ok(controller.post_input_text("MaaEnd bridge")))
    check("text_delivered", observed(host, lambda: host.title() == "MaaEnd bridge: text MaaEnd bridge"))
    save_capture(controller, directory, "02-inputs.png")
    check("local_video_frames", observed(host, lambda: any(v["frames"] > 5 and v["width"] == 640 for v in videos(host)), 20))
    before_stats = videos(host)
    before = save_capture(controller, directory, "03-video-a.png")
    check("decoded_frames_advance", observed(host, lambda: videos(host)[0]["frames"] > before_stats[0]["frames"] + 5))
    after = save_capture(controller, directory, "04-video-b.png")
    check("video_pixels_change", np.any(before[280:600, 580:1180] != after[280:600, 580:1180]))
    report["video"] = videos(host)

    # A second native Qt window covers the browser. Offscreen platforms cannot
    # establish real desktop occlusion/focus; mark that boundary explicitly.
    if QApplication.platformName() not in {"offscreen", "minimal"}:
        def cover_view():
            cover = QWidget()
            cover.setWindowTitle("CloudWeb test cover (not a browser)")
            cover.setGeometry(host.view.geometry())
            cover.setStyleSheet("background:#e11d48")
            QLabel("This native window covers the embedded browser", cover).move(30, 30)
            cover.show()
            cover.raise_()
            return cover
        cover = host.call_on_ui(cover_view)
        try:
            covered = save_capture(controller, directory, "05-covered.png")
            check("covered_capture_is_page", not np.all(covered[100, 100] == [72, 29, 225]))
            check("covered_click", job_ok(controller.post_click(250, 360)))
            check("covered_click_delivered", observed(host, lambda: host.title() == "MaaEnd bridge: clicked 2"))
        finally:
            host.call_on_ui(cover.close)
        report["desktop_occlusion"] = "tested with separate native cover window"
    else:
        report["desktop_occlusion"] = "not tested: offscreen/minimal is not a desktop window system"
    check("inactive", job_ok(controller.post_inactive()))


def interactive(host, controller, directory, stop_event):
    """Developer-only stdin commands. There is no socket or web-facing API."""
    commands = queue.Queue()
    def read_input():
        for line in sys.stdin:
            commands.put(line)
        commands.put(None)
    threading.Thread(target=read_input, daemon=True).start()
    print('READY: stdin JSON commands: capture, click, key, status, quit', flush=True)
    while not stop_event.is_set():
        try:
            line = commands.get(timeout=0.1)
        except queue.Empty:
            continue
        if line is None:
            break
        try:
            command = json.loads(line)
            operation = command.get("op")
            if operation == "quit":
                break
            if operation == "capture":
                name = command.get("name", "remote-preview.png")
                save_capture(controller, directory, name)
                result = {"saved": str(directory / name)}
            elif operation == "click":
                result = {"ok": job_ok(controller.post_click(int(command["x"]), int(command["y"])))}
            elif operation == "key":
                result = {"ok": job_ok(controller.post_click_key(int(command["key"])))}
            elif operation == "status":
                result = {"title": host.title(), "videos": videos(host), "connected": host.connected()}
            else:
                raise ValueError("Unknown command; arbitrary scripts, shell and text commands are not exposed")
            print(json.dumps(result, ensure_ascii=False), flush=True)
        except Exception as error:
            print(json.dumps({"error": str(error)}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description="Experimental embedded Maa controller on Windows, macOS and Linux")
    parser.add_argument("--connection", choices=("test-page", "embedded-webview", "eagle-public-demo"), default="test-page")
    parser.add_argument("--url")
    parser.add_argument("--use-environment-proxy", action="store_true", help="Honor an existing HTTP(S)_PROXY for this process; never bypass it")
    parser.add_argument("--video-source", choices=("canvas", "webrtc"), default="canvas", help="Explicit offline video fixture; neither mode is a cloud service")
    parser.add_argument("--allow-origin", action="append", default=[])
    parser.add_argument("--output", type=Path, default=Path("cloudweb-results"))
    parser.add_argument("--keep-open", action="store_true", help="Keep the embedded window open for manual use after connection/test")
    parser.add_argument("--interactive", action="store_true", help="Developer stdin controls; no web/network endpoint")
    args = parser.parse_args()
    if os.environ.get("QTWEBENGINE_DISABLE_SANDBOX") or "--no-sandbox" in os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""):
        parser.error("This prototype refuses to run with the Chromium sandbox disabled")
    if args.connection == "test-page" and (args.url or args.allow_origin):
        parser.error("test-page never accepts a remote URL or additional origins")
    if args.connection == "embedded-webview" and not args.url:
        parser.error("embedded-webview requires an explicit HTTPS --url")
    if args.connection == "eagle-public-demo" and (args.url or args.allow_origin):
        parser.error("The named demo has a fixed verified URL; use embedded-webview for custom configuration")
    if args.connection != "test-page" and not (args.interactive or args.keep_open):
        parser.error("Remote pages require --interactive or --keep-open; login/start/queue are manual")

    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if args.use_environment_proxy:
        proxy_url = urlsplit(os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or "")
        if proxy_url.scheme != "http" or not proxy_url.hostname or not proxy_url.port or proxy_url.username or proxy_url.password:
            parser.error("An existing unauthenticated HTTP proxy URL is required; credentials are not accepted here")
        QNetworkProxy.setApplicationProxy(QNetworkProxy(QNetworkProxy.ProxyType.HttpProxy, proxy_url.hostname, proxy_url.port))
    app = QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)
    adapter = None
    if args.connection == "test-page":
        html = (Path(__file__).with_name("fixture.html")).read_text(encoding="utf-8")
        html = html.replace("{{VIDEO_MODE}}", args.video_source)
        html = html.replace("{{VIDEO_DESCRIPTION}}", "canvas-to-video stream" if args.video_source == "canvas" else "WebRTC loopback")
        html = html.replace("{{VIDEO_LABEL}}", "LOCAL CANVAS → VIDEO / NO WEBRTC OR CLOUD SERVER" if args.video_source == "canvas" else "LOCAL CANVAS → WEBRTC → VIDEO / NO CLOUD SERVER")
        host = QtBrowserHost(test_html=html)
    else:
        adapter = EAGLE_PUBLIC_DEMO if args.connection == "eagle-public-demo" else ManualServiceAdapter("Explicit URL", args.url, tuple(args.allow_origin))
        host = QtBrowserHost(url=adapter.url, allowed_origins=adapter.allowed_origins)
    stop_event = threading.Event()
    host.closed.connect(stop_event.set)
    host.closed.connect(app.quit)
    host.show()
    report = {
        "experimental": True, "os": platform.platform(), "qt_platform": app.platformName(),
        "connection": args.connection, "video_source": args.video_source if args.connection == "test-page" else "remote", "checks": {}, "real_game_compatibility": "unverified",
        "backend": "QtWebEngine (not Windows WebView2)",
    }
    exit_code = [1]

    def run():
        controller = None
        try:
            controller = EmbeddedWebController(host)
            if not job_ok(controller.post_connection()):
                raise RuntimeError(controller.last_error or "Maa/embedded page connection failed")
            report["checks"]["maa_connection"] = True
            if args.connection == "test-page":
                smoke(host, controller, directory, report)
            else:
                report["service"] = adapter.name
                report["stage"] = adapter.stage(videos(host)).value
            if args.interactive:
                interactive(host, controller, directory, stop_event)
            elif args.keep_open:
                stop_event.wait()
            report["result"] = "passed" if args.connection == "test-page" else "manual_preview_completed"
            exit_code[0] = 0
        except Exception as error:
            report["result"] = "failed"
            report["error"] = str(error)
            traceback.print_exc()
        finally:
            if controller:
                controller.close()
            (directory / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False), flush=True)
            host.close()

    worker = threading.Thread(target=run)
    QTimer.singleShot(0, worker.start)
    app.exec()
    worker.join(timeout=30)
    return exit_code[0] if not worker.is_alive() else 1


if __name__ == "__main__":
    raise SystemExit(main())
