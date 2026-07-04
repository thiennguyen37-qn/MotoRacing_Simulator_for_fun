from pathlib import Path
from PyQt6.QtGui import QImage, QPixmap, QPainter
from PyQt6.QtCore import QObject, QUrl, QElapsedTimer, QRectF, QSize, QPoint, Qt, pyqtSignal

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

    QWizard reserves a thin strip below every page for its (unused, hidden)
    button row, so a full-bleed page is a few pixels short of the actual
    window. `paint()` optionally takes `full_size`/`offset`: the scale/crop is
    computed against the *window's* size instead of the calling widget's own
    size, and the widget only draws the slice that falls inside its own
    bounds. Every widget that passes the same `full_size` is therefore
    painting a slice of one shared image, so a page and a separate sliver
    widget positioned right below it line up pixel-for-pixel — the video
    reads as continuous instead of being covered by a patch.
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

    def paint(self, painter: QPainter, widget,
              full_size: QSize | None = None, offset: QPoint | None = None) -> None:
        """Cover-scale the current frame (or fallback photo) onto widget.

        By default scales to `widget`'s own size. Pass `full_size` (the
        window's size) and `offset` (widget's top-left within that window) to
        instead scale against the window and draw only this widget's slice —
        see the class docstring.
        """
        W = full_size.width()  if full_size is not None else widget.width()
        H = full_size.height() if full_size is not None else widget.height()
        ox, oy = (offset.x(), offset.y()) if offset is not None else (0, 0)
        if W <= 0 or H <= 0:
            return

        if not self.image.isNull():
            key = (self._frame_id, W, H)
            if key != self._scaled_key or self._scaled.isNull():
                # Scale the full-res frame down once (cover) per window size,
                # then reuse the pixmap for every widget/repaint — cheap blits.
                scaled = self.image.scaled(
                    W, H,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.FastTransformation,
                )
                self._scaled     = QPixmap.fromImage(scaled)
                self._scaled_key = key
            pm = self._scaled
            fx, fy = (W - pm.width()) // 2, (H - pm.height()) // 2
            painter.drawPixmap(fx - ox, fy - oy, pm)
            return

        if not self.fallback.isNull():
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            iw, ih = self.fallback.width(), self.fallback.height()
            scale = max(W / iw, H / ih)
            w, h = iw * scale, ih * scale
            x, y = (W - w) / 2, (H - h) / 2
            painter.drawPixmap(QRectF(x - ox, y - oy, w, h), self.fallback,
                               QRectF(0, 0, iw, ih))
