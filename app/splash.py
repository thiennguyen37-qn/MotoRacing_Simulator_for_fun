from PyQt6.QtWidgets import QWidget, QLabel, QFrame, QApplication, QGraphicsOpacityEffect
from PyQt6.QtGui import QFont, QColor, QPainter, QBrush
from PyQt6.QtCore import (Qt, QPropertyAnimation, QSequentialAnimationGroup,
                           QParallelAnimationGroup, QRect, QEasingCurve, pyqtSignal)

W, H = 860, 480


def _opacity_anim(effect, duration, start, end, curve=QEasingCurve.Type.OutCubic):
    a = QPropertyAnimation(effect, b'opacity')
    a.setDuration(duration)
    a.setStartValue(float(start))
    a.setEndValue(float(end))
    a.setEasingCurve(curve)
    return a


def _geom_anim(widget, duration, start: QRect, end: QRect, curve=QEasingCurve.Type.OutCubic):
    a = QPropertyAnimation(widget, b'geometry')
    a.setDuration(duration)
    a.setStartValue(start)
    a.setEndValue(end)
    a.setEasingCurve(curve)
    return a


class SplashScreen(QWidget):
    finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(W, H)

        geo = QApplication.primaryScreen().availableGeometry()
        self.move(geo.center().x() - W // 2, geo.center().y() - H // 2)

        # Background
        bg = QFrame(self)
        bg.setGeometry(0, 0, W, H)
        bg.setStyleSheet('background-color: #08080e; border-radius: 14px;')

        # Top / bottom accent bars
        QFrame(self).setGeometry(0, 0, W, 4)
        self.findChildren(QFrame)[-1].setStyleSheet(
            'background: qlineargradient(x1:0,y1:0,x2:1,y2:0,'
            'stop:0 transparent, stop:0.2 #e02840, stop:0.8 #e02840, stop:1 transparent);'
        )
        QFrame(self).setGeometry(0, H - 4, W, 4)
        self.findChildren(QFrame)[-1].setStyleSheet(
            'background: qlineargradient(x1:0,y1:0,x2:1,y2:0,'
            'stop:0 transparent, stop:0.2 #e02840, stop:0.8 #e02840, stop:1 transparent);'
        )

        # Icon
        self._icon = QLabel('🏁', self)
        self._icon.setFont(QFont('Segoe UI Emoji', 54))
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setGeometry(W // 2 - 64, 130, 128, 96)

        # Title
        self._title = QLabel('MotoRacing Simulator', self)
        f = QFont('Segoe UI', 28, QFont.Weight.Bold)
        self._title.setFont(f)
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setStyleSheet('color: #f0f0f8;')
        self._title.setGeometry(60, 244, W - 120, 58)

        # Accent line (width starts 0, expands from center)
        self._line = QFrame(self)
        self._line.setGeometry(W // 2, 312, 0, 3)
        self._line.setStyleSheet('background: #e02840; border-radius: 1px;')

        # Subtitle
        self._sub = QLabel('W O R L D   C H A M P I O N S H I P   S E A S O N   2 0 2 6', self)
        self._sub.setFont(QFont('Segoe UI', 8))
        self._sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub.setStyleSheet('color: #666;')
        self._sub.setGeometry(60, 326, W - 120, 24)



        # Opacity effects (all start invisible)
        self._eff = {}
        for key, widget in [('icon', self._icon), ('title', self._title),
                             ('sub',  self._sub)]:
            eff = QGraphicsOpacityEffect()
            eff.setOpacity(0.0)
            widget.setGraphicsEffect(eff)
            self._eff[key] = eff

        self.setWindowOpacity(1.0)

    # ── Custom background paint (needed for transparency + rounded corners) ──

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(QColor(8, 8, 14)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(self.rect(), 14, 14)

    # ── Animation ─────────────────────────────────────────────────────────────

    def start(self):
        e = self._eff
        seq = QSequentialAnimationGroup(self)

        # 1. Icon: fade + slide up
        p1 = QParallelAnimationGroup()
        p1.addAnimation(_opacity_anim(e['icon'], 620, 0, 1))
        p1.addAnimation(_geom_anim(self._icon, 620,
                                   QRect(W//2-64, 150, 128, 96),
                                   QRect(W//2-64, 130, 128, 96)))
        seq.addAnimation(p1)

        # 2. Title: fade + slide up
        p2 = QParallelAnimationGroup()
        p2.addAnimation(_opacity_anim(e['title'], 560, 0, 1))
        p2.addAnimation(_geom_anim(self._title, 560,
                                   QRect(60, 268, W-120, 58),
                                   QRect(60, 244, W-120, 58)))
        seq.addAnimation(p2)

        # 3. Accent line expands from center
        line_w = 340
        a_line = QPropertyAnimation(self._line, b'geometry')
        a_line.setDuration(380)
        a_line.setStartValue(QRect(W//2, 312, 0, 3))
        a_line.setEndValue(QRect(W//2 - line_w//2, 312, line_w, 3))
        a_line.setEasingCurve(QEasingCurve.Type.OutCubic)
        seq.addAnimation(a_line)

        # 4. Subtitle
        seq.addAnimation(_opacity_anim(e['sub'], 380, 0, 1))

        # 5. Tagline + version

        # 6. Hold
        seq.addPause(1800)

        # 7. Fade out entire window
        a_out = QPropertyAnimation(self, b'windowOpacity')
        a_out.setDuration(380)
        a_out.setStartValue(1.0)
        a_out.setEndValue(0.0)
        a_out.setEasingCurve(QEasingCurve.Type.InCubic)
        seq.addAnimation(a_out)

        seq.finished.connect(self._on_done)
        self._seq = seq
        seq.start()

    def _on_done(self):
        self.hide()
        self.finished.emit()
