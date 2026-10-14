"""System tray integration.

Closing the window hides the application to the tray rather than quitting, so
playback continues. The tray icon carries a context menu with the transport
controls, and its tooltip shows what is currently playing.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import appicon, theme


class TrayController(QObject):
    """Owns the tray icon and its menu. Emits intents; the window acts on them."""

    show_requested = Signal()
    quit_requested = Signal()
    play_pause_requested = Signal()
    stop_requested = Signal()
    next_requested = Signal()
    previous_requested = Signal()
    record_requested = Signal()
    favorites_requested = Signal()

    def __init__(self, parent=None, title: str = "BROADCAST"):
        super().__init__(parent)
        self.title = title
        self.available = QSystemTrayIcon.isSystemTrayAvailable()

        self.icon = QSystemTrayIcon(appicon.tray_icon(theme.TEXT_FAINT), self)
        self.icon.setToolTip(title)

        self.menu = QMenu()
        self.menu.setObjectName("TrayMenu")
        # Own padding: extra left inset, compact right so the menu stays narrow
        # (the old now-playing header forced it wide).
        self.menu.setStyleSheet(
            theme.stylesheet()
            + """
QMenu#TrayMenu {
    padding: 6px 4px;
}
QMenu#TrayMenu::item {
    padding: 6px 14px 6px 18px;
}
QMenu#TrayMenu::icon {
    left: 10px;
}
QMenu#TrayMenu::separator {
    margin: 4px 12px;
}
"""
        )

        self._act_show = self._action("显示主窗口", self.show_requested, icon="external")
        self.menu.addAction(self._act_show)
        self.menu.addSeparator()

        self._act_play = self._action("播放 / 暂停", self.play_pause_requested, icon="play")
        self._act_stop = self._action("停止", self.stop_requested, icon="stop")
        self._act_prev = self._action("上一个电台", self.previous_requested, icon="prev")
        self._act_next = self._action("下一个电台", self.next_requested, icon="next")
        for a in (self._act_play, self._act_stop, self._act_prev, self._act_next):
            self.menu.addAction(a)

        self.menu.addSeparator()
        self._act_rec = self._action("开始录制", self.record_requested, icon="record_ring")
        self._act_fav = self._action("收藏当前电台", self.favorites_requested, icon="heart")
        self.menu.addAction(self._act_rec)
        self.menu.addAction(self._act_fav)

        self.menu.addSeparator()
        self._act_quit = self._action("退出", self.quit_requested, icon="power")
        self.menu.addAction(self._act_quit)

        self.icon.setContextMenu(self.menu)
        # Double-click restores the window, matching platform convention.
        self.icon.activated.connect(self._on_activated)

    # ------------------------------------------------------------------ #
    def _action(self, text: str, signal, icon: str = "") -> QAction:
        act = QAction(text, self)
        if icon:
            from . import icons
            act.setIcon(icons.icon(icon, 14, theme.TEXT_DIM))
        act.triggered.connect(signal.emit)
        return act

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.DoubleClick,
                      QSystemTrayIcon.ActivationReason.Trigger):
            self.show_requested.emit()

    # ------------------------------------------------------------------ #
    def show(self) -> None:
        if self.available:
            self.icon.show()

    def hide(self) -> None:
        self.icon.hide()

    def notify(self, title: str, message: str) -> None:
        if self.available and self.icon.isVisible() and message:
            self.icon.showMessage(title, message,
                                  QSystemTrayIcon.MessageIcon.NoIcon, 4000)

    def set_playing(self, station: str, track: str = "", playing: bool = False,
                    state: str = "") -> None:
        lines = [self.title]
        if station:
            if state in ("playing", "buffering") or (not state and playing):
                label = "播放中"
            elif state == "connecting":
                label = "正在连接"
            elif state == "error":
                label = "出错"
            else:
                label = "已停止"
            lines.append(f"{label} · {station}")
        if track:
            lines.append(track)
        self.icon.setToolTip("\n".join(lines))

    def set_state(self, playing: bool, recording: bool, is_favorite: bool) -> None:
        # The mark itself tells idle from live at a glance in the tray.
        self.icon.setIcon(appicon.tray_icon(theme.ACCENT if playing else theme.TEXT_FAINT))
        self._act_play.setText("暂停" if playing else "播放")
        from . import icons
        self._act_play.setIcon(icons.icon("pause" if playing else "play", 14, theme.TEXT_DIM))
        self._act_rec.setText("停止录制" if recording else "开始录制")
        self._act_rec.setIcon(
            icons.icon("record" if recording else "record_ring", 14,
                       theme.REC if recording else theme.TEXT_DIM))
        self._act_fav.setText("取消收藏" if is_favorite else "收藏当前电台")
        self._act_fav.setIcon(
            icons.icon("heart_filled" if is_favorite else "heart", 14,
                       theme.REC if is_favorite else theme.TEXT_DIM))
