from pathlib import Path
from PyQt6.QtWidgets import QWizard, QApplication, QDialog, QWidget
from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtCore import Qt, QEvent, QTimer

from src.loader import load_riders, load_circuits
from app.audio import AudioManager
from app.widgets.now_playing import NowPlayingToast
from app.widgets.video_bg import VideoBackground

PROJECT_ROOT = Path(__file__).parent.parent
RAW          = PROJECT_ROOT / 'data' / 'raw'


class _GapFiller(QWidget):
    """
    Fills the strip QWizard reserves below the page for its (hidden) button
    row. Full-bleed video pages (Home/Gallery/Soundtrack, identified by their
    `_vbg` attribute) get the same video continued seamlessly into the strip —
    see VideoBackground.paint. Other pages just get a plain dark fill.
    """

    def __init__(self, wizard: 'MotoWizard'):
        super().__init__(wizard)
        self._wizard = wizard
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        page = self._wizard.currentPage()
        vbg = getattr(page, '_vbg', None)
        if vbg is not None:
            offset = self.mapTo(self._wizard, self.rect().topLeft())
            vbg.paint(p, self, full_size=self._wizard.size(), offset=offset)
        overlay = getattr(page, 'paint_gap_overlay', None)
        if overlay is not None:
            overlay(p, self.rect())


class MotoWizard(QWizard):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('MotoRacing Simulator')
        self.setMinimumSize(1060, 680)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowSystemMenuHint |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint |
            Qt.WindowType.WindowCloseButtonHint
        )

        # Data
        self.df          = load_riders(RAW)
        self.circuits_df = load_circuits(RAW)

        # Mode state
        self.mode          = None        # 'random' | 'championship' | 'gallery' | 'soundtrack'
        self.circuit_index = 0
        self.all_race_pts  = []

        # Per-circuit state (reset each circuit)
        self.circuit          = None
        self.practice_results = None
        self.grid_all_df      = None
        self.race_pts         = []

        # Audio — created before pages so SoundtrackPage can receive the reference
        self._audio = AudioManager()
        self._toast = NowPlayingToast(self)
        if hasattr(self._audio, 'track_changed'):
            self._audio.track_changed.connect(self._toast.show_track)

        # Pages — IDs are assigned in addPage order
        from app.pages.p_home          import HomePage
        from app.pages.p0_circuit      import CircuitPage
        from app.pages.p1_practice     import PracticePage
        from app.pages.p2_qualifying   import QualifyingPage
        from app.pages.p3_race         import RacePage
        from app.pages.p4_championship import ChampionshipPage
        from app.pages.p_gallery       import GalleryPage
        from app.pages.p_soundtrack    import SoundtrackPage

        self.ID_HOME       = self.addPage(HomePage(self))
        self.ID_CIRCUIT    = self.addPage(CircuitPage(self))
        self.ID_PRACTICE   = self.addPage(PracticePage(self))
        self.ID_QUALI      = self.addPage(QualifyingPage(self))
        self.ID_RACE       = self.addPage(RacePage(self))
        self.ID_STANDINGS  = self.addPage(ChampionshipPage(self))
        self.ID_GALLERY    = self.addPage(GalleryPage(self))
        self.ID_SOUNDTRACK = self.addPage(SoundtrackPage(self, self._audio))

        self.setOption(QWizard.WizardOption.IndependentPages)

        self.setButtonText(QWizard.WizardButton.NextButton,   'Continue →')
        self.setButtonText(QWizard.WizardButton.FinishButton, 'Finish')
        self.setButtonText(QWizard.WizardButton.BackButton,   '← Back')
        self.setButtonText(QWizard.WizardButton.CancelButton, 'Exit')

        self.setMaximumSize(16_777_215, 16_777_215)

        # QWizard reserves a strip at the bottom for its button row — even with
        # setButtonLayout([]) the row stays 0-height but the space (and its
        # lighter default background) remains, showing as a stray gray bar.
        # This app never shows wizard buttons (fully keyboard-driven), so this
        # continues the current page's own background into that strip instead.
        self._gap_filler = _GapFiller(self)
        VideoBackground.instance().frame_ready.connect(self._gap_filler.update)

        self.currentIdChanged.connect(self._on_page_changed)
        self._on_page_changed(self.ID_HOME)

        self.setCursor(Qt.CursorShape.BlankCursor)
        QApplication.instance().installEventFilter(self)

        self._audio_started = False

    def showEvent(self, event):
        super().showEvent(event)
        if not self._audio_started:
            self._audio_started = True
            self._audio.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._sync_gap_filler)

    def _sync_gap_filler(self):
        page = self.currentPage()
        if page is None:
            self._gap_filler.hide()
            return
        # page.geometry() is in its parent's coordinates; on pages with a
        # title, QWizard's header banner sits above that parent, so map the
        # page bottom into wizard coordinates to place the filler correctly.
        y = page.mapTo(self, page.rect().bottomLeft()).y() + 1
        h = self.height() - y
        if h <= 0:
            self._gap_filler.hide()
            return
        self._gap_filler.setGeometry(0, y, self.width(), h)
        self._gap_filler.show()
        self._gap_filler.raise_()
        self._toast.raise_()   # keep the now-playing toast above the gap filler

    def reject(self):
        pass  # prevent Escape from closing the wizard

    def accept(self):
        if self.mode == 'random':
            self.restart()
            self.page(self.ID_HOME).initializePage()
        else:
            super().accept()

    def eventFilter(self, obj, event):
        # keep the gap filler glued to the page bottom whenever QWizard
        # relayouts the page (maximize, header appearing, etc.)
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Move) and obj is self.currentPage():
            self._sync_gap_filler()

        if event.type() in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.MouseMove,
            QEvent.Type.Wheel,
        ):
            return True
        if event.type() == QEvent.Type.KeyPress and self.isActiveWindow():
            page = self.currentPage()
            k = event.key()

            if k == Qt.Key.Key_M:
                self._audio.toggle_mute()
                return True

            if hasattr(page, 'handle_key') and page.handle_key(k):
                if k in (Qt.Key.Key_Up, Qt.Key.Key_Down,
                         Qt.Key.Key_Left, Qt.Key.Key_Right):
                    self._audio.play_sfx('navigate')
                elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter,
                            Qt.Key.Key_Space):
                    self._audio.play_sfx('select')
                elif k in (Qt.Key.Key_Escape, Qt.Key.Key_Backspace):
                    self._audio.play_sfx('back')
                return True

            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if page and page.isComplete():
                    self._audio.play_sfx('select')
                    if page.nextId() == -1:
                        self.accept()
                    else:
                        self.next()
                    return True
            elif k in (Qt.Key.Key_Backspace, Qt.Key.Key_Escape):
                if self.currentId() != self.startId():
                    self._audio.play_sfx('back')
                    self.back()
                    return True
        return False

    def closeEvent(self, event):
        from app.pages.p_home import ExitDialog
        if ExitDialog(self).exec() == QDialog.DialogCode.Accepted:
            event.accept()
        else:
            event.ignore()

    def _on_page_changed(self, page_id):
        self.setButtonLayout([])
        QTimer.singleShot(0, self._sync_gap_filler)
