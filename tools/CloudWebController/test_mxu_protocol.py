"""Pure protocol tests plus opt-in real source/packaged child-process smoke.

python test_mxu_protocol.py
python test_mxu_protocol.py --integration [--executable path/to/packaged-host]
Qt must have a desktop, or use QT_QPA_PLATFORM=offscreen for limited cloud QA.
"""

import argparse
import base64
import io
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import unittest

from mxu_host import MAX_REQUEST_BYTES, decode_request, serve


class FakeHost:
    def __init__(self):
        self.closed = False
        self.released = False

    def wait_ready(self, timeout):
        return timeout == 30

    def connected(self):
        return not self.closed

    def inactive(self):
        self.released = True
        return True

    def capture_png(self):
        return b"\x89PNG\r\n\x1a\n"

    def click(self, x, y):
        raise ValueError("Unsafe https://example.com/private?token=secret")

    def close(self):
        self.closed = True


def request(request_id, method, **params):
    return json.dumps({"id": request_id, "method": method, "params": params}).encode("utf-8") + b"\n"


class ProtocolTests(unittest.TestCase):
    def test_allows_only_private_typed_methods(self):
        value = decode_request(request(2**64 - 1, "touch_move", contact=-1, x=10, y=20, pressure=0))
        self.assertEqual(value["method"], "touch_move")
        for line in (
            b"[]", b"null", b"\xff", b'{"id":1,"id":2}',
            request(True, "connect"), request(-1, "connect"), request(2**64, "connect"),
            request(1, "evaluate", script="document.title"),
            request(1, "connect", url="https://example.com"),
            request(1, "click", x=1), b"[" * 2000,
            b'{"id":1,"method":"click","params":{"x":NaN,"y":0}}',
        ):
            with self.subTest(line=line[:80]), self.assertRaises(ValueError):
                decode_request(line)

    def test_responses_eof_and_sanitized_errors(self):
        host = FakeHost()
        reader = io.BytesIO(b"".join((request(1, "connect"), request(2, "screencap"), request(3, "click", x=1, y=2), request(4, "inactive"), request(5, "connected"))))
        writer = io.BytesIO()
        serve(host, reader, writer)
        replies = [json.loads(line) for line in writer.getvalue().splitlines()]
        self.assertEqual([item["id"] for item in replies], [1, 2, 3, 4, 5])
        self.assertTrue(replies[0]["result"])
        self.assertEqual(base64.b64decode(replies[1]["result"]), host.capture_png())
        self.assertFalse(replies[2]["ok"])
        self.assertNotIn("secret", replies[2]["error"])
        self.assertTrue(replies[4]["result"])
        self.assertTrue(host.closed and host.released)

    def test_close_stops_before_next_operation(self):
        for method in ("close", "shutdown"):
            writer = io.BytesIO()
            host = FakeHost()
            serve(host, io.BytesIO(request(1, method) + request(2, "connected")), writer)
            self.assertEqual(len(writer.getvalue().splitlines()), 1)
            self.assertTrue(host.closed)

    def test_unsupported_method_keeps_valid_request_id(self):
        writer = io.BytesIO()
        serve(FakeHost(), io.BytesIO(request(42, "evaluate", script="document.title")), writer)
        reply = json.loads(writer.getvalue())
        self.assertEqual(reply["id"], 42)
        self.assertFalse(reply["ok"])

    def test_oversized_line_is_bounded_and_terminal(self):
        writer = io.BytesIO()
        host = FakeHost()
        serve(host, io.BytesIO(b" " * (MAX_REQUEST_BYTES + 1) + b"\n" + request(1, "connect")), writer)
        self.assertFalse(json.loads(writer.getvalue())["ok"])
        self.assertTrue(host.closed)


def integration(executable=None):
    command = [str(executable)] if executable else [sys.executable, str(Path(__file__).with_name("qt_launcher.py"))]
    command += ["--mxu-host", "--url", ""]
    checks = []

    def run_child(eof=False):
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        lines = queue.Queue()
        diagnostics = bytearray()

        def read_lines():
            try:
                while True:
                    line = process.stdout.readline(8 * 1024 * 1024 + 1)
                    lines.put(line)
                    if not line:
                        break
            except (OSError, ValueError):
                lines.put(b"")

        def read_errors():
            try:
                while chunk := process.stderr.read(4096):
                    diagnostics.extend(chunk)
                    if len(diagnostics) > 8192:
                        del diagnostics[:-8192]
            except (OSError, ValueError):
                pass  # The parent test may close pipes after a killed child.

        readers = [threading.Thread(target=target, daemon=True) for target in (read_lines, read_errors)]
        for reader in readers:
            reader.start()
        serial = 0

        def call(method, *, valid=True, **params):
            nonlocal serial
            serial += 1
            process.stdin.write(request(serial, method, **params))
            process.stdin.flush()
            try:
                line = lines.get(timeout=40)
                reply = json.loads(line)
            except (queue.Empty, ValueError) as error:
                raise AssertionError("Missing/invalid protocol reply; stderr: " + diagnostics.decode("utf-8", errors="replace")) from error
            assert reply["id"] == serial, reply
            assert reply["ok"] == valid, reply
            assert set(reply) == {"id", "ok", "result", "error"}, reply
            checks.append(method + ("_rejected" if not valid else ""))
            return reply["result"]

        def marker(expected):
            from PIL import Image
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                png = base64.b64decode(call("screencap"), validate=True)
                with Image.open(io.BytesIO(png)) as image:
                    assert image.format == "PNG" and image.size == (1280, 720)
                    if image.convert("RGB").getpixel((30, 660)) == expected:
                        checks.append("fixture_marker_" + str(expected))
                        return
                time.sleep(0.01)
            raise AssertionError("Captured fixture marker did not reach " + str(expected))

        try:
            assert call("connect") is True
            if eof:
                process.stdin.close()
                assert process.wait(timeout=10) == 0
                checks.append("stdin_eof_exit")
                return
            assert call("connected") is True
            marker((225, 29, 72))
            for contact in (0, 1, 2):
                call("touch_down", contact=contact, x=600, y=500, pressure=1)
                call("touch_move", contact=contact, x=620, y=510, pressure=0)
                call("touch_up", contact=contact)
            call("touch_move", contact=-1, x=700, y=400, pressure=0)
            call("click", x=240, y=350)
            marker((34, 197, 94))
            call("click", x=240, y=350)
            marker((59, 130, 246))
            call("swipe", x1=600, y1=500, x2=700, y2=450, duration=40)
            for keycode in (0x10, 0x11, 0x12, 0x57):
                call("key_down", keycode=keycode)
            call("touch_down", contact=0, x=600, y=500, pressure=1)
            call("inactive")
            assert call("connected") is True
            # The same button can be pressed again only if inactive released it.
            call("touch_down", contact=0, x=600, y=500, pressure=1)
            call("touch_up", contact=0)
            call("key_down", keycode=0x57)
            call("key_up", keycode=0x57)
            call("click_key", keycode=0x57)
            call("click", x=220, y=590)
            call("input_text", text="MXU native text ✓")
            call("scroll", dx=0, dy=120)
            call("relative_move", dx=20, dy=-20)
            call("click", valid=False, x=1280, y=0)
            call("key_down", valid=False, keycode=0x5B)
            call("touch_down", valid=False, contact=3, x=10, y=10, pressure=0)
            call("evaluate", valid=False, script="document.title")
            call("connected")
            assert call("close") is True
            assert process.wait(timeout=10) == 0
            assert lines.get(timeout=5) == b"", "Unexpected non-protocol stdout"
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for reader in readers:
                reader.join(timeout=2)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()

    run_child()
    run_child(eof=True)
    return {"ok": True, "checks": checks, "scope": "Real child stdio and Qt dispatch; no cloud game compatibility claim"}


if __name__ == "__main__":
    if "--integration" not in sys.argv:
        unittest.main()
    else:
        parser = argparse.ArgumentParser()
        parser.add_argument("--integration", action="store_true")
        parser.add_argument("--executable", type=Path)
        parser.add_argument("--output", type=Path)
        args = parser.parse_args()
        result = integration(args.executable)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result))
