from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout,
                              QPushButton, QLabel, QTableWidget,
                              QTableWidgetItem, QTabWidget)
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtCore import Qt

from src.simulator import run_race

HEADERS = ['P', '#', 'RIDER', 'TEAM', 'MANUFACTURER', 'RACE TIME', 'GAP']


def _make_table():
    t = QTableWidget()
    t.setColumnCount(len(HEADERS))
    t.setHorizontalHeaderLabels(HEADERS)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    t.setFont(QFont('Courier New', 9))
    return t


def _fill(table, result_df, meta):
    rows = result_df.to_dict('records')
    table.setRowCount(len(rows))
    red = QColor(200, 60, 60)
    for r, row in enumerate(rows):
        fl_tag = ' ⚡' if row.get('fastest_lap') else ''
        vals = [
            row['pos_label'],
            f"#{row['bike_number']}",
            row['name'] + fl_tag,
            row['team'],
            row['manufacturer'],
            row['time_fmt'],
            row['gap_fmt'],
        ]
        for c, val in enumerate(vals):
            item = QTableWidgetItem(str(val))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if row.get('dnf'):
                item.setForeground(red)
            table.setItem(r, c, item)
    table.resizeColumnsToContents()
    table.horizontalHeader().setStretchLastSection(True)


class RacePage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self._wiz       = wiz
        self._r1_done   = False
        self._both_done = False
        self.setTitle('Race Weekend')
        self.setSubTitle('Two races on the same grid. Each race has an independent weather roll.')

        layout = QVBoxLayout(self)

        ctrl = QHBoxLayout()
        self._btn_r1 = QPushButton('▶  Run Race 1')
        self._btn_r1.setFixedHeight(34)
        self._btn_r1.clicked.connect(lambda: self._run(1))
        self._btn_r2 = QPushButton('▶  Run Race 2')
        self._btn_r2.setFixedHeight(34)
        self._btn_r2.setEnabled(False)
        self._btn_r2.clicked.connect(lambda: self._run(2))
        self._status = QLabel('')
        ctrl.addWidget(self._btn_r1)
        ctrl.addWidget(self._btn_r2)
        ctrl.addWidget(self._status, 1)
        layout.addLayout(ctrl)

        self._tabs = QTabWidget()
        self._t_r1 = _make_table()
        self._t_r2 = _make_table()
        self._tabs.addTab(self._t_r1, 'Race 1')
        self._tabs.addTab(self._t_r2, 'Race 2')
        layout.addWidget(self._tabs)

    def initializePage(self):
        self._r1_done   = False
        self._both_done = False
        self._btn_r1.setEnabled(True)
        self._btn_r1.setText('▶  Run Race 1')
        self._btn_r2.setEnabled(False)
        self._btn_r2.setText('▶  Run Race 2')
        self._status.setText('')
        self._t_r1.setRowCount(0)
        self._t_r2.setRowCount(0)
        self._wiz.race_pts = []
        self.completeChanged.emit()

    def _run(self, race_num):
        if race_num == 1:
            self._btn_r1.setEnabled(False)
        else:
            self._btn_r2.setEnabled(False)
        self._status.setText(f'Running Race {race_num}…')

        result_df, pts_df, meta = run_race(
            self._wiz.df, self._wiz.circuit, self._wiz.grid_all_df
        )
        self._wiz.race_pts.append(pts_df)

        table = self._t_r1 if race_num == 1 else self._t_r2
        _fill(table, result_df, meta)
        self._tabs.setCurrentIndex(race_num - 1)

        weather = 'WET 🌧' if meta['is_wet'] else 'DRY ☀'
        winner  = result_df.iloc[0]['name']
        fl      = meta['fl_name']
        self._status.setText(
            f"✓ Race {race_num}  {weather}  |  Winner: {winner}  |  ⚡ FL: {fl}"
        )

        if race_num == 1:
            self._r1_done = True
            self._btn_r2.setEnabled(True)
        else:
            self._both_done = True
            self.completeChanged.emit()

    def isComplete(self):
        return self._both_done
