from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout,
                              QPushButton, QLabel, QTableWidgetItem, QTabWidget,
                              QDialog, QFrame, QApplication, QWidget)
from PyQt6.QtGui import (QFont, QColor, QBrush, QPen, QPainter, QPainterPath,
                          QLinearGradient)
from PyQt6.QtCore import (Qt, QTimer, QVariantAnimation, QEasingCurve,
                           QRect, QRectF, QPropertyAnimation, pyqtProperty)

from src.simulator import run_race
from src import progression
from PyQt6.QtWidgets import QHeaderView
from app.widgets.table_utils import (make_table, TEAM_COLOR, MANU_COLOR, _DEFAULT_COLOR,
                                      row_bg, _is_time, SESSION_BTN_SS, SESSION_TABS_SS)
from app.pages.p_gallery import STATS

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


# ── Post-race progression panel (career only) ─────────────────────────────────
# Bigger, animated cousin of season_hub's _RatingBar: fills from the stat's
# pre-race value up to its post-race value once shown, rather than sitting at
# a fixed value.

class _GrowthBar(QWidget):
    def __init__(self, label: str, color_hex: str, old_value: float, new_value: float):
        super().__init__()
        self._label = label
        self._color = QColor(color_hex)
        self._old   = old_value
        self._new   = new_value
        self._fill  = old_value / 100.0
        self._anim  = None
        self.setFixedHeight(38)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def _get_fill(self):
        return self._fill

    def _set_fill(self, v):
        self._fill = v
        self.update()

    fill = pyqtProperty(float, _get_fill, _set_fill)

    def animate(self, duration=900, delay=0):
        anim = QPropertyAnimation(self, b'fill', self)
        anim.setStartValue(self._old / 100.0)
        anim.setEndValue(self._new / 100.0)
        anim.setDuration(duration)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim = anim   # keep a reference alive for the animation's duration
        QTimer.singleShot(delay, anim.start)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        label_w, val_w = 200, 100
        bar_x = label_w
        bar_w = w - label_w - val_w - 12

        p.setFont(QFont('Segoe UI', 13))
        p.setPen(QColor('#ffffff'))
        p.drawText(QRect(0, 0, label_w, h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._label)

        tr = QRectF(bar_x, h / 2 - 7, bar_w, 14)
        tp = QPainterPath(); tp.addRoundedRect(tr, 7, 7)
        p.fillPath(tp, QColor(22, 22, 38, 200))

        fw = max(14.0, bar_w * self._fill)
        fr = QRectF(bar_x, h / 2 - 7, fw, 14)
        fp = QPainterPath(); fp.addRoundedRect(fr, 7, 7)
        g = QLinearGradient(bar_x, 0, bar_x + fw, 0)
        g.setColorAt(0, self._color.darker(145))
        g.setColorAt(1, self._color)
        p.fillPath(fp, g)

        p.setFont(QFont('Segoe UI', 13, QFont.Weight.Bold))
        p.setPen(QColor('#ffffff'))
        p.drawText(QRect(w - val_w, 0, val_w - 54, h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   f'{self._new:.2f}')

        delta = self._new - self._old
        p.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
        p.setPen(QColor('#5eff7e'))
        p.drawText(QRect(w - 54, 0, 54, h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   f'+{delta:.2f}')


class ProgressionPanel(QDialog):
    """Career only: shown right after a race's results reveal, animating each
    growth stat's bar from its pre-race value up to its post-race value."""

    _META = {name: (label, color) for name, label, color in STATS}

    def __init__(self, parent, race_num, position, xp, growth: dict, is_wet=False):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # A wet race adds a sixth bar (wet_performance), so size to the bar count.
        bar_order = [s for s in progression.GROWTH_STATS if s in growth]
        if 'wet_performance' in growth:
            bar_order.append('wet_performance')
        height = 180 + len(bar_order) * 48
        self.setFixedSize(560, height)
        geo = QApplication.primaryScreen().availableGeometry()
        self.move(geo.center().x() - 280, geo.center().y() - height // 2)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setStyleSheet(
            'QFrame { background-color: #111116; border: 1px solid #2a2a3a; border-radius: 12px; }'
            'QLabel { background: transparent; border: none; color: #ffffff; }'
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(32, 26, 32, 22)
        cl.setSpacing(10)

        pos_text = 'DNF' if position is None else f'P{position}'
        weather = '  ·  WET 🌧' if is_wet else ''
        title = QLabel(f'RACE {race_num} RESULT  ·  {pos_text}{weather}')
        title.setFont(QFont('Segoe UI', 16, QFont.Weight.Bold))
        title.setStyleSheet('letter-spacing: 1px;')
        cl.addWidget(title)

        xp_lbl = QLabel(f'+{xp:.2f} XP earned')
        xp_lbl.setFont(QFont('Segoe UI', 11))
        xp_lbl.setStyleSheet('color: #9b9bac;')
        cl.addWidget(xp_lbl)
        cl.addSpacing(14)

        self._bars = []
        for stat in bar_order:
            label, color = self._META[stat]
            old, new, _delta = growth[stat]
            bar = _GrowthBar(label, color, old, new)
            self._bars.append(bar)
            cl.addWidget(bar)

        cl.addStretch(1)
        hint = QLabel('Press Enter to continue')
        hint.setFont(QFont('Segoe UI', 9))
        hint.setStyleSheet('color: #666677;')
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(hint)

        root.addWidget(card)

    def showEvent(self, event):
        super().showEvent(event)
        for i, bar in enumerate(self._bars):
            bar.animate(delay=i * 90)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape):
            self.accept()
        else:
            super().keyPressEvent(event)


class RacePage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self._wiz       = wiz
        self._r1_done   = False
        self._both_done = False
        # Career runs Race 1 and Race 2 as two separate hub excursions; True
        # once the current excursion's race has finished revealing.
        self._career_session_done = False
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
            # Career: after Race 1 finishes, hand back to the hub (Race 2 is
            # the next excursion). After Race 2, fall through so global Enter
            # advances to the Standings round summary as usual.
            if (self._wiz.mode == 'career' and self._wiz.session_index <= 3
                    and self._career_session_done):
                self._wiz.return_to_hub_after_session()
                return True
            return False    # both races done -> global Enter advances
        return False

    def initializePage(self):
        if self._wiz.mode == 'career':
            self._init_career()
            return
        self._r1_done   = False
        self._both_done = False
        self._career_session_done = False
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
        self._tabs.setCurrentIndex(0)
        self.completeChanged.emit()

    def _init_career(self):
        """Career visits this page twice a round: Race 1 (session_index 3),
        then Race 2 (index 4). The Race 1 visit starts the round's races fresh;
        the Race 2 visit keeps Race 1's banked result (its table still shows it
        from the earlier visit) and runs only Race 2, so both classifications
        accumulate into race_pts / race_results for the round summary."""
        self._career_session_done = False
        self._stop_reveal(self._t_r1)
        self._stop_reveal(self._t_r2)
        self._status.setText('')
        if self._wiz.session_index <= 3:
            # Race 1 excursion — reset the round's race state.
            self._r1_done   = False
            self._both_done = False
            self._btn_r1.setEnabled(True)
            self._btn_r1.setText('▶  Run Race 1')
            self._btn_r2.setEnabled(False)
            self._btn_r2.setText('▶  Run Race 2')
            self._t_r1.setRowCount(0)
            self._t_r2.setRowCount(0)
            self._wiz.race_pts     = []
            self._wiz.race_results = []
            self._tabs.setCurrentIndex(0)
        else:
            # Race 2 excursion — Race 1 stays banked (its table still holds the
            # earlier reveal); enable only Race 2.
            self._r1_done   = True
            self._both_done = False
            self._btn_r1.setEnabled(False)
            self._btn_r1.setText('✓  Race 1')
            self._btn_r2.setEnabled(True)
            self._btn_r2.setText('▶  Run Race 2')
            self._t_r2.setRowCount(0)
            self._tabs.setCurrentIndex(1)
        self.completeChanged.emit()

    def _run(self, race_num):
        if race_num == 1:
            self._btn_r1.setEnabled(False)
        else:
            self._btn_r2.setEnabled(False)
        self._status.setText(f'Running Race {race_num}…')

        # forced_weather: Random Race takes its override from WeatherPage;
        # Career instead reuses the Season Hub's already-rolled forecast for
        # this weekend day (wiz.weekend_weather — see
        # p_season_hub._roll_session_weather) so the race that actually plays
        # out matches what the hub showed, rather than rolling independently.
        # Championship rounds visit neither, so forced_weather stays None
        # there (the plain WET_RACE_PROB_PCT dice roll in run_race()).
        if self._wiz.mode == 'random':
            forced_weather = self._wiz.forced_weather
        elif self._wiz.mode == 'career' and self._wiz.weekend_weather is not None:
            forced_weather = 'wet' if self._wiz.session_is_wet() else 'dry'
        else:
            forced_weather = None
        result_df, pts_df, meta = run_race(
            self._wiz.df, self._wiz.circuit, self._wiz.grid_all_df,
            forced_weather=forced_weather
        )
        self._wiz.race_pts.append(pts_df)
        self._wiz.race_results.append(
            result_df[['name', 'pos', 'dnf', 'fastest_lap', 'grid_pos']].copy())
        if meta['fl_name'] is not None:
            self._wiz.race_fastest_laps.append((meta['fl_time'], meta['fl_name']))

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
        career  = self._wiz.mode == 'career'
        tail    = '   ·   Enter → hub' if (career and race_num == 1) else ''
        self._status.setText(
            f"✓ Race {race_num}  {weather}  |  Winner: {winner}  |  ⚡ FL: {fl}{tail}"
        )
        if race_num == 1:
            self._r1_done = True
            if career:
                # Race 1 is its own hub session — Enter returns to the hub
                # rather than unlocking Race 2 here (that's the next excursion).
                self._career_session_done = True
            else:
                self._btn_r2.setEnabled(True)
        else:
            self._both_done = True
            if career:
                self._career_session_done = True
            self.completeChanged.emit()
        if career:
            self._show_progression(race_num, result_df, meta)

    def _show_progression(self, race_num, result_df, meta):
        """Career only: award this race's XP to the custom rider and show the
        stat-growth panel — see src/progression.py for the formula. A wet race
        additionally boosts wet_performance."""
        wiz = self._wiz
        rider = wiz.load_career_rider()
        if not rider:
            return
        row = result_df[result_df['name'] == rider['name']]
        if row.empty:
            return
        row = row.iloc[0]
        position = None if bool(row['dnf']) else int(row['pos'])
        year = wiz.years_racing()
        xp = progression.xp_for_race(position, year)
        wet_bonus = progression.wet_perf_bonus(position, year) if meta['is_wet'] else 0.0
        growth = progression.apply_growth(rider, xp, wet_bonus)
        wiz.save_career_rider(rider)
        for stat in growth:
            wiz.df.loc[wiz.df['name'] == rider['name'], stat] = rider[stat]
        ProgressionPanel(self, race_num, position, xp, growth, meta['is_wet']).exec()

    def isComplete(self):
        return self._both_done
