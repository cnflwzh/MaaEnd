# Build on Windows x64 with the pinned packaging requirements.
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

packaging = Path(SPECPATH)
source = packaging.parent
maa_data, maa_binaries, maa_imports = collect_all("maa")

# PyInstaller's PySide6.QtWebEngineCore hook collects QtWebEngineProcess,
# resources, locales and the required Qt plugins. Do not collect all PySide6:
# unrelated Qt modules make the portable archive unnecessarily large.
a = Analysis(
    [str(source / "qt_launcher.py")],
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
    name="MaaEnd-CloudWeb-Prototype",
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
    name="MaaEnd-CloudWeb-Prototype",
)
