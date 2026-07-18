import json
from pathlib import Path

from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout, QWidget,
                              QLabel, QStackedWidget, QFrame, QDialog)
from PyQt6.QtGui import (QFont, QPainter, QColor, QPixmap, QPainterPath,
                          QLinearGradient)
from PyQt6.QtCore import Qt, QTimer, QUrl, QRect, QRectF, pyqtSignal

from app.pages.p_gallery import STATS, _make_scroll_area, _BIKES_DIR, _BIKE_IMAGE
from app.pages.p_calendar import _SlotBar
from app.pages.p_home import ExitDialog
from app.pages.p_history import (_aggregate_riders, _build_rider_race_matrix,
                                  _stat_tiles, _TOTAL_COLS, _pos_bg, _medal_color,
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
    instead of being covered corner to corner."""

    def __init__(self, inner: QWidget, margin: int = _TINT_MARGIN):
        super().__init__()
        self._margin = margin
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
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
        outer.setContentsMargins(56, 52, 56, 48)
        outer.setSpacing(0)

        title = QLabel('BASIC INFO')
        title.setFont(QFont('Segoe UI', 26, QFont.Weight.Bold))
        title.setStyleSheet('color:#ffffff; letter-spacing:2px; background:transparent; border:none;')
        outer.addWidget(title)
        outer.addSpacing(30)

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
        fields_lay.setSpacing(18)
        self._values = {}
        for key in self.FIELDS:
            kl = QLabel(key)
            kl.setFont(QFont('Segoe UI', 9))
            kl.setStyleSheet('color:#ffffff; letter-spacing:2px; background:transparent; border:none;')
            vl = QLabel('—')
            vl.setFont(QFont('Segoe UI', 18, QFont.Weight.Bold))
            vl.setStyleSheet('color:#ffffff; background:transparent; border:none;')
            row = QVBoxLayout()
            row.setSpacing(4)
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

        right_lay.addSpacing(36)

        self._bike_lbl = QLabel()
        self._bike_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._bike_lbl.setStyleSheet('background: transparent; border: none;')
        right_lay.addWidget(self._bike_lbl, 0, Qt.AlignmentFlag.AlignHCenter)
        right_lay.addSpacing(20)

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
        pix = _big_bike_pixmap(rider.get('team', ''), height=240)
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
        self.setFixedHeight(34)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        label_w, val_w = 220, 56
        bar_x = label_w
        bar_w = w - label_w - val_w - 12

        p.setFont(QFont('Segoe UI', 13))
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

        p.setFont(QFont('Segoe UI', 13, QFont.Weight.Bold))
        p.setPen(QColor('#ffffff'))
        p.drawText(QRect(w - val_w, 0, val_w, h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   str(self._value))


class _RatingPowerBar(QWidget):
    def __init__(self, score: float):
        super().__init__()
        self._score = score
        self._fill  = score / 100.0
        self.setFixedHeight(50)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        label_w, val_w = 220, 120
        bar_x = label_w
        bar_w = w - label_w - val_w - 12

        p.setFont(QFont('Segoe UI', 14, QFont.Weight.Bold))
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

        p.setFont(QFont('Segoe UI', 15, QFont.Weight.Bold))
        p.setPen(QColor('#ffffff'))
        p.drawText(QRect(w - val_w, 0, val_w, h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   f'{self._score:.1f} / 100')


class _RatingView(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(56, 52, 56, 48)
        lay.setSpacing(0)

        title = QLabel('YOUR RATING')
        title.setFont(QFont('Segoe UI', 26, QFont.Weight.Bold))
        title.setStyleSheet('color:#ffffff; letter-spacing:2px; background:transparent; border:none;')
        lay.addWidget(title)
        lay.addSpacing(40)

        self._bars_holder = QWidget()
        self._bars_holder.setStyleSheet('background: transparent;')
        self._bars_lay = QVBoxLayout(self._bars_holder)
        self._bars_lay.setContentsMargins(0, 0, 0, 0)
        self._bars_lay.setSpacing(22)
        lay.addWidget(self._bars_holder)
        lay.addSpacing(36)

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

        self._scrolls = []
        for view in (self._basic, self._results, self._rating):
            sc = _make_scroll_area()
            sc.setWidget(view)
            self._scrolls.append(sc)
            self._content.addWidget(_TintWrap(sc))                 # 1/2/3

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
            bar = self._scrolls[self._focus].verticalScrollBar()
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

def _standings_window(standings: list, rider_name: str, span: int = 5):
    """(start_index, rows) — up to `span` rows centred on the rider, clamped
    at the top/bottom of the full standings."""
    idx = next((i for i, s in enumerate(standings) if s.get('name') == rider_name), None)
    if idx is None:
        return 0, standings[:span]
    half = span // 2
    start = max(0, idx - half)
    end = min(len(standings), start + span)
    start = max(0, end - span)
    return start, standings[start:end]


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


class _FormBox(QFrame):
    """One race in the rider's recent-form strip: flag, then the result
    filled with the same colour the race-by-race grids use."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(80, 116)
        self.setStyleSheet('background: transparent; border: none;')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(0)

        self._flag_lbl = QLabel()
        self._flag_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._flag_lbl.setFixedHeight(32)
        self._flag_lbl.setStyleSheet('background: transparent; border: none;')
        lay.addWidget(self._flag_lbl)
        lay.addSpacing(8)

        self._bottom = QWidget()
        bl = QVBoxLayout(self._bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        self._result_lbl = QLabel('')
        self._result_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._result_lbl.setFont(QFont('Segoe UI', 15, QFont.Weight.Bold))
        self._result_lbl.setStyleSheet('color:#ffffff; background: transparent; border: none;')
        bl.addWidget(self._result_lbl)
        lay.addWidget(self._bottom, 1)

    def load(self, country: str | None, result: dict | None):
        pix = _flag_pixmap(country, height=28) if country else None
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


class _StandingsPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(0)

        title = QLabel('STANDINGS')
        title.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
        title.setStyleSheet('color:#ffffff; letter-spacing:2px; background:transparent; border:none;')
        lay.addWidget(title)
        lay.addSpacing(14)

        header = QWidget()
        header.setStyleSheet('background: transparent;')
        hl = QHBoxLayout(header)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(12)
        pos_h = QLabel('POS'); pos_h.setFixedWidth(32)
        rider_h = QLabel('RIDER')
        pts_h = QLabel('PTS'); pts_h.setFixedWidth(50)
        pts_h.setAlignment(Qt.AlignmentFlag.AlignRight)
        for l in (pos_h, rider_h, pts_h):
            l.setFont(QFont('Segoe UI', 8, QFont.Weight.Bold))
            l.setStyleSheet('color:#ffffff; letter-spacing:1px; background:transparent; border:none;')
        hl.addWidget(pos_h)
        hl.addWidget(rider_h, 1)
        hl.addWidget(pts_h)
        lay.addWidget(header)
        lay.addSpacing(8)

        self._rows_holder = QWidget()
        self._rows_holder.setStyleSheet('background: transparent;')
        self._rows_lay = QVBoxLayout(self._rows_holder)
        self._rows_lay.setContentsMargins(0, 0, 0, 0)
        self._rows_lay.setSpacing(10)
        lay.addWidget(self._rows_holder)
        lay.addStretch(1)

    def load(self, standings: list, rider_name: str):
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
        start, window = _standings_window(standings, rider_name)
        for i, s in enumerate(window):
            pos = start + i + 1
            team_color = TEAM_COLOR.get(s.get('team', '')) or MANU_COLOR.get(
                s.get('manufacturer', ''), _DEFAULT_COLOR)
            bg = row_bg(team_color)
            row = QFrame()
            row.setStyleSheet(f'background: {bg.name()}; border-radius: 6px; border: none;')
            rl = QHBoxLayout(row)
            rl.setContentsMargins(14, 8, 14, 8)
            rl.setSpacing(12)
            pos_lbl = QLabel(str(pos)); pos_lbl.setFixedWidth(28)
            name_lbl = QLabel(str(s.get('name', '')).upper())
            pts_lbl = QLabel(str(int(s.get('points', 0)))); pts_lbl.setFixedWidth(50)
            pts_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
            for l in (pos_lbl, name_lbl, pts_lbl):
                l.setFont(QFont('Segoe UI', 12, QFont.Weight.Bold))
                l.setStyleSheet('color:#ffffff; background:transparent; border:none;')
            rl.addWidget(pos_lbl)
            rl.addWidget(name_lbl, 1)
            rl.addWidget(pts_lbl)
            self._rows_lay.addWidget(row)


class _FormPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(0)

        title = QLabel('RECENT FORM')
        title.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
        title.setStyleSheet('color:#ffffff; letter-spacing:2px; background:transparent; border:none;')
        lay.addWidget(title)
        lay.addSpacing(14)

        boxes_holder = QWidget()
        boxes_holder.setStyleSheet('background: transparent;')
        boxes_lay = QHBoxLayout(boxes_holder)
        boxes_lay.setContentsMargins(0, 0, 0, 0)
        boxes_lay.setSpacing(12)
        self._boxes = [_FormBox() for _ in range(5)]
        for b in self._boxes:
            boxes_lay.addWidget(b)
        boxes_lay.addStretch(1)
        lay.addWidget(boxes_holder)
        lay.addStretch(1)

    def load(self, races: list):
        # Chronological, earliest on the left — blanks (races not yet run)
        # trail on the right instead of leading on the left.
        window = list(races[-len(self._boxes):])
        padded = window + [(None, None)] * (len(self._boxes) - len(window))
        for box, (country, result) in zip(self._boxes, padded):
            box.load(country, result)


def _mini_board(title: str, entries: list) -> QWidget:
    col = QWidget()
    col.setStyleSheet('background: transparent;')
    lay = QVBoxLayout(col)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)

    t = QLabel(title)
    t.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
    t.setStyleSheet('color:#ffffff; letter-spacing:1px; background:transparent; border:none;')
    lay.addWidget(t)
    lay.addSpacing(4)

    if not entries:
        ph = QLabel('—')
        ph.setFont(QFont('Segoe UI', 11))
        ph.setStyleSheet('color:#8a8aa2; background:transparent; border:none;')
        lay.addWidget(ph)
    for i, (name, count) in enumerate(entries[:3], start=1):
        row = QWidget()
        row.setStyleSheet('background: transparent;')
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        medal = _medal_color(i) or '#ffffff'
        pos_lbl = QLabel(str(i)); pos_lbl.setFixedWidth(16)
        name_lbl = QLabel(str(name).upper())
        count_lbl = QLabel(str(count))
        pos_lbl.setStyleSheet(f'color:{medal}; background:transparent; border:none;')
        for l in (name_lbl, count_lbl):
            l.setStyleSheet('color:#ffffff; background:transparent; border:none;')
        for l in (pos_lbl, name_lbl, count_lbl):
            l.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
        rl.addWidget(pos_lbl)
        rl.addWidget(name_lbl, 1)
        rl.addWidget(count_lbl)
        lay.addWidget(row)
    lay.addStretch(1)
    return col


class _SeasonStatsPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(0)

        title = QLabel('SEASON STATS')
        title.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
        title.setStyleSheet('color:#ffffff; letter-spacing:2px; background:transparent; border:none;')
        lay.addWidget(title)
        lay.addSpacing(14)

        self._cols_holder = QWidget()
        self._cols_holder.setStyleSheet('background: transparent;')
        self._cols_lay = QVBoxLayout(self._cols_holder)
        self._cols_lay.setContentsMargins(0, 0, 0, 0)
        self._cols_lay.setSpacing(22)
        lay.addWidget(self._cols_holder)
        lay.addStretch(1)

    def load(self, honours: dict | None):
        while self._cols_lay.count():
            item = self._cols_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        board = honours or {}
        self._cols_lay.addWidget(_mini_board('TOP WINNERS', board.get('wins', [])))
        self._cols_lay.addWidget(_mini_board('TOP PODIUMS', board.get('podiums', [])))
        self._cols_lay.addWidget(_mini_board('TOP POLESITTERS', board.get('poles', [])))


class _HubDashboard(QWidget):
    """Sits below the main hub's tab bar: last-season standings + recent form
    on the left, that season's top-3 honours on the right."""

    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        outer = QHBoxLayout(self)
        outer.setContentsMargins(56, 0, 56, 40)
        outer.setSpacing(56)

        left_col = QVBoxLayout()
        left_col.setSpacing(24)
        self._standings = _StandingsPanel()
        self._form = _FormPanel()
        left_col.addWidget(_TintWrap(self._standings, margin=0), 1)
        left_col.addWidget(_TintWrap(self._form, margin=0), 1)
        outer.addLayout(left_col, 1)

        self._season_stats = _SeasonStatsPanel()
        outer.addWidget(_TintWrap(self._season_stats, margin=0), 1)

    def load(self, standings: list, rider_name: str, races: list, honours: dict | None):
        self._standings.load(standings, rider_name)
        self._form.load(races)
        self._season_stats.load(honours)


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

        self._hub = _TopTabBar(['TO NEXT RACE', 'YOUR PROFILE', 'CALENDAR', 'MAIN MENU'])
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

    def initializePage(self):
        rider = self._wiz.load_career_rider() or {}
        seasons = self._load_history_seasons()
        name = rider.get('name')

        rec = None
        if rider and seasons:
            entry = _aggregate_riders(seasons).get(name)
            if entry is not None:
                rec = {'name': name, **entry}    # _build_rider_race_matrix expects rec['name']
        self._profile.load(rider, rec)
        self._profile.reset()

        # Prefer the season currently being played (from its 1st completed
        # round onward) — only fall back to the last *archived* season when
        # nothing's been played yet this season (e.g. right at season start).
        live_rounds = self._build_live_rounds_detail()
        if live_rounds:
            data = _season_tables_data({'rounds_detail': live_rounds})
            standings = ([{'name': n, 'team': data['names'][n]['team'],
                          'manufacturer': data['names'][n]['manufacturer'],
                          'points': data['rider_total'][n]} for n in data['riders_sorted']]
                         if data is not None else [])
            honours = _honours_data(data)['riders'] if data is not None else None
            recent_races = _recent_form(live_rounds, name or '')
        else:
            # seasons[] is append-ordered, so the last entry is the latest
            # one archived (see p4_championship._save_history).
            last_season = seasons[-1] if seasons else None
            standings = last_season.get('standings', []) if last_season else []
            honours = None
            if last_season and last_season.get('rounds_detail'):
                data = _season_tables_data(last_season)
                if data is not None:
                    honours = _honours_data(data)['riders']
            recent_races = _rider_recent_races(rec)
        self._hub_dashboard.load(standings, name or '', recent_races, honours)

        self._calendar.load(self._wiz.season_df)
        bar = self._calendar.scrollbar()
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

        if idx == 1:                                     # hub — Esc disabled, use the Main Menu tab
            if key in (K.Key_Left, K.Key_Right):
                self._hub_focus = (self._hub_focus + (1 if key == K.Key_Right else -1)) % 4
                self._sync_hub_focus()
            elif key in (K.Key_Return, K.Key_Enter, K.Key_Space):
                (self._go_next, self._open_profile,
                 self._open_calendar, self._confirm_main_menu)[self._hub_focus]()
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

        return True

    def _open_profile(self):
        self._profile.reset()      # always land on the tab bar, not the last-viewed sub-tab
        self._stack.setCurrentIndex(2)

    def _open_calendar(self):
        self._stack.setCurrentIndex(3)

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
