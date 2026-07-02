from pathlib import Path
from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout,
                              QLabel, QFrame, QSizePolicy, QApplication,
                              QPushButton, QDialog)
from PyQt6.QtGui import QFont, QPixmap, QPainter, QColor
from PyQt6.QtCore import Qt, pyqtSignal


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


_BG     = Path(__file__).parent.parent.parent / 'images' / 'homepage.jpg'
PANEL_W = 390


# ── Mode bar ──────────────────────────────────────────────────────────────────

class ModeBar(QFrame):
    clicked = pyqtSignal()

    _SS = """
        ModeBar {{
            background-color: {bg};
            border: 1px solid {border};
            border-radius: 6px;
        }}
        ModeBar QLabel {{ background: transparent; border: none; color: {txt}; }}
        ModeBar QFrame {{ background: transparent; border: none; }}
    """

    def __init__(self, title, subtitle, danger=False):
        super().__init__()
        self._selected = False
        self._danger   = danger
        self._focused  = False
        self._apply(False, False)

        col = QVBoxLayout(self)
        col.setContentsMargins(18, 14, 18, 14)
        col.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(0)

        self._accent = QFrame()
        self._accent.setFixedWidth(3)
        self._accent.setMinimumHeight(24)
        self._accent.setStyleSheet('background: #2a2a2a; border-radius: 2px;')
        row.addWidget(self._accent)
        row.addSpacing(14)

        self._ttl = QLabel(title)
        self._ttl.setFont(QFont('Segoe UI', 13, QFont.Weight.Bold))
        row.addWidget(self._ttl, 1)

        col.addLayout(row)

        self._sub = QLabel(subtitle)
        self._sub.setFont(QFont('Segoe UI', 10))
        self._sub.setStyleSheet('color: #888; padding-left: 17px; background: transparent; border: none;')
        self._sub.setVisible(False)
        col.addWidget(self._sub)

    def _apply(self, selected, hover):
        if selected:
            bg, border, txt = 'rgba(224,40,64,35)', '#e02840', '#ffffff'
        elif hover:
            if self._danger:
                bg, border, txt = 'rgba(224,40,64,20)', '#993020', '#ff7766'
            else:
                bg, border, txt = 'rgba(255,255,255,10)', '#555', '#eeeeee'
        else:
            bg, border, txt = 'rgba(255,255,255,4)', '#222', '#aaaaaa'
        self.setStyleSheet(self._SS.format(bg=bg, border=border, txt=txt))

    def set_selected(self, v):
        self._selected = v
        self._apply(v, False)
        self._sub.setVisible(v)
        self._accent.setStyleSheet(
            'background: #e02840; border-radius: 2px;' if v
            else 'background: #2a2a2a; border-radius: 2px;'
        )

    def set_focused(self, v: bool):
        self._focused = v
        if not self._selected:
            if v:
                self.setStyleSheet(self._SS.format(
                    bg='rgba(255,255,255,8)', border='#555566', txt='#ddddee'))
            else:
                self._apply(False, False)
            self._accent.setStyleSheet(
                'background: #e02840; border-radius: 2px;' if v
                else 'background: #2a2a2a; border-radius: 2px;'
            )
        self._sub.setVisible(v or self._selected)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


# ── Page ─────────────────────────────────────────────────────────────────────

class HomePage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self._wiz = wiz
        self.setTitle('')
        self.setSubTitle('')
        self._bg_pixmap = QPixmap(str(_BG)) if _BG.exists() else QPixmap()
        self._bg_cache  = QPixmap()

        # ── Right navigation panel ────────────────────────────────────────────
        main = QHBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        main.addStretch(1)

        panel = QFrame()
        panel.setFixedWidth(PANEL_W)
        panel.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        panel.setStyleSheet('background-color: rgba(0,0,0,215); border: none;')

        pl = QVBoxLayout(panel)
        pl.setContentsMargins(28, 32, 28, 28)
        pl.setSpacing(0)

        ttl = QLabel('MotoRacing\nSimulator')
        ttl.setFont(QFont('Segoe UI', 22, QFont.Weight.Bold))
        ttl.setStyleSheet('color: #ffffff; background: transparent; border: none;')
        pl.addWidget(ttl)
        pl.addSpacing(8)

        tag = QLabel('2026  ·  WORLD CHAMPIONSHIP')
        tag.setFont(QFont('Segoe UI', 11))
        tag.setStyleSheet('color: #666; letter-spacing: 1px; background: transparent; border: none;')
        pl.addWidget(tag)
        pl.addSpacing(18)

        div = QFrame()
        div.setFixedHeight(2)
        div.setStyleSheet('background: #e02840; border: none;')
        pl.addWidget(div)
        pl.addSpacing(28)

        pl.addStretch(1)

        self._bar_r = ModeBar('RANDOM RACE',  'Pick any circuit for a single weekend')
        self._bar_c = ModeBar('CHAMPIONSHIP', 'All 13 rounds — full season')
        self._bar_g = ModeBar('GALLERY',      'Browse rider and team profiles')
        self._bar_x = ModeBar('EXIT',         'Close the application', danger=True)
        self._bars  = [self._bar_r, self._bar_c, self._bar_g, self._bar_x]
        self._modes = ['random', 'championship', 'gallery', 'exit']
        self._focus_idx = 0

        self._bar_r.clicked.connect(lambda: self._select('random'))
        self._bar_c.clicked.connect(lambda: self._select('championship'))
        self._bar_g.clicked.connect(lambda: self._select('gallery'))
        self._bar_x.clicked.connect(self._confirm_exit)

        pl.addWidget(self._bar_r)
        pl.addSpacing(10)
        pl.addWidget(self._bar_c)
        pl.addSpacing(10)
        pl.addWidget(self._bar_g)
        pl.addSpacing(10)
        pl.addWidget(self._bar_x)

        pl.addStretch(1)

        main.addWidget(panel)

    # ── Background image ──────────────────────────────────────────────────────

    def _rescale(self):
        if self._bg_pixmap.isNull() or self.width() < 2 or self.height() < 2:
            return
        dpr = self.devicePixelRatio()
        self._bg_cache = self._bg_pixmap.scaled(
            int(self.width()  * dpr),
            int(self.height() * dpr),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._bg_cache.setDevicePixelRatio(dpr)
        self.update()

    def resizeEvent(self, event):
        self._rescale()
        super().resizeEvent(event)

    def showEvent(self, event):
        self._rescale()
        super().showEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        if not self._bg_cache.isNull():
            dpr = self.devicePixelRatio()
            x   = int((self.width()  - self._bg_cache.width()  / dpr) / 2)
            y   = int((self.height() - self._bg_cache.height() / dpr) / 2)
            p.drawPixmap(x, y, self._bg_cache)

    # ── Logic ─────────────────────────────────────────────────────────────────

    def initializePage(self):
        wiz = self._wiz
        wiz.mode          = None
        wiz.circuit_index = 0
        wiz.all_race_pts  = []
        for bar in self._bars:
            bar.set_selected(False)
            bar.set_focused(False)
        self.completeChanged.emit()
        self._focus_idx = 0
        self._bars[0].set_focused(True)

    def handle_key(self, key: int) -> bool:
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._bars[self._focus_idx].set_focused(False)
            self._focus_idx = (self._focus_idx + (-1 if key == Qt.Key.Key_Up else 1)) % len(self._bars)
            self._bars[self._focus_idx].set_focused(True)
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            mode = self._modes[self._focus_idx]
            if mode == 'exit':
                self._confirm_exit()
            else:
                self._wiz.mode = mode
                self._wiz.next()
            return True
        return False

    def _select(self, mode):
        self._wiz.mode = mode
        self._bar_r.set_selected(mode == 'random')
        self._bar_c.set_selected(mode == 'championship')
        self._bar_g.set_selected(mode == 'gallery')
        self._bar_x.set_selected(False)
        self.completeChanged.emit()
        # sync keyboard focus to the clicked/selected bar
        for b in self._bars:
            b.set_focused(False)
        self._focus_idx = self._modes.index(mode)
        self._bars[self._focus_idx].set_focused(True)

    def _confirm_exit(self):
        if ExitDialog(self).exec() == QDialog.DialogCode.Accepted:
            QApplication.instance().quit()

    def isComplete(self):
        return self._wiz.mode is not None

    def nextId(self):
        if self._wiz.mode == 'championship':
            return self._wiz.ID_PRACTICE
        if self._wiz.mode == 'gallery':
            return self._wiz.ID_GALLERY
        return self._wiz.ID_CIRCUIT
