"""Custom widgets.

Everything here is drawn with QPainter rather than assembled from stock
controls, which is what keeps the interface from looking like a default Qt
application.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QHelpEvent,
    QLinearGradient, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListView, QProxyStyle, QPushButton, QSizePolicy, QSlider,
    QStyle, QStyleFactory, QToolTip, QVBoxLayout, QWidget,
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


class _ScrollComboStyle(QProxyStyle):
    """Force a scrollable combo popup instead of a full-height menu."""

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_ComboBox_Popup:
            return 0
        if hint == QStyle.StyleHint.SH_ScrollBar_Transient:
            return 0
        return super().styleHint(hint, option, widget, returnData)


class ScrollComboBox(QComboBox):
    """Combo whose popup is height-capped and always shows a vertical scrollbar."""

    popup_cap = 280

    def __init__(self, parent=None, visible_items: int = 12):
        super().__init__(parent)
        # Keep style objects alive; Qt does not take ownership of QProxyStyle.
        self._combo_style = _ScrollComboStyle(QStyleFactory.create("Fusion"))
        self._bar_style = _ScrollComboStyle(QStyleFactory.create("Fusion"))
        self.setStyle(self._combo_style)
        view = QListView(self)
        view.setObjectName("ComboPopup")
        view.setUniformItemSizes(True)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        view.setMouseTracking(True)
        view.setStyleSheet(
            f"QListView#ComboPopup {{ outline: none; border: none; color: {theme.TEXT}; }}"
            f"QListView#ComboPopup::item {{ color: {theme.TEXT}; padding: 3px 8px; }}"
            f"QListView#ComboPopup::item:hover,"
            f"QListView#ComboPopup::item:selected {{ color: {theme.WARN};"
            f"  background: {theme.BG_ROW_HOVER}; }}"
            "QScrollBar:vertical { background: #161a1f; width: 12px; margin: 2px; }"
            "QScrollBar::handle:vertical { background: #6a7580; min-height: 32px;"
            "  border-radius: 4px; }"
            "QScrollBar::handle:vertical:hover { background: #8b96a1; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: #161a1f; }"
        )
        self.setView(view)
        self.setMaxVisibleItems(visible_items)

    def showPopup(self) -> None:
        super().showPopup()
        view = self.view()
        if view is None:
            return
        cap = self._popup_cap()
        container = view.parentWidget()
        if container is not None and container is not self:
            container.setMaximumHeight(cap)
            if container.height() > cap:
                geo = container.geometry()
                geo.setHeight(cap)
                container.setGeometry(geo)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        view.updateGeometries()
        bar = view.verticalScrollBar()
        bar.setStyle(self._bar_style)

    def _popup_cap(self) -> int:
        screen = self.screen()
        avail = screen.availableGeometry() if screen else QRect(0, 0, 800, 600)
        below = self.mapToGlobal(self.rect().bottomLeft())
        above = self.mapToGlobal(self.rect().topLeft())
        room_below = avail.bottom() - below.y() - 8
        room_above = above.y() - avail.top() - 8
        room = max(room_below, room_above, 120)
        wanted = self.maxVisibleItems() * 24 + 8
        return min(self.popup_cap, room, wanted)


def section_label(text: str, spacing: float = 1.5) -> QLabel:
    lab = QLabel(text.upper())
    lab.setObjectName("SideHeader")
    lab.setFont(theme.label_font(9, 700, spacing))
    return lab


def show_copy_tip(widget: QWidget, message: str = "已复制") -> None:
    """Flash a compact hint at the cursor."""
    pos = QCursor.pos() + QPoint(12, 16)

    def _show() -> None:
        hint_tip().popup(message, pos, linger_ms=1400)

    QTimer.singleShot(0, _show)


class HintTip(QWidget):
    """Content-sized hover hint, painted so Windows cannot inflate it."""

    _max_w = 240
    _pad_x = 8
    _pad_y = 5
    _radius = 4
    _gap = 2

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setObjectName("HintTip")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._title_font = theme.font(11, 500)
        self._note_font = theme.font(10, 400)
        self._title_lines: list[str] = []
        self._note_lines: list[str] = []
        self._hide = QTimer(self)
        self._hide.setSingleShot(True)
        self._hide.timeout.connect(self.hide)

    def popup(self, text: str, pos: QPoint, linger_ms: int = 0) -> None:
        raw = (text or "").strip()
        if not raw:
            self.hide()
            return
        parts = [p.strip() for p in raw.split("\n") if p.strip()]
        title = parts[0] if parts else ""
        notes = parts[1:]
        title_fm = QFontMetrics(self._title_font)
        note_fm = QFontMetrics(self._note_font)
        inner = self._max_w - self._pad_x * 2
        self._title_lines = self._wrap(title, title_fm, inner)
        self._note_lines = []
        for note in notes:
            self._note_lines.extend(self._wrap(note, note_fm, inner))

        widths = [title_fm.horizontalAdvance(s) for s in self._title_lines]
        widths += [note_fm.horizontalAdvance(s) for s in self._note_lines]
        text_w = max(widths) if widths else 0
        line_blocks = len(self._title_lines) + len(self._note_lines)
        extra_gaps = max(0, line_blocks - 1)
        note_gap = self._gap + 1 if self._title_lines and self._note_lines else 0
        h = (
            self._pad_y * 2
            + title_fm.height() * len(self._title_lines)
            + note_fm.height() * len(self._note_lines)
            + extra_gaps * self._gap
            + note_gap
        )
        w = text_w + self._pad_x * 2
        self.setFixedSize(max(w, 24), max(h, 18))

        geo = QRect(pos, self.size())
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry().adjusted(6, 6, -6, -6)
            if geo.right() > avail.right():
                geo.moveRight(avail.right())
            if geo.bottom() > avail.bottom():
                geo.moveBottom(pos.y() - 8)
            if geo.left() < avail.left():
                geo.moveLeft(avail.left())
            if geo.top() < avail.top():
                geo.moveTop(avail.top())
        self.setGeometry(geo)
        self.show()
        self.raise_()
        self.update()
        if linger_ms > 0:
            self._hide.start(linger_ms)
        else:
            self._hide.stop()

    @staticmethod
    def _wrap(text: str, fm: QFontMetrics, max_w: int) -> list[str]:
        if not text:
            return []
        if fm.horizontalAdvance(text) <= max_w:
            return [text]
        lines: list[str] = []
        current = ""
        for ch in text:
            trial = current + ch
            if current and fm.horizontalAdvance(trial) > max_w:
                lines.append(current)
                current = ch
            else:
                current = trial
        if current:
            lines.append(current)
        return lines

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        p.fillPath(path, QColor(theme.BG_PANEL_ALT))
        p.setPen(QPen(QColor(theme.STROKE), 1))
        p.drawPath(path)

        x = self._pad_x
        y = self._pad_y
        title_fm = QFontMetrics(self._title_font)
        note_fm = QFontMetrics(self._note_font)
        p.setFont(self._title_font)
        p.setPen(QColor(theme.TEXT))
        for line in self._title_lines:
            y += title_fm.ascent()
            p.drawText(x, y, line)
            y += title_fm.descent() + self._gap
        if self._title_lines and self._note_lines:
            y += 1
        p.setFont(self._note_font)
        p.setPen(QColor(theme.TEXT_FAINT))
        for line in self._note_lines:
            y += note_fm.ascent()
            p.drawText(x, y, line)
            y += note_fm.descent() + self._gap


class _TipFilter(QObject):
    def __init__(self, tip: HintTip, parent=None):
        super().__init__(parent)
        self._tip = tip
        self._anchor = None

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        try:
            et = event.type()
            if et == QEvent.Type.ToolTip:
                if obj is self._tip or not isinstance(obj, QWidget):
                    return False
                text = obj.toolTip()
                if not text:
                    return False
                if isinstance(event, QHelpEvent):
                    pos = event.globalPos() + QPoint(12, 14)
                else:
                    pos = QCursor.pos() + QPoint(12, 14)
                self._anchor = obj
                self._tip.popup(text, pos)
                return True
            if et == QEvent.Type.Leave and obj is self._anchor:
                self._tip.hide()
                self._anchor = None
                return False
            if et in (
                QEvent.Type.Wheel,
                QEvent.Type.MouseButtonPress,
                QEvent.Type.WindowDeactivate,
            ) and self._tip.isVisible():
                self._tip.hide()
                self._anchor = None
        except Exception:
            return False
        return False


_HINT_TIP: HintTip | None = None


def hint_tip() -> HintTip:
    global _HINT_TIP
    app = QApplication.instance()
    if _HINT_TIP is None and app is not None:
        _HINT_TIP = HintTip()
        filt = _TipFilter(_HINT_TIP, app)
        app.installEventFilter(filt)
        _HINT_TIP._filter = filt  # noqa: SLF001 — keep the filter alive
    if _HINT_TIP is None:
        raise RuntimeError("HintTip needs a QApplication")
    return _HINT_TIP


def install_hint_tips(app: QApplication | None = None) -> None:
    app = app or QApplication.instance()
    if app is not None:
        hint_tip()


class ElideLabel(QLabel):
    """A label that elides its text to the available width."""

    copied = Signal(str)

    def __init__(self, text: str = "", mode=Qt.TextElideMode.ElideRight, parent=None):
        super().__init__(parent)
        self._full = text
        self._mode = mode
        self._copy_on_click = False
        self._hover_tip = True
        # Ignored + a tiny hint: never fight the layout with the unelided
        # string width, which used to make the now-playing bar oscillate.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(24)
        super().setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text or ""
        self._sync_copy_tip()
        self._apply()

    def fullText(self) -> str:  # noqa: N802
        return self._full

    def set_copy_on_click(self, enabled: bool = True) -> None:
        self._copy_on_click = enabled
        if enabled:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()
        self._sync_copy_tip()

    def set_hover_tip(self, enabled: bool) -> None:
        self._hover_tip = enabled
        self._sync_copy_tip()

    def _sync_copy_tip(self) -> None:
        if self._copy_on_click and self._full:
            self.setToolTip(f"{self._full}\n点击复制")
        elif self._hover_tip and self._full:
            self.setToolTip(self._full)
        else:
            self.setToolTip("")

    def mouseReleaseEvent(self, event):  # noqa: N802
        if (self._copy_on_click and event.button() == Qt.MouseButton.LeftButton
                and self._full.strip()):
            QApplication.clipboard().setText(self._full)
            self.copied.emit(self._full)
            show_copy_tip(self)
            event.accept()
            return
        super().mouseReleaseEvent(event)

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
    """Marquee: centred while the text fits, looping when it does not."""

    copied = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self._offset = 0.0
        self._pause = 0.0
        self._hover = False
        self._font = theme.font(12, 600)
        self._color = theme.c(theme.ACCENT)
        self._fade = theme.BG_SIDEBAR
        self._align = Qt.AlignmentFlag.AlignHCenter
        self._gap = 56
        self._press_at: QPoint | None = None
        self.setMinimumHeight(20)
        self.setMinimumWidth(24)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._timer = QTimer(self)
        self._timer.setInterval(28)
        self._timer.timeout.connect(self._tick)

    def setText(self, text: str) -> None:  # noqa: N802
        self._text = text or ""
        self._offset = 0.0
        self._pause = 1.6
        self._sync_copy_tip()
        self._update_timer()
        self.update()

    def text(self) -> str:
        return self._text

    def fullText(self) -> str:  # noqa: N802
        return self._text

    def setFont(self, font: QFont) -> None:  # noqa: N802
        self._font = font
        fm = QFontMetrics(font)
        self.setMinimumHeight(max(20, fm.height() + 2))
        self._update_timer()
        self.update()

    def setColor(self, color: str) -> None:  # noqa: N802
        self._color = theme.c(color)
        self.update()

    def setFadeColor(self, color: str) -> None:  # noqa: N802
        self._fade = color
        self.update()

    def setAlignment(self, align) -> None:  # noqa: N802
        self._align = align
        self.update()

    def set_copy_on_click(self, enabled: bool = True) -> None:
        if enabled:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()

    def _sync_copy_tip(self) -> None:
        self.setToolTip(f"{self._text}\n点击复制" if self._text else "")

    def _overflow(self) -> float:
        fm = QFontMetrics(self._font)
        return fm.horizontalAdvance(self._text) - max(0, self.width() - 4)

    def _update_timer(self) -> None:
        if self._overflow() > 0 and self.isVisible() and not self._hover:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            if self._overflow() <= 0:
                self._offset = 0.0

    def _tick(self) -> None:
        if self._overflow() <= 0 or self._hover:
            self._timer.stop()
            if self._overflow() <= 0:
                self._offset = 0.0
            self.update()
            return
        if self._pause > 0:
            self._pause -= 0.028
            return
        self._offset += 1.05
        span = QFontMetrics(self._font).horizontalAdvance(self._text) + self._gap
        if span > 0 and self._offset >= span:
            self._offset -= span
        self.update()

    def enterEvent(self, event):  # noqa: N802
        self._hover = True
        self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hover = False
        self._update_timer()
        super().leaveEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_at = event.position().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        start = self._press_at
        self._press_at = None
        if (event.button() == Qt.MouseButton.LeftButton and start is not None
                and (event.position().toPoint() - start).manhattanLength() < 8
                and self._text.strip()):
            QApplication.clipboard().setText(self._text)
            self.copied.emit(self._text)
            show_copy_tip(self)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._update_timer()
        self.update()

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
        if not self._text:
            return
        if self._overflow() <= 0:
            p.drawText(rect, Qt.AlignmentFlag.AlignVCenter | self._align, self._text)
            return
        p.setClipRect(rect)
        y = rect.top() + (rect.height() + fm.ascent() - fm.descent()) // 2
        span = fm.horizontalAdvance(self._text) + self._gap
        x = rect.left() - self._offset
        p.drawText(QPoint(int(x), y), self._text)
        p.drawText(QPoint(int(x + span), y), self._text)
        fade = 18
        left = QLinearGradient(rect.left(), 0, rect.left() + fade, 0)
        left.setColorAt(0.0, theme.c(self._fade))
        left.setColorAt(1.0, theme.c(self._fade, 0.0))
        right = QLinearGradient(rect.right() - fade, 0, rect.right(), 0)
        right.setColorAt(0.0, theme.c(self._fade, 0.0))
        right.setColorAt(1.0, theme.c(self._fade))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(left))
        p.drawRect(QRect(rect.left(), rect.top(), fade, rect.height()))
        p.setBrush(QBrush(right))
        p.drawRect(QRect(rect.right() - fade, rect.top(), fade, rect.height()))
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
        self.setTextMargins(0, 0, 0, 0)


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
        self._value.set_hover_tip(False)
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
    """Frameless window chrome: brand mark and window buttons. Empty middle is for dragging."""

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
        brand = QLabel("BROADCAST")
        brand.setObjectName("BrandMark")
        brand.setFont(theme.font(13, 800, spacing=2.6))
        sub = QLabel("NETWORK RADIO")
        sub.setObjectName("BrandSub")
        sub.setFont(theme.font(10, 600, spacing=1.4))
        for w in (mark, brand, sub):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            lay.addWidget(w)

        lay.addStretch(1)

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

    clicked = Signal(str)

    def __init__(self, key: str, value: str = "", parent=None):
        super().__init__(parent)
        self._filterable = False
        self._dim = False
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
        self._k.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._v.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(self._k)
        lay.addWidget(self._v, 1)

    def set_value(self, value: str, dim: bool = False) -> None:
        self._dim = dim
        self._v.setText(value or "--")
        self._sync_filter_style()

    def set_hover_tip(self, enabled: bool) -> None:
        self._v.set_hover_tip(enabled)
        self._sync_filter_style()

    def set_filterable(self, enabled: bool) -> None:
        self._filterable = enabled
        self._sync_filter_style()

    def _has_filter_value(self) -> bool:
        text = (self._v.fullText() or "").strip()
        return text not in ("", "--")

    def _sync_filter_style(self) -> None:
        active = self._filterable and self._has_filter_value()
        color = theme.ACCENT if active else (theme.TEXT_MUTED if self._dim else theme.TEXT_DIM)
        self._v.setStyleSheet(f"color: {color}; font-size: 11px;")
        if active:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            tip = self._v.fullText()
            self.setToolTip(f"{tip}\n点击按此项筛选" if tip else "点击按此项筛选")
        else:
            self.unsetCursor()
            if not self._v.toolTip():
                self.setToolTip("")

    def mouseReleaseEvent(self, event):  # noqa: N802
        if (self._filterable and event.button() == Qt.MouseButton.LeftButton
                and self._has_filter_value()):
            self.clicked.emit(self._k.text())
            event.accept()
            return
        super().mouseReleaseEvent(event)
