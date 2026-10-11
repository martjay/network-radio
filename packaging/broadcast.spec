# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for BROADCAST.

Builds a single-folder distribution (faster start-up than one-file, and Qt's
multimedia backend needs its plugin tree intact).

Build with:  pyinstaller --clean --noconfirm broadcast.spec
"""
from __future__ import annotations

import os

from PyInstaller.utils.hooks import collect_dynamic_libs

APP_NAME = "Broadcast"
ROOT = os.path.abspath(os.path.join(os.path.dirname(SPEC), ".."))
SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))

# ---- data files -----------------------------------------------------------
# The station catalogue and the documentation shipped alongside the binary.
datas = [
    (os.path.join(ROOT, "assets", "stations.json"), "assets"),
    (os.path.join(ROOT, "README.md"), "."),
]

# ---- Qt multimedia --------------------------------------------------------
# Qt's FFmpeg backend is what actually decodes the audio streams. PyInstaller's
# PySide6 hook normally picks these up, but the multimedia plugins and the
# FFmpeg shared libraries are the ones that silently go missing, so they are
# requested explicitly.
binaries = []
binaries += collect_dynamic_libs("PySide6")

hiddenimports = [
    "PySide6.QtMultimedia",
    "PySide6.QtNetwork",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "numpy",
]

# PySide6's hook copies every Qt module it can find, and `excludes` does not
# stop DLLs (only Python imports). Qt6WebEngineCore.dll alone is ~194 MB, so
# the unwanted Qt libraries are filtered out of the binary list explicitly.
# Only Core, Gui, Widgets, Network and Multimedia are used by this app.
_KEEP_DLL_PREFIXES = (
    "Qt6Core", "Qt6Gui", "Qt6Widgets", "Qt6Network", "Qt6Multimedia",
    "Qt6Svg", "Qt6Xml", "Qt6DBus",
    # the FFmpeg backend that decodes the radio streams
    "avcodec", "avformat", "avutil", "swresample", "swscale",
    # TLS / codecs / platform support
    "libcrypto", "libssl", "libEGL", "libGLESv2", "opengl32sw", "d3dcompiler",
    "plugins_platforms", "plugins_multimedia", "plugins_imageformats",
    "plugins_tls", "plugins_networkinformation", "plugins_styles",
    "plugins_iconengines", "plugins_generic",
)
_KEEP_EXACT = {
    "python3", "python311", "python312", "python313", "VCRUNTIME140",
    "VCRUNTIME140_1", "MSVCP140", "MSVCP140_1", "MSVCP140_2",
    "ucrtbase", "concrt140",
}


def _keep_binary(entry) -> bool:
    name = os.path.basename(entry[0]).lower()
    if name.startswith("qt6webengine") or name.startswith("qtwebengine"):
        return False
    if name.startswith("qt6"):
        stem = name.split(".dll")[0].replace(".pyd", "")
        return any(stem.lower().startswith(p.lower()) for p in _KEEP_DLL_PREFIXES
                   if p.lower().startswith("qt6"))
    if name.startswith(("avcodec", "avformat", "avutil", "swresample", "swscale")):
        return True
    if any(name.startswith(p) for p in ("libcrypto", "libssl", "libegl", "libglesv2",
                                        "opengl32sw", "d3dcompiler")):
        return True
    if name.startswith(("python3", "vcruntime", "msvcp", "ucrtbase", "concrt")):
        return True
    # Qt plugin trees live under PySide6/plugins/<kind>/...
    normalised = entry[0].replace("\\", "/").lower()
    if "/plugins/" in normalised:
        kind = normalised.split("/plugins/", 1)[1].split("/", 1)[0]
        return kind in ("platforms", "multimedia", "imageformats", "tls",
                        "networkinformation", "styles", "iconengines", "generic")
    # everything else (Qt6Quick*, Qt6Qml, Qt6Designer, Qt6Pdf, Qt6Charts, ...)
    return False


_filtered = [b for b in binaries if _keep_binary(b)]
_removed_mb = sum(os.path.getsize(b[0]) for b in binaries if os.path.isfile(b[0])
                  and not _keep_binary(b)) / (1024 * 1024)
binaries = _filtered
print(f"[spec] kept {len(binaries)} binaries, filtered out ~{_removed_mb:.0f} MB of unused Qt modules")

excludes = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtQuick3D", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
    "PySide6.QtDesigner", "PySide6.QtTest", "PySide6.QtSql", "PySide6.QtPdf",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtSerialPort", "PySide6.QtSensors", "PySide6.QtWebSockets",
    "PySide6.QtWebChannel", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtSvgWidgets", "PySide6.QtHelp", "PySide6.QtUiTools",
    "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtStateMachine", "PySide6.QtTextToSpeech",
    "PySide6.QtHttpServer", "PySide6.QtSpatialAudio",
    "tkinter", "unittest", "pydoc", "doctest", "test",
    "matplotlib", "PIL", "scipy", "pandas",
]

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUI application: no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
