"""A single embedded QtWebEngine view with worker-safe, view-local controls.

Create QApplication and QtBrowserHost on the application's main thread. Keep
that event loop running while MaaFramework calls the methods from its worker.
No external browser, debugging socket, JavaScript input dispatch or host API is
used. Captures cover the web viewport, not the desktop. Actual desktop background
behavior requires platform testing; hidden/minimized rendering is unsupported.
"""

from dataclasses import dataclass, field
import os
from threading import Condition, Event
import time
from typing import Any, Callable

import numpy as np
from PySide6.QtCore import QBuffer, QByteArray, QCoreApplication, QEvent, QIODevice, QObject, QPoint, QPointF, QThread, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QImage, QInputMethodEvent, QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWebEngineCore import QWebEngineLoadingInfo, QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

from qt_policy import VIEWPORT_HEIGHT, VIEWPORT_WIDTH, allowed_origins as make_origins, bounded_int, canonical_key, https_origin, inside_viewport, mouse_contact, safe_load_error, supported_key, validate_webengine_environment


@dataclass(eq=False)
class _UiCall:
    function: Callable[..., Any]
    asynchronous: bool = False
    done: Event = field(default_factory=Event)
    result: Any = None
    error: BaseException | None = None
    cancelled: bool = False


class _ResourcePolicy(QWebEngineUrlRequestInterceptor):
    def __init__(self, offline: bool, parent: QObject):
        super().__init__(parent)
        self._schemes = frozenset(("data", "about")) if offline else frozenset(("https", "wss", "data", "blob", "about"))

    def interceptRequest(self, info):
        # Remote pages may use CDN/media subresources, but never local files,
        # insecure transport, custom handlers or an OS-launched protocol.
        if info.requestUrl().scheme().lower() not in self._schemes:
            info.block(True)


class _RestrictedPage(QWebEnginePage):
    navigationBlocked = Signal(str)

    def __init__(self, profile, origins, offline, parent):
        super().__init__(profile, parent)
        self._origins = origins
        self._offline_bootstrap = offline
        self._offline = offline

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        if self._offline:
            # setHtml makes exactly one data: main-frame navigation. Once it
            # has loaded, even another data: document must not replace it.
            if is_main_frame and self._offline_bootstrap and url.scheme() == "data":
                self._offline_bootstrap = False
                return True
            if is_main_frame:
                self.navigationBlocked.emit("Offline page replacement is forbidden")
            return not is_main_frame and url.toString() == "about:blank"
        if not is_main_frame:
            return url.scheme() in ("https", "about", "blob", "data")
        try:
            origin = https_origin(url.toString(QUrl.ComponentFormattingOption.FullyEncoded))
            if origin in self._origins:
                return True
            reason = "Top-level origin is not explicitly allowed: " + origin
        except ValueError:
            reason = "Top-level navigation requires an allowed HTTPS origin on port 443"
        self.navigationBlocked.emit(reason)
        return False

    def createWindow(self, window_type):
        return None

    def chooseFiles(self, mode, old_files, accepted_mime_types):
        return []

    def javaScriptAlert(self, security_origin, message):
        pass

    def javaScriptConfirm(self, security_origin, message):
        return False

    def javaScriptPrompt(self, security_origin, message, default_value):
        return False, ""


class _View(QWebEngineView):
    closing = Signal()

    def closeEvent(self, event):
        self.closing.emit()
        super().closeEvent(event)


class QtBrowserHost(QObject):
    """UI-owned browser; all public operations except construction are safe
    from a worker. A passed profile must be dedicated and off-the-record.

    wait_ready and evaluate_readonly cannot block the UI thread. Input delivery
    only acknowledges dispatch; use a fresh screenshot/page state to verify its
    effect. Timeout cancels queued work, but cannot undo an already sent event.
    """

    closed = Signal()
    _requested = Signal(object)
    _close_requested = Signal()
    _release_requested = Signal()

    def __init__(self, url=None, test_html=None, profile=None, allowed_origins=()):
        app = QApplication.instance()
        if app is None or QThread.currentThread() != app.thread():
            raise RuntimeError("Construct QtBrowserHost on the QApplication main thread")
        validate_webengine_environment(os.environ, app.arguments())
        if (url is None) == (test_html is None):
            raise ValueError("Provide exactly one explicit HTTPS URL or offline test_html")
        # A worker may hold the last Python reference returned by call_on_ui.
        # Native WebEngine objects must still be destroyed by the UI owner.
        super().__init__(app)
        self._state = Condition()
        self._pending: set[_UiCall] = set()
        self._closed = False
        self._faulted = False
        self._ready = False
        self._load_error: str | None = None
        self._navigation_error: str | None = None
        self._held_keys: set[int] = set()
        self._held_contacts: set[int] = set()
        self._pointer = QPoint(VIEWPORT_WIDTH // 2, VIEWPORT_HEIGHT // 2)
        origins = make_origins(url, allowed_origins) if url is not None else frozenset()
        if url is None and allowed_origins:
            raise ValueError("Offline mode cannot allow remote origins")
        self.profile = profile if profile is not None else QWebEngineProfile(self)
        if not self.profile.isOffTheRecord():
            raise ValueError("The controller requires an off-the-record browser profile")
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        self._resource_policy = _ResourcePolicy(url is None, self.profile)
        self.profile.setUrlRequestInterceptor(self._resource_policy)
        self.profile.downloadRequested.connect(lambda download: download.cancel())
        self.view = _View()
        self.view.setFixedSize(VIEWPORT_WIDTH, VIEWPORT_HEIGHT)
        self.view.setWindowTitle("MaaEnd · embedded web controller")
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.view.setAcceptDrops(False)
        self.page = _RestrictedPage(self.profile, origins, url is None, self.view)
        self.view.setPage(self.page)
        self.view.setZoomFactor(1.0)
        settings = self.page.settings()
        for name in (
            "JavascriptCanOpenWindows", "JavascriptCanAccessClipboard", "JavascriptCanPaste",
            "LocalContentCanAccessRemoteUrls", "LocalContentCanAccessFileUrls", "HyperlinkAuditingEnabled",
            "PluginsEnabled", "FullScreenSupportEnabled", "ScreenCaptureEnabled", "AllowRunningInsecureContent",
            "AllowGeolocationOnInsecureOrigins", "AllowWindowActivationFromJavaScript", "NavigateOnDropEnabled",
        ):
            attribute = getattr(QWebEngineSettings.WebAttribute, name, None)
            if attribute is not None:
                settings.setAttribute(attribute, False)
        settings.setUnknownUrlSchemePolicy(QWebEngineSettings.UnknownUrlSchemePolicy.DisallowUnknownUrlSchemes)
        self.page.permissionRequested.connect(lambda permission: permission.deny())
        self.page.fileSystemAccessRequested.connect(lambda request: request.reject())
        self.page.registerProtocolHandlerRequested.connect(lambda request: request.reject())
        self.page.fullScreenRequested.connect(lambda request: request.reject())
        self.page.certificateError.connect(lambda error: error.rejectCertificate())
        self.page.selectClientCertificate.connect(lambda selection: selection.selectNone())
        self.page.desktopMediaRequested.connect(lambda request: request.cancel())
        self.page.webAuthUxRequested.connect(lambda request: request.cancel())
        # Leaving an authenticator empty cancels the challenge. Do not consult
        # system credentials, show a login dialog or retry cached credentials.
        self.page.authenticationRequired.connect(lambda url, authenticator: None)
        self.page.proxyAuthenticationRequired.connect(lambda url, authenticator, host: None)
        self.page.newWindowRequested.connect(lambda request: None)
        self.page.loadStarted.connect(self._load_started)
        self.page.loadingChanged.connect(self._loading_changed)
        self.page.loadFinished.connect(self._load_finished)
        self.page.navigationBlocked.connect(self._navigation_blocked)
        self.page.renderProcessTerminated.connect(self._render_terminated)
        self.view.closing.connect(self._shutdown)
        app.aboutToQuit.connect(self._shutdown)
        self._requested.connect(self._dispatch, Qt.ConnectionType.QueuedConnection)
        self._close_requested.connect(self.view.close, Qt.ConnectionType.QueuedConnection)
        self._release_requested.connect(self._release_inputs, Qt.ConnectionType.QueuedConnection)
        if url is None:
            self.view.setHtml(test_html)
        else:
            self.view.setUrl(QUrl(url))

    def _is_ui(self):
        return QThread.currentThread() == self.thread()

    def _ensure_open(self):
        if self._closed:
            raise RuntimeError("Browser host is closed")

    def _submit(self, request, timeout):
        if timeout <= 0:
            raise ValueError("Timeout must be positive")
        with self._state:
            self._ensure_open()
            self._pending.add(request)
        self._requested.emit(request)
        if not request.done.wait(timeout):
            with self._state:
                if not request.done.is_set():
                    request.cancelled = True
                    request.error = RuntimeError("Browser UI operation timed out; already-dispatched input cannot be undone")
                    self._faulted = True
                    self._ready = False
                    self._load_error = str(request.error)
                    self._state.notify_all()
                    self._pending.discard(request)
                    request.done.set()
                    # A prior key/button may still be held when another UI
                    # operation times out. Release it once the UI recovers;
                    # never retry the timed-out action or re-enable input.
                    self._release_requested.emit()
        if request.error is not None:
            raise request.error
        return request.result

    def _finish(self, request, result=None, error=None):
        with self._state:
            if request.cancelled or request.done.is_set():
                return
            request.result, request.error = result, error
            self._pending.discard(request)
            request.done.set()

    @Slot(object)
    def _dispatch(self, request):
        with self._state:
            if self._closed or request.cancelled or request.done.is_set():
                return
        try:
            if request.asynchronous:
                request.function(lambda value: self._finish(request, value))
            else:
                self._finish(request, request.function())
        except BaseException as error:
            self._finish(request, error=RuntimeError(str(error)))

    def call_on_ui(self, function, timeout=10):
        """Invoke a short local callable. Never wait on a Maa task inside it."""
        if self._is_ui():
            with self._state:
                self._ensure_open()
            return function()
        return self._submit(_UiCall(function), timeout)

    def evaluate_readonly(self, script, timeout=10):
        """Trusted local runner diagnostics only; never exposed to web content.

        Callers must supply read-only expressions, never JS input dispatch or
        page mutation. Results are marshalled by Qt's asynchronous callback.
        """
        if self._is_ui():
            raise RuntimeError("JavaScript results must be awaited from a worker, not the UI thread")
        return self._submit(_UiCall(lambda callback: self.page.runJavaScript(script, callback), asynchronous=True), timeout)

    @Slot()
    def _load_started(self):
        self._release_inputs()
        with self._state:
            self._ready = False
            self._load_error = None
            self._navigation_error = None

    @Slot(str)
    def _navigation_blocked(self, reason):
        with self._state:
            self._navigation_error = reason

    def _loading_changed(self, info):
        if info.status() not in (
            QWebEngineLoadingInfo.LoadStatus.LoadFailedStatus,
            QWebEngineLoadingInfo.LoadStatus.LoadStoppedStatus,
        ):
            return
        detail = (
            f"{info.errorDomain().name}, code {info.errorCode()}: "
            + safe_load_error(info.errorString())
        )
        with self._state:
            if self._closed:
                return
            reason = self._navigation_error or "Embedded page load failed"
            self._load_error = f"{reason} ({detail})"
            self._ready = False
            self._state.notify_all()

    @Slot(bool)
    def _load_finished(self, success):
        with self._state:
            if self._closed:
                return
            self._ready = bool(success) and not self._faulted
            self._load_error = None if success else (
                self._load_error or self._navigation_error or "Page load failed before detailed diagnostics were available"
            )
            self._state.notify_all()

    def _render_terminated(self, status, exit_code):
        with self._state:
            self._ready = False
            self._load_error = f"Embedded renderer terminated ({status}, exit {exit_code})"
            self._state.notify_all()

    def wait_ready(self, timeout=30):
        with self._state:
            self._ensure_open()
            if not self._ready and self._is_ui():
                raise RuntimeError("Readiness must be awaited from a worker while Qt's event loop runs")
            if not self._state.wait_for(lambda: self._ready or self._closed or self._load_error, timeout):
                raise RuntimeError("Embedded browser did not finish loading before the timeout")
            self._ensure_open()
            if self._load_error:
                raise RuntimeError(self._load_error)
            return True

    def connected(self):
        with self._state:
            return self._ready and not self._closed and not self._faulted

    def show(self):
        return self.call_on_ui(self.view.show)

    def title(self):
        return self.call_on_ui(self.view.title)

    def _check_surface(self):
        if not self.connected():
            raise RuntimeError("Embedded browser is not ready")
        if not self.view.isVisible() or self.view.isMinimized():
            raise RuntimeError("Hidden/minimized capture and input are unsupported; restore the embedded view")
        if self.view.width() != VIEWPORT_WIDTH or self.view.height() != VIEWPORT_HEIGHT:
            raise RuntimeError("Embedded browser viewport must remain exactly 1280x720")

    def _capture_image(self):
        self._check_surface()
        image = self.view.grab().toImage().convertToFormat(QImage.Format.Format_RGB888)
        if image.isNull():
            raise RuntimeError("Embedded browser returned an empty screenshot")
        # Logical input coordinates always match the returned Maa viewport.
        if image.width() != VIEWPORT_WIDTH or image.height() != VIEWPORT_HEIGHT:
            image = image.scaled(VIEWPORT_WIDTH, VIEWPORT_HEIGHT, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        return image

    def capture_png(self):
        def grab():
            data = QByteArray()
            buffer = QBuffer(data)
            if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not self._capture_image().save(buffer, "PNG"):
                raise RuntimeError("Embedded screenshot PNG encoding failed")
            return bytes(data)
        return self.call_on_ui(grab)

    def capture(self):
        def grab():
            image = self._capture_image()
            rows = np.frombuffer(image.constBits(), dtype=np.uint8, count=image.sizeInBytes()).reshape(image.height(), image.bytesPerLine())
            rgb = rows[:, :VIEWPORT_WIDTH * 3].reshape(VIEWPORT_HEIGHT, VIEWPORT_WIDTH, 3)
            return rgb[:, :, ::-1].copy()  # Own storage before QImage is destroyed.
        return self.call_on_ui(grab)

    def _input_target(self):
        self._check_surface()
        target = self.view.focusProxy() or self.view
        target.setFocus(Qt.FocusReason.OtherFocusReason)
        return target

    def click(self, x, y):
        if not inside_viewport(x, y):
            raise ValueError("Click is outside the 1280x720 viewport")
        def send():
            if 0 in self._held_contacts:
                raise RuntimeError("Cannot click while the left button is held")
            self._input_target()
            self._pointer = QPoint(x, y)
            self._held_contacts.add(0)
            self._mouse_event(QEvent.Type.MouseButtonPress, 0)
            self._held_contacts.remove(0)
            self._mouse_event(QEvent.Type.MouseButtonRelease, 0)
            return True
        return self.call_on_ui(send)

    def _modifiers(self):
        modifiers = Qt.KeyboardModifier.NoModifier
        held = {canonical_key(code) for code in self._held_keys}
        for code, flag in ((0x10, Qt.KeyboardModifier.ShiftModifier), (0x11, Qt.KeyboardModifier.ControlModifier), (0x12, Qt.KeyboardModifier.AltModifier)):
            if code in held:
                modifiers |= flag
        return modifiers

    @staticmethod
    def _button(contact):
        return {0: Qt.MouseButton.LeftButton, 1: Qt.MouseButton.RightButton, 2: Qt.MouseButton.MiddleButton}.get(contact, Qt.MouseButton.NoButton)

    def _buttons(self):
        buttons = Qt.MouseButton.NoButton
        for contact in self._held_contacts:
            buttons |= self._button(contact)
        return buttons

    def _mouse_event(self, event_type, contact=-1):
        target = self.view.focusProxy() or self.view
        point = target.mapFrom(self.view, self._pointer)
        event = QMouseEvent(event_type, QPointF(point), QPointF(target.mapToGlobal(point)), self._button(contact), self._buttons(), self._modifiers())
        QCoreApplication.sendEvent(target, event)

    def touch_down(self, contact, x, y, pressure=1):
        mouse_contact(contact)
        bounded_int(pressure, 0, 0x7FFFFFFF, "Pressure")
        if not inside_viewport(x, y):
            raise ValueError("Pointer is outside the 1280x720 viewport")
        def send():
            self._input_target()
            if contact in self._held_contacts:
                raise RuntimeError("Mouse button is already held")
            self._pointer = QPoint(x, y)
            self._held_contacts.add(contact)
            self._mouse_event(QEvent.Type.MouseButtonPress, contact)
            return True
        return self.call_on_ui(send)

    def touch_move(self, contact, x, y, pressure=0):
        mouse_contact(contact, hover=True)
        bounded_int(pressure, 0, 0x7FFFFFFF, "Pressure")
        if not inside_viewport(x, y):
            raise ValueError("Pointer is outside the 1280x720 viewport")
        def send():
            self._input_target()
            self._pointer = QPoint(x, y)
            # Motion never implies a press. Actual held buttons determine drag.
            self._mouse_event(QEvent.Type.MouseMove)
            return True
        return self.call_on_ui(send)

    def touch_up(self, contact):
        mouse_contact(contact)
        def send():
            self._input_target()
            if contact in self._held_contacts:
                self._held_contacts.remove(contact)
                self._mouse_event(QEvent.Type.MouseButtonRelease, contact)
            return True
        return self.call_on_ui(send)

    def swipe(self, x1, y1, x2, y2, duration):
        bounded_int(duration, 0, 10000, "Swipe duration (milliseconds)")
        if not inside_viewport(x1, y1) or not inside_viewport(x2, y2):
            raise ValueError("Swipe is outside the 1280x720 viewport")
        if self._is_ui():
            raise RuntimeError("Swipe must run on the controller worker")
        self.touch_down(0, x1, y1)
        try:
            # Timing defines the gesture, not a blind wait for page state.
            steps = max(1, (duration + 15) // 16)
            start = time.monotonic()
            for step in range(1, steps + 1):
                deadline = start + duration / 1000 * step / steps
                with self._state:
                    if self._state.wait_for(lambda: self._closed, max(0, deadline - time.monotonic())):
                        self._ensure_open()
                self.touch_move(0, round(x1 + (x2 - x1) * step / steps), round(y1 + (y2 - y1) * step / steps))
            return True
        finally:
            if self.connected():
                self.touch_up(0)

    def relative_move(self, dx, dy):
        """Bounded view-local movement, NOT raw/pointer-lock camera input."""
        bounded_int(dx, -32767, 32767, "Relative x")
        bounded_int(dy, -32767, 32767, "Relative y")
        def send():
            self._input_target()
            self._pointer = QPoint(max(0, min(VIEWPORT_WIDTH - 1, self._pointer.x() + dx)), max(0, min(VIEWPORT_HEIGHT - 1, self._pointer.y() + dy)))
            self._mouse_event(QEvent.Type.MouseMove)
            return True
        return self.call_on_ui(send)

    def scroll(self, dx, dy):
        bounded_int(dx, -32767, 32767, "Scroll x")
        bounded_int(dy, -32767, 32767, "Scroll y")
        def send():
            target = self._input_target()
            point = target.mapFrom(self.view, self._pointer)
            event = QWheelEvent(QPointF(point), QPointF(target.mapToGlobal(point)), QPoint(), QPoint(-dx, -dy), self._buttons(), self._modifiers(), Qt.ScrollPhase.NoScrollPhase, False)
            QCoreApplication.sendEvent(target, event)
            return True
        return self.call_on_ui(send)

    def key(self, code, down):
        if not supported_key(code):
            raise ValueError("Supported keys: A-Z, 0-9, F1-F12, arrows, Shift/Ctrl/Alt (including left/right aliases), space, enter, escape, tab, backspace")
        def send():
            self._input_target()
            family = canonical_key(code)
            was_held = any(canonical_key(key) == family for key in self._held_keys)
            if down:
                if code in self._held_keys:
                    return True
                self._held_keys.add(code)
                if was_held:
                    return True
            else:
                if code not in self._held_keys:
                    return True
                self._held_keys.discard(code)
                if any(canonical_key(key) == family for key in self._held_keys):
                    return True
            self._key_event(code, down)
            return True
        return self.call_on_ui(send)

    def _key_event(self, code, down):
        code = canonical_key(code)
        keys = {0x08: Qt.Key.Key_Backspace, 0x09: Qt.Key.Key_Tab, 0x0D: Qt.Key.Key_Return, 0x10: Qt.Key.Key_Shift, 0x11: Qt.Key.Key_Control, 0x12: Qt.Key.Key_Alt, 0x1B: Qt.Key.Key_Escape, 0x20: Qt.Key.Key_Space, 0x25: Qt.Key.Key_Left, 0x26: Qt.Key.Key_Up, 0x27: Qt.Key.Key_Right, 0x28: Qt.Key.Key_Down}
        if 0x70 <= code <= 0x7B:
            keys[code] = int(Qt.Key.Key_F1) + code - 0x70
        held = {canonical_key(key) for key in self._held_keys}
        value = chr(code).lower() if 0x30 <= code <= 0x5A else {0x20: " ", 0x0D: "\r", 0x09: "\t", 0x08: "\b"}.get(code, "")
        if 0x10 in held:
            value = value.upper()
            if 0x30 <= code <= 0x39:
                value = ")!@#$%^&*("[code - 0x30]
        if 0x11 in held or 0x12 in held:
            value = ""
        event = QKeyEvent(QEvent.Type.KeyPress if down else QEvent.Type.KeyRelease, keys.get(code, code), self._modifiers(), value)
        QCoreApplication.sendEvent(self.view.focusProxy() or self.view, event)

    def click_key(self, code):
        if not supported_key(code):
            raise ValueError("Unsupported key code")
        if self.call_on_ui(lambda: any(canonical_key(key) == canonical_key(code) for key in self._held_keys)):
            raise RuntimeError("Cannot click a key that is already held")
        return self.key(code, True) and self.key(code, False)

    @Slot()
    def _release_inputs(self):
        # Cleanup must still work after navigation, hide/minimize or a fault.
        for contact in tuple(self._held_contacts):
            self._held_contacts.remove(contact)
            self._mouse_event(QEvent.Type.MouseButtonRelease, contact)
        # Release ordinary keys before modifiers, retaining chord semantics.
        for code in sorted(self._held_keys, key=lambda code: canonical_key(code) in (0x10, 0x11, 0x12)):
            self._held_keys.remove(code)
            if not any(canonical_key(key) == canonical_key(code) for key in self._held_keys):
                self._key_event(code, False)
        return True

    def inactive(self):
        """Release every held input without destroying this reusable browser."""
        return self.call_on_ui(self._release_inputs)

    def text(self, value):
        if not isinstance(value, str) or len(value) > 4096:
            raise ValueError("Text must be a string of at most 4096 characters")
        def send():
            target = self._input_target()
            event = QInputMethodEvent()
            event.setCommitString(value)
            QCoreApplication.sendEvent(target, event)
            return True
        return self.call_on_ui(send)

    @Slot()
    def _shutdown(self):
        if not self._closed:
            self._release_inputs()
        with self._state:
            if self._closed:
                return
            self._closed = True
            self._ready = False
            for request in self._pending:
                request.cancelled = True
                request.error = RuntimeError("Browser host closed while an operation was pending")
                request.done.set()
            self._pending.clear()
            self._state.notify_all()
        self.closed.emit()

    def close(self):
        """Idempotent, nonblocking close; closed is emitted on the UI thread."""
        with self._state:
            if self._closed:
                return
        if self._is_ui():
            self.view.close()
        else:
            self._close_requested.emit()
