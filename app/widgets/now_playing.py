from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel,
                              QGraphicsOpacityEffect)
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QEvent
from PyQt6.QtGui import QPainter, QColor, QFont, QFontMetrics

_MARGIN  = 24   # distance from window edges
_HOLD_MS = 3000


class NowPlayingToast(QWidget):
    """Pill-shaped toast that shows track title/artist for 3 s then fades out."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedWidth(300)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 12, 26, 12)
        lay.setSpacing(14)
        lay.addStretch(1)

        note = QLabel('♪')
        note.setFont(QFont('Segoe UI', 15))
        note.setStyleSheet('color: #e02840; background: transparent; border: none;')
        note.setSizePolicy(note.sizePolicy().horizontalPolicy(),
                           note.sizePolicy().verticalPolicy())
        lay.addWidget(note)

        texts = QVBoxLayout()
        texts.setSpacing(2)

        self._title_lbl = QLabel()
        self._title_lbl.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
        self._title_lbl.setStyleSheet('color: #ffffff; background: transparent; border: none;')
        self._title_lbl.setMaximumWidth(210)
        texts.addWidget(self._title_lbl, 0, Qt.AlignmentFlag.AlignLeft)

        self._artist_lbl = QLabel()
        self._artist_lbl.setFont(QFont('Segoe UI', 9))
        self._artist_lbl.setStyleSheet('color: #aaaaaa; background: transparent; border: none;')
        self._artist_lbl.setMaximumWidth(210)
        texts.addWidget(self._artist_lbl, 0, Qt.AlignmentFlag.AlignLeft)

        lay.addLayout(texts)
        lay.addStretch(1)

        # ── Opacity animation ─────────────────────────────────────────────────
        self._fx = QGraphicsOpacityEffect(self)
        self._fx.setOpacity(0.0)
        self.setGraphicsEffect(self._fx)

        self._anim_in = QPropertyAnimation(self._fx, b'opacity', self)
        self._anim_in.setDuration(300)
        self._anim_in.setStartValue(0.0)
        self._anim_in.setEndValue(1.0)
        self._anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._anim_out = QPropertyAnimation(self._fx, b'opacity', self)
        self._anim_out.setDuration(600)
        self._anim_out.setStartValue(1.0)
        self._anim_out.setEndValue(0.0)
        self._anim_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._anim_out.finished.connect(self.hide)

        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self._anim_out.start)

        # watch parent resize to keep position correct
        parent.installEventFilter(self)
        self.hide()

    # ── Public ────────────────────────────────────────────────────────────────

    @staticmethod
    def _elide(text: str, font: QFont, max_px: int) -> str:
        return QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, max_px)

    def show_track(self, title: str, artist: str) -> None:
        self._title_lbl.setText(self._elide(title,  self._title_lbl.font(),  210))
        self._artist_lbl.setText(self._elide(artist, self._artist_lbl.font(), 210))
        self._artist_lbl.setVisible(bool(artist))
        self.layout().activate()
        self.resize(300, self.sizeHint().height())
        self._reposition()
        self.show()
        self.raise_()
        self._anim_out.stop()
        self._anim_in.start()
        self._hold_timer.start(_HOLD_MS)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _reposition(self) -> None:
        p = self.parent()
        if p is None:
            return
        x = p.width()  - self.width()  - _MARGIN
        y = p.height() - self.height() - _MARGIN
        self.move(x, y)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.parent() and event.type() == QEvent.Type.Resize:
            if not self.isHidden():
                self._reposition()
        return False

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.setBrush(QColor(12, 12, 20, 225))
        p.setPen(QColor(55, 55, 75))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
