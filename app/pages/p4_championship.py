import pandas as pd
from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout,
                              QLabel, QTabWidget)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt

from app.widgets.table_utils import make_table, fill_table


class ChampionshipPage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self._wiz = wiz
        self.setTitle('Standings')

        layout = QVBoxLayout(self)

        # Info bar
        self._info_lbl = QLabel('')
        self._info_lbl.setFont(QFont('Segoe UI', 10))
        layout.addWidget(self._info_lbl)

        self._tabs = QTabWidget()
        self._t_riders = make_table(['P', '#', 'RIDER', 'TEAM', 'MANUFACTURER', 'PTS'])
        self._t_teams  = make_table(['P', 'TEAM', 'PTS'])
        self._t_manu   = make_table(['P', 'MANUFACTURER', 'PTS'])
        self._tabs.addTab(self._t_riders, 'Riders')
        self._tabs.addTab(self._t_teams,  'Teams')
        self._tabs.addTab(self._t_manu,   'Manufacturers')
        layout.addWidget(self._tabs)

        self._rider_total = None
        self._team_total  = None
        self._manu_total  = None

    # ── Wizard flow ───────────────────────────────────────────────────────────

    def initializePage(self):
        wiz = self._wiz

        if wiz.mode == 'championship':
            n   = len(wiz.circuits_df)
            idx = wiz.circuit_index
            self.setSubTitle(f"Round {idx + 1}/{n}  —  {wiz.circuit['circuit_name']}")
            self._info_lbl.setText(
                f"  Season standing after {idx + 1} of {n} rounds"
                + (f"  |  {n - idx - 1} round(s) remaining" if idx < n - 1 else "  |  Final standings")
            )
            # Update Next button text
            if idx < n - 1:
                wiz.setButtonText(
                    wiz.WizardButton.NextButton,
                    f'Next Circuit ({idx + 2}/{n}) →'
                )
            else:
                wiz.setButtonText(wiz.WizardButton.FinishButton, '🏆  Finish Championship')
        else:
            self.setSubTitle(f"Overall standings after 2 races at {wiz.circuit['circuit_name']}.")
            self._info_lbl.setText('')
            wiz.setButtonText(wiz.WizardButton.FinishButton, 'Finish')

        self._compute()

    def validatePage(self):
        wiz = self._wiz
        if wiz.mode == 'championship':
            # Save current circuit's pts into cumulative pool
            wiz.all_race_pts.extend(wiz.race_pts)
            wiz.circuit_index += 1
        return True

    def handle_key(self, key: int) -> bool:
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            bar = self._tabs.currentWidget().verticalScrollBar()
            bar.setValue(bar.value() + (bar.singleStep() if key == Qt.Key.Key_Down else -bar.singleStep()))
            return True
        return False

    def nextId(self):
        wiz = self._wiz
        if wiz.mode == 'championship' and wiz.circuit_index < len(wiz.circuits_df) - 1:
            return wiz.ID_PRACTICE
        return -1  # end of wizard (Finish button shown)

    # ── Data ─────────────────────────────────────────────────────────────────

    def _compute(self):
        wiz = self._wiz

        if wiz.mode == 'championship':
            # Cumulative: all previous circuits + current circuit
            all_pts = wiz.all_race_pts + wiz.race_pts
        else:
            all_pts = wiz.race_pts

        if not all_pts:
            return

        combined = pd.concat(all_pts, ignore_index=True)

        self._rider_total = (
            combined.groupby(['name', 'bike_number', 'team', 'manufacturer'], as_index=False)['points']
            .sum().sort_values('points', ascending=False).reset_index(drop=True)
        )
        self._team_total = (
            combined.groupby('team', as_index=False)['points']
            .sum().sort_values('points', ascending=False).reset_index(drop=True)
        )
        manu_per_race = [r.groupby('manufacturer', as_index=False)['points'].max() for r in all_pts]
        self._manu_total = (
            pd.concat(manu_per_race).groupby('manufacturer', as_index=False)['points']
            .sum().sort_values('points', ascending=False).reset_index(drop=True)
        )

        fill_table(self._t_riders, [
            [i + 1, f"#{r['bike_number']}", r['name'], r['team'], r['manufacturer'], r['points']]
            for i, r in self._rider_total.iterrows()
        ])                                              # manu_col_idx=4, num_col_idx=1

        fill_table(self._t_teams, [
            [i + 1, r['team'], r['points']] for i, r in self._team_total.iterrows()
        ], team_col_idx=1, manu_col_idx=None, num_col_idx=None, name_col_idx=1, stretch_col=1)

        fill_table(self._t_manu, [
            [i + 1, r['manufacturer'], r['points']] for i, r in self._manu_total.iterrows()
        ], team_col_idx=None, manu_col_idx=1, num_col_idx=None, name_col_idx=1, stretch_col=1)
