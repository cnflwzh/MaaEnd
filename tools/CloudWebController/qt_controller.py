"""Shared MaaFramework controller for the embedded Qt host on three desktop OSes."""

import uuid

import numpy as np
from maa.controller import CustomController


class EmbeddedWebController(CustomController):
    """Keeps site flow out of the device bridge. Never sends OS-global input."""

    def __init__(self, host):
        self.host = host
        self.last_error = ""
        self._uuid = f"maaend-qt-web-{uuid.uuid4()}"
        self._held_keys = set()
        super().__init__()

    def _call(self, operation, *args):
        try:
            return bool(operation(*args))
        except Exception as error:
            # Exceptions must not cross a ctypes callback boundary.
            self.last_error = str(error)
            return False

    def connect(self):
        return self._call(self.host.wait_ready, 30)

    def connected(self):
        return self.host.connected()

    def request_uuid(self):
        return self._uuid

    def get_features(self):
        # Direct click/click_key callbacks; no synthetic touch/swipe promises.
        return 0

    def start_app(self, intent):
        return False

    def stop_app(self, intent):
        return False

    def screencap(self):
        try:
            image = self.host.capture()
            if image.shape != (720, 1280, 3) or image.dtype != np.uint8:
                raise RuntimeError("Embedded viewport is not 1280x720 BGR8")
            return np.ascontiguousarray(image)
        except Exception as error:
            self.last_error = str(error)
            # The pinned Python binding writes this empty image to Maa. Maa's
            # screenshot job then fails instead of consuming stale pixels.
            return np.empty((0, 0, 3), dtype=np.uint8)

    def click(self, x, y):
        return self._call(self.host.click, x, y)

    def swipe(self, x1, y1, x2, y2, duration):
        return False

    def touch_down(self, contact, x, y, pressure):
        return False

    def touch_move(self, contact, x, y, pressure):
        return False

    def touch_up(self, contact):
        return False

    def click_key(self, keycode):
        return self.key_down(keycode) and self.key_up(keycode)

    def input_text(self, text):
        return self._call(self.host.text, text)

    def key_down(self, keycode):
        if not self._call(self.host.key, keycode, True):
            return False
        self._held_keys.add(keycode)
        return True

    def key_up(self, keycode):
        if not self._call(self.host.key, keycode, False):
            return False
        self._held_keys.discard(keycode)
        return True

    def inactive(self):
        ok = True
        for keycode in tuple(self._held_keys):
            ok = self.key_up(keycode) and ok
        return ok

    def get_custom_info(self):
        return {"backend": "QtWebEngine", "experimental": True, "site_adapter": "separate"}

    def close(self):
        """Run on the harness worker after jobs finish, while Qt still pumps."""
        if getattr(self, "_handle", None):
            self.post_inactive().wait()
            super().__del__()
            self._handle = None
