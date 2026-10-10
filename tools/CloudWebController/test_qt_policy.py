"""Focused pure-Python checks; no display server or MaaFramework required."""

import unittest

from qt_policy import allowed_origins, https_origin, inside_viewport, safe_load_error, supported_key, validate_webengine_environment


class QtPolicyTests(unittest.TestCase):
    def test_loading_diagnostics_omit_url_secrets(self):
        value = safe_load_error("ERR_FAILED https://example.com/private?token=secret#fragment")
        self.assertEqual(value, "ERR_FAILED [URL omitted]")
        self.assertNotIn("secret", safe_load_error("Failure ?token=secret"))
        self.assertEqual(safe_load_error("net::ERR_NETWORK_ACCESS_DENIED"), "net::ERR_NETWORK_ACCESS_DENIED")

    def test_reject_debugging_and_disabled_sandbox(self):
        validate_webengine_environment({"QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu"})
        for environment in (
            {"QTWEBENGINE_REMOTE_DEBUGGING": "9222"},
            {"QTWEBENGINE_DISABLE_SANDBOX": "1"},
            {"QTWEBENGINE_CHROMIUM_FLAGS": "--no-sandbox"},
            {"QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu-sandbox"},
            {"QTWEBENGINE_CHROMIUM_FLAGS": "--remote-debugging-port=9222"},
        ):
            with self.subTest(environment=environment), self.assertRaises(ValueError):
                validate_webengine_environment(environment)
        with self.assertRaises(ValueError):
            validate_webengine_environment({}, ["controller", "--remote-debugging-port=9222"])

    def test_https_default_port(self):
        self.assertEqual(https_origin("https://Example.COM:443/play?q=1#game"), "https://example.com")
        self.assertEqual(https_origin("https://example.com/"), "https://example.com")

    def test_reject_ambiguous_or_privileged_urls(self):
        for url in (
            "http://example.com", "file:///tmp/game", "javascript:alert(1)",
            "https://example.com:80", "https://example.com:0443", "https://user@example.com",
            "https://example.com\\@evil.com", "https://example.com\n", "https://éxample.com",
            "https://example.com.", "https://-example.com", "https://example..com",
            "https://[::1]", "https://example.com%2f.evil.com", "https://",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                https_origin(url)

    def test_explicit_additional_origins(self):
        self.assertEqual(
            allowed_origins("https://example.com/game", ["https://Login.EXAMPLE.com:443/"]),
            frozenset(("https://example.com", "https://login.example.com")),
        )
        for origin in ("https://example.com/path", "https://example.com?x=1", "https://example.com/#fragment"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                allowed_origins("https://example.com", [origin])

    def test_viewport(self):
        self.assertTrue(inside_viewport(0, 0))
        self.assertTrue(inside_viewport(1279, 719))
        for point in ((-1, 0), (1280, 0), (0, 720), (0, 0.0), (True, 0)):
            self.assertFalse(inside_viewport(*point))

    def test_bounded_key_set(self):
        for code in (ord("A"), ord("W"), ord("Z"), ord("0"), 0x25, 0x28, 0x20, 0x0D):
            self.assertTrue(supported_key(code))
        for code in (-1, 0, 0x10, 0x11, 0x12, 0x5B, 0x70, True):
            self.assertFalse(supported_key(code))


if __name__ == "__main__":
    unittest.main()
