"""Application icon.

The window icon, taskbar icon and tray icon all come from one source: the
broadcast-tower mark already used in the title bar. It is rasterised at every
size Windows asks for so it stays sharp on high-DPI displays, and written to a
multi-resolution .ico for the executable.
"""
from __future__ import annotations

import os
import struct

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap

from . import icons, theme

# Sizes Windows uses for window, taskbar, Alt-Tab, tray and Explorer.
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)

_icon_cache: QIcon | None = None
_ico_written: str = ""


def app_icon() -> QIcon:
    """The application icon, cached. Used for the window and taskbar."""
    global _icon_cache
    if _icon_cache is not None:
        return _icon_cache

    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(_render(size), QIcon.Mode.Normal, QIcon.State.Off)
    # A muted variant for the disabled state, so menus and dialogs look right.
    for size in (16, 32, 48):
        icon.addPixmap(_render(size, color=theme.TEXT_FAINT),
                       QIcon.Mode.Disabled, QIcon.State.Off)
    _icon_cache = icon
    return icon


def _render(size: int, color: str = theme.ACCENT) -> QPixmap:
    """Rasterise the brand mark at `size` with an opaque, rounded backdrop.

    The title-bar mark is drawn on transparency, which looks thin in a taskbar
    or tray. This adds the product's own dark panel behind it so the icon reads
    at 16 px.
    """
    dpr = 1
    pm = QPixmap(size * dpr, size * dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    pad = max(1.0, size * 0.02)
    radius = size * 0.22
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(theme.c("#11151a"))
    p.drawRoundedRect(int(pad), int(pad), int(size - 2 * pad), int(size - 2 * pad),
                      radius, radius)

    # Inner hairline so the tile does not disappear against a dark taskbar.
    if size >= 32:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(theme.c(theme.STROKE_STRONG))
        p.drawRoundedRect(int(pad) + 0.5, int(pad) + 0.5,
                          int(size - 2 * pad) - 1, int(size - 2 * pad) - 1,
                          radius, radius)

    # The mark itself, inset from the tile edge.
    inset = size * 0.13
    mark = icons.brand_pixmap(int(size - 2 * inset), color, dpr=1)
    p.drawPixmap(int(inset), int(inset), mark)
    p.end()

    pm.setDevicePixelRatio(dpr)
    return pm


_tray_icon_cache: dict[str, QIcon] = {}


def tray_icon(color: str = theme.ACCENT) -> QIcon:
    """Tray icons are shown small, so they use a tighter inset.

    The colour is cached per variant so the tray can switch between the
    "playing" (accent) and "idle" (muted) marks without re-rasterising.
    """
    cached = _tray_icon_cache.get(color)
    if cached is not None:
        return cached
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        mark = icons.brand_pixmap(size, color, dpr=1)
        p.drawPixmap(0, 0, mark)
        p.end()
        icon.addPixmap(pm, QIcon.Mode.Normal, QIcon.State.Off)
    _tray_icon_cache[color] = icon
    return icon


# --------------------------------------------------------------------------- #
#  .ico writer
# --------------------------------------------------------------------------- #
def _png_bytes(size: int) -> bytes:
    """Encode one icon size as PNG."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    image: QImage = _render(size).toImage().convertToFormat(
        QImage.Format.Format_ARGB32)
    # Keep the QByteArray alive: QBuffer only borrows it, and letting the
    # temporary be collected while the buffer is open crashes the process.
    store = QByteArray()
    buf = QBuffer(store)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buf, "PNG"):
        buf.close()
        raise RuntimeError(f"could not encode {size}px icon as PNG")
    buf.close()
    return bytes(store)


def write_ico(path: str, sizes=ICON_SIZES) -> str:
    """Write a multi-resolution .ico file.

    Each entry is stored as PNG, which Windows Vista and later read directly
    and which keeps the 256 px frame small. Qt cannot write .ico, so the
    container is assembled here.
    """
    entries = []
    for size in sorted(set(sizes)):
        entries.append((size, _png_bytes(size)))

    header = struct.pack("<HHH", 0, 1, len(entries))
    directory = b""
    payload = b""
    offset = len(header) + 16 * len(entries)

    for size, data in entries:
        # 0 means 256 in the ICO format.
        dim = 0 if size >= 256 else size
        directory += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32,
                                 len(data), offset)
        payload += data
        offset += len(data)

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(header + directory + payload)
    return path


def ensure_ico(path: str) -> str:
    """Write the .ico if it is missing or stale. Returns its path."""
    global _ico_written
    if _ico_written == path and os.path.isfile(path):
        return path
    write_ico(path)
    _ico_written = path
    return path


def set_taskbar_identity() -> None:
    """Give the process its own taskbar identity on Windows.

    Without an explicit AppUserModelID, Windows groups a frozen build under the
    host executable and shows the generic Python icon in the taskbar instead of
    the application's own.
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "martjay.Broadcast.NetworkRadio.1"
        )
    except Exception:  # noqa: BLE001
        pass


def save_preview(directory: str) -> list[str]:
    """Write PNG previews of the icon at several sizes (for the docs)."""
    os.makedirs(directory, exist_ok=True)
    out = []
    for size in (16, 32, 64, 128, 256):
        p = os.path.join(directory, f"icon-{size}.png")
        _render(size).save(p)
        out.append(p)
    return out
