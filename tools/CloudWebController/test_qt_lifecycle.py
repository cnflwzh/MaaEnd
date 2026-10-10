"""Opt-in Qt lifecycle test. Run in a desktop or QT_QPA_PLATFORM=offscreen.

This is not a substitute for real desktop focus, occlusion or game testing.
"""

import json
import threading
import time

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from qt_host import QtBrowserHost


HTML = """<html><head><title>ready</title></head><body style='margin:0;background:#123456'>
<button style='width:200px;height:100px' onclick='document.title="clicked"'>Test</button>
<script>document.onkeydown=e=>document.title=e.code+':'+e.isTrusted</script></body></html>"""


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    host = QtBrowserHost(test_html=HTML)
    host.show()
    result = {"qt_platform": app.platformName(), "checks": {}}
    stop = threading.Event()
    host.closed.connect(stop.set)
    code = [1]

    def check(name, condition):
        result["checks"][name] = bool(condition)
        if not condition:
            raise AssertionError(name)

    def rejected(operation):
        try:
            operation()
        except (RuntimeError, ValueError):
            return True
        return False

    def run():
        second = None
        try:
            check("ready", host.wait_ready())
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not np.array_equal(host.capture()[300, 300], [86, 52, 18]):
                time.sleep(0.02)
            image = host.capture()
            check("first_paint", np.array_equal(image[300, 300], [86, 52, 18]))
            image[:] = 0
            check("capture_owned_copy", np.array_equal(host.capture()[300, 300], [86, 52, 18]))
            check("out_of_bounds_rejected", rejected(lambda: host.click(1280, 0)))
            host.call_on_ui(host.view.hide)
            check("hidden_rejected", rejected(host.capture))
            host.show()
            host.call_on_ui(host.view.showMinimized)
            check("minimized_rejected", rejected(host.capture))
            host.call_on_ui(host.view.showNormal)
            check("restored_capture", host.capture().shape == (720, 1280, 3))
            second = host.call_on_ui(lambda: QtBrowserHost(test_html=HTML))
            second.show()
            check("second_host_ready", second.wait_ready())

            # Queue a timed-out operation behind an intentionally busy UI slot.
            # The expired callback must not run once that slot releases.
            called = threading.Event()
            timed_out = threading.Event()
            def request_late():
                if rejected(lambda: host.call_on_ui(called.set, timeout=0.02)):
                    timed_out.set()
            def block_ui():
                waiter = threading.Thread(target=request_late)
                waiter.start()
                time.sleep(0.08)
                return waiter
            waiter = host.call_on_ui(block_ui)
            waiter.join(1)
            time.sleep(0.05)
            check("timeout_reported", timed_out.is_set())
            check("timed_out_callback_skipped", not called.is_set())
            check("input_disabled_after_timeout", not host.connected() and rejected(lambda: host.click(20, 20)))

            waiting_started = threading.Event()
            waiting_cancelled = threading.Event()
            def capture_waiter():
                waiting_started.set()
                if rejected(second.capture):
                    waiting_cancelled.set()
            waiter = threading.Thread(target=capture_waiter)
            def close_during_pending():
                waiter.start()
                waiting_started.wait(1)
                time.sleep(0.03)
                second.close()
            try:
                second.call_on_ui(close_during_pending)
            except RuntimeError:
                pass  # Closing also cancels this enclosing UI request.
            waiter.join(1)
            check("close_cancels_waiting_capture", waiting_cancelled.is_set() and not waiter.is_alive())
            check("closed_input_rejected", rejected(lambda: second.click(20, 20)))
            code[0] = 0
        except Exception as error:
            result["error"] = str(error)
        finally:
            if second:
                second.close()
            host.closed.connect(app.quit)
            host.close()
            print(json.dumps(result), flush=True)

    worker = threading.Thread(target=run)
    QTimer.singleShot(0, worker.start)
    app.exec()
    worker.join(2)
    return code[0]


if __name__ == "__main__":
    raise SystemExit(main())
