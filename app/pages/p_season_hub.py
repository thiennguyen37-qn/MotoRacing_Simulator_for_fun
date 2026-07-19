import json
from pathlib import Path

from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout, QWidget,
                              QLabel, QStackedWidget, QFrame, QDialog, QSizePolicy,
                              QSpacerItem, QGraphicsOpacityEffect)
from PyQt6.QtGui import (QFont, QPainter, QColor, QPixmap, QPainterPath,
                          QLinearGradient, QPen)
from PyQt6.QtCore import (Qt, QTimer, QUrl, QRect, QRectF, QPointF, QPoint,
                          pyqtSignal, QPropertyAnimation, QParallelAnimationGroup,
                          QEasingCurve, QAbstractAnimation)

from app.pages.p_gallery import STATS, _make_scroll_area, _BIKES_DIR, _BIKE_IMAGE
from app.pages.p_calendar import _SlotBar
from app.pages.p_home import ExitDialog
from app.pages.p_history import (_aggregate_riders, _build_rider_race_matrix,
                                  _stat_tiles, _TOTAL_COLS, _pos_bg,
                                  _flag_pixmap, _season_tables_data, _honours_data)
from app.widgets.table_utils import TEAM_COLOR, MANU_COLOR, _DEFAULT_COLOR, row_bg
from src.simulator import POINTS


def _big_bike_pixmap(team_name: str, height: int = 200):
    """Same source image as Gallery's _bike_pixmap, scaled straight from the
    full-res file at a larger height — Gallery's version caches a 180px-tall
    copy for its compact side panel, and upscaling that cached copy for this
    page's bigger hero shot would just look blurry."""
    img_file = _BIKE_IMAGE.get(team_name)
    if not img_file:
        return None
    raw = QPixmap(str(_BIKES_DIR / img_file))
    if raw.isNull():
        return None
    return raw.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)

try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PyQt6.QtMultimediaWidgets import QVideoWidget
    _MEDIA_OK = True
except ImportError:
    _MEDIA_OK = False

_IMAGES      = Path(__file__).parent.parent.parent / 'images'
_INTRO_VIDEO = _IMAGES / 'career_intro.mp4'
_HUB_BG      = _IMAGES / 'career.jpg'


class _StaticBackground:
    """A cached, cover-scaled static image exposing the same
    `.paint(painter, widget, full_size=, offset=)` shape as the shared
    VideoBackground — set as a page's `self._vbg` and the wizard's
    _GapFiller (app/wizard.py) will automatically continue this image
    seamlessly into the thin strip it reserves below the page, the same way
    it already does for video-backed pages. Without this, that strip just
    shows a plain black fill and the photo reads as cut off from the window."""

    def __init__(self, path: Path):
        self._pixmap = QPixmap(str(path)) if path.exists() else QPixmap()
        self._scaled = QPixmap()
        self._scaled_key = None

    def paint(self, painter, widget, full_size=None, offset=None):
        if self._pixmap.isNull():
            return
        W = full_size.width()  if full_size is not None else widget.width()
        H = full_size.height() if full_size is not None else widget.height()
        ox, oy = (offset.x(), offset.y()) if offset is not None else (0, 0)
        if W <= 0 or H <= 0:
            return
        key = (W, H)
        if key != self._scaled_key:
            iw, ih = self._pixmap.width(), self._pixmap.height()
            scale = max(W / iw, H / ih)
            self._scaled = self._pixmap.scaled(
                max(1, round(iw * scale)), max(1, round(ih * scale)),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation)
            self._scaled_key = key
        pm = self._scaled
        fx, fy = (W - pm.width()) // 2, (H - pm.height()) // 2
        painter.drawPixmap(fx - ox, fy - oy, pm)


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


# ── Hub: a top tab bar (PES2017 "Forward Time" style) ─────────────────────────

class _TabButton(QFrame):
    """One flat top-bar tab: light/inactive, or solid blue when focused."""

    def __init__(self, text: str):
        super().__init__()
        self._focused = False
        self.setFixedHeight(52)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._lbl = QLabel(text)
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl.setFont(QFont('Segoe UI', 10, QFont.Weight.Bold))
        lay.addWidget(self._lbl)
        self._apply()

    def set_focused(self, v: bool):
        self._focused = v
        self._apply()

    def _apply(self):
        if self._focused:
            bg, fg = '#e02840', '#ffffff'
        else:
            bg, fg = 'rgba(235,235,238,235)', '#1a1a1a'
        self.setStyleSheet(f'background: {bg}; border: none;')
        self._lbl.setStyleSheet(f'color: {fg}; letter-spacing: 1px; background: transparent; border: none;')


class _TopTabBar(QWidget):
    """A flat row of _TabButtons — reused for the main hub (To Next Race /
    Your Profile / Calendar / Main Menu) and for the Your Profile sub-hub
    (Basic Info / Results / Rating)."""

    def __init__(self, labels: list):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 24, 0, 0)
        outer.setSpacing(0)

        row = QHBoxLayout()
        row.setSpacing(2)
        self._tabs = [_TabButton(lbl) for lbl in labels]
        for w in self._tabs:
            row.addWidget(w, 1)
        outer.addLayout(row)
        outer.addStretch(1)

    def cards(self) -> list:
        return list(self._tabs)


_PANEL_TINT = QColor(5, 5, 14, 200)


_TINT_MARGIN = 48   # keep this in sync with each sub-view's own content margins


class _TintWrap(QWidget):
    """Veils a Your-Profile sub-view with a dark, rounded card so its text
    stays readable over the career.jpg background — only used once a
    selection is actually opened, not on the tab bar itself. Inset from the
    full rect (rather than edge-to-edge) so the photo still shows at the rim
    instead of being covered corner to corner.

    The inner widget's own layout margin matches the tint's inset, so a
    scrollable child (and its scrollbar) stays confined to the tinted card
    at every scroll position instead of the tint only covering however much
    fit on screen when the view first opened."""

    def __init__(self, inner: QWidget, margin: int = _TINT_MARGIN):
        super().__init__()
        self._margin = margin
        lay = QVBoxLayout(self)
        lay.setContentsMargins(margin, margin, margin, margin)
        lay.addWidget(inner)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = self._margin
        r = QRectF(self.rect().adjusted(m, m, -m, -m))
        path = QPainterPath()
        path.addRoundedRect(r, 20, 20)
        p.fillPath(path, _PANEL_TINT)


# ── Your Profile: Basic Info ───────────────────────────────────────────────────

class _BasicInfoView(QWidget):
    FIELDS = ['NAME', 'AGE', 'NATIONALITY', 'BIKE NUMBER', 'TEAM', 'MANUFACTURER']

    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        outer = QVBoxLayout(self)
        # Sized to fit the stack's height even on a 150%-scaled 1080p screen
        # (~500 logical px of content room) without the scroll area this
        # view used to have — but a plain trailing stretch left everything
        # huddled at the top with a lot of dead space below on a roomier
        # window. Both columns below centre their content vertically
        # instead (leading + trailing stretch) so any surplus space splits
        # evenly rather than pooling at the bottom.
        outer.setContentsMargins(48, 24, 48, 24)
        outer.setSpacing(0)

        title = QLabel('BASIC INFO')
        title.setFont(QFont('Segoe UI', 21, QFont.Weight.Bold))
        title.setStyleSheet('color:#ffffff; letter-spacing:2px; background:transparent; border:none;')
        outer.addWidget(title)
        outer.addSpacing(18)

        body = QWidget()
        body.setStyleSheet('background: transparent;')
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(48)

        # LEFT: explicit field list — plain-weight caps label, bold value
        fields_w = QWidget()
        fields_w.setStyleSheet('background: transparent;')
        fields_lay = QVBoxLayout(fields_w)
        fields_lay.setContentsMargins(0, 0, 0, 0)
        fields_lay.setSpacing(11)
        fields_lay.addStretch(1)
        self._values = {}
        for key in self.FIELDS:
            kl = QLabel(key)
            kl.setFont(QFont('Segoe UI', 9))
            kl.setStyleSheet('color:#ffffff; letter-spacing:2px; background:transparent; border:none;')
            vl = QLabel('—')
            vl.setFont(QFont('Segoe UI', 15, QFont.Weight.Bold))
            vl.setStyleSheet('color:#ffffff; background:transparent; border:none;')
            row = QVBoxLayout()
            row.setSpacing(2)
            row.addWidget(kl)
            row.addWidget(vl)
            fields_lay.addLayout(row)
            self._values[key] = vl
        fields_lay.addStretch(1)
        body_lay.addWidget(fields_w, 1)

        # RIGHT column: bike image, then CAREER SUMMARY directly under it —
        # not a separate full-width block under the left field list.
        right_w = QWidget()
        right_w.setStyleSheet('background: transparent;')
        right_lay = QVBoxLayout(right_w)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        right_lay.addStretch(1)
        right_lay.addSpacing(16)

        self._bike_lbl = QLabel()
        self._bike_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._bike_lbl.setStyleSheet('background: transparent; border: none;')
        right_lay.addWidget(self._bike_lbl, 0, Qt.AlignmentFlag.AlignHCenter)
        right_lay.addSpacing(14)

        summary_title = QLabel('CAREER SUMMARY')
        summary_title.setFont(QFont('Segoe UI', 9))
        summary_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        summary_title.setStyleSheet('color:#ffffff; letter-spacing:2px; background:transparent; border:none;')
        right_lay.addWidget(summary_title, 0, Qt.AlignmentFlag.AlignHCenter)
        right_lay.addSpacing(10)

        self._summary_holder = QWidget()
        self._summary_holder.setStyleSheet('background: transparent;')
        self._summary_lay = QVBoxLayout(self._summary_holder)
        self._summary_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.addWidget(self._summary_holder, 0, Qt.AlignmentFlag.AlignHCenter)
        right_lay.addStretch(1)

        body_lay.addWidget(right_w, 1)

        outer.addWidget(body, 1)

    def load(self, rider: dict, rec: dict | None):
        self._values['NAME'].setText(str(rider.get('name', '—')).upper())
        self._values['AGE'].setText(str(rider.get('age', '—')))
        self._values['NATIONALITY'].setText(str(rider.get('nationality', '—')))
        self._values['BIKE NUMBER'].setText(f"#{rider.get('bike_number', '—')}")
        self._values['TEAM'].setText(str(rider.get('team', '—')))
        self._values['MANUFACTURER'].setText(str(rider.get('manufacturer', '—')))
        pix = _big_bike_pixmap(rider.get('team', ''), height=188)
        self._bike_lbl.setPixmap(pix if pix is not None else QPixmap())

        while self._summary_lay.count():
            item = self._summary_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        totals = rec or {}
        self._summary_lay.addWidget(
            _stat_tiles([(label, totals.get(key, 0)) for label, key in _TOTAL_COLS], spacing=26))


# ── Your Profile: Results (career race-by-race, reuses the Rider Stats grid) ──

class _ResultsView(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(48, 44, 48, 40)
        self._lay.setSpacing(0)

        title = QLabel('CAREER RESULTS')
        title.setFont(QFont('Segoe UI', 26, QFont.Weight.Bold))
        title.setStyleSheet('color:#ffffff; letter-spacing:2px; background:transparent; border:none;')
        self._lay.addWidget(title)
        self._lay.addSpacing(20)
        self._lay.addStretch(1)
        self._body = None

    def load(self, rec: dict | None):
        if self._body is not None:
            self._lay.removeWidget(self._body)
            self._body.deleteLater()
            self._body = None
        matrix = _build_rider_race_matrix(rec) if rec else None
        if matrix is not None:
            self._body = matrix
        else:
            note = QLabel('No race results recorded yet — check back after your first season.')
            note.setWordWrap(True)
            note.setFont(QFont('Segoe UI', 11))
            note.setStyleSheet('color:#8a8aa2; background:transparent; border:none;')
            self._body = note
        self._lay.insertWidget(self._lay.count() - 1, self._body)


# ── Your Profile: Rating (ability bars) ───────────────────────────────────────
# Dedicated (bigger, all-white-text) bars rather than reusing p_gallery's
# _StatBar/_PowerBar — those are tuned for Gallery's compact side panel and
# have their label/value colours baked into paintEvent, not parameterised.

class _RatingBar(QWidget):
    def __init__(self, label: str, value: int, color_hex: str):
        super().__init__()
        self._label = label
        self._value = value
        self._color = QColor(color_hex)
        self._fill  = value / 100.0
        self.setFixedHeight(30)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        label_w, val_w = 190, 48
        bar_x = label_w
        bar_w = w - label_w - val_w - 12

        p.setFont(QFont('Segoe UI', 12))
        p.setPen(QColor('#ffffff'))
        p.drawText(QRect(0, 0, label_w, h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._label)

        tr = QRectF(bar_x, h / 2 - 6, bar_w, 12)
        tp = QPainterPath(); tp.addRoundedRect(tr, 6, 6)
        p.fillPath(tp, QColor(22, 22, 38, 200))

        fw = max(12.0, bar_w * self._fill)
        fr = QRectF(bar_x, h / 2 - 6, fw, 12)
        fp = QPainterPath(); fp.addRoundedRect(fr, 6, 6)
        g = QLinearGradient(bar_x, 0, bar_x + fw, 0)
        g.setColorAt(0, self._color.darker(145))
        g.setColorAt(1, self._color)
        p.fillPath(fp, g)

        p.setFont(QFont('Segoe UI', 12, QFont.Weight.Bold))
        p.setPen(QColor('#ffffff'))
        p.drawText(QRect(w - val_w, 0, val_w, h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   str(self._value))


class _RatingPowerBar(QWidget):
    def __init__(self, score: float):
        super().__init__()
        self._score = score
        self._fill  = score / 100.0
        self.setFixedHeight(42)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        label_w, val_w = 190, 100
        bar_x = label_w
        bar_w = w - label_w - val_w - 12

        p.setFont(QFont('Segoe UI', 13, QFont.Weight.Bold))
        p.setPen(QColor('#ffffff'))
        p.drawText(QRect(0, 0, label_w, h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   'POWER RATING')

        tr = QRectF(bar_x, h / 2 - 8, bar_w, 16)
        tp = QPainterPath(); tp.addRoundedRect(tr, 8, 8)
        p.fillPath(tp, QColor(22, 22, 38, 200))

        fw = max(16.0, bar_w * self._fill)
        fr = QRectF(bar_x, h / 2 - 8, fw, 16)
        fp = QPainterPath(); fp.addRoundedRect(fr, 8, 8)
        g = QLinearGradient(bar_x, 0, bar_x + fw, 0)
        g.setColorAt(0.0, QColor('#0f6b22'))
        g.setColorAt(0.5, QColor('#22c044'))
        g.setColorAt(1.0, QColor('#5eff7e'))
        p.fillPath(fp, g)

        p.setFont(QFont('Segoe UI', 14, QFont.Weight.Bold))
        p.setPen(QColor('#ffffff'))
        p.drawText(QRect(w - val_w, 0, val_w, h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   f'{self._score:.1f} / 100')


class _RatingView(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        lay = QVBoxLayout(self)
        # Sized to fit without scrolling — same constraint as _BasicInfoView
        # (see the note there). The bars+power block centres vertically in
        # the space below the title (leading + trailing stretch) instead of
        # huddling at the top with dead space below on a roomier window.
        lay.setContentsMargins(48, 24, 48, 24)
        lay.setSpacing(0)

        title = QLabel('YOUR RATING')
        title.setFont(QFont('Segoe UI', 21, QFont.Weight.Bold))
        title.setStyleSheet('color:#ffffff; letter-spacing:2px; background:transparent; border:none;')
        lay.addWidget(title)
        lay.addSpacing(20)

        lay.addStretch(1)

        self._bars_holder = QWidget()
        self._bars_holder.setStyleSheet('background: transparent;')
        self._bars_lay = QVBoxLayout(self._bars_holder)
        self._bars_lay.setContentsMargins(0, 0, 0, 0)
        self._bars_lay.setSpacing(13)
        lay.addWidget(self._bars_holder)
        lay.addSpacing(18)

        self._power_holder = QWidget()
        self._power_holder.setStyleSheet('background: transparent;')
        self._power_lay = QVBoxLayout(self._power_holder)
        self._power_lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._power_holder)
        lay.addStretch(1)

    def load(self, rider: dict):
        while self._bars_lay.count():
            item = self._bars_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        for col_name, label, color in STATS:
            self._bars_lay.addWidget(_RatingBar(label, int(rider.get(col_name, 0)), color))

        while self._power_lay.count():
            item = self._power_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        score = sum(int(rider.get(c, 0)) for c, _, _ in STATS) / len(STATS) if rider else 0.0
        self._power_lay.addWidget(_RatingPowerBar(score))


# ── Your Profile sub-hub: Basic Info / Results / Rating ───────────────────────

class _ProfileScreen(QWidget):
    """Same focus-then-open interaction as the main hub, nested one level in:
    Left/Right moves the tab focus, Enter opens that sub-view (with a dark
    tint over the background for readability), Escape closes it back to the
    tab bar — a second Escape bubbles up to the main hub."""

    SUB_TABS = ['BASIC INFO', 'RESULTS', 'RATING']

    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._tabbar = _TopTabBar(self.SUB_TABS)
        outer.addWidget(self._tabbar)

        self._basic = _BasicInfoView()
        self._results = _ResultsView()
        self._rating = _RatingView()

        self._content = QStackedWidget()
        self._content.setStyleSheet('background: transparent;')
        blank = QWidget()
        blank.setStyleSheet('background: transparent;')
        self._content.addWidget(blank)                             # 0 nothing opened

        # Only Results can outgrow the panel (a long career's race-by-race
        # grid) — Basic Info and Rating are fixed, bounded content and don't
        # need a scrollbar, so they skip the QScrollArea wrapper entirely.
        self._scrolls: list = []
        for view, needs_scroll in ((self._basic, False), (self._results, True), (self._rating, False)):
            if needs_scroll:
                sc = _make_scroll_area()
                sc.setWidget(view)
                self._scrolls.append(sc)
                self._content.addWidget(_TintWrap(sc))              # 1/2/3
            else:
                self._scrolls.append(None)
                self._content.addWidget(_TintWrap(view))

        outer.addWidget(self._content, 1)

        self._focus = 0
        self._opened = False

    def load(self, rider: dict, rec: dict | None):
        self._basic.load(rider, rec)
        self._results.load(rec)
        self._rating.load(rider)

    def reset(self):
        """Always resume on the tab bar, nothing opened — same 'no stale
        state' rule as the rest of this feature."""
        self._focus = 0
        self._opened = False
        self._sync_focus()
        self._content.setCurrentIndex(0)
        for sc in self._scrolls:
            if sc is not None:
                bar = sc.verticalScrollBar()
                if bar is not None:
                    bar.setValue(0)

    def _sync_focus(self):
        for i, c in enumerate(self._tabbar.cards()):
            c.set_focused(i == self._focus)

    def handle_key(self, key: int):
        """Returns 'close' when the caller should return to the main hub."""
        K = Qt.Key
        if not self._opened:
            if key in (K.Key_Left, K.Key_Right):
                self._focus = (self._focus + (1 if key == K.Key_Right else -1)) % 3
                self._sync_focus()
            elif key in (K.Key_Return, K.Key_Enter, K.Key_Space):
                self._opened = True
                self._content.setCurrentIndex(self._focus + 1)
            elif key in (K.Key_Escape, K.Key_Backspace):
                return 'close'
            return None

        if key in (K.Key_Escape, K.Key_Backspace):
            self._opened = False
            self._content.setCurrentIndex(0)
        elif key in (K.Key_Up, K.Key_Down):
            sc = self._scrolls[self._focus]
            if sc is not None:
                bar = sc.verticalScrollBar()
                if bar is not None:
                    bar.setValue(bar.value() + (-60 if key == K.Key_Up else 60))
        return None


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


# ── Hub dashboard: last season's standings / recent form / season honours ────
# Fills the empty space below the main hub's tab bar with a quick "where do
# things stand" recap — all scoped to the most recently *completed* season
# (the one about to start has no results yet).

def _flatten_rounds(rounds_detail_list: list) -> list:
    """(country, race) pairs flattened across every round, in calendar order —
    `race` is the raw list of per-rider result dicts for that race."""
    out = []
    for rnd in rounds_detail_list:
        country = rnd.get('country', '')
        for race in rnd.get('races', []):
            out.append((country, race))
    return out


def _recent_form(rounds_detail_list: list, name: str, limit: int = 5) -> list:
    """(country, result-dict-or-None) for this rider, oldest to newest, then
    just the last `limit`."""
    flat = _flatten_rounds(rounds_detail_list)
    return [(country, next((r for r in race if r['name'] == name), None))
            for country, race in flat[-limit:]]


def _rider_recent_races(rec: dict | None, limit: int = 5) -> list:
    """Same as _recent_form, but across every *archived* season this rider
    has (oldest to newest) — naturally falls back into an earlier season if
    the latest one is too short."""
    if not rec:
        return []
    combined = []
    for h in sorted(rec.get('history', []), key=lambda x: str(x['year'])):
        rd = h.get('rounds_detail')
        if rd:
            combined.extend(rd)
    return _recent_form(combined, rec.get('name'), limit)


def _stats_from_rounds_detail(rounds_detail_list: list) -> dict:
    """Per-rider races/wins/podiums/poles/fastest_laps tally from a
    rounds_detail list — mirrors p4_championship._save_history()'s 'stats'
    computation (including counting pole only once per round, not once per
    race), so a season-in-progress aggregates the same way an archived one
    does once _aggregate_riders() sees it."""
    def _blank():
        return {'races': 0, 'wins': 0, 'podiums': 0, 'poles': 0, 'fastest_laps': 0}
    stats: dict[str, dict] = {}
    for rnd in rounds_detail_list:
        races = rnd.get('races', [])
        for race in races:
            for r in race:
                s = stats.setdefault(r['name'], _blank())
                s['races'] += 1
                if not r.get('dnf'):
                    pos = int(r.get('pos', 0))
                    s['wins']    += pos == 1
                    s['podiums'] += 1 <= pos <= 3
                if r.get('fastest_lap'):
                    s['fastest_laps'] += 1
        if races:                      # pole is shared by both races of a round
            for r in races[0]:
                if r.get('pole'):
                    stats.setdefault(r['name'], _blank())['poles'] += 1
    return stats


def _rider_position_trend(rounds_detail_list: list, name: str) -> list:
    """(label, position-or-None) per race in calendar order for the line
    chart — None marks a DNF (no finishing position to plot)."""
    flat = _flatten_rounds(rounds_detail_list)
    out = []
    for i, (_country, race) in enumerate(flat, start=1):
        r = next((x for x in race if x['name'] == name), None)
        if r is None:
            continue
        pos = None if r.get('dnf') else int(r.get('pos', 0))
        out.append((f'R{i}', pos))
    return out


class _FormBox(QFrame):
    """One race in the rider's recent-form strip: flag, then the result
    filled with the same colour the race-by-race grids use."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(60, 86)
        self.setStyleSheet('background: transparent; border: none;')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(0)

        self._flag_lbl = QLabel()
        self._flag_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._flag_lbl.setFixedHeight(24)
        self._flag_lbl.setStyleSheet('background: transparent; border: none;')
        lay.addWidget(self._flag_lbl)
        lay.addSpacing(6)

        self._bottom = QWidget()
        bl = QVBoxLayout(self._bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        self._result_lbl = QLabel('')
        self._result_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._result_lbl.setFont(QFont('Segoe UI', 13, QFont.Weight.Bold))
        self._result_lbl.setStyleSheet('color:#ffffff; background: transparent; border: none;')
        bl.addWidget(self._result_lbl)
        lay.addWidget(self._bottom, 1)

    def load(self, country: str | None, result: dict | None):
        # Explicit width too: flag source images don't share one aspect
        # ratio, so scaling by height alone left each one a different width
        # (looking like inconsistent sizes) — force every flag to the same
        # box regardless of its source proportions.
        pix = _flag_pixmap(country, height=20, width=28) if country else None
        self._flag_lbl.setPixmap(pix if pix is not None else QPixmap())
        if result is None:
            self._result_lbl.setText('')
            bg = QColor(26, 26, 40, 160)
        else:
            dnf = bool(result.get('dnf', False))
            pos = int(result.get('pos', 0))
            self._result_lbl.setText('Ret' if dnf else str(pos))
            bg = _pos_bg(pos, dnf)
        self._bottom.setStyleSheet(f'background: {bg.name() if hasattr(bg, "name") else bg}; border: none;')


class _ElideLabel(QLabel):
    """A QLabel that elides its own text down to whatever width the layout
    actually gives it, instead of demanding its full text width — a long
    team/manufacturer name (e.g. "KAWASAKI FACTORY RACING") was forcing the
    row wider than its fixed-width neighbours could make room for, pushing
    the points column past the row's edge. The full name still shows as a
    tooltip when elided."""

    def __init__(self, text: str = ''):
        super().__init__()
        self._full = text
        self.setMinimumWidth(0)

    def setFullText(self, text: str):
        self._full = text
        self._apply_elide()

    def _apply_elide(self):
        elided = self.fontMetrics().elidedText(
            self._full, Qt.TextElideMode.ElideRight, max(self.width(), 1))
        super().setText(elided)
        self.setToolTip(self._full if elided != self._full else '')

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_elide()


_DASH_ROW_H = 30   # locked height of every standings row — see _StandingsPanel._render
_MINI_ROW_H = 26   # overall-stats rows are a notch shorter, keeping the middle card compact


def _soft_gap(preferred: int) -> QSpacerItem:
    """A vertical gap that prefers `preferred` px but may collapse to 0.
    Panels use these instead of addSpacing() for their internal padding:
    addSpacing() is rigid, so when the dashboard column runs short of height
    the layout could only satisfy the deficit by clipping the bottom of a
    panel — cutting through its last row. Soft gaps give the layout
    somewhere harmless to take the shortfall from instead."""
    return QSpacerItem(0, preferred, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Maximum)


_TRANSITION_MS = 380


def _grab_snapshot(container: QWidget) -> tuple:
    """(pixmap, geometry) of `container`'s current visual state — grab this
    *before* rebuilding its content, then pass it to _play_transition()
    *after*. Geometry has to be captured now too, not read back off the
    container later: a page with fewer rows than the next is a smaller
    widget, and by the time _play_transition runs, the container has
    already resized to fit the *new* (possibly taller) content — reading
    its geometry then would size the overlay for the new page and leave
    the old page's snapshot only covering part of it."""
    return container.grab(), container.geometry()


_SCROLL_NUDGE = 16   # small pop distance for kind='scroll' — see _play_transition


def _play_transition(owner: QWidget, container: QWidget, snapshot: tuple, kind: str):
    """Animates a dashboard card's periodic content swap.

    `snapshot` is the (pixmap, geometry) pair from _grab_snapshot(), taken
    before the caller rebuilt `container`'s content (which by now is
    already showing the new content, sitting at its normal resting spot):

    - kind='scroll': the outgoing snapshot pops up a *little* (a small
      _SCROLL_NUDGE, not a full page-height) while fading out, and the
      incoming `container` mirrors it — starts nudged slightly below rest
      and eases up while fading in. A full-height traverse read as the page
      being "flung" off-screen; this keeps the same up-and-out direction
      as a hint of scrolling without the large travel. Used for paging
      within the same standings category (top 5 -> next 5 -> ...).
    - kind='fade': the outgoing snapshot cross-dissolves in place, no
      movement at all — used when the category itself changes (e.g.
      Riders -> Teams).

    `owner` just needs to outlive the animation to keep it alive (Python
    would otherwise garbage-collect the QPropertyAnimation/group as soon as
    this function returns) — the calling panel passes `self`.
    """
    old_pixmap, old_geometry = snapshot
    if old_pixmap.isNull():
        return
    parent = container.parentWidget()
    overlay = QLabel(parent)
    overlay.setPixmap(old_pixmap)
    overlay.setGeometry(old_geometry)
    overlay.show()
    overlay.raise_()

    out_effect = QGraphicsOpacityEffect(overlay)
    overlay.setGraphicsEffect(out_effect)
    out_fade = QPropertyAnimation(out_effect, b'opacity', overlay)
    out_fade.setDuration(_TRANSITION_MS)
    out_fade.setStartValue(1.0)
    out_fade.setEndValue(0.0)

    group = QParallelAnimationGroup(owner)
    group.addAnimation(out_fade)

    if kind == 'scroll':
        out_move = QPropertyAnimation(overlay, b'pos', overlay)
        out_move.setDuration(_TRANSITION_MS)
        out_move.setStartValue(overlay.pos())
        out_move.setEndValue(overlay.pos() - QPoint(0, _SCROLL_NUDGE))
        out_move.setEasingCurve(QEasingCurve.Type.OutCubic)
        group.addAnimation(out_move)

        in_effect = QGraphicsOpacityEffect(container)
        container.setGraphicsEffect(in_effect)
        in_effect.setOpacity(0.0)
        in_fade = QPropertyAnimation(in_effect, b'opacity', container)
        in_fade.setDuration(_TRANSITION_MS)
        in_fade.setStartValue(0.0)
        in_fade.setEndValue(1.0)
        group.addAnimation(in_fade)

        settled_pos = container.pos()
        container.move(settled_pos + QPoint(0, _SCROLL_NUDGE))
        in_move = QPropertyAnimation(container, b'pos', container)
        in_move.setDuration(_TRANSITION_MS)
        in_move.setStartValue(container.pos())
        in_move.setEndValue(settled_pos)
        in_move.setEasingCurve(QEasingCurve.Type.OutCubic)
        group.addAnimation(in_move)

        group.finished.connect(lambda: container.setGraphicsEffect(None))

    group.finished.connect(overlay.deleteLater)
    owner._active_transition = group   # keep a live Python reference until done
    group.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


def _panel_title(text: str) -> QWidget:
    """A dashboard panel's heading: centred, with a divider marking where
    the title ends and the panel's own content begins."""
    w = QWidget()
    w.setStyleSheet('background: transparent;')
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)

    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
    lbl.setStyleSheet('color:#ffffff; letter-spacing:2px; background:transparent; border:none;')
    lay.addWidget(lbl)

    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet('background: rgba(255,255,255,60); border:none;')
    lay.addWidget(line)
    return w


class _StandingsPanel(QWidget):
    """Every 5s either pages within the current standings category (top 5,
    then 6-10, ... scrolling down between pages) or, once a category runs
    out of pages, crossfades to the next one — RIDER -> TEAM -> MANUFACTURER
    -> repeat. Plain top-down ranking throughout; it doesn't hunt for the
    player's own row."""

    _MODES = ['RIDER', 'TEAM', 'MANUFACTURER']
    _PAGE_SIZE = 5
    _CYCLE_MS = 5000

    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(0)

        lay.addWidget(_panel_title('STANDINGS'))
        lay.addItem(_soft_gap(10))

        header = QWidget()
        header.setStyleSheet('background: transparent;')
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 0, 10, 0)
        hl.setSpacing(8)
        pos_h = QLabel('POS'); pos_h.setFixedWidth(24)
        self._name_h = QLabel(self._MODES[0])
        pts_h = QLabel('PTS'); pts_h.setFixedWidth(44)
        # AlignRight alone REPLACES QLabel's default vertical centring —
        # without an explicit AlignVCenter the text is drawn from the top
        # and its lower half gets clipped whenever the row is squeezed.
        pts_h.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for l in (pos_h, self._name_h, pts_h):
            l.setFont(QFont('Segoe UI', 7, QFont.Weight.Bold))
            l.setStyleSheet('color:#ffffff; letter-spacing:1px; background:transparent; border:none;')
        hl.addWidget(pos_h)
        hl.addWidget(self._name_h, 1)
        hl.addWidget(pts_h)
        lay.addWidget(header)
        lay.addItem(_soft_gap(6))

        self._rows_holder = QWidget()
        self._rows_holder.setStyleSheet('background: transparent;')
        self._rows_lay = QVBoxLayout(self._rows_holder)
        self._rows_lay.setContentsMargins(0, 0, 0, 0)
        self._rows_lay.setSpacing(8)
        lay.addWidget(self._rows_holder)
        lay.addStretch(1)

        self._by_mode = {}
        self._mode_index = 0
        self._page_index = 0
        self._timer = QTimer(self)
        self._timer.setInterval(self._CYCLE_MS)
        self._timer.timeout.connect(self._advance)
        self._timer.start()

    def load(self, standings: list, team_standings: list, manu_standings: list):
        self._by_mode = {'RIDER': standings, 'TEAM': team_standings, 'MANUFACTURER': manu_standings}
        self._mode_index = 0
        self._page_index = 0
        self._render()

    def _advance(self):
        if not self._by_mode:
            return
        mode = self._MODES[self._mode_index]
        total_pages = max(1, -(-len(self._by_mode.get(mode, [])) // self._PAGE_SIZE))
        if self._page_index + 1 < total_pages:
            self._page_index += 1
            kind = 'scroll'
        else:
            self._mode_index = (self._mode_index + 1) % len(self._MODES)
            self._page_index = 0
            kind = 'fade'
        self._render(kind)

    @staticmethod
    def _row_color(mode: str, s: dict):
        if mode == 'TEAM':
            return TEAM_COLOR.get(s.get('name', ''), _DEFAULT_COLOR)
        if mode == 'MANUFACTURER':
            return MANU_COLOR.get(s.get('name', ''), _DEFAULT_COLOR)
        return TEAM_COLOR.get(s.get('team', '')) or MANU_COLOR.get(
            s.get('manufacturer', ''), _DEFAULT_COLOR)

    def _render(self, transition: str | None = None):
        mode = self._MODES[self._mode_index]
        self._name_h.setText(mode)
        standings = self._by_mode.get(mode, [])
        snapshot = _grab_snapshot(self._rows_holder) if transition else None

        while self._rows_lay.count():
            item = self._rows_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        if not standings:
            ph = QLabel('No standings yet — check back after your first season.')
            ph.setWordWrap(True)
            ph.setFont(QFont('Segoe UI', 10))
            ph.setStyleSheet('color:#8a8aa2; background:transparent; border:none;')
            self._rows_lay.addWidget(ph)
            return
        # Always exactly _PAGE_SIZE slots — a last page with fewer real
        # entries (e.g. 12 total -> page 3 is just #11-12) pads out with
        # empty placeholders instead of shrinking. Besides matching
        # _mini_board's own look, this keeps every page the same height,
        # which the transition overlay relies on (see _grab_snapshot).
        start = self._page_index * self._PAGE_SIZE
        window = standings[start:start + self._PAGE_SIZE]
        for i in range(self._PAGE_SIZE):
            pos = start + i + 1
            row = QFrame()
            # Fixed height: a Preferred-height row is fair game for the
            # layout to squeeze when the column runs short, and a squeezed
            # row clips the bottom of its text. Locked, it can't.
            row.setFixedHeight(_DASH_ROW_H)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(10, 0, 10, 0)
            rl.setSpacing(8)
            pos_lbl = QLabel(str(pos)); pos_lbl.setFixedWidth(24)
            name_lbl = _ElideLabel()
            pts_lbl = QLabel(); pts_lbl.setFixedWidth(44)
            pts_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for l in (pos_lbl, name_lbl, pts_lbl):
                l.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))

            if i < len(window):
                s = window[i]
                bg = row_bg(self._row_color(mode, s))
                row.setStyleSheet(f'background: {bg.name()}; border-radius: 6px; border: none;')
                text_color = '#ffffff'
                name_lbl.setFullText(str(s.get('name', '')).upper())
                pts_lbl.setText(str(int(s.get('points', 0))))
            else:
                row.setStyleSheet('background: rgba(255,255,255,10); border-radius: 6px; border: none;')
                text_color = '#5a5a72'
                name_lbl.setFullText('—')

            for l in (pos_lbl, name_lbl, pts_lbl):
                l.setStyleSheet(f'color:{text_color}; background:transparent; border:none;')
            rl.addWidget(pos_lbl)
            rl.addWidget(name_lbl, 1)
            rl.addWidget(pts_lbl)
            self._rows_lay.addWidget(row)

        if transition:
            _play_transition(self, self._rows_holder, snapshot, transition)


class _FormPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(0)

        lay.addWidget(_panel_title('RECENT FORM'))
        lay.addItem(_soft_gap(10))

        boxes_holder = QWidget()
        boxes_holder.setStyleSheet('background: transparent;')
        boxes_lay = QHBoxLayout(boxes_holder)
        boxes_lay.setContentsMargins(0, 0, 0, 0)
        boxes_lay.setSpacing(8)
        self._boxes = [_FormBox() for _ in range(5)]
        for b in self._boxes:
            boxes_lay.addWidget(b)
        # No internal stretch — boxes_holder shrinks to exactly fit the 5
        # boxes, and centering it (rather than left-aligning it in the full
        # width) is what actually centers the strip.
        lay.addWidget(boxes_holder, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(1)

    def load(self, races: list):
        # Chronological, earliest on the left — blanks (races not yet run)
        # trail on the right instead of leading on the left.
        window = list(races[-len(self._boxes):])
        padded = window + [(None, None)] * (len(self._boxes) - len(window))
        for box, (country, result) in zip(self._boxes, padded):
            box.load(country, result)


_MINI_BOARD_SLOTS = 3


def _mini_board(title: str, entries: list, names_map: dict | None = None) -> QWidget:
    """`title` doubles as this board's own subtitle (e.g. "TOP WINNERS"),
    styled the same as the other dashboard panels' headers — there's no
    outer "OVERALL STATS" label any more, so whichever category is showing
    carries its own heading.

    Always renders exactly `_MINI_BOARD_SLOTS` rows — padding with empty
    placeholders when a category has fewer real entries — so this board's
    height stays constant as it cycles categories; a category-dependent
    height here was resizing _FormPanel too, since both share a grid row.

    `names_map` looks up each rider's {'team', 'manufacturer'} (from
    _season_tables_data's 'names') so every row gets the same team/manu
    colour-filled box the Standings panel uses, instead of plain text."""
    col = QWidget()
    col.setStyleSheet('background: transparent;')
    lay = QVBoxLayout(col)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(5)

    lay.addWidget(_panel_title(title))
    lay.addSpacing(2)

    names_map = names_map or {}
    for i in range(1, _MINI_BOARD_SLOTS + 1):
        row = QFrame()
        row.setFixedHeight(_MINI_ROW_H)   # same no-squeeze rule as the standings rows
        rl = QHBoxLayout(row)
        rl.setContentsMargins(10, 0, 10, 0)
        rl.setSpacing(8)
        pos_lbl = QLabel(str(i)); pos_lbl.setFixedWidth(24)
        name_lbl = _ElideLabel()
        count_lbl = QLabel(); count_lbl.setFixedWidth(44)
        count_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for l in (pos_lbl, name_lbl, count_lbl):
            l.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))

        if i <= len(entries):
            name, count = entries[i - 1]
            info = names_map.get(name, {})
            color = TEAM_COLOR.get(info.get('team', '')) or MANU_COLOR.get(
                info.get('manufacturer', ''), _DEFAULT_COLOR)
            row.setStyleSheet(f'background: {row_bg(color).name()}; border-radius: 6px; border: none;')
            text_color = '#ffffff'
            name_lbl.setFullText(str(name).upper())
            count_lbl.setText(str(count))
        else:
            row.setStyleSheet('background: rgba(255,255,255,10); border-radius: 6px; border: none;')
            text_color = '#5a5a72'
            name_lbl.setFullText('—')

        for l in (pos_lbl, name_lbl, count_lbl):
            l.setStyleSheet(f'color:{text_color}; background:transparent; border:none;')
        rl.addWidget(pos_lbl)
        rl.addWidget(name_lbl, 1)
        rl.addWidget(count_lbl)
        lay.addWidget(row)
    lay.addStretch(1)
    return col


class _OverallStatsPanel(QWidget):
    """Cycles every 5s between TOP WINNERS / TOP PODIUMS / TOP POLESITTERS,
    showing one board at a time instead of all three stacked statically.
    No static panel title — the currently-showing category's own name
    (rendered by _mini_board) serves as this panel's heading."""

    _BOARDS = [('TOP WINNERS', 'wins'), ('TOP PODIUMS', 'podiums'), ('TOP POLESITTERS', 'poles')]
    _CYCLE_MS = 5000

    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(0)

        self._board_holder = QWidget()
        self._board_holder.setStyleSheet('background: transparent;')
        self._board_lay = QVBoxLayout(self._board_holder)
        self._board_lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._board_holder)
        lay.addStretch(1)

        self._honours = {}
        self._names_map = {}
        self._index = 0
        self._timer = QTimer(self)
        self._timer.setInterval(self._CYCLE_MS)
        self._timer.timeout.connect(self._advance)
        self._timer.start()

    def load(self, honours: dict | None, names_map: dict | None = None):
        self._honours = honours or {}
        self._names_map = names_map or {}
        self._index = 0
        self._render()

    def _advance(self):
        self._index = (self._index + 1) % len(self._BOARDS)
        self._render(transition=True)

    def _render(self, transition: bool = False):
        snapshot = _grab_snapshot(self._board_holder) if transition else None
        while self._board_lay.count():
            item = self._board_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        title, key = self._BOARDS[self._index]
        self._board_lay.addWidget(_mini_board(title, self._honours.get(key, []), self._names_map))
        if transition:
            _play_transition(self, self._board_holder, snapshot, 'fade')


_HUB_SIDEBAR_W = 380   # compact right-hand column; the left side stays open for more sections


class _HubDashboard(QWidget):
    """Sits below the main hub's tab bar as a single compact column, pinned
    to the right: standings, then overall stats, then recent form below
    it — leaving the whole left side of the screen open for future
    sections instead of spreading across the full width."""

    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        outer = QHBoxLayout(self)
        outer.setContentsMargins(56, 0, 56, 40)
        outer.setSpacing(0)
        outer.addStretch(1)

        right = QWidget()
        right.setFixedWidth(_HUB_SIDEBAR_W)
        right.setStyleSheet('background: transparent;')
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(12)

        self._standings = _StandingsPanel()
        self._overall_stats = _OverallStatsPanel()
        self._form = _FormPanel()
        for panel in (self._standings, self._overall_stats, self._form):
            wrap = _TintWrap(panel, margin=0)
            # Maximum: a card may shrink below its natural height — its
            # internal _soft_gap()s collapse first, so rows stay intact —
            # but never grows past it (the trailing stretch takes surplus).
            # A hard Fixed policy here forced Qt to clip card bottoms
            # instead, cutting through the last row.
            wrap.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            right_lay.addWidget(wrap)
        # Trailing stretch keeps the stack pinned to the top when the column
        # has height to spare.
        right_lay.addStretch(1)

        outer.addWidget(right)

    def load(self, standings: list, races: list, honours: dict | None,
            team_standings: list, manu_standings: list,
            names_map: dict | None = None):
        self._standings.load(standings, team_standings, manu_standings)
        self._form.load(races)
        self._overall_stats.load(honours, names_map)


# ── Season Stats tab: STANDINGS / YOUR RESULT (same sub-hub pattern as
# Your Profile) — unlike the dashboard's condensed Standings panel (5 rows
# around the player), the full-page Standings view here lists every rider.

class _FullStandingsView(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(56, 52, 56, 48)
        outer.setSpacing(0)

        title = QLabel('STANDINGS')
        title.setFont(QFont('Segoe UI', 26, QFont.Weight.Bold))
        title.setStyleSheet('color:#ffffff; letter-spacing:2px; background:transparent; border:none;')
        outer.addWidget(title)
        outer.addSpacing(20)

        self._rows_holder = QWidget()
        self._rows_holder.setStyleSheet('background: transparent;')
        self._rows_lay = QVBoxLayout(self._rows_holder)
        self._rows_lay.setContentsMargins(0, 0, 0, 0)
        self._rows_lay.setSpacing(10)
        self._rows_lay.addStretch(1)
        outer.addWidget(self._rows_holder)

    def load(self, standings: list, rider_name: str):
        while self._rows_lay.count() > 1:
            item = self._rows_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        for i, s in enumerate(standings, start=1):
            team_color = TEAM_COLOR.get(s.get('team', '')) or MANU_COLOR.get(
                s.get('manufacturer', ''), _DEFAULT_COLOR)
            bg = row_bg(team_color)
            row = QFrame()
            row.setStyleSheet(f'background: {bg.name()}; border-radius: 6px; border: none;')
            rl = QHBoxLayout(row)
            rl.setContentsMargins(14, 8, 14, 8)
            rl.setSpacing(12)
            pos_lbl = QLabel(str(i)); pos_lbl.setFixedWidth(32)
            name_lbl = QLabel(str(s.get('name', '')).upper())
            pts_lbl = QLabel(str(int(s.get('points', 0)))); pts_lbl.setFixedWidth(60)
            pts_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for l in (pos_lbl, name_lbl, pts_lbl):
                l.setFont(QFont('Segoe UI', 12, QFont.Weight.Bold))
                l.setStyleSheet('color:#ffffff; background:transparent; border:none;')
            rl.addWidget(pos_lbl)
            rl.addWidget(name_lbl, 1)
            rl.addWidget(pts_lbl)
            self._rows_lay.insertWidget(self._rows_lay.count() - 1, row)
        if not standings:
            ph = QLabel('No standings yet — check back after your first season.')
            ph.setFont(QFont('Segoe UI', 11))
            ph.setStyleSheet('color:#8a8aa2; background:transparent; border:none;')
            self._rows_lay.insertWidget(self._rows_lay.count() - 1, ph)


class _PositionTrendChart(QWidget):
    """Line plot of the rider's finishing position race by race this season
    — x = race, y = position (inverted, P1 at the top, since a higher chart
    line should read as a better result). DNFs break the line and get a
    marker at the bottom row instead of implying a real finishing spot."""

    _DNF_COLOR = QColor('#8a4fc9')
    _LINE_COLOR = QColor('#e02840')

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(220)
        self.setStyleSheet('background: transparent;')
        self._points: list = []

    def load(self, points: list):
        self._points = points
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        pad_l, pad_r, pad_t, pad_b = 34, 12, 10, 24

        if not self._points:
            p.setFont(QFont('Segoe UI', 11))
            p.setPen(QColor('#8a8aa2'))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                      'No races run yet this season.')
            return

        n = len(self._points)
        max_pos = max((pos for _, pos in self._points if pos is not None), default=20)
        max_pos = max(max_pos, 3)
        plot_w = max(1, w - pad_l - pad_r)
        plot_h = max(1, h - pad_t - pad_b)

        def _x(i):
            return pad_l + (i / (n - 1) * plot_w if n > 1 else plot_w / 2)

        def _y(pos):
            return pad_t + (pos - 1) / max(1, max_pos - 1) * plot_h

        p.setPen(QPen(QColor(255, 255, 255, 50), 1))
        p.drawLine(int(pad_l), int(pad_t), int(pad_l), int(h - pad_b))
        p.drawLine(int(pad_l), int(h - pad_b), int(w - pad_r), int(h - pad_b))

        p.setFont(QFont('Segoe UI', 8))
        step = max(1, max_pos // 5)
        for pos in range(1, max_pos + 1, step):
            y = _y(pos)
            p.setPen(QColor(255, 255, 255, 22))
            p.drawLine(int(pad_l), int(y), int(w - pad_r), int(y))
            p.setPen(QColor('#8a8aa2'))
            p.drawText(QRect(0, int(y) - 7, pad_l - 6, 14),
                      Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f'P{pos}')

        prev = None
        for i, (_label, pos) in enumerate(self._points):
            if pos is None:
                prev = None
                continue
            pt = (_x(i), _y(pos))
            if prev is not None:
                p.setPen(QPen(self._LINE_COLOR, 2))
                p.drawLine(int(prev[0]), int(prev[1]), int(pt[0]), int(pt[1]))
            prev = pt

        p.setPen(Qt.PenStyle.NoPen)
        for i, (_label, pos) in enumerate(self._points):
            if pos is None:
                p.setBrush(self._DNF_COLOR)
                p.drawEllipse(QPointF(_x(i), h - pad_b), 4, 4)
            else:
                p.setBrush(self._LINE_COLOR)
                p.drawEllipse(QPointF(_x(i), _y(pos)), 4, 4)


class _YourResultView(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(56, 52, 56, 48)
        outer.setSpacing(0)

        title = QLabel('YOUR RESULT')
        title.setFont(QFont('Segoe UI', 26, QFont.Weight.Bold))
        title.setStyleSheet('color:#ffffff; letter-spacing:2px; background:transparent; border:none;')
        outer.addWidget(title)
        outer.addSpacing(30)

        self._result_holder = QWidget()
        self._result_holder.setStyleSheet('background: transparent;')
        self._result_lay = QVBoxLayout(self._result_holder)
        self._result_lay.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._result_holder)
        outer.addSpacing(36)

        chart_title = QLabel('POSITION BY RACE')
        chart_title.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
        chart_title.setStyleSheet('color:#ffffff; letter-spacing:2px; background:transparent; border:none;')
        outer.addWidget(chart_title)
        outer.addSpacing(14)

        self._chart = _PositionTrendChart()
        outer.addWidget(self._chart)
        outer.addStretch(1)

    def load(self, standings: list, rider_name: str, honours: dict | None,
            trend: list | None = None):
        while self._result_lay.count():
            item = self._result_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        pos = next((i for i, s in enumerate(standings, start=1)
                   if s.get('name') == rider_name), None)
        points = next((int(s.get('points', 0)) for s in standings
                       if s.get('name') == rider_name), 0)
        honours = honours or {}

        def _count(key):
            return next((c for n, c in honours.get(key, []) if n == rider_name), 0)

        pairs = [
            ('POSITION', f'P{pos}' if pos else '—'),
            ('POINTS', points),
            ('WINS', _count('wins')),
            ('PODIUMS', _count('podiums')),
            ('POLES', _count('poles')),
        ]
        self._result_lay.addWidget(_stat_tiles(pairs))
        self._chart.load(trend or [])


class _SeasonStatsScreen(QWidget):
    """Same focus-then-open interaction as Your Profile: STANDINGS / YOUR
    RESULT, each behind its own tint once opened."""

    SUB_TABS = ['STANDINGS', 'YOUR RESULT']

    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._tabbar = _TopTabBar(self.SUB_TABS)
        outer.addWidget(self._tabbar)

        self._standings_view = _FullStandingsView()
        self._result_view = _YourResultView()

        self._content = QStackedWidget()
        self._content.setStyleSheet('background: transparent;')
        blank = QWidget()
        blank.setStyleSheet('background: transparent;')
        self._content.addWidget(blank)                             # 0 nothing opened

        self._scrolls = []
        for view in (self._standings_view, self._result_view):
            sc = _make_scroll_area()
            sc.setWidget(view)
            self._scrolls.append(sc)
            self._content.addWidget(_TintWrap(sc))                 # 1/2

        outer.addWidget(self._content, 1)

        self._focus = 0
        self._opened = False

    def load(self, standings: list, rider_name: str, honours: dict | None,
            trend: list | None = None):
        self._standings_view.load(standings, rider_name)
        self._result_view.load(standings, rider_name, honours, trend)

    def reset(self):
        """Always resume on the tab bar, nothing opened."""
        self._focus = 0
        self._opened = False
        self._sync_focus()
        self._content.setCurrentIndex(0)
        for sc in self._scrolls:
            bar = sc.verticalScrollBar()
            if bar is not None:
                bar.setValue(0)

    def _sync_focus(self):
        for i, c in enumerate(self._tabbar.cards()):
            c.set_focused(i == self._focus)

    def handle_key(self, key: int):
        """Returns 'close' when the caller should return to the main hub."""
        K = Qt.Key
        if not self._opened:
            if key in (K.Key_Left, K.Key_Right):
                self._focus = (self._focus + (1 if key == K.Key_Right else -1)) % 2
                self._sync_focus()
            elif key in (K.Key_Return, K.Key_Enter, K.Key_Space):
                self._opened = True
                self._content.setCurrentIndex(self._focus + 1)
            elif key in (K.Key_Escape, K.Key_Backspace):
                return 'close'
            return None

        if key in (K.Key_Escape, K.Key_Backspace):
            self._opened = False
            self._content.setCurrentIndex(0)
        elif key in (K.Key_Up, K.Key_Down):
            bar = self._scrolls[self._focus].verticalScrollBar()
            if bar is not None:
                bar.setValue(bar.value() + (-60 if key == K.Key_Up else 60))
        return None


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
        # Only the intro plays video; once it's done the hub/profile/calendar
        # sit over this static image instead of the shared ambient loop. Named
        # _vbg (matching every video-backed page) so the wizard's _GapFiller
        # picks it up automatically and continues it into the reserved strip
        # below the page instead of leaving that strip plain black.
        self._vbg = _StaticBackground(_HUB_BG)
        self._hub_focus = 0

        self._stack = QStackedWidget(self)
        self._stack.setAutoFillBackground(False)
        self._stack.setStyleSheet('background: transparent;')

        self._intro = _SeasonIntroVideo()          # paints its own background
        self._intro.finished.connect(self._show_hub)
        self._stack.addWidget(self._intro)                      # 0

        self._hub = _TopTabBar(['TO NEXT RACE', 'YOUR PROFILE', 'CALENDAR', 'SEASON STATS', 'MAIN MENU'])
        self._hub_dashboard = _HubDashboard()
        hub_page = QWidget()
        hub_page.setStyleSheet('background: transparent;')
        hub_page_lay = QVBoxLayout(hub_page)
        hub_page_lay.setContentsMargins(0, 0, 0, 0)
        hub_page_lay.setSpacing(0)
        hub_page_lay.addWidget(self._hub)
        hub_page_lay.addSpacing(30)
        hub_page_lay.addWidget(self._hub_dashboard, 1)
        self._stack.addWidget(self._wrap(hub_page))               # 1

        self._profile = _ProfileScreen()
        self._stack.addWidget(self._wrap(self._profile))         # 2

        self._calendar = _CalendarView()
        self._stack.addWidget(self._wrap(self._calendar))        # 3

        self._season_stats_screen = _SeasonStatsScreen()
        self._stack.addWidget(self._wrap(self._season_stats_screen))  # 4

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._stack)

    @staticmethod
    def _wrap(inner: QWidget) -> QWidget:
        w = QWidget()
        w.setStyleSheet('background: transparent;')
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(inner)
        return w

    # ── Wizard flow ───────────────────────────────────────────────────────────

    def _load_history_seasons(self) -> list:
        """This career slot's own history.json — the History page's helpers
        work on any `seasons` list, but its own _load_history() reads the
        unrelated one-off Championship archive."""
        path = self._wiz.history_path()
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding='utf-8')).get('seasons', [])
        except (json.JSONDecodeError, OSError):
            return []

    def _build_live_rounds_detail(self) -> list:
        """Convert the wizard's in-memory, not-yet-archived round_results for
        the season currently being played into the same rounds_detail shape
        history.json uses (mirrors p4_championship._save_history), so a
        season shows dashboard info from its 1st round onward instead of only
        after the whole season is archived at season end."""
        wiz = self._wiz
        df = getattr(wiz, 'df', None)
        rounds = getattr(wiz, 'round_results', None)
        if df is None or not rounds:
            return []
        roster = {str(r['name']): (int(r['bike_number']), str(r['team']), str(r['manufacturer']))
                  for _, r in df.iterrows()}
        rounds_detail = []
        for rd in rounds:
            races_out = []
            for race_df in rd['races']:
                race = []
                for _, r in race_df.iterrows():
                    name = str(r['name'])
                    bn, team, manu = roster.get(name, (0, '', ''))
                    pos, dnf = int(r['pos']), bool(r['dnf'])
                    race.append({
                        'name': name, 'team': team, 'manufacturer': manu,
                        'bike_number': bn, 'pos': pos, 'dnf': dnf,
                        'fastest_lap': bool(r.get('fastest_lap', False)),
                        'pole': int(r.get('grid_pos', 0)) == 1,
                        'points': 0 if dnf else int(POINTS.get(pos, 0)),
                    })
                races_out.append(race)
            rounds_detail.append({'circuit': str(rd['circuit']), 'country': str(rd['country']),
                                  'races': races_out})
        return rounds_detail

    def _refresh_data(self):
        """Everything initializePage() does except deciding which stack page
        to land on — shared with resume_at_hub(), which reopens the hub
        directly on the dashboard instead of replaying the intro clip."""
        rider = self._wiz.load_career_rider() or {}
        seasons = self._load_history_seasons()
        name = rider.get('name')

        # Prefer the season currently being played (from its 1st completed
        # round onward) — only fall back to the last *archived* season when
        # nothing's been played yet this season (e.g. right at season start).
        live_rounds = self._build_live_rounds_detail()
        data = None
        if live_rounds:
            data = _season_tables_data({'rounds_detail': live_rounds})
            standings = ([{'name': n, 'team': data['names'][n]['team'],
                          'manufacturer': data['names'][n]['manufacturer'],
                          'points': data['rider_total'][n]} for n in data['riders_sorted']]
                         if data is not None else [])
            honours = _honours_data(data)['riders'] if data is not None else None
            recent_races = _recent_form(live_rounds, name or '')
            current_rounds_detail = live_rounds
        else:
            # seasons[] is append-ordered, so the last entry is the latest
            # one archived (see p4_championship._save_history).
            last_season = seasons[-1] if seasons else None
            standings = last_season.get('standings', []) if last_season else []
            honours = None
            current_rounds_detail = last_season.get('rounds_detail') if last_season else None
            if current_rounds_detail:
                data = _season_tables_data(last_season)
                if data is not None:
                    honours = _honours_data(data)['riders']
            recent_races = _rider_recent_races(None)   # filled in below once `rec` exists

        # Your Profile's Career Summary / Results should reflect the season
        # in progress too, not just fully-archived ones — fold the live
        # season in as a synthetic history entry before aggregating.
        seasons_for_rec = seasons
        if live_rounds:
            seasons_for_rec = seasons + [{
                'year': self._wiz.season_year, 'standings': standings,
                'stats': _stats_from_rounds_detail(live_rounds),
                'rounds_detail': live_rounds,
            }]
        rec = None
        if rider and seasons_for_rec:
            entry = _aggregate_riders(seasons_for_rec).get(name)
            if entry is not None:
                rec = {'name': name, **entry}    # _build_rider_race_matrix expects rec['name']
        self._profile.load(rider, rec)
        self._profile.reset()
        if not live_rounds:
            recent_races = _rider_recent_races(rec)

        team_standings = ([{'name': t, 'points': data['team_total'][t]} for t in data['teams_sorted']]
                          if data is not None else [])
        manu_standings = ([{'name': m, 'points': data['manu_total'][m]} for m in data['manu_sorted']]
                          if data is not None else [])

        trend = _rider_position_trend(current_rounds_detail or [], name or '')
        self._hub_dashboard.load(standings, recent_races, honours,
                                 team_standings, manu_standings,
                                 data['names'] if data is not None else {})
        self._season_stats_screen.load(standings, name or '', honours, trend)

        self._calendar.load(self._wiz.season_df)
        bar = self._calendar.scrollbar()
        if bar is not None:
            bar.setValue(0)

    def initializePage(self):
        self._refresh_data()
        self._hub_focus = 0
        self._sync_hub_focus()
        self._stack.setCurrentIndex(0)
        self._wiz.pause_music()     # the intro clip has its own audio
        self._intro.start()
        self.setFocus()     # keep focus off the video widget so Esc/Enter both reach handle_key

    def resume_at_hub(self):
        """Reopen straight on the dashboard, skipping the intro clip —
        used when a race session bails back to the hub mid-season (Esc
        after a round) instead of arriving here fresh via Calendar."""
        self._refresh_data()
        self._hub_focus = 0
        self._sync_hub_focus()
        self._stack.setCurrentIndex(1)
        self._wiz.resume_music()
        self.setFocus()

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

        if idx == 1:                                     # hub — Esc disabled, use the Main Menu tab
            if key in (K.Key_Left, K.Key_Right):
                self._hub_focus = (self._hub_focus + (1 if key == K.Key_Right else -1)) % 5
                self._sync_hub_focus()
            elif key in (K.Key_Return, K.Key_Enter, K.Key_Space):
                (self._go_next, self._open_profile, self._open_calendar,
                 self._open_season_stats_screen, self._confirm_main_menu)[self._hub_focus]()
            return True

        if idx == 2:                                      # Your Profile owns its own sub-nav
            if self._profile.handle_key(key) == 'close':
                self._stack.setCurrentIndex(1)
            return True

        if idx == 3:                                       # calendar detail
            if key in (K.Key_Escape, K.Key_Backspace):
                self._stack.setCurrentIndex(1)
            elif key in (K.Key_Up, K.Key_Down):
                self._calendar.scroll(-60 if key == K.Key_Up else 60)
            return True

        if idx == 4:                                       # Season Stats owns its own sub-nav
            if self._season_stats_screen.handle_key(key) == 'close':
                self._stack.setCurrentIndex(1)
            return True

        return True

    def _open_profile(self):
        self._profile.reset()      # always land on the tab bar, not the last-viewed sub-tab
        self._stack.setCurrentIndex(2)

    def _open_calendar(self):
        self._stack.setCurrentIndex(3)

    def _open_season_stats_screen(self):
        self._season_stats_screen.reset()   # always land on the tab bar, not the last-viewed sub-tab
        self._stack.setCurrentIndex(4)

    def _go_next(self):
        self._wiz.next()

    def _confirm_main_menu(self):
        dlg = ExitDialog(self._wiz, message='Return to Main Menu?', confirm_text='Yes, Return')
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._wiz.accept()      # bail out of the season start -> Home

    # ── Background painting: static image behind the hub/profile/calendar ────
    # (the intro is a separate, fully opaque video widget — see _SeasonIntroVideo)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        offset = self.mapTo(self._wiz, self.rect().topLeft())
        self._vbg.paint(p, self, full_size=self._wiz.size(), offset=offset)

    def paint_gap_overlay(self, painter, rect):
        # QWizard reserves a thin strip below the page for its hidden button
        # row; _GapFiller already continues self._vbg (the static hub photo)
        # into that strip automatically. But during the intro, the visible
        # page content is the separate opaque video widget, not this photo —
        # cover the strip in black then so it doesn't show a mismatched photo
        # sliver under the video.
        if self._stack.currentIndex() == 0:
            painter.fillRect(rect, QColor(0, 0, 0))
