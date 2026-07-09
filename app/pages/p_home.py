from pathlib import Path
from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout,
                              QLabel, QFrame, QWidget, QApplication,
                              QPushButton, QDialog)
from PyQt6.QtGui import QFont, QPainter, QColor, QPixmap
from PyQt6.QtCore import Qt, pyqtSignal

from app.widgets.video_bg import VideoBackground

_MENU_DIR = Path(__file__).parent.parent.parent / 'images' / 'menu'

# bottom status bar (option subtitle) — near-solid black, sized to ~2x the text
_BAND_CSS   = 'rgba(6, 6, 10, 235)'
_SBAR_PT    = 10       # subtitle font size
_SBAR_H     = 34       # bar thickness ≈ 2x the text height


def _load_logo(key: str) -> QPixmap | None:
    for ext in ('png', 'jpg'):
        p = _MENU_DIR / f'{key}.{ext}'
        if p.exists():
            return QPixmap(str(p))
    return None


# ── Exit confirmation dialog ──────────────────────────────────────────────────

class ExitDialog(QDialog):
    def __init__(self, parent=None):
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

        msg = QLabel('Do you want to exit?')
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

        self._btn_yes = QPushButton('Yes, Exit')
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


# ── Mode tile (horizontal menu) ────────────────────────────────────────────────

class ModeTile(QFrame):
    """One entry in the horizontal home menu: a logo above a label. The logo
    image (images/menu/<key>.png) is optional — until one is dropped in, a
    'LOGO' placeholder box is shown."""

    clicked = pyqtSignal()

    _SS = """
        ModeTile {{ background: {bg}; border: 1px solid {border}; border-radius: 10px; }}
        ModeTile QLabel {{ background: transparent; border: none; color: {txt}; }}
    """

    def __init__(self, key, title, danger=False):
        super().__init__()
        self._danger  = danger
        self._focused = False
        self.setFixedSize(162, 140)

        col = QVBoxLayout(self)
        col.setContentsMargins(12, 16, 12, 12)
        col.setSpacing(10)

        self._logo = QLabel()
        self._logo.setFixedHeight(60)
        self._logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = _load_logo(key)
        self._has_logo = pix is not None
        if self._has_logo:
            self._logo.setPixmap(pix.scaled(
                58, 58, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        col.addWidget(self._logo)

        self._lbl = QLabel(title)
        self._lbl.setWordWrap(True)
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self._lbl.setFont(QFont('Segoe UI', 10, QFont.Weight.Bold))
        col.addWidget(self._lbl, 1)

        self._apply()

    def _apply(self):
        if self._focused:
            bg, border, txt = 'rgba(224,40,64,45)', '#e02840', '#ffffff'
        elif self._danger:
            bg, border, txt = 'rgba(255,255,255,5)', '#33232a', '#cc9099'
        else:
            bg, border, txt = 'rgba(255,255,255,5)', '#2a2a3a', '#cfcfe0'
        self.setStyleSheet(self._SS.format(bg=bg, border=border, txt=txt))
        if not self._has_logo:
            c = '#e02840' if self._focused else '#3a3a4a'
            self._logo.setText('LOGO')
            self._logo.setFont(QFont('Segoe UI', 7, QFont.Weight.Bold))
            self._logo.setStyleSheet(
                f'color: {c}; border: 1px dashed {c}; border-radius: 8px;'
                ' letter-spacing: 2px; background: transparent;')

    def set_focused(self, v: bool):
        self._focused = v
        self._apply()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
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

        # ── Title top, tiles + subtitle band along the bottom ────────────────
        # The home video plays at its original colour (no darkening overlay);
        # the focused option's subtitle sits in a solid black band instead, so
        # it stays readable without dimming the footage.
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        ttl = QLabel('MotoRacing Simulator')
        ttl.setFont(QFont('Segoe UI', 30, QFont.Weight.Bold))
        ttl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ttl.setStyleSheet('color: #ffffff; background: transparent; border: none;')
        root.addWidget(ttl)
        root.addSpacing(6)

        tag = QLabel('2026  ·  WORLD CHAMPIONSHIP')
        tag.setFont(QFont('Segoe UI', 12))
        tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tag.setStyleSheet('color: #ffffff; letter-spacing: 3px; background: transparent; border: none;')
        root.addWidget(tag)

        root.addStretch(1)

        row = QHBoxLayout()
        row.setSpacing(14)
        row.addStretch(1)
        self._tiles = []
        for i, (key, title, _sub) in enumerate(_MODES):
            tile = ModeTile(key, title, danger=(key == 'exit'))
            tile.clicked.connect(lambda _=False, idx=i: self._activate(idx))
            row.addWidget(tile)
            self._tiles.append(tile)
        row.addStretch(1)
        root.addLayout(row)
        # bottom margin keeps the tile row just above the status-bar overlay
        # (the bar sits at the true window bottom; the page ends ~gap px above it)
        root.setContentsMargins(40, 34, 40, 18)

        # Bottom status bar — a slim black strip parented to the wizard so it
        # spans the full width and sits flush at the true window bottom (over
        # the strip QWizard reserves). Text is centred inside it.
        self._desc = QLabel(self._wiz)
        self._desc.setFont(QFont('Segoe UI', _SBAR_PT))
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
        self._focus_idx = idx % len(self._tiles)
        for i, tile in enumerate(self._tiles):
            tile.set_focused(i == self._focus_idx)
        self._desc.setText(self._subs[self._modes[self._focus_idx]])

    def handle_key(self, key: int) -> bool:
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self._set_focus(self._focus_idx + (-1 if key == Qt.Key.Key_Left else 1))
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
