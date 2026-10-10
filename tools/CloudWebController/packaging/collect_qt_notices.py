"""Save official QtWebEngine license pages as offline documentation, never code."""

from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
from urllib.request import urlopen

from PySide6.QtWebEngineCore import qWebEngineVersion


BASE = "https://doc-snapshots.qt.io/qtwebengine/"
INDEX = "qtwebengine-licensing.html"


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []

    def handle_data(self, data):
        self.text.append(data)


def fetch(name):
    with urlopen(BASE + name, timeout=40) as response:
        html = response.read().decode("utf-8")
    parser = PlainText()
    parser.feed(html)
    return html, "".join(parser.text)


def main():
    destination = Path(sys.argv[1])
    html, text = fetch(INDEX)
    version = qWebEngineVersion()
    if f"Qt WebEngine {version}" not in html:
        raise RuntimeError("Official notice index no longer matches the pinned QtWebEngine; update the license snapshot")
    names = sorted(set(re.findall(r'href="(qtwebengine-3rdparty-[a-z0-9-]+\.html)"', html)))
    if len(names) < 50:
        raise RuntimeError("The official QtWebEngine license index is incomplete")
    sections = [f"QtWebEngine {version} official third-party license documentation\nSource: {BASE + INDEX}\n\n{text}"]
    with ThreadPoolExecutor(max_workers=6) as executor:
        for name, (_, notice) in zip(names, executor.map(fetch, names)):
            sections.append(f"\n\nSource: {BASE + name}\n\n{notice}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(sections), encoding="utf-8")
    print(f"Saved {len(names)} official QtWebEngine notices for {version}", flush=True)


if __name__ == "__main__":
    main()
