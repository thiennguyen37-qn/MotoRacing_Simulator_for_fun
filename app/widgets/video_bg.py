from pathlib import Path
from PyQt6.QtGui import QImage, QPixmap, QPainter
from PyQt6.QtCore import QObject, QUrl, QElapsedTimer, QRectF, pyqtSignal

_IMAGES   = Path(__file__).parent.parent.parent / 'images'
_VIDEO    = _IMAGES / 'homepage.mp4'
_FALLBACK = _IMAGES / 'homepage.jpg'

try:
    from PyQt6.QtMultimedia import QMediaPlayer, QVideoSink
    _OK = True
except ImportError:
    _OK = False


class VideoBackground(QObject):
    """
    Single shared video player for page backgrounds.

    Decodes images/homepage.mp4 once for the whole app; every page paints the
    same current frame. Falls back to images/homepage.jpg when no video exists.
    Frame rate is capped at ~30 fps to keep the UI responsive.
    """

    frame_ready = pyqtSignal()

    _instance = None

    @classmethod
    def instance(cls) -> 'VideoBackground':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        self.image    = QImage()
        self.fallback = QPixmap(str(_FALLBACK)) if _FALLBACK.exists() else QPixmap()

        self._clock = QElapsedTimer()
        self._clock.start()
        self._last_ms = 0

        self._player = None
        if _OK and _VIDEO.exists():
            self._player = QMediaPlayer()
            self._sink = QVideoSink()
            self._player.setVideoSink(self._sink)
            self._player.setSource(QUrl.fromLocalFile(str(_VIDEO)))
            self._player.setLoops(QMediaPlayer.Loops.Infinite)
            self._sink.videoFrameChanged.connect(self._on_frame)
            self._player.play()

    def _on_frame(self, frame) -> None:
        if not frame.isValid():
            return
        now = self._clock.elapsed()
        if now - self._last_ms < 33:      # skip frame before the toImage() copy
            return
        self._last_ms = now
        self.image = frame.toImage()
        self.frame_ready.emit()

    def paint(self, painter: QPainter, widget) -> None:
        """Cover-scale the current frame (or fallback photo) onto widget."""
        if not self.image.isNull():
            iw, ih = self.image.width(), self.image.height()
            scale = max(widget.width() / iw, widget.height() / ih)
            w, h = iw * scale, ih * scale
            x, y = (widget.width() - w) / 2, (widget.height() - h) / 2
            painter.drawImage(QRectF(x, y, w, h), self.image)
            return

        if not self.fallback.isNull():
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            iw, ih = self.fallback.width(), self.fallback.height()
            scale = max(widget.width() / iw, widget.height() / ih)
            w, h = iw * scale, ih * scale
            x, y = (widget.width() - w) / 2, (widget.height() - h) / 2
            painter.drawPixmap(QRectF(x, y, w, h), self.fallback,
                               QRectF(0, 0, iw, ih))
