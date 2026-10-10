"""Native Qt/WebEngine input assertions on an isolated, network-free page.

Read-only JavaScript observes events; no input is dispatched by JavaScript.
The offscreen backend is useful for dispatch QA, not desktop/game acceptance.
"""

import json
import threading
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from qt_host import QtBrowserHost


HTML = """<!doctype html><html><head><title>Native input checks</title></head>
<body style="margin:0;background:#234;width:1280px;height:720px">
<input id="text" style="position:absolute;left:40px;top:600px;width:400px;height:50px">
<script>
window.events=[];
// Exercise F-key delivery without this test page invoking browser shortcuts.
document.addEventListener('keydown',e=>{if(/^F[0-9]+$/.test(e.key))e.preventDefault()});
for (const type of ['mousedown','mouseup','mousemove','wheel','keydown','keyup','input']) {
  document.addEventListener(type,e=>window.events.push({type:e.type, trusted:e.isTrusted,
    button:e.button, buttons:e.buttons, x:e.clientX, y:e.clientY, key:e.key, code:e.code,
    shift:e.shiftKey, ctrl:e.ctrlKey, alt:e.altKey, dx:e.deltaX, dy:e.deltaY}));
}
</script></body></html>"""


def main():
    app = QApplication([])
    host = QtBrowserHost(test_html=HTML)
    host.closed.connect(app.quit)
    host.show()
    report = {"ok": False, "platform": app.platformName(), "checks": []}

    def check(name, expression):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if host.evaluate_readonly(expression):
                report["checks"].append(name)
                return
            time.sleep(0.01)
        raise AssertionError(name + ": " + host.evaluate_readonly("JSON.stringify(window.events)"))

    def run():
        try:
            assert host.wait_ready()
            host.click(200, 200)
            check("native_left_click", "events.some(e=>e.type==='mousedown'&&e.button===0&&e.buttons===1&&e.trusted)&&events.some(e=>e.type==='mouseup'&&e.button===0&&e.buttons===0&&e.trusted)")
            for contact, button, buttons in ((1, 2, 2), (2, 1, 4)):
                host.touch_down(contact, 250, 200, 1)
                host.touch_up(contact)
                check("native_button_" + str(contact), f"events.some(e=>e.type==='mousedown'&&e.button==={button}&&e.buttons==={buttons}&&e.trusted)")
            host.touch_move(-1, 400, 300)
            check("native_hover", "events.some(e=>e.type==='mousemove'&&e.x===400&&e.y===300&&e.buttons===0&&e.trusted)")
            host.touch_down(0, 400, 300)
            host.touch_move(0, 450, 350)
            host.touch_up(0)
            check("native_drag", "events.some(e=>e.type==='mousemove'&&e.x===450&&e.y===350&&e.buttons===1&&e.trusted)")
            host.relative_move(25, -15)
            check("native_relative_move", "events.some(e=>e.type==='mousemove'&&e.x===475&&e.y===335&&e.buttons===0&&e.trusted)")
            host.scroll(0, 120)
            check("native_wheel", "events.some(e=>e.type==='wheel'&&e.dy>0&&e.trusted)")
            host.key(0x10, True)
            host.key(0x57, True)
            host.key(0x57, False)
            host.key(0x10, False)
            check("native_shift_w", "events.some(e=>e.type==='keydown'&&e.code==='KeyW'&&e.key==='W'&&e.shift&&e.trusted)")
            for code, modifier in ((0x11, "ctrl"), (0x12, "alt")):
                host.key(code, True)
                host.click_key(0x4B)
                host.key(code, False)
                check("native_" + modifier, f"events.some(e=>e.type==='keydown'&&e.code==='KeyK'&&e.{modifier}&&e.trusted)")
            for code, modifier in ((0xA0, "shift"), (0xA1, "shift"), (0xA2, "ctrl"), (0xA3, "ctrl"), (0xA4, "alt"), (0xA5, "alt")):
                start = host.evaluate_readonly("events.length")
                host.key(code, True)
                host.click_key(0x4B)
                host.click(300, 250)
                host.key(code, False)
                check("native_modifier_alias_" + str(code), f"events.slice({start}).some(e=>e.type==='keydown'&&e.code==='KeyK'&&e.{modifier}&&e.trusted)&&events.slice({start}).some(e=>e.type==='mousedown'&&e.{modifier}&&e.trusted)")
            # Keeping both aliases held must not release the modifier when
            # only one side is released, nor leave it stuck after inactive.
            start = host.evaluate_readonly("events.length")
            host.key(0xA0, True)
            host.key(0xA1, True)
            host.key(0xA0, False)
            host.click_key(0x4A)
            host.inactive()
            host.click_key(0x4C)
            check("native_overlapping_modifier_aliases", f"events.slice({start}).some(e=>e.type==='keydown'&&e.code==='KeyJ'&&e.shift&&e.trusted)&&events.slice({start}).some(e=>e.type==='keydown'&&e.code==='KeyL'&&!e.shift&&e.trusted)")
            for code in range(0x70, 0x7C):
                name = "F" + str(code - 0x70 + 1)
                host.click_key(code)
                check("native_" + name, f"events.some(e=>e.type==='keydown'&&e.code==='{name}'&&e.key==='{name}'&&e.trusted)&&events.some(e=>e.type==='keyup'&&e.code==='{name}'&&e.trusted)")
            host.key(0x10, True)
            host.key(0x57, True)
            host.touch_down(0, 500, 400)
            host.inactive()
            assert host.connected()
            check("inactive_releases_chord", "events.some(e=>e.type==='keyup'&&e.code==='KeyW'&&e.shift&&e.trusted)&&events.some(e=>e.type==='keyup'&&e.key==='Shift'&&e.trusted)")
            check("inactive_releases_button", "events.some(e=>e.type==='mouseup'&&e.x===500&&e.y===400&&e.buttons===0&&e.trusted)")
            host.click(150, 625)
            host.text("原生 text ✓")
            check("native_unicode_text", "document.getElementById('text').value==='原生 text ✓'&&events.some(e=>e.type==='input'&&e.trusted)")
            host.key(0x11, True)
            host.click_key(0x41)
            host.key(0x11, False)
            host.text("replacement")
            check("native_ctrl_a_selection", "document.getElementById('text').value==='replacement'")
            host.swipe(700, 400, 800, 500, 40)
            check("native_swipe", "events.some(e=>e.type==='mousemove'&&e.x===800&&e.y===500&&e.buttons===1&&e.trusted)&&events.some(e=>e.type==='mouseup'&&e.x===800&&e.y===500&&e.buttons===0)")
            report["ok"] = True
        except Exception as error:
            report["error"] = str(error)
        finally:
            host.close()

    worker = threading.Thread(target=run)
    QTimer.singleShot(0, worker.start)
    app.exec()
    worker.join(timeout=3)
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
