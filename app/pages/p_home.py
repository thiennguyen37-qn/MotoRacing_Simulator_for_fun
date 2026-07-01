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

        btn_cancel = QPushButton('Cancel')
        btn_cancel.setFixedHeight(38)
        btn_cancel.setFont(QFont('Segoe UI', 10))
        btn_cancel.setStyleSheet(
            'QPushButton { background: #1e1e2a; color: #aaa; border: 1px solid #333; border-radius: 6px; }'
            'QPushButton:hover { background: #2a2a3a; color: #fff; }'
        )
        btn_cancel.clicked.connect(self.reject)

        btn_yes = QPushButton('Yes, Exit')
        btn_yes.setFixedHeight(38)
        btn_yes.setFont(QFont('Segoe UI', 10, QFont.Weight.Bold))
        btn_yes.setStyleSheet(
            'QPushButton { background: #e02840; color: #fff; border: none; border-radius: 6px; }'
            'QPushButton:hover { background: #ff3050; }'
            'QPushButton:pressed { background: #b01e30; }'
        )
        btn_yes.clicked.connect(self.accept)

        btns.addWidget(btn_cancel)
        btns.addWidget(btn_yes)
        cl.addLayout(btns)
        root.addWidget(card)

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
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._selected = False
        self._danger   = danger
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

    def enterEvent(self, e):
        if not self._selected:
            self._apply(False, True)
            accent_col = '#e02840' if self._danger else '#882020'
            self._accent.setStyleSheet(f'background: {accent_col}; border-radius: 2px;')
        super().enterEvent(e)

    def leaveEvent(self, e):
        if not self._selected:
            self._apply(False, False)
            self._accent.setStyleSheet('background: #2a2a2a; border-radius: 2px;')
        super().leaveEvent(e)

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

        self._btn_continue = QPushButton('Continue  →')
        self._btn_continue.setFixedHeight(42)
        self._btn_continue.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
        self._btn_continue.setStyleSheet("""
            QPushButton { background-color: #e02840; color: #ffffff; border: none; border-radius: 6px; }
            QPushButton:hover { background-color: #ff3050; }
            QPushButton:pressed { background-color: #b01e30; }
        """)
        self._btn_continue.setVisible(False)
        self._btn_continue.clicked.connect(self._wiz.next)
        pl.addWidget(self._btn_continue)

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
        for bar in (self._bar_r, self._bar_c, self._bar_g, self._bar_x):
            bar.set_selected(False)
        self._btn_continue.setVisible(False)
        self.completeChanged.emit()

    def _select(self, mode):
        self._wiz.mode = mode
        self._bar_r.set_selected(mode == 'random')
        self._bar_c.set_selected(mode == 'championship')
        self._bar_g.set_selected(mode == 'gallery')
        self._bar_x.set_selected(False)
        self._btn_continue.setVisible(True)
        self.completeChanged.emit()

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
