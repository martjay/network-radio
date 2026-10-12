"""Custom widgets.

Everything here is drawn with QPainter rather than assembled from stock
controls, which is what keeps the interface from looking like a default Qt
application.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QSlider,
    QVBoxLayout, QWidget,
)

from . import icons, theme


# --------------------------------------------------------------------------- #
#  small helpers
# --------------------------------------------------------------------------- #
def hline(color: str = theme.STROKE, height: int = 1) -> QFrame:
    f = QFrame()
    f.setObjectName("HLine")
    f.setFixedHeight(height)
    f.setStyleSheet(f"background: {color}; border: none;")
    return f


def vline(color: str = theme.STROKE, width: int = 1) -> QFrame:
    f = QFrame()
    f.setFixedWidth(width)
    f.setStyleSheet(f"background: {color}; border: none;")
    return f


def section_label(text: str, spacing: float = 1.5) -> QLabel:
    lab = QLabel(text.upper())
    lab.setObjectName("SideHeader")
    lab.setFont(theme.label_font(9, 700, spacing))
    return lab


class ElideLabel(QLabel):
    """A label that elides its text to the available width."""

    def __init__(self, text: str = "", mode=Qt.TextElideMode.ElideRight, parent=None):
        super().__init__(parent)
        self._full = text
        self._mode = mode
        # Ignored + a tiny hint: never fight the layout with the unelided
        # string width, which used to make the now-playing bar oscillate.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(24)
        super().setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text or ""
        self.setToolTip(self._full if self._full else "")
        self._apply()

    def fullText(self) -> str:  # noqa: N802
        return self._full

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(24, super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(24, super().minimumSizeHint().height())

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._apply()

    def _apply(self) -> None:
        fm = QFontMetrics(self.font())
        avail = max(0, self.width() - 2)
        shown = self._full if avail <= 0 else fm.elidedText(self._full, self._mode, avail)
        if shown != self.text():
            super().setText(shown)


class ScrollingLabel(QWidget):
    """Marquee label: static while the text fits, gently scrolling when it does not."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self._offset = 0.0
        self._pause = 0.0
        self._font = theme.font(12, 500)
        self._color = theme.c(theme.TEXT)
        self._gap = 64
        self.setMinimumHeight(20)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._timer = QTimer(self)
        self._timer.setInterval(28)
        self._timer.timeout.connect(self._tick)

    def setText(self, text: str) -> None:  # noqa: N802
        self._text = text or ""
        self._offset = 0.0
        self._pause = 1.4
        self.setToolTip(self._text)
        self._update_timer()
        self.update()

    def text(self) -> str:
        return self._text

    def setFont(self, font: QFont) -> None:  # noqa: N802
        self._font = font
        self._update_timer()
        self.update()

    def setColor(self, color: str) -> None:  # noqa: N802
        self._color = theme.c(color)
        self.update()

    def _overflow(self) -> float:
        fm = QFontMetrics(self._font)
        return fm.horizontalAdvance(self._text) - max(0, self.width() - 2)

    def _update_timer(self) -> None:
        if self._overflow() > 0 and self.isVisible():
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            self._offset = 0.0

    def _tick(self) -> None:
        if self._overflow() <= 0:
            self._timer.stop()
            self._offset = 0.0
            self.update()
            return
        if self._pause > 0:
            self._pause -= 0.028
            return
        self._offset += 0.85
        span = QFontMetrics(self._font).horizontalAdvance(self._text) + self._gap
        if self._offset >= span:
            self._offset = 0.0
            self._pause = 1.2
        self.update()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._update_timer()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._update_timer()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setFont(self._font)
        p.setPen(QPen(self._color))
        rect = self.rect().adjusted(0, 0, -1, 0)
        fm = QFontMetrics(self._font)
        if self._overflow() <= 0:
            p.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)
            return
        p.setClipRect(rect)
        y = rect.top() + (rect.height() + fm.ascent() - fm.descent()) // 2
        x = rect.left() - self._offset
        p.drawText(QPoint(int(x), y), self._text)
        x2 = x + fm.horizontalAdvance(self._text) + self._gap
        if x2 < rect.right():
            p.drawText(QPoint(int(x2), y), self._text)
        # fade the edges so text does not clip abruptly
        grad = QLinearGradient(rect.left(), 0, rect.left() + 22, 0)
        grad.setColorAt(0.0, theme.c(theme.BG_TITLEBAR))
        grad.setColorAt(1.0, theme.c(theme.BG_TITLEBAR, 0.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRect(QRect(rect.left(), rect.top(), 22, rect.height()))
        p.end()


# --------------------------------------------------------------------------- #
#  spectrum analyser
# --------------------------------------------------------------------------- #
class SpectrumWidget(QWidget):
    """Log-spaced FFT bar display with peak-hold caps and a reflection floor."""

    def __init__(self, bands: int = 40, parent=None):
        super().__init__(parent)
        self._bands = bands
        self._values = [0.0] * bands
        self._peaks = [0.0] * bands
        self._peak_age = [0.0] * bands
        self._active = False
        self.setMinimumHeight(76)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_values(self, values) -> None:
        vals = list(values)[: self._bands]
        if len(vals) < self._bands:
            vals += [0.0] * (self._bands - len(vals))
        self._values = [float(v) for v in vals]
        now = time.monotonic()
        for i, v in enumerate(self._values):
            if v >= self._peaks[i]:
                self._peaks[i] = v
                self._peak_age[i] = now
        self.update()

    def set_active(self, active: bool) -> None:
        self._active = active
        if not active:
            self._values = [0.0] * self._bands
            self._peaks = [0.0] * self._bands
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        base = h - 12

        # baseline + subtle horizontal guides
        p.setPen(QPen(theme.c(theme.STROKE_SOFT), 1))
        for frac in (0.25, 0.5, 0.75):
            y = int(base - base * frac)
            p.setPen(QPen(theme.c(theme.STROKE_SOFT, 0.55), 1, Qt.PenStyle.DotLine))
            p.drawLine(0, y, w, y)
        p.setPen(QPen(theme.c(theme.STROKE), 1))
        p.drawLine(0, int(base), w, int(base))

        n = self._bands
        slot = w / n
        bar_w = max(2.0, slot * 0.60)
        radius = min(2.0, bar_w / 2)

        for i, v in enumerate(self._values):
            x = i * slot + (slot - bar_w) / 2
            bh = max(1.0, v * base)
            top = base - bh
            grad = QLinearGradient(0, top, 0, base)
            grad.setColorAt(0.0, theme.c(theme.ACCENT))
            grad.setColorAt(0.55, theme.c(theme.ACCENT_DIM))
            grad.setColorAt(1.0, theme.c(theme.ACCENT_SOFT))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(grad))
            path = QPainterPath()
            path.addRoundedRect(QRectF(x, top, bar_w, bh), radius, radius)
            p.drawPath(path)

            # reflection
            p.setBrush(theme.c(theme.ACCENT, 0.13))
            p.drawRoundedRect(QRectF(x, base + 1, bar_w, min(9.0, bh * 0.28)), radius, radius)

            # peak cap
            pk = self._peaks[i]
            if pk > 0.012:
                age = time.monotonic() - self._peak_age[i]
                alpha = 0.95 if age < 1.1 else max(0.15, 0.95 - (age - 1.1) * 0.55)
                py = base - pk * base
                p.setBrush(theme.c(theme.ACCENT, alpha))
                p.drawRoundedRect(QRectF(x, py - 1.6, bar_w, 1.8), 0.9, 0.9)
        p.end()


# --------------------------------------------------------------------------- #
#  level meter
# --------------------------------------------------------------------------- #
class LevelMeter(QWidget):
    """Stereo-style peak meter with a hold marker and a clip indicator."""

    SEGMENTS = 26

    def __init__(self, parent=None):
        super().__init__(parent)
        self._level = 0.0
        self._display = 0.0
        self._hold = 0.0
        self._hold_ts = 0.0
        self.setMinimumHeight(10)
        self.setMaximumHeight(10)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._decay)
        self._timer.start()

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, float(level)))
        if self._level >= self._hold:
            self._hold = self._level
            self._hold_ts = time.monotonic()

    def _decay(self) -> None:
        target = self._level
        self._display += (target - self._display) * (0.55 if target > self._display else 0.20)
        self._level *= 0.72
        if time.monotonic() - self._hold_ts > 1.6:
            self._hold = max(0.0, self._hold - 0.012)
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        n = self.SEGMENTS
        gap = 2.0
        seg_w = max(1.5, (w - gap * (n - 1)) / n)
        lit = int(round(self._display * n))

        for i in range(n):
            x = i * (seg_w + gap)
            frac = (i + 1) / n
            if i < lit:
                if frac > 0.94:
                    col = theme.c(theme.REC)
                elif frac > 0.78:
                    col = theme.c(theme.WARN)
                else:
                    col = theme.c(theme.ACCENT)
            else:
                col = theme.c("#232a31")
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(x, 1.0, seg_w, h - 2.0), 1.2, 1.2)

        hold_x = self._hold * w
        if self._hold > 0.02:
            p.setBrush(theme.c(theme.TEXT, 0.85))
            p.drawRect(QRectF(max(0.0, hold_x - 1.0), 0.0, 2.0, h))
        p.end()


# --------------------------------------------------------------------------- #
#  generated station artwork
# --------------------------------------------------------------------------- #
class ArtTile(QWidget):
    """Deterministic generated cover art for a station.

    The pattern is derived from the station name so a given station always
    looks the same, and the palette stays inside the product's own accent
    family rather than inventing random colours.
    """

    def __init__(self, size: int = 132, parent=None):
        super().__init__(parent)
        self._size = size
        self._name = ""
        self._sub = ""
        self._playing = False
        self.setFixedSize(size, size)

    def set_station(self, name: str, sub: str = "") -> None:
        self._name = name or ""
        self._sub = sub or ""
        self.update()

    def set_playing(self, playing: bool) -> None:
        self._playing = playing
        self.update()

    def _hash(self) -> int:
        h = 2166136261
        for ch in self._name:
            h ^= ord(ch)
            h = (h * 16777619) & 0xFFFFFFFF
        return h

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        s = self._size
        rect = QRectF(0.5, 0.5, s - 1.0, s - 1.0)

        # base
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("#101317"))
        p.drawRoundedRect(rect, theme.RADIUS_LG, theme.RADIUS_LG)

        p.save()
        clip = QPainterPath()
        clip.addRoundedRect(rect, theme.RADIUS_LG, theme.RADIUS_LG)
        p.setClipPath(clip)

        h = self._hash()
        variant = h % 4

        if variant == 0:
            # concentric broadcast arcs from the lower-left
            p.setBrush(Qt.BrushStyle.NoBrush)
            for i in range(7):
                r = s * (0.28 + i * 0.20)
                p.setPen(QPen(theme.c(theme.ACCENT, max(0.05, 0.42 - i * 0.055)), 1.4))
                p.drawEllipse(QRectF(-r * 0.35, s - r * 0.65, r * 2, r * 2))
        elif variant == 1:
            # diagonal rule field
            p.setPen(QPen(theme.c(theme.ACCENT, 0.24), 1.2))
            step = max(7, s // 11)
            for i in range(-s, s * 2, step):
                p.drawLine(i, 0, i + s, s)
            p.setPen(QPen(theme.c(theme.ACCENT, 0.55), 2.0))
            p.drawLine(int(s * 0.12), int(s * 0.86), int(s * 0.88), int(s * 0.14))
        elif variant == 2:
            # waveform blocks
            p.setPen(Qt.PenStyle.NoPen)
            bars = 13
            bw = s / (bars * 1.7)
            for i in range(bars):
                t = i / (bars - 1)
                hh = (0.18 + 0.62 * abs(math.sin(t * math.pi * 1.7 + (h % 7)))) * s
                x = s * 0.09 + i * (bw * 1.7)
                p.setBrush(theme.c(theme.ACCENT, 0.20 + 0.55 * (1 - abs(t - 0.5) * 1.6)))
                p.drawRoundedRect(QRectF(x, (s - hh) / 2, bw, hh), bw / 2.4, bw / 2.4)
        else:
            # contour rings
            p.setBrush(Qt.BrushStyle.NoBrush)
            cx, cy = s * 0.5, s * 0.52
            for i in range(9):
                rr = s * (0.06 + i * 0.055)
                wob = 1.0 + 0.16 * math.sin(i * 1.3 + (h % 11))
                p.setPen(QPen(theme.c(theme.ACCENT, 0.30 - i * 0.022), 1.3))
                p.drawEllipse(QRectF(cx - rr * wob, cy - rr * 0.72, rr * 2 * wob, rr * 1.44))

        # vignette so the initials stay legible
        grad = QLinearGradient(0, s * 0.30, 0, s)
        grad.setColorAt(0.0, theme.c("#0b0d10", 0.0))
        grad.setColorAt(1.0, theme.c("#0b0d10", 0.86))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRect(QRectF(0, 0, s, s))
        p.restore()

        # initials
        initials = self._initials()
        f = theme.font(int(s * 0.30), 800, spacing=1.5)
        p.setFont(f)
        p.setPen(QPen(theme.c(theme.TEXT, 0.94)))
        p.drawText(
            QRectF(0, s * 0.30, s, s * 0.44),
            Qt.AlignmentFlag.AlignCenter, initials,
        )

        if self._sub:
            p.setFont(theme.font(max(8, int(s * 0.085)), 600, mono=True, spacing=0.6))
            p.setPen(QPen(theme.c(theme.ACCENT, 0.92)))
            p.drawText(
                QRectF(0, s * 0.735, s, s * 0.18),
                Qt.AlignmentFlag.AlignCenter, self._sub[:22],
            )

        # live badge
        if self._playing:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.c(theme.REC))
            p.drawEllipse(QRectF(s - 22, 12, 6, 6))
            p.setFont(theme.font(8, 800, spacing=1.2))
            p.setPen(QPen(theme.c(theme.REC)))
            p.drawText(QRectF(s - 62, 8, 34, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "LIVE")

        # frame
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(theme.c(theme.STROKE), 1))
        p.drawRoundedRect(rect, theme.RADIUS_LG, theme.RADIUS_LG)
        p.end()

    def _initials(self) -> str:
        name = self._name.strip()
        if not name:
            return "--"
        # CJK: first two characters
        if any("\u4e00" <= ch <= "\u9fff" for ch in name):
            cjk = [ch for ch in name if "\u4e00" <= ch <= "\u9fff"]
            return "".join(cjk[:2])
        words = [w for w in name.replace("-", " ").replace("_", " ").split() if w]
        if len(words) >= 2:
            return (words[0][0] + words[1][0]).upper()
        return name[:2].upper()


# --------------------------------------------------------------------------- #
#  buttons
# --------------------------------------------------------------------------- #
class IconButton(QPushButton):
    """Flat icon button with hover/pressed backgrounds and an optional label."""

    def __init__(self, icon_name: str, size: int = 30, icon_size: int = 16,
                 tooltip: str = "", checkable: bool = False, color: str = theme.TEXT_DIM,
                 object_name: str = "IconBtn", parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._icon_size = icon_size
        self._color = color
        self.setObjectName(object_name)
        self.setFixedSize(size, size)
        self.setIconSize(QSize(icon_size, icon_size))
        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)
        self._refresh()

    def set_icon_name(self, name: str, color: str | None = None) -> None:
        self._icon_name = name
        if color:
            self._color = color
        self._refresh()

    def _refresh(self) -> None:
        self.setIcon(icons.icon(self._icon_name, self._icon_size, self._color))


class TransportButton(QPushButton):
    """Large transport control with a painted glyph and a hover ring."""

    def __init__(self, icon_name: str, size: int = 40, icon_size: int = 18,
                 tooltip: str = "", primary: bool = False, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._icon_size = icon_size
        self._primary = primary
        self.setObjectName("PlayBtn" if primary else "Transport")
        self.setFixedSize(size, size)
        self.setIconSize(QSize(icon_size, icon_size))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)
        self._refresh()

    def set_icon_name(self, name: str) -> None:
        self._icon_name = name
        self._refresh()

    def _refresh(self) -> None:
        col = "#06222a" if self._primary else theme.TEXT
        self.setIcon(icons.icon(self._icon_name, self._icon_size, col))


class Chip(QPushButton):
    """Compact filter chip."""

    def __init__(self, text: str, tooltip: str = "", checkable: bool = True, parent=None):
        super().__init__(text, parent)
        self.setObjectName("Chip")
        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)
        self.setFont(theme.font(11, 500))


class TextButton(QPushButton):
    def __init__(self, text: str, icon_name: str = "", primary: bool = False,
                 tooltip: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("Primary" if primary else "Ghost")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(theme.font(12, 600))
        if icon_name:
            col = "#06222a" if primary else theme.TEXT_DIM
            self.setIcon(icons.icon(icon_name, 14, col))
            self.setIconSize(QSize(14, 14))
        if tooltip:
            self.setToolTip(tooltip)


# --------------------------------------------------------------------------- #
#  search field
# --------------------------------------------------------------------------- #
class SearchField(QLineEdit):
    def __init__(self, placeholder: str = "搜索电台、国家或标签", parent=None):
        super().__init__(parent)
        self.setObjectName("Search")
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.setFont(theme.font(12, 400))
        self.setFixedHeight(28)
        self.addAction(icons.icon("search", 13, theme.TEXT_MUTED), QLineEdit.ActionPosition.LeadingPosition)


# --------------------------------------------------------------------------- #
#  now-playing header inside the right panel
# --------------------------------------------------------------------------- #
class PlayingIndicator(QWidget):
    """Three-bar equaliser animation shown next to the station being played."""

    def __init__(self, parent=None, bars: int = 3, color: str = theme.ACCENT):
        super().__init__(parent)
        self._bars = bars
        self._color = color
        self._phase = 0.0
        self._active = False
        self.setFixedSize(bars * 4 + 2, 14)
        self._timer = QTimer(self)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self._tick)

    def set_active(self, active: bool) -> None:
        self._active = active
        if active:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._phase += 0.42
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        h = self.height()
        for i in range(self._bars):
            if self._active:
                v = 0.30 + 0.70 * abs(math.sin(self._phase + i * 1.05))
            else:
                v = 0.22
            bh = max(3.0, v * (h - 2))
            x = i * 4 + 1
            p.setBrush(theme.c(self._color, 0.95 if self._active else 0.35))
            p.drawRoundedRect(QRectF(x, h - bh, 2.6, bh), 1.2, 1.2)
        p.end()


# --------------------------------------------------------------------------- #
#  labelled stat row
# --------------------------------------------------------------------------- #
class StatRow(QWidget):
    """A micro-label above a monospaced value, used across the info panel."""

    def __init__(self, label: str, value: str = "--", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self._label = QLabel(label.upper())
        self._label.setObjectName("CardLabel")
        self._label.setFont(theme.label_font(8, 700, 1.2))
        self._value = ElideLabel(value)
        self._value.setObjectName("CardValue")
        self._value.setFont(theme.font(11, 500, mono=True))
        lay.addWidget(self._label)
        lay.addWidget(self._value)

    def set_value(self, text: str, dim: bool = False) -> None:
        self._value.setObjectName("CardValueDim" if dim else "CardValue")
        self._value.setStyleSheet(
            f"color: {theme.TEXT_MUTED if dim else theme.TEXT};"
            f"font-family: '{theme.mono_family()}'; font-size: 11px;"
        )
        self._value.setText(text or "--")


# --------------------------------------------------------------------------- #
#  custom title bar
# --------------------------------------------------------------------------- #
class TitleBar(QWidget):
    """Frameless window chrome: mark, live now-playing readout, window buttons."""

    minimize_clicked = Signal()
    maximize_clicked = Signal()
    close_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setFixedHeight(theme.TITLEBAR_H)
        self._drag_offset: QPoint | None = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 0, 0)
        lay.setSpacing(10)

        mark = QLabel()
        mark.setPixmap(icons.brand_pixmap(20, theme.ACCENT))
        mark.setFixedSize(20, 20)
        lay.addWidget(mark)

        brand = QLabel("BROADCAST")
        brand.setObjectName("BrandMark")
        brand.setFont(theme.font(13, 800, spacing=2.6))
        lay.addWidget(brand)

        sub = QLabel("NETWORK RADIO")
        sub.setObjectName("BrandSub")
        sub.setFont(theme.font(10, 600, spacing=1.4))
        lay.addWidget(sub)

        lay.addSpacing(14)
        lay.addWidget(vline(theme.STROKE, 1))

        self._indicator = PlayingIndicator(self)
        lay.addSpacing(6)
        lay.addWidget(self._indicator)

        self._ticker = ScrollingLabel()
        self._ticker.setFont(theme.font(12, 500))
        self._ticker.setColor(theme.TEXT_DIM)
        self._ticker.setMinimumWidth(120)
        lay.addWidget(self._ticker, 1)

        self._codec = QLabel("")
        self._codec.setObjectName("CardValueDim")
        self._codec.setFont(theme.font(10, 600, mono=True))
        self._codec.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-family: '{theme.mono_family()}'; font-size: 10px;")
        lay.addWidget(self._codec)

        lay.addSpacing(6)

        self._btn_min = self._win_button("minimize", "最小化", self.minimize_clicked)
        self._btn_max = self._win_button("maximize", "最大化", self.maximize_clicked)
        self._btn_close = self._win_button("close", "关闭", self.close_clicked, close=True)
        for b in (self._btn_min, self._btn_max, self._btn_close):
            lay.addWidget(b)

    def _win_button(self, icon_name: str, tip: str, signal, close: bool = False) -> QPushButton:
        b = QPushButton()
        b.setObjectName("WinBtnClose" if close else "WinBtn")
        b.setFixedSize(44, theme.TITLEBAR_H - 1)
        b.setIcon(icons.icon(icon_name, 13, theme.TEXT_DIM))
        b.setIconSize(QSize(13, 13))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setToolTip(tip)
        b.clicked.connect(signal.emit)
        return b

    def set_now_playing(self, text: str, playing: bool) -> None:
        self._ticker.setText(text or "")
        self._indicator.set_active(playing)

    def set_codec(self, text: str) -> None:
        self._codec.setText(text or "")

    def set_maximized(self, maximized: bool) -> None:
        self._btn_max.setIcon(icons.icon("restore" if maximized else "maximize", 13, theme.TEXT_DIM))
        self._btn_max.setToolTip("还原" if maximized else "最大化")

    # -- window dragging ---------------------------------------------------
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            win = self.window()
            handle = win.windowHandle()
            if handle is not None and not win.isMaximized():
                handle.startSystemMove()
                event.accept()
                return
            self._drag_offset = event.globalPosition().toPoint() - win.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            win = self.window()
            if not win.isMaximized():
                win.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.maximize_clicked.emit()
            event.accept()


# --------------------------------------------------------------------------- #
#  volume control
# --------------------------------------------------------------------------- #
class VolumeControl(QWidget):
    volume_changed = Signal(int)
    mute_toggled = Signal(bool)

    def __init__(self, value: int = 72, parent=None):
        super().__init__(parent)
        self._muted = False
        self._value = value
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self._btn = IconButton("volume", 26, 15, "静音 / 恢复", color=theme.TEXT_DIM)
        self._btn.clicked.connect(self._toggle_mute)
        lay.addWidget(self._btn)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setObjectName("VolumeSlider")
        self._slider.setRange(0, 100)
        self._slider.setValue(value)
        self._slider.setFixedHeight(20)
        self._slider.valueChanged.connect(self._on_change)
        lay.addWidget(self._slider, 1)

        self._label = QLabel(f"{value}")
        self._label.setFixedWidth(26)
        self._label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._label.setFont(theme.font(11, 500, mono=True))
        self._label.setStyleSheet(f"color: {theme.TEXT_DIM}; font-family: '{theme.mono_family()}';")
        lay.addWidget(self._label)

    def _on_change(self, value: int) -> None:
        self._value = value
        self._label.setText(str(value))
        if value > 0 and self._muted:
            self._muted = False
            self._refresh_icon()
            self.mute_toggled.emit(False)
        self.volume_changed.emit(value)

    def _toggle_mute(self) -> None:
        self._muted = not self._muted
        self._refresh_icon()
        self.mute_toggled.emit(self._muted)

    def _refresh_icon(self) -> None:
        if self._muted or self._value == 0:
            name = "mute"
        elif self._value < 45:
            name = "volume_low"
        else:
            name = "volume"
        self._btn.set_icon_name(name)

    def set_value(self, value: int) -> None:
        self._slider.blockSignals(True)
        self._slider.setValue(value)
        self._slider.blockSignals(False)
        self._label.setText(str(value))
        self._value = value
        self._refresh_icon()

    def set_muted(self, muted: bool) -> None:
        self._muted = muted
        self._refresh_icon()

    @property
    def value(self) -> int:
        return self._value


# --------------------------------------------------------------------------- #
#  sidebar navigation
# --------------------------------------------------------------------------- #
class NavItem(QWidget):
    """One row in the sidebar: icon, label, count."""

    clicked = Signal(str)

    def __init__(self, key: str, label: str, count: int = -1, icon_name: str = "",
                 parent=None):
        super().__init__(parent)
        self.key = key
        self._selected = False
        self._hover = False
        self._icon_name = icon_name
        self._label = label
        self._count = count
        self.setFixedHeight(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.update()

    def set_count(self, count: int) -> None:
        self._count = count
        self.update()

    def enterEvent(self, event):  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event):  # noqa: N802
        self._hover = False
        self.update()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()

        if self._selected:
            p.fillRect(0, 0, w, h, theme.c(theme.BG_ROW_SEL))
            p.fillRect(0, 0, 2, h, theme.c(theme.ACCENT))
        elif self._hover:
            p.fillRect(0, 0, w, h, theme.c(theme.BG_ROW_HOVER))

        x = 10
        if self._icon_name:
            col = theme.ACCENT if self._selected else theme.TEXT_MUTED
            pm = icons.pixmap(self._icon_name, 14, col)
            p.drawPixmap(x, (h - 14) // 2, 14, 14, pm)
        # Reserve the icon gutter even when a row has no icon, so icon-less
        # lists (genres) stay column-aligned with the icon lists above them.
        x += 22

        p.setFont(theme.font(12, 600 if self._selected else 400))
        p.setPen(QPen(theme.c(theme.TEXT if self._selected else theme.TEXT_DIM)))
        text_rect = QRect(x, 0, w - x - 46, h)
        fm = QFontMetrics(p.font())
        p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   fm.elidedText(self._label, Qt.TextElideMode.ElideRight, text_rect.width()))

        if self._count >= 0:
            p.setFont(theme.font(10, 500, mono=True))
            p.setPen(QPen(theme.c(theme.TEXT_MUTED if not self._selected else theme.ACCENT_DIM)))
            p.drawText(QRect(w - 46, 0, 40, h),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, str(self._count))
        p.end()


# --------------------------------------------------------------------------- #
#  misc
# --------------------------------------------------------------------------- #
class Badge(QLabel):
    """Small monospaced pill used for codec / bitrate / quality markers."""

    def __init__(self, text: str = "", tone: str = "neutral", parent=None):
        super().__init__(text, parent)
        self.setFont(theme.font(9, 700, mono=True, spacing=0.4))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(16)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        palette = {
            "neutral": (theme.BG_PANEL_ALT, theme.STROKE, theme.TEXT_MUTED),
            "accent": (theme.ACCENT_SOFT, theme.ACCENT_DIM, theme.ACCENT),
            "good": ("#12301f", "#1d5c38", theme.GOOD),
            "warn": ("#33260c", "#6b4e14", theme.WARN),
            "rec": ("#2a1512", theme.REC_DIM, theme.REC),
        }
        bg, border, fg = palette.get(tone, palette["neutral"])
        self.setStyleSheet(
            f"background: {bg}; border: 1px solid {border}; border-radius: 2px;"
            f"color: {fg}; padding: 0px 5px;"
        )
        self.setMinimumWidth(0)


class KeyValueRow(QWidget):
    """Label on the left, value on the right, used in detail panels."""

    def __init__(self, key: str, value: str = "", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self._k = QLabel(key)
        self._k.setObjectName("CardLabel")
        self._k.setFont(theme.label_font(8, 700, 1.1))
        self._k.setFixedWidth(76)
        self._v = ElideLabel(value)
        self._v.setFont(theme.font(11, 400))
        self._v.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        lay.addWidget(self._k)
        lay.addWidget(self._v, 1)

    def set_value(self, value: str, dim: bool = False) -> None:
        self._v.setText(value or "--")
        self._v.setStyleSheet(
            f"color: {theme.TEXT_MUTED if dim else theme.TEXT_DIM}; font-size: 11px;"
        )
