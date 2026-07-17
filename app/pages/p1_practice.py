from PyQt6.QtWidgets import QWizardPage, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt

from src.simulator import run_practice
from app.widgets.table_utils import make_table, fill_table, SESSION_BTN_SS
from app.wizard import SEASON_MODES

HEADERS = ['P', '#', 'RIDER', 'TEAM', 'MANUFACTURER', 'BEST LAP', 'GAP']


class PracticePage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self._wiz  = wiz
        self._done = False
        self.setTitle('Practice Session')
        self.setSubTitle('Simulate the free practice session.')

        layout = QVBoxLayout(self)

        # Control row
        ctrl = QHBoxLayout()
        self._btn = QPushButton('▶  Run Practice Session')
        self._btn.setFixedHeight(36)
        self._btn.setStyleSheet(SESSION_BTN_SS)
        self._btn.setAutoDefault(False)
        self._btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn.clicked.connect(self._run)
        self._status = QLabel('')
        ctrl.addWidget(self._btn)
        ctrl.addWidget(self._status, 1)
        layout.addLayout(ctrl)

        self._table = make_table(HEADERS)
        layout.addWidget(self._table)

    def handle_key(self, key: int) -> bool:
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            bar = self._table.verticalScrollBar()
            bar.setValue(bar.value() + (bar.singleStep() if key == Qt.Key.Key_Down else -bar.singleStep()))
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._btn.isEnabled():
            self._btn.click()
            return True
        return False    # session done -> global Enter advances the page

    def initializePage(self):
        wiz = self._wiz
        # Championship / Career: auto-select current circuit from index
        if wiz.mode in SEASON_MODES:
            idx = wiz.circuit_index
            season = wiz.season_df if wiz.season_df is not None else wiz.circuits_df
            wiz.circuit     = season.iloc[idx]
            wiz.practice_results = None
            wiz.grid_all_df      = None
            wiz.race_pts         = []
            wiz.race_results     = []
            n = len(season)
            label = 'World Championship' if wiz.mode == 'championship' else 'Career Season'
            self.setSubTitle(f"{wiz.season_year} {label}  ·  "
                             f"Round {idx + 1}/{n}  —  {wiz.circuit['circuit_name']}  ({wiz.circuit['country']})")
        else:
            self.setSubTitle('Simulate the free practice session.')

        self._done = False
        self._btn.setEnabled(True)
        self._btn.setText('▶  Run Practice Session')
        self._status.setText('')
        self._table.setRowCount(0)
        self.completeChanged.emit()

    def _run(self):
        self._btn.setEnabled(False)
        self._status.setText('Simulating…')
        QWizardPage.update(self)

        c = self._wiz.circuit
        res = run_practice(self._wiz.df, c)
        self._wiz.practice_results = res

        rows = []
        for pos, row in res.iterrows():
            rows.append([
                f'P{pos}', f"#{row['bike_number']}",
                row['name'], row['team'], row['manufacturer'],
                row['best_lap'], row['gap_fmt'],
            ])
        fill_table(self._table, rows)

        self._status.setText(
            f"✓  P1: {res.iloc[0]['name']}  —  {res.iloc[0]['best_lap']}"
        )
        self._done = True
        self.completeChanged.emit()

    def isComplete(self):
        return self._done
