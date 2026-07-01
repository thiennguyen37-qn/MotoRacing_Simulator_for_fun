from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout,
                              QLabel, QFrame, QListWidget, QListWidgetItem,
                              QSizePolicy)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt

from app.wizard import REPORT_ROOT
from app.widgets.world_map import WorldMapWidget


class CircuitPage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self._wiz = wiz
        self.setTitle('Select Circuit')
        self.setSubTitle('Choose the circuit for this race weekend.')

        main = QHBoxLayout(self)
        main.setSpacing(16)
        main.setContentsMargins(12, 8, 12, 8)

        # ── Left: circuit list ────────────────────────────────────────────────
        left = QVBoxLayout()
        left.setSpacing(6)

        lbl_list = QLabel('CIRCUITS')
        lbl_list.setFont(QFont('Segoe UI', 8))
        lbl_list.setStyleSheet('color: #555; letter-spacing: 2px;')
        left.addWidget(lbl_list)

        self._list = QListWidget()
        self._list.setFont(QFont('Segoe UI', 10))
        self._list.setSpacing(2)
        self._list.setStyleSheet("""
            QListWidget {
                background: #0e0e14;
                border: 1px solid #1e1e2a;
                border-radius: 8px;
                outline: none;
            }
            QListWidget::item {
                color: #aaa;
                padding: 8px 14px;
                border-radius: 4px;
            }
            QListWidget::item:hover {
                background: #1a1a24;
                color: #fff;
            }
            QListWidget::item:selected {
                background: #e02840;
                color: #fff;
            }
        """)

        for _, c in wiz.circuits_df.iterrows():
            item = QListWidgetItem(f"  {c['circuit_name']}  —  {c['country']}")
            self._list.addItem(item)

        self._list.currentRowChanged.connect(self._on_select)
        left.addWidget(self._list)
        main.addLayout(left, 1)

        # ── Right: world map ──────────────────────────────────────────────────
        right = QVBoxLayout()
        right.setSpacing(6)

        lbl_map = QLabel('WORLD MAP')
        lbl_map.setFont(QFont('Segoe UI', 8))
        lbl_map.setStyleSheet('color: #555; letter-spacing: 2px;')
        right.addWidget(lbl_map)

        self._map = WorldMapWidget()
        self._map.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right.addWidget(self._map)

        # Circuit info bar below map
        info_frame = QFrame()
        info_frame.setStyleSheet(
            'QFrame { background: #0e0e14; border: 1px solid #1e1e2a; border-radius: 6px; }'
            'QLabel { background: transparent; border: none; }'
        )
        info_row = QHBoxLayout(info_frame)
        info_row.setContentsMargins(16, 10, 16, 10)
        info_row.setSpacing(24)

        self._stat_labels = {}
        for key in ['Circuit', 'Country', 'Length', 'Base Lap', 'Corners', 'Straight']:
            col = QVBoxLayout()
            col.setSpacing(2)
            k_lbl = QLabel(key.upper())
            k_lbl.setFont(QFont('Segoe UI', 7))
            k_lbl.setStyleSheet('color: #444; letter-spacing: 1px;')
            v_lbl = QLabel('—')
            v_lbl.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
            v_lbl.setStyleSheet('color: #ddd;')
            col.addWidget(k_lbl)
            col.addWidget(v_lbl)
            self._stat_labels[key] = v_lbl
            info_row.addLayout(col)

        info_row.addStretch()
        right.addWidget(info_frame)

        main.addLayout(right, 2)

        # Select first item
        self._list.setCurrentRow(0)

    def _on_select(self, idx):
        if idx < 0:
            return
        c = self._wiz.circuits_df.iloc[idx]

        # Update map
        self._map.highlight(c['country'])

        # Update stat bar
        self._stat_labels['Circuit'].setText(c['circuit_name'])
        self._stat_labels['Country'].setText(c['country'])
        self._stat_labels['Length'].setText(f"{c['lap_length_km']} km")
        self._stat_labels['Base Lap'].setText(f"{c['base_lap_time']} s")
        self._stat_labels['Corners'].setText(str(int(c['corners'])))
        self._stat_labels['Straight'].setText(f"{int(c['straight_length_m'])} m")

    def validatePage(self):
        idx = self._list.currentRow()
        self._wiz.circuit       = self._wiz.circuits_df.iloc[idx]
        self._wiz.circuit_index = idx
        self._wiz.report_dir    = REPORT_ROOT / self._wiz.circuit['country']
        self._wiz.report_dir.mkdir(parents=True, exist_ok=True)
        self._wiz.practice_results = None
        self._wiz.grid_all_df      = None
        self._wiz.race_pts         = []
        return True

    def nextId(self):
        return self._wiz.ID_PRACTICE
