"""Keep the portable build's Maa runtime inside its replaceable DLL directory."""

import os
from pathlib import Path
import sys


if sys.platform == "win32" and getattr(sys, "frozen", False):
    _maa_bin = Path(sys._MEIPASS) / "maa" / "bin"
    os.environ["MAAFW_BINARY_PATH"] = str(_maa_bin)
    # Keep the directory handle alive for delayed native plugin loads.
    _maa_dll_directory = os.add_dll_directory(str(_maa_bin))
