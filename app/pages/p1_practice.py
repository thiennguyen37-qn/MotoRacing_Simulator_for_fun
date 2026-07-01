from PyQt6.QtWidgets import QWizardPage, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt

from src.simulator import run_practice
from app.wizard import REPORT_ROOT
from app.widgets.table_utils import make_table, fill_table

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
        self._btn.clicked.connect(self._run)
        self._status = QLabel('')
        ctrl.addWidget(self._btn)
        ctrl.addWidget(self._status, 1)
        layout.addLayout(ctrl)

        self._table = make_table(HEADERS)
        layout.addWidget(self._table)

    def initializePage(self):
        wiz = self._wiz
        # Championship: auto-select current circuit from index
        if wiz.mode == 'championship':
            idx = wiz.circuit_index
            wiz.circuit     = wiz.circuits_df.iloc[idx]
            wiz.report_dir  = REPORT_ROOT / wiz.circuit['country']
            wiz.report_dir.mkdir(parents=True, exist_ok=True)
            wiz.practice_results = None
            wiz.grid_all_df      = None
            wiz.race_pts         = []
            n = len(wiz.circuits_df)
            self.setSubTitle(f"Round {idx + 1}/{n}  —  {wiz.circuit['circuit_name']}  ({wiz.circuit['country']})")
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
