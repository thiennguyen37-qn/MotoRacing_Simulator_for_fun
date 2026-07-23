import json
import pandas as pd
from pathlib import Path
from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout,
                              QPushButton, QLabel, QTabWidget, QTableWidgetItem,
                              QHeaderView, QDialog)
from PyQt6.QtGui import QFont, QColor, QBrush, QIcon
from PyQt6.QtCore import Qt, QSize

from app.widgets.table_utils import (make_table, fill_table, row_bg,
                                      TEAM_COLOR, _DEFAULT_COLOR, GRID_ROLE)
from app.pages.p_calendar import _ISO2
from app.wizard import SEASON_MODES
from src.simulator import POINTS

def _round_lap_records(wiz) -> dict:
    """Fastest lap set anywhere in the round currently in progress —
    {'race': (seconds, name) | None, 'session': (seconds, name) | None}.
    'race' only looks at the two races (feeds Season Hub's BRLC); 'session'
    folds in Practice and Qualifying too (BLC) — see
    p_season_hub._track_records, which picks the all-time min per circuit
    out of these per-round values."""
    race_candidates = list(getattr(wiz, 'race_fastest_laps', []))
    session_candidates = list(race_candidates)

    pr = getattr(wiz, 'practice_results', None)
    if pr is not None and not pr.empty:
        i = pr['best_lap_sec'].idxmin()
        session_candidates.append((float(pr.loc[i, 'best_lap_sec']), str(pr.loc[i, 'name'])))

    grid = getattr(wiz, 'grid_all_df', None)
    if grid is not None and not grid.empty and 'best_lap_sec' in grid.columns:
        valid = grid.dropna(subset=['best_lap_sec'])
        if not valid.empty:
            i = valid['best_lap_sec'].idxmin()
            session_candidates.append((float(valid.loc[i, 'best_lap_sec']), str(valid.loc[i, 'name'])))

    def _best(cands):
        return min(cands, key=lambda c: c[0]) if cands else None

    return {'race': _best(race_candidates), 'session': _best(session_candidates)}


_FLAGS = Path(__file__).parent.parent.parent / 'data' / 'flags'

# Wikipedia-style GP three-letter codes for the round headers
_CODE3 = {
    'Australia': 'AUS', 'Japan': 'JPN', 'Italy': 'ITA', 'Spain': 'SPA',
    'Germany': 'GER', 'United Kingdom': 'GBR', 'Brazil': 'BRA',
    'Argentina': 'ARG', 'Netherlands': 'NED', 'France': 'FRA',
    'Portugal': 'POR', 'Thailand': 'THA', 'Qatar': 'QAT',
}

# Result-cell colours — wiki semantics, tuned for the dark theme
_C_WIN  = QColor(148, 116, 24)    # 1st  — gold
_C_P2   = QColor(108, 112, 122)   # 2nd  — silver
_C_P3   = QColor(140, 84, 32)     # 3rd  — bronze
_C_PTS  = QColor(28, 96, 48)      # 4-15 — points finish (green)
_C_NOPT = QColor(42, 58, 104)     # 16+  — outside the points (blue)
_C_RET  = QColor(96, 42, 112)     # Ret  — DNF (purple)
_WHITE  = QColor(240, 240, 248)

# Tab chips: the selected section is always a filled box, never just tinted
# text — its fill tells you whether the cursor is on it, you're inside it,
# or the cursor moved on to the action buttons.
_TABS_BASE_SS = """
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
"""
_TAB_SEL_BROWSE  = 'background: #e02840; color: #ffffff;'           # cursor here
_TAB_SEL_INSIDE  = 'background: rgba(224,40,64,90); color: #ffffff;'  # entered
_TAB_SEL_ELSEWHERE = 'background: rgba(255,255,255,16); color: #ccccdd;'  # cursor on buttons

# Action buttons: BOTH states carry identical padding/border metrics — mixing
# a styled state with the native (Fusion) one makes the button change size
# whenever focus moves onto it.
_BTN_FOCUS_SS = """
    QPushButton {
        background: #e02840; color: #ffffff;
        border: 1px solid #ff6080; border-radius: 6px;
        padding: 0 18px; font-weight: 600;
    }
"""
_BTN_IDLE_SS = """
    QPushButton {
        background: #20202a; color: #aaaabb;
        border: 1px solid #2a2a3a; border-radius: 6px;
        padding: 0 18px; font-weight: 600;
    }
"""


class _FlagHeaderView(QHeaderView):
    """Header that truly centres icon-only sections (QHeaderView lays icons
    out beside the text slot, which leaves flag headers a few px off-centre).
    Text sections are painted to match the app's stylesheet header look."""

    _BGC  = QColor('#0c0c12')
    _LINE = QColor('#1c1c2c')
    _TXT  = QColor('#ffffff')

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setSectionsClickable(False)

    def sectionSizeFromContents(self, logicalIndex):
        base = super().sectionSizeFromContents(logicalIndex)
        return QSize(base.width(), max(base.height(), 30))

    def paintSection(self, painter, rect, logicalIndex):
        painter.save()
        painter.fillRect(rect, self._BGC)
        painter.setPen(self._LINE)
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())

        m = self.model()
        icon = m.headerData(logicalIndex, Qt.Orientation.Horizontal,
                            Qt.ItemDataRole.DecorationRole)
        if isinstance(icon, QIcon) and not icon.isNull():
            pm = icon.pixmap(22, 15)
            sz = pm.deviceIndependentSize()
            painter.drawPixmap(rect.x() + int((rect.width() - sz.width()) / 2),
                               rect.y() + int((rect.height() - sz.height()) / 2), pm)
        else:
            text = m.headerData(logicalIndex, Qt.Orientation.Horizontal,
                                Qt.ItemDataRole.DisplayRole)
            if text:
                f = QFont('Segoe UI')
                f.setPixelSize(9)
                f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
                painter.setFont(f)
                painter.setPen(self._TXT)
                painter.drawText(rect.adjusted(12, 0, -12, 0),
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                 str(text).upper())
        painter.restore()


class ChampionshipPage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self._wiz = wiz
        self.setTitle('Standings')

        layout = QVBoxLayout(self)

        # Control row — next round / finish
        ctrl = QHBoxLayout()
        self._btn_next = QPushButton('')
        self._btn_next.setFixedHeight(34)
        self._btn_next.setAutoDefault(False)
        # keyboard focus is managed by _browse_focus — a real Tab-key focus on
        # the button would silently desync from the page's navigation state
        self._btn_next.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_next.clicked.connect(self._on_next_clicked)
        # second action, shown only once the season is over: finish -> home
        # (while _btn_next becomes "Next Season" -> back to the calendar)
        self._btn_finish = QPushButton('Finish Championship')
        self._btn_finish.setFixedHeight(34)
        self._btn_finish.setAutoDefault(False)
        self._btn_finish.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_finish.clicked.connect(self._finish_clicked)
        self._btn_finish.setVisible(False)
        self._info_lbl = QLabel('')
        self._info_lbl.setFont(QFont('Segoe UI', 10))
        ctrl.addWidget(self._btn_next)
        ctrl.addWidget(self._btn_finish)
        ctrl.addWidget(self._info_lbl, 1)
        layout.addLayout(ctrl)

        self._tabs = QTabWidget()
        self._t_riders = make_table(['P', '#', 'RIDER', 'TEAM', 'MANUFACTURER', 'PTS'])
        self._t_teams  = make_table(['P', 'TEAM', 'PTS'])
        self._t_manu   = make_table(['P', 'MANUFACTURER', 'PTS'])
        # Results matrix (wiki style): two columns per round (race 1 / race 2),
        # headers = GP country code + flag, cells = finishing position with the
        # classic colour code. Columns for every round exist upfront; unraced
        # ones are hidden. Wider than the viewport -> horizontal scroll (←/→).
        self._n_rounds = len(wiz.circuits_df)
        self._t_results = make_table(
            ['P', '#', 'RIDER', 'BIKE', 'TEAM']
            + ['—'] * (2 * self._n_rounds)      # headers set per-season in _fill_results
            + ['PTS'])
        self._t_results.setHorizontalHeader(_FlagHeaderView(self._t_results))
        self._tabs.addTab(self._t_riders,  'Riders')
        self._tabs.addTab(self._t_teams,   'Teams')
        self._tabs.addTab(self._t_manu,    'Manufacturers')
        self._tabs.addTab(self._t_results, 'Results')
        layout.addWidget(self._tabs)

        self._rider_total = None
        self._team_total  = None
        self._manu_total  = None

        # Two-level navigation: ←/→ browse tabs + the Next-Round button,
        # Enter dives into the focused tab (arrows then scroll its content),
        # Esc climbs back out to browse mode.
        self._browse_focus  = 0       # 0..count-1 = tabs, count(+1) = button(s)
        self._in_content    = False
        self._history_saved = False

    # ── Wizard flow ───────────────────────────────────────────────────────────

    def initializePage(self):
        wiz = self._wiz

        if wiz.mode in SEASON_MODES:
            season = wiz.season_df if wiz.season_df is not None else wiz.circuits_df
            n   = len(season)
            idx = wiz.circuit_index
            label = 'World Championship' if wiz.mode == 'championship' else 'Career Season'
            self.setSubTitle(f"{wiz.season_year} {label}  ·  "
                             f"Round {idx + 1}/{n}  —  {wiz.circuit['circuit_name']}")
            self._info_lbl.setText(
                f"  Season standing after {idx + 1} of {n} rounds"
                + (f"  |  {n - idx - 1} round(s) remaining" if idx < n - 1 else "  |  Final standings")
            )
            if idx < n - 1:
                # Career runs the weekend from the Season Hub, so this button
                # just closes the grand prix and drops back there — hence a
                # plain "Finish" (no icon, no round counter). Championship
                # walks straight into the next round, so it keeps the counter.
                self._btn_next.setText('Finish' if wiz.mode == 'career'
                                       else f'▶  Next Round ({idx + 2}/{n})')
                self._btn_finish.setVisible(False)
            elif wiz.mode == 'career':
                # Season finale mirrors a normal round: one plain "Finish" that
                # drops back to the Career Hub, whose "TO NEXT SEASON" card then
                # opens next year's setup (no separate "Next Season"/"Finish
                # Championship" here — the hub's Main Menu tab / Esc exits home).
                self._btn_next.setText('Finish')
                self._btn_finish.setVisible(False)
            else:
                self._btn_next.setText('▶  Next Season')
                self._btn_finish.setVisible(True)
        else:
            self.setSubTitle(f"Overall standings after 2 races at {wiz.circuit['circuit_name']}.")
            self._info_lbl.setText('')
            self._btn_next.setText('🏁  Finish')
            self._btn_finish.setVisible(False)

        # per-round results only make sense across a season
        self._tabs.setTabVisible(3, wiz.mode in SEASON_MODES)

        self._compute()

        self._in_content    = False
        self._browse_focus  = 0
        self._history_saved = False
        self._tabs.setCurrentIndex(0)
        self._update_nav_styles()

    def handle_key(self, key: int) -> bool:
        K = Qt.Key
        if self._in_content:
            if key in (K.Key_Up, K.Key_Down):
                bar = self._tabs.currentWidget().verticalScrollBar()
                bar.setValue(bar.value() + (bar.singleStep() if key == K.Key_Down else -bar.singleStep()))
                self._wiz.suppress_next_sfx = True   # scrolling content — no SFX
                return True
            if key in (K.Key_Left, K.Key_Right):
                bar = self._tabs.currentWidget().horizontalScrollBar()
                if bar.maximum() > 0:      # wide Results grid
                    step = max(bar.singleStep(), 52)
                    bar.setValue(bar.value() + (step if key == K.Key_Right else -step))
                self._wiz.suppress_next_sfx = True   # scrolling content — no SFX
                return True
            if key in (K.Key_Escape, K.Key_Backspace,
                       K.Key_Return, K.Key_Enter, K.Key_Space):
                # Enter toggles back out too — a dead key here just left the
                # user stuck with no feedback when they wanted the button
                self._in_content = False
                self._update_nav_styles()
                return True
            return False

        # browse mode: ←/→ (or Tab) move across tabs + the action button(s)
        if key in (K.Key_Left, K.Key_Right, K.Key_Tab):
            step = -1 if key == K.Key_Left else 1
            n = self._tabs.count() + self._n_buttons()
            i = self._browse_focus
            for _ in range(n):
                i = (i + step) % n
                if i >= self._tabs.count() or self._tabs.isTabVisible(i):
                    break
            self._browse_focus = i
            if i < self._tabs.count():
                self._tabs.setCurrentIndex(i)
            self._update_nav_styles()
            return True
        if key in (K.Key_Return, K.Key_Enter, K.Key_Space):
            btns = self._nav_buttons()
            slot = self._browse_focus - self._tabs.count()
            if 0 <= slot < len(btns):
                btns[slot].click()
            else:
                self._in_content = True
                self._update_nav_styles()
            return True
        if key in (K.Key_Escape, K.Key_Backspace) and self._wiz.mode in SEASON_MODES:
            self._confirm_home()      # save & exit to Home (with a confirm)
            return True
        return False    # random mode: Esc/Backspace fall through -> wizard.back()

    def _nav_buttons(self) -> list:
        return [b for b in (self._btn_next, self._btn_finish)
                if b.isVisibleTo(self)]

    def _n_buttons(self) -> int:
        return len(self._nav_buttons())

    def _update_nav_styles(self):
        on_btn = self._browse_focus >= self._tabs.count()
        if self._in_content:
            sel = _TAB_SEL_INSIDE
        elif on_btn:
            sel = _TAB_SEL_ELSEWHERE
        else:
            sel = _TAB_SEL_BROWSE
        # Re-applying the QTabWidget stylesheet re-polishes every table inside it
        # (~40ms). Only do it when the selection style actually changes.
        ss = _TABS_BASE_SS + f'QTabBar::tab:selected {{ {sel} }}'
        if ss != getattr(self, '_last_tabs_ss', None):
            self._tabs.setStyleSheet(ss)
            self._last_tabs_ss = ss
        for slot, btn in enumerate(self._nav_buttons()):
            focused = (not self._in_content
                       and self._browse_focus == self._tabs.count() + slot)
            want = _BTN_FOCUS_SS if focused else _BTN_IDLE_SS
            if btn.styleSheet() != want:
                btn.setStyleSheet(want)

    def nextId(self):
        # The championship loop (Standings -> Practice) is driven by
        # _advance_round(); QWizard.next() refuses to visit a page already in
        # its history, so this page is always terminal for the wizard itself.
        return -1

    # ── Season loop ───────────────────────────────────────────────────────────

    def _has_next_round(self) -> bool:
        wiz = self._wiz
        season = wiz.season_df if wiz.season_df is not None else wiz.circuits_df
        return wiz.mode in SEASON_MODES and wiz.circuit_index < len(season) - 1

    def _on_next_clicked(self):
        if self._has_next_round():
            self._advance_round()
        elif self._wiz.mode == 'career':
            self._finish_season_to_hub()
        elif self._wiz.mode in SEASON_MODES:      # championship
            self._next_season()
        else:
            self._wiz.accept()          # random race: finish -> home

    def _finish_clicked(self):
        """Archive the season and return home. The career carries on: a
        next-season marker keeps Continue enabled, and entering it opens next
        year's calendar setup."""
        self._save_history()
        self._wiz.save_next_season_marker()
        self._wiz.accept()

    def _confirm_home(self):
        """Esc on the standings: confirm, then save. Career returns to the
        Season Hub — it already has its own Main Menu exit from there —
        while Championship/Random go all the way back to Home. Mid-season
        banks the round just raced (CONTINUE resumes at the next one); a
        finished season is archived with a marker so CONTINUE opens next
        year's calendar."""
        from app.pages.p_home import ExitDialog
        wiz = self._wiz
        to_hub = wiz.mode == 'career'
        dlg = ExitDialog(wiz, message='Return to Career Hub?' if to_hub else 'Return to Home?',
                         confirm_text='Yes')
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if self._has_next_round():
            self._bank_round()
            wiz.save_season()
        else:
            self._save_history()
            wiz.save_next_season_marker()
            if to_hub:
                # Career final round: land on the hub's "TO NEXT SEASON"
                # summary, same as pressing Finish (below).
                self._mark_season_complete()
        if not to_hub:
            wiz.accept()
            return
        # Career returns to the hub with the weekend reset to its first session
        # (the round just banked, or the finished season archived above).
        wiz.session_index = 0
        while wiz.currentId() not in (wiz.ID_SEASON_HUB, wiz.startId()):
            wiz.back()
        if wiz.currentId() == wiz.ID_SEASON_HUB:
            wiz.currentPage().resume_at_hub()

    def _next_season(self):
        """Championship: archive the finished season and rewind to the Season
        Calendar. (Career routes through the Season Hub instead — see
        _finish_season_to_hub.)"""
        wiz = self._wiz
        self._save_history()
        # marker instead of a bare clear: if the app closes while the new
        # calendar is being set up, CONTINUE still offers the next season
        wiz.save_next_season_marker()
        wiz.begin_next_season_setup()

    def _mark_season_complete(self):
        """Flag the finished season and drop its running state so the Season
        Hub shows the 'TO NEXT SEASON' summary (reading the just-archived
        season, not a duplicate live copy) and the next season starts clean.
        The season must already be archived (_save_history) first."""
        wiz = self._wiz
        wiz.season_complete = True
        wiz.circuit_index = 0
        wiz.all_race_pts  = []
        wiz.race_pts      = []
        wiz.race_results  = []
        wiz.race_fastest_laps = []
        wiz.round_results = []

    def _finish_season_to_hub(self):
        """Career season finale: archive the completed season, then drop back
        to the Career Hub in its 'season complete' state (the "TO NEXT SEASON"
        summary) — mirroring how a normal round's Finish returns to the hub.
        Advancing from that hub card opens next year's calendar (see
        SeasonHubPage._go_next / wizard.begin_next_season_setup)."""
        wiz = self._wiz
        self._save_history()               # archive the just-finished season (once)
        wiz.save_next_season_marker()      # quitting now still CONTINUEs into next year
        self._mark_season_complete()
        wiz.session_index = 0
        wiz.return_to_hub()

    def _bank_round(self):
        """Fold the just-raced round into the season totals."""
        wiz = self._wiz
        wiz.all_race_pts.extend(wiz.race_pts)
        wiz.race_pts = []
        wiz.round_results.append({'circuit': wiz.circuit['circuit_name'],
                                  'country': wiz.circuit['country'],
                                  'races': wiz.race_results,
                                  'lap_records': _round_lap_records(wiz)})
        wiz.race_results = []
        wiz.race_fastest_laps = []
        wiz.circuit_index += 1

    def _advance_round(self):
        """Bank this round's points and rewind the wizard to Practice.

        QWizard.next() can't loop back to an already-visited page, so the
        next round is started by walking the history back to PracticePage and
        re-initializing it (back() itself never calls initializePage).
        """
        wiz = self._wiz
        self._bank_round()
        wiz.save_season()               # resume point: start of the next round
        if wiz.mode == 'career':
            # Career runs the weekend from the hub — drop back to the Season Hub
            # at the next round's first session (Practice) instead of walking
            # straight into the Practice page. The hub reads this as a between-GP
            # boundary (session_index 0, circuit_index just bumped > 0) and shows
            # the "TO NEXT GRAND PRIX" recap — see SeasonHubPage._refresh_data.
            wiz.session_index = 0
            wiz.return_to_hub()
            return
        while wiz.currentId() not in (wiz.ID_PRACTICE, wiz.startId()):
            wiz.back()
        if wiz.currentId() == wiz.ID_PRACTICE:
            wiz.currentPage().initializePage()

    # ── History ───────────────────────────────────────────────────────────────

    def _season_rounds(self):
        """Banked rounds + the current (not yet banked) one."""
        wiz = self._wiz
        rounds = list(wiz.round_results)
        if wiz.race_results:
            rounds.append({'circuit': wiz.circuit['circuit_name'],
                           'country': wiz.circuit['country'],
                           'races': wiz.race_results,
                           'lap_records': _round_lap_records(wiz)})
        return rounds

    def _save_history(self):
        """Append the finished season to data/history.json (once).

        Hard invariant: only a season that is definitely over may be
        archived — enforced here, not just at the call sites."""
        wiz = self._wiz
        if (self._history_saved or wiz.mode not in SEASON_MODES
                or self._rider_total is None or self._has_next_round()):
            return
        rounds = self._season_rounds()

        def _blank_stat():
            return {'wins': 0, 'podiums': 0, 'poles': 0, 'fastest_laps': 0,
                    'dnfs': 0, 'races': 0}

        stats = {}
        for rd in rounds:
            races = rd['races']
            for df in races:
                for _, r in df.iterrows():
                    s = stats.setdefault(r['name'], _blank_stat())
                    s['races'] += 1
                    if bool(r['dnf']):
                        s['dnfs'] += 1
                    else:
                        pos = int(r['pos'])
                        s['wins']    += pos == 1
                        s['podiums'] += pos <= 3
                    if bool(r.get('fastest_lap', False)):
                        s['fastest_laps'] += 1
            # Pole is set once per round (both races share the grid), so count it
            # from the round's first race to avoid double-counting.
            if races and 'grid_pos' in races[0].columns:
                for _, r in races[0][races[0]['grid_pos'] == 1].iterrows():
                    stats.setdefault(r['name'], _blank_stat())['poles'] += 1

        standings = [{'name': str(r['name']), 'team': str(r['team']),
                      'manufacturer': str(r['manufacturer']), 'points': int(r['points'])}
                     for _, r in self._rider_total.iterrows()]

        # Per-round, per-race classifications — everything the History page needs
        # to rebuild the results matrix and the race-by-race stats.
        roster = {str(r['name']): (int(r['bike_number']), str(r['team']),
                                   str(r['manufacturer']))
                  for _, r in wiz.df.iterrows()}
        rounds_detail = []
        for rd in rounds:
            races_out = []
            for df in rd['races']:
                race = []
                for _, r in df.iterrows():
                    name = str(r['name'])
                    bn, team, manu = roster.get(name, (0, '', ''))
                    pos, dnf = int(r['pos']), bool(r['dnf'])
                    race.append({
                        'name': name, 'team': team, 'manufacturer': manu,
                        'bike_number': bn, 'pos': pos, 'dnf': dnf,
                        'fastest_lap': bool(r.get('fastest_lap', False)),
                        'pole': int(r.get('grid_pos', 0)) == 1,
                        'points': 0 if dnf else int(POINTS.get(pos, 0)),
                    })
                races_out.append(race)
            rounds_detail.append({'circuit': str(rd['circuit']),
                                  'country': str(rd['country']), 'races': races_out,
                                  'lap_records': rd.get('lap_records')})

        entry = {
            'year':          wiz.season_year,
            'rounds':        len(rounds),
            'calendar':      [str(rd['circuit']) for rd in rounds],
            'champion':      standings[0] if standings else None,
            'standings':     standings,
            'stats':         stats,
            'rounds_detail': rounds_detail,
        }

        history_path = wiz.history_path()
        data = {'seasons': []}
        if history_path.exists():
            try:
                data = json.loads(history_path.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, OSError):
                pass                       # corrupt file -> start a fresh log
        data.setdefault('seasons', []).append(entry)
        history_path.write_text(json.dumps(data, indent=2), encoding='utf-8')
        self._history_saved = True

        self._maybe_offer_number_switch(standings)

    def _maybe_offer_number_switch(self, standings):
        """Career only: a top-3 finish can swap the rider onto #1/#2/#3 for
        next season, MotoGP-style — offered once, right after the season is
        archived, so the choice doesn't affect this season's own results."""
        wiz = self._wiz
        if wiz.mode != 'career':
            return
        rider = wiz.load_career_rider()
        if not rider:
            return
        pos = next((i + 1 for i, s in enumerate(standings) if s['name'] == rider['name']), None)
        if pos not in (1, 2, 3) or int(rider['bike_number']) == pos:
            return
        from app.pages.p_home import ExitDialog
        dlg = ExitDialog(
            wiz,
            message=f"P{pos} in the championship!\nSwitch to bike #{pos} next season?",
            confirm_text=f"Yes, switch to #{pos}")
        if dlg.exec() == QDialog.DialogCode.Accepted:
            rider['bike_number'] = pos
            wiz.save_career_rider(rider)
            wiz.df.loc[wiz.df['name'] == rider['name'], 'bike_number'] = pos

    # ── Data ─────────────────────────────────────────────────────────────────

    def _season_results(self):
        """Per-race classifications feeding the current standings.

        Parallels `all_pts` in `_compute`: banked rounds plus the current
        (not-yet-banked) one for a championship, or just this session's races
        otherwise. Each DataFrame carries name/pos/dnf.
        """
        wiz = self._wiz
        if wiz.mode in SEASON_MODES:
            banked = [df for rd in wiz.round_results for df in rd['races']]
            return banked + wiz.race_results
        return wiz.race_results

    def _tiebreak_counts(self, results):
        """Countback vectors keyed by rider, team and manufacturer.

        Each vector is (n_P1, …, n_P24): how many finishes at each position,
        mirroring how points are earned — a rider counts their own results, a
        team counts both its riders', a manufacturer counts its best bike per
        race. DNFs and finishes past P24 don't count.
        """
        roster = {str(r['name']): (str(r['team']), str(r['manufacturer']))
                  for _, r in self._wiz.df.iterrows()}
        rider, team, manu = {}, {}, {}
        for df in results:
            if df is None or df.empty:
                continue
            best_manu = {}
            for _, r in df.iterrows():
                if bool(r.get('dnf', False)):
                    continue
                pos = int(r['pos'])
                if not (1 <= pos <= 24):
                    continue
                name = str(r['name'])
                t, m = roster.get(name, ('', ''))
                rider.setdefault(name, [0] * 24)[pos - 1] += 1
                team.setdefault(t, [0] * 24)[pos - 1] += 1
                if m and (m not in best_manu or pos < best_manu[m]):
                    best_manu[m] = pos
            for m, pos in best_manu.items():
                manu.setdefault(m, [0] * 24)[pos - 1] += 1
        as_tuples = lambda d: {k: tuple(v) for k, v in d.items()}
        return as_tuples(rider), as_tuples(team), as_tuples(manu)

    @staticmethod
    def _rank(totals, countback, key_col):
        """Order a points-summed table by points, then countback (both desc)."""
        zero = (0,) * 24
        order = sorted(
            totals.index,
            key=lambda i: (int(totals.at[i, 'points']),)
            + countback.get(str(totals.at[i, key_col]), zero),
            reverse=True,
        )
        return totals.loc[order].reset_index(drop=True)

    def _compute(self):
        wiz = self._wiz

        if wiz.mode in SEASON_MODES:
            # Cumulative: all previous circuits + current circuit
            all_pts = wiz.all_race_pts + wiz.race_pts
        else:
            all_pts = wiz.race_pts

        if not all_pts:
            return

        combined = pd.concat(all_pts, ignore_index=True)

        # Countback tie-breakers: riders/teams/manufacturers level on points are
        # split by number of wins, then 2nds, then 3rds … down to P24.
        rider_cb, team_cb, manu_cb = self._tiebreak_counts(self._season_results())

        self._rider_total = self._rank(
            combined.groupby(['name', 'bike_number', 'team', 'manufacturer'],
                             as_index=False)['points'].sum(),
            rider_cb, 'name')
        self._team_total = self._rank(
            combined.groupby('team', as_index=False)['points'].sum(),
            team_cb, 'team')
        manu_per_race = [r.groupby('manufacturer', as_index=False)['points'].max() for r in all_pts]
        self._manu_total = self._rank(
            pd.concat(manu_per_race).groupby('manufacturer', as_index=False)['points'].sum(),
            manu_cb, 'manufacturer')

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

        if wiz.mode in SEASON_MODES:
            self._fill_results()

    @staticmethod
    def _result_cell(res):
        """res: (pos, dnf) or None -> coloured QTableWidgetItem, wiki-style."""
        item = QTableWidgetItem()
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        item.setFont(QFont('Consolas', 9, QFont.Weight.Bold))
        item.setData(GRID_ROLE, True)   # black frame between result cells
        if res is None:
            item.setBackground(QBrush(row_bg(_DEFAULT_COLOR)))
            return item
        pos, dnf = res
        if dnf:
            txt, bg = 'Ret', _C_RET
        else:
            txt = str(pos)
            bg = (_C_WIN if pos == 1 else _C_P2 if pos == 2 else
                  _C_P3 if pos == 3 else _C_PTS if pos <= 15 else _C_NOPT)
        item.setText(txt)
        item.setBackground(QBrush(bg))
        item.setForeground(QBrush(_WHITE))
        return item

    def _fill_results(self):
        """Results tab — wiki-style season grid: one column per race (two per
        round), coloured by finishing position, 'Ret' for DNF."""
        wiz = self._wiz
        season = wiz.season_df if wiz.season_df is not None else wiz.circuits_df
        rounds = list(wiz.round_results)
        if wiz.race_results:   # current round (already raced, not banked yet)
            rounds.append({'circuit': wiz.circuit['circuit_name'],
                           'country': wiz.circuit['country'],
                           'races': wiz.race_results})

        t = self._t_results
        RES0 = 5                      # first result column (after P/#/RIDER/BIKE/TEAM)

        # Round headers follow the season calendar: flag only (country code
        # is used just as a fallback when the flag file is missing)
        for k in range(min(self._n_rounds, len(season))):
            country = str(season.iloc[k]['country'])
            flag    = _FLAGS / f"{_ISO2.get(country, '')}.png"
            for j in (0, 1):
                if flag.exists():
                    hdr = QTableWidgetItem(QIcon(str(flag)), '')
                else:
                    hdr = QTableWidgetItem(_CODE3.get(country, country[:3].upper()))
                hdr.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                t.setHorizontalHeaderItem(RES0 + 2 * k + j, hdr)

        # name -> (pos, dnf) per race, per round
        result_maps = []
        for rd in rounds:
            maps = []
            for df in rd['races']:
                maps.append({r['name']: (int(r['pos']), bool(r['dnf']))
                             for _, r in df.iterrows()})
            result_maps.append(maps)

        neutral_bg = row_bg(_DEFAULT_COLOR)
        t.setRowCount(len(self._rider_total))
        for i, r in self._rider_total.iterrows():
            team    = str(r['team'])
            color   = TEAM_COLOR.get(team, _DEFAULT_COLOR)
            lighter = QColor(min(color.red() + 80, 255),
                             min(color.green() + 80, 255),
                             min(color.blue() + 80, 255))

            def _plain(txt, fg=_WHITE, bold=False, center=False, size=10):
                it = QTableWidgetItem(str(txt))
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                it.setBackground(QBrush(neutral_bg))
                it.setForeground(QBrush(fg))
                it.setFont(QFont('Segoe UI', size,
                                 QFont.Weight.Bold if bold else QFont.Weight.Normal))
                if center:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
                return it

            p_item = _plain(i + 1, bold=True, center=True, size=9)
            p_item.setData(Qt.ItemDataRole.UserRole, color)   # delegate accent bar
            t.setItem(i, 0, p_item)
            t.setItem(i, 1, _plain(f"#{r['bike_number']}", fg=lighter, bold=True, center=True, size=11))
            t.setItem(i, 2, _plain(str(r['name']).upper(), bold=True, size=11))
            t.setItem(i, 3, _plain(r['manufacturer']))
            t.setItem(i, 4, _plain(r['team'], fg=QColor(190, 190, 205)))

            for k in range(self._n_rounds):
                for j in (0, 1):
                    res = None
                    if k < len(result_maps) and j < len(result_maps[k]):
                        res = result_maps[k][j].get(r['name'])
                    t.setItem(i, RES0 + 2 * k + j, self._result_cell(res))

            t.setItem(i, RES0 + 2 * self._n_rounds, _plain(r['points'], bold=True, center=True, size=11))

        for k in range(self._n_rounds):
            hide = k >= len(result_maps)
            t.setColumnHidden(RES0 + 2 * k,     hide)
            t.setColumnHidden(RES0 + 2 * k + 1, hide)

        t.resizeColumnsToContents()
        t.setColumnWidth(0, 44)
        t.setColumnWidth(1, 52)
        for k in range(len(result_maps)):
            t.setColumnWidth(RES0 + 2 * k,     52)
            t.setColumnWidth(RES0 + 2 * k + 1, 52)
