"""Small, Qt-independent boundaries for the embedded web controller."""

import re

VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 720


def safe_load_error(message: str) -> str:
    """Keep Chromium's error text, never a URL path/query from a login flow."""
    message = re.sub(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s<>\"']+", "[URL omitted]", message)
    message = re.sub(r"[?#][^\s<>\"']*", "[query omitted]", message)
    return " ".join(message.split())[:256]


def validate_webengine_environment(environment, arguments=()) -> None:
    """Refuse opt-outs inherited from a developer shell or Qt command line."""
    if environment.get("QTWEBENGINE_REMOTE_DEBUGGING"):
        raise ValueError("Remote debugging must not be enabled for this host")
    if environment.get("QTWEBENGINE_DISABLE_SANDBOX"):
        raise ValueError("The embedded browser sandbox must remain enabled")
    flags = environment.get("QTWEBENGINE_CHROMIUM_FLAGS", "") + " " + " ".join(arguments)
    if any(flag in flags for flag in (
        "--no-sandbox", "--disable-setuid-sandbox", "--disable-namespace-sandbox",
        "--disable-gpu-sandbox", "--remote-debugging",
    )):
        raise ValueError("Sandbox-disabling and remote-debugging flags are forbidden")


def https_origin(url: str) -> str:
    """Accept only unambiguous ASCII HTTPS URLs on the default TLS port.

    Deliberately matches the existing WebView2 prototype's narrow URL policy.
    Credentials, IP literals in brackets, IDNs, non-default ports and malformed
    host labels are rejected instead of being normalized into another origin.
    """
    if not isinstance(url, str) or not url.startswith("https://"):
        raise ValueError("A complete https:// URL is required")
    if any(ord(char) <= 32 or ord(char) >= 127 or char == "\\" for char in url):
        raise ValueError("URL must be ASCII and contain no whitespace or backslash")
    authority = re.split(r"[/?#]", url[8:], maxsplit=1)[0]
    host = authority.removesuffix(":443")
    if not host or len(host) > 253:
        raise ValueError("Invalid HTTPS host")
    for label in host.split("."):
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label):
            raise ValueError("Only ASCII DNS hosts and HTTPS port 443 are supported")
    return "https://" + host.lower()


def allowed_origins(initial_url: str, additional=()) -> frozenset[str]:
    origins = {https_origin(initial_url)}
    for value in additional:
        origin = https_origin(value)
        if value.rstrip("/").lower() not in (origin, origin + ":443"):
            raise ValueError("Additional origins must not contain a path, query or fragment")
        origins.add(origin)
    return frozenset(origins)


def inside_viewport(x: int, y: int) -> bool:
    return (
        isinstance(x, int)
        and not isinstance(x, bool)
        and isinstance(y, int)
        and not isinstance(y, bool)
        and 0 <= x < VIEWPORT_WIDTH
        and 0 <= y < VIEWPORT_HEIGHT
    )


def supported_key(code: int) -> bool:
    return isinstance(code, int) and not isinstance(code, bool) and (
        0x41 <= code <= 0x5A
        or 0x30 <= code <= 0x39
        or 0x25 <= code <= 0x28
        or code in (0x08, 0x09, 0x0D, 0x1B, 0x20)
    )
