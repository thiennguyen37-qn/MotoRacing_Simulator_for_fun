from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout,
                              QPushButton, QLabel, QTableWidgetItem, QTabWidget)
from PyQt6.QtGui import QFont, QColor, QBrush, QPen
from PyQt6.QtCore import Qt, QTimer, QVariantAnimation, QEasingCurve

from src.simulator import run_race
from PyQt6.QtWidgets import QHeaderView
from app.widgets.table_utils import (make_table, TEAM_COLOR, MANU_COLOR, _DEFAULT_COLOR,
                                      row_bg, _is_time, SESSION_BTN_SS, SESSION_TABS_SS)

HEADERS = ['P', '#', 'RIDER', 'TEAM', 'MANUFACTURER', 'RACE TIME', 'GAP']

# ── Staggered result reveal ────────────────────────────────────────────────────
_ROW_H       = 42     # target row height (matches make_table default section size)
_REVEAL_MS   = 300    # per-row grow-in animation duration
# Delay before each finisher = its gap to the rider ahead, scaled. A literal 1:1
# (1.0) runs ~30 s because the field spreads over 40–80 s; 0.20 keeps the same
# pacing (bigger gap → longer pause) at a snappy ~10 s. Raise toward 1.0 to slow.
_GAP_SCALE   = 0.20
_STEP_MIN_MS = 120    # floor so near-simultaneous finishes still stagger visibly
_STEP_MAX_MS = 900    # cap so a lone straggler doesn't freeze the reveal
_DNF_STEP_MS = 350    # fixed delay per DNF row (no race-time gap to key off)
_LEAD_MS     = 250    # pause before the winner appears


def _gap_seconds(gap_fmt) -> float | None:
    """Parse a GAP cell → seconds. None means DNF ('Lap N'); 0.0 is the leader."""
    s = str(gap_fmt).strip()
    if s.startswith('+'):
        try:
            return float(s[1:])
        except ValueError:
            return 0.0
    if s in ('—', '-', '–', ''):
        return 0.0
    return None


def _fill(table, result_df, meta):
    """Populate the table with rows collapsed; return per-row reveal metadata."""
    rows = result_df.to_dict('records')
    table.setRowCount(len(rows))
    reveal = []
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
        # DNF rows keep the same light text as finishers (readable on every team
        # colour); they stay distinguishable via the darker row + 'DNF' / 'Lap N'.
        for c, val in enumerate(vals):
            txt  = str(val)
            item = QTableWidgetItem(txt)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setBackground(QBrush(bg))

            if c == 0:
                item.setData(Qt.ItemDataRole.UserRole, accent)
                item.setForeground(QBrush(QColor(220, 220, 235)))
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
                item.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
            elif c == 1:
                item.setForeground(QBrush(lighter))
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
                item.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
            elif c == 2:
                # Rider name — bold, already uppercased above
                item.setForeground(QBrush(QColor(235, 235, 248)))
                item.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
            elif _is_time(txt):
                item.setForeground(QBrush(QColor(235, 235, 248)))
                item.setFont(QFont('Consolas', 10))
            else:
                item.setForeground(QBrush(QColor(235, 235, 248)))
                item.setFont(QFont('Segoe UI', 10))

            table.setItem(r, c, item)
        reveal.append({'dnf': dnf, 'gap': _gap_seconds(row['gap_fmt'])})

    table.resizeColumnsToContents()
    table.setColumnWidth(0, 56)
    table.setColumnWidth(1, 56)
    hdr = table.horizontalHeader()
    hdr.setStretchLastSection(False)
    hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)  # TEAM col fills width

    for r in range(table.rowCount()):
        table.setRowHeight(r, 0)   # collapsed; grown one-by-one during the reveal
    return reveal


class RacePage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self._wiz       = wiz
        self._r1_done   = False
        self._both_done = False
        self._reveal_timers: dict[int, list] = {}   # table-id → pending QTimers
        self._reveal_anims:  dict[int, list] = {}    # table-id → running animations
        self.setTitle('Race Weekend')
        self.setSubTitle('Two races on the same grid. Each race has an independent weather roll.')

        layout = QVBoxLayout(self)

        ctrl = QHBoxLayout()
        self._btn_r1 = QPushButton('▶  Run Race 1')
        self._btn_r1.setFixedHeight(34)
        self._btn_r1.setStyleSheet(SESSION_BTN_SS)
        self._btn_r1.setAutoDefault(False)
        self._btn_r1.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_r1.clicked.connect(lambda: self._run(1))
        self._btn_r2 = QPushButton('▶  Run Race 2')
        self._btn_r2.setFixedHeight(34)
        self._btn_r2.setStyleSheet(SESSION_BTN_SS)
        self._btn_r2.setAutoDefault(False)
        self._btn_r2.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_r2.setEnabled(False)
        self._btn_r2.clicked.connect(lambda: self._run(2))
        self._status = QLabel('')
        ctrl.addWidget(self._btn_r1)
        ctrl.addWidget(self._btn_r2)
        ctrl.addWidget(self._status, 1)
        layout.addLayout(ctrl)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(SESSION_TABS_SS)
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
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            step = 1 if key == Qt.Key.Key_Right else -1
            self._tabs.setCurrentIndex((self._tabs.currentIndex() + step) % self._tabs.count())
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Enter drives the highlighted (enabled) run button
            for btn in (self._btn_r1, self._btn_r2):
                if btn.isEnabled():
                    btn.click()
                    return True
            return False    # both races done -> global Enter advances
        return False

    def initializePage(self):
        self._r1_done   = False
        self._both_done = False
        self._stop_reveal(self._t_r1)
        self._stop_reveal(self._t_r2)
        self._btn_r1.setEnabled(True)
        self._btn_r1.setText('▶  Run Race 1')
        self._btn_r2.setEnabled(False)
        self._btn_r2.setText('▶  Run Race 2')
        self._status.setText('')
        self._t_r1.setRowCount(0)
        self._t_r2.setRowCount(0)
        self._wiz.race_pts     = []
        self._wiz.race_results = []
        self.completeChanged.emit()

    def _run(self, race_num):
        if race_num == 1:
            self._btn_r1.setEnabled(False)
        else:
            self._btn_r2.setEnabled(False)
        self._status.setText(f'Running Race {race_num}…')

        # forced_weather is a Random Race-only override (set by WeatherPage,
        # which championship rounds never visit) — gate by mode so a stale
        # value from an earlier Random Race can't leak into a championship.
        forced_weather = self._wiz.forced_weather if self._wiz.mode == 'random' else None
        result_df, pts_df, meta = run_race(
            self._wiz.df, self._wiz.circuit, self._wiz.grid_all_df,
            forced_weather=forced_weather
        )
        self._wiz.race_pts.append(pts_df)
        self._wiz.race_results.append(
            result_df[['name', 'pos', 'dnf', 'fastest_lap', 'grid_pos']].copy())

        table = self._t_r1 if race_num == 1 else self._t_r2
        reveal = _fill(table, result_df, meta)
        self._tabs.setCurrentIndex(race_num - 1)

        # Reveal the classification row-by-row, spacing each finisher by the gap
        # to the one ahead; winner/FL are announced only once the reveal ends so
        # it isn't spoiled up front.
        self._status.setText(f'Race {race_num} — revealing results…')
        self._start_reveal(
            table, reveal,
            lambda: self._on_reveal_done(race_num, result_df, meta),
        )

    # ── Staggered reveal ──────────────────────────────────────────────────────

    def _start_reveal(self, table, reveal, on_done):
        self._stop_reveal(table)
        tid = id(table)
        timers, anims = [], []
        self._reveal_timers[tid] = timers
        self._reveal_anims[tid]  = anims

        n = len(reveal)
        if n == 0:
            on_done()
            return

        cum, prev_gap = _LEAD_MS, 0.0
        for r, m in enumerate(reveal):
            if r == 0:
                step = 0
            elif m['gap'] is None:                       # DNF — no time gap
                step = _DNF_STEP_MS
            else:
                incr = max(0.0, m['gap'] - prev_gap)
                step = int(min(max(incr * 1000 * _GAP_SCALE, _STEP_MIN_MS), _STEP_MAX_MS))
            if m['gap'] is not None:
                prev_gap = m['gap']
            cum += step

            tm = QTimer(self)
            tm.setSingleShot(True)
            tm.timeout.connect(
                lambda _r=r, _last=(r == n - 1): self._reveal_row(table, _r, _last, on_done)
            )
            tm.start(cum)
            timers.append(tm)

    def _reveal_row(self, table, r, is_last, on_done):
        if r >= table.rowCount():   # table was reset mid-reveal
            return
        anim = QVariantAnimation(self)
        anim.setStartValue(0)
        anim.setEndValue(_ROW_H)
        anim.setDuration(_REVEAL_MS)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(lambda v, _r=r: table.setRowHeight(_r, int(v)))
        if is_last:
            anim.finished.connect(on_done)
        anim.start()
        self._reveal_anims.setdefault(id(table), []).append(anim)

    def _stop_reveal(self, table):
        tid = id(table)
        for tm in self._reveal_timers.get(tid, []):
            tm.stop()
        for a in self._reveal_anims.get(tid, []):
            a.stop()
        self._reveal_timers[tid] = []
        self._reveal_anims[tid]  = []

    def _on_reveal_done(self, race_num, result_df, meta):
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
