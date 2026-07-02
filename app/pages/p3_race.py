from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout,
                              QPushButton, QLabel, QTableWidgetItem, QTabWidget)
from PyQt6.QtGui import QFont, QColor, QBrush, QPen
from PyQt6.QtCore import Qt

from src.simulator import run_race
from PyQt6.QtWidgets import QHeaderView
from app.widgets.table_utils import make_table, TEAM_COLOR, MANU_COLOR, _DEFAULT_COLOR, row_bg, _is_time

HEADERS = ['P', '#', 'RIDER', 'TEAM', 'MANUFACTURER', 'RACE TIME', 'GAP']

_DNF_COLOR = QColor(180, 55, 55)


def _fill(table, result_df, meta):
    rows = result_df.to_dict('records')
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        dnf     = bool(row.get('dnf'))
        manu    = row.get('manufacturer', '')
        color   = TEAM_COLOR.get(row.get('team', '')) or MANU_COLOR.get(manu, _DEFAULT_COLOR)
        bg      = row_bg(color.darker(140) if dnf else color)
        lighter = QColor(
            min(color.red()   + 80, 255),
            min(color.green() + 80, 255),
            min(color.blue()  + 80, 255),
        )
        accent = color.darker(160) if dnf else color

        fl_tag = ' ⚡' if row.get('fastest_lap') else ''
        # col 2 = rider name: uppercase
        vals = [
            row['pos_label'],
            f"#{row['bike_number']}",
            (row['name'] + fl_tag).upper(),
            row['team'],
            row['manufacturer'],
            row['time_fmt'],
            row['gap_fmt'],
        ]
        for c, val in enumerate(vals):
            txt  = str(val)
            item = QTableWidgetItem(txt)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setBackground(QBrush(bg))

            if c == 0:
                item.setData(Qt.ItemDataRole.UserRole, accent)
                item.setForeground(QBrush(QColor(200, 80, 80) if dnf else QColor(220, 220, 235)))
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
                item.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
            elif c == 1:
                item.setForeground(QBrush(_DNF_COLOR if dnf else lighter))
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
                item.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
            elif c == 2:
                # Rider name — bold, already uppercased above
                item.setForeground(QBrush(_DNF_COLOR if dnf else QColor(235, 235, 248)))
                item.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
            elif _is_time(txt):
                item.setForeground(QBrush(_DNF_COLOR if dnf else QColor(235, 235, 248)))
                item.setFont(QFont('Consolas', 10))
            else:
                item.setForeground(QBrush(_DNF_COLOR if dnf else QColor(235, 235, 248)))
                item.setFont(QFont('Segoe UI', 10))

            table.setItem(r, c, item)

    table.resizeColumnsToContents()
    table.setColumnWidth(0, 56)
    table.setColumnWidth(1, 56)
    hdr = table.horizontalHeader()
    hdr.setStretchLastSection(False)
    hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)  # TEAM col fills width


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
        self._t_r1 = make_table(HEADERS)
        self._t_r2 = make_table(HEADERS)
        self._tabs.addTab(self._t_r1, 'Race 1')
        self._tabs.addTab(self._t_r2, 'Race 2')
        layout.addWidget(self._tabs)

    def handle_key(self, key: int) -> bool:
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            bar = self._tabs.currentWidget().verticalScrollBar()
            bar.setValue(bar.value() + (bar.singleStep() if key == Qt.Key.Key_Down else -bar.singleStep()))
            return True
        return False

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
