"""Main application window."""
from __future__ import annotations

import os
import sys
import time

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from . import appicon, icons, paths, theme
from .dialogs import (
    ExportDialog, PreferencesDialog, ReportDialog, StationDialog, confirm, info,
)
from .library import SORT_MODES, Library
from .net import decode_stream_title
from .player import PlayerEngine
from .table import GENRE_ZH, StationModel, StationTable
from .tray import TrayController
from .widgets import (
    Chip, ElideLabel, IconButton, KeyValueRow, LevelMeter, NavItem,
    PlayingIndicator, ScrollingLabel, SearchField, SpectrumWidget, StatRow,
    TextButton, TransportButton, VolumeControl, hline, section_label, vline,
)


def _win32_hwnd_rect(hwnd: int):
    """Physical GetWindowRect as (left, top, right, bottom), or None."""
    try:
        import ctypes
        from ctypes import wintypes
        r = wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(int(hwnd), ctypes.byref(r)):
            return None
        return (int(r.left), int(r.top), int(r.right), int(r.bottom))
    except Exception:
        return None


def _ensure_dir(path: str) -> bool:
    """Create `path` if needed and confirm it is writable."""
    if not path:
        return False
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write-probe")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return True
    except (OSError, PermissionError):
        return False


def _reveal_in_file_manager(path: str) -> bool:
    """Open `path` in the desktop file manager. Returns True on success.

    Three independent attempts: `os.startfile`, then `explorer.exe`, then
    Qt's handler. `startfile` can raise on machines with a damaged folder
    association even when Explorer itself opens the path fine, which used to
    leave the button silently copying the path instead of opening it.
    """
    import subprocess
    import sys as _sys

    if _sys.platform == "win32":
        try:
            os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
            return True
        except OSError:
            pass
        try:
            from .recorder import CREATE_NO_WINDOW
            subprocess.Popen(["explorer.exe", os.path.normpath(path)],
                             creationflags=CREATE_NO_WINDOW)
            return True
        except Exception:  # noqa: BLE001
            pass
    else:
        try:
            if _sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            return True
        except Exception:  # noqa: BLE001
            pass
    # Last resort: Qt's own handler.
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    try:
        return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(path)))
    except Exception:  # noqa: BLE001
        return False


class MiniBar(QWidget):
    """Thin horizontal capacity bar used in the status strip."""

    def __init__(self, parent=None, color: str = theme.ACCENT):
        super().__init__(parent)
        self._value = 0.0
        self._color = color
        self.setFixedSize(52, 6)

    def set_value(self, value: float) -> None:
        self._value = max(0.0, min(1.0, float(value)))
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("#252b32"))
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 3, 3)
        if self._value > 0.01:
            p.setBrush(theme.c(self._color))
            p.drawRoundedRect(QRectF(0, 0, self.width() * self._value, self.height()), 3, 3)
        p.end()


class ResizeCorner(QWidget):
    """Visible bottom-right handle. Native QSizeGrip does nothing on a
    frameless WS_POPUP, so this starts the same manual resize as the edges."""

    def __init__(self, owner: "MainWindow", parent=None):
        super().__init__(parent)
        self._owner = owner
        self.setFixedSize(32, 32)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setToolTip("拖动调整窗口大小")
        self.setObjectName("ResizeCorner")

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            gp = event.globalPosition().toPoint()
            self._owner._begin_edge_resize(
                gp, Qt.Edge.RightEdge | Qt.Edge.BottomEdge,
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c(theme.TEXT))
        w, h = self.width(), self.height()
        for i in range(3):
            for j in range(3 - i):
                p.drawRect(w - 8 - i * 7, h - 8 - j * 7, 4, 4)
        p.end()


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("Root")
        self.setWindowTitle(f"{paths.APP_TITLE} — 网络收音机")
        # FramelessWindowHint alone strips WS_MINIMIZEBOX/WS_MAXIMIZEBOX, which
        # is why clicking the taskbar button would not minimise/restore the
        # window. The MinMax hints restore those styles without drawing any
        # native buttons.
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowMinMaxButtonsHint
        )
        self.setMinimumSize(1180, 700)

        self.library = Library(self)
        self.engine = PlayerEngine(self.library.settings, self)
        self.engine.set_proxy(self.library.proxy_config())

        self._section = self.library.get("genre", "all")
        self._filtered_rows: list[dict] = []
        self._page = 0
        self._sleep_deadline = 0.0
        self._play_started = 0.0
        self._history_recorded_url = ""
        self._record_started = 0.0
        self._really_quit = False
        self._tray_hint_shown = False
        self._pending_maximize = False
        self._restoring_normal = False
        self._rz_edges = Qt.Edge(0)
        self._rz_origin = QPoint()
        self._rz_geo = QRect()
        self.tray: TrayController | None = None

        self._build()
        self._wire()
        self._build_tray()
        self._restore_geometry()
        self._restore_session_ui()

        self._apply_filters(select_last=True)
        self._refresh_sidebar_counts()
        self._update_status()
        self._update_proxy_indicator()
        self._restore_last_station()

        self._clock = QTimer(self)
        self._clock.setInterval(500)
        self._clock.timeout.connect(self._tick)
        self._clock.start()

    # ================================================================== #
    #  construction
    # ================================================================== #
    def _build(self) -> None:
        from .widgets import TitleBar

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.titlebar = TitleBar(self)
        root.addWidget(self.titlebar)
        root.addWidget(hline(theme.STROKE))

        body = QWidget()
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)

        body_lay.addWidget(self._build_sidebar())
        body_lay.addWidget(vline(theme.STROKE))
        body_lay.addWidget(self._build_center(), 1)
        body_lay.addWidget(vline(theme.STROKE))
        body_lay.addWidget(self._build_right_panel())
        root.addWidget(body, 1)

        root.addWidget(hline(theme.STROKE))
        root.addWidget(self._build_statusbar())
        # Overlay on the window itself so the grip sits on the true
        # bottom-right pixel (the status bar layout has 12px margins).
        self._resize_corner = ResizeCorner(self, self)
        self._place_resize_corner()

    # ---------------------------------------------------------------- sidebar
    def _build_sidebar(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("Sidebar")
        panel.setFixedWidth(theme.SIDEBAR_W)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 12, 0, 8)
        lay.setSpacing(4)

        lay.addWidget(self._padded(section_label("浏览 / BROWSE")))
        lay.addSpacing(2)

        self._nav_items: dict[str, NavItem] = {}
        browse = [
            ("all", "全部电台", "list"),
            ("top", "常听电台", "star"),
            ("recent", "最近播放", "clock"),
            ("favorites", "我的收藏", "heart"),
            ("custom", "自建电台", "edit"),
            ("zh", "中文电台", "globe"),
        ]
        for key, label, icon_name in browse:
            item = NavItem(key, label, -1, icon_name)
            item.clicked.connect(self._on_nav)
            self._nav_items[key] = item
            lay.addWidget(item)

        lay.addSpacing(10)
        lay.addWidget(self._padded(section_label("类型 / GENRES")))
        lay.addSpacing(2)

        scroll = QScrollArea()
        scroll.setObjectName("SideScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner_lay = QVBoxLayout(inner)
        inner_lay.setContentsMargins(0, 0, 0, 0)
        inner_lay.setSpacing(0)
        for key, zh, en, count in self.library.genre_options():
            item = NavItem(key, zh, count)
            item.clicked.connect(self._on_nav)
            self._nav_items[key] = item
            inner_lay.addWidget(item)
        inner_lay.addStretch(1)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

        lay.addSpacing(6)
        lay.addWidget(self._padded(section_label("地区 / REGION")))
        self._country_combo = QComboBox()
        self._country_combo.setObjectName("Field")
        self._country_combo.addItem("全部地区", "all")
        for name, count in self.library.country_options():
            self._country_combo.addItem(f"{name}  ({count})", name)
        self._country_combo.setFixedHeight(26)
        self._country_combo.setFont(theme.font(11, 400))
        self._country_combo.currentIndexChanged.connect(self._on_country)
        wrap = QWidget()
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(10, 0, 10, 0)
        wl.addWidget(self._country_combo)
        lay.addWidget(wrap)

        lay.addSpacing(4)
        self._quality_chip = Chip("高音质 ≥128k", "只显示码率 128 kbps 以上的电台")
        self._quality_chip.toggled.connect(self._on_quality)
        qw = QWidget()
        ql = QHBoxLayout(qw)
        ql.setContentsMargins(10, 0, 10, 0)
        ql.addWidget(self._quality_chip)
        lay.addWidget(qw)
        return panel

    @staticmethod
    def _padded(widget: QWidget) -> QWidget:
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.addWidget(widget)
        return wrap

    # ---------------------------------------------------------------- center
    def _build_center(self) -> QWidget:
        center = QWidget()
        center.setObjectName("Center")
        center.setStyleSheet(f"QWidget#Center {{ background: {theme.BG_APP}; }}")
        lay = QVBoxLayout(center)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(self._build_toolbar())
        lay.addWidget(hline(theme.STROKE))

        self.model = StationModel(self.library, self)
        self.table = StationTable(self.model, self)
        lay.addWidget(self.table, 1)

        lay.addWidget(hline(theme.STROKE))
        lay.addWidget(self._build_pager())

        lay.addWidget(hline(theme.STROKE))
        lay.addWidget(self._build_nowbar())
        return center

    def _build_pager(self) -> QWidget:
        """Hairline page cluster under the station list."""
        bar = QWidget()
        bar.setObjectName("PagerBar")
        bar.setFixedHeight(36)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 4, 12, 4)
        lay.setSpacing(10)

        cluster = QWidget()
        cluster.setObjectName("PagerCluster")
        cluster.setFixedHeight(26)
        cl = QHBoxLayout(cluster)
        cl.setContentsMargins(1, 0, 1, 0)
        cl.setSpacing(0)

        def pager_btn(name: str, tip: str) -> IconButton:
            btn = IconButton(name, 24, 12, tip, object_name="PagerBtn")
            return btn

        self._page_first = pager_btn("chev_first", "第一页")
        self._page_first.clicked.connect(lambda: self._goto_page(0))
        cl.addWidget(self._page_first)

        self._page_prev = pager_btn("chev_left", "上一页")
        self._page_prev.clicked.connect(lambda: self._goto_page(self._page - 1))
        cl.addWidget(self._page_prev)

        cl.addWidget(vline(theme.STROKE))

        self._page_label = QLabel("1 / 1")
        self._page_label.setObjectName("PagerReadout")
        self._page_label.setFont(theme.font(11, 600, mono=True))
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_label.setFixedWidth(72)
        cl.addWidget(self._page_label)

        cl.addWidget(vline(theme.STROKE))

        self._page_next = pager_btn("chev_right", "下一页")
        self._page_next.clicked.connect(lambda: self._goto_page(self._page + 1))
        cl.addWidget(self._page_next)

        self._page_last = pager_btn("chev_last", "最后一页")
        self._page_last.clicked.connect(lambda: self._goto_page(self._page_count() - 1))
        cl.addWidget(self._page_last)

        lay.addWidget(cluster)

        self._page_range = QLabel("")
        self._page_range.setObjectName("PagerRange")
        self._page_range.setFont(theme.font(10, 500, mono=True))
        lay.addWidget(self._page_range)

        lay.addStretch(1)

        size_hint = QLabel("每页")
        size_hint.setObjectName("PagerMicro")
        size_hint.setFont(theme.label_font(8, 700, 1.2))
        lay.addWidget(size_hint)

        self._page_size_combo = QComboBox()
        self._page_size_combo.setObjectName("PagerField")
        self._page_size_combo.setFixedSize(58, 26)
        self._page_size_combo.setFont(theme.font(11, 600, mono=True))
        for n in (15, 30, 50, 100, 200):
            self._page_size_combo.addItem(str(n), n)
        saved = int(self.library.get("page_size", 30) or 30)
        idx = self._page_size_combo.findData(saved)
        self._page_size_combo.setCurrentIndex(idx if idx >= 0 else 1)
        self._page_size_combo.currentIndexChanged.connect(self._on_page_size)
        lay.addWidget(self._page_size_combo)
        return bar

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("Toolbar")
        bar.setFixedHeight(46)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(8)

        self.search = SearchField()
        self.search.setFixedWidth(280)
        lay.addWidget(self.search)

        self._fav_chip = Chip("仅收藏", "只显示已收藏的电台")
        self._fav_chip.toggled.connect(self._on_fav_filter)
        lay.addWidget(self._fav_chip)

        self._zh_chip = Chip("仅中文", "只显示中文电台")
        self._zh_chip.toggled.connect(self._on_zh_filter)
        lay.addWidget(self._zh_chip)

        self._sort_combo = QComboBox()
        self._sort_combo.setObjectName("Field")
        self._sort_combo.setFixedHeight(26)
        self._sort_combo.setFixedWidth(122)
        self._sort_combo.setFont(theme.font(11, 400))
        for key, label in SORT_MODES:
            self._sort_combo.addItem(label, key)
        idx = self._sort_combo.findData(self.library.get("sort", "score"))
        self._sort_combo.setCurrentIndex(max(0, idx))
        self._sort_combo.currentIndexChanged.connect(self._on_sort)
        lay.addWidget(self._sort_combo)

        lay.addStretch(1)

        self._count_label = QLabel("")
        self._count_label.setObjectName("CountLabel")
        self._count_label.setFont(theme.font(11, 500, mono=True))
        lay.addWidget(self._count_label)

        lay.addSpacing(4)
        self._export_btn = IconButton("download", 28, 15, "导出收藏为 M3U")
        self._export_btn.clicked.connect(self._export_favorites)
        lay.addWidget(self._export_btn)

        self._refresh_btn = IconButton("refresh", 28, 15, "重新载入列表")
        self._refresh_btn.clicked.connect(lambda: self._apply_filters())
        lay.addWidget(self._refresh_btn)

        self._settings_btn = IconButton("gear", 28, 16, "设置")
        self._settings_btn.clicked.connect(self._open_preferences)
        lay.addWidget(self._settings_btn)
        return bar

    def _build_nowbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("Toolbar")
        bar.setFixedHeight(84)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 8, 12, 8)
        lay.setSpacing(12)

        info_wrap = QWidget()
        info_wrap.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        info_wrap.setMinimumWidth(120)
        info_col = QVBoxLayout(info_wrap)
        info_col.setContentsMargins(0, 0, 0, 0)
        info_col.setSpacing(1)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(7)
        self._mini_indicator = PlayingIndicator(self, 3)
        title_row.addWidget(self._mini_indicator)
        self._mini_title = ElideLabel("未选择电台")
        self._mini_title.setFont(theme.font(14, 700))
        self._mini_title.setStyleSheet(f"color: {theme.TEXT};")
        title_row.addWidget(self._mini_title, 1)
        info_col.addLayout(title_row)

        self._mini_meta = ElideLabel("从左侧列表中选择一个电台开始收听")
        self._mini_meta.setFont(theme.font(11, 400))
        self._mini_meta.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        info_col.addWidget(self._mini_meta)

        self._mini_track = ScrollingLabel()
        self._mini_track.setFont(theme.font(11, 500))
        self._mini_track.setColor(theme.ACCENT)
        self._mini_track.setFadeColor(theme.BG_TOOLBAR)
        self._mini_track.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._mini_track.set_copy_on_click(True)
        info_col.addWidget(self._mini_track)
        lay.addWidget(info_wrap, 1)

        # level meter + timer
        meter_col = QVBoxLayout()
        meter_col.setContentsMargins(0, 0, 0, 0)
        meter_col.setSpacing(3)
        meter_caption = QLabel("输出电平")
        meter_caption.setObjectName("CardLabel")
        meter_caption.setFont(theme.label_font(8, 700, 1.1))
        meter_col.addWidget(meter_caption)
        self._level = LevelMeter(self)
        self._level.setFixedWidth(96)
        meter_col.addWidget(self._level)
        self._mini_time = QLabel("00:00:00")
        self._mini_time.setFont(theme.font(10, 500, mono=True))
        self._mini_time.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-family: '{theme.mono_family()}';")
        meter_col.addWidget(self._mini_time)
        lay.addLayout(meter_col)

        lay.addWidget(vline(theme.STROKE, 1))

        # transport — keep intrinsic width so shrinking the window elides
        # the title instead of cycling the button row.
        transport = QWidget()
        transport.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        tl = QHBoxLayout(transport)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(6)
        self._btn_prev = TransportButton("prev", 34, 15, "上一个电台  (Ctrl+Left)")
        self._btn_play = TransportButton("play", 44, 20, "播放 / 暂停  (Space)", primary=True)
        self._btn_stop = TransportButton("stop", 34, 15, "停止")
        self._btn_next = TransportButton("next", 34, 15, "下一个电台  (Ctrl+Right)")
        self._btn_rec = TransportButton("record", 34, 15, "录制当前电台")
        self._btn_rec.setCheckable(True)
        for b in (self._btn_prev, self._btn_play, self._btn_stop, self._btn_next):
            tl.addWidget(b)
        tl.addSpacing(4)
        tl.addWidget(self._btn_rec)
        lay.addWidget(transport)

        lay.addWidget(vline(theme.STROKE, 1))

        self._volume = VolumeControl(int(self.library.get("volume", 72)))
        self._volume.setMinimumWidth(96)
        self._volume.setMaximumWidth(158)
        lay.addWidget(self._volume)
        return bar

    # ------------------------------------------------------------ right panel
    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("RightPanel")
        panel.setFixedWidth(theme.RIGHTPANEL_W)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("SideScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = QWidget()
        inner.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        self._np_title = ElideLabel("未选择电台")
        self._np_title.setObjectName("NpTitle")
        self._np_title.setFont(theme.font(16, 700))
        self._np_title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self._np_title)

        self._np_sub = ElideLabel("")
        self._np_sub.setObjectName("NpSub")
        self._np_sub.setFont(theme.font(11, 400))
        self._np_sub.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self._np_sub)

        self._np_track = ScrollingLabel()
        self._np_track.setObjectName("NpMeta")
        self._np_track.setFont(theme.font(12, 600))
        self._np_track.setColor(theme.ACCENT)
        self._np_track.setFadeColor(theme.BG_SIDEBAR)
        self._np_track.set_copy_on_click(True)
        lay.addWidget(self._np_track)

        # ---- spectrum --------------------------------------------------
        lay.addWidget(hline(theme.STROKE_SOFT))
        lay.addWidget(section_label("频谱 / SPECTRUM"))
        self._spectrum = SpectrumWidget(40, self)
        self._spectrum.setFixedHeight(72)
        lay.addWidget(self._spectrum)

        # ---- quality ---------------------------------------------------
        lay.addWidget(hline(theme.STROKE_SOFT))
        lay.addWidget(section_label("音质 / QUALITY"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        self._q_codec = StatRow("编码", "--")
        self._q_bitrate = StatRow("标称码率", "--")
        self._q_measured = StatRow("实测码率", "--")
        self._q_sample = StatRow("采样率", "--")
        self._q_channels = StatRow("声道", "--")
        self._q_buffer = StatRow("缓冲", "--")
        grid.addWidget(self._q_codec, 0, 0)
        grid.addWidget(self._q_bitrate, 0, 1)
        grid.addWidget(self._q_measured, 1, 0)
        grid.addWidget(self._q_sample, 1, 1)
        grid.addWidget(self._q_channels, 2, 0)
        grid.addWidget(self._q_buffer, 2, 1)
        lay.addLayout(grid)

        # ---- station info ----------------------------------------------
        lay.addWidget(hline(theme.STROKE_SOFT))
        lay.addWidget(section_label("电台信息 / STATION"))
        self._info_rows: dict[str, KeyValueRow] = {}
        for key in ("国家", "地区", "语言", "类型", "标签", "投票", "播放次数"):
            row = KeyValueRow(key, "--")
            row.set_hover_tip(key == "标签")
            self._info_rows[key] = row
            lay.addWidget(row)

        # ---- recording -------------------------------------------------
        lay.addWidget(hline(theme.STROKE_SOFT))
        lay.addWidget(section_label("录制 / RECORDING"))
        rec_row = QWidget()
        rl = QHBoxLayout(rec_row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        self._rec_button = QPushButton("开始录制")
        self._rec_button.setObjectName("RecBtn")
        self._rec_button.setCheckable(True)
        self._rec_button.setFixedHeight(28)
        self._rec_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rec_button.clicked.connect(self._toggle_record)
        rl.addWidget(self._rec_button, 1)
        self._rec_folder_btn = IconButton("folder", 28, 15, "打开录音目录")
        self._rec_folder_btn.clicked.connect(self._open_recordings)
        rl.addWidget(self._rec_folder_btn)
        lay.addWidget(rec_row)

        self._rec_status = ElideLabel("未在录制")
        self._rec_status.setFont(theme.font(10, 400, mono=True))
        self._rec_status.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-family: '{theme.mono_family()}';")
        lay.addWidget(self._rec_status)

        # ---- actions ---------------------------------------------------
        lay.addWidget(hline(theme.STROKE_SOFT))
        lay.addWidget(section_label("操作 / ACTIONS"))
        acts = QGridLayout()
        acts.setHorizontalSpacing(8)
        acts.setVerticalSpacing(8)
        self._act_fav = TextButton("收藏", "heart")
        self._act_fav.clicked.connect(self._toggle_favorite_current)
        self._act_copy = TextButton("复制地址", "external")
        self._act_copy.clicked.connect(self._copy_url)
        self._act_report = TextButton("诊断", "signal")
        self._act_report.clicked.connect(self._open_report)
        self._act_home = TextButton("官网", "globe")
        self._act_home.clicked.connect(self._open_homepage)
        acts.addWidget(self._act_fav, 0, 0)
        acts.addWidget(self._act_copy, 0, 1)
        acts.addWidget(self._act_report, 1, 0)
        acts.addWidget(self._act_home, 1, 1)
        lay.addLayout(acts)

        lay.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        return panel

    # -------------------------------------------------------------- statusbar
    def _build_statusbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("StatusBar")
        bar.setFixedHeight(theme.STATUSBAR_H)
        lay = QHBoxLayout(bar)
        # Leave room on the right for the overlay resize grip.
        lay.setContentsMargins(12, 0, 34, 0)
        lay.setSpacing(8)

        self._status_text = QLabel("就绪")
        self._status_text.setObjectName("StatusText")
        self._status_text.setFont(theme.font(11, 400, mono=True))
        lay.addWidget(self._status_text)

        lay.addSpacing(8)
        self._proxy_btn = QPushButton()
        self._proxy_btn.setObjectName("Flat")
        self._proxy_btn.setFixedHeight(18)
        self._proxy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._proxy_btn.setIconSize(QSize(12, 12))
        self._proxy_btn.setFont(theme.font(10, 500, mono=True))
        self._proxy_btn.clicked.connect(self._open_preferences)
        lay.addWidget(self._proxy_btn)

        lay.addStretch(1)

        self._status_center = QLabel("")
        self._status_center.setObjectName("StatusText")
        self._status_center.setFont(theme.font(11, 400, mono=True))
        lay.addWidget(self._status_center)

        lay.addStretch(1)

        cap = QLabel("缓冲")
        cap.setObjectName("CardLabel")
        cap.setFont(theme.label_font(8, 700, 1.0))
        lay.addWidget(cap)
        self._buffer_bar = MiniBar(self)
        lay.addWidget(self._buffer_bar)

        self._status_right = QLabel("--")
        self._status_right.setObjectName("StatusText")
        self._status_right.setFont(theme.font(11, 400, mono=True))
        self._status_right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self._status_right)

        return bar

    # ================================================================== #
    #  wiring
    # ================================================================== #
    def _wire(self) -> None:
        self.titlebar.minimize_clicked.connect(self.showMinimized)
        self.titlebar.maximize_clicked.connect(self._toggle_max)
        self.titlebar.close_clicked.connect(self.close)

        self.search.textChanged.connect(lambda _: self._apply_filters())
        self.table.station_activated.connect(self._on_station_activated)
        self.table.favorite_toggled.connect(self._on_favorite_toggled)
        self.table.context_requested.connect(self._on_context_menu)
        self.table.selection_changed.connect(self._on_selection_changed)

        self._btn_play.clicked.connect(self._on_play_clicked)
        self._btn_stop.clicked.connect(self._on_stop_clicked)
        self._btn_prev.clicked.connect(lambda: self._step(-1))
        self._btn_next.clicked.connect(lambda: self._step(1))
        self._btn_rec.clicked.connect(self._toggle_record)

        self._volume.volume_changed.connect(self._on_volume)
        self._volume.mute_toggled.connect(self._on_mute)

        self.engine.state_changed.connect(self._on_state)
        self.engine.station_changed.connect(self._on_station_changed)
        self.engine.metadata_changed.connect(self._on_metadata)
        self.engine.error_occurred.connect(self._on_error)
        self.engine.level_changed.connect(self._level.set_level)
        self.engine.spectrum_changed.connect(self._spectrum.set_values)
        self.engine.stats_changed.connect(self._on_stats)
        self.engine.recording_changed.connect(self._on_recording_changed)
        self.engine.buffer_health.connect(self._buffer_bar.set_value)
        self.library.favorites_changed.connect(self._on_favorites_changed)
        self.library.custom_changed.connect(lambda: self._apply_filters())
        self.library.catalogue_changed.connect(lambda: self._apply_filters())
        self.library.history_changed.connect(self._refresh_sidebar_counts)

        # shortcuts
        from PySide6.QtGui import QShortcut

        QShortcut(QKeySequence("Space"), self, self._on_play_clicked)
        QShortcut(QKeySequence("Ctrl+F"), self, self.search.setFocus)
        QShortcut(QKeySequence("Ctrl+Left"), self, lambda: self._step(-1))
        QShortcut(QKeySequence("Ctrl+Right"), self, lambda: self._step(1))
        QShortcut(QKeySequence("Ctrl+R"), self, self._toggle_record)
        QShortcut(QKeySequence("Ctrl+E"), self, self._export_favorites)
        QShortcut(QKeySequence("Ctrl+Comma"), self, self._open_preferences)
        QShortcut(QKeySequence("Ctrl+N"), self, self._add_station)
        QShortcut(QKeySequence("Ctrl+D"), self, self._toggle_favorite_current)
        QShortcut(QKeySequence("Escape"), self, self._on_escape)
        QShortcut(QKeySequence("F11"), self, self._toggle_max)

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802
        et = event.type()
        if self._rz_edges and hasattr(event, "globalPosition"):
            if et in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonRelease):
                gp = event.globalPosition().toPoint()
                self._apply_manual_resize(gp)
                if et == QEvent.Type.MouseButtonRelease:
                    self._rz_edges = Qt.Edge(0)
                    if QWidget.mouseGrabber() is self:
                        self.releaseMouse()
                return True
        widget = obj if isinstance(obj, QWidget) else None
        if (widget is not None and widget.window() is self
                and not self.isMaximized() and not self.isFullScreen()
                and hasattr(event, "globalPosition")):
            # Title-bar window buttons sit on the top-right edge. Stealing
            # those presses for resize made maximize/close feel broken.
            if widget.objectName() in ("WinBtn", "WinBtnClose"):
                return super().eventFilter(obj, event)
            gp = event.globalPosition().toPoint()
            edges = self._resize_edges_at(gp)
            if self._in_resize_corner(gp):
                edges = Qt.Edge.RightEdge | Qt.Edge.BottomEdge
            if et == QEvent.Type.MouseMove:
                self._apply_resize_cursor(edges)
            elif (et == QEvent.Type.MouseButtonPress
                    and event.button() == Qt.MouseButton.LeftButton
                    and edges):
                self._begin_edge_resize(gp, edges)
                return True
        if et == QEvent.Type.Leave and obj is self and not self._rz_edges:
            self.unsetCursor()
        return super().eventFilter(obj, event)

    def _platform_geo(self) -> QRect:
        """HWND rect in logical pixels. Qt geometry can lie after un-maximize."""
        native = _win32_hwnd_rect(int(self.winId()))
        if not native:
            return QRect(self.geometry())
        dpr = float(self.devicePixelRatioF() or 1.0)
        l, t, r, b = native
        return QRect(
            int(round(l / dpr)), int(round(t / dpr)),
            int(round((r - l) / dpr)), int(round((b - t) / dpr)),
        )

    def _set_platform_geo(self, rect: QRect, restore_state: bool = False) -> None:
        w = max(self.minimumWidth(), rect.width())
        h = max(self.minimumHeight(), rect.height())
        x, y = rect.x(), rect.y()
        try:
            import ctypes
            hwnd = int(self.winId())
            if restore_state:
                ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            dpr = float(self.devicePixelRatioF() or 1.0)
            ctypes.windll.user32.SetWindowPos(
                hwnd, 0,
                int(round(x * dpr)), int(round(y * dpr)),
                int(round(w * dpr)), int(round(h * dpr)),
                0x0004 | 0x0020,  # SWP_NOZORDER | SWP_FRAMECHANGED
            )
        except Exception:
            pass
        self.resize(w, h)
        self.move(x, y)

    def _begin_edge_resize(self, gp: QPoint, edges) -> None:
        if self.isMaximized() or self.isFullScreen() or not edges:
            return
        self._rz_origin = QPoint(gp)
        self._rz_geo = QRect(self._platform_geo())
        self._rz_edges = edges
        self.grabMouse()

    def _apply_manual_resize(self, gp: QPoint) -> None:
        dx = gp.x() - self._rz_origin.x()
        dy = gp.y() - self._rz_origin.y()
        g = QRect(self._rz_geo)
        minw, minh = self.minimumWidth(), self.minimumHeight()
        x, y, w, h = g.x(), g.y(), g.width(), g.height()
        if self._rz_edges & Qt.Edge.LeftEdge:
            w = max(minw, w - dx)
            x = g.x() + g.width() - w
        if self._rz_edges & Qt.Edge.RightEdge:
            w = max(minw, g.width() + dx)
        if self._rz_edges & Qt.Edge.TopEdge:
            h = max(minh, h - dy)
            y = g.y() + g.height() - h
        if self._rz_edges & Qt.Edge.BottomEdge:
            h = max(minh, g.height() + dy)
        self._set_platform_geo(QRect(x, y, w, h))

    def _in_resize_corner(self, gp: QPoint) -> bool:
        if self.isMaximized() or self.isFullScreen():
            return False
        r = self._platform_geo()
        return gp.x() >= r.x() + r.width() - 36 and gp.y() >= r.y() + r.height() - 36

    def _resize_edges_at(self, gp: QPoint):
        """Which Qt.Edge values the global point sits on, or 0.

        Hit-test against the visible client, not the HWND, so DPI / DWM
        padding cannot turn the whole title bar into a top-resize strip.
        Keep the band thin so the title bar stays a move handle.
        """
        if self.isMaximized() or self.isFullScreen():
            return Qt.Edge(0)
        origin = self.mapToGlobal(QPoint(0, 0))
        x = gp.x() - origin.x()
        y = gp.y() - origin.y()
        w, h = self.width(), self.height()
        b = 6
        edges = Qt.Edge(0)
        if x < b:
            edges |= Qt.Edge.LeftEdge
        if x >= w - b:
            edges |= Qt.Edge.RightEdge
        if y < b:
            edges |= Qt.Edge.TopEdge
        if y >= h - b:
            edges |= Qt.Edge.BottomEdge
        return edges

    def _apply_resize_cursor(self, edges) -> None:
        # Always set the window cursor, never a child's: a SizeVer left on
        # the title bar was inherited by the empty drag area.
        left = bool(edges & Qt.Edge.LeftEdge)
        right = bool(edges & Qt.Edge.RightEdge)
        top = bool(edges & Qt.Edge.TopEdge)
        bottom = bool(edges & Qt.Edge.BottomEdge)
        if (left and top) or (right and bottom):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif (right and top) or (left and bottom):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif left or right:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif top or bottom:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()

    def _place_resize_corner(self) -> None:
        c = getattr(self, "_resize_corner", None)
        if c is None:
            return
        c.move(self.width() - c.width(), self.height() - c.height())
        c.raise_()
        c.setVisible(not self.isMaximized() and not self.isFullScreen())

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._place_resize_corner()

    def _restore_session_ui(self) -> None:
        """Apply persisted chrome that widgets do not read on their own.

        The library already holds last session's filters, mute and spectrum
        flag. Without this pass the sidebar highlight, chips, country combo
        and mute state always boot as defaults even when userdata says otherwise.
        """
        section = self.library.get("genre", "all") or "all"
        self._section = section
        if section in self._nav_items:
            self._set_nav(section)

        self._fav_chip.blockSignals(True)
        self._fav_chip.setChecked(bool(self.library.get("favorites_only", False)))
        self._fav_chip.blockSignals(False)

        self._zh_chip.blockSignals(True)
        self._zh_chip.setChecked(bool(self.library.get("zh_only", False)))
        self._zh_chip.blockSignals(False)

        country = self.library.get("country", "all") or "all"
        cidx = self._country_combo.findData(country)
        self._country_combo.blockSignals(True)
        if cidx >= 0:
            self._country_combo.setCurrentIndex(cidx)
        else:
            self._country_combo.setCurrentIndex(0)
            if country != "all":
                self.library.set("country", "all", save=False)
        self._country_combo.blockSignals(False)

        muted = bool(self.library.get("muted", False))
        self._volume.set_muted(muted)
        self.engine.set_muted(muted)

        self._spectrum.setVisible(bool(self.library.get("show_spectrum", True)))

    # ================================================================== #
    #  data flow
    # ================================================================== #
    def _apply_filters(self, select_last: bool = False, keep_page: bool = False) -> None:
        text = self.search.text().strip()
        country = self._country_combo.currentData() or "all"
        min_br = 128 if self._quality_chip.isChecked() else int(self.library.get("min_bitrate", 0))
        rows = self.library.query(
            section=self._section,
            text=text,
            country=country,
            min_bitrate=min_br,
            favorites_only=self._fav_chip.isChecked(),
            zh_only=self._zh_chip.isChecked(),
            sort=self._sort_combo.currentData() or "score",
        )
        self._filtered_rows = rows
        if select_last and self.engine.station:
            # Jump to the page holding the playing station before selecting it.
            url = self.engine.station.get("url", "")
            size = self._page_size()
            for i, r in enumerate(rows):
                if r.get("url") == url:
                    self._page = i // size
                    break
            else:
                self._page = 0
        elif not keep_page:
            self._page = 0
        self._show_page()
        self._count_label.setText(f"{len(rows)} / {len(self.library.all_stations())}")
        self._update_status()

        if select_last and self.engine.station:
            self.table.select_url(self.engine.station.get("url", ""))
        elif self.model.rows and not self.table.currentIndex().isValid():
            self.table.setCurrentIndex(self.model.index(0, 1))
        if self.engine.station:
            self._show_station_detail(self.engine.station)

    # -- pagination ------------------------------------------------------
    def _page_size(self) -> int:
        return int(self._page_size_combo.currentData() or 30)

    def _page_count(self) -> int:
        size = self._page_size()
        return max(1, (len(self._filtered_rows) + size - 1) // size)

    def _show_page(self) -> None:
        pages = self._page_count()
        self._page = max(0, min(self._page, pages - 1))
        size = self._page_size()
        start = self._page * size
        self.model.set_rows(self._filtered_rows[start:start + size])
        self.model.set_playing(
            self.engine.station.get("url", "") if self.engine.state != "idle" else "",
            self.engine.station.get("url", "") if self.engine.state == "connecting" else "",
        )
        self._page_label.setText(f"{self._page + 1} / {pages}")
        at_start = self._page <= 0
        at_end = self._page >= pages - 1
        self._page_first.setEnabled(not at_start)
        self._page_prev.setEnabled(not at_start)
        self._page_next.setEnabled(not at_end)
        self._page_last.setEnabled(not at_end)
        total = len(self._filtered_rows)
        if total == 0:
            self._page_range.setText("0")
        else:
            lo = start + 1
            hi = min(start + size, total)
            self._page_range.setText(f"{lo}–{hi}  ·  {total}")

    def _goto_page(self, page: int) -> None:
        page = max(0, min(page, self._page_count() - 1))
        if page == self._page:
            return
        self._page = page
        self._show_page()
        if self.model.rows:
            self.table.setCurrentIndex(self.model.index(0, 1))

    def _on_page_size(self) -> None:
        old_size = int(self.library.get("page_size", 30) or 30)
        first = self._page * old_size           # keep the same anchor row in view
        new_size = self._page_size()
        self.library.set("page_size", new_size, save=False)
        self._page = first // new_size
        self._show_page()
        if self.model.rows:
            self.table.setCurrentIndex(self.model.index(0, 1))

    def select_station(self, url: str) -> None:
        """Jump to the page containing `url` and select the row there."""
        size = self._page_size()
        for i, r in enumerate(self._filtered_rows):
            if r.get("url") == url:
                page = i // size
                if page != self._page:
                    self._page = page
                    self._show_page()
                break
        self.table.select_url(url)

    def _refresh_sidebar_counts(self) -> None:
        counts = {
            "all": len(self.library.stations) + len(self.library.custom),
            "favorites": len(self.library.favorites),
            "recent": len(self.library.history),
            "top": len(self.library.most_played()),
            "custom": len(self.library.custom),
            "zh": sum(1 for s in self.library.all_stations() if s.get("zh")),
        }
        for key, item in self._nav_items.items():
            if key in counts:
                item.set_count(counts[key])
        self._update_status()

    def _update_status(self) -> None:
        stats = self.library.stats()
        self._status_center.setText(
            f"电台库 {stats['builtin']} · 自建 {stats['custom']} · "
            f"收藏 {stats['favorites']} · 覆盖 {stats['countries']} 个国家/地区"
        )

    def _update_proxy_indicator(self) -> None:
        """Keep the active proxy visible; unreachable stations are often a proxy issue."""
        cfg = self.engine.proxy
        if cfg is None or cfg.mode == "none":
            self._proxy_btn.setText("  代理：关闭")
            self._proxy_btn.setIcon(icons.icon("globe", 12, theme.TEXT_MUTED))
            self._proxy_btn.setToolTip("当前不使用代理，点击打开网络设置")
            self._proxy_btn.setStyleSheet(
                f"color: {theme.TEXT_MUTED}; font-family: '{theme.mono_family()}'; font-size: 10px;")
        elif cfg.usable:
            self._proxy_btn.setText(f"  代理：{cfg.host}:{cfg.port}")
            self._proxy_btn.setIcon(icons.icon("globe", 12, theme.ACCENT))
            self._proxy_btn.setToolTip(f"{cfg.describe()}\n点击打开网络设置")
            self._proxy_btn.setStyleSheet(
                f"color: {theme.ACCENT}; font-family: '{theme.mono_family()}'; font-size: 10px;")
        else:
            self._proxy_btn.setText("  代理：未检测到")
            self._proxy_btn.setIcon(icons.icon("globe", 12, theme.WARN))
            self._proxy_btn.setToolTip(
                (cfg.unresolved or "未检测到系统代理") + "\n点击打开网络设置"
            )
            self._proxy_btn.setStyleSheet(
                f"color: {theme.WARN}; font-family: '{theme.mono_family()}'; font-size: 10px;")

    # ================================================================== #
    #  selection / detail
    # ================================================================== #
    def _restore_last_station(self) -> None:
        """Re-show (and optionally resume) the station from the previous session."""
        url = self.library.get("last_station", "")
        if not url:
            return
        station = self.library.find(url)
        if not station:
            return
        self._show_station_detail(station)
        self._mini_title.setText(station.get("name", ""))
        self.select_station(url)
        if self.library.get("resume_last", True):
            QTimer.singleShot(400, lambda: self.engine.tune(station))

    def _on_selection_changed(self, station) -> None:
        if station:
            self._show_station_detail(station)

    def _show_station_detail(self, station: dict) -> None:
        name = station.get("name", "")
        country = station.get("country", "") or "未知"
        genre = GENRE_ZH.get(station.get("genre", ""), station.get("genre", ""))
        self._np_title.setText(name)
        self._np_sub.setText(" · ".join([b for b in [country, genre] if b]))

        self._info_rows["国家"].set_value(country)
        self._info_rows["地区"].set_value(station.get("state", "") or "--")
        self._info_rows["语言"].set_value(station.get("language", "") or "--")
        self._info_rows["类型"].set_value(genre)
        self._info_rows["标签"].set_value(station.get("tags", "") or "--")
        votes = int(station.get("votes") or 0)
        self._info_rows["投票"].set_value(str(votes) if votes else "--")
        count = self.library.play_count(station.get("url", ""))
        self._info_rows["播放次数"].set_value(str(count) if count else "0")

        br = int(station.get("bitrate") or 0)
        self._q_codec.set_value((station.get("codec") or "--").upper())
        self._q_bitrate.set_value(f"{br} kbps" if br else "未知")
        sr = station.get("sample_rate") or ""
        self._q_sample.set_value(f"{sr} Hz" if sr else "--")
        ch = int(station.get("channels") or 0)
        self._q_channels.set_value({1: "单声道", 2: "立体声"}.get(ch, "--"))

        url = station.get("url", "")
        fav = self.library.is_favorite(url)
        self._act_fav.setText("已收藏" if fav else "收藏")
        self._act_fav.setIcon(icons.icon("heart_filled" if fav else "heart", 14,
                                         theme.REC if fav else theme.TEXT_DIM))
        self._act_home.setEnabled(bool(station.get("homepage")))

    def _current_station(self) -> dict | None:
        idx = self.table.currentIndex()
        if idx.isValid():
            station = self.model.station_at(idx.row())
            if station:
                return station
        return self.engine.station or None

    # ================================================================== #
    #  playback
    # ================================================================== #
    def _halt_playback(self) -> None:
        """User-initiated stop. Retune must not go through here or the sleep timer resets."""
        self.engine.stop()
        self._play_started = 0.0
        self._sleep_deadline = 0.0
        self._history_recorded_url = ""

    def _on_station_activated(self, station: dict) -> None:
        if station.get("url") == self.engine.station.get("url") and self.engine.state == "playing":
            self._halt_playback()
            return
        self.engine.tune(station)

    def _on_play_clicked(self) -> None:
        if self.engine.state in ("playing", "buffering", "connecting"):
            self._halt_playback()
            return
        station = self._current_station()
        if station:
            self.engine.tune(station)
        else:
            info(self, "没有选中电台", "请先在列表中选择一个电台。")

    def _on_stop_clicked(self) -> None:
        self._halt_playback()

    def _step(self, delta: int) -> None:
        """Tune the previous/next station across the whole filtered list,
        turning pages as needed."""
        rows = self._filtered_rows
        if not rows:
            return
        url = self.engine.station.get("url", "")
        current = next((i for i, r in enumerate(rows) if r.get("url") == url), -1)
        if current < 0:
            sel = self.table.currentIndex().row()
            current = self._page * self._page_size() + (sel if sel >= 0 else 0)
        nxt = (current + delta) % len(rows)
        size = self._page_size()
        page = nxt // size
        if page != self._page:
            self._page = page
            self._show_page()
        station = rows[nxt]
        row_in_page = nxt - self._page * size
        self.table.setCurrentIndex(self.model.index(row_in_page, 1))
        self.table.scrollTo(self.model.index(row_in_page, 1))
        self.engine.tune(station)

    def _on_volume(self, value: int) -> None:
        self.engine.set_volume(value)
        self.library.set("volume", value, save=False)

    def _on_mute(self, muted: bool) -> None:
        self.engine.set_muted(muted)
        self.library.set("muted", muted, save=False)

    # -- engine callbacks --------------------------------------------------
    def _on_state(self, state: str) -> None:
        labels = {
            "idle": "已停止", "connecting": "正在连接 …", "buffering": "缓冲中 …",
            "playing": "播放中", "error": "播放错误",
        }
        self._status_text.setText(labels.get(state, state))
        self._sync_tray()
        obj = "StatusTextLive" if state == "playing" else "StatusText"
        self._status_text.setObjectName(obj)
        self._status_text.setStyleSheet(
            f"color: {theme.ACCENT if state == 'playing' else theme.TEXT_MUTED};"
            f"font-family: '{theme.mono_family()}'; font-size: 11px;"
        )
        self._status_text.style().unpolish(self._status_text)
        self._status_text.style().polish(self._status_text)

        playing = state in ("playing", "buffering")
        self._btn_play.set_icon_name("pause" if playing else "play")
        self._mini_indicator.set_active(state == "playing")
        self._spectrum.set_active(state == "playing")

        if state == "idle":
            # Keep the last station on screen when playback stops: an operator
            # needs to see what was tuned, not a blank panel.
            if self.engine.station:
                self._mini_track.setText("")
                self._np_track.setText("")
            else:
                self._mini_title.setText("未选择电台")
                self._mini_meta.setText("从左侧列表中选择一个电台开始收听")
                self._mini_track.setText("")
                self._np_track.setText("")
            self._mini_time.setText("00:00:00")
            self._q_measured.set_value("--")
            self._q_buffer.set_value("--")
            self._buffer_bar.set_value(0.0)
            self._status_right.setText("--")
            self.model.set_playing("", "")
        else:
            self.model.set_playing(
                self.engine.station.get("url", "") if state in ("playing", "buffering") else "",
                self.engine.station.get("url", "") if state == "connecting" else "",
            )

        if state == "playing":
            url = self.engine.station.get("url", "") if self.engine.station else ""
            if url and url != self._history_recorded_url:
                self.library.record_play(self.engine.station)
                self._history_recorded_url = url
                self._refresh_sidebar_counts()
            if self._play_started == 0.0:
                self._play_started = time.time()
                self._arm_sleep_timer()

    def _on_station_changed(self, station: dict) -> None:
        self._show_station_detail(station)
        self.library.set("last_station", station.get("url", ""), save=False)
        self._mini_title.setText(station.get("name", ""))
        bits = []
        if station.get("country"):
            bits.append(station["country"])
        if station.get("genre"):
            bits.append(GENRE_ZH.get(station["genre"], station["genre"]))
        if station.get("codec"):
            bits.append((station["codec"] or "").upper())
        if station.get("bitrate"):
            bits.append(f"{station['bitrate']} kbps")
        self._mini_meta.setText(" · ".join(bits))
        self.model.refresh_row(station.get("url", ""))

    def _on_metadata(self, title: str) -> None:
        title = decode_stream_title(title)
        prev = self._mini_track.fullText()
        self._mini_track.setText(title)
        self._np_track.setText(title)
        self._sync_tray()
        if (title and title != prev
                and bool(self.library.get("notify_track", False))
                and self.tray is not None):
            station = self.engine.station.get("name", "") if self.engine.station else ""
            self.tray.notify(station or paths.APP_TITLE, title)

    def _on_error(self, message: str) -> None:
        retrying = "自动重连" in (message or "")
        color = theme.WARN if retrying else theme.REC
        self._status_text.setText(message)
        self._status_text.setStyleSheet(
            f"color: {color}; font-family: '{theme.mono_family()}'; font-size: 11px;")
        self._mini_track.setText(message)
        self._np_track.setText(message)

    def _on_stats(self, stats: dict) -> None:
        kbps = stats.get("kbps", 0.0)
        self._q_measured.set_value(f"{kbps:.0f} kbps" if kbps else "--")
        rate = int(stats.get("encoded_rate") or 0)
        if rate:
            self._q_sample.set_value(f"{rate} Hz")
        ch = int(stats.get("encoded_channels") or 0)
        if ch:
            self._q_channels.set_value({1: "单声道", 2: "立体声"}.get(ch, f"{ch} 声道"))
        buf = stats.get("buffer", 0)
        self._q_buffer.set_value(f"{buf/1024:.0f} KB")
        dropped = stats.get("dropped", 0)
        elapsed = stats.get("elapsed", 0.0)
        self._mini_time.setText(
            f"{int(elapsed//3600):02d}:{int(elapsed%3600//60):02d}:{int(elapsed%60):02d}")
        self._status_right.setText(
            f"{kbps:.0f} kbps  缓冲 {buf/1024:.0f} KB  丢帧 {dropped/1024:.0f} KB"
        )

    def _on_favorites_changed(self) -> None:
        self._refresh_sidebar_counts()
        if self._section == "favorites":
            self._apply_filters()
        station = self._current_station()
        if station:
            self._show_station_detail(station)
        self.table.viewport().update()

    # ================================================================== #
    #  favourites / stations
    # ================================================================== #
    def _on_favorite_toggled(self, url: str) -> None:
        self.library.toggle_favorite(url)
        self.model.refresh_row(url)
        self.table.viewport().update()

    def _toggle_favorite_current(self) -> None:
        station = self._current_station()
        if not station:
            if not self.isVisible() and self.tray is not None and self.tray.available:
                self.tray.notify(paths.APP_TITLE, "当前没有正在播放的电台")
            return
        url = station.get("url", "")
        was_fav = self.library.is_favorite(url)
        self._on_favorite_toggled(url)
        self._show_station_detail(station)
        if not self.isVisible() and self.tray is not None and self.tray.available:
            verb = "已取消收藏" if was_fav else "已收藏"
            self.tray.notify(paths.APP_TITLE, f"{verb}：{station.get('name', '')}")

    def _copy_url(self) -> None:
        station = self._current_station()
        if station:
            QApplication.clipboard().setText(station.get("url", ""))
            self._status_text.setText("已复制流地址")

    def _open_homepage(self) -> None:
        station = self._current_station()
        if station and station.get("homepage"):
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(station["homepage"]))

    def _recordings_dir(self) -> str:
        """The directory recordings go to, resolved and guaranteed to exist.

        Falls back to a writable location when the preferred one cannot be
        created, so a locked-down or missing Music folder never leaves the
        user with a dead button and no explanation.
        """
        wanted = paths.recordings_dir(self.library.get("recordings_dir") or "")
        if _ensure_dir(wanted):
            return wanted
        fallback = os.path.join(paths.app_dir(), "recordings")
        if fallback != wanted and _ensure_dir(fallback):
            self._status_text.setText(f"原录音目录不可写，已改用 {fallback}")
            return fallback
        return wanted

    def _open_recordings(self) -> None:
        path = self._recordings_dir()
        if not os.path.isdir(path):
            self._status_text.setText(f"无法创建录音目录：{path}")
            return
        if _reveal_in_file_manager(path):
            self._status_text.setText(f"已打开 {path}")
        else:
            # Last resort: tell the user where it is and copy the path.
            QApplication.clipboard().setText(path)
            self._status_text.setText(f"无法打开文件管理器，路径已复制：{path}")

    def _open_report(self) -> None:
        station = self._current_station()
        if station:
            ReportDialog(self, station, self.engine).exec()

    def _add_station(self) -> None:
        dlg = StationDialog(self, None, self.engine)
        if dlg.exec() and dlg.result_station:
            station = self.library.add_custom(dlg.result_station)
            self._section = "custom"
            self._set_nav("custom")
            self._apply_filters()
            self.select_station(station.get("url", ""))

    def _edit_station(self, station: dict) -> None:
        dlg = StationDialog(self, station, self.engine)
        if dlg.exec() and dlg.result_station:
            self.library.update_custom(station.get("id", ""), dlg.result_station)
            self._apply_filters()

    def _delete_station(self, station: dict) -> None:
        if confirm(self, "删除电台", f"确定要从自建电台中删除「{station.get('name', '')}」吗？", danger=True):
            self.library.remove_custom(station.get("id", ""))
            self._apply_filters()

    def _export_favorites(self) -> None:
        if not self.library.favorites:
            info(self, "没有收藏", "请先收藏一些电台，再导出播放列表。")
            return
        dlg = ExportDialog(self, self.library)
        if dlg.exec() and dlg.path:
            self._status_text.setText(f"已导出到 {dlg.path}")

    def _open_preferences(self) -> None:
        dlg = PreferencesDialog(self, self.library, self.engine)
        if dlg.exec():
            dlg.apply()
            self.engine.set_proxy(self.library.proxy_config())
            self._update_proxy_indicator()
            self._fav_chip.setChecked(bool(self.library.get("favorites_only", False)))
            self._zh_chip.setChecked(bool(self.library.get("zh_only", False)))
            self._spectrum.setVisible(bool(self.library.get("show_spectrum", True)))
            idx = self._sort_combo.findData(self.library.get("sort", "score"))
            if idx >= 0:
                self._sort_combo.setCurrentIndex(idx)
            cidx = self._country_combo.findData(self.library.get("country", "all") or "all")
            self._country_combo.blockSignals(True)
            self._country_combo.setCurrentIndex(cidx if cidx >= 0 else 0)
            self._country_combo.blockSignals(False)
            muted = bool(self.library.get("muted", False))
            self._volume.set_muted(muted)
            self.engine.set_muted(muted)
            self._arm_sleep_timer(restart=True)
            self._apply_filters()

    # ================================================================== #
    #  recording
    # ================================================================== #
    def _inform(self, title: str, message: str) -> None:
        """Tell the user something, wherever they currently are.

        A modal dialog on a window that is hidden in the tray is invisible
        and blocks nothing the user can see, so tray-initiated actions fall
        back to a balloon notification instead.
        """
        if self.isVisible():
            info(self, title, message)
        elif self.tray is not None and self.tray.available:
            self.tray.notify(title, message)

    def _toggle_record(self) -> None:
        if self.engine.is_recording:
            path = self.engine.stop_recording()
            self._btn_rec.setChecked(False)
            self._rec_button.setChecked(False)
            if path:
                self._status_text.setText(f"录音已保存：{path}")
                if not self.isVisible() and self.tray is not None and self.tray.available:
                    self.tray.notify(paths.APP_TITLE,
                                     f"录音已保存：{os.path.basename(path)}")
        else:
            if self.engine.state not in ("playing", "buffering"):
                self._inform("无法录制", "请先播放一个电台，再开始录制。")
                self._btn_rec.setChecked(False)
                self._rec_button.setChecked(False)
                return
            if self.engine.start_recording():
                self._record_started = time.time()
                self._btn_rec.setChecked(True)
                self._rec_button.setChecked(True)
                if not self.isVisible() and self.tray is not None and self.tray.available:
                    self.tray.notify(paths.APP_TITLE, "已开始录制")

    def _on_recording_changed(self, active: bool, path: str) -> None:
        self._btn_rec.setChecked(active)
        self._rec_button.setChecked(active)
        self._rec_button.setText("停止录制" if active else "开始录制")
        self._sync_tray()
        if active:
            name = os.path.basename(path) if path else ""
            self._rec_status.setText(f"录制中 · {name}")
            self._rec_status.setStyleSheet(
                f"color: {theme.REC}; font-family: '{theme.mono_family()}'; font-size: 10px;")
        else:
            self._record_started = 0.0
            if path:
                size = os.path.getsize(path) / 1048576 if os.path.exists(path) else 0
                self._rec_status.setText(f"已保存 · {os.path.basename(path)} · {size:.1f} MB")
                self._rec_status.setStyleSheet(
                    f"color: {theme.GOOD}; font-family: '{theme.mono_family()}'; font-size: 10px;")
            else:
                self._rec_status.setText("未在录制")
                self._rec_status.setStyleSheet(
                    f"color: {theme.TEXT_MUTED}; font-family: '{theme.mono_family()}'; font-size: 10px;")

    # ================================================================== #
    #  filters / nav
    # ================================================================== #
    def _on_nav(self, key: str) -> None:
        self._section = key
        self._set_nav(key)
        self.library.set("genre", key, save=False)
        self._apply_filters()

    def _set_nav(self, key: str) -> None:
        for nav_key, item in self._nav_items.items():
            item.set_selected(nav_key == key)

    def _on_country(self) -> None:
        country = self._country_combo.currentData() or "all"
        self.library.set("country", country, save=False)
        self._apply_filters()

    def _on_quality(self) -> None:
        self._apply_filters()

    def _on_fav_filter(self) -> None:
        self.library.set("favorites_only", self._fav_chip.isChecked(), save=False)
        self._apply_filters()

    def _on_zh_filter(self) -> None:
        self.library.set("zh_only", self._zh_chip.isChecked(), save=False)
        self._apply_filters()

    def _on_sort(self) -> None:
        self.library.set("sort", self._sort_combo.currentData(), save=False)
        self._apply_filters()

    # ================================================================== #
    #  context menu
    # ================================================================== #
    def _on_context_menu(self, station, global_pos) -> None:
        if station is None:
            return
        menu = QMenu(self)
        menu.setStyleSheet(theme.stylesheet())
        url = station.get("url", "")

        act_play = QAction("播放", self)
        act_play.triggered.connect(lambda: self.engine.tune(station))
        menu.addAction(act_play)

        fav_label = "取消收藏" if self.library.is_favorite(url) else "加入收藏"
        act_fav = QAction(fav_label, self)
        act_fav.triggered.connect(lambda: self._on_favorite_toggled(url))
        menu.addAction(act_fav)

        act_copy = QAction("复制流地址", self)
        act_copy.triggered.connect(lambda: QApplication.clipboard().setText(url))
        menu.addAction(act_copy)

        if station.get("homepage"):
            act_home = QAction("打开官网", self)
            act_home.triggered.connect(lambda: self._open_homepage_for(station))
            menu.addAction(act_home)

        menu.addSeparator()
        act_report = QAction("连接诊断", self)
        act_report.triggered.connect(lambda: ReportDialog(self, station, self.engine).exec())
        menu.addAction(act_report)

        if station.get("custom"):
            menu.addSeparator()
            act_edit = QAction("编辑电台", self)
            act_edit.triggered.connect(lambda: self._edit_station(station))
            menu.addAction(act_edit)
            act_del = QAction("删除电台", self)
            act_del.triggered.connect(lambda: self._delete_station(station))
            menu.addAction(act_del)

        menu.exec(global_pos)

    def _open_homepage_for(self, station: dict) -> None:
        if station.get("homepage"):
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(station["homepage"]))

    # ================================================================== #
    #  sleep timer / clock
    # ================================================================== #
    def _arm_sleep_timer(self, restart: bool = False) -> None:
        minutes = int(self.library.get("sleep_minutes", 0) or 0)
        if minutes <= 0:
            self._sleep_deadline = 0.0
            return
        # Keep an already-running timer across station changes. Prefs apply
        # passes restart=True so a newly chosen duration takes effect.
        if not restart and self._sleep_deadline > time.time():
            return
        if self.engine.state in ("playing", "buffering"):
            self._sleep_deadline = time.time() + minutes * 60
        elif restart:
            self._sleep_deadline = 0.0

    def _tick(self) -> None:
        if self.engine.state == "playing" and self.engine.is_recording and self._record_started:
            elapsed = time.time() - self._record_started
            size = 0
            rec = getattr(self.engine, "_recorder", None)
            if rec is not None:
                size = rec.size
            self._rec_status.setText(
                f"录制中 · {int(elapsed//60):02d}:{int(elapsed%60):02d} · {size/1048576:.1f} MB")

        if self._sleep_deadline:
            remaining = self._sleep_deadline - time.time()
            if remaining <= 0:
                self._sleep_deadline = 0.0
                self._play_started = 0.0
                action = self.library.get("sleep_action", "stop")
                if action == "quit":
                    self._really_quit = True
                    self.close()
                else:
                    self.engine.stop()
                    self._status_text.setText("定时器到时，已停止播放")
            elif self.engine.state == "playing":
                mins, secs = divmod(int(remaining), 60)
                self._status_text.setText(f"播放中 · 定时关闭 {mins:02d}:{secs:02d}")

    def _on_escape(self) -> None:
        if self.search.text():
            self.search.clear()
        else:
            self.search.clearFocus()

    # ================================================================== #
    #  window chrome
    # ================================================================== #
    def _toggle_max(self) -> None:
        before = self.isMaximized()
        if before:
            ng = self.normalGeometry()
            # showNormal() on this frameless chrome either keeps the
            # work-area size or gets immediately re-maximized by a queued
            # WindowStateChange. Hold the restoring flag so changeEvent
            # can swallow that echo, then apply the floating rect.
            self._restoring_normal = True
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMaximized)
            if (ng.isValid()
                    and ng.width() >= self.minimumWidth()
                    and ng.height() >= self.minimumHeight()):
                self._set_platform_geo(QRect(ng), restore_state=True)
            QTimer.singleShot(0, lambda n=QRect(ng): self._finish_restore_normal(n))
        else:
            self.showMaximized()
        self.titlebar.set_maximized(self.isMaximized())

    def _finish_restore_normal(self, ng) -> None:
        if self.isMaximized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMaximized)
        if ng.isValid() and ng.width() >= self.minimumWidth() and ng.height() >= self.minimumHeight():
            # Always push the HWND even when Qt already reports the wanted
            # size: after un-maximize the native window can stay work-area
            # sized while geometry() pretends it shrank.
            self._set_platform_geo(QRect(ng), restore_state=True)
        self.titlebar.set_maximized(False)
        # Keep _restoring_normal until the next event-loop turn so a queued
        # maximize echo (observed immediately after this) is still swallowed.
        QTimer.singleShot(0, self._clear_restoring_normal)

    def _clear_restoring_normal(self) -> None:
        if self._restoring_normal and self.isMaximized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMaximized)
        self._restoring_normal = False
        self.titlebar.set_maximized(self.isMaximized())

    def _apply_window_chrome(self) -> None:
        """Hairline border + Win11 small corners when floating; flush when maximized."""
        flush = self.isMaximized() or self.isFullScreen()
        self.setProperty("chrome", "flush" if flush else "framed")
        self.style().unpolish(self)
        self.style().polish(self)
        lay = self.layout()
        if lay is not None:
            m = 0 if flush else 1
            lay.setContentsMargins(m, m, m, m)
        theme.apply_native_corners(self, rounded=not flush)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if self._pending_maximize:
            self._pending_maximize = False
            self.showMaximized()
            self.titlebar.set_maximized(True)
        self._apply_window_chrome()

    def changeEvent(self, event):  # noqa: N802
        super().changeEvent(event)
        if event.type() == event.Type.WindowStateChange:
            if self._restoring_normal and self.isMaximized():
                self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMaximized)
                return
            self.titlebar.set_maximized(self.isMaximized())
            self._place_resize_corner()
            self._apply_window_chrome()
            # Defer to the next event-loop turn: the minimised state must be
            # fully applied before we hide, or the taskbar button lingers.
            if self.isMinimized():
                QTimer.singleShot(0, self._minimize_to_tray)

    # ================================================================== #
    #  tray
    # ================================================================== #
    def _build_tray(self) -> None:
        self.setWindowIcon(appicon.app_icon())
        self.tray = TrayController(self, paths.APP_TITLE)
        if not self.tray.available:
            return
        self.tray.show_requested.connect(self._restore_from_tray)
        self.tray.quit_requested.connect(self._quit_from_tray)
        self.tray.play_pause_requested.connect(self._on_play_clicked)
        self.tray.stop_requested.connect(self._on_stop_clicked)
        self.tray.next_requested.connect(lambda: self._step(1))
        self.tray.previous_requested.connect(lambda: self._step(-1))
        self.tray.record_requested.connect(self._toggle_record)
        self.tray.favorites_requested.connect(self._toggle_favorite_current)
        self.tray.set_state(False, False, False)
        self.tray.show()

    def _restore_from_tray(self) -> None:
        """Bring the window back from the tray, preserving its previous state.

        `show()` (not `showNormal()`) keeps the maximized flag the window had
        when it was hidden, so double-clicking the tray icon no longer knocks
        a maximized window back to a floating one. When the window is already
        visible we only raise and activate it.
        """
        if self.isMinimized():
            self.setWindowState(
                (self.windowState() & ~Qt.WindowState.WindowMinimized)
                | Qt.WindowState.WindowActive)
        if not self.isVisible():
            self.show()
        if self.isMaximized():
            self.showMaximized()
        self.raise_()
        self.activateWindow()

    def _minimize_to_tray(self) -> None:
        """Hide a minimised window to the tray when that option is enabled."""
        if not bool(self.library.get("minimize_to_tray", False)):
            return
        if self.tray is None or not self.tray.available:
            return
        if not self.isMinimized():
            return
        self.hide()
        if self.library.get("tray_notifications", True):
            self.tray.notify(paths.APP_TITLE,
                             "已最小化到托盘，双击托盘图标恢复窗口。")

    def _quit_from_tray(self) -> None:
        self._really_quit = True
        from PySide6.QtWidgets import QApplication
        from .winjob import hard_exit

        QTimer.singleShot(2500, lambda: hard_exit(0))
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _sync_tray(self) -> None:
        if self.tray is None or not self.tray.available:
            return
        state = self.engine.state
        # Same rule as the nowbar pause button: buffering is still on-air.
        # Connecting stays "not playing" visually, but the tooltip says so
        # instead of calling a stop "paused" (this player has no pause).
        live = state in ("playing", "buffering")
        station = self.engine.station.get("name", "")
        track = self._mini_track.fullText()
        self.tray.set_playing(station, track, playing=live, state=state)
        url = self.engine.station.get("url", "")
        self.tray.set_state(live, self.engine.is_recording,
                            self.library.is_favorite(url) if url else False)

    # ================================================================== #
    #  window geometry / DPI
    # ================================================================== #
    def _restore_geometry(self) -> None:
        """Restore the saved size, clamped to the screen it will appear on.

        Coordinates are stored in logical pixels, so they stay meaningful when
        the display scale changes between sessions (a window saved on a 150%
        display is still usable on a 100% one).
        """
        screen = self._target_screen()
        avail = screen.availableGeometry() if screen else None

        # Apply the floating size first even when the last session was
        # maximized. showMaximized() during construction (before a normal
        # geometry exists) leaves Qt with no restore rect, so the title-bar
        # restore button would snap to the full available screen instead of
        # the size the user actually had.
        restored = False
        geo = self.library.get("window_geometry", "")
        parts = str(geo).split(",") if geo else []
        if len(parts) == 4:
            try:
                x, y, w, h = (int(p) for p in parts)
                if avail is not None:
                    # A previous session that maximized before Qt had a restore
                    # rect would persist the work-area size as "normal". Treat
                    # that as unset so restore-down does not stay full screen.
                    fullish = (w >= avail.width() - 16 and h >= avail.height() - 16)
                    if fullish:
                        restored = False
                    else:
                        w = max(self.minimumWidth(), min(w, avail.width()))
                        h = max(self.minimumHeight(), min(h, avail.height()))
                        x = max(avail.left(), min(x, avail.right() - w))
                        y = max(avail.top(), min(y, avail.bottom() - h))
                        self.setGeometry(x, y, w, h)
                        restored = True
                else:
                    self.setGeometry(x, y, w, h)
                    restored = True
            except (TypeError, ValueError):
                restored = False

        if not restored:
            self._center_default(avail)

        want_max = bool(self.library.get("window_maximized", False))
        # Maximize only after the window is shown: calling showMaximized()
        # during construction does not snapshot the floating rect as
        # normalGeometry, so the restore button kept the work-area size.
        self._pending_maximize = want_max
        self.titlebar.set_maximized(want_max)

    def _target_screen(self):
        geo = self.library.get("window_geometry", "")
        parts = str(geo).split(",") if geo else []
        if len(parts) == 4:
            try:
                x, y = int(parts[0]), int(parts[1])
                from PySide6.QtCore import QRect
                probe = QRect(x, y, 200, 200)
                for s in QGuiApplication.screens():
                    if s.availableGeometry().intersects(probe):
                        return s
            except (TypeError, ValueError):
                pass
        return QGuiApplication.primaryScreen()

    def _center_default(self, avail) -> None:
        if avail is None:
            self.resize(1400, 880)
            return
        # Size to the screen rather than a fixed pixel count, so a 4K display
        # does not open a small window and a laptop does not get one too big.
        w = min(int(avail.width() * 0.86), 1680)
        h = min(int(avail.height() * 0.88), 1000)
        w = max(self.minimumWidth(), w)
        h = max(self.minimumHeight(), h)
        self.resize(w, h)
        self.move(avail.center().x() - w // 2, avail.center().y() - h // 2)

    def _save_geometry(self) -> None:
        rect = self.normalGeometry() if self.isMaximized() else self.geometry()
        self.library.set("window_maximized", self.isMaximized(), save=False)
        if not self.isMinimized():
            self.library.set(
                "window_geometry",
                f"{rect.x()},{rect.y()},{rect.width()},{rect.height()}",
                save=False,
            )

    def reveal(self) -> None:
        """Bring a hidden/minimised window back (second-instance handoff)."""
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):  # noqa: N802
        """Hide to the tray instead of quitting, unless quitting for real."""
        self._save_geometry()
        want_tray = (self.tray is not None and self.tray.available
                     and not self._really_quit
                     and bool(self.library.get("close_to_tray", True)))
        if want_tray:
            event.ignore()
            self.hide()
            if (not self._tray_hint_shown
                    and self.library.get("tray_notifications", True)):
                self._tray_hint_shown = True
                self.tray.notify(paths.APP_TITLE,
                                 "已最小化到托盘，播放继续。右键托盘图标可操作。")
            return
        # Synchronous teardown: no daemon threads racing interpreter exit.
        from .winjob import hard_exit, kill_descendants

        QTimer.singleShot(2500, lambda: hard_exit(0))
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        self._rz_edges = Qt.Edge(0)
        if self.tray is not None:
            self.tray.hide()
        self.engine.shutdown()
        kill_descendants()
        self.library.save()
        super().closeEvent(event)
        if app is not None:
            app.quit()
