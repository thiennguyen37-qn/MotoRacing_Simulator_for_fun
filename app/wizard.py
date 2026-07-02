from pathlib import Path
from PyQt6.QtWidgets import QWizard, QApplication, QDialog
from PyQt6.QtCore import Qt, QEvent

from src.loader import load_riders, load_circuits
from app.audio import AudioManager
from app.widgets.now_playing import NowPlayingToast

PROJECT_ROOT = Path(__file__).parent.parent
RAW          = PROJECT_ROOT / 'data' / 'raw'
REPORT_ROOT  = PROJECT_ROOT / 'report'


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
        self.report_dir       = None
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

    def reject(self):
        pass  # prevent Escape from closing the wizard

    def accept(self):
        if self.mode == 'random':
            self.restart()
            self.page(self.ID_HOME).initializePage()
        else:
            super().accept()

    def eventFilter(self, obj, event):
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
