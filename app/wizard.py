from pathlib import Path
from PyQt6.QtWidgets import QWizard
from PyQt6.QtCore import Qt

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

    def accept(self):
        if self.mode == 'random':
            # Finish in Random Race → go back to homepage, not exit
            self.restart()
            self.page(self.ID_HOME).initializePage()
        else:
            super().accept()

    def _on_page_changed(self, page_id):
        if page_id == self.ID_HOME:
            self.setButtonLayout([])
        elif page_id == self.ID_GALLERY:
            self.setButtonLayout([
                QWizard.WizardButton.BackButton,
                QWizard.WizardButton.Stretch,
                QWizard.WizardButton.CancelButton,
            ])
        else:
            self.setButtonLayout([
                QWizard.WizardButton.BackButton,
                QWizard.WizardButton.Stretch,
                QWizard.WizardButton.CancelButton,
                QWizard.WizardButton.NextButton,
                QWizard.WizardButton.FinishButton,
            ])
