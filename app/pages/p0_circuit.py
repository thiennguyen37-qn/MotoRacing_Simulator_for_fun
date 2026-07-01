from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout,
                              QLabel, QFrame, QListWidget, QListWidgetItem,
                              QSizePolicy)
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtCore import Qt

from app.wizard import REPORT_ROOT

# ── Stat row helper ───────────────────────────────────────────────────────────

def _stat(label, value):
    row = QHBoxLayout()
    row.setSpacing(0)
    lbl = QLabel(label)
    lbl.setFont(QFont('Segoe UI', 9))
    lbl.setStyleSheet('color: #555; background: transparent; border: none;')
    lbl.setFixedWidth(110)
    val = QLabel(str(value))
    val.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
    val.setStyleSheet('color: #ddd; background: transparent; border: none;')
    row.addWidget(lbl)
    row.addWidget(val, 1)
    return row


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

        self._list.currentRowChanged.connect(self._refresh)
        left.addWidget(self._list)
        main.addLayout(left, 2)

        # ── Right: circuit detail card ────────────────────────────────────────
        right = QVBoxLayout()
        right.setSpacing(6)

        lbl_info = QLabel('CIRCUIT INFO')
        lbl_info.setFont(QFont('Segoe UI', 8))
        lbl_info.setStyleSheet('color: #555; letter-spacing: 2px;')
        right.addWidget(lbl_info)

        card = QFrame()
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        card.setStyleSheet(
            'QFrame { background: #0e0e14; border: 1px solid #1e1e2a; border-radius: 8px; }'
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 20, 20, 20)
        cl.setSpacing(4)

        # Circuit name (large)
        self._name_lbl = QLabel('')
        self._name_lbl.setFont(QFont('Segoe UI', 15, QFont.Weight.Bold))
        self._name_lbl.setStyleSheet('color: #fff; background: transparent; border: none;')
        self._name_lbl.setWordWrap(True)
        cl.addWidget(self._name_lbl)

        self._country_lbl = QLabel('')
        self._country_lbl.setFont(QFont('Segoe UI', 10))
        self._country_lbl.setStyleSheet('color: #e02840; background: transparent; border: none;')
        cl.addWidget(self._country_lbl)
        cl.addSpacing(12)

        # Red divider
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet('background: #1e1e2a; border: none;')
        cl.addWidget(div)
        cl.addSpacing(12)

        # Stats — keep references to update them
        self._stats_layout = QVBoxLayout()
        self._stats_layout.setSpacing(10)
        cl.addLayout(self._stats_layout)
        cl.addStretch()

        right.addWidget(card)
        main.addLayout(right, 1)

        # Select first item
        self._list.setCurrentRow(0)

    def _refresh(self, idx):
        if idx < 0:
            return
        c = self._wiz.circuits_df.iloc[idx]

        self._name_lbl.setText(c['circuit_name'])
        self._country_lbl.setText(c['country'].upper())

        # Rebuild stats
        while self._stats_layout.count():
            item = self._stats_layout.takeAt(0)
            if item.layout():
                while item.layout().count():
                    w = item.layout().takeAt(0).widget()
                    if w:
                        w.deleteLater()

        stats = [
            ('LAP LENGTH',     f"{c['lap_length_km']} km"),
            ('BASE LAP TIME',  f"{c['base_lap_time']} s"),
            ('CORNERS',        str(int(c['corners']))),
            ('STRAIGHT',       f"{int(c['straight_length_m'])} m"),
        ]
        for label, value in stats:
            self._stats_layout.addLayout(_stat(label, value))

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
