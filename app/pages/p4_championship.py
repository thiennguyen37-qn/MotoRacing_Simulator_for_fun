import pandas as pd
from pathlib import Path
from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout,
                              QPushButton, QLabel, QTabWidget, QTableWidgetItem,
                              QHeaderView)
from PyQt6.QtGui import QFont, QColor, QBrush, QIcon
from PyQt6.QtCore import Qt, QSize

from app.widgets.table_utils import (make_table, fill_table, row_bg,
                                      TEAM_COLOR, _DEFAULT_COLOR, GRID_ROLE)
from app.pages.p_calendar import _ISO2

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


class _FlagHeaderView(QHeaderView):
    """Header that truly centres icon-only sections (QHeaderView lays icons
    out beside the text slot, which leaves flag headers a few px off-centre).
    Text sections are painted to match the app's stylesheet header look."""

    _BGC  = QColor('#0c0c12')
    _LINE = QColor('#1c1c2c')
    _TXT  = QColor('#444455')

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
        self._btn_next.clicked.connect(self._on_next_clicked)
        self._info_lbl = QLabel('')
        self._info_lbl.setFont(QFont('Segoe UI', 10))
        ctrl.addWidget(self._btn_next)
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

    # ── Wizard flow ───────────────────────────────────────────────────────────

    def initializePage(self):
        wiz = self._wiz

        if wiz.mode == 'championship':
            season = wiz.season_df if wiz.season_df is not None else wiz.circuits_df
            n   = len(season)
            idx = wiz.circuit_index
            self.setSubTitle(f"Round {idx + 1}/{n}  —  {wiz.circuit['circuit_name']}")
            self._info_lbl.setText(
                f"  Season standing after {idx + 1} of {n} rounds"
                + (f"  |  {n - idx - 1} round(s) remaining" if idx < n - 1 else "  |  Final standings")
            )
            if idx < n - 1:
                self._btn_next.setText(f'▶  Next Round ({idx + 2}/{n})')
            else:
                self._btn_next.setText('🏆  Finish Championship')
        else:
            self.setSubTitle(f"Overall standings after 2 races at {wiz.circuit['circuit_name']}.")
            self._info_lbl.setText('')
            self._btn_next.setText('🏁  Finish')

        # per-round results only make sense across a season
        self._tabs.setTabVisible(3, wiz.mode == 'championship')

        self._compute()

    def handle_key(self, key: int) -> bool:
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            bar = self._tabs.currentWidget().verticalScrollBar()
            bar.setValue(bar.value() + (bar.singleStep() if key == Qt.Key.Key_Down else -bar.singleStep()))
            return True
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            # wide Results grid scrolls horizontally
            bar = self._tabs.currentWidget().horizontalScrollBar()
            if bar.maximum() > 0:
                step = max(bar.singleStep(), 52)
                bar.setValue(bar.value() + (step if key == Qt.Key.Key_Right else -step))
                return True
            return False
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._has_next_round():
            self._advance_round()
            return True
        # final round / random mode: fall through -> wizard's global Enter
        # handler sees nextId() == -1 and finishes
        return False

    def nextId(self):
        # The championship loop (Standings -> Practice) is driven by
        # _advance_round(); QWizard.next() refuses to visit a page already in
        # its history, so this page is always terminal for the wizard itself.
        return -1

    # ── Season loop ───────────────────────────────────────────────────────────

    def _has_next_round(self) -> bool:
        wiz = self._wiz
        season = wiz.season_df if wiz.season_df is not None else wiz.circuits_df
        return wiz.mode == 'championship' and wiz.circuit_index < len(season) - 1

    def _on_next_clicked(self):
        if self._has_next_round():
            self._advance_round()
        else:
            self._wiz.accept()

    def _advance_round(self):
        """Bank this round's points and rewind the wizard to Practice.

        QWizard.next() can't loop back to an already-visited page, so the
        next round is started by walking the history back to PracticePage and
        re-initializing it (back() itself never calls initializePage).
        """
        wiz = self._wiz
        wiz.all_race_pts.extend(wiz.race_pts)
        wiz.race_pts = []
        wiz.round_results.append({'circuit': wiz.circuit['circuit_name'],
                                  'country': wiz.circuit['country'],
                                  'races': wiz.race_results})
        wiz.race_results = []
        wiz.circuit_index += 1
        while wiz.currentId() not in (wiz.ID_PRACTICE, wiz.startId()):
            wiz.back()
        if wiz.currentId() == wiz.ID_PRACTICE:
            wiz.currentPage().initializePage()

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

        if wiz.mode == 'championship':
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
