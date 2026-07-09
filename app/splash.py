from pathlib import Path
from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtGui import QFont, QColor, QPainter, QBrush, QPen, QPixmap, QLinearGradient
from PyQt6.QtCore import (Qt, QPropertyAnimation, QEasingCurve, QRectF, QTimer,
                           pyqtSignal, pyqtProperty)

_IMAGES = Path(__file__).parent.parent / 'images'
# dedicated wallpaper wins; falls back to the homepage photo until one is added
_WALL = next((p for p in (_IMAGES / 'splash.jpg', _IMAGES / 'splash.png',
                          _IMAGES / 'homepage.jpg') if p.exists()), None)


class SplashScreen(QWidget):
    """Full-screen loading screen: wallpaper + a progress bar that fills as the
    app initialises, then fades out into the home page."""

    finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setWindowTitle('MotoRacing Simulator')
        self.setGeometry(QApplication.primaryScreen().geometry())   # full screen

        self._wall = QPixmap(str(_WALL)) if _WALL else QPixmap()
        self._target  = 0.0     # real progress 0..1
        self._display = 0.0     # animated value the bar actually draws
        self._label   = 'Loading…'
        self._done    = False

        self._bar_anim = QPropertyAnimation(self, b'display')
        self._bar_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    # ── animated bar value ─────────────────────────────────────────────────────

    def _get_display(self) -> float:
        return self._display

    def _set_display(self, v: float):
        self._display = v
        self.update()

    display = pyqtProperty(float, _get_display, _set_display)

    # ── public API ─────────────────────────────────────────────────────────────

    def set_progress(self, frac: float, label: str = ''):
        # Called from the (blocking) synchronous page build, so paint the new
        # value immediately with repaint() rather than waiting on the event
        # loop — and never run processEvents here (that would re-enter the
        # half-built video/map widgets and crash).
        self._display = max(0.0, min(1.0, float(frac)))
        if label:
            self._label = label
        self.repaint()

    def complete(self):
        """Fill to 100%, hold briefly, then fade out and emit `finished`."""
        if self._done:
            return
        self._done = True
        self._label = 'Ready'
        self._bar_anim.stop()
        self._bar_anim.setStartValue(self._display)
        self._bar_anim.setEndValue(1.0)
        self._bar_anim.setDuration(320)
        self._bar_anim.finished.connect(lambda: QTimer.singleShot(360, self._fade_out))
        self._bar_anim.start()

    def _fade_out(self):
        a = QPropertyAnimation(self, b'windowOpacity', self)
        a.setDuration(420)
        a.setStartValue(1.0)
        a.setEndValue(0.0)
        a.setEasingCurve(QEasingCurve.Type.InCubic)
        a.finished.connect(self._on_done)
        self._fade = a
        a.start()

    def _on_done(self):
        self.hide()
        self.finished.emit()

    # ── paint ──────────────────────────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        # wallpaper, cover-scaled
        if not self._wall.isNull():
            iw, ih = self._wall.width(), self._wall.height()
            scale = max(W / iw, H / ih)
            w, h = iw * scale, ih * scale
            p.drawPixmap(QRectF((W - w) / 2, (H - h) / 2, w, h), self._wall,
                         QRectF(0, 0, iw, ih))
        else:
            p.fillRect(self.rect(), QColor(8, 8, 14))

        # darkening overlay — heavier toward the bottom where the bar sits
        grad = QLinearGradient(0, 0, 0, H)
        grad.setColorAt(0.0, QColor(6, 6, 12, 150))
        grad.setColorAt(0.55, QColor(6, 6, 12, 120))
        grad.setColorAt(1.0, QColor(4, 4, 10, 230))
        p.fillRect(self.rect(), QBrush(grad))

        # title
        cx = W / 2
        p.setPen(QColor(240, 240, 248))
        p.setFont(QFont('Segoe UI', 40, QFont.Weight.Bold))
        title_rect = QRectF(0, H * 0.5 - 90, W, 60)
        p.drawText(title_rect, Qt.AlignmentFlag.AlignCenter, 'MotoRacing Simulator')

        p.setPen(QColor(200, 60, 80))
        f = QFont('Segoe UI', 12, QFont.Weight.Bold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4)
        p.setFont(f)
        p.drawText(QRectF(0, H * 0.5 - 24, W, 24),
                   Qt.AlignmentFlag.AlignCenter, 'WORLD CHAMPIONSHIP')

        # progress bar
        bar_w = min(560, W * 0.42)
        bar_h = 6
        bx, by = cx - bar_w / 2, H * 0.78
        track = QRectF(bx, by, bar_w, bar_h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 30))
        p.drawRoundedRect(track, 3, 3)
        fill_w = max(0.0, bar_w * self._display)
        if fill_w > 0:
            p.setBrush(QColor(224, 40, 64))
            p.drawRoundedRect(QRectF(bx, by, fill_w, bar_h), 3, 3)

        # label + percentage
        pct = int(round(self._display * 100))
        p.setPen(QColor(180, 180, 195))
        lf = QFont('Segoe UI', 9)
        lf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        p.setFont(lf)
        p.drawText(QRectF(bx, by + 14, bar_w, 20),
                   Qt.AlignmentFlag.AlignLeft, self._label.upper())
        p.drawText(QRectF(bx, by + 14, bar_w, 20),
                   Qt.AlignmentFlag.AlignRight, f'{pct}%')
