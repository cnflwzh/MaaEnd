"""Private parent/child stdio bridge for MXU's native custom controller.

No socket, JavaScript evaluation method, page-to-host API or filesystem method
is exposed. The browser belongs to this process, which belongs to MXU. The
serial protocol worker never blocks Qt's UI thread.
"""

import argparse
import base64
import json
import hashlib
import os
from pathlib import Path
import sys
import threading

from qt_policy import bounded_int, https_origin, safe_load_error, validate_webengine_environment

MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
METHOD_FIELDS = {
    "connect": (), "connected": (), "screencap": (),
    "click": ("x", "y"),
    "swipe": ("x1", "y1", "x2", "y2", "duration"),
    "touch_down": ("contact", "x", "y", "pressure"),
    "touch_move": ("contact", "x", "y", "pressure"),
    "touch_up": ("contact",),
    "click_key": ("keycode",), "key_down": ("keycode",), "key_up": ("keycode",),
    "input_text": ("text",), "scroll": ("dx", "dy"), "relative_move": ("dx", "dy"),
    "inactive": (), "close": (), "shutdown": (),
}


class RequestError(ValueError):
    def __init__(self, message, request_id=None):
        super().__init__(message)
        self.request_id = request_id


def _reject_constant(value):
    raise ValueError("Invalid JSON number")


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON object keys are forbidden")
        value[key] = item
    return value


def decode_request(line):
    if len(line) > MAX_REQUEST_BYTES:
        raise ValueError("Protocol request exceeds 64 KiB")
    try:
        request = json.loads(line.decode("utf-8"), object_pairs_hook=_object, parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("Request must be one UTF-8 JSON object") from error
    if not isinstance(request, dict) or set(request) != {"id", "method", "params"}:
        raise ValueError("Request requires exactly id, method and params")
    bounded_int(request["id"], 0, 2**64 - 1, "Request id")
    method, params = request["method"], request["params"]
    if not isinstance(method, str) or method not in METHOD_FIELDS:
        raise RequestError("Unknown controller method", request["id"])
    if not isinstance(params, dict) or set(params) != set(METHOD_FIELDS[method]):
        raise RequestError("Unexpected or missing method parameters", request["id"])
    return request


def dispatch(host, method, params):
    if method == "connect":
        return bool(host.wait_ready(30))
    if method == "connected":
        return bool(host.connected())
    if method == "screencap":
        return base64.b64encode(host.capture_png()).decode("ascii")
    if method in ("close", "shutdown"):
        return True
    if method in ("key_down", "key_up"):
        return bool(host.key(params["keycode"], method == "key_down"))
    if method == "input_text":
        return bool(host.text(params["text"]))
    if method == "click_key":
        return bool(host.click_key(params["keycode"]))
    return bool(getattr(host, method)(**params))


def _reply(writer, request_id, result=None, error=None):
    reply = {"id": request_id, "ok": error is None, "result": result, "error": error}
    line = json.dumps(reply, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(line) > MAX_RESPONSE_BYTES:
        line = json.dumps({"id": request_id, "ok": False, "result": None, "error": "Protocol response exceeds 8 MiB"}).encode("ascii") + b"\n"
    writer.write(line)
    writer.flush()


def serve(host, reader, writer):
    """Process one bounded request at a time; EOF and broken pipes close host."""
    try:
        while True:
            line = reader.readline(MAX_REQUEST_BYTES + 1)
            if not line:
                break
            request_id = None
            try:
                request = decode_request(line)
                request_id = request["id"]
                result = dispatch(host, request["method"], request["params"])
                _reply(writer, request_id, result=result)
                if request["method"] in ("close", "shutdown"):
                    break
            except (ValueError, RuntimeError, TypeError, OverflowError) as error:
                if isinstance(error, RequestError):
                    request_id = error.request_id
                _reply(writer, request_id, error=safe_load_error(str(error)))
            if len(line) > MAX_REQUEST_BYTES:
                break  # Do not drain an unbounded invalid input stream.
    except (BrokenPipeError, OSError):
        pass  # Parent is gone; there is no peer to report the failure to.
    finally:
        host.close()


def _protocol_streams():
    # Reserve a copy of stdout exclusively for JSON before loading Qt. Native
    # dependency diagnostics written to fd 1 are redirected to stderr too.
    sys.stdout.flush()
    # BufferedWriter.write + flush handle short OS pipe writes for large PNGs.
    output = os.fdopen(os.dup(sys.stdout.fileno()), "wb")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    return sys.stdin.buffer, output


def main(argv=None):
    reader, writer = _protocol_streams()
    parser = argparse.ArgumentParser(description="MXU private embedded browser host")
    parser.add_argument("--url", default="")
    parser.add_argument("--profile-root", type=Path)
    parser.add_argument("--session-id", default="default")
    args = parser.parse_args(argv)
    profile_lock = None
    host = None
    try:
        validate_webengine_environment(os.environ, sys.argv)
        offline = args.url in ("", "bundled-fixture")
        if not offline:
            https_origin(args.url)
        from PySide6.QtCore import QTimer, QLockFile
        from PySide6.QtWidgets import QApplication
        from qt_host import QtBrowserHost

        app = QApplication([sys.argv[0]])
        if offline:
            html = Path(__file__).with_name("fixture.html").read_text(encoding="utf-8")
            html = html.replace("{{VIDEO_MODE}}", "canvas").replace("{{VIDEO_DESCRIPTION}}", "canvas-to-video stream")
            html = html.replace("{{VIDEO_LABEL}}", "LOCAL CANVAS → VIDEO / NO CLOUD SERVER")
            host = QtBrowserHost(test_html=html)
        else:
            # Stable across launches, independent of URL query/login tokens.
            root = args.profile_root
            if root is None:
                root = Path(sys.executable).resolve().parent.parent / "config" / "cloudweb-profiles"
            identity = args.session_id + "\n" + https_origin(args.url)
            directory = root.resolve() / hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
            directory.mkdir(parents=True, exist_ok=True)
            profile_lock = QLockFile(str(directory / "maaend-profile.lock"))
            profile_lock.setStaleLockTime(0)
            if not profile_lock.tryLock(0):
                raise RuntimeError("This MaaEnd browser profile is already in use")
            host = QtBrowserHost(url=args.url, profile_dir=directory)
        host.closed.connect(app.quit)
        host.show()
        worker = threading.Thread(target=serve, args=(host, reader, writer), daemon=True, name="mxu-private-stdio")
        QTimer.singleShot(0, worker.start)
        result = app.exec()
        # A closed window may leave stdin blocked. It must not keep the child
        # alive. Destroy pages before their profile to flush persistent data.
        worker.join(timeout=0.2)
        return result
    except Exception as error:
        print("MXU browser host failed: " + safe_load_error(str(error)), file=sys.stderr, flush=True)
        return 2
    finally:
        if host is not None:
            import shiboken6
            # Pages must be destroyed before their owning disk profile.
            if shiboken6.isValid(host.view):
                shiboken6.delete(host.view)
            if shiboken6.isValid(host.profile):
                shiboken6.delete(host.profile)
        if profile_lock is not None:
            profile_lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
