from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout,
                              QPushButton, QLabel, QTabWidget, QWidget)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt

from src.simulator import run_qualifying
from app.widgets.table_utils import (make_table, fill_table,
                                      SESSION_BTN_SS, SESSION_TABS_SS)

HEADERS_Q  = ['P', '#', 'RIDER', 'TEAM', 'MANUFACTURER', 'BEST LAP', 'GAP']
HEADERS_GR = ['GRID', '#', 'RIDER', 'TEAM', 'MANUFACTURER', 'BEST LAP']


class QualifyingPage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self._wiz     = wiz
        self._q1_done = False
        self._q2_done = False
        # Career runs Q1 and Q2 as two separate hub excursions; True once the
        # session for the *current* excursion is done, so Enter returns to the
        # hub instead of running the other session.
        self._career_session_done = False
        self.setTitle('Qualifying Session')
        self.setSubTitle('Q1 → top 2 advance to Q2. Q2 sets the starting grid (P1–P12).')

        layout = QVBoxLayout(self)

        # Buttons row
        ctrl = QHBoxLayout()
        self._btn_q1 = QPushButton('▶  Run Q1')
        self._btn_q1.setFixedHeight(34)
        self._btn_q1.setStyleSheet(SESSION_BTN_SS)
        self._btn_q1.setAutoDefault(False)
        self._btn_q1.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_q1.clicked.connect(self._run_q1)
        self._btn_q2 = QPushButton('▶  Run Q2')
        self._btn_q2.setFixedHeight(34)
        self._btn_q2.setStyleSheet(SESSION_BTN_SS)
        self._btn_q2.setAutoDefault(False)
        self._btn_q2.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_q2.setEnabled(False)
        self._btn_q2.clicked.connect(self._run_q2)
        self._status = QLabel('')
        ctrl.addWidget(self._btn_q1)
        ctrl.addWidget(self._btn_q2)
        ctrl.addWidget(self._status, 1)
        layout.addLayout(ctrl)

        # Tab widget
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(SESSION_TABS_SS)
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

    def handle_key(self, key: int) -> bool:
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            bar = self._tabs.currentWidget().verticalScrollBar()
            bar.setValue(bar.value() + (bar.singleStep() if key == Qt.Key.Key_Down else -bar.singleStep()))
            return True
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            step = 1 if key == Qt.Key.Key_Right else -1
            self._tabs.setCurrentIndex((self._tabs.currentIndex() + step) % self._tabs.count())
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Enter drives the highlighted (enabled) run button
            for btn in (self._btn_q1, self._btn_q2):
                if btn.isEnabled():
                    btn.click()
                    return True
            # Career: this excursion's single session (Q1 or Q2) is done — hand
            # back to the Season Hub rather than advancing to the Race page.
            if self._career_session_done and self._wiz.mode == 'career':
                self._wiz.return_to_hub_after_session()
                return True
            return False    # both sessions done -> global Enter advances
        return False

    def initializePage(self):
        if self._wiz.mode == 'career':
            self._init_career()
            return
        self._q1_done = False
        self._q2_done = False
        self._career_session_done = False
        self._btn_q1.setEnabled(True)
        self._btn_q1.setText('▶  Run Q1')
        self._btn_q2.setEnabled(False)
        self._btn_q2.setText('▶  Run Q2')
        self._status.setText('')
        for t in (self._t_q1, self._t_q2, self._t_gr):
            t.setRowCount(0)
        self._wiz.grid_all_df = None
        self._tabs.setCurrentIndex(0)
        self.completeChanged.emit()

    def _init_career(self):
        """Career visits this page twice a round: once for the Qualifying 1
        session (session_index 1) and again for Qualifying 2 (index 2). Q1
        simulates the whole session and parks the result on the wizard; the Q2
        visit restores that result so it can reveal Q2 + the grid without
        re-simulating (which would shuffle a grid the player already saw)."""
        self._career_session_done = False
        self._status.setText('')
        if self._wiz.session_index <= 1:
            # Qualifying 1 excursion — a fresh session.
            self._q1_done = False
            self._q2_done = False
            self._btn_q1.setEnabled(True)
            self._btn_q1.setText('▶  Run Q1')
            self._btn_q2.setEnabled(False)
            self._btn_q2.setText('▶  Run Q2')
            for t in (self._t_q1, self._t_q2, self._t_gr):
                t.setRowCount(0)
            self._wiz.grid_all_df  = None
            self._wiz.quali_result = None
            self._tabs.setCurrentIndex(0)
        else:
            # Qualifying 2 excursion — restore Q1's simulated result.
            q1, q2, adv, nq, _grid = self._wiz.quali_result
            self._q1_class, self._q2_class = q1, q2
            self._q2_advance, self._q1_nq  = adv, nq
            self._fill_q1_table()
            self._q1_done = True
            self._q2_done = False
            self._btn_q1.setEnabled(False)
            self._btn_q1.setText('✓  Q1')
            self._btn_q2.setEnabled(True)
            self._btn_q2.setText('▶  Run Q2')
            self._t_q2.setRowCount(0)
            self._t_gr.setRowCount(0)
            self._tabs.setCurrentIndex(0)
        self.completeChanged.emit()

    def _fill_q1_table(self):
        rows = []
        for pos, row in self._q1_class.iterrows():
            adv_tag = '★' if row['name'] in self._q2_advance else ''
            rows.append([f'P{pos}', f"#{row['bike_number']}", row['name'],
                         row['team'], row['manufacturer'],
                         row['best_lap'], row['gap_fmt'] + (' ' + adv_tag if adv_tag else '')])
        fill_table(self._t_q1, rows)

    def _run_q1(self):
        self._btn_q1.setEnabled(False)
        self._status.setText('Running Q1…')
        q1, q2, adv, nq, grid = run_qualifying(
            self._wiz.df, self._wiz.circuit, self._wiz.practice_results,
            is_wet=self._wiz.session_is_wet()
        )
        self._q1_class   = q1
        self._q2_class   = q2
        self._q2_advance = adv
        self._q1_nq      = nq
        # Park the whole simulated session so a Career Q2 excursion can reveal
        # Q2 + grid without re-simulating (see _init_career).
        self._wiz.quali_result = (q1, q2, adv, nq, grid)

        self._fill_q1_table()

        self._q1_done = True
        if self._wiz.mode == 'career':
            # Q1 is its own hub session — don't roll straight into Q2; Enter
            # now returns to the hub, where Qualifying 2 becomes next up.
            self._career_session_done = True
            self._status.setText(f"Q1 done. Advancing: {', '.join(adv)}   ·   Enter → hub")
            self.completeChanged.emit()
        else:
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

        # Build grid_all_df for the race session
        import pandas as pd
        grid_all = pd.concat([q2, nq]).reset_index(drop=True)
        grid_all['grid_pos'] = range(1, len(grid_all) + 1)
        self._wiz.grid_all_df = grid_all

        self._q2_done = True
        if self._wiz.mode == 'career':
            self._career_session_done = True
        pole = q2.iloc[0]['name']
        tail = '   ·   Enter → hub' if self._wiz.mode == 'career' else ''
        self._status.setText(f"✓  POLE: {pole}  —  {q2.iloc[0]['best_lap']}{tail}")
        self._tabs.setCurrentIndex(2)
        self.completeChanged.emit()

    def isComplete(self):
        # Career returns to the hub via handle_key (Enter), so each excursion's
        # own session finishing is what matters; other modes need both.
        if self._wiz.mode == 'career':
            return self._career_session_done
        return self._q2_done

    def nextId(self):
        # Weather selection is a Random Race extra — championship rounds
        # skip straight to Race and keep rolling WET_RACE_PROB_PCT.
        if self._wiz.mode == 'random':
            return self._wiz.ID_WEATHER
        return self._wiz.ID_RACE
