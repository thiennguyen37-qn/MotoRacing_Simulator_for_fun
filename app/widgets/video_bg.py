from pathlib import Path
from PyQt6.QtGui import QImage, QPixmap, QPainter
from PyQt6.QtCore import QObject, QUrl, QElapsedTimer, QRectF, Qt, pyqtSignal

_IMAGES   = Path(__file__).parent.parent.parent / 'images'
_VIDEO    = _IMAGES / 'homepage.mp4'
_FALLBACK = _IMAGES / 'homepage.jpg'

_FRAME_MS = 40      # ~25 fps cap for the background (lower = lighter; was ~30 fps)

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

    Each frame is cover-scaled to the target size at most once (cached as a
    QPixmap) so repaints are cheap blits instead of rescaling a full-res frame
    every time — the key to staying smooth with 1080p sources.
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

        # cover-scaled cache: scale each frame once per size, then just blit it
        self._frame_id   = 0
        self._scaled     = QPixmap()
        self._scaled_key = None       # (frame_id, width, height)

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
        if now - self._last_ms < _FRAME_MS:   # skip frame before the toImage() copy
            return
        self._last_ms = now
        self.image = frame.toImage()
        self._frame_id += 1
        self.frame_ready.emit()

    def paint(self, painter: QPainter, widget) -> None:
        """Cover-scale the current frame (or fallback photo) onto widget."""
        W, H = widget.width(), widget.height()
        if W <= 0 or H <= 0:
            return

        if not self.image.isNull():
            key = (self._frame_id, W, H)
            if key != self._scaled_key or self._scaled.isNull():
                # Scale the full-res frame down once (cover), then reuse the
                # pixmap for every repaint at this size — cheap on the CPU.
                scaled = self.image.scaled(
                    W, H,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.FastTransformation,
                )
                self._scaled     = QPixmap.fromImage(scaled)
                self._scaled_key = key
            pm = self._scaled
            painter.drawPixmap((W - pm.width()) // 2, (H - pm.height()) // 2, pm)
            return

        if not self.fallback.isNull():
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            iw, ih = self.fallback.width(), self.fallback.height()
            scale = max(widget.width() / iw, widget.height() / ih)
            w, h = iw * scale, ih * scale
            x, y = (widget.width() - w) / 2, (widget.height() - h) / 2
            painter.drawPixmap(QRectF(x, y, w, h), self.fallback,
                               QRectF(0, 0, iw, ih))
