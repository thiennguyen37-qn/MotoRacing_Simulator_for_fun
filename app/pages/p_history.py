import json
from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout,
                              QLabel, QFrame, QTabWidget)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt

from app.widgets.table_utils import make_table, fill_table
from app.wizard import HISTORY_FILE as _HISTORY


def _load_history() -> list:
    if not _HISTORY.exists():
        return []
    try:
        return json.loads(_HISTORY.read_text(encoding='utf-8')).get('seasons', [])
    except (json.JSONDecodeError, OSError):
        return []


class HistoryPage(QWizardPage):
    """Championship archive — all-time rider records and past seasons."""

    def __init__(self, wiz):
        super().__init__()
        self._wiz = wiz
        self.setTitle('')
        self.setSubTitle('')

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 24, 36, 24)
        root.setSpacing(0)

        hdr_row = QHBoxLayout()
        hdr = QLabel('CHAMPIONSHIP HISTORY')
        hdr.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
        hdr.setStyleSheet('color: #e02840; letter-spacing: 3px; background: transparent; border: none;')
        hdr_row.addWidget(hdr)
        hdr_row.addStretch(1)
        self._count_lbl = QLabel('')
        self._count_lbl.setFont(QFont('Consolas', 10, QFont.Weight.Bold))
        self._count_lbl.setStyleSheet('color: #666677; background: transparent; border: none;')
        hdr_row.addWidget(self._count_lbl)
        root.addLayout(hdr_row)
        root.addSpacing(4)

        sub = QLabel('All-time rider records and past championship seasons')
        sub.setFont(QFont('Segoe UI', 9))
        sub.setStyleSheet('color: #666677; background: transparent; border: none;')
        root.addWidget(sub)
        root.addSpacing(12)

        div = QFrame()
        div.setFixedHeight(2)
        div.setStyleSheet('background: #1e1e2e; border: none;')
        root.addWidget(div)
        root.addSpacing(12)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane { border: none; }
            QTabBar::tab {
                background: rgba(255,255,255,5);
                color: #666677;
                padding: 7px 20px;
                border: none;
                border-radius: 6px;
                margin-right: 6px;
                font-weight: 600;
            }
            QTabBar::tab:selected { background: #e02840; color: #ffffff; }
        """)
        self._t_overall = make_table(
            ['P', 'RIDER', 'TEAM', 'SEASONS', 'TITLES', 'WINS', 'PODIUMS', 'PTS'])
        self._t_seasons = make_table(
            ['SEASON', 'ROUNDS', 'CHAMPION', 'TEAM', 'MANUFACTURER', 'WINS', 'PTS'])
        self._tabs.addTab(self._t_overall, "Rider's Overall Stats")
        self._tabs.addTab(self._t_seasons, 'Season Stats')
        root.addWidget(self._tabs, 1)

        self._empty = QLabel('No championship has been completed yet — '
                             'finish a season and it will be recorded here.')
        self._empty.setFont(QFont('Segoe UI', 10))
        self._empty.setStyleSheet('color: #555566; background: transparent; border: none;')
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._empty)

    # ── Wizard flow ───────────────────────────────────────────────────────────

    def initializePage(self):
        seasons = _load_history()
        self._count_lbl.setText(f'{len(seasons)} SEASON{"S" if len(seasons) != 1 else ""}')
        self._empty.setVisible(not seasons)
        self._tabs.setVisible(bool(seasons))
        self._tabs.setCurrentIndex(0)
        if seasons:
            self._fill_overall(seasons)
            self._fill_seasons(seasons)

    def nextId(self):
        return -1

    def handle_key(self, key: int) -> bool:
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            step = 1 if key == Qt.Key.Key_Right else -1
            self._tabs.setCurrentIndex((self._tabs.currentIndex() + step) % self._tabs.count())
            return True
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            bar = self._tabs.currentWidget().verticalScrollBar()
            bar.setValue(bar.value() + (bar.singleStep() if key == Qt.Key.Key_Down else -bar.singleStep()))
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            return True    # nothing to activate — Backspace/Esc goes home
        return False

    # ── Tables ────────────────────────────────────────────────────────────────

    def _fill_overall(self, seasons):
        agg: dict[str, dict] = {}
        for s in seasons:
            for st in s.get('standings', []):
                a = agg.setdefault(st['name'], {'team': '', 'seasons': 0, 'titles': 0,
                                                'wins': 0, 'podiums': 0, 'pts': 0})
                a['seasons'] += 1
                a['pts']     += int(st.get('points', 0))
                a['team']     = st.get('team', '')       # most recent team
            for name, stt in s.get('stats', {}).items():
                a = agg.setdefault(name, {'team': '', 'seasons': 0, 'titles': 0,
                                          'wins': 0, 'podiums': 0, 'pts': 0})
                a['wins']    += int(stt.get('wins', 0))
                a['podiums'] += int(stt.get('podiums', 0))
            champ = s.get('champion') or {}
            if champ.get('name') in agg:
                agg[champ['name']]['titles'] += 1

        order = sorted(agg.items(),
                       key=lambda kv: (-kv[1]['titles'], -kv[1]['wins'], -kv[1]['pts']))
        fill_table(self._t_overall, [
            [i + 1, name, a['team'], a['seasons'], a['titles'],
             a['wins'], a['podiums'], a['pts']]
            for i, (name, a) in enumerate(order)
        ], team_col_idx=2, manu_col_idx=None, num_col_idx=None,
           name_col_idx=1, stretch_col=2)

    def _fill_seasons(self, seasons):
        rows = []
        for i, s in enumerate(seasons):
            champ = s.get('champion') or {}
            wins  = s.get('stats', {}).get(champ.get('name', ''), {}).get('wins', 0)
            rows.append([s.get('year', f'S{i + 1:02d}'), s.get('rounds', 0),
                         champ.get('name', '—'), champ.get('team', '—'),
                         champ.get('manufacturer', '—'), wins,
                         champ.get('points', 0)])
        fill_table(self._t_seasons, rows,
                   team_col_idx=3, manu_col_idx=4, num_col_idx=None,
                   name_col_idx=2, stretch_col=3)
