import json
from pathlib import Path

import numpy as np

from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout, QWidget,
                              QLabel, QStackedWidget, QFrame, QDialog, QSizePolicy,
                              QSpacerItem, QGraphicsOpacityEffect, QHeaderView)
from PyQt6.QtGui import (QFont, QFontMetrics, QPainter, QColor, QPixmap, QPainterPath,
                          QLinearGradient, QPen, QImage)
from PyQt6.QtCore import (Qt, QTimer, QUrl, QRect, QRectF, QPointF, QPoint, QSize,
                          pyqtSignal, QPropertyAnimation, QParallelAnimationGroup,
                          QSequentialAnimationGroup, QEasingCurve, QAbstractAnimation)

from app.pages.p_gallery import (STATS, _make_scroll_area, _BIKES_DIR, _BIKE_IMAGE,
                                  _RiderDetail)
from app.pages.p_calendar import _SlotBar
from app.pages.p_home import ExitDialog
from app.pages.p_history import (_aggregate_riders, _build_rider_race_matrix,
                                  _stat_tiles, _TOTAL_COLS, _pos_bg, _cell, _grid_cell,
                                  _rider_race_results,
                                  _flag_pixmap, _season_tables_data, _honours_data)
from app.widgets.table_utils import (TEAM_COLOR, MANU_COLOR, _DEFAULT_COLOR, row_bg,
                                      make_table)
from app.widgets.world_map import WorldMapWidget
from app.wizard import SESSION_NAMES, SESSION_DAY
from src.simulator import POINTS, WET_RACE_PROB_PCT
from src.engine import fmt_lap, perf_score_race, circuit_weights, norm


def _alpha_bbox(pix: QPixmap):
    """Bounding QRect of the non-transparent pixels. The bike cutouts bake in
    an inconsistent amount of empty margin around the motorcycle (some have
    far more clearance below the tyres than others), which threw off pixel
    alignment against the field rows next to it — cropping to this box first
    makes a requested `height=` map to the visible bike, not its padding."""
    img = pix.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    if w == 0 or h == 0:
        return None
    ptr = img.bits()
    ptr.setsize(h * img.bytesPerLine())
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(h, img.bytesPerLine())[:, :w * 4].reshape(h, w, 4)
    rows = np.any(arr[:, :, 3] > 10, axis=1)
    cols = np.any(arr[:, :, 3] > 10, axis=0)
    if not rows.any():
        return None
    top    = int(np.argmax(rows))
    bottom = h - int(np.argmax(rows[::-1]))
    left   = int(np.argmax(cols))
    right  = w - int(np.argmax(cols[::-1]))
    return QRect(left, top, right - left, bottom - top)


_BIKE_CROP_CACHE: dict = {}


def _cropped_bike_source(team_name: str):
    """The raw bike cutout, cropped to its visible content once per team and
    cached — cheap to rescale from afterwards."""
    if team_name in _BIKE_CROP_CACHE:
        return _BIKE_CROP_CACHE[team_name]
    img_file = _BIKE_IMAGE.get(team_name)
    pix = None
    if img_file:
        raw = QPixmap(str(_BIKES_DIR / img_file))
        if not raw.isNull():
            bbox = _alpha_bbox(raw)
            pix = raw.copy(bbox) if bbox is not None else raw
    _BIKE_CROP_CACHE[team_name] = pix
    return pix


def _big_bike_pixmap(team_name: str, height: int = 200):
    """Same source image as Gallery's _bike_pixmap, cropped to its visible
    content then scaled straight from the full-res file at a larger height —
    Gallery's version caches a 180px-tall copy for its compact side panel, and
    upscaling that cached copy for this page's bigger hero shot would just
    look blurry."""
    base = _cropped_bike_source(team_name)
    if base is None:
        return None
    return base.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)

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

    def set_text(self, text: str):
        self._lbl.setText(text)

    def _apply(self):
        if self._focused:
            bg, fg = '#e02840', '#ffffff'
        else:
            bg, fg = 'rgba(235,235,238,235)', '#1a1a1a'
        self.setStyleSheet(f'background: {bg}; border: none;')
        self._lbl.setStyleSheet(f'color: {fg}; letter-spacing: 1px; background: transparent; border: none;')


class _TopTabBar(QWidget):
    """A flat row of _TabButtons — the main hub's own tab bar (To Next
    Session / Your Profile / Season Info / Main Menu)."""

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


class _SideTabBar(QWidget):
    """A vertical stack of short tab bars, pinned to the top-left — the Your
    Profile and Season Info sub-hubs' browse menu. Up/Down moves the focus
    (contrast _TopTabBar's full-width horizontal row driven by Left/Right)."""

    _BAR_W = 280

    def __init__(self, labels: list):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)
        self._tabs = []
        for lbl in labels:
            b = _TabButton(lbl)
            b.setFixedWidth(self._BAR_W)
            self._tabs.append(b)
            outer.addWidget(b)

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
    fit on screen when the view first opened.

    `full_bleed` paints the tint edge-to-edge over the whole screen (no photo
    rim, no rounded corners) while keeping the content's layout margin for
    padding — used by the Your Profile sub-views, which own the full screen
    once opened and read best against a solid backdrop."""

    def __init__(self, inner: QWidget, margin: int = _TINT_MARGIN, full_bleed: bool = False):
        super().__init__()
        self._margin = margin
        self._full_bleed = full_bleed
        lay = QVBoxLayout(self)
        lay.setContentsMargins(margin, margin, margin, margin)
        lay.addWidget(inner)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._full_bleed:
            p.fillRect(self.rect(), _PANEL_TINT)
            return
        m = self._margin
        r = QRectF(self.rect().adjusted(m, m, -m, -m))
        path = QPainterPath()
        path.addRoundedRect(r, 20, 20)
        p.fillPath(path, _PANEL_TINT)


# ── Generic focus-then-open sub-hub ────────────────────────────────────────────
# Factored out of what used to be three copies of the same pattern (Your
# Profile; Season Info's own Standings/Calendar picker; Standings' own
# Riders/Teams/Manufacturers picker) — a vertical stack of tab bars pinned
# top-left, Up/Down to move focus, Enter to open the selection full-screen
# behind a dark tint, Escape to close it back to the tab stack.
#
# `cycle=True` swaps that browse-then-open model for a plain toggle (used by
# Riders' own Basic/Details, championship-mode style): there's no tab bar and
# no unopened state — it starts right on the first entry, and Enter steps to
# the next one in place instead of returning to a picker first.

class _SideSubHub(QWidget):
    """`entries` is a list of (label, view, needs_scroll). needs_scroll wraps
    the view in its own outer QScrollArea (for content that can outgrow the
    panel, e.g. a long standings list); the rest are tinted directly (either
    a view with fixed, bounded content, or one that already manages its own
    scrolling/navigation — see below). `label` is unused when cycle=True.

    Once opened (always true in cycle mode), arrow keys route to whichever
    the focused view provides, checked in this order:
      - `handle_key(key)` — the view is itself a nested _SideSubHub (or
        anything with the same contract); keys are forwarded wholesale, and
        this level only closes itself when the child reports 'close' (unless
        this level is itself cycle-mode, with no tab bar to fall back to —
        then 'close' is passed straight on up instead).
      - `scroll_by(dx, dy)` — the view owns internal widgets with their own
        scrollbars (e.g. a QTableWidget) that the wrapping QScrollArea can't
        reach directly.
      - `scrollbar()` — returns the QScrollBar to nudge (e.g. a view with its
        own internal QScrollArea, like the Calendar's slot list). Deliberately
        NOT a `scroll(dy)` method: QWidget already has a built-in
        scroll(dx, dy, [rect]) that would match `hasattr(view, 'scroll')` and
        silently shadow a one-argument version of the same name.
      - otherwise the wrapping QScrollArea's own vertical bar, if this entry
        was wrapped (needs_scroll=True)."""

    def __init__(self, entries: list, sidebar_margins=(48, 40, 48, 40),
                tint_margin: int = _TINT_MARGIN, cycle: bool = False):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._cycle = cycle
        # Non-cycle mode reserves content index 0 for the browse page (tab
        # bar), so entry i's wrap lives at index i+1; cycle mode has no
        # browse page, so entry i's wrap lives at index i directly.
        self._offset = 0 if cycle else 1
        labels = [e[0] for e in entries]
        self._views = [e[1] for e in entries]

        self._content = QStackedWidget()
        self._content.setStyleSheet('background: transparent;')

        self._sidebar = None
        if not cycle:
            self._sidebar = _SideTabBar(labels)
            browse_page = QWidget()
            browse_page.setStyleSheet('background: transparent;')
            bp_lay = QVBoxLayout(browse_page)
            bp_lay.setContentsMargins(*sidebar_margins)
            bp_lay.setSpacing(0)
            bp_lay.addWidget(self._sidebar, 0,
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            bp_lay.addStretch(1)
            self._content.addWidget(browse_page)                   # 0 nothing opened

        self._scrolls: list = []
        for _label, view, needs_scroll in entries:
            if hasattr(view, 'handle_key'):
                # A nested _SideSubHub: it paints its own tint (if any) only
                # once ITS OWN entries are opened, and its own browse page is
                # transparent, matching this level's browse page. Wrapping it
                # in another _TintWrap here would darken/overlay its tab bar
                # even while it's just showing a picker (nothing "opened"
                # yet) and offset its tab bar from where this one sits — so
                # it's added directly, no wrap, no extra margin, no tint.
                self._scrolls.append(None)
                self._content.addWidget(view)
                continue
            if needs_scroll:
                sc = _make_scroll_area()
                sc.setWidget(view)
                self._scrolls.append(sc)
                self._content.addWidget(_TintWrap(sc, margin=tint_margin, full_bleed=True))
            else:
                self._scrolls.append(None)
                self._content.addWidget(_TintWrap(view, margin=tint_margin, full_bleed=True))

        outer.addWidget(self._content, 1)

        self._focus = 0
        self._opened = cycle          # cycle mode has no browse state to start on
        if cycle:
            self._content.setCurrentIndex(0)

    def is_opened(self) -> bool:
        """True while a TINTED sub-view is actually showing (not a tab bar —
        this level's own, or, recursing, a nested sub-hub's) — a parent hub
        (or the wizard page's gap filler) uses this to keep a matching tint
        on whatever's below/around this widget. Merely having stepped into a
        nested sub-hub's OWN tab-bar picker doesn't count: that picker has no
        tint of its own (see __init__), so reporting True there would tint
        the gap while the visible content stays untinted."""
        if not self._opened:
            return False
        view = self._views[self._focus]
        if hasattr(view, 'is_opened'):
            return view.is_opened()
        return True

    def reset(self):
        """Always resume on the tab bar with nothing opened (or, in cycle
        mode, back on the first entry) — recurses into any nested sub-hub
        entry so it forgets its own last-viewed state too."""
        self._focus = 0
        self._opened = self._cycle
        if self._sidebar is not None:
            self._sync_focus()
        self._content.setCurrentIndex(0)
        for view, sc in zip(self._views, self._scrolls):
            if hasattr(view, 'reset'):
                view.reset()
            if sc is not None:
                bar = sc.verticalScrollBar()
                if bar is not None:
                    bar.setValue(0)

    def _sync_focus(self):
        for i, c in enumerate(self._sidebar.cards()):
            c.set_focused(i == self._focus)

    def handle_key(self, key: int):
        """Returns 'close' when the caller should return to its own tab bar
        (or bubble further up, if the caller has none, or if this level is
        itself cycle-mode); 'scroll' when the key panned an opened view's
        content rather than moving a tab focus — the wizard's 'navigate'
        click is only meant for the latter, so a caller that gets 'scroll'
        back should suppress it (see SeasonHubPage)."""
        K = Qt.Key
        n = len(self._views)
        if not self._opened:
            if key in (K.Key_Up, K.Key_Down):
                self._focus = (self._focus + (1 if key == K.Key_Down else -1)) % n
                self._sync_focus()
            elif key in (K.Key_Return, K.Key_Enter, K.Key_Space):
                self._opened = True
                self._content.setCurrentIndex(self._focus + self._offset)
            elif key in (K.Key_Escape, K.Key_Backspace):
                return 'close'
            return None

        view = self._views[self._focus]
        if hasattr(view, 'handle_key'):
            result = view.handle_key(key)
            if result == 'close':
                if self._cycle:
                    return 'close'   # no tab bar of our own to fall back to
                self._opened = False
                self._content.setCurrentIndex(0)
                return None
            return result   # propagate 'scroll' (or None) from the nested hub

        if key in (K.Key_Escape, K.Key_Backspace):
            if self._cycle:
                return 'close'
            self._opened = False
            self._content.setCurrentIndex(0)
            return None
        if self._cycle and key in (K.Key_Return, K.Key_Enter, K.Key_Space):
            # Championship-mode style: Enter steps to the next entry in
            # place (Basic -> Details -> Basic -> …) instead of opening one
            # from a picker — there's no picker here to open one from.
            self._focus = (self._focus + 1) % n
            self._content.setCurrentIndex(self._focus)
            return None
        if key in (K.Key_Up, K.Key_Down, K.Key_Left, K.Key_Right):
            dx = (-27 if key == K.Key_Left else 27 if key == K.Key_Right else 0)
            dy = (-60 if key == K.Key_Up else 60 if key == K.Key_Down else 0)
            sc = self._scrolls[self._focus]
            # Horizontal panning (e.g. a wide race-by-race grid's R1…Rn
            # columns) only ever makes sense through the view's OWN internal
            # widget — the wrapping QScrollArea's horizontal bar is disabled
            # (see _make_scroll_area) — so scroll_by always gets first go at dx.
            if dx and hasattr(view, 'scroll_by'):
                view.scroll_by(dx, 0)
            # Vertical panning of an entry that was wrapped in its own outer
            # QScrollArea (needs_scroll=True) must go through THAT bar, not
            # view.scroll_by(0, dy): a view like the race-by-race grid fixes
            # its own table height to fit every row with no scrollbar of its
            # own (see _build_riders_detail_table) precisely so the OUTER
            # QScrollArea is what has room to move — routing dy into the
            # table's own (zero-range) bar instead silently ate every Up/Down
            # press once the grid grew past one screen.
            if dy:
                if sc is not None:
                    bar = sc.verticalScrollBar()
                    if bar is not None:
                        bar.setValue(bar.value() + dy)
                elif hasattr(view, 'scroll_by'):
                    view.scroll_by(0, dy)
                elif hasattr(view, 'scrollbar'):
                    # NOTE: not `hasattr(view, 'scroll')` — every QWidget
                    # already has a built-in scroll(dx, dy, [rect]) that would
                    # match here and silently shadow a view's own single-
                    # argument scroll(); `scrollbar()` has no such collision.
                    bar = view.scrollbar()
                    if bar is not None:
                        bar.setValue(bar.value() + dy)
            return 'scroll'
        return None


# ── Your Profile: Basic Info ───────────────────────────────────────────────────

class _BasicInfoView(QWidget):
    FIELDS = ['NAME', 'AGE', 'NATIONALITY', 'BIKE NUMBER', 'TEAM', 'MANUFACTURER']

    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        outer = QVBoxLayout(self)
        # Sized to fit the stack's height even on a 150%-scaled 1080p screen
        # (~500 logical px of content room) without the scroll area this
        # view used to have. Both columns below are bottom-anchored (leading
        # stretch only, no trailing one) rather than centred — that pins
        # MANUFACTURER (left) and the stat tiles (right) to the same edge, and
        # with the bike cropped to its visible content and the gap beneath it
        # tuned to exactly two field-row steps, its bottom (the tyres) lands
        # level with BIKE NUMBER (two rows above MANUFACTURER). Swapping any
        # of the fonts/spacing below out of sync with the field rows' own
        # would throw that alignment off again — see the gap comment below.
        outer.setContentsMargins(48, 24, 48, 24)
        outer.setSpacing(0)

        title = QLabel('BASIC INFO')
        title.setFont(QFont('Segoe UI', 27, QFont.Weight.Bold))
        title.setStyleSheet('color:#ffffff; letter-spacing:2px; background:transparent; border:none;')
        outer.addWidget(title)
        outer.addSpacing(22)

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
        fields_lay.setSpacing(15)
        fields_lay.addStretch(1)
        self._values = {}
        for key in self.FIELDS:
            kl = QLabel(key)
            kl.setFont(QFont('Segoe UI', 11))
            kl.setStyleSheet('color:#ffffff; letter-spacing:2px; background:transparent; border:none;')
            vl = QLabel('—')
            vl.setFont(QFont('Segoe UI', 20, QFont.Weight.Bold))
            vl.setStyleSheet('color:#ffffff; background:transparent; border:none;')
            row = QVBoxLayout()
            row.setSpacing(2)
            row.addWidget(kl)
            row.addWidget(vl)
            fields_lay.addLayout(row)
            self._values[key] = vl
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
        # One field row's height+spacing is 73px (label 20 + row-gap 2 + value
        # 36 + fields_lay spacing 15). Below the bike, CAREER SUMMARY's title
        # (20) + spacing (10) + the stat tiles (43) already add up to 73 on
        # their own — so this spacer adds exactly one MORE row-step (73px) to
        # put two full steps between the (alpha-cropped, no hidden padding)
        # bike's bottom and the stat tiles' bottom, matching the two-row gap
        # between BIKE NUMBER and MANUFACTURER on the left.
        right_lay.addSpacing(73)

        summary_title = QLabel('CAREER SUMMARY')
        summary_title.setFont(QFont('Segoe UI', 11))
        summary_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        summary_title.setStyleSheet('color:#ffffff; letter-spacing:2px; background:transparent; border:none;')
        right_lay.addWidget(summary_title, 0, Qt.AlignmentFlag.AlignHCenter)
        right_lay.addSpacing(10)

        self._summary_holder = QWidget()
        self._summary_holder.setStyleSheet('background: transparent;')
        self._summary_lay = QVBoxLayout(self._summary_holder)
        self._summary_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.addWidget(self._summary_holder, 0, Qt.AlignmentFlag.AlignHCenter)

        body_lay.addWidget(right_w, 1)

        outer.addWidget(body, 1)

    def load(self, rider: dict, rec: dict | None):
        self._values['NAME'].setText(str(rider.get('name', '—')).upper())
        self._values['AGE'].setText(str(rider.get('age', '—')))
        self._values['NATIONALITY'].setText(str(rider.get('nationality', '—')))
        self._values['BIKE NUMBER'].setText(f"#{rider.get('bike_number', '—')}")
        self._values['TEAM'].setText(str(rider.get('team', '—')))
        self._values['MANUFACTURER'].setText(str(rider.get('manufacturer', '—')))
        pix = _big_bike_pixmap(rider.get('team', ''), height=236)
        self._bike_lbl.setPixmap(pix if pix is not None else QPixmap())

        while self._summary_lay.count():
            item = self._summary_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        totals = rec or {}
        self._summary_lay.addWidget(
            _stat_tiles([(label, totals.get(key, 0)) for label, key in _TOTAL_COLS], spacing=32))


# ── Your Profile: Results (career race-by-race, reuses the Rider Stats grid) ──

class _ResultsView(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        self._lay = QVBoxLayout(self)
        # Left/right margins trimmed down (paired with a tighter _TintWrap
        # inset for this view specifically — see _ProfileScreen) so the
        # race-by-race grid gets as much width as possible before its own
        # horizontal scrollbar kicks in, without sitting flush on the screen edge.
        self._lay.setContentsMargins(12, 44, 12, 40)
        self._lay.setSpacing(0)

        title = QLabel('CAREER RESULTS')
        title.setFont(QFont('Segoe UI', 30, QFont.Weight.Bold))
        title.setStyleSheet('color:#ffffff; letter-spacing:2px; background:transparent; border:none;')
        self._lay.addWidget(title)
        self._lay.addSpacing(22)
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
            note.setFont(QFont('Segoe UI', 14))
            note.setStyleSheet('color:#8a8aa2; background:transparent; border:none;')
            self._body = note
        self._lay.insertWidget(self._lay.count() - 1, self._body)

    def scroll_by(self, dx: int, dy: int):
        """Pan the race-by-race table with the arrow keys. It's a QTableWidget
        with its OWN scrollbars (wider than the card via R1…Rn, taller via a
        row per season); the wrapping QScrollArea can't move it — its
        horizontal bar is off and the table fits it vertically — so drive the
        table's own bars directly. A no-op on the placeholder note (a QLabel
        has no scrollbars)."""
        body = self._body
        hbar = getattr(body, 'horizontalScrollBar', None)
        vbar = getattr(body, 'verticalScrollBar', None)
        if dx and callable(hbar):
            bar = hbar(); bar.setValue(bar.value() + dx)
        if dy and callable(vbar):
            bar = vbar(); bar.setValue(bar.value() + dy)


# ── Your Profile: Rating (ability bars) ───────────────────────────────────────
# Dedicated (bigger, all-white-text) bars rather than reusing p_gallery's
# _StatBar/_PowerBar — those are tuned for Gallery's compact side panel and
# have their label/value colours baked into paintEvent, not parameterised.

class _RatingBar(QWidget):
    def __init__(self, label: str, value: float, color_hex: str):
        super().__init__()
        self._label = label
        self._value = value
        self._color = QColor(color_hex)
        self._fill  = value / 100.0
        self.setFixedHeight(38)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        label_w, val_w = 240, 84   # val_w fits a 2-decimal rating (e.g. "99.00")
        bar_x = label_w
        bar_w = w - label_w - val_w - 12

        p.setFont(QFont('Segoe UI', 15))
        p.setPen(QColor('#ffffff'))
        p.drawText(QRect(0, 0, label_w, h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._label)

        tr = QRectF(bar_x, h / 2 - 7, bar_w, 14)
        tp = QPainterPath(); tp.addRoundedRect(tr, 7, 7)
        p.fillPath(tp, QColor(22, 22, 38, 200))

        fw = max(14.0, bar_w * self._fill)
        fr = QRectF(bar_x, h / 2 - 7, fw, 14)
        fp = QPainterPath(); fp.addRoundedRect(fr, 7, 7)
        g = QLinearGradient(bar_x, 0, bar_x + fw, 0)
        g.setColorAt(0, self._color.darker(145))
        g.setColorAt(1, self._color)
        p.fillPath(fp, g)

        p.setFont(QFont('Segoe UI', 15, QFont.Weight.Bold))
        p.setPen(QColor('#ffffff'))
        p.drawText(QRect(w - val_w, 0, val_w, h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   f'{self._value:.2f}')


class _RatingPowerBar(QWidget):
    def __init__(self, score: float):
        super().__init__()
        self._score = score
        self._fill  = score / 100.0
        self.setFixedHeight(52)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        label_w, val_w = 240, 130
        bar_x = label_w
        bar_w = w - label_w - val_w - 12

        p.setFont(QFont('Segoe UI', 16, QFont.Weight.Bold))
        p.setPen(QColor('#ffffff'))
        p.drawText(QRect(0, 0, label_w, h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   'POWER RATING')

        tr = QRectF(bar_x, h / 2 - 9, bar_w, 18)
        tp = QPainterPath(); tp.addRoundedRect(tr, 9, 9)
        p.fillPath(tp, QColor(22, 22, 38, 200))

        fw = max(18.0, bar_w * self._fill)
        fr = QRectF(bar_x, h / 2 - 9, fw, 18)
        fp = QPainterPath(); fp.addRoundedRect(fr, 9, 9)
        g = QLinearGradient(bar_x, 0, bar_x + fw, 0)
        g.setColorAt(0.0, QColor('#0f6b22'))
        g.setColorAt(0.5, QColor('#22c044'))
        g.setColorAt(1.0, QColor('#5eff7e'))
        p.fillPath(fp, g)

        p.setFont(QFont('Segoe UI', 17, QFont.Weight.Bold))
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
        title.setFont(QFont('Segoe UI', 27, QFont.Weight.Bold))
        title.setStyleSheet('color:#ffffff; letter-spacing:2px; background:transparent; border:none;')
        lay.addWidget(title)
        lay.addSpacing(22)

        lay.addStretch(1)

        self._bars_holder = QWidget()
        self._bars_holder.setStyleSheet('background: transparent;')
        self._bars_lay = QVBoxLayout(self._bars_holder)
        self._bars_lay.setContentsMargins(0, 0, 0, 0)
        self._bars_lay.setSpacing(16)
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
            self._bars_lay.addWidget(_RatingBar(label, float(rider.get(col_name, 0)), color))

        while self._power_lay.count():
            item = self._power_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        score = sum(float(rider.get(c, 0)) for c, _, _ in STATS) / len(STATS) if rider else 0.0
        self._power_lay.addWidget(_RatingPowerBar(score))


# ── Your Profile sub-hub: Basic Info / Results / Rating ───────────────────────

class _ProfileScreen(QWidget):
    """Focus-then-open interaction: a stack of short tab bars pinned top-left,
    Up/Down moves the focus, Enter opens that sub-view FULL-SCREEN (the tabs
    give way to it, with a dark tint over the background for readability),
    Escape closes it back to the tab stack — a second Escape bubbles up to the
    main hub."""

    SUB_TABS = ['BASIC INFO', 'RESULTS', 'RATING']

    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._basic = _BasicInfoView()
        self._results = _ResultsView()
        self._rating = _RatingView()

        self._content = QStackedWidget()
        self._content.setStyleSheet('background: transparent;')
        # Index 0 (browse): the short tab bars stacked in the top-left corner
        # over the career background — Enter swaps to a full-screen view below,
        # so the tabs aren't kept alongside it (they live on this page only).
        self._sidebar = _SideTabBar(self.SUB_TABS)
        browse_page = QWidget()
        browse_page.setStyleSheet('background: transparent;')
        bp_lay = QVBoxLayout(browse_page)
        bp_lay.setContentsMargins(48, 40, 48, 40)
        bp_lay.setSpacing(0)
        bp_lay.addWidget(self._sidebar, 0,
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        bp_lay.addStretch(1)
        self._content.addWidget(browse_page)                       # 0 nothing opened

        # Only Results can outgrow the panel (a long career's race-by-race
        # grid) — Basic Info and Rating are fixed, bounded content and don't
        # need a scrollbar, so they skip the QScrollArea wrapper entirely.
        # Results also gets a tighter tint inset (16 vs. the usual 48) — its
        # race-by-race grid is the one view that's actually width-constrained
        # (R1…Rn columns), so it gets the extra room; Basic Info/Rating keep
        # the wider inset since their own layouts are already tuned to it.
        self._scrolls: list = []
        for view, needs_scroll, inset in ((self._basic, False, _TINT_MARGIN),
                                          (self._results, True, 16),
                                          (self._rating, False, _TINT_MARGIN)):
            if needs_scroll:
                sc = _make_scroll_area()
                sc.setWidget(view)
                self._scrolls.append(sc)
                self._content.addWidget(_TintWrap(sc, margin=inset, full_bleed=True))   # 1/2/3
            else:
                self._scrolls.append(None)
                self._content.addWidget(_TintWrap(view, margin=inset, full_bleed=True))

        outer.addWidget(self._content, 1)

        self._focus = 0
        self._opened = False

    def is_opened(self) -> bool:
        """True while a sub-view is showing full-bleed (not the tab bar) — the
        hub uses this to tint the reserved bottom strip to match."""
        return self._opened

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
        for i, c in enumerate(self._sidebar.cards()):
            c.set_focused(i == self._focus)

    def handle_key(self, key: int):
        """Returns 'close' when the caller should return to the main hub;
        'scroll' when the key panned the opened view's content rather than
        moving a tab focus — see _SideSubHub.handle_key for why that
        distinction matters to the caller."""
        K = Qt.Key
        if not self._opened:
            if key in (K.Key_Up, K.Key_Down):     # vertical stack of tab bars
                self._focus = (self._focus + (1 if key == K.Key_Down else -1)) % 3
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
            return None
        if key in (K.Key_Up, K.Key_Down, K.Key_Left, K.Key_Right):
            dx = (-27 if key == K.Key_Left else 27 if key == K.Key_Right else 0)
            dy = (-60 if key == K.Key_Up else 60 if key == K.Key_Down else 0)
            view = (self._basic, self._results, self._rating)[self._focus]
            sc = self._scrolls[self._focus]
            # Results: pan the race-by-race table horizontally across R1…Rn
            # through its OWN scrollbars (_ResultsView.scroll_by) — the
            # wrapping QScrollArea's horizontal bar is disabled (see
            # _make_scroll_area). Vertical panning, though, must go through
            # THAT wrapping QScrollArea, not scroll_by(0, dy): the table
            # fixes its own height to fit every season with no vertical
            # scrollbar of its own (_build_rider_race_matrix), so routing dy
            # into it was silently swallowing every Up/Down press once a
            # career grew past one screen of seasons.
            if dx and hasattr(view, 'scroll_by'):
                view.scroll_by(dx, 0)
            if dy:
                if sc is not None:
                    bar = sc.verticalScrollBar()
                    if bar is not None:
                        bar.setValue(bar.value() + dy)
                elif hasattr(view, 'scroll_by'):
                    view.scroll_by(0, dy)
            return 'scroll'
        return None


# ── Read-only calendar recap ───────────────────────────────────────────────────

class _CalendarView(QWidget):
    # Row height flexes between _ROW_MIN_H and _ROW_MAX_H so the whole
    # calendar — up to every available circuit (13 as of writing) — always
    # fills the viewport with no scrollbar and no dead space below the last
    # row: _fit_rows() sizes rows to consume the full available height
    # first, only clamping at the edges (MIN so a packed 13-round calendar
    # never gets uncomfortably thin; MAX so a short season's few rows don't
    # balloon to fill the whole screen on their own).
    _ROW_MIN_H   = 26
    _ROW_MAX_H   = 64
    _ROW_SPACING = 10

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
        self._lay.setSpacing(self._ROW_SPACING)
        self._lay.addStretch(1)
        self._scroll.setWidget(cont)
        outer.addWidget(self._scroll, 1)
        self._bars: list[_SlotBar] = []

    def load(self, season_df):
        while self._lay.count() > 1:
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        self._bars = []
        if season_df is None:
            return
        for i, (_, row) in enumerate(season_df.iterrows(), start=1):
            bar = _SlotBar(i)
            bar.set_circuit(row)
            self._bars.append(bar)
            self._lay.insertWidget(self._lay.count() - 1, bar)
        # Deferred a tick: the scroll area's viewport isn't laid out to its
        # final size yet on this same call (e.g. right after the page is
        # first built) — see resume_at_hub's own QTimer.singleShot(0, ...)
        # for the same reason.
        QTimer.singleShot(0, self._fit_rows)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_rows()

    def _fit_rows(self):
        n = len(self._bars)
        if not n:
            return
        avail = self._scroll.viewport().height()
        if avail <= 0:
            return
        spacing_total = self._ROW_SPACING * max(0, n - 1)
        row_h = max(self._ROW_MIN_H, min(self._ROW_MAX_H, (avail - spacing_total) // n))
        for bar in self._bars:
            bar.set_row_height(int(row_h))

    def scroll(self, delta: int):
        bar = self._scroll.verticalScrollBar()
        if bar is not None:
            bar.setValue(bar.value() + delta)

    def scrollbar(self):
        return self._scroll.verticalScrollBar()


# ── Hub dashboard: this season's standings / recent form / season honours ────
# Fills the empty space below the main hub's tab bar with a quick "where do
# things stand" recap — scoped to the season currently being played. Before
# its first round is completed everything reads empty (a fresh season starts
# from zero); the cumulative track-history boards and career totals are the
# only cross-season figures.

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


def _track_history(seasons_for_rec: list, circuit_name: str | None, limit: int = 5) -> tuple:
    """(winners, polesitters) at `circuit_name` across every season on
    record (archived + the live in-progress one folded into
    `seasons_for_rec`, oldest to newest) — each a (year, name) tuple, most
    recent first, capped to `limit`.

    Winners are read per-race (a round can run more than one race, each
    with its own winner); poles are read once per round from its first
    race only, mirroring _stats_from_rounds_detail's own rule against
    double-counting a round's shared grid."""
    if not circuit_name:
        return [], []
    winners, poles = [], []
    for season in sorted(seasons_for_rec, key=lambda s: s.get('year', 0)):
        year = season.get('year', '')
        for rnd in season.get('rounds_detail') or []:
            if str(rnd.get('circuit', '')) != circuit_name:
                continue
            races = rnd.get('races', [])
            for race in races:
                winner = next((r for r in race if not r.get('dnf') and int(r.get('pos', 0)) == 1), None)
                if winner is not None:
                    winners.append((year, winner['name']))
            if races:
                pole = next((r for r in races[0] if r.get('pole')), None)
                if pole is not None:
                    poles.append((year, pole['name']))
    return winners[-limit:][::-1], poles[-limit:][::-1]


def _track_records(seasons_for_rec: list, circuit_name: str | None) -> tuple:
    """(brlc, blc) at `circuit_name` across every recorded round — each a
    (seconds, name, year) tuple, or None if this track has no lap-record
    data yet (older history predates lap-time tracking, or it simply
    hasn't been raced this career). BRLC is the fastest lap set in either
    race; BLC also considers Practice and Qualifying — see
    p4_championship._round_lap_records, which computes both per round."""
    if not circuit_name:
        return None, None
    brlc, blc = None, None
    for season in seasons_for_rec:
        year = season.get('year', '')
        for rnd in season.get('rounds_detail') or []:
            if str(rnd.get('circuit', '')) != circuit_name:
                continue
            lr = rnd.get('lap_records') or {}
            race = lr.get('race')
            if race is not None and (brlc is None or race[0] < brlc[0]):
                brlc = (race[0], race[1], year)
            session = lr.get('session')
            if session is not None and (blc is None or session[0] < blc[0]):
                blc = (session[0], session[1], year)
    return brlc, blc


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

    def minimumSizeHint(self):
        # It elides, so it must never impose its full text width as a layout
        # minimum — otherwise a row of these would keep its whole column too
        # wide to shrink on a narrow window. Report ~zero width (keep height).
        return QSize(0, super().minimumSizeHint().height())

    def sizeHint(self):
        # Same reasoning for the preferred width: lean on the row's stretch to
        # size it, not the (possibly long) full text.
        return QSize(0, super().sizeHint().height())

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

    Both kinds run in two sequential phases (old page fades fully out,
    then the new page fades in) — never a crossfade, so no frame ever
    shows both pages' text at once:

    - kind='scroll': the outgoing snapshot also pops up a *little* (a
      small _SCROLL_NUDGE, not a full page-height) as it fades, and the
      incoming `container` mirrors it — starts nudged slightly below rest
      and eases up while fading in. A full-height traverse read as the page
      being "flung" off-screen; this keeps the same up-and-out direction
      as a hint of scrolling without the large travel. Used for paging
      within the same standings category (top 5 -> next 5 -> ...).
    - kind='fade': no movement at all — used when the category itself
      changes (e.g. Riders -> Teams).

    `owner` just needs to outlive the animation to keep it alive (Python
    would otherwise garbage-collect the QPropertyAnimation/group as soon as
    this function returns) — the calling panel passes `self`.
    """
    old_pixmap, old_geometry = snapshot
    if old_pixmap.isNull():
        return
    # A still-running previous transition would leave its overlay/effects
    # on screen while this one stacks its own on top. Qt's stop() does NOT
    # emit finished() for an animation halted mid-flight, so cleanup can't
    # ride on that signal alone — the previous transition's cleanup closure
    # is kept on the owner and invoked explicitly here.
    prev = getattr(owner, '_active_transition', None)
    if prev is not None:
        try:
            if prev.state() == QAbstractAnimation.State.Running:
                prev.stop()
        except RuntimeError:
            pass   # DeleteWhenStopped already tore the C++ object down
    prev_cleanup = getattr(owner, '_transition_cleanup', None)
    if prev_cleanup is not None:
        prev_cleanup()

    parent = container.parentWidget()
    overlay = QLabel(parent)
    overlay.setPixmap(old_pixmap)
    overlay.setGeometry(old_geometry)
    overlay.show()
    overlay.raise_()

    # Sequential, not a crossfade: the old page fades fully OUT before the
    # new one fades in. A crossfade draws both pages at once for its whole
    # duration, and any screenshot/glance mid-swap reads as the panel's
    # text being garbled/overlapping — with the half-and-half phasing there
    # is no frame in which two sets of rows are visible together.
    half = _TRANSITION_MS // 2

    out_effect = QGraphicsOpacityEffect(overlay)
    overlay.setGraphicsEffect(out_effect)
    out_fade = QPropertyAnimation(out_effect, b'opacity', overlay)
    out_fade.setDuration(half)
    out_fade.setStartValue(1.0)
    out_fade.setEndValue(0.0)

    # The container (already holding the new page) starts invisible for
    # phase 1 either way; phase 2 fades it in.
    in_effect = QGraphicsOpacityEffect(container)
    container.setGraphicsEffect(in_effect)
    in_effect.setOpacity(0.0)
    in_fade = QPropertyAnimation(in_effect, b'opacity', container)
    in_fade.setDuration(half)
    in_fade.setStartValue(0.0)
    in_fade.setEndValue(1.0)

    phase_out = QParallelAnimationGroup()
    phase_out.addAnimation(out_fade)
    phase_in = QParallelAnimationGroup()
    phase_in.addAnimation(in_fade)

    if kind == 'scroll':
        out_move = QPropertyAnimation(overlay, b'pos', overlay)
        out_move.setDuration(half)
        out_move.setStartValue(overlay.pos())
        out_move.setEndValue(overlay.pos() - QPoint(0, _SCROLL_NUDGE))
        out_move.setEasingCurve(QEasingCurve.Type.OutCubic)
        phase_out.addAnimation(out_move)

        settled_pos = container.pos()
        container.move(settled_pos + QPoint(0, _SCROLL_NUDGE))
        in_move = QPropertyAnimation(container, b'pos', container)
        in_move.setDuration(half)
        in_move.setStartValue(container.pos())
        in_move.setEndValue(settled_pos)
        in_move.setEasingCurve(QEasingCurve.Type.OutCubic)
        phase_in.addAnimation(in_move)

    group = QSequentialAnimationGroup(owner)
    group.addAnimation(phase_out)
    group.addAnimation(phase_in)

    _done = [False]

    def _cleanup():
        # Idempotent: runs on natural finish AND when the next transition
        # interrupts this one (see prev_cleanup above) — whichever first.
        if _done[0]:
            return
        _done[0] = True
        container.setGraphicsEffect(None)
        overlay.deleteLater()
        # An interrupted scroll phase can leave the container displaced by
        # its nudge; reasserting the layout snaps it back to rest.
        p = container.parentWidget()
        if p is not None and p.layout() is not None:
            p.layout().activate()
        # Drop the owner's refs if they still point at this transition, so
        # the next one doesn't poke a C++ object DeleteWhenStopped already
        # destroyed.
        if getattr(owner, '_transition_cleanup', None) is _cleanup:
            owner._transition_cleanup = None
            owner._active_transition = None

    group.finished.connect(_cleanup)
    owner._transition_cleanup = _cleanup
    owner._active_transition = group   # keep a live Python reference until done
    group.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


def _panel_title_parts(text: str) -> tuple:
    """(widget, label) of a dashboard panel's heading: centred, with a
    divider marking where the title ends and the panel's content begins.
    Callers that relabel the heading as the panel cycles categories keep
    the returned label; the rest use _panel_title() for just the widget."""
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
    return w, lbl


def _panel_title(text: str) -> QWidget:
    return _panel_title_parts(text)[0]


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

        # Category now rides in the title (e.g. "RIDER STANDINGS") since the
        # column-header row was removed — otherwise the panel would cycle
        # riders -> teams -> manufacturers with nothing saying which.
        title_w, self._title_lbl = _panel_title_parts('STANDINGS')
        lay.addWidget(title_w)
        lay.addItem(_soft_gap(10))

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
        self._title_lbl.setText(f'{mode} STANDINGS')
        standings = self._by_mode.get(mode, [])
        snapshot = _grab_snapshot(self._rows_holder) if transition else None

        while self._rows_lay.count():
            item = self._rows_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        if not standings:
            ph = QLabel('No standings yet — check back after the first round.')
            ph.setWordWrap(True)
            ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ph.setFont(QFont('Segoe UI', 10))
            ph.setStyleSheet('color:#8a8aa2; background:transparent; border:none;')
            # Hold the panel at exactly a filled 5-row page's height so an empty
            # standings card doesn't collapse and let the Expanding Recent Form
            # card below stretch to swallow the freed column height.
            ph.setFixedHeight(self._PAGE_SIZE * _DASH_ROW_H
                              + (self._PAGE_SIZE - 1) * self._rows_lay.spacing())
            self._rows_lay.addWidget(ph)
            return
        # Always exactly _PAGE_SIZE slots so every page keeps the same height
        # (the transition overlay relies on it — see _grab_snapshot) and the
        # panel never resizes as it cycles. A last page with fewer real
        # entries leaves its trailing slots as blank, fully transparent rows
        # rather than the old dim "—" placeholders.
        start = self._page_index * self._PAGE_SIZE
        window = standings[start:start + self._PAGE_SIZE]
        for i in range(self._PAGE_SIZE):
            pos = start + i + 1
            filled = i < len(window)
            row = QFrame()
            # Fixed height: a Preferred-height row is fair game for the
            # layout to squeeze when the column runs short, and a squeezed
            # row clips the bottom of its text. Locked, it can't.
            row.setFixedHeight(_DASH_ROW_H)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(10, 0, 10, 0)
            rl.setSpacing(8)
            pos_lbl = QLabel(str(pos) if filled else ''); pos_lbl.setFixedWidth(24)
            name_lbl = _ElideLabel()
            # Rider standings show the manufacturer between the name and the
            # points (values only, no header) — teams/manufacturers already
            # carry that identity in their own name column, so only RIDER mode
            # gets the extra column.
            manu_lbl = _ElideLabel() if mode == 'RIDER' else None
            if manu_lbl is not None:
                # Kept narrow (the longest manufacturer, "KAWASAKI", is ~72px)
                # and pushed to the right so the rider-name column stays wide
                # enough for long names like "JUAN FRANCISCO VALDES".
                manu_lbl.setFixedWidth(78)
            pts_lbl = QLabel(); pts_lbl.setFixedWidth(44)
            pts_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            labels = [pos_lbl, name_lbl, pts_lbl] + ([manu_lbl] if manu_lbl is not None else [])
            for l in labels:
                l.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))

            if filled:
                s = window[i]
                bg = row_bg(self._row_color(mode, s))
                row.setStyleSheet(f'background: {bg.name()}; border-radius: 6px; border: none;')
                name_lbl.setFullText(str(s.get('name', '')).upper())
                if manu_lbl is not None:
                    manu_lbl.setFullText(str(s.get('manufacturer', '')).upper())
                pts_lbl.setText(str(int(s.get('points', 0))))
            else:
                # Empty slot: invisible, but still _DASH_ROW_H tall so the
                # panel's overall size doesn't change page to page.
                row.setStyleSheet('background: transparent; border: none;')

            for l in labels:
                l.setStyleSheet('color:#ffffff; background:transparent; border:none;')
            rl.addWidget(pos_lbl)
            rl.addWidget(name_lbl, 1)
            if manu_lbl is not None:
                rl.addWidget(manu_lbl)
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

    Always renders exactly `_MINI_BOARD_SLOTS` rows so this board's height
    stays constant as it cycles categories (a category-dependent height here
    was resizing _FormPanel too, since both share a grid row) — but a slot
    past a category's real entries is left fully blank rather than shown as
    a dim placeholder row.

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
    if not entries:
        # Same "empty but not collapsed" treatment as the Standings panel:
        # a centred note held at the board's normal (3-row) height so the
        # column layout doesn't shift as the categories cycle while empty.
        ph = QLabel('No results yet — check back after the first round.')
        ph.setWordWrap(True)
        ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph.setFont(QFont('Segoe UI', 9))
        ph.setStyleSheet('color:#8a8aa2; background:transparent; border:none;')
        ph.setFixedHeight(_MINI_BOARD_SLOTS * _MINI_ROW_H
                          + (_MINI_BOARD_SLOTS - 1) * lay.spacing())
        lay.addWidget(ph)
        lay.addStretch(1)
        return col
    for i in range(1, _MINI_BOARD_SLOTS + 1):
        filled = i <= len(entries)
        row = QFrame()
        row.setFixedHeight(_MINI_ROW_H)   # same no-squeeze rule as the standings rows
        rl = QHBoxLayout(row)
        rl.setContentsMargins(10, 0, 10, 0)
        rl.setSpacing(8)
        pos_lbl = QLabel(str(i) if filled else ''); pos_lbl.setFixedWidth(24)
        name_lbl = _ElideLabel()
        count_lbl = QLabel(); count_lbl.setFixedWidth(44)
        count_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for l in (pos_lbl, name_lbl, count_lbl):
            l.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))

        if filled:
            name, count = entries[i - 1]
            info = names_map.get(name, {})
            color = TEAM_COLOR.get(info.get('team', '')) or MANU_COLOR.get(
                info.get('manufacturer', ''), _DEFAULT_COLOR)
            row.setStyleSheet(f'background: {row_bg(color).name()}; border-radius: 6px; border: none;')
            name_lbl.setFullText(str(name).upper())
            count_lbl.setText(str(count))
        else:
            # Empty slot: invisible, but still _MINI_ROW_H tall so the board's
            # height stays constant across categories with fewer entries.
            row.setStyleSheet('background: transparent; border: none;')

        for l in (pos_lbl, name_lbl, count_lbl):
            l.setStyleSheet('color:#ffffff; background:transparent; border:none;')
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


_INFO_ROW_H = 22   # locked, same no-squeeze rule as the standings rows


def _info_row(label: str, label_color: str = '#9a9ab2') -> tuple:
    """label:value line for _NextRacePanel's circuit-info/records block — a
    small caption on the left, an eliding bold value on the right (a
    long circuit name or a "time — HOLDER — year" record string both need
    to shrink gracefully instead of overrunning the card). The caption
    keeps its natural width (a fixed one clipped "LONGEST STRAIGHT" mid-
    word) and the row's height is locked so a squeezed column clips the
    card's bottom edge cleanly instead of mashing lines into each other.
    `label_color` defaults to the dim GP-Info caption; the Upcoming Session
    card passes white."""
    row = QWidget()
    row.setStyleSheet('background: transparent;')
    row.setFixedHeight(_INFO_ROW_H)
    rl = QHBoxLayout(row)
    rl.setContentsMargins(0, 0, 0, 0)
    rl.setSpacing(8)
    lbl = QLabel(label)
    lbl.setFont(QFont('Segoe UI', 8, QFont.Weight.Bold))
    lbl.setStyleSheet(f'color:{label_color}; letter-spacing:1px; background:transparent; border:none;')
    val = _ElideLabel()
    val.setFont(QFont('Segoe UI', 10, QFont.Weight.Bold))
    val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    val.setStyleSheet('color:#ffffff; background:transparent; border:none;')
    rl.addWidget(lbl)
    rl.addWidget(val, 1)
    return row, val


def _record_row(label: str) -> tuple:
    """A lap-record entry for the GP Info card. Unlike _info_row (caption and
    value fighting for one line), the caption sits on its own line with the
    value spanning the FULL card width beneath it. A long 'time — HOLDER —
    year' string then has the whole card to render in, so it no longer gets
    ellipsised whenever the caption is wide ('ALL TIME LAP RECORD') or the
    left column is narrowed — which is why some tracks' records showed cut
    off and others didn't."""
    box = QWidget()
    box.setStyleSheet('background: transparent;')
    bl = QVBoxLayout(box)
    bl.setContentsMargins(0, 0, 0, 0)
    bl.setSpacing(2)
    cap = QLabel(label)
    cap.setFont(QFont('Segoe UI', 8, QFont.Weight.Bold))
    cap.setStyleSheet('color:#9a9ab2; letter-spacing:1px; background:transparent; border:none;')
    val = _ElideLabel()
    val.setFont(QFont('Segoe UI', 10, QFont.Weight.Bold))
    val.setStyleSheet('color:#ffffff; background:transparent; border:none;')
    bl.addWidget(cap)
    bl.addWidget(val)
    return box, val


def _fmt_record(rec: tuple | None) -> str:
    """(seconds, name, year) -> 'MM:SS.mmm — HOLDER NAME — year', or '—'
    before this track has any lap-record data on file."""
    if rec is None:
        return '—'
    sec, name, year = rec
    return f'{fmt_lap(sec)} — {str(name).upper()} — {year}'


# Shared flag box for the two GP-header cards (GP Info's _NextRacePanel and
# the between-GP _UpcomingSessionPanel preview): a fixed WIDTH×HEIGHT so every
# country's flag occupies the exact same rectangle. Without a fixed width,
# flags scale to height only and wide flags (e.g. Qatar, ~2.5:1) come out far
# longer than a 3:2 one (France) at the same height. 96×64 is 3:2, so a
# standard 3:2 flag is undistorted and unusually-wide ones are reined in to
# match rather than overhanging the card.
_GP_FLAG_W, _GP_FLAG_H = 96, 64


class _NextRacePanel(QWidget):
    """Top-left card: the upcoming round's title and national flag, a
    second divider (border2), then the circuit's vitals and its two
    all-time lap records — the same divider-under-heading look every
    other dashboard panel uses (via _panel_title), just with a flag and a
    stat block standing in for a row list."""

    _FLAG_H = _GP_FLAG_H

    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(0)

        self._title_holder = QWidget()
        self._title_holder.setStyleSheet('background: transparent;')
        self._title_lay = QVBoxLayout(self._title_holder)
        self._title_lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._title_holder)
        lay.addItem(_soft_gap(12))

        self._flag_lbl = QLabel()
        self._flag_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._flag_lbl.setFixedHeight(self._FLAG_H)
        lay.addWidget(self._flag_lbl)
        lay.addItem(_soft_gap(12))

        border2 = QFrame()
        border2.setFixedHeight(1)
        border2.setStyleSheet('background: rgba(255,255,255,60); border:none;')
        lay.addWidget(border2)
        lay.addItem(_soft_gap(10))

        info_holder = QWidget()
        info_holder.setStyleSheet('background: transparent;')
        info_lay = QVBoxLayout(info_holder)
        info_lay.setContentsMargins(0, 0, 0, 0)
        info_lay.setSpacing(6)
        self._circuit_row, self._circuit_val = _info_row('CIRCUIT')
        self._length_row, self._length_val = _info_row('LENGTH')
        self._corners_row, self._corners_val = _info_row('CORNERS')
        self._straight_row, self._straight_val = _info_row('LONGEST STRAIGHT')
        for row in (self._circuit_row, self._length_row, self._corners_row, self._straight_row):
            info_lay.addWidget(row)
        lay.addWidget(info_holder)
        lay.addItem(_soft_gap(10))

        records_holder = QWidget()
        records_holder.setStyleSheet('background: transparent;')
        records_lay = QVBoxLayout(records_holder)
        records_lay.setContentsMargins(0, 0, 0, 0)
        records_lay.setSpacing(8)
        self._brlc_row, self._brlc_val = _record_row('BEST RACE LAP')
        self._blc_row, self._blc_val = _record_row('ALL TIME LAP RECORD')
        records_lay.addWidget(self._brlc_row)
        records_lay.addWidget(self._blc_row)
        lay.addWidget(records_holder)
        lay.addStretch(1)

    def load(self, circuit_row, brlc: tuple | None = None, blc: tuple | None = None):
        while self._title_lay.count():
            item = self._title_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

        country = str(circuit_row['country']) if circuit_row is not None else ''
        title = f'GRAND PRIX OF {country.upper()}' if country else 'OFF-SEASON'
        self._title_lay.addWidget(_panel_title(title))

        pix = _flag_pixmap(country, height=_GP_FLAG_H, width=_GP_FLAG_W) if country else None
        self._flag_lbl.setPixmap(pix if pix is not None else QPixmap())

        if circuit_row is not None:
            self._circuit_val.setFullText(str(circuit_row['circuit_name']).upper())
            self._length_val.setFullText(f"{float(circuit_row['lap_length_km']):.2f} KM")
            self._corners_val.setFullText(str(int(circuit_row['corners'])))
            self._straight_val.setFullText(f"{int(circuit_row['straight_length_m'])} M")
        else:
            for val in (self._circuit_val, self._length_val, self._corners_val, self._straight_val):
                val.setFullText('—')

        self._brlc_val.setFullText(_fmt_record(brlc))
        self._blc_val.setFullText(_fmt_record(blc))


class _TrackHistoryPanel(QWidget):
    """Bottom-left card: mirrors _StandingsPanel's structure and animation
    exactly (static panel title, a header row whose label swaps in place,
    animated rows below) — cycling every 5s between this circuit's last 5
    winners and its last 5 polesitters. Both lists are already capped to 5
    entries by _track_history, so unlike Standings there's never a second
    page to scroll through; every cycle is a category fade, never a scroll."""

    _MODES = ['LAST 5 WINNERS', 'LAST 5 POLESITTERS']
    _SLOTS = 5
    _CYCLE_MS = 5000
    # A notch shorter than _MINI_ROW_H: five rows in the shorter (2-card) left
    # column leave almost no room under the last one, so shaving 2px/row buys
    # back enough height for a comfortable gap above the card's bottom edge
    # without risking the clip that a taller row / bigger bottom margin caused.
    _ROW_H = 24

    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        lay = QVBoxLayout(self)
        # Slimmer rigid spacing than the other panels: this is the last card in
        # the shorter (2-card) left column, set Expanding to pin its bottom to
        # Recent Form's — so on a short window (e.g. 150%-scaled 1080p) the
        # column can't fit Next Race + five fixed-height rows and the trailing
        # rigid space would push the last row's bottom past the card, clipping
        # it. Shorter rows (_ROW_H) + tighter row spacing keep the five rows
        # compact enough that the bottom margin below stays a comfortable gap
        # rather than either clipping or hugging the last row.
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(0)

        # The mode names are self-describing, so with the column-header row
        # gone they become the panel title outright (no separate "TRACK
        # HISTORY" line) — it swaps between the two as the panel cycles.
        title_w, self._title_lbl = _panel_title_parts(self._MODES[0])
        lay.addWidget(title_w)
        lay.addItem(_soft_gap(10))

        self._rows_holder = QWidget()
        self._rows_holder.setStyleSheet('background: transparent;')
        self._rows_lay = QVBoxLayout(self._rows_holder)
        self._rows_lay.setContentsMargins(0, 0, 0, 0)
        self._rows_lay.setSpacing(6)
        lay.addWidget(self._rows_holder)
        lay.addStretch(1)

        self._by_mode = {}
        self._names_map = {}
        self._mode_index = 0
        self._timer = QTimer(self)
        self._timer.setInterval(self._CYCLE_MS)
        self._timer.timeout.connect(self._advance)
        self._timer.start()

    def load(self, winners: list, polesitters: list, names_map: dict | None = None):
        self._by_mode = {'LAST 5 WINNERS': winners, 'LAST 5 POLESITTERS': polesitters}
        self._names_map = names_map or {}
        self._mode_index = 0
        self._render()

    def _advance(self):
        if not self._by_mode:
            return
        self._mode_index = (self._mode_index + 1) % len(self._MODES)
        self._render('fade')

    def _render(self, transition: str | None = None):
        mode = self._MODES[self._mode_index]
        self._title_lbl.setText(mode)
        entries = self._by_mode.get(mode, [])
        snapshot = _grab_snapshot(self._rows_holder) if transition else None

        while self._rows_lay.count():
            item = self._rows_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

        for i in range(self._SLOTS):
            row = QFrame()
            # _ROW_H (shorter than _MINI_ROW_H, itself shorter than _DASH_ROW_H):
            # five rows plus the Next Race card above pushed the left column past
            # what a 150%-scaled 1080p screen can show, and the resulting squeeze
            # mashed the cards' text together / clipped the last row.
            row.setFixedHeight(self._ROW_H)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(10, 0, 10, 0)
            rl.setSpacing(8)
            name_lbl = _ElideLabel()
            manu_lbl = _ElideLabel(); manu_lbl.setFixedWidth(100)
            year_lbl = QLabel(); year_lbl.setFixedWidth(44)
            year_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for l in (name_lbl, manu_lbl, year_lbl):
                l.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))

            if i < len(entries):
                year, name = entries[i]
                info = self._names_map.get(name, {})
                color = TEAM_COLOR.get(info.get('team', '')) or MANU_COLOR.get(
                    info.get('manufacturer', ''), _DEFAULT_COLOR)
                row.setStyleSheet(f'background: {row_bg(color).name()}; border-radius: 6px; border: none;')
                text_color = '#ffffff'
                name_lbl.setFullText(str(name).upper())
                manu_lbl.setFullText(str(info.get('manufacturer', '—')).upper())
                year_lbl.setText(str(year))
            else:
                row.setStyleSheet('background: rgba(255,255,255,10); border-radius: 6px; border: none;')
                text_color = '#5a5a72'
                name_lbl.setFullText('—')
                manu_lbl.setFullText('—')

            for l in (name_lbl, manu_lbl, year_lbl):
                l.setStyleSheet(f'color:{text_color}; background:transparent; border:none;')
            rl.addWidget(name_lbl, 1)
            rl.addWidget(manu_lbl)
            rl.addWidget(year_lbl)
            self._rows_lay.addWidget(row)

        if transition:
            _play_transition(self, self._rows_holder, snapshot, transition)


# Per-country climate baseline for the Upcoming Session forecast: (dry_temp_lo,
# dry_temp_hi, dry_humidity_lo, dry_humidity_hi) in °C / %. Rough real-world
# flavour for each circuit's country (desert Qatar hot & dry, UK cool & damp,
# tropical Thailand/Brazil hot & humid, ...) — provisional, like the winner-
# favourites model, and only ever cosmetic (see _roll_session_weather).
_CLIMATE: dict[str, tuple[int, int, int, int]] = {
    'Qatar':          (26, 36, 15, 35),
    'Thailand':       (28, 36, 55, 80),
    'Australia':      (18, 30, 30, 55),
    'Japan':          (18, 28, 50, 75),
    'Italy':          (20, 32, 30, 55),
    'Spain':          (20, 34, 20, 45),
    'Germany':        (14, 24, 40, 60),
    'United Kingdom': (12, 20, 55, 75),
    'Brazil':         (22, 32, 55, 80),
    'Argentina':      (14, 26, 30, 55),
    'Netherlands':    (13, 21, 55, 75),
    'France':         (16, 26, 35, 60),
    'Portugal':       (17, 27, 40, 65),
}
_CLIMATE_DEFAULT = (16, 28, 35, 60)   # fallback for a country not in the table


def _weather_label(is_wet: bool, temp: float, humidity: float) -> str:
    """Plain-language forecast bucketed from the already-rolled is_wet/temp/
    humidity, so the label can never contradict them (no "Sunny" at 95%
    humidity) — see _roll_session_weather. is_wet gates the two families
    (rain vs no rain), then humidity sets the cloud cover and temperature
    the warmth flavour, so both readings shape the wording."""
    if is_wet:
        # Rain family — heavier with humidity, a storm only when it's both
        # saturated and warm enough for one.
        if humidity > 95 and temp >= 20:
            return 'Thunderstorm ⛈'
        if humidity > 88:
            return 'Rain 🌧'
        return 'Light Rain 🌦'
    # Dry family — cloud cover from humidity, then temperature colours it.
    if humidity >= 55:
        return 'Overcast ☁' if temp < 16 else 'Cloudy ☁'
    if humidity >= 40:
        return 'Partly Sunny 🌤'
    # Clear skies — temperature sets the flavour of a low-humidity day.
    if temp >= 30:
        return 'Hot & Sunny ☀'
    if temp < 14:
        return 'Cool & Clear 🌤'
    return 'Sunny ☀'


def _roll_session_weather(country: str | None) -> dict:
    """Forecast for the Upcoming Session card — one roll per weekend DAY
    (Friday practice / Saturday Q1+Q2+Race 1 / Sunday Race 2, see
    wizard.SESSION_DAY), cached on wiz.weekend_weather and reused across
    sessions sharing a day; see SeasonHubPage._refresh_data's day-keyed cache.

    is_wet (rolled here at WET_RACE_PROB_PCT, same odds run_race() itself
    uses) is the single source of truth for the day — when a Race session for
    that day actually runs, RacePage._run passes this same is_wet through as
    forced_weather instead of rolling its own, so what the hub forecasts is
    exactly what happens (see p3_race.py). temp/humidity/label stay purely
    cosmetic on top of it: temp/humidity are sampled from the circuit's
    country baseline (_CLIMATE), pulled cooler and wetter for a "wet" roll,
    and the label is bucketed from the result."""
    is_wet = np.random.uniform(0, 100) <= WET_RACE_PROB_PCT
    lo, hi, hlo, hhi = _CLIMATE.get(country, _CLIMATE_DEFAULT)
    if is_wet:
        # Rain cools things down and pushes humidity to the top of the scale
        # regardless of country — the wet temp band is still derived from the
        # country's own dry range, so a Qatar shower reads warmer than a UK one.
        mid = (lo + hi) / 2
        temp = np.random.uniform(mid - 10, mid - 2)
        humidity = np.random.uniform(78, 100)
    else:
        temp = np.random.uniform(lo, hi)
        humidity = np.random.uniform(hlo, hhi)
    temp, humidity = round(temp), round(humidity)
    return {'is_wet': is_wet, 'temp': temp, 'humidity': humidity,
            'label': _weather_label(is_wet, temp, humidity)}


class _UpcomingSessionPanel(QWidget):
    """Middle-column card with two looks that share one heading + divider:

      • Normal — names the weekend session up next (Practice, Qualifying 1/2,
        Race 1/2 — see wizard.SESSION_NAMES) over a second divider and a
        conditions block (current weather / temperature / humidity).
      • Between grand prix (the post-Finish "TO NEXT GRAND PRIX" hub landing)
        — the NEXT round's flag and "GRAND PRIX OF <country>" instead, with no
        second divider and no weather. Toggled by load()'s next_gp_country."""

    _FLAG_H = _GP_FLAG_H

    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(0)

        title_w, self._card_title = _panel_title_parts('UPCOMING SESSION')
        lay.addWidget(title_w)
        lay.addItem(_soft_gap(18))

        # ── Normal: session name + second divider + weather block ──────────
        self._session_box = QWidget()
        self._session_box.setStyleSheet('background: transparent;')
        sb = QVBoxLayout(self._session_box)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(0)
        self._name_lbl = QLabel('—')
        self._name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name_lbl.setWordWrap(True)
        self._name_lbl.setFont(QFont('Segoe UI', 17, QFont.Weight.Bold))
        self._name_lbl.setStyleSheet('color:#ffffff; letter-spacing:1px; background:transparent; border:none;')
        sb.addWidget(self._name_lbl)
        sb.addItem(_soft_gap(16))
        border2 = QFrame()
        border2.setFixedHeight(1)
        border2.setStyleSheet('background: rgba(255,255,255,60); border:none;')
        sb.addWidget(border2)
        sb.addItem(_soft_gap(14))
        # White captions (not GP Info's dim grey), and the three rows are
        # spread with stretches between them so they fill down to near the
        # card's bottom rather than huddling under the divider.
        self._weather_row, self._weather_val = _info_row('CURRENT WEATHER', label_color='#ffffff')
        self._temp_row,    self._temp_val    = _info_row('TEMPERATURE',     label_color='#ffffff')
        self._humid_row,   self._humid_val   = _info_row('HUMIDITY',        label_color='#ffffff')
        sb.addWidget(self._weather_row)
        sb.addStretch(1)
        sb.addWidget(self._temp_row)
        sb.addStretch(1)
        sb.addWidget(self._humid_row)
        lay.addWidget(self._session_box, 1)

        # ── Between grand prix: next round's flag + "GRAND PRIX OF X" ───────
        self._nextgp_box = QWidget()
        self._nextgp_box.setStyleSheet('background: transparent;')
        nb = QVBoxLayout(self._nextgp_box)
        nb.setContentsMargins(0, 0, 0, 0)
        nb.setSpacing(0)
        nb.addStretch(1)
        self._flag_lbl = QLabel()
        self._flag_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._flag_lbl.setFixedHeight(self._FLAG_H)
        nb.addWidget(self._flag_lbl)
        nb.addItem(_soft_gap(18))
        self._gp_name_lbl = QLabel()
        self._gp_name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._gp_name_lbl.setWordWrap(True)
        self._gp_name_lbl.setFont(QFont('Segoe UI', 16, QFont.Weight.Bold))
        self._gp_name_lbl.setStyleSheet('color:#ffffff; letter-spacing:1px; background:transparent; border:none;')
        nb.addWidget(self._gp_name_lbl)
        nb.addStretch(1)
        lay.addWidget(self._nextgp_box, 1)
        self._nextgp_box.setVisible(False)

    def load(self, session_name: str, weather: str = '—',
             temperature: str = '—', humidity: str = '—',
             next_gp_country: str | None = None, champion: str | None = None,
             champion_year: int | str | None = None):
        if champion:
            # Season finale: crown the champion in place of the flag/GP-name
            # (reuse the centred nextgp box, flag hidden — the off-season has no
            # country to show). Rich text so the "World Champion" line can run
            # smaller than the champion's name.
            self._card_title.setText('SEASON COMPLETE')
            self._flag_lbl.setVisible(False)
            year_txt = str(champion_year) if champion_year else ''
            self._gp_name_lbl.setText(
                f'<div style="font-size:16pt; font-weight:600;">{str(champion).upper()}</div>'
                f'<div style="font-size:11pt; font-weight:400;">{year_txt} WORLD CHAMPION</div>'
            )
            self._session_box.setVisible(False)
            self._nextgp_box.setVisible(True)
        elif next_gp_country:
            self._card_title.setText('UPCOMING SESSION')
            country = str(next_gp_country)
            pix = _flag_pixmap(country, height=_GP_FLAG_H, width=_GP_FLAG_W) if country else None
            self._flag_lbl.setVisible(True)
            self._flag_lbl.setPixmap(pix if pix is not None else QPixmap())
            self._gp_name_lbl.setText(f'GRAND PRIX OF {country.upper()}')
            self._session_box.setVisible(False)
            self._nextgp_box.setVisible(True)
        else:
            self._card_title.setText('UPCOMING SESSION')
            self._name_lbl.setText(str(session_name).upper())
            self._weather_val.setFullText(str(weather))
            self._temp_val.setFullText(str(temperature))
            self._humid_val.setFullText(str(humidity))
            self._nextgp_box.setVisible(False)
            self._session_box.setVisible(True)


class _MarqueeLabel(QWidget):
    """A name label that scrolls its text sideways, LED-sign style, instead of
    cutting it off with an ellipsis — used for the GP Winner Favourites
    bar-chart names, which sit in a column too narrow for names like "MATTEO
    ESPOSITO". Text that already fits the widget is just centered and stays
    still; only overflowing text scrolls, continuously and on a loop."""

    _SPEED_PX = 1     # pixels advanced per tick
    _TICK_MS  = 40     # ~25fps
    _GAP      = 24     # blank gap between the text's end and its looped repeat

    def __init__(self, font: QFont, color: str = '#ffffff'):
        super().__init__()
        self._text   = ''
        self._font   = font
        self._color  = QColor(color)
        self._offset = 0
        self.setFixedHeight(QFontMetrics(font).height())
        self._timer = QTimer(self)
        self._timer.setInterval(self._TICK_MS)
        self._timer.timeout.connect(self._advance)

    def setFullText(self, text: str):
        self._text = text
        self._offset = 0
        self._sync_timer()
        self.update()

    def _text_width(self) -> int:
        return QFontMetrics(self._font).horizontalAdvance(self._text)

    def _sync_timer(self):
        overflow = self.width() > 0 and self._text_width() > self.width()
        if overflow and not self._timer.isActive():
            self._timer.start()
        elif not overflow and self._timer.isActive():
            self._timer.stop()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_timer()

    def _advance(self):
        cycle = self._text_width() + self._GAP
        self._offset = (self._offset + self._SPEED_PX) % max(cycle, 1)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(self._font)
        p.setPen(self._color)
        fm = QFontMetrics(self._font)
        tw = fm.horizontalAdvance(self._text)
        y = (self.height() + fm.ascent() - fm.descent()) // 2
        if tw <= self.width():
            p.drawText((self.width() - tw) // 2, y, self._text)
        else:
            cycle = tw + self._GAP
            x = -self._offset
            while x < self.width():
                p.drawText(x, y, self._text)
                x += cycle
        p.end()


# Winner-favourites model — relative weights of each active factor (they're
# renormalised over whichever ones apply at the current weekend stage, so they
# needn't sum to 1). Rating already folds in circuit fit and, in the wet, wet
# skill; the Race-1 podium momentum rides inside the rating via an aggression
# bump, so neither needs its own weight here.
_FAV_W_RATING = 0.50   # rider+bike pace, weighted to the circuit (perf_score_race)
_FAV_W_FORM   = 0.22   # last-5-rounds finishing form
_FAV_W_GRID   = 0.28   # qualifying grid position (Race sessions only)
_FAV_SOFTMAX_T = 0.12   # softmax spread over the [0,1] blended power; lower = top-heavier
_FAV_PODIUM_AGGRO = {1: 3, 2: 2, 3: 1}   # Race-1 podium -> Race-2 aggression boost


def _form_scores(rounds_detail_list: list, limit: int = 5) -> dict:
    """Per-rider recent-form score in [0, 1] from the last `limit` ROUNDS
    (fewer if the career is younger — "5 chặng gần đây, chưa đủ thì 4, 3…").
    Each race a rider finished scores (field - pos)/(field - 1) — win = 1,
    last = 0 — a DNF scores 0; the rider's score is the mean across those
    races. Riders with no recent races get a neutral 0.5 so a newcomer isn't
    punished as if they'd finished dead last."""
    flat = _flatten_rounds((rounds_detail_list or [])[-limit:])
    totals: dict[str, list] = {}
    for _country, race in flat:
        field = len(race)
        if field < 2:
            continue
        for r in race:
            pos = int(r.get('pos', 0))
            val = 0.0 if r.get('dnf') or pos < 1 else (field - pos) / (field - 1)
            totals.setdefault(str(r['name']), []).append(val)
    return {n: (sum(v) / len(v)) for n, v in totals.items() if v}


def _gp_point_scorers(round_detail: dict, limit: int = 5) -> list:
    """Top `limit` point scorers of a single round — each rider's points summed
    across the round's two races, highest first. Rows carry name/team/
    manufacturer/points so the between-GP result panel can colour them exactly
    like the standings (see _WinnerFavouritesPanel._render_result)."""
    tally: dict[str, dict] = {}
    for race in (round_detail or {}).get('races', []):
        for r in race:
            e = tally.setdefault(str(r['name']), {
                'name': str(r['name']), 'team': str(r.get('team', '')),
                'manufacturer': str(r.get('manufacturer', '')), 'points': 0})
            e['points'] += int(r.get('points', 0))
    return sorted(tally.values(), key=lambda x: -x['points'])[:limit]


def _winner_favourites(df, *, circuit=None, session_index: int = 0,
                       form_scores: dict | None = None, grid_df=None,
                       is_wet: bool = False, race1_podium: dict | None = None,
                       limit: int = 3) -> list:
    """Top `limit` riders by an estimated win chance for the upcoming Grand
    Prix, rebuilt at every hub visit so it grows sharper as the weekend
    unfolds (see wizard.SESSION_DAY / session_index):

      • Before Practice (session 0-2): recent form + circuit-weighted rider+
        bike rating.
      • Before Race 1 (session 3, after qualifying): adds grid position and
        the day's weather — a wet forecast tilts the rating toward each
        rider's wet_performance.
      • Before Race 2 (session 4): adds "instant form" — the Race-1 podium
        gets a temporary aggression bump (+3/+2/+1, _FAV_PODIUM_AGGRO) that
        feeds back through the rating. It's applied to a throwaway copy of the
        roster, so it only colours this circuit's Race 2 and never persists
        into the next round.

    Each factor is a [0,1] score; the active ones are blended by their
    _FAV_W_* weights (renormalised) into one power, then a softmax turns the
    field into probabilities. Returns dicts name/team/manufacturer/pct,
    highest first."""
    if df is None or len(df) == 0:
        return []
    work = df.reset_index(drop=True).copy()
    names = work['name'].astype(str).to_numpy()
    n = len(work)

    # Factor 6 (Race 2 only): instant-form aggression boost for the Race-1
    # podium, on this throwaway copy so it never leaks past this circuit. Not
    # clipped at the 99 rating ceiling — this is a momentum bonus for the
    # estimate only (never the race sim), so a winner already at 99 still gets
    # the full +3 edge rather than being silently capped out.
    if session_index >= 4 and race1_podium:
        for nm, boost in race1_podium.items():
            work.loc[work['name'] == nm, 'aggression'] += boost

    # Factors 2+3: circuit-weighted rider+bike rating — perf_score_race already
    # blends the two, so a power track and a corner track reward different
    # archetypes. Falls back to a flat stat mean if the circuit is unknown.
    if circuit is not None:
        w = circuit_weights(circuit)
        rating = work.apply(lambda r: perf_score_race(r, *w), axis=1).to_numpy(float)
    else:
        stat_cols = [c for c, _, _ in STATS]
        rating = norm(work[stat_cols].mean(axis=1).to_numpy(float))

    # Factor 5 (weather, Race sessions): a wet track leans on wet skill.
    if session_index >= 3 and is_wet:
        rating = 0.6 * rating + 0.4 * norm(work['wet_performance'].to_numpy(float))

    comps = [(_FAV_W_RATING, _minmax(rating))]

    # Factor 1: recent form (every stage).
    if form_scores:
        form = np.array([form_scores.get(nm, 0.5) for nm in names], dtype=float)
        comps.append((_FAV_W_FORM, form))

    # Factor 4: grid position (Race sessions, once qualifying has set the grid).
    if session_index >= 3 and grid_df is not None and len(grid_df) > 1:
        gmap = {str(r['name']): int(r['grid_pos']) for _, r in grid_df.iterrows()}
        field = len(grid_df)
        grid = np.array([(field - gmap.get(nm, field)) / (field - 1) for nm in names], dtype=float)
        comps.append((_FAV_W_GRID, grid))

    total_w = sum(wt for wt, _ in comps) or 1.0
    power = sum(wt * vals for wt, vals in comps) / total_w

    e = np.exp((power - power.max()) / _FAV_SOFTMAX_T)
    prob = e / e.sum()
    order = list(np.argsort(-prob))[:limit]
    out = []
    for i in order:
        row = work.iloc[int(i)]
        out.append({'name': str(row['name']), 'team': str(row['team']),
                    'manufacturer': str(row['manufacturer']), 'pct': float(prob[i] * 100)})
    return out


def _minmax(a):
    """Scale an array to [0, 1]; a flat array maps to all-0.5 (no signal)."""
    a = np.asarray(a, dtype=float)
    lo, hi = a.min(), a.max()
    if hi - lo < 1e-9:
        return np.full_like(a, 0.5)
    return (a - lo) / (hi - lo)


_FAV_CHART_H = 110   # fixed height of the bar area; bar heights scale within it
_FAV_BAR_W   = 34
_FAV_COL_GAP = 30     # fixed breathing room between columns — a flexible
                      # stretch alone can collapse to ~0 on a narrow window,
                      # which read as a scrolling name running into its neighbour


class _WinnerFavouritesPanel(QWidget):
    """Bottom card of the middle column, with two looks:

      • Normal — "GRAND PRIX WINNER FAVOURITES": a vertical bar chart of the
        riders most likely (in theory) to win the upcoming GP; taller bar =
        higher win chance, coloured by team/manufacturer.
      • Between grand prix (post-Finish) — "GRAND PRIX RESULT": the top 5
        point scorers across the two races of the GP just finished, as a
        standings-style row list. Toggled by load()'s gp_result."""

    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(0)

        # Same 9pt/letter-spacing as every other panel's _panel_title header;
        # the title is long, so it still wraps to two lines on a narrow window.
        self._title_lbl = QLabel('GRAND PRIX WINNER FAVOURITES')
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_lbl.setWordWrap(True)
        # Let it wrap rather than dictate the card's minimum width — otherwise
        # the long title would keep the whole middle column ~354px wide and stop
        # the side columns from ever reclaiming that space on a narrow window.
        self._title_lbl.setMinimumWidth(1)
        self._title_lbl.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
        self._title_lbl.setStyleSheet('color:#ffffff; letter-spacing:2px; background:transparent; border:none;')
        lay.addWidget(self._title_lbl)
        lay.addItem(_soft_gap(8))
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet('background: rgba(255,255,255,60); border:none;')
        lay.addWidget(line)
        lay.addItem(_soft_gap(22))

        # One body area rebuilt per mode (bar chart vs standings rows).
        self._body = QWidget()
        self._body.setStyleSheet('background: transparent;')
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(0, 0, 0, 0)
        self._body_lay.setSpacing(0)
        lay.addWidget(self._body, 1)

    def _clear_body(self):
        while self._body_lay.count():
            item = self._body_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

    def load(self, favourites: list | None = None, gp_result: list | None = None,
             result_title: str | None = None):
        self._clear_body()
        if gp_result is not None:
            self._title_lbl.setText(result_title or 'GRAND PRIX RESULT')
            self._render_result(gp_result)
        else:
            self._title_lbl.setText('GRAND PRIX WINNER FAVOURITES')
            self._render_bars(favourites or [])

    def _render_result(self, result: list):
        """Standings-style top-5 rows (pos / name / points), team-coloured like
        _StandingsPanel, spread down the card. No manufacturer column — the
        name column takes that width so full rider names fit."""
        self._body_lay.addStretch(1)
        for i in range(5):
            filled = i < len(result)
            row = QFrame()
            row.setFixedHeight(_DASH_ROW_H)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(10, 0, 10, 0)
            rl.setSpacing(8)
            pos_lbl = QLabel(str(i + 1) if filled else ''); pos_lbl.setFixedWidth(24)
            name_lbl = _ElideLabel()
            pts_lbl = QLabel(); pts_lbl.setFixedWidth(44)
            pts_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            labels = [pos_lbl, name_lbl, pts_lbl]
            for l in labels:
                l.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
            if filled:
                s = result[i]
                color = TEAM_COLOR.get(s.get('team', '')) or MANU_COLOR.get(
                    s.get('manufacturer', ''), _DEFAULT_COLOR)
                row.setStyleSheet(f'background: {row_bg(color).name()}; border-radius: 6px; border: none;')
                name_lbl.setFullText(str(s.get('name', '')).upper())
                pts_lbl.setText(str(int(s.get('points', 0))))
            else:
                row.setStyleSheet('background: transparent; border: none;')
            for l in labels:
                l.setStyleSheet('color:#ffffff; background:transparent; border:none;')
            rl.addWidget(pos_lbl)
            rl.addWidget(name_lbl, 1)
            rl.addWidget(pts_lbl)
            self._body_lay.addWidget(row)
            self._body_lay.addStretch(1)

    def _render_bars(self, favourites: list):
        if not favourites:
            ph = QLabel('Not enough data yet.')
            ph.setWordWrap(True)
            ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ph.setFont(QFont('Segoe UI', 10))
            ph.setStyleSheet('color:#8a8aa2; background:transparent; border:none;')
            self._body_lay.addStretch(1)
            self._body_lay.addWidget(ph)
            self._body_lay.addStretch(1)
            return
        chart = QWidget()
        chart.setStyleSheet('background: transparent;')
        chart_lay = QHBoxLayout(chart)
        chart_lay.setContentsMargins(0, 0, 0, 0)
        chart_lay.setSpacing(4)
        max_pct = max(f.get('pct', 0) for f in favourites) or 1.0
        chart_lay.addStretch(1)
        for i, f in enumerate(favourites):
            if i > 0:
                chart_lay.addSpacing(_FAV_COL_GAP)
            pct = f.get('pct', 0)
            color = TEAM_COLOR.get(f.get('team', '')) or MANU_COLOR.get(
                f.get('manufacturer', ''), _DEFAULT_COLOR)

            col = QWidget()
            col.setStyleSheet('background: transparent;')
            cl = QVBoxLayout(col)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(6)

            # The empty space goes ABOVE both the % label and the bar (not
            # between them), so the two move down together — the percentage
            # always sits right on top of its own bar instead of staying
            # pinned to the column's top with a big gap under it for a short
            # (low-%) bar.
            bar_h = max(6, round(pct / max_pct * _FAV_CHART_H))
            cl.addSpacing(_FAV_CHART_H - bar_h)

            pct_lbl = QLabel(f'{pct:.0f}%')
            pct_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pct_lbl.setFont(QFont('Segoe UI', 10, QFont.Weight.Bold))
            pct_lbl.setStyleSheet('color:#ffffff; background:transparent; border:none;')
            cl.addWidget(pct_lbl)

            bar = QFrame()
            bar.setFixedSize(_FAV_BAR_W, bar_h)
            bar.setStyleSheet(f'background: {color.name()}; border-radius: 4px; border: none;')
            bar_row = QHBoxLayout()
            bar_row.setContentsMargins(0, 0, 0, 0)
            bar_row.addStretch(1)
            bar_row.addWidget(bar)
            bar_row.addStretch(1)
            cl.addLayout(bar_row)

            # Scrolls sideways instead of eliding — some rider names run
            # longer than this narrow bar column can show at once.
            name_lbl = _MarqueeLabel(QFont('Segoe UI', 8, QFont.Weight.Bold))
            name_lbl.setFullText(str(f.get('name', '')).upper())
            name_lbl.setFixedWidth(94)
            cl.addWidget(name_lbl)

            chart_lay.addWidget(col)
        chart_lay.addStretch(1)
        self._body_lay.addStretch(1)
        self._body_lay.addWidget(chart)
        self._body_lay.addStretch(1)


_HUB_SIDEBAR_W = 380   # compact right-hand column (preferred width)
_HUB_LEFT_W = 460      # left column runs a bit wider — room for the circuit-info lines
_HUB_MID_GAP = 26      # fixed breathing space between the middle card and each side column
_HUB_MID_H   = 244     # fixed height so its bottom lines up with GP Info's LONGEST STRAIGHT row
_HUB_SIDE_MARGIN = 56  # dashboard's outer left/right margin
# On a window too narrow to hold the preferred widths, the two side columns
# shrink (never below these floors, where their inner rows still fit) so the
# board always fits without a scrollbar — see _relayout_columns. The right
# floor is high because Recent Form's five fixed 60px flag boxes can't shrink.
_HUB_LEFT_MIN  = 268
_HUB_RIGHT_MIN = 360
# Sized to hold the Winner-Favourites bar chart (3 fixed 94px name columns +
# their 30px gaps + card padding ≈ 394px). Keeping this at/above the middle
# card's real content minimum makes _relayout_columns' max(_HUB_MID_MIN,
# middle.minimumSizeHint()) resolve to this CONSTANT in every state — so the
# middle column no longer widens for the bar chart and narrows for the
# between-GP "Grand Prix Result" rows, which was jittering the side columns
# (and clipping the left card's long lap-record lines) as the hub cycled.
_HUB_MID_MIN   = 400   # the middle column never gets squeezed below this


class _HubDashboard(QWidget):
    """Sits below the main hub's tab bar as two compact columns: the next
    round's title/flag and this circuit's track history pinned to the
    left, standings/overall-stats/recent-form pinned to the right — with
    the wide gap between them left open to show the background art."""

    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        outer = QHBoxLayout(self)
        outer.setContentsMargins(_HUB_SIDE_MARGIN, 0, _HUB_SIDE_MARGIN, 40)
        outer.setSpacing(0)

        left = QWidget()
        self._left = left
        left.setFixedWidth(_HUB_LEFT_W)
        left.setStyleSheet('background: transparent;')
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(12)

        self._next_race = _NextRacePanel()
        self._track_history = _TrackHistoryPanel()
        left_panels = (self._next_race, self._track_history)
        for i, panel in enumerate(left_panels):
            wrap = _TintWrap(panel, margin=0)
            # The last card (Track History) expands to soak up whatever
            # height its column has to spare, instead of a trailing stretch
            # leaving a gap below it — that's what pins its bottom edge
            # level with Recent Form's, the last card on the right.
            v_policy = (QSizePolicy.Policy.Expanding if i == len(left_panels) - 1
                       else QSizePolicy.Policy.Maximum)
            wrap.setSizePolicy(QSizePolicy.Policy.Preferred, v_policy)
            left_lay.addWidget(wrap)
        outer.addWidget(left)

        # Middle column: the "Upcoming session" card fills the whole gap between
        # the two fixed side columns, leaving only a small fixed _HUB_MID_GAP on
        # each side. Giving it the layout's stretch (addWidget(..., 1)) rather
        # than flanking it with expanding spacers keeps that gap constant and
        # tight at every window width — it grows/shrinks with the window instead
        # of leaving a big empty margin on a wide screen or overflowing the
        # columns off-screen on a narrow one. Top-aligned (fixed-height card,
        # then a trailing stretch) so its bottom lands level with GP Info's
        # CORNERS row.
        outer.addSpacing(_HUB_MID_GAP)

        middle = QWidget()
        self._middle = middle
        middle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        middle.setStyleSheet('background: transparent;')
        mid_lay = QVBoxLayout(middle)
        mid_lay.setContentsMargins(0, 0, 0, 0)
        mid_lay.setSpacing(12)
        self._upcoming = _UpcomingSessionPanel()
        self._upcoming_wrap = _TintWrap(self._upcoming, margin=0)
        # Starting height; _sync_upcoming_height() then pins it to the Standings
        # card's actual height so the two cards' bottoms line up exactly (see
        # resizeEvent / load).
        self._upcoming_wrap.setFixedHeight(_HUB_MID_H)
        mid_lay.addWidget(self._upcoming_wrap)
        # Winner-favourites card fills the rest of the column (Expanding), so
        # its bottom lands level with Recent Form (right) and Last 5 (left),
        # whose last cards expand the same way.
        self._favourites = _WinnerFavouritesPanel()
        fav_wrap = _TintWrap(self._favourites, margin=0)
        fav_wrap.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        mid_lay.addWidget(fav_wrap)
        outer.addWidget(middle, 1)

        outer.addSpacing(_HUB_MID_GAP)

        right = QWidget()
        self._right = right
        right.setFixedWidth(_HUB_SIDEBAR_W)
        right.setStyleSheet('background: transparent;')
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(12)

        self._standings = _StandingsPanel()
        self._overall_stats = _OverallStatsPanel()
        self._form = _FormPanel()
        self._standings_wrap = None
        right_panels = (self._standings, self._overall_stats, self._form)
        for i, panel in enumerate(right_panels):
            wrap = _TintWrap(panel, margin=0)
            if panel is self._standings:
                self._standings_wrap = wrap
            # Maximum: a card may shrink below its natural height — its
            # internal _soft_gap()s collapse first, so rows stay intact —
            # but never grows past it on its own. A hard Fixed policy here
            # forced Qt to clip card bottoms instead, cutting through the
            # last row. The last card (Recent Form) is Expanding instead,
            # so it — not a trailing stretch — absorbs the column's
            # leftover height, putting its bottom edge at the column's
            # bottom rather than short of it.
            v_policy = (QSizePolicy.Policy.Expanding if i == len(right_panels) - 1
                       else QSizePolicy.Policy.Maximum)
            wrap.setSizePolicy(QSizePolicy.Policy.Preferred, v_policy)
            right_lay.addWidget(wrap)

        outer.addWidget(right)

    def minimumSizeHint(self):
        # Report the *floor* width (side columns at their _MIN, middle at
        # _HUB_MID_MIN), not the width the fixed columns currently occupy —
        # otherwise the parent layout would never size the board below the
        # preferred 460/380 and _relayout_columns() could never shrink them to
        # a narrow window. Height is left as Qt computes it, so the board is
        # never squeezed shorter than its content (no vertical overlap).
        s = super().minimumSizeHint()
        mid_min = max(_HUB_MID_MIN, self._middle.minimumSizeHint().width())
        min_w = (_HUB_LEFT_MIN + _HUB_RIGHT_MIN + mid_min
                 + _HUB_SIDE_MARGIN * 2 + _HUB_MID_GAP * 2)
        return QSize(min_w, s.height())

    def _relayout_columns(self):
        """Keep the whole board inside the window width without a scrollbar:
        the side columns sit at their preferred 460 / 380 whenever there's
        room, and shrink proportionally (never past their _MIN floors) on a
        narrower window. The middle column — Expanding between them — always
        fills whatever is left, down to _HUB_MID_MIN. This is what lets the app
        window be resized freely without the columns overlapping."""
        avail = self.width()
        overhead = _HUB_SIDE_MARGIN * 2 + _HUB_MID_GAP * 2
        # The middle column can't be squeezed below the width its own content
        # needs, so reserve its actual minimum first, then hand what's left to
        # the two side columns.
        mid_min = max(_HUB_MID_MIN, self._middle.minimumSizeHint().width())
        room = avail - overhead - mid_min               # width for the two side columns
        # How much must come off the preferred side widths, split in proportion
        # to each column's shrinkable range (the right column barely moves —
        # its flag boxes floor it at _HUB_RIGHT_MIN).
        excess = (_HUB_LEFT_W + _HUB_SIDEBAR_W) - room
        if excess <= 0:
            lw, rw = _HUB_LEFT_W, _HUB_SIDEBAR_W
        else:
            l_range = _HUB_LEFT_W - _HUB_LEFT_MIN
            r_range = _HUB_SIDEBAR_W - _HUB_RIGHT_MIN
            total = l_range + r_range
            if excess >= total or total <= 0:
                lw, rw = _HUB_LEFT_MIN, _HUB_RIGHT_MIN   # fully shrunk (window below the board min)
            else:
                lw = _HUB_LEFT_W    - round(excess * l_range / total)
                rw = _HUB_SIDEBAR_W - round(excess * r_range / total)
        if self._left.width() != lw:
            self._left.setFixedWidth(lw)
        if self._right.width() != rw:
            self._right.setFixedWidth(rw)

    _MIN_SANE_STANDINGS_H = 150   # 5 rows * _DASH_ROW_H(30) alone is already 150

    def _sync_upcoming_height(self, _retry: int = 0):
        """Pin the middle "Upcoming session" card to the same height as the
        Standings card so their bottom edges line up (both start at the top of
        the dashboard row). The Standings height is constant — 5 fixed rows —
        so this only needs to run once the panel has been laid out.

        Skipped while the board is hidden: a hidden (or not-yet-laid-out)
        Standings card reports only its title height (~53px), and pinning to
        that collapsed the Upcoming card's content on top of itself until the
        next resize. `isVisible()` alone isn't a reliable enough guard for
        this — a widget can report visible before the top-level window has
        finished its first real layout pass (e.g. resuming straight onto the
        dashboard on a mid-season CONTINUE, which skips the intro's few
        seconds of breathing room) — so an implausibly small reading here
        retries a few times a beat later instead of trusting it outright.
        showEvent also re-runs this once the page is shown."""
        if self._standings_wrap is None or not self.isVisible():
            return
        h = self._standings_wrap.sizeHint().height()
        if h < self._MIN_SANE_STANDINGS_H:
            if _retry < 15:
                QTimer.singleShot(30, lambda: self._sync_upcoming_height(_retry + 1))
            return
        if self._upcoming_wrap.height() != h:
            self._upcoming_wrap.setFixedHeight(h)

    def showEvent(self, event):
        super().showEvent(event)
        # First real layout: the board may have been load()ed while hidden
        # (during the season intro), so re-run both fits now that sizes are
        # measurable. Deferred a tick so the show-time layout has settled.
        self._relayout_columns()
        QTimer.singleShot(0, self._sync_upcoming_height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_columns()
        self._sync_upcoming_height()

    def load(self, standings: list, races: list, honours: dict | None,
            team_standings: list, manu_standings: list,
            names_map: dict | None = None, next_circuit=None,
            track_winners: list | None = None, track_polesitters: list | None = None,
            brlc: tuple | None = None, blc: tuple | None = None,
            upcoming_session: str = '', favourites: list | None = None,
            weather: dict | None = None, next_gp_country: str | None = None,
            gp_result: list | None = None, result_title: str | None = None,
            champion: str | None = None, champion_year: int | str | None = None):
        self._standings.load(standings, team_standings, manu_standings)
        self._form.load(races)
        self._overall_stats.load(honours, names_map)
        self._next_race.load(next_circuit, brlc, blc)
        self._track_history.load(track_winners or [], track_polesitters or [], names_map)
        weather = weather or {}
        # champion set -> season-finale look (trophy + champion name, no session
        # or weather); next_gp_country set -> "between grand prix" look (flag +
        # GP name, no weather); gp_result set -> a top-5 result list (finished
        # GP's point scorers, or the final standings on the finale) in place of
        # the winner-favourites bar chart.
        self._upcoming.load(upcoming_session, weather=weather.get('label', '—'),
                            temperature=f"{weather['temp']}°C" if 'temp' in weather else '—',
                            humidity=f"{weather['humidity']}%" if 'humidity' in weather else '—',
                            next_gp_country=next_gp_country, champion=champion,
                            champion_year=champion_year)
        self._favourites.load(favourites=favourites, gp_result=gp_result,
                              result_title=result_title)
        # Rows are in place now — match the Standings card's height on the next
        # tick (after the layout settles).
        QTimer.singleShot(0, self._sync_upcoming_height)


# ── Season Info tab: STANDINGS (Riders/Teams/Manufacturers) / CALENDAR ────────
# (same sub-hub pattern as Your Profile) — unlike the dashboard's condensed
# Standings panel (5 rows around the player), the full-page views here list
# every rider/team/manufacturer.

class _StandingsListView(QWidget):
    """Pos / Name / Points list — shared by Riders (BASIC), Teams, and
    Manufacturers, each supplying its own per-row colour lookup.

    The title lives outside its own internal QScrollArea (only the rows sit
    inside it) so a long list scrolls in place under a pinned title, instead
    of the whole view — title included — panning as one block. Same pattern
    as _CalendarView; see _SideSubHub's needs_scroll=False branch, which is
    why this view supplies its own scrollbar() instead of being wrapped in
    another QScrollArea from outside."""

    def __init__(self, title: str):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(56, 52, 56, 48)
        outer.setSpacing(0)

        title_lbl = QLabel(title)
        title_lbl.setFont(QFont('Segoe UI', 26, QFont.Weight.Bold))
        title_lbl.setStyleSheet('color:#ffffff; letter-spacing:2px; background:transparent; border:none;')
        outer.addWidget(title_lbl)
        outer.addSpacing(20)

        self._scroll = _make_scroll_area()
        self._rows_holder = QWidget()
        self._rows_holder.setStyleSheet('background: transparent;')
        self._rows_lay = QVBoxLayout(self._rows_holder)
        self._rows_lay.setContentsMargins(0, 0, 12, 0)
        self._rows_lay.setSpacing(10)
        self._rows_lay.addStretch(1)
        self._scroll.setWidget(self._rows_holder)
        outer.addWidget(self._scroll, 1)

    def scrollbar(self):
        return self._scroll.verticalScrollBar()

    def reset(self):
        """Scroll back to top when this view is closed/reopened — mirrors
        what the (now-removed) outer wrapping QScrollArea used to do via
        _SideSubHub.reset()'s own sc.verticalScrollBar() reset."""
        bar = self._scroll.verticalScrollBar()
        if bar is not None:
            bar.setValue(0)

    def load(self, rows: list, color_fn):
        while self._rows_lay.count() > 1:
            item = self._rows_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        for i, s in enumerate(rows, start=1):
            bg = row_bg(color_fn(s))
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
        if not rows:
            ph = QLabel('No standings yet — check back after your first season.')
            ph.setFont(QFont('Segoe UI', 11))
            ph.setStyleSheet('color:#8a8aa2; background:transparent; border:none;')
            self._rows_lay.insertWidget(self._rows_lay.count() - 1, ph)


def _build_riders_detail_table(standings: list, rounds_detail: list):
    """Wiki-style race-by-race grid for the CURRENT season's riders, ordered
    by the standings passed in — POS / RIDER / R1…Rn (coloured by finishing
    position, 'Ret' for DNF) / PTS. Mirrors career's cross-season race matrix
    (_build_rider_race_matrix), but scoped to just this season. (The Standings
    page used to carry an equivalent grid of its own; this is now the only one
    for the running season.)

    Only the R1…Rn cells carry the per-position colour coding — POS/RIDER/PTS
    stay on the plain neutral background (no team/manufacturer tint), same
    as YEAR/BIKE in _build_rider_race_matrix."""
    per_rider = [(s, _rider_race_results(str(s.get('name', '')), rounds_detail))
                for s in standings]
    max_races = max((len(r) for _, r in per_rider if r is not None), default=0)
    race0 = 2                              # POS, RIDER, then R1…Rn
    pts_col = race0 + max_races
    headers = ['POS', 'RIDER'] + [f'R{i + 1}' for i in range(max_races)] + ['PTS']
    t = make_table(headers)
    t.setRowCount(len(per_rider))
    neutral = row_bg(_DEFAULT_COLOR)

    for i, (s, results) in enumerate(per_rider):
        t.setItem(i, 0, _cell(i + 1, neutral, bold=True, center=True, size=11))
        t.setItem(i, 1, _cell(str(s.get('name', '')).upper(), neutral, bold=True, size=11))
        for c in range(max_races):
            r = results[c] if (results is not None and c < len(results)) else None
            if r is None:
                t.setItem(i, race0 + c, _grid_cell('', neutral))
            else:
                txt = 'Ret' if r['dnf'] else str(r['pos'])
                t.setItem(i, race0 + c, _grid_cell(txt, _pos_bg(r['pos'], r['dnf'])))
        t.setItem(i, pts_col, _cell(int(s.get('points', 0)), neutral, bold=True, center=True, size=11))

    t.setColumnWidth(0, 56)
    t.setColumnWidth(1, 240)   # RIDER (roomy — some names are long, e.g. "Juan Francisco Valdes")
    for c in range(max_races):
        t.setColumnWidth(race0 + c, 54)
    t.setColumnWidth(pts_col, 70)
    t.horizontalHeader().setStretchLastSection(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    t.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    for c in range(pts_col + 1):
        hdr = t.horizontalHeaderItem(c)
        if hdr is not None:
            hdr.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

    # Same reasoning as _build_rider_race_matrix: fix the height to fit every
    # rider with no vertical scrollbar of its own — the page's own scroll
    # area (or the wrapping QScrollArea's bar, driven via scroll_by below)
    # takes over once there's genuinely too much content for the screen.
    t.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    t.setFixedHeight(t.horizontalHeader().sizeHint().height() + t.verticalHeader().length()
                     + 2 * t.frameWidth())
    return t


class _RidersDetailView(QWidget):
    """Riders Standings — DETAILS: race-by-race finishing order, championship-
    mode style (contrast BASIC's plain Pos/Name/Points list).

    The title lives outside its own internal QScrollArea (only the table
    sits inside it) so a season with enough riders/races to overflow one
    screen scrolls the table in place under a pinned title, instead of the
    whole view — title included — panning as one block. Same pattern as
    _StandingsListView/_CalendarView; see _SideSubHub's needs_scroll
    docstring."""

    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 44, 12, 40)
        outer.setSpacing(0)

        title = QLabel('RIDERS — RACE BY RACE')
        title.setFont(QFont('Segoe UI', 22, QFont.Weight.Bold))
        title.setStyleSheet('color:#ffffff; letter-spacing:2px; background:transparent; border:none;')
        outer.addWidget(title)
        outer.addSpacing(22)

        # Horizontal scrolling of the wide R1…Rn grid stays with the table's
        # own scrollbar (_build_riders_detail_table) — this wrap only ever
        # needs to move vertically (_make_scroll_area already keeps its own
        # horizontal bar off).
        self._scroll = _make_scroll_area()
        cont = QWidget()
        cont.setStyleSheet('background: transparent;')
        self._lay = QVBoxLayout(cont)
        self._lay.setContentsMargins(0, 0, 12, 0)
        self._lay.setSpacing(0)
        self._lay.addStretch(1)
        self._scroll.setWidget(cont)
        outer.addWidget(self._scroll, 1)
        self._body = None

    def scrollbar(self):
        return self._scroll.verticalScrollBar()

    def reset(self):
        """Scroll back to top when this view is closed/reopened — mirrors
        what the (now-removed) outer wrapping QScrollArea used to do via
        _SideSubHub.reset()'s own sc.verticalScrollBar() reset."""
        bar = self._scroll.verticalScrollBar()
        if bar is not None:
            bar.setValue(0)

    def load(self, standings: list, rounds_detail: list | None):
        if self._body is not None:
            self._lay.removeWidget(self._body)
            self._body.deleteLater()
            self._body = None
        if standings:
            self._body = _build_riders_detail_table(standings, rounds_detail or [])
        else:
            note = QLabel('No standings yet — check back after your first season.')
            note.setWordWrap(True)
            note.setFont(QFont('Segoe UI', 14))
            note.setStyleSheet('color:#8a8aa2; background:transparent; border:none;')
            self._body = note
        self._lay.insertWidget(self._lay.count() - 1, self._body)

    def scroll_by(self, dx: int, dy: int):
        """Pan the race-by-race grid with the arrow keys: horizontal through
        the table's own scrollbar (R1…Rn can be wider than the viewport);
        vertical through this view's own internal QScrollArea instead of the
        table's — the table fixes its own height to fit every rider with no
        vertical scrollbar of its own (see _build_riders_detail_table),
        precisely so this wrap is what has room to move."""
        body = self._body
        hbar = getattr(body, 'horizontalScrollBar', None)
        if dx and callable(hbar):
            bar = hbar(); bar.setValue(bar.value() + dx)
        if dy:
            bar = self._scroll.verticalScrollBar()
            if bar is not None:
                bar.setValue(bar.value() + dy)


class _RidersStandingsScreen(_SideSubHub):
    """RIDERS entry within Standings: BASIC (Pos/Name/Points) and DETAILS
    (race-by-race grid), championship-mode style — no picker step, Enter
    toggles straight between the two (and back), Escape bubbles straight up
    to _StandingsScreen's own RIDERS/TEAMS/MANUFACTURERS tab bar.

    A footer pinned to the very bottom of the SCREEN (not the bottom of
    whichever list/grid happens to be showing — that would scroll out of
    view once the content overflows one screen) advertises the Enter-to-
    toggle control, swapping its wording between BASIC and DETAILS."""

    _HINTS = ['Press Enter to see details',
             'Press Enter to see the shortened version']

    def __init__(self, basic_view: _StandingsListView, detail_view: _RidersDetailView):
        # Both False: _StandingsListView/_RidersDetailView each scroll their
        # own content internally (title stays pinned above it) — wrapping
        # either in another outer QScrollArea here would scroll the title
        # along with the content. See their own docstrings / _SideSubHub's
        # needs_scroll docstring.
        super().__init__([('BASIC', basic_view, False), ('DETAILS', detail_view, False)],
                         tint_margin=16, cycle=True)

        self._footer = QLabel()
        self._footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._footer.setFont(QFont('Segoe UI', 10))
        self._footer.setStyleSheet(
            'color:#c8c8d8; letter-spacing:1px; border:none; padding:10px 0;'
            f'background: rgba({_PANEL_TINT.red()}, {_PANEL_TINT.green()}, '
            f'{_PANEL_TINT.blue()}, {_PANEL_TINT.alpha()});')
        self.layout().addWidget(self._footer)
        self._sync_footer()

    def _sync_footer(self):
        self._footer.setText(self._HINTS[self._focus])

    def reset(self):
        super().reset()
        self._sync_footer()

    def handle_key(self, key: int):
        result = super().handle_key(key)
        self._sync_footer()
        return result


class _StandingsScreen(_SideSubHub):
    """STANDINGS entry within Season Info: RIDERS (its own BASIC/DETAILS
    Enter-toggle), TEAMS, and MANUFACTURERS."""

    def __init__(self):
        self._riders_basic = _StandingsListView('RIDERS')
        self._riders_detail = _RidersDetailView()
        self._riders = _RidersStandingsScreen(self._riders_basic, self._riders_detail)
        self._teams = _StandingsListView('TEAMS')
        self._manu = _StandingsListView('MANUFACTURERS')
        super().__init__([
            ('RIDERS', self._riders, False),
            ('TEAMS', self._teams, False),
            ('MANUFACTURERS', self._manu, False),
        ], tint_margin=24)

    def load(self, riders: list, teams: list, manu: list, rounds_detail: list | None):
        self._riders_basic.load(riders, lambda s: TEAM_COLOR.get(str(s.get('team', '')))
                                 or MANU_COLOR.get(str(s.get('manufacturer', '')), _DEFAULT_COLOR))
        self._riders_detail.load(riders, rounds_detail)
        self._teams.load(teams, lambda s: TEAM_COLOR.get(str(s.get('name', '')), _DEFAULT_COLOR))
        self._manu.load(manu, lambda s: MANU_COLOR.get(str(s.get('name', '')), _DEFAULT_COLOR))


def _seat_tint(tc: QColor) -> QColor:
    """Team colour pulled into a band that works as a row fill behind white
    text. The palette spans Triumph's near-black and BMW's near-white, and
    neither survives being used raw: one reads as no colour at all, the other as
    a grey slab you can't read off. Clamping value (and saturation, so the
    brightest reds don't vibrate) keeps all twelve recognisable as *their* colour
    while sharing one legibility floor. Greys get pulled down further — with no
    hue to carry it, lightness is all they have."""
    h, s, v, a = tc.getHsv()
    ceiling = 112 if s < 40 else 148
    return QColor.fromHsv(h, min(s, 205), max(70, min(v, ceiling)), a)


def _seat_accent(tc: QColor) -> QColor:
    """The same colour at full strength, for the strip and team name beside the
    row — those sit on the page's own dark backdrop, so here the floor is a
    minimum brightness rather than a ceiling."""
    h, s, v, a = tc.getHsv()
    return QColor.fromHsv(h, min(s, 190), max(v, 190), a)


class _RiderSeat(QFrame):
    """One rider inside a team row: bike number and name, on the team's colour.

    Two of these sit side by side per team, so a seat that nobody fills (a grid
    caught mid-market, or a legacy career whose roster predates the player
    taking a real seat) still holds its half of the row rather than letting the
    other rider stretch across it."""

    _H = 54

    def __init__(self):
        super().__init__()
        self.setFixedHeight(self._H)
        self._focused = False
        self._empty   = True
        self._tc      = _DEFAULT_COLOR

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(12)
        self._num = QLabel('')
        self._num.setFont(QFont('Consolas', 12, QFont.Weight.Bold))
        self._num.setFixedWidth(38)
        lay.addWidget(self._num)
        self._name = QLabel('')
        self._name.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
        lay.addWidget(self._name, 1)
        self._tag = QLabel('')
        self._tag.setFont(QFont('Segoe UI', 8, QFont.Weight.Bold))
        lay.addWidget(self._tag)
        self._apply()

    def set_rider(self, rider: dict | None, tc: QColor, is_player: bool):
        self._empty = rider is None
        self._tc = tc
        if rider is None:
            self._num.setText('')
            self._name.setText('—')
            self._tag.setText('')
        else:
            self._num.setText(f"#{rider['bike_number']}")
            self._name.setText(str(rider['name']).upper())
            self._tag.setText('YOU' if is_player else '')
        self._apply()

    def set_focused(self, f: bool):
        self._focused = f
        self._apply()

    def _apply(self):
        bg = _seat_tint(self._tc)
        accent = _seat_accent(self._tc)
        if self._focused:
            bg, border = bg.lighter(140), accent.name()
            num, name, width = '#ffffff', '#ffffff', 2
        else:
            border, num, name, width = 'transparent', accent.name(), '#e8e8f0', 2
        if self._empty:
            bg, num, name = QColor(14, 14, 22), '#555566', '#555566'
        self.setStyleSheet(
            f'QFrame {{ background: {bg.name()}; border: {width}px solid {border};'
            f' border-radius: 5px; }}'
            f' QLabel {{ background: transparent; border: none; }}')
        self._num.setStyleSheet(f'color: {num};')
        self._name.setStyleSheet(f'color: {name};')
        self._tag.setStyleSheet('color: #ffd24a;')


class _TeamRow(QWidget):
    """A team's name and its two seats, as one line of the grid."""

    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self._bar = QFrame()
        self._bar.setFixedWidth(4)
        lay.addWidget(self._bar)
        self._team = QLabel('')
        self._team.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
        self._team.setFixedWidth(190)
        lay.addWidget(self._team)
        self.seats = [_RiderSeat(), _RiderSeat()]
        for s in self.seats:
            lay.addWidget(s, 1)

    def load(self, team: str, riders: list, tc: QColor, player_name: str):
        accent = _seat_accent(tc)
        self._bar.setStyleSheet(f'background: {accent.name()}; border: none;'
                                f' border-radius: 2px;')
        self._team.setText(team.upper())
        self._team.setStyleSheet(f'color: {accent.name()};'
                                 f' background: transparent; border: none;')
        for i, seat in enumerate(self.seats):
            r = riders[i] if i < len(riders) else None
            seat.set_rider(r, tc, r is not None and r['name'] == player_name)


class _RiderGridView(QWidget):
    """The season's grid as twelve team rows of two riders each.

    Reads wiz.df, which in a career is the slot's own roster plus the player
    (see wizard.apply_roster_to_df), so once a transfer market has run it shows
    the riders actually racing rather than the CSV line-up — which is why it is
    rebuilt on every load instead of populated once.

    Rows are ordered by bike power, strongest first, computed from the riders'
    own bike stats rather than by re-reading bikes_rating.csv: they carry the
    machinery they were signed onto (transfers.sign), so this stays right even
    for a grid the CSV no longer describes.
    """

    def __init__(self, wiz):
        super().__init__()
        self._wiz = wiz
        self._rows: list = []
        self._squads: list = []          # [(team, [rider, …]), …] matching _rows
        self._focus = (0, 0)             # (row, seat)
        self._player_name = ''
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 24, 40, 24)
        root.setSpacing(0)
        root.addWidget(_panel_title('RIDERS'))
        root.addSpacing(12)

        body = QWidget()
        body.setStyleSheet('background: transparent;')
        self._body_lay = QVBoxLayout(body)
        self._body_lay.setContentsMargins(0, 0, 0, 0)
        self._body_lay.setSpacing(6)
        self._scroll = _make_scroll_area()
        self._scroll.setWidget(body)
        root.addWidget(self._scroll, 1)

    def reload(self):
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows, self._squads = [], []

        # The career rider is whatever sits past the AI grid at the tail of the
        # frame — the invariant apply_roster_to_df keeps — rather than a re-read
        # of rider.json, which would miss a rider created but not yet committed.
        df = self._wiz.df
        tail = df.iloc[int(getattr(self._wiz, '_base_rider_count', len(df))):]
        self._player_name = str(tail.iloc[0]['name']) if len(tail) else ''

        squads: dict = {}
        for _, row_s in df.iterrows():
            r = row_s.to_dict()
            squads.setdefault(str(r.get('team', '')), []).append(r)
        for riders in squads.values():
            riders.sort(key=lambda r: int(r['bike_number']))

        def power(riders):
            keys = ('top_speed', 'acceleration', 'bike_braking',
                    'bike_cornering', 'stability')
            return sum(float(riders[0].get(k, 0)) for k in keys) / len(keys)

        for team, riders in sorted(squads.items(), key=lambda kv: -power(kv[1])):
            tc = TEAM_COLOR.get(team) or MANU_COLOR.get(
                str(riders[0].get('manufacturer', '')), _DEFAULT_COLOR)
            row = _TeamRow()
            row.load(team, riders, tc, self._player_name)
            self._body_lay.addWidget(row)
            self._rows.append(row)
            self._squads.append((team, riders))
        self._body_lay.addStretch(1)

        self._focus = (0, 0)
        self._sync_focus()

    def current(self) -> dict | None:
        """The rider under the cursor, or None on an empty seat."""
        r, c = self._focus
        if r >= len(self._squads):
            return None
        riders = self._squads[r][1]
        return riders[c] if c < len(riders) else None

    def _sync_focus(self):
        for i, row in enumerate(self._rows):
            for j, seat in enumerate(row.seats):
                seat.set_focused((i, j) == self._focus)
        if self._rows:
            self._scroll.ensureWidgetVisible(self._rows[self._focus[0]], 0, 40)

    def move(self, dr: int, dc: int):
        if not self._rows:
            return
        r, c = self._focus
        if dr:
            r = (r + dr) % len(self._rows)
        if dc:
            c = (c + dc) % 2
        self._focus = (r, c)
        self._sync_focus()


class _RiderInfoScreen(QWidget):
    """RIDERS entry within Season Info: the grid of twelve team rows, and the
    rider's own page once one is opened with Enter.

    Having handle_key is what tells _SideSubHub this is a self-driving view: it
    gets added with no tint wrap, which is right — both pages below paint their
    own near-opaque backdrop already."""

    def __init__(self, wiz):
        super().__init__()
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self._grid = _RiderGridView(wiz)
        # Placeholder until the rider page is specified: Gallery's own panel,
        # which at least shows the right rider.
        self._detail = _RiderDetail()
        detail_page = QWidget()
        detail_page.setStyleSheet('background: transparent;')
        dl = QVBoxLayout(detail_page)
        dl.setContentsMargins(0, 0, 0, 0)
        self._detail_scroll = _make_scroll_area()
        self._detail_scroll.setWidget(self._detail)
        dl.addWidget(self._detail_scroll)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet('background: transparent;')
        self._stack.addWidget(self._grid)
        self._stack.addWidget(detail_page)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._stack)

    def load(self):
        self._grid.reload()
        self._stack.setCurrentIndex(0)

    def handle_key(self, key: int):
        K = Qt.Key
        if self._stack.currentIndex() == 1:            # a rider's own page
            if key in (K.Key_Escape, K.Key_Backspace):
                self._stack.setCurrentIndex(0)
                return None
            if key in (K.Key_Up, K.Key_Down):
                bar = self._detail_scroll.verticalScrollBar()
                if bar is not None:
                    bar.setValue(bar.value() + (-60 if key == K.Key_Up else 60))
                return 'scroll'
            return None

        if key in (K.Key_Up, K.Key_Down, K.Key_Left, K.Key_Right):
            self._grid.move(1 if key == K.Key_Down else -1 if key == K.Key_Up else 0,
                            1 if key == K.Key_Right else -1 if key == K.Key_Left else 0)
            # Moving around the grid is browsing, not a tab-focus move —
            # 'scroll' is what tells SeasonHubPage to suppress the wizard's
            # 'navigate' click.
            return 'scroll'
        if key in (K.Key_Return, K.Key_Enter, K.Key_Space):
            rider = self._grid.current()
            if rider is not None:
                self._detail.load(rider)
                self._detail_scroll.verticalScrollBar().setValue(0)
                self._stack.setCurrentIndex(1)
            return None
        if key in (K.Key_Escape, K.Key_Backspace):
            return 'close'
        return None              # swallow the rest rather than let it fall through

    def paintEvent(self, event):
        # Both pages below are transparent, so the near-opaque backdrop belongs
        # here — it is also what lets _SideSubHub add this view with no tint
        # wrap of its own.
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(5, 5, 14, 218))


class _SeasonInfoScreen(_SideSubHub):
    """Same focus-then-open sub-hub as Your Profile: a vertical stack of tab
    bars pinned top-left (STANDINGS / CALENDAR / RIDERS), Enter opens the
    selection full-screen behind a dark tint, Escape closes it back to the tab
    stack. STANDINGS itself opens a further Riders/Teams/Manufacturers picker."""

    def __init__(self, wiz):
        self._standings = _StandingsScreen()
        self._calendar_view = _CalendarView()
        self._rider_info = _RiderInfoScreen(wiz)
        super().__init__([
            ('STANDINGS', self._standings, False),
            ('CALENDAR', self._calendar_view, False),
            ('RIDERS', self._rider_info, False),
        ])

    def load(self, riders: list, teams: list, manu: list, season_df,
            rounds_detail: list | None):
        self._standings.load(riders, teams, manu, rounds_detail)
        self._calendar_view.load(season_df)
        bar = self._calendar_view.scrollbar()
        if bar is not None:
            bar.setValue(0)
        self._rider_info.load()


# ── Between-GP map transition ─────────────────────────────────────────────────

class GpMapPage(QWizardPage):
    """Career only: full-screen page between the between-GP recap hub and the
    next round — a live world map camera-flies from the GP just finished to
    the next one's country (WorldMapWidget.fly_to — zoom out to hold both
    flags on screen, then zoom into the destination), edge to edge with no
    caption.

    A genuine QWizardPage (not a sub-state inside SeasonHubPage's own
    QStackedWidget, which is how this started out): leaving it needs to be a
    real QWizard page transition — hosting the live map as just one more page
    in SeasonHubPage's internal stack left stale ghosted frames behind when
    landing back on the dashboard (its matplotlib canvas, a
    FigureCanvasQTAgg, doesn't tear down cleanly on an internal-only stack
    switch the way it does on an actual page hide/show).

    Landing and leaving are two separate steps, both driven by Enter:
      - mid-flight, Enter cuts the pan short and lands immediately;
      - once landed (naturally or via that cut-short), the view just sits
        there — it does NOT auto-advance — and a further Enter is what
        actually moves on (wiz.next(), back to the Season Hub — see
        nextId())."""

    def __init__(self, wiz):
        super().__init__()
        self._wiz = wiz
        self.setTitle('')
        self.setSubTitle('')
        self._active = False
        self._landed = False
        self._from_country = None
        self._to_country = None
        self.setStyleSheet('background: #08080e;')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._map = WorldMapWidget()
        lay.addWidget(self._map)

    def preload(self, from_country: str, to_country: str):
        """Kick off the flight's capture in the background as soon as the
        destination is known (see WorldMapWidget.preload_fly), and remember
        the pair for initializePage() below — called from the recap hub,
        well before the player presses "To next grand prix", so the fly_to()
        call below usually finds it already cached."""
        self._from_country = from_country
        self._to_country = to_country
        self._map.preload_fly(from_country, to_country)

    def initializePage(self):
        self._active = True
        self._landed = False
        self._map.fly_to(self._from_country, self._to_country, on_done=self._on_landed)
        self.setFocus()

    def _on_landed(self):
        """The camera reached the destination — naturally, or because a skip
        just cut the pan short. Freeze here; leaving needs its own,
        subsequent Enter (see handle_key)."""
        self._landed = True

    def handle_key(self, key: int) -> bool:
        K = Qt.Key
        if key in (K.Key_Return, K.Key_Enter, K.Key_Space, K.Key_Escape, K.Key_Backspace):
            self._advance()
        return True

    def _advance(self):
        """Enter pressed. Mid-flight: land immediately (cut the pan short)
        and wait there. Already landed: actually leave the page — back to the
        Season Hub."""
        if not self._active:
            return
        if not self._landed:
            self._map.fly_skip(self._to_country, on_done=self._on_landed)
            return
        self._active = False
        # This round boundary's recap has now been seen — don't show it again
        # when the hub reloads right after (see SeasonHubPage._refresh_data).
        self._wiz.gp_recap_dismissed_for = self._wiz.circuit_index
        # The hub sits one page BEHIND this one in wizard history (it navigated
        # here via next()), so return the same way every session page does —
        # walk history back with return_to_hub(), NOT next(). QWizard.next()
        # only ever moves forward to nextId(); it can't step back onto an
        # already-visited page, so using it here left Enter doing nothing.
        self._wiz.return_to_hub()


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
        self._hub_focus = 0
        # Between-GP recap state (set by _refresh_data): True while the hub is
        # showing the post-Finish "TO NEXT GRAND PRIX" landing, plus the
        # (from_country, to_country) GpMapPage flies between when "To next
        # grand prix" is pressed — see _go_next/nextId(). (Whether the recap
        # has already been dismissed for the current round boundary lives on
        # the wizard — wiz.gp_recap_dismissed_for, set by GpMapPage — since
        # that page, not this one, is what marks it seen.)
        self._showing_next_gp = False
        self._next_gp_info = None

        self._stack = QStackedWidget(self)
        self._stack.setAutoFillBackground(False)
        self._stack.setStyleSheet('background: transparent;')

        self._intro = _SeasonIntroVideo()          # paints its own background
        self._intro.finished.connect(self._show_hub)
        self._stack.addWidget(self._intro)                      # 0

        self._hub = _TopTabBar(['TO NEXT SESSION', 'YOUR PROFILE', 'SEASON INFO', 'MAIN MENU'])
        self._hub_dashboard = _HubDashboard()
        hub_page = QWidget()
        hub_page.setStyleSheet('background: transparent;')
        hub_page_lay = QVBoxLayout(hub_page)
        hub_page_lay.setContentsMargins(0, 0, 0, 0)
        hub_page_lay.setSpacing(0)
        hub_page_lay.addWidget(self._hub)
        hub_page_lay.addSpacing(30)
        # The dashboard sits in a scroll area with its scrollbars HIDDEN. Two
        # things keep the board tidy at any window size:
        #  - width: the side columns shrink proportionally on a narrow window
        #    (_HubDashboard._relayout_columns), so nothing overlaps.
        #  - height: the scroll area holds the board at (at least) its own
        #    minimum height, so a short window never squeezes a card below its
        #    rows (which used to clip the last standings row) — the overflow is
        #    just cropped off the bottom instead. At the app's normal size the
        #    whole board fits, with no scrollbar and nothing cropped.
        self._dash_scroll = _make_scroll_area()
        self._dash_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._dash_scroll.setWidget(self._hub_dashboard)
        hub_page_lay.addWidget(self._dash_scroll, 1)
        self._stack.addWidget(self._wrap(hub_page))               # 1

        self._profile = _ProfileScreen()
        self._stack.addWidget(self._wrap(self._profile))         # 2

        self._season_info = _SeasonInfoScreen(self._wiz)
        self._stack.addWidget(self._wrap(self._season_info))     # 3

        # Only the intro plays video; once it's done the hub/profile/season
        # info sit over this static image instead of the shared ambient loop.
        # Named _vbg (matching every video-backed page) so the wizard's _GapFiller
        # picks it up automatically and continues it into the reserved strip
        # below the page instead of leaving that strip plain black.
        self._vbg = _StaticBackground(_HUB_BG)

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
        """Convert the wizard's in-memory, not-yet-archived rounds for the
        season currently being played into the same rounds_detail shape
        history.json uses (mirrors p4_championship._save_history), so a
        season shows dashboard info from its 1st round onward instead of only
        after the whole season is archived at season end.

        Includes the round currently being played (its already-finished races
        from wiz.race_results, not yet banked into round_results) — mirroring
        p4._season_rounds() — so a just-completed Race 1 refreshes the
        dashboard (standings, recent form, lap records) immediately instead of
        only once Race 2 banks the whole round."""
        wiz = self._wiz
        df = getattr(wiz, 'df', None)
        if df is None:
            return []
        # Banked rounds + the in-progress one (built exactly as _bank_round
        # will bank it). A race lives in exactly one of round_results /
        # race_results at any moment, so this never double-counts.
        rounds = list(getattr(wiz, 'round_results', None) or [])
        live_races = getattr(wiz, 'race_results', None)
        circuit = getattr(wiz, 'circuit', None)
        if live_races and circuit is not None:
            from app.pages.p4_championship import _round_lap_records
            rounds = rounds + [{'circuit': circuit['circuit_name'],
                                'country': circuit['country'],
                                'races': list(live_races),
                                'lap_records': _round_lap_records(wiz)}]
        if not rounds:
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
                                  'races': races_out, 'lap_records': rd.get('lap_records')})
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
        season_complete = bool(self._wiz.season_complete)
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
        elif season_complete and seasons:
            # Season just finished (round_results cleared at Finish): show the
            # just-archived season's FINAL standings as the "TO NEXT SEASON"
            # summary. seasons[-1] is that season (append-ordered archive), and
            # it's the only copy — no live_rounds — so nothing double-counts.
            last_season = seasons[-1]
            standings = last_season.get('standings', [])
            honours = None
            current_rounds_detail = last_season.get('rounds_detail')
            if current_rounds_detail:
                data = _season_tables_data(last_season)
                if data is not None:
                    honours = _honours_data(data)['riders']
            recent_races = _recent_form(current_rounds_detail or [], name or '')
        else:
            # No round completed in the current season yet (e.g. right after
            # advancing to a new season): show an EMPTY season dashboard rather
            # than the just-finished season's results. Standings / honours /
            # team + manufacturer tables visibly reset to zero and refill from
            # this season's first completed round. Career totals (the profile
            # `rec` below) and the track-history boards stay cumulative — they
            # aggregate every archived season, not just the current one.
            standings = []
            honours = None
            data = None
            current_rounds_detail = None
            # Recent Form is season-scoped too: an empty new season shows blank
            # form boxes rather than trailing in last season's final results.
            recent_races = []

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

        team_standings = ([{'name': t, 'points': data['team_total'][t]} for t in data['teams_sorted']]
                          if data is not None else [])
        manu_standings = ([{'name': m, 'points': data['manu_total'][m]} for m in data['manu_sorted']]
                          if data is not None else [])

        wiz = self._wiz
        season_df = wiz.season_df

        # "Between grand prix" recap: shown at a round boundary once at least
        # one round has been completed this season — session_index 0 (next up is
        # a fresh weekend's Practice) AND circuit_index > 0. It keeps the JUST-
        # FINISHED GP on the left and its result in the middle while previewing
        # the NEXT GP (see below). Derived from persistent state, not a one-shot
        # flag, so it survives quitting and CONTINUE-ing while on the recap (the
        # round-granular save resumes exactly at this boundary anyway). Round 1
        # (circuit_index 0) stays the normal "TO NEXT SESSION" hub — and so does
        # landing back here after the map transition (GpMapPage) has already
        # been watched and dismissed for this same boundary
        # (wiz.gp_recap_dismissed_for) — otherwise the still-persistent
        # session_index/circuit_index state would show the recap again right
        # after leaving it.
        show_next_gp = (not season_complete and wiz.session_index == 0 and wiz.circuit_index > 0
                        and wiz.gp_recap_dismissed_for != wiz.circuit_index)
        if season_complete:
            self._hub.cards()[0].set_text('TO NEXT SEASON')
        else:
            self._hub.cards()[0].set_text('TO NEXT GRAND PRIX' if show_next_gp else 'TO NEXT SESSION')

        # circuit_index always points at the round about to be played next
        # (p4._bank_round() bumps it after a round is banked). On the between-GP
        # landing the left column / records / track history describe the round
        # just finished (circuit_index - 1); otherwise the upcoming one.
        def _season_row(idx):
            return (season_df.iloc[idx]
                    if season_df is not None and 0 <= idx < len(season_df) else None)
        if season_complete:
            # Off-season: no active/next GP — the left card reads "OFF-SEASON"
            # and there's no weather or map (the next season's calendar isn't
            # chosen yet).
            play_row = display_row = next_gp_row = None
        else:
            play_row = _season_row(wiz.circuit_index)          # the round to be played next
            display_row = _season_row(wiz.circuit_index - 1) if show_next_gp else play_row
            next_gp_row = play_row if show_next_gp else None    # middle preview of what's next

        # Arm the map transition for "To next grand prix" (see _go_next/
        # nextId()) when this is the between-GP landing — flies from the
        # just-finished GP's country to the next one's. Kicked off as a
        # background preload right away (not just when the button is
        # pressed) so the transition's expensive capture is normally already
        # done by the time the player actually presses it — see
        # WorldMapWidget.preload_fly.
        self._showing_next_gp = show_next_gp
        if show_next_gp and display_row is not None and next_gp_row is not None:
            from_country, to_country = str(display_row['country']), str(next_gp_row['country'])
            self._next_gp_info = (from_country, to_country)
            wiz.page(wiz.ID_GP_MAP).preload(from_country, to_country)
        else:
            self._next_gp_info = None

        display_circuit_name = str(display_row['circuit_name']) if display_row is not None else None
        track_winners, track_polesitters = _track_history(seasons_for_rec, display_circuit_name)
        brlc, blc = _track_records(seasons_for_rec, display_circuit_name)

        upcoming = SESSION_NAMES[wiz.session_index % len(SESSION_NAMES)]

        # Weather is always for the round you'll play next (play_row) so the
        # forecast RacePage reuses stays right, even on the between-GP landing
        # where the weather block itself is hidden.
        play_country = str(play_row['country']) if play_row is not None else None
        day = SESSION_DAY[wiz.session_index % len(SESSION_DAY)]
        if wiz.weekend_weather is None or wiz.weekend_weather.get('day') != day:
            wiz.weekend_weather = _roll_session_weather(play_country)
            wiz.weekend_weather['day'] = day
        weather = wiz.weekend_weather

        # Middle bottom card: season finale shows the final championship top-5;
        # the between-GP landing shows the finished GP's top-5 point scorers
        # (across its two races); otherwise the winner-favourites estimate for
        # the upcoming GP.
        favourites = None
        gp_result = None
        result_title = None
        champion = None
        champion_year = None
        next_gp_country = str(next_gp_row['country']) if next_gp_row is not None else None
        if season_complete:
            gp_result = standings[:5]
            result_title = 'FINAL STANDINGS'
            champion = standings[0].get('name') if standings else None
            champion_year = wiz.season_year
        elif show_next_gp:
            gp_result = _gp_point_scorers(live_rounds[-1]) if live_rounds else []
        else:
            # Recent form spans archived seasons + the live one so an early-
            # season round still finds its "last 5".
            form_rounds = []
            for s in seasons:
                form_rounds.extend(s.get('rounds_detail') or [])
            form_rounds.extend(live_rounds)
            form_scores = _form_scores(form_rounds, limit=5)
            # Race 2 only: +3/+2/+1 aggression for this circuit's Race-1 podium.
            race1_podium = None
            if wiz.session_index >= 4 and wiz.race_results:
                r1 = wiz.race_results[0]
                race1_podium = {str(r['name']): _FAV_PODIUM_AGGRO[int(r['pos'])]
                                for _, r in r1.iterrows()
                                if not bool(r['dnf']) and int(r['pos']) in _FAV_PODIUM_AGGRO}
            favourites = _winner_favourites(
                getattr(wiz, 'df', None), circuit=play_row,
                session_index=wiz.session_index, form_scores=form_scores,
                grid_df=wiz.grid_all_df, is_wet=bool(weather.get('is_wet')),
                race1_podium=race1_podium)

        # Team/manufacturer colours for the row-fill boards (Overall Stats +
        # Track History). `data['names']` only exists once this season has a
        # completed round; the current roster is a season-independent fallback
        # so the cumulative Track History rows (last winners/polesitters) stay
        # colour-filled even before the new season has produced any results.
        df = getattr(wiz, 'df', None)
        names_map = ({str(r['name']): {'team': str(r['team']),
                                       'manufacturer': str(r['manufacturer'])}
                      for _, r in df.iterrows()} if df is not None else {})
        if data is not None:
            names_map.update(data['names'])

        self._hub_dashboard.load(standings, recent_races, honours,
                                 team_standings, manu_standings,
                                 names_map,
                                 next_circuit=display_row,
                                 track_winners=track_winners,
                                 track_polesitters=track_polesitters,
                                 brlc=brlc, blc=blc,
                                 upcoming_session=upcoming,
                                 weather=weather,
                                 favourites=favourites,
                                 next_gp_country=next_gp_country,
                                 gp_result=gp_result,
                                 result_title=result_title,
                                 champion=champion, champion_year=champion_year)
        self._season_info.load(standings, team_standings, manu_standings,
                               self._wiz.season_df, current_rounds_detail)

    def initializePage(self):
        # Arrival from Calendar: either a brand-new round (session_index is
        # already 0 in memory — see reset_career_progress/begin_next_season_
        # setup/_bank_round's boundary reset) or CONTINUE resuming an
        # in-progress one exactly where it paused (session_index restored
        # from disk by CalendarPage._resume_season). Either way the value
        # already in memory is the right one — don't stomp it here.
        # resume_at_hub() (mid-weekend re-entry within the same run) likewise
        # leaves session_index alone so the round continues where it paused.
        self._hub_focus = 0
        # Switch to the career soundtrack BEFORE any pause/resume below, so a
        # season-start intro pauses (and later resumes) the career track
        # itself, never the main playlist it's replacing — a no-op every visit
        # after the first (see MotoWizard.play_career_music).
        self._wiz.play_career_music()
        if self._wiz.circuit_index == 0:
            # Start of a season, before Round 1: the intro clip plays first,
            # giving _refresh_data() (and the geometry-dependent layout work
            # it triggers — see resume_at_hub()) several seconds to settle
            # before the dashboard is ever actually shown, so populating it
            # while still hidden is safe here.
            self._refresh_data()
            self._sync_hub_focus()
            self._stack.setCurrentIndex(0)
            self._wiz.pause_music()     # the intro clip has its own audio
            self._intro.start()
        else:
            # CONTINUE'ing mid-season (before Round 2+): the intro is a
            # new-season beat, so skip it and drop straight onto the
            # dashboard — same landing as resume_at_hub(), same reason to
            # show first and populate after (see there).
            self._stack.setCurrentIndex(1)
            self._wiz.resume_music()
            self._refresh_data()
            self._sync_hub_focus()
        self.setFocus()     # keep focus off the video widget so Esc/Enter both reach handle_key

    def resume_at_hub(self):
        """Reopen straight on the dashboard, skipping the intro clip — used
        when a race session bails back to the hub mid-season (Esc after a
        round, or the between-GP map transition being dismissed) instead of
        arriving here fresh via Calendar.

        Ends by hide()+show()-ing the dashboard scroll area. This is the
        between-GP ghosting fix. Returning from the map (a separate
        QWizardPage), the hub's OWN internal QStackedWidget never left the
        dashboard page — it showed the recap the entire time the map was up —
        so the setCurrentIndex(1) below is a no-op: no hide/show, so no clean
        re-render, and _refresh_data() just mutates the (translucent) panels
        in place over their earlier paint, leaving it ghosted. Tabbing out to
        Profile/Calendar and back visibly clears it precisely because THAT
        does hide+show the dashboard page. So we do the same hide+show
        ourselves — deferred a tick so the layout (_sync_upcoming_height &c.)
        has settled first — forcing the same full clean repaint of the
        dashboard's whole region that a real tab switch gives."""
        self._stack.setCurrentIndex(1)
        self._refresh_data()
        self._hub_focus = 0
        self._sync_hub_focus()
        self._wiz.resume_music()
        self.setFocus()
        QTimer.singleShot(0, self._flush_dashboard)

    def _flush_dashboard(self):
        """Hide+show the dashboard to force a clean full repaint of its
        region — see resume_at_hub()."""
        self._dash_scroll.hide()
        self._dash_scroll.show()
        self._dash_scroll.repaint()

    def nextId(self):
        # Between-GP landing: "To Next Grand Prix" goes to the map transition
        # first (GpMapPage), which hands back here once dismissed. Otherwise
        # "To Next Session" navigates to the page owning the upcoming session:
        # Practice(0) -> ID_PRACTICE, Qualifying 1/2 -> ID_QUALI, Race 1/2 ->
        # ID_RACE. The pages themselves run only the session at session_index
        # and hand back to the hub afterwards (see return_to_hub_after_session).
        # Season over (career): the off-season transfer market comes before
        # next year's calendar — see _go_next and p_transfers.TransfersPage.
        if self._wiz.season_complete:
            return self._wiz.ID_TRANSFERS
        if self._showing_next_gp:
            return self._wiz.ID_GP_MAP
        idx = self._wiz.session_index
        if idx <= 0:
            return self._wiz.ID_PRACTICE
        if idx <= 2:
            return self._wiz.ID_QUALI
        return self._wiz.ID_RACE

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
                 self._open_season_info, self._confirm_main_menu)[self._hub_focus]()
            return True

        if idx == 2:                                      # Your Profile owns its own sub-nav
            result = self._profile.handle_key(key)
            # Opening/closing a sub-view flips whether the reserved bottom strip
            # is tinted (see paint_gap_overlay); the gap filler is a separate
            # overlay widget that won't repaint on its own, so nudge it.
            gap = getattr(self._wiz, '_gap_filler', None)
            if gap is not None:
                gap.update()
            if result == 'close':
                self._stack.setCurrentIndex(1)
            elif result == 'scroll':
                # A content scroll, not a tab-focus move — the wizard would
                # otherwise play its 'navigate' click for every arrow key.
                self._wiz.suppress_next_sfx = True
            return True

        if idx == 3:                                       # Season Info owns its own sub-nav
            result = self._season_info.handle_key(key)
            gap = getattr(self._wiz, '_gap_filler', None)
            if gap is not None:
                gap.update()
            if result == 'close':
                self._stack.setCurrentIndex(1)
            elif result == 'scroll':
                self._wiz.suppress_next_sfx = True
            return True

        return True

    def _open_profile(self):
        self._profile.reset()      # always land on the tab bar, not the last-viewed sub-tab
        self._stack.setCurrentIndex(2)

    def _open_season_info(self):
        self._season_info.reset()   # always land on the tab bar, not the last-viewed sub-tab
        self._stack.setCurrentIndex(3)

    def _go_next(self):
        # "TO NEXT SEASON" (season just finished) goes through the off-season
        # transfer market, which then opens next year's calendar itself. In
        # Championship mode — no roster, no career rider, no market — it still
        # jumps straight to calendar setup. Otherwise nextId() routes to
        # GpMapPage on the between-GP landing, or to the upcoming session's page.
        if self._wiz.season_complete and self._wiz.mode != 'career':
            self._wiz.begin_next_season_setup()
            return
        self._wiz.next()

    def _confirm_main_menu(self):
        dlg = ExitDialog(self._wiz, message='Return to Main Menu?', confirm_text='Yes, Return')
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._wiz.accept()      # bail out of the season start -> Home

    # ── Background painting: static image behind the hub/profile/season info ─
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
        elif self._stack.currentIndex() == 2 and self._profile.is_opened():
            # A Your Profile sub-view is open full-bleed over the whole page;
            # continue that same tint (over the photo _GapFiller already
            # painted) into the strip so the overlay reaches the very bottom
            # edge instead of leaving a photo sliver below it.
            painter.fillRect(rect, _PANEL_TINT)
        elif self._stack.currentIndex() == 3 and self._season_info.is_opened():
            # Same continuation for a full-bleed Season Info sub-view (Standings
            # or Calendar).
            painter.fillRect(rect, _PANEL_TINT)
