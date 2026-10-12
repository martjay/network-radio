"""Station list: model, painted delegate and view.

The list is the centre of the application, so it is fully custom painted -
two-line rows, codec badges, signal-strength bars, favourite stars and a live
playing indicator - rather than stock QTreeView rows.
"""
from __future__ import annotations

import time

from PySide6.QtCore import (
    QAbstractTableModel, QModelIndex, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal,
)
from PySide6.QtGui import QBrush, QFontMetrics, QLinearGradient, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QStyle, QStyledItemDelegate, QTreeView,
)

from . import icons, theme

STATION_ROLE = Qt.ItemDataRole.UserRole + 1

COL_STATE = 0
COL_NAME = 1
COL_GENRE = 2
COL_CODEC = 3
COL_RATE = 4
COL_SIGNAL = 5
COL_FAV = 6

HEADERS = [
    ("", 26, "state"),
    ("电台 / STATION", 0, "name"),
    ("类型 / GENRE", 104, "genre"),
    ("编码", 60, "codec"),
    ("码率", 66, "bitrate"),
    ("信号", 62, "signal"),
    ("", 34, "fav"),
]

GENRE_ZH = {
    "news": "新闻资讯", "classical": "古典音乐", "jazz": "爵士蓝调",
    "electronic": "电子舞曲", "chill": "氛围休闲", "rock": "摇滚金属",
    "pop": "流行金曲", "urban": "嘻哈节奏", "folk": "民谣乡村",
    "world": "世界拉丁", "oldies": "怀旧年代", "screen": "影视原声",
    "sport": "体育赛事", "culture": "文化谈话", "varied": "综合电台",
}


def signal_bars(bitrate: int) -> int:
    if bitrate >= 256:
        return 4
    if bitrate >= 192:
        return 3
    if bitrate >= 128:
        return 2
    if bitrate > 0:
        return 1
    return 2  # unknown: assume acceptable, it was verified playable


class StationModel(QAbstractTableModel):
    def __init__(self, library, parent=None):
        super().__init__(parent)
        self.library = library
        self.rows: list[dict] = []
        self.playing_url = ""
        self.loading_url = ""

    # -- Qt API ------------------------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return len(HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return HEADERS[section][0]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        col = index.column()
        if role == STATION_ROLE:
            return row
        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_NAME:
                return row.get("name", "")
            if col == COL_GENRE:
                return GENRE_ZH.get(row.get("genre", ""), row.get("genre", ""))
            if col == COL_CODEC:
                return row.get("codec", "") or ""
            if col == COL_RATE:
                br = int(row.get("bitrate") or 0)
                return f"{br}k" if br else "--"
            return ""
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(row)
        if role == Qt.ItemDataRole.TextAlignmentRole and col in (COL_RATE, COL_CODEC):
            return int(Qt.AlignmentFlag.AlignCenter)
        return None

    @staticmethod
    def _tooltip(row: dict) -> str:
        parts = [row.get("name", "")]
        meta = []
        if row.get("country"):
            meta.append(row["country"])
        if row.get("state"):
            meta.append(row["state"])
        if row.get("codec"):
            meta.append(row["codec"])
        if row.get("bitrate"):
            meta.append(f"{row['bitrate']} kbps")
        if row.get("sample_rate"):
            meta.append(f"{row['sample_rate']} Hz")
        if meta:
            parts.append(" · ".join(meta))
        if row.get("tags"):
            parts.append(row["tags"])
        parts.append(row.get("url", ""))
        return "\n".join(parts)

    # -- data plumbing -----------------------------------------------------
    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def set_playing(self, url: str, loading: str = "") -> None:
        self.playing_url, self.loading_url = url, loading

    def refresh_row(self, url: str) -> None:
        for i, row in enumerate(self.rows):
            if row.get("url") == url:
                self.dataChanged.emit(self.index(i, 0), self.index(i, len(HEADERS) - 1))
                return

    def row_of(self, url: str) -> int:
        for i, row in enumerate(self.rows):
            if row.get("url") == url:
                return i
        return -1

    def station_at(self, row: int) -> dict | None:
        if 0 <= row < len(self.rows):
            return self.rows[row]
        return None


class StationDelegate(QStyledItemDelegate):
    """Paints every cell by hand for full control over the row design."""

    def __init__(self, model: StationModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.hover_row = -1
        self.hover_col = -1
        self.hover_play = -1

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(120, theme.ROW_H)

    # ------------------------------------------------------------------ #
    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        row = index.data(STATION_ROLE)
        if row is None:
            super().paint(painter, option, index)
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect: QRect = option.rect
        col = index.column()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = (index.row() == self.hover_row)
        is_playing = row.get("url") == self.model.playing_url
        is_loading = row.get("url") == self.model.loading_url

        # ---- background ------------------------------------------------
        if selected:
            painter.fillRect(rect, theme.c(theme.BG_ROW_SEL))
            painter.fillRect(rect.left(), rect.top(), 2, rect.height(), theme.c(theme.ACCENT))
        elif hovered:
            painter.fillRect(rect, theme.c(theme.BG_ROW_HOVER))

        if is_playing:
            grad = QLinearGradient(rect.left(), 0, rect.left() + 150, 0)
            grad.setColorAt(0.0, theme.c(theme.ACCENT, 0.10))
            grad.setColorAt(1.0, theme.c(theme.ACCENT, 0.0))
            painter.fillRect(rect, QBrush(grad))

        # ---- bottom hairline -------------------------------------------
        painter.setPen(QPen(theme.c(theme.STROKE_SOFT), 1))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

        if col == COL_STATE:
            self._paint_state(painter, rect, is_playing, is_loading, hovered, selected)
        elif col == COL_NAME:
            self._paint_name(painter, rect, row, is_playing, selected)
        elif col == COL_GENRE:
            self._paint_text(painter, rect, GENRE_ZH.get(row.get("genre", ""), ""),
                             theme.TEXT_DIM, 11, Qt.AlignmentFlag.AlignLeft)
        elif col == COL_CODEC:
            self._paint_badge(painter, rect, (row.get("codec") or "").upper())
        elif col == COL_RATE:
            br = int(row.get("bitrate") or 0)
            self._paint_text(painter, rect, f"{br}" if br else "--",
                             theme.TEXT_DIM if br else theme.TEXT_FAINT, 11,
                             Qt.AlignmentFlag.AlignCenter, mono=True)
        elif col == COL_SIGNAL:
            self._paint_signal(painter, rect, signal_bars(int(row.get("bitrate") or 0)))
        elif col == COL_FAV:
            self._paint_fav(painter, rect, row, hovered)
        painter.restore()

    # ------------------------------------------------------------------ #
    def _paint_state(self, painter, rect, is_playing, is_loading, hovered, selected) -> None:
        cx = rect.center().x()
        cy = rect.center().y()
        if is_loading:
            phase = (time.monotonic() * 2.4) % (2 * 3.14159)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(theme.c(theme.ACCENT_DIM), 1.6))
            painter.drawArc(QRectF(cx - 6, cy - 6, 12, 12), int(phase * 57.3 * 16), 100 * 16)
            return
        if is_playing:
            # three animated bars
            for i in range(3):
                v = 0.35 + 0.65 * abs((time.monotonic() * 2.2 + i * 0.7) % 2 - 1)
                bh = max(3.0, v * 11)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(theme.c(theme.ACCENT))
                painter.drawRoundedRect(QRectF(cx - 5 + i * 3.6, cy + 5.5 - bh, 2.4, bh), 1.1, 1.1)
            return
        if hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.c(theme.TEXT))
            painter.drawPolygon(QPolygonF([
                QPointF(cx - 3, cy - 5), QPointF(cx + 5, cy), QPointF(cx - 3, cy + 5),
            ]))
            return
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.c(theme.TEXT_FAINT if not selected else theme.TEXT_MUTED))
        painter.drawEllipse(QRectF(cx - 2, cy - 2, 4, 4))

    def _paint_name(self, painter, rect, row, is_playing, selected) -> None:
        name = row.get("name", "")
        left = rect.left() + 4
        right = rect.right() - 8
        width = max(10, right - left)

        f_main = theme.font(12, 600 if (selected or is_playing) else 500)
        fm_main = QFontMetrics(f_main)
        painter.setFont(f_main)
        painter.setPen(QPen(theme.c(theme.TEXT if (selected or is_playing) else "#d5dae0")))

        # subtitle: country · state · tags
        bits = []
        if row.get("country"):
            bits.append(row["country"])
        if row.get("state"):
            bits.append(row["state"])
        tags = (row.get("tags") or "").strip()
        if tags:
            bits.append(tags.split(",")[0].strip())
        sub = " · ".join([b for b in bits if b])
        f_sub = theme.font(10, 400)
        fm_sub = QFontMetrics(f_sub)

        name_y = rect.top() + 8
        painter.drawText(
            QRect(left, name_y, width, 17),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            fm_main.elidedText(name, Qt.TextElideMode.ElideRight, width),
        )
        if sub:
            painter.setFont(f_sub)
            painter.setPen(QPen(theme.c(theme.TEXT_MUTED)))
            painter.drawText(
                QRect(left, rect.top() + 25, width, 14),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                fm_sub.elidedText(sub, Qt.TextElideMode.ElideRight, width),
            )

    def _paint_text(self, painter, rect, text, color, size, align, mono=False) -> None:
        if not text:
            return
        painter.setFont(theme.font(size, 400, mono=mono))
        painter.setPen(QPen(theme.c(color)))
        painter.drawText(rect.adjusted(4, 0, -6, 0),
                         int(align | Qt.AlignmentFlag.AlignVCenter), text)

    def _paint_badge(self, painter, rect, text) -> None:
        if not text:
            return
        short = {"MPEG": "MP3", "AAC": "AAC", "MP3": "MP3", "AAC+": "AAC+", "OGG": "OGG",
                 "OPUS": "OPUS", "FLAC": "FLAC", "H264": "AAC"}.get(text, text[:5])
        f = theme.font(9, 700, mono=True, spacing=0.3)
        painter.setFont(f)
        fm = QFontMetrics(f)
        w = min(fm.horizontalAdvance(short) + 12, rect.width() - 8)
        h = 16
        box = QRectF(rect.center().x() - w / 2.0, rect.center().y() - h / 2.0, w, h)
        painter.setPen(QPen(theme.c(theme.STROKE), 1))
        painter.setBrush(theme.c(theme.BG_PANEL_ALT))
        painter.drawRoundedRect(box, 2, 2)
        painter.setPen(QPen(theme.c(theme.TEXT_DIM)))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, short)

    def _paint_signal(self, painter, rect, bars: int) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        bw, gap = 3.2, 2.4
        total = 4 * bw + 3 * gap
        x0 = rect.center().x() - total / 2.0
        base = rect.center().y() + 6
        for i in range(4):
            h = 4 + i * 3.4
            x = x0 + i * (bw + gap)
            if i < bars:
                col = theme.c(theme.ACCENT if bars >= 3 else theme.WARN)
            else:
                col = theme.c("#2a3138")
            painter.setBrush(col)
            painter.drawRoundedRect(QRectF(x, base - h, bw, h), 1.0, 1.0)

    def _paint_fav(self, painter, rect, row, hovered) -> None:
        url = row.get("url", "")
        is_fav = self.model.library.is_favorite(url)
        count = self.model.library.play_count(url)
        if is_fav:
            pm = icons.pixmap("heart_filled", 14, theme.REC)
        elif hovered:
            pm = icons.pixmap("heart", 14, theme.TEXT_DIM)
        else:
            pm = icons.pixmap("heart", 14, "#3a424b")
        painter.drawPixmap(rect.center().x() - 7, rect.center().y() - 7 - (5 if count else 0), 14, 14, pm)
        if count > 1:
            painter.setFont(theme.font(8, 600, mono=True))
            painter.setPen(QPen(theme.c(theme.TEXT_FAINT)))
            painter.drawText(QRect(rect.left(), rect.center().y() + 3, rect.width(), 12),
                             Qt.AlignmentFlag.AlignCenter, str(min(count, 999)))


class StationTable(QTreeView):
    """The station list with hover tracking and click-to-act columns."""

    station_activated = Signal(dict)
    favorite_toggled = Signal(str)
    context_requested = Signal(object, object)   # (station, global QPoint)
    selection_changed = Signal(object)           # station dict or None

    def __init__(self, model: StationModel, parent=None):
        super().__init__(parent)
        self.setObjectName("StationTable")
        self._model = model
        self.setModel(model)
        self._delegate = StationDelegate(model, self)
        self.setItemDelegate(self._delegate)

        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setExpandsOnDoubleClick(False)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QTreeView.Shape.NoFrame)
        self.setIndentation(0)
        self.setIconSize(QSize(14, 14))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        header = self.header()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(False)
        header.setHighlightSections(False)
        header.setSectionsClickable(True)
        header.setFixedHeight(26)
        for i, (_label, width, _key) in enumerate(HEADERS):
            if width:
                self.setColumnWidth(i, width)
        self.setColumnWidth(COL_FAV, 34)
        self.setColumnWidth(COL_STATE, 26)

        self.verticalScrollBar().setSingleStep(theme.ROW_H // 3)

        self.clicked.connect(self._on_clicked)
        self.doubleClicked.connect(self._on_double)
        self.customContextMenuRequested.connect(self._on_context)
        self.selectionModel().currentChanged.connect(self._on_current)

        self._anim = QTimer(self)
        self._anim.setInterval(80)
        self._anim.timeout.connect(self._repaint_animated)
        self._anim.start()

    def _repaint_animated(self) -> None:
        if self._model.playing_url or self._model.loading_url:
            self.viewport().update()

    # -- interaction -------------------------------------------------------
    def _on_current(self, current: QModelIndex, previous: QModelIndex) -> None:
        station = self._model.station_at(current.row()) if current.isValid() else None
        self.selection_changed.emit(station)

    def _on_clicked(self, index: QModelIndex) -> None:
        station = self._model.station_at(index.row())
        if station is None:
            return
        if index.column() == COL_FAV:
            self.favorite_toggled.emit(station.get("url", ""))
            return
        self.station_activated.emit(station)

    def _on_double(self, index: QModelIndex) -> None:
        station = self._model.station_at(index.row())
        if station is not None:
            self.station_activated.emit(station)

    def _on_context(self, pos) -> None:
        index = self.indexAt(pos)
        station = self._model.station_at(index.row()) if index.isValid() else None
        self.context_requested.emit(station, self.viewport().mapToGlobal(pos))

    def mouseMoveEvent(self, event):  # noqa: N802
        index = self.indexAt(event.position().toPoint())
        row = index.row() if index.isValid() else -1
        col = index.column() if index.isValid() else -1
        if row != self._delegate.hover_row or col != self._delegate.hover_col:
            self._delegate.hover_row = row
            self._delegate.hover_col = col
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._delegate.hover_row = -1
        self._delegate.hover_col = -1
        self.viewport().update()
        super().leaveEvent(event)

    def keyPressEvent(self, event):  # noqa: N802
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            station = self._model.station_at(self.currentIndex().row())
            if station:
                self.station_activated.emit(station)
                event.accept()
                return
        if key == Qt.Key.Key_F and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            event.ignore()
            return
        super().keyPressEvent(event)

    def select_url(self, url: str) -> None:
        row = self._model.row_of(url)
        if row >= 0:
            idx = self._model.index(row, COL_NAME)
            self.setCurrentIndex(idx)
            self.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)
