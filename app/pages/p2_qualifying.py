from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout,
                              QPushButton, QLabel, QTabWidget, QWidget)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt

from src.simulator import run_qualifying
from app.widgets.table_utils import make_table, fill_table

HEADERS_Q  = ['P', '#', 'RIDER', 'TEAM', 'MANUFACTURER', 'BEST LAP', 'GAP']
HEADERS_GR = ['GRID', '#', 'RIDER', 'TEAM', 'MANUFACTURER', 'BEST LAP']


class QualifyingPage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self._wiz     = wiz
        self._q1_done = False
        self._q2_done = False
        self.setTitle('Qualifying Session')
        self.setSubTitle('Q1 → top 2 advance to Q2. Q2 sets the starting grid (P1–P12).')

        layout = QVBoxLayout(self)

        # Buttons row
        ctrl = QHBoxLayout()
        self._btn_q1 = QPushButton('▶  Run Q1')
        self._btn_q1.setFixedHeight(34)
        self._btn_q1.clicked.connect(self._run_q1)
        self._btn_q2 = QPushButton('▶  Run Q2')
        self._btn_q2.setFixedHeight(34)
        self._btn_q2.setEnabled(False)
        self._btn_q2.clicked.connect(self._run_q2)
        self._status = QLabel('')
        ctrl.addWidget(self._btn_q1)
        ctrl.addWidget(self._btn_q2)
        ctrl.addWidget(self._status, 1)
        layout.addLayout(ctrl)

        # Tab widget
        self._tabs = QTabWidget()
        self._t_q1 = make_table(HEADERS_Q)
        self._t_q2 = make_table(HEADERS_Q)
        self._t_gr = make_table(HEADERS_GR)
        self._tabs.addTab(self._t_q1, 'Q1')
        self._tabs.addTab(self._t_q2, 'Q2')
        self._tabs.addTab(self._t_gr, 'Starting Grid')
        layout.addWidget(self._tabs)

        # Saved results for downstream use
        self._q1_class = None
        self._q2_class = None
        self._q2_advance = None
        self._q1_nq = None

    def initializePage(self):
        self._q1_done = False
        self._q2_done = False
        self._btn_q1.setEnabled(True)
        self._btn_q1.setText('▶  Run Q1')
        self._btn_q2.setEnabled(False)
        self._btn_q2.setText('▶  Run Q2')
        self._status.setText('')
        for t in (self._t_q1, self._t_q2, self._t_gr):
            t.setRowCount(0)
        self._wiz.grid_all_df = None
        self.completeChanged.emit()

    def _run_q1(self):
        self._btn_q1.setEnabled(False)
        self._status.setText('Running Q1…')
        q1, q2, adv, nq, grid = run_qualifying(
            self._wiz.df, self._wiz.circuit, self._wiz.practice_results
        )
        self._q1_class   = q1
        self._q2_class   = q2
        self._q2_advance = adv
        self._q1_nq      = nq

        rows = []
        for pos, row in q1.iterrows():
            adv_tag = '★' if row['name'] in adv else ''
            rows.append([f'P{pos}', f"#{row['bike_number']}", row['name'],
                         row['team'], row['manufacturer'],
                         row['best_lap'], row['gap_fmt'] + (' ' + adv_tag if adv_tag else '')])
        fill_table(self._t_q1, rows)

        self._q1_done = True
        self._btn_q2.setEnabled(True)
        self._status.setText(f"Q1 done. Advancing: {', '.join(adv)}")
        self._tabs.setCurrentIndex(0)

    def _run_q2(self):
        self._btn_q2.setEnabled(False)
        self._status.setText('Running Q2…')

        q2   = self._q2_class
        nq   = self._q1_nq
        adv  = self._q2_advance

        # Q2 table
        rows = []
        for pos, row in q2.iterrows():
            pole = ' ◀ POLE' if pos == 1 else ''
            rows.append([f'P{pos}', f"#{row['bike_number']}", row['name'] + pole,
                         row['team'], row['manufacturer'], row['best_lap'], row['gap_fmt']])
        fill_table(self._t_q2, rows)

        # Grid table (Q2 P1-P12 then Q1 NQ P13-P24)
        grid_rows = []
        for pos, row in q2.iterrows():
            grid_rows.append([f'P{pos}', f"#{row['bike_number']}", row['name'],
                               row['team'], row['manufacturer'], row['best_lap']])
        for pos, row in nq.iterrows():
            grid_rows.append([f'P{pos}', f"#{row['bike_number']}", row['name'],
                               row['team'], row['manufacturer'], row['best_lap']])
        fill_table(self._t_gr, grid_rows)

        # Build grid_all_df for race notebook
        import pandas as pd
        grid_all = pd.concat([q2, nq]).reset_index(drop=True)
        grid_all['grid_pos'] = range(1, len(grid_all) + 1)
        self._wiz.grid_all_df = grid_all

        self._q2_done = True
        pole = q2.iloc[0]['name']
        self._status.setText(f"✓  POLE: {pole}  —  {q2.iloc[0]['best_lap']}")
        self._tabs.setCurrentIndex(2)
        self.completeChanged.emit()

    def isComplete(self):
        return self._q2_done
