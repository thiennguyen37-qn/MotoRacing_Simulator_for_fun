from pathlib import Path
from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout,
                              QLabel, QFrame, QWidget, QApplication,
                              QPushButton, QDialog, QGraphicsOpacityEffect)
from PyQt6.QtGui import QFont, QPainter, QColor, QPixmap
from PyQt6.QtCore import (Qt, pyqtSignal, pyqtProperty, QPropertyAnimation,
                          QEasingCurve)

from app.widgets.video_bg import VideoBackground

_MENU_DIR = Path(__file__).parent.parent.parent / 'images' / 'menu'

# bottom status bar (option subtitle) — near-solid black, sized to ~2x the text
_BAND_CSS   = 'rgba(6, 6, 10, 235)'
_SBAR_PT    = 11       # subtitle font size
_SBAR_H     = 36       # bar thickness ≈ 2x the text height
# modern, motorsport-flavoured face for the uppercase subtitle (Bahnschrift is
# a DIN-style font bundled with Windows 10/11; Segoe UI is the fallback)
_SBAR_FAMILIES = ['Bahnschrift SemiBold', 'Bahnschrift', 'Segoe UI Semibold', 'Segoe UI']


def _statusbar_font() -> QFont:
    f = QFont()
    f.setFamilies(_SBAR_FAMILIES)
    f.setPointSize(_SBAR_PT)
    f.setBold(True)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
    return f


_LOGO_CACHE: dict[str, QPixmap | None] = {}


def _load_logo(key: str) -> QPixmap | None:
    # Cache decoded pixmaps: the carousel reconfigures tiles on every arrow
    # press, and re-reading/decoding the PNG from disk each time is what made
    # navigation feel laggy.
    if key in _LOGO_CACHE:
        return _LOGO_CACHE[key]
    pix = None
    for ext in ('png', 'jpg'):
        p = _MENU_DIR / f'{key}.{ext}'
        if p.exists():
            pix = QPixmap(str(p))
            break
    _LOGO_CACHE[key] = pix
    return pix


# ── Exit confirmation dialog ──────────────────────────────────────────────────

class ExitDialog(QDialog):
    def __init__(self, parent=None, message='Do you want to exit?',
                 confirm_text='Yes, Exit'):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(380, 180)

        geo = QApplication.primaryScreen().availableGeometry()
        self.move(geo.center().x() - 190, geo.center().y() - 90)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setStyleSheet(
            'QFrame { background-color: #111116; border: 1px solid #2a2a3a; border-radius: 12px; }'
            'QLabel { background: transparent; border: none; color: #ffffff; }'
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(32, 28, 32, 24)
        cl.setSpacing(20)

        msg = QLabel(message)
        msg.setFont(QFont('Segoe UI', 14, QFont.Weight.Bold))
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(msg)

        btns = QHBoxLayout()
        btns.setSpacing(12)

        self._btn_cancel = QPushButton('Cancel')
        self._btn_cancel.setFixedHeight(38)
        self._btn_cancel.setFont(QFont('Segoe UI', 10))
        self._btn_cancel.setAutoDefault(False)
        self._btn_cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_cancel.clicked.connect(self.reject)

        self._btn_yes = QPushButton(confirm_text)
        self._btn_yes.setFixedHeight(38)
        self._btn_yes.setFont(QFont('Segoe UI', 10, QFont.Weight.Bold))
        self._btn_yes.setAutoDefault(False)
        self._btn_yes.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_yes.clicked.connect(self.accept)

        btns.addWidget(self._btn_cancel)
        btns.addWidget(self._btn_yes)
        cl.addLayout(btns)
        root.addWidget(card)

        self._yes_focused = True
        self._update_focus()

    def _update_focus(self):
        if self._yes_focused:
            self._btn_yes.setStyleSheet(
                'QPushButton { background: #e02840; color: #fff;'
                ' border: 2px solid #ff6080; border-radius: 6px; }')
            self._btn_cancel.setStyleSheet(
                'QPushButton { background: #1a1a24; color: #555;'
                ' border: 1px solid #222; border-radius: 6px; }')
        else:
            self._btn_yes.setStyleSheet(
                'QPushButton { background: #2a0810; color: #884455;'
                ' border: none; border-radius: 6px; }')
            self._btn_cancel.setStyleSheet(
                'QPushButton { background: #2a2a3a; color: #fff;'
                ' border: 2px solid #6666aa; border-radius: 6px; }')

    def keyPressEvent(self, event):
        k = event.key()
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self._yes_focused = not self._yes_focused
            self._update_focus()
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.accept() if self._yes_focused else self.reject()
        elif k == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(self.rect(), 12, 12)


# ── Carousel arrow ─────────────────────────────────────────────────────────────

def _make_arrow(ch: str) -> QLabel:
    """A slim chevron flanking the carousel. Purely decorative — navigation is
    by keyboard. Kept visible only when there is a neighbour in that direction;
    at the list ends it is made transparent but still occupies its slot so the
    current tile stays pinned to the screen centre."""
    a = QLabel(ch)
    a.setAlignment(Qt.AlignmentFlag.AlignCenter)
    a.setFont(QFont('Segoe UI', 30, QFont.Weight.Bold))
    a.setFixedWidth(44)
    a.setStyleSheet('color: rgba(255,255,255,190); background: transparent; border: none;')
    return a


# ── Mode tile (carousel slot) ──────────────────────────────────────────────────

class ModeTile(QFrame):
    """One carousel slot: a logo above a label. The same three widgets are
    reused as the previous / current / next slots and reconfigured as the
    selection moves. The logo image (images/menu/<key>.png) is optional — until
    one is dropped in, a 'LOGO' placeholder box is shown."""

    clicked = pyqtSignal()

    _SS = """
        ModeTile {{ background: {bg}; border: 1px solid {border}; border-radius: 10px; }}
        ModeTile QLabel {{ background: transparent; border: none; color: {txt}; }}
    """

    # per-variant metrics: centre tile is bigger, side tiles smaller + dimmed
    _BIG  = dict(size=(200, 196), logo=104, logo_h=112, pt=12)
    _SIDE = dict(size=(152, 152), logo=74,  logo_h=82,  pt=10)

    def __init__(self):
        super().__init__()
        self._danger   = False
        self._center   = False
        self._blank    = False
        self._has_logo = False

        col = QVBoxLayout(self)
        col.setContentsMargins(12, 16, 12, 12)
        col.setSpacing(10)

        self._logo = QLabel()
        self._logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(self._logo)

        self._lbl = QLabel()
        self._lbl.setWordWrap(True)
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        col.addWidget(self._lbl, 1)

        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)

        # Gentle red pulse for the centre (selected) tile.
        self._pulse = 0.0
        self._last_alpha = -1
        self._pulse_anim = QPropertyAnimation(self, b'pulse', self)
        self._pulse_anim.setDuration(1100)
        self._pulse_anim.setLoopCount(-1)
        self._pulse_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._pulse_anim.setKeyValueAt(0.0, 0.0)
        self._pulse_anim.setKeyValueAt(0.5, 1.0)
        self._pulse_anim.setKeyValueAt(1.0, 0.0)

    # centre-tile background alpha oscillates with this 0..1 value
    def _get_pulse(self) -> float:
        return self._pulse

    def _set_pulse(self, v: float):
        self._pulse = v
        if self._center and not self._blank:
            # Quantise the alpha so we only re-apply the (expensive) stylesheet a
            # handful of times per cycle instead of on every animation frame.
            a = int(85 + v * 95) // 6 * 6   # ~85..180 — medium red that breathes
            if a != self._last_alpha:
                self._last_alpha = a
                self.setStyleSheet(self._SS.format(
                    bg=f'rgba(224,40,64,{a})', border='#ff6078', txt='#ffffff'))

    pulse = pyqtProperty(float, _get_pulse, _set_pulse)

    def configure(self, key: str, title: str, danger: bool, center: bool):
        """Populate this slot with a mode. center=True → big + highlighted;
        otherwise it is a smaller, dimmed neighbour."""
        self._blank  = False
        self._danger = danger
        self._center = center
        spec = self._BIG if center else self._SIDE
        self.setFixedSize(*spec['size'])
        self._logo.setFixedHeight(spec['logo_h'])

        pix = _load_logo(key)
        self._has_logo = pix is not None
        if self._has_logo:
            self._logo.setPixmap(pix.scaled(
                spec['logo'], spec['logo'], Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            self._logo.setPixmap(QPixmap())

        self._lbl.setText(title)
        self._lbl.setFont(QFont('Segoe UI', spec['pt'], QFont.Weight.Bold))
        self._opacity.setOpacity(1.0 if center else 0.5)
        self._apply()
        if center:
            if self._pulse_anim.state() != QPropertyAnimation.State.Running:
                self._pulse_anim.start()
        else:
            self._pulse_anim.stop()

    def set_blank(self):
        """Empty side slot that still occupies its footprint so the current
        tile stays centred when there is no neighbour on this side."""
        self._blank    = True
        self._center   = False
        self._has_logo = False
        self._pulse_anim.stop()
        self.setFixedSize(*self._SIDE['size'])
        self._logo.setFixedHeight(self._SIDE['logo_h'])
        self._logo.clear()
        self._logo.setStyleSheet('background: transparent; border: none;')
        self._lbl.clear()
        self.setStyleSheet('ModeTile { background: transparent; border: none; }')
        self._opacity.setOpacity(0.0)

    def _apply(self):
        if self._center:
            bg, border, txt = 'rgba(224,40,64,130)', '#ff6078', '#ffffff'
        elif self._danger:
            bg, border, txt = 'rgba(255,255,255,5)', '#33232a', '#cc9099'
        else:
            bg, border, txt = 'rgba(255,255,255,5)', '#2a2a3a', '#cfcfe0'
        self.setStyleSheet(self._SS.format(bg=bg, border=border, txt=txt))
        if self._has_logo:
            self._logo.setText('')
            self._logo.setStyleSheet('background: transparent; border: none;')
        else:
            c = '#e02840' if self._center else '#3a3a4a'
            self._logo.setText('LOGO')
            self._logo.setFont(QFont('Segoe UI', 8 if self._center else 7,
                                     QFont.Weight.Bold))
            self._logo.setStyleSheet(
                f'color: {c}; border: 1px dashed {c}; border-radius: 8px;'
                ' letter-spacing: 2px; background: transparent;')

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self._blank:
            self.clicked.emit()
        super().mousePressEvent(e)


# ── Page ─────────────────────────────────────────────────────────────────────

_MODES = [
    ('random',       'RANDOM RACE',          'Pick any circuit for a single weekend'),
    ('championship', 'CHAMPIONSHIP',         'Arrange a calendar and run a full season'),
    ('history',      'CHAMPIONSHIP HISTORY', 'Past champions and all-time rider records'),
    ('gallery',      'GALLERY',              'Browse rider and team profiles'),
    ('soundtrack',   'SOUNDTRACK',           'Browse and play music tracks'),
    ('exit',         'EXIT',                 'Close the application'),
]


class HomePage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self._wiz = wiz
        self.setTitle('')
        self.setSubTitle('')
        self._vbg = VideoBackground.instance()
        self._vbg.frame_ready.connect(self._on_bg_frame)

        self._modes = [m[0] for m in _MODES]
        self._subs  = {m[0]: m[2] for m in _MODES}
        self._focus_idx = 0

        # ── Tiles + subtitle band along the bottom, over the raw video ───────
        # No title/overlay — just the video, the tile row, and the focused
        # option's subtitle in a slim black status bar at the very bottom.
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addStretch(1)

        # Carousel: a big centre tile flanked by the dimmed previous / next
        # tiles and a chevron on each side. Only three tiles ever show; they are
        # reconfigured as the selection moves (see _set_focus).
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addStretch(1)
        self._arrow_l = _make_arrow('❮')
        self._tile_prev = ModeTile()
        self._tile_cur  = ModeTile()
        self._tile_next = ModeTile()
        self._arrow_r = _make_arrow('❯')
        self._tile_cur.clicked.connect(lambda: self._activate(self._focus_idx))
        for w in (self._arrow_l, self._tile_prev, self._tile_cur,
                  self._tile_next, self._arrow_r):
            row.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)
        root.addLayout(row)
        # bottom margin keeps the tile row just above the status-bar overlay
        # (the bar sits at the true window bottom; the page ends ~gap px above it)
        root.setContentsMargins(40, 34, 40, 18)

        # Bottom status bar — a slim black strip parented to the wizard so it
        # spans the full width and sits flush at the true window bottom (over
        # the strip QWizard reserves). Text is centred inside it.
        self._desc = QLabel(self._wiz)
        self._desc.setFont(_statusbar_font())
        self._desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._desc.setStyleSheet(
            f'background: {_BAND_CSS}; color: #ffffff; border: none;')
        self._desc.hide()
        self._wiz.currentIdChanged.connect(self._sync_statusbar)

    # ── Background ────────────────────────────────────────────────────────────

    def _on_bg_frame(self):
        if self.isVisible():
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        # Original video colour — no darkening overlay on the home page.
        offset = self.mapTo(self._wiz, self.rect().topLeft())
        self._vbg.paint(p, self, full_size=self._wiz.size(), offset=offset)

    # ── Bottom status bar (wizard-level overlay) ──────────────────────────────

    def place_bottom_overlay(self):
        """Position + raise the status bar. Also called by the wizard after it
        raises the gap filler, so the bar always stays above it."""
        self._desc.setGeometry(0, self._wiz.height() - _SBAR_H,
                               self._wiz.width(), _SBAR_H)
        self._desc.raise_()

    def _sync_statusbar(self):
        if self._wiz.currentPage() is self:
            self.place_bottom_overlay()
            self._desc.show()
        else:
            self._desc.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._desc.isVisible():
            self.place_bottom_overlay()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_statusbar()

    # ── Logic ─────────────────────────────────────────────────────────────────

    def initializePage(self):
        wiz = self._wiz
        wiz.mode          = None
        wiz.circuit_index = 0
        wiz.all_race_pts  = []
        from app.wizard import START_YEAR
        wiz.season_year   = START_YEAR
        self.completeChanged.emit()
        self._set_focus(0)

    def _set_focus(self, idx: int):
        n = len(self._modes)
        self._focus_idx = max(0, min(idx, n - 1))
        i = self._focus_idx

        key, title, _ = _MODES[i]
        self._tile_cur.configure(key, title, danger=(key == 'exit'), center=True)

        if i > 0:
            key, title, _ = _MODES[i - 1]
            self._tile_prev.configure(key, title, danger=(key == 'exit'), center=False)
            self._arrow_l.setStyleSheet(
                'color: rgba(255,255,255,190); background: transparent; border: none;')
        else:
            self._tile_prev.set_blank()
            self._arrow_l.setStyleSheet('color: transparent; background: transparent; border: none;')

        if i < n - 1:
            key, title, _ = _MODES[i + 1]
            self._tile_next.configure(key, title, danger=(key == 'exit'), center=False)
            self._arrow_r.setStyleSheet(
                'color: rgba(255,255,255,190); background: transparent; border: none;')
        else:
            self._tile_next.set_blank()
            self._arrow_r.setStyleSheet('color: transparent; background: transparent; border: none;')

        self._desc.setText(self._subs[self._modes[i]].upper())

    def handle_key(self, key: int) -> bool:
        if key == Qt.Key.Key_Left:
            if self._focus_idx > 0:
                self._set_focus(self._focus_idx - 1)
            return True
        if key == Qt.Key.Key_Right:
            if self._focus_idx < len(self._modes) - 1:
                self._set_focus(self._focus_idx + 1)
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._activate(self._focus_idx)
            return True
        return False

    def _activate(self, idx: int):
        self._set_focus(idx)
        mode = self._modes[idx]
        if mode == 'exit':
            self._confirm_exit()
        else:
            self._wiz.mode = mode
            self._wiz.next()

    def _confirm_exit(self):
        # The single "Do you want to exit?" confirmation lives in
        # MotoWizard.closeEvent (it also covers the window X button and
        # Alt+F4). Since Qt 6.5, QApplication.quit() closes windows first —
        # so showing a dialog here produced the confirmation twice.
        self._wiz.close()

    def isComplete(self):
        return self._wiz.mode is not None

    def nextId(self):
        if self._wiz.mode == 'championship':
            return self._wiz.ID_CALENDAR
        if self._wiz.mode == 'history':
            return self._wiz.ID_HISTORY
        if self._wiz.mode == 'gallery':
            return self._wiz.ID_GALLERY
        if self._wiz.mode == 'soundtrack':
            return self._wiz.ID_SOUNDTRACK
        return self._wiz.ID_CIRCUIT
