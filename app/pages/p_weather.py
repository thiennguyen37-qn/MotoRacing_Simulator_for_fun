from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout,
                              QLabel, QPushButton, QFrame, QButtonGroup)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt

_OPTIONS = [
    ('random', 'RANDOM', 'WET_RACE_PROB_PCT decides — the usual dice roll'),
    ('dry',    'DRY ☀',  'Both races are guaranteed dry'),
    ('wet',    'WET 🌧', 'Both races are guaranteed wet'),
]


class WeatherPage(QWizardPage):
    """Random Race only — shown right after Qualifying, before the Race
    session. Lets the player force the weekend's weather instead of leaving
    it to WET_RACE_PROB_PCT. Cycled with ←/→ and confirmed with Enter (this
    app has no mouse input — see MotoWizard.eventFilter)."""

    def __init__(self, wiz):
        super().__init__()
        self._wiz = wiz
        self.setTitle('Race Weather')
        self.setSubTitle('Choose the conditions for both races this weekend.')

        root = QVBoxLayout(self)
        root.addStretch(1)

        row = QHBoxLayout()
        row.setSpacing(16)
        row.addStretch(1)

        self._weather = 'random'
        self._buttons = {}
        self._descs = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for value, label, desc in _OPTIONS:
            card = QFrame()
            card.setFixedSize(220, 150)
            card.setStyleSheet("""
                QFrame { background: rgba(255,255,255,4); border: 1px solid #1e1e2e; border-radius: 14px; }
                QLabel { background: transparent; border: none; }
            """)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(18, 18, 18, 18)
            cl.setSpacing(10)

            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(value == 'random')
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # keyboard-driven via handle_key, not Tab
            btn.setFixedHeight(48)
            btn.setFont(QFont('Segoe UI', 13, QFont.Weight.Bold))
            btn.setStyleSheet("""
                QPushButton {
                    color: #aaaabb; background: rgba(255,255,255,6);
                    border: 1px solid #1e1e2e; border-radius: 10px;
                }
                QPushButton:checked {
                    color: #ffffff; background: rgba(224,40,64,40);
                    border: 1px solid #e02840;
                }
            """)
            cl.addWidget(btn)

            desc_lbl = QLabel(desc)
            desc_lbl.setWordWrap(True)
            desc_lbl.setFont(QFont('Segoe UI', 8))
            desc_lbl.setStyleSheet('color: #888899;')
            cl.addWidget(desc_lbl, 1)

            self._buttons[value] = btn
            self._descs[value] = desc_lbl
            self._group.addButton(btn)
            row.addWidget(card)

        row.addStretch(1)
        root.addLayout(row)
        root.addSpacing(18)

        hint = QLabel('◀ ▶  choose      Enter  continue')
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setFont(QFont('Segoe UI', 9))
        hint.setStyleSheet('color: #666677;')
        root.addWidget(hint)
        root.addStretch(1)

        self._order = [v for v, _, _ in _OPTIONS]

    def initializePage(self):
        self._set_weather('random')

    def _set_weather(self, value):
        self._weather = value
        self._buttons[value].setChecked(True)

    def handle_key(self, key: int) -> bool:
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            step = -1 if key == Qt.Key.Key_Left else 1
            idx = (self._order.index(self._weather) + step) % len(self._order)
            self._set_weather(self._order[idx])
            return True
        return False

    def validatePage(self):
        self._wiz.forced_weather = None if self._weather == 'random' else self._weather
        return True

    def nextId(self):
        return self._wiz.ID_RACE
