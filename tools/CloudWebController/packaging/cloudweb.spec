# Build on Windows x64 with the pinned packaging requirements.
from pathlib import Path
import os
import sys

from PyInstaller.utils.hooks import collect_all

# Resolve native dependencies from this Python environment and Windows only.
# An unrelated tool on PATH can provide an incompatible same-named ICU DLL;
# collecting it shadows Windows ICU and breaks QtCore in the frozen program.
windows = Path(os.environ["SystemRoot"])
os.environ["PATH"] = os.pathsep.join(
    str(path) for path in (Path(sys.prefix), Path(sys.base_prefix), windows / "System32", windows)
)

packaging = Path(SPECPATH)
source = packaging.parent
maa_data, maa_binaries, maa_imports = collect_all("maa")

# PyInstaller's PySide6.QtWebEngineCore hook collects QtWebEngineProcess,
# resources, locales and the required Qt plugins. Do not collect all PySide6:
# unrelated Qt modules make the portable archive unnecessarily large.
a = Analysis(
    [str(source / "host_main.py")],
    pathex=[str(source)],
    binaries=maa_binaries,
    datas=[(str(source / "fixture.html"), ".")] + maa_data,
    hiddenimports=maa_imports,
    runtime_hooks=[str(packaging / "rthook_maa.py")],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CloudWebHost",
    console=True,
    debug=False,
    strip=False,
    upx=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="CloudWebHost",
)
