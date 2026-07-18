from pathlib import Path

from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout, QWidget,
                              QLabel, QStackedWidget)
from PyQt6.QtGui import QFont, QPainter, QColor
from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal

from app.widgets.video_bg import VideoBackground
from app.pages.p_gallery import _Card, _RiderDetail, _make_scroll_area
from app.pages.p_calendar import _SlotBar

try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PyQt6.QtMultimediaWidgets import QVideoWidget
    _MEDIA_OK = True
except ImportError:
    _MEDIA_OK = False

_INTRO_VIDEO = Path(__file__).parent.parent.parent / 'images' / 'career_intro.mp4'

_TINT = QColor(5, 5, 14, 218)


class _TintPanel(QWidget):
    """A panel that veils the video background with _TINT (mirrors the split
    views elsewhere in the app)."""
    def paintEvent(self, event):
        QPainter(self).fillRect(self.rect(), _TINT)


# ── Season intro: plays images/career_intro.mp4 once, full-screen ─────────────

class _SeasonIntroVideo(QWidget):
    """Plays the season-intro clip once and emits `finished` when it ends (or
    the player skips it). If the clip is missing, finishes immediately so the
    hub still opens normally.

    Renders through QVideoWidget (native/hardware-accelerated output) rather
    than pulling frames as QImages and rescaling them by hand every frame —
    that manual path was the source of the stutter at full-screen sizes."""

    finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: black;')
        self._active = False
        self._player = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        if _MEDIA_OK:
            self._video = QVideoWidget(self)
            self._video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
            self._video.setStyleSheet('background: black;')
            # QVideoWidget can use a native child surface for playback; keep
            # it out of the focus chain so it never intercepts Escape/Enter
            # ahead of the app's global key handling (installed on QApplication).
            self._video.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            outer.addWidget(self._video)
            if _INTRO_VIDEO.exists():
                self._player = QMediaPlayer()
                self._audio_out = QAudioOutput()
                self._player.setAudioOutput(self._audio_out)
                self._player.setVideoOutput(self._video)
                self._player.setSource(QUrl.fromLocalFile(str(_INTRO_VIDEO)))
                self._player.setLoops(1)
                self._player.mediaStatusChanged.connect(self._on_status)

    def start(self):
        self._active = True
        if self._player is not None:
            self._player.setPosition(0)
            self._player.play()
        else:
            # No clip on disk (or multimedia unavailable) — don't block the flow.
            QTimer.singleShot(0, self._finish)

    def skip(self):
        if not self._active:
            return
        if self._player is not None:
            self._player.stop()
        self._finish()

    def stop(self):
        """Halt playback without emitting `finished` — used when the caller
        is navigating elsewhere on its own (e.g. bailing out to Home)."""
        self._active = False
        if self._player is not None:
            self._player.stop()

    def _finish(self):
        if not self._active:
            return
        self._active = False
        self.finished.emit()

    def _on_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._finish()


# ── Hub: three selectable cards ────────────────────────────────────────────────

class _Hub(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(2)

        title = QLabel('WHAT NEXT?')
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
        title.setStyleSheet('color:#8a8aa2; letter-spacing:3px; background:transparent; border:none;')
        outer.addWidget(title)
        outer.addSpacing(24)

        row = QHBoxLayout()
        row.addStretch(1)
        self.card_profile = _Card(
            'YOUR PROFILE', 'Review your rider before the season begins', '#e02840')
        self.card_calendar = _Card(
            'CHECK CALENDAR', "See every round on this year's calendar", '#318CE7')
        self.card_next = _Card(
            'TO NEXT RACE', 'Head to Round 1 and get the season started', '#2ecc71')
        cards = [self.card_profile, self.card_calendar, self.card_next]
        for i, w in enumerate(cards):
            row.addWidget(w)
            if i < len(cards) - 1:
                row.addSpacing(28)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(3)

    def cards(self) -> list:
        return [self.card_profile, self.card_calendar, self.card_next]


# ── Read-only calendar recap ───────────────────────────────────────────────────

class _CalendarView(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 44, 48, 40)
        outer.setSpacing(0)

        title = QLabel('SEASON CALENDAR')
        title.setFont(QFont('Segoe UI', 18, QFont.Weight.Bold))
        title.setStyleSheet('color:#ffffff; letter-spacing:2px; background:transparent; border:none;')
        outer.addWidget(title)
        outer.addSpacing(20)

        self._scroll = _make_scroll_area()
        cont = QWidget()
        cont.setStyleSheet('background: transparent;')
        self._lay = QVBoxLayout(cont)
        self._lay.setContentsMargins(0, 0, 12, 0)
        self._lay.setSpacing(8)
        self._lay.addStretch(1)
        self._scroll.setWidget(cont)
        outer.addWidget(self._scroll, 1)

    def load(self, season_df):
        while self._lay.count() > 1:
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        if season_df is None:
            return
        for i, (_, row) in enumerate(season_df.iterrows(), start=1):
            bar = _SlotBar(i)
            bar.set_circuit(row)
            self._lay.insertWidget(self._lay.count() - 1, bar)

    def scroll(self, delta: int):
        bar = self._scroll.verticalScrollBar()
        if bar is not None:
            bar.setValue(bar.value() + delta)

    def scrollbar(self):
        return self._scroll.verticalScrollBar()


# ── Page ──────────────────────────────────────────────────────────────────────

class SeasonHubPage(QWizardPage):
    """Career-mode-only stop between Calendar setup and Round 1: a short
    intro beat, then a hub with the rider's profile, the season calendar,
    and the way into Round 1 — so a new season isn't just an abrupt cut
    from calendar-editing straight into Practice."""

    def __init__(self, wiz):
        super().__init__()
        self._wiz = wiz
        self.setTitle('')
        self.setSubTitle('')
        self._vbg = VideoBackground.instance()
        self._vbg.frame_ready.connect(self._on_bg_frame)
        self._hub_focus = 0

        self._stack = QStackedWidget(self)
        self._stack.setAutoFillBackground(False)
        self._stack.setStyleSheet('background: transparent;')

        self._intro = _SeasonIntroVideo()          # paints its own background
        self._intro.finished.connect(self._show_hub)
        self._stack.addWidget(self._intro)                      # 0

        self._hub = _Hub()
        self._stack.addWidget(self._wrap(self._hub))             # 1

        self._profile = _RiderDetail()
        self._profile_scroll = _make_scroll_area()
        self._profile_scroll.setWidget(self._profile)
        self._stack.addWidget(self._wrap(self._profile_scroll))  # 2

        self._calendar = _CalendarView()
        self._stack.addWidget(self._wrap(self._calendar))        # 3

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._stack)

    @staticmethod
    def _wrap(inner: QWidget) -> QWidget:
        w = _TintPanel()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(inner)
        return w

    # ── Wizard flow ───────────────────────────────────────────────────────────

    def initializePage(self):
        rider = self._wiz.load_career_rider() or {}
        if rider:
            self._profile.load(rider)
        self._calendar.load(self._wiz.season_df)
        for bar in (self._profile_scroll.verticalScrollBar(), self._calendar.scrollbar()):
            if bar is not None:
                bar.setValue(0)

        self._hub_focus = 0
        self._sync_hub_focus()
        self._stack.setCurrentIndex(0)
        self._wiz.pause_music()     # the intro clip has its own audio
        self._intro.start()
        self.setFocus()     # keep focus off the video widget so Esc/Enter both reach handle_key

    def nextId(self):
        return self._wiz.ID_PRACTICE

    # ── Hub navigation ────────────────────────────────────────────────────────

    def _show_hub(self):
        self._wiz.resume_music()
        self._stack.setCurrentIndex(1)

    def _sync_hub_focus(self):
        for i, c in enumerate(self._hub.cards()):
            c.set_focused(i == self._hub_focus)

    def handle_key(self, key: int) -> bool:
        K = Qt.Key
        idx = self._stack.currentIndex()

        if idx == 0:                                    # intro
            if key in (K.Key_Return, K.Key_Enter, K.Key_Space):
                self._intro.skip()
            elif key in (K.Key_Escape, K.Key_Backspace):
                self._intro.stop()
                self._wiz.resume_music()
                self._wiz.accept()      # bail out of the season start -> Home
            return True

        if idx == 1:                                     # hub
            if key in (K.Key_Left, K.Key_Right):
                self._hub_focus = (self._hub_focus + (1 if key == K.Key_Right else -1)) % 3
                self._sync_hub_focus()
            elif key in (K.Key_Return, K.Key_Enter, K.Key_Space):
                (self._open_profile, self._open_calendar, self._go_next)[self._hub_focus]()
            elif key in (K.Key_Escape, K.Key_Backspace):
                self._wiz.accept()      # bail out of the season start -> Home
            return True

        if idx in (2, 3):                                 # profile / calendar detail
            if key in (K.Key_Escape, K.Key_Backspace):
                self._stack.setCurrentIndex(1)
            elif key in (K.Key_Up, K.Key_Down):
                delta = -60 if key == K.Key_Up else 60
                if idx == 2:
                    bar = self._profile_scroll.verticalScrollBar()
                    if bar is not None:
                        bar.setValue(bar.value() + delta)
                else:
                    self._calendar.scroll(delta)
            return True

        return True

    def _open_profile(self):
        self._stack.setCurrentIndex(2)

    def _open_calendar(self):
        self._stack.setCurrentIndex(3)

    def _go_next(self):
        self._wiz.next()

    # ── Background painting (mirrors HomePage/HistoryPage) ────────────────────

    def _on_bg_frame(self):
        if self.isVisible():
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        offset = self.mapTo(self._wiz, self.rect().topLeft())
        self._vbg.paint(p, self, full_size=self._wiz.size(), offset=offset)

    def paint_gap_overlay(self, painter, rect):
        # QWizard reserves a thin strip below the page for its hidden button
        # row; the shared ambient background would otherwise bleed into it
        # while the intro clip is playing (which should read as full-screen).
        if self._stack.currentIndex() == 0:
            painter.fillRect(rect, QColor(0, 0, 0))
