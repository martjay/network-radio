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

excludes = [
    # Nothing here is used; dropping them keeps the build small.
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtQuick3D", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
    "PySide6.QtDesigner", "PySide6.QtTest", "PySide6.QtSql", "PySide6.QtPdf",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtSerialPort", "PySide6.QtSensors", "PySide6.QtWebSockets",
    "PySide6.QtWebChannel", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtSvgWidgets", "PySide6.QtHelp", "PySide6.QtUiTools",
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
