"""Vector icon set drawn programmatically with QPainter.

Everything is line art on a 24x24 logical grid, stroked with a 1.7px round pen
so the icons stay crisp at any DPI and match the interface weight. No font
glyphs and no emoji are used anywhere in this application.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

from . import theme

_CACHE: dict[tuple, QIcon] = {}

GRID = 24.0


# --------------------------------------------------------------------------- #
#  primitives
# --------------------------------------------------------------------------- #
def _poly(*pts: tuple[float, float]) -> QPolygonF:
    return QPolygonF([QPointF(x, y) for x, y in pts])


def _tri_right(p: QPainter, x: float = 8.0, y: float = 5.0, w: float = 11.0, h: float = 14.0) -> None:
    p.drawPolygon(_poly((x, y), (x + w, y + h / 2), (x, y + h)))


def _tri_left(p: QPainter, x: float = 16.0, y: float = 5.0, w: float = 11.0, h: float = 14.0) -> None:
    p.drawPolygon(_poly((x, y), (x - w, y + h / 2), (x, y + h)))


# --------------------------------------------------------------------------- #
#  drawings
# --------------------------------------------------------------------------- #
def _play(p: QPainter) -> None:
    p.setBrush(p.pen().color())
    _tri_right(p, 8.0, 5.2, 11.0, 13.6)


def _pause(p: QPainter) -> None:
    p.setBrush(p.pen().color())
    p.drawRoundedRect(QRectF(8.0, 5.5, 3.2, 13.0), 1.0, 1.0)
    p.drawRoundedRect(QRectF(13.0, 5.5, 3.2, 13.0), 1.0, 1.0)


def _stop(p: QPainter) -> None:
    p.setBrush(p.pen().color())
    p.drawRoundedRect(QRectF(7.0, 7.0, 10.0, 10.0), 1.5, 1.5)


def _prev(p: QPainter) -> None:
    p.setBrush(p.pen().color())
    p.drawRoundedRect(QRectF(5.5, 5.5, 2.6, 13.0), 1.0, 1.0)
    _tri_left(p, 19.0, 5.5, 10.0, 13.0)


def _next(p: QPainter) -> None:
    p.setBrush(p.pen().color())
    p.drawRoundedRect(QRectF(15.9, 5.5, 2.6, 13.0), 1.0, 1.0)
    _tri_right(p, 5.0, 5.5, 10.0, 13.0)


def _record(p: QPainter) -> None:
    p.setBrush(p.pen().color())
    p.drawEllipse(QPointF(12.0, 12.0), 6.0, 6.0)


def _record_ring(p: QPainter) -> None:
    p.drawEllipse(QPointF(12.0, 12.0), 7.6, 7.6)
    p.setBrush(p.pen().color())
    p.drawEllipse(QPointF(12.0, 12.0), 3.6, 3.6)


def _volume(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(4.5, 9.5)
    path.lineTo(8.0, 9.5)
    path.lineTo(12.0, 5.5)
    path.lineTo(12.0, 18.5)
    path.lineTo(8.0, 14.5)
    path.lineTo(4.5, 14.5)
    path.closeSubpath()
    p.setBrush(p.pen().color())
    p.drawPath(path)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(11.0, 7.5, 7.0, 9.0), -60 * 16, 120 * 16)
    p.drawArc(QRectF(12.5, 4.5, 9.5, 15.0), -55 * 16, 110 * 16)


def _volume_low(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(4.5, 9.5)
    path.lineTo(8.0, 9.5)
    path.lineTo(12.0, 5.5)
    path.lineTo(12.0, 18.5)
    path.lineTo(8.0, 14.5)
    path.lineTo(4.5, 14.5)
    path.closeSubpath()
    p.setBrush(p.pen().color())
    p.drawPath(path)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(11.0, 7.5, 7.0, 9.0), -60 * 16, 120 * 16)


def _mute(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(3.5, 9.5)
    path.lineTo(7.0, 9.5)
    path.lineTo(10.5, 5.5)
    path.lineTo(10.5, 18.5)
    path.lineTo(7.0, 14.5)
    path.lineTo(3.5, 14.5)
    path.closeSubpath()
    p.setBrush(p.pen().color())
    p.drawPath(path)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(14.0, 9.0), QPointF(20.0, 15.0))
    p.drawLine(QPointF(20.0, 9.0), QPointF(14.0, 15.0))


def _search(p: QPainter) -> None:
    p.drawEllipse(QPointF(10.8, 10.8), 5.8, 5.8)
    p.drawLine(QPointF(15.2, 15.2), QPointF(20.0, 20.0))


def _heart(p: QPainter, filled: bool = False) -> None:
    path = QPainterPath()
    path.moveTo(12.0, 19.6)
    path.cubicTo(3.2, 13.4, 3.0, 8.4, 5.6, 6.2)
    path.cubicTo(8.0, 4.2, 10.9, 5.3, 12.0, 7.6)
    path.cubicTo(13.1, 5.3, 16.0, 4.2, 18.4, 6.2)
    path.cubicTo(21.0, 8.4, 20.8, 13.4, 12.0, 19.6)
    if filled:
        p.setBrush(p.pen().color())
    p.drawPath(path)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _heart_filled(p: QPainter) -> None:
    _heart(p, True)


def _plus(p: QPainter) -> None:
    p.drawLine(QPointF(12.0, 5.0), QPointF(12.0, 19.0))
    p.drawLine(QPointF(5.0, 12.0), QPointF(19.0, 12.0))


def _folder(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(3.5, 6.5)
    path.lineTo(9.0, 6.5)
    path.lineTo(11.0, 9.0)
    path.lineTo(20.5, 9.0)
    path.lineTo(20.5, 18.0)
    path.lineTo(3.5, 18.0)
    path.closeSubpath()
    p.drawPath(path)


def _list(p: QPainter) -> None:
    for y in (7.5, 12.0, 16.5):
        p.setBrush(p.pen().color())
        p.drawEllipse(QPointF(5.6, y), 1.15, 1.15)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(9.5, y), QPointF(19.5, y))


def _equalizer(p: QPainter) -> None:
    p.setBrush(p.pen().color())
    for x, h in ((5.5, 7.0), (9.5, 12.5), (13.5, 5.0), (17.5, 10.0)):
        p.drawRoundedRect(QRectF(x, 12.0 - h / 2, 2.4, h), 1.1, 1.1)


def _trash(p: QPainter) -> None:
    p.drawLine(QPointF(4.5, 7.0), QPointF(19.5, 7.0))
    p.drawLine(QPointF(9.5, 7.0), QPointF(9.5, 4.8))
    p.drawLine(QPointF(14.5, 7.0), QPointF(14.5, 4.8))
    p.drawLine(QPointF(9.5, 4.8), QPointF(14.5, 4.8))
    path = QPainterPath()
    path.moveTo(6.5, 7.0)
    path.lineTo(7.6, 19.5)
    path.lineTo(16.4, 19.5)
    path.lineTo(17.5, 7.0)
    p.drawPath(path)
    p.drawLine(QPointF(10.6, 10.0), QPointF(10.9, 16.6))
    p.drawLine(QPointF(13.4, 10.0), QPointF(13.1, 16.6))


def _sliders(p: QPainter) -> None:
    for y, kx in ((7.5, 9.0), (12.0, 15.0), (16.5, 7.0)):
        p.drawLine(QPointF(4.5, y), QPointF(19.5, y))
        p.setBrush(QBrush(theme.c(theme.BG_APP)))
        p.drawEllipse(QPointF(kx, y), 2.5, 2.5)
        p.setBrush(Qt.BrushStyle.NoBrush)


def _gear(p: QPainter) -> None:
    """Eight-tooth cog with a clear hub — reads as Settings at 16px."""
    cx, cy = 12.0, 12.0
    n = 8
    r_tip, r_valley, r_hub = 8.6, 6.15, 2.55
    path = QPainterPath()
    started = False
    for i in range(n):
        a = -math.pi / 2 + i * (2 * math.pi / n)
        span = 2 * math.pi / n
        pts = (
            (a - span * 0.18, r_valley),
            (a - span * 0.11, r_tip),
            (a + span * 0.11, r_tip),
            (a + span * 0.18, r_valley),
        )
        for t, r in pts:
            x = cx + r * math.cos(t)
            y = cy + r * math.sin(t)
            if not started:
                path.moveTo(x, y)
                started = True
            else:
                path.lineTo(x, y)
    path.closeSubpath()
    p.drawPath(path)
    p.drawEllipse(QPointF(cx, cy), r_hub, r_hub)


def _chevron_down(p: QPainter) -> None:
    p.drawPolyline(_poly((6.0, 9.5), (12.0, 15.0), (18.0, 9.5)))


def _chevron_up(p: QPainter) -> None:
    p.drawPolyline(_poly((6.0, 14.5), (12.0, 9.0), (18.0, 14.5)))


def _chevron_left(p: QPainter) -> None:
    p.drawPolyline(_poly((15.0, 5.0), (9.0, 12.0), (15.0, 19.0)))


def _chevron_right(p: QPainter) -> None:
    p.drawPolyline(_poly((9.0, 5.0), (15.0, 12.0), (9.0, 19.0)))


def _close(p: QPainter) -> None:
    p.drawLine(QPointF(6.5, 6.5), QPointF(17.5, 17.5))
    p.drawLine(QPointF(17.5, 6.5), QPointF(6.5, 17.5))


def _minimize(p: QPainter) -> None:
    p.drawLine(QPointF(6.0, 12.5), QPointF(18.0, 12.5))


def _maximize(p: QPainter) -> None:
    p.drawRect(QRectF(6.5, 6.5, 11.0, 11.0))


def _restore(p: QPainter) -> None:
    p.drawRect(QRectF(5.0, 8.0, 10.5, 10.5))
    p.drawPolyline(_poly((8.5, 8.0), (8.5, 5.5), (19.0, 5.5), (19.0, 16.0), (16.0, 16.0)))


def _power(p: QPainter) -> None:
    p.drawArc(QRectF(5.0, 5.0, 14.0, 14.0), 60 * 16, 240 * 16)
    p.drawLine(QPointF(12.0, 3.5), QPointF(12.0, 11.5))


def _globe(p: QPainter) -> None:
    p.drawEllipse(QPointF(12.0, 12.0), 8.0, 8.0)
    p.drawEllipse(QPointF(12.0, 12.0), 3.6, 8.0)
    p.drawLine(QPointF(4.0, 12.0), QPointF(20.0, 12.0))
    p.drawArc(QRectF(4.0, 6.6, 16.0, 10.8), 0, 180 * 16)


def _signal(p: QPainter) -> None:
    p.setBrush(p.pen().color())
    for x, h in ((5.5, 4.0), (10.0, 7.5), (14.5, 11.0), (19.0, 14.5)):
        p.drawRoundedRect(QRectF(x - 1.2, 19.0 - h, 2.4, h), 1.0, 1.0)


def _disc(p: QPainter) -> None:
    p.drawEllipse(QPointF(12.0, 12.0), 8.4, 8.4)
    p.drawEllipse(QPointF(12.0, 12.0), 4.6, 4.6)
    p.setBrush(p.pen().color())
    p.drawEllipse(QPointF(12.0, 12.0), 1.3, 1.3)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _headphones(p: QPainter) -> None:
    p.drawArc(QRectF(4.0, 4.5, 16.0, 16.0), 0, 180 * 16)
    p.setBrush(p.pen().color())
    p.drawRoundedRect(QRectF(4.0, 12.0, 3.6, 6.5), 1.4, 1.4)
    p.drawRoundedRect(QRectF(16.4, 12.0, 3.6, 6.5), 1.4, 1.4)


def _star(p: QPainter, filled: bool = False) -> None:
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        r = 8.2 if i % 2 == 0 else 3.6
        pts.append((12.0 + r * math.cos(ang), 12.0 + r * math.sin(ang)))
    if filled:
        p.setBrush(p.pen().color())
    p.drawPolygon(_poly(*pts))
    p.setBrush(Qt.BrushStyle.NoBrush)


def _check(p: QPainter) -> None:
    p.drawPolyline(_poly((5.0, 12.5), (10.0, 17.5), (19.0, 6.5)))


def _download(p: QPainter) -> None:
    p.drawLine(QPointF(12.0, 4.0), QPointF(12.0, 14.5))
    p.drawPolyline(_poly((7.5, 10.5), (12.0, 15.0), (16.5, 10.5)))
    p.drawPolyline(_poly((4.5, 16.5), (4.5, 19.5), (19.5, 19.5), (19.5, 16.5)))


def _refresh(p: QPainter) -> None:
    p.drawArc(QRectF(4.5, 4.5, 15.0, 15.0), 40 * 16, 280 * 16)
    p.setBrush(p.pen().color())
    p.drawPolygon(_poly((16.2, 3.4), (20.0, 6.4), (15.6, 7.6)))


def _tower(p: QPainter) -> None:
    p.drawLine(QPointF(12.0, 20.0), QPointF(12.0, 12.0))
    p.setBrush(p.pen().color())
    p.drawEllipse(QPointF(12.0, 9.6), 2.1, 2.1)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(7.0, 4.0, 10.0, 10.0), 30 * 16, 120 * 16)
    p.drawArc(QRectF(3.6, 1.4, 16.8, 16.8), 34 * 16, 112 * 16)
    p.drawLine(QPointF(8.0, 20.0), QPointF(16.0, 20.0))


def _clock(p: QPainter) -> None:
    p.drawEllipse(QPointF(12.0, 12.0), 8.2, 8.2)
    p.drawLine(QPointF(12.0, 7.0), QPointF(12.0, 12.4))
    p.drawLine(QPointF(12.0, 12.4), QPointF(15.8, 14.4))


def _waveform(p: QPainter) -> None:
    p.setBrush(p.pen().color())
    for x, h in ((4.5, 3.0), (7.5, 7.0), (10.5, 12.0), (13.5, 8.0), (16.5, 15.0), (19.5, 5.0)):
        p.drawRoundedRect(QRectF(x - 1.0, 12.0 - h / 2, 2.0, h), 1.0, 1.0)


def _bookmark(p: QPainter, filled: bool = False) -> None:
    path = QPainterPath()
    path.moveTo(6.5, 4.5)
    path.lineTo(17.5, 4.5)
    path.lineTo(17.5, 19.5)
    path.lineTo(12.0, 14.8)
    path.lineTo(6.5, 19.5)
    path.closeSubpath()
    if filled:
        p.setBrush(p.pen().color())
    p.drawPath(path)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _info(p: QPainter) -> None:
    p.drawEllipse(QPointF(12.0, 12.0), 8.2, 8.2)
    p.setBrush(p.pen().color())
    p.drawEllipse(QPointF(12.0, 8.2), 1.1, 1.1)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(12.0, 11.0), QPointF(12.0, 16.4))


def _grid(p: QPainter) -> None:
    for x in (4.5, 13.0):
        for y in (4.5, 13.0):
            p.drawRect(QRectF(x, y, 6.5, 6.5))


def _edit(p: QPainter) -> None:
    p.drawLine(QPointF(5.0, 19.0), QPointF(7.5, 13.0))
    p.drawLine(QPointF(7.5, 13.0), QPointF(15.5, 5.0))
    p.drawLine(QPointF(15.5, 5.0), QPointF(19.0, 8.5))
    p.drawLine(QPointF(19.0, 8.5), QPointF(11.0, 16.5))
    p.drawLine(QPointF(11.0, 16.5), QPointF(5.0, 19.0))


def _external(p: QPainter) -> None:
    p.drawPolyline(_poly((13.5, 5.0), (19.0, 5.0), (19.0, 10.5)))
    p.drawLine(QPointF(19.0, 5.0), QPointF(11.0, 13.0))
    p.drawPolyline(_poly((16.0, 14.0), (16.0, 19.0), (5.0, 19.0), (5.0, 8.0), (10.0, 8.0)))


def _chev_left(p: QPainter) -> None:
    p.drawPolyline(_poly((14.2, 6.2), (8.6, 12.0), (14.2, 17.8)))


def _chev_right(p: QPainter) -> None:
    p.drawPolyline(_poly((9.8, 6.2), (15.4, 12.0), (9.8, 17.8)))


def _chev_first(p: QPainter) -> None:
    p.drawLine(QPointF(7.2, 6.2), QPointF(7.2, 17.8))
    p.drawPolyline(_poly((17.2, 6.2), (11.4, 12.0), (17.2, 17.8)))


def _chev_last(p: QPainter) -> None:
    p.drawLine(QPointF(16.8, 6.2), QPointF(16.8, 17.8))
    p.drawPolyline(_poly((6.8, 6.2), (12.6, 12.0), (6.8, 17.8)))


def _sleep(p: QPainter) -> None:
    p.drawArc(QRectF(4.5, 4.5, 15.0, 15.0), 90 * 16, 180 * 16)
    p.drawArc(QRectF(7.0, 4.5, 12.5, 15.0), 90 * 16, 180 * 16)
    p.drawLine(QPointF(12.0, 4.5), QPointF(12.0, 8.5))


DRAW = {
    "play": _play,
    "pause": _pause,
    "stop": _stop,
    "prev": _prev,
    "next": _next,
    "record": _record,
    "record_ring": _record_ring,
    "volume": _volume,
    "volume_low": _volume_low,
    "mute": _mute,
    "search": _search,
    "heart": _heart,
    "heart_filled": _heart_filled,
    "plus": _plus,
    "folder": _folder,
    "list": _list,
    "equalizer": _equalizer,
    "trash": _trash,
    "sliders": _sliders,
    "gear": _gear,
    "chevron_down": _chevron_down,
    "chevron_up": _chevron_up,
    "chevron_left": _chevron_left,
    "chevron_right": _chevron_right,
    "close": _close,
    "minimize": _minimize,
    "maximize": _maximize,
    "restore": _restore,
    "power": _power,
    "globe": _globe,
    "signal": _signal,
    "disc": _disc,
    "headphones": _headphones,
    "star": _star,
    "star_filled": lambda p: _star(p, True),
    "check": _check,
    "download": _download,
    "refresh": _refresh,
    "tower": _tower,
    "clock": _clock,
    "waveform": _waveform,
    "bookmark": _bookmark,
    "bookmark_filled": lambda p: _bookmark(p, True),
    "info": _info,
    "grid": _grid,
    "edit": _edit,
    "external": _external,
    "sleep": _sleep,
    "chev_left": _chev_left,
    "chev_right": _chev_right,
    "chev_first": _chev_first,
    "chev_last": _chev_last,
}


# --------------------------------------------------------------------------- #
#  public API
# --------------------------------------------------------------------------- #
def pixmap(name: str, size: int = 16, color: str = theme.TEXT_DIM, dpr: int = 2) -> QPixmap:
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.scale(size * dpr / GRID, size * dpr / GRID)
    pen = QPen(QColor(color), 1.7)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    fn = DRAW.get(name)
    if fn is not None:
        fn(p)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, size: int = 16, color: str = theme.TEXT_DIM) -> QIcon:
    key = (name, size, color)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    ic = QIcon()
    for state, col in (
        (QIcon.Mode.Normal, color),
        (QIcon.Mode.Active, theme.TEXT),
        (QIcon.Mode.Selected, theme.TEXT),
        (QIcon.Mode.Disabled, theme.TEXT_FAINT),
    ):
        pm = pixmap(name, size, col)
        ic.addPixmap(pm, state, QIcon.State.Off)
    _CACHE[key] = ic
    return ic


def brand_pixmap(size: int = 22, color: str = theme.ACCENT, dpr: int = 2) -> QPixmap:
    """The application mark: a broadcast tower inside a signal ring."""
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.scale(size * dpr / GRID, size * dpr / GRID)

    col = QColor(color)
    pen = QPen(col, 1.9)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(12.0, 12.0), 9.0, 9.0)

    pen2 = QPen(col, 1.7)
    pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen2)
    p.drawLine(QPointF(12.0, 18.4), QPointF(12.0, 11.6))
    p.drawLine(QPointF(9.4, 18.4), QPointF(14.6, 18.4))
    p.setBrush(col)
    p.drawEllipse(QPointF(12.0, 9.2), 2.2, 2.2)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(6.6, 3.4, 10.8, 10.8), 28 * 16, 124 * 16)
    p.drawArc(QRectF(3.9, 0.7, 16.2, 16.2), 32 * 16, 116 * 16)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm
