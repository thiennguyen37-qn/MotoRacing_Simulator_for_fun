from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout, QLabel,
                              QFrame, QScrollArea, QWidget)
from PyQt6.QtGui import QFont, QPainter, QColor
from PyQt6.QtCore import Qt

from app.widgets.video_bg import VideoBackground


class _TrackRow(QFrame):
    _SS = """
        QFrame {{
            background: {bg};
            border: 1px solid {border};
            border-radius: 8px;
        }}
        QLabel {{ background: transparent; border: none; }}
    """

    def __init__(self, idx: int, title: str, artist: str):
        super().__init__()
        self._focused = False
        self._playing = False
        self.setFixedHeight(68)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(16)

        num = QLabel(f'{idx + 1:02d}')
        num.setFont(QFont('Consolas', 11))
        num.setStyleSheet('color: #ffffff; background: transparent; border: none;')
        num.setFixedWidth(28)
        num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(num)

        texts = QVBoxLayout()
        texts.setSpacing(3)

        self._title_lbl = QLabel(title)
        self._title_lbl.setFont(QFont('Segoe UI', 12, QFont.Weight.Bold))
        self._title_lbl.setStyleSheet('color: #ddddee; background: transparent; border: none;')
        texts.addWidget(self._title_lbl)

        self._artist_lbl = QLabel(artist if artist else '—')
        self._artist_lbl.setFont(QFont('Segoe UI', 9))
        self._artist_lbl.setStyleSheet('color: #bbbbcc; background: transparent; border: none;')
        texts.addWidget(self._artist_lbl)

        lay.addLayout(texts, 1)

        self._play_lbl = QLabel('▶')
        self._play_lbl.setFont(QFont('Segoe UI', 12))
        self._play_lbl.setStyleSheet('color: #e02840; background: transparent; border: none;')
        self._play_lbl.setVisible(False)
        lay.addWidget(self._play_lbl)

        self._refresh()

    def update_info(self, title: str, artist: str) -> None:
        self._title_lbl.setText(title)
        self._artist_lbl.setText(artist if artist else '—')

    def set_focused(self, v: bool) -> None:
        self._focused = v
        self._refresh()

    def set_playing(self, v: bool) -> None:
        self._playing = v
        self._play_lbl.setVisible(v)
        self._refresh()

    def _refresh(self) -> None:
        if self._playing:
            self.setStyleSheet(self._SS.format(
                bg='rgba(224,40,64,12)', border='#e02840'))
        elif self._focused:
            self.setStyleSheet(self._SS.format(
                bg='rgba(255,255,255,10)', border='#555577'))
        else:
            self.setStyleSheet(self._SS.format(
                bg='rgba(255,255,255,4)', border='#1e1e2e'))


class SoundtrackPage(QWizardPage):
    def __init__(self, wiz, audio):
        super().__init__()
        self._wiz   = wiz
        self._audio = audio
        self._rows: list[_TrackRow] = []
        self._focus_idx = 0
        self.setTitle('')
        self.setSubTitle('')

        self._vbg = VideoBackground.instance()
        self._vbg.frame_ready.connect(self._on_bg_frame)

        main = QVBoxLayout(self)
        main.setContentsMargins(100, 52, 100, 52)
        main.setSpacing(0)

        hdr = QLabel('SOUNDTRACK')
        hdr.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
        hdr.setStyleSheet(
            'color: #e02840; letter-spacing: 3px; background: transparent; border: none;')
        main.addWidget(hdr)
        main.addSpacing(8)

        div = QFrame()
        div.setFixedHeight(2)
        div.setStyleSheet('background: #1e1e2e; border: none;')
        main.addWidget(div)
        main.addSpacing(24)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { background: transparent; width: 4px; border: none; }
            QScrollBar::handle:vertical {
                background: #2a2a40; border-radius: 2px; min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        self._list_w = QWidget()
        self._list_w.setStyleSheet('background: transparent;')
        self._list_lay = QVBoxLayout(self._list_w)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(8)
        self._scroll.setWidget(self._list_w)
        main.addWidget(self._scroll, 1)

        if hasattr(audio, 'track_changed'):
            audio.track_changed.connect(self._on_track_changed)

    # ── Populate ──────────────────────────────────────────────────────────────

    def _build_rows(self) -> None:
        while self._list_lay.count():
            item = self._list_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows.clear()

        for i, (title, artist) in enumerate(self._audio.playlist_info):
            row = _TrackRow(i, title, artist)
            self._rows.append(row)
            self._list_lay.addWidget(row)

        if not self._rows:
            empty = QLabel('No tracks found in audio/music/')
            empty.setFont(QFont('Segoe UI', 11))
            empty.setStyleSheet('color: #555566; background: transparent; border: none;')
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._list_lay.addWidget(empty)

        self._list_lay.addStretch(1)

    def initializePage(self) -> None:
        self._build_rows()
        cur = self._audio.current_idx
        self._focus_idx = cur
        for i, row in enumerate(self._rows):
            row.set_focused(i == self._focus_idx)
            row.set_playing(i == cur)

    def _on_track_changed(self, title: str, artist: str) -> None:
        cur = self._audio.current_idx
        if 0 <= cur < len(self._rows):
            self._rows[cur].update_info(title, artist)
        for i, row in enumerate(self._rows):
            row.set_playing(i == cur)

    # ── Keyboard ──────────────────────────────────────────────────────────────

    def handle_key(self, key: int) -> bool:
        if not self._rows:
            return False

        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._rows[self._focus_idx].set_focused(False)
            delta = -1 if key == Qt.Key.Key_Up else 1
            self._focus_idx = (self._focus_idx + delta) % len(self._rows)
            self._rows[self._focus_idx].set_focused(True)
            self._scroll.ensureWidgetVisible(self._rows[self._focus_idx])
            return True

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._audio.play_at(self._focus_idx)
            for i, row in enumerate(self._rows):
                row.set_playing(i == self._focus_idx)
            return True

        return False

    def isComplete(self) -> bool:
        return False

    def nextId(self) -> int:
        return -1

    # ── Background ────────────────────────────────────────────────────────────

    def _on_bg_frame(self) -> None:
        if self.isVisible():
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        self._vbg.paint(p, self)
        p.fillRect(self.rect(), QColor(0, 0, 8, 175))
