from pathlib import Path
from PyQt6.QtWidgets import QWizard, QApplication, QDialog
from PyQt6.QtCore import Qt, QEvent

from src.loader import load_riders, load_circuits

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
        self.mode          = None        # 'random' | 'championship'
        self.circuit_index = 0
        self.all_race_pts  = []          # cumulative pts across championship circuits

        # Per-circuit state (reset each circuit)
        self.circuit          = None
        self.report_dir       = None
        self.practice_results = None
        self.grid_all_df      = None
        self.race_pts         = []

        # Pages — IDs are assigned in addPage order
        from app.pages.p_home          import HomePage
        from app.pages.p0_circuit      import CircuitPage
        from app.pages.p1_practice     import PracticePage
        from app.pages.p2_qualifying   import QualifyingPage
        from app.pages.p3_race         import RacePage
        from app.pages.p4_championship import ChampionshipPage
        from app.pages.p_gallery       import GalleryPage

        self.ID_HOME      = self.addPage(HomePage(self))
        self.ID_CIRCUIT   = self.addPage(CircuitPage(self))
        self.ID_PRACTICE  = self.addPage(PracticePage(self))
        self.ID_QUALI     = self.addPage(QualifyingPage(self))
        self.ID_RACE      = self.addPage(RacePage(self))
        self.ID_STANDINGS = self.addPage(ChampionshipPage(self))
        self.ID_GALLERY   = self.addPage(GalleryPage(self))

        # initializePage() called every time a page is entered (needed for championship loop)
        self.setOption(QWizard.WizardOption.IndependentPages)

        self.setButtonText(QWizard.WizardButton.NextButton,   'Continue →')
        self.setButtonText(QWizard.WizardButton.FinishButton, 'Finish')
        self.setButtonText(QWizard.WizardButton.BackButton,   '← Back')
        self.setButtonText(QWizard.WizardButton.CancelButton, 'Exit')

        # Allow window to be resized / maximized
        self.setMaximumSize(16_777_215, 16_777_215)

        # Hide Back button on homepage, show on all other pages
        self.currentIdChanged.connect(self._on_page_changed)
        self._on_page_changed(self.ID_HOME)   # currentIdChanged doesn't fire on startup

        self.setCursor(Qt.CursorShape.BlankCursor)
        QApplication.instance().installEventFilter(self)

    def reject(self):
        pass  # prevent Escape from closing the wizard

    def accept(self):
        if self.mode == 'random':
            # Finish in Random Race → go back to homepage, not exit
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
            if hasattr(page, 'handle_key') and page.handle_key(event.key()):
                return True
            k = event.key()
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if page and page.isComplete():
                    if page.nextId() == -1:
                        self.accept()
                    else:
                        self.next()
                    return True
            elif k in (Qt.Key.Key_Backspace, Qt.Key.Key_Escape):
                if self.currentId() != self.startId():
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
