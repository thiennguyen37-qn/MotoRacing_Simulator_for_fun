import json
from pathlib import Path
from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout, QGridLayout,
                              QLabel, QFrame, QWidget, QStackedWidget, QSizePolicy,
                              QTableWidgetItem, QHeaderView)
from PyQt6.QtGui import QFont, QPainter, QColor, QPen, QBrush, QPixmap, QIcon
from PyQt6.QtCore import (Qt, pyqtSignal, pyqtProperty, QPropertyAnimation,
                          QEasingCurve, QTimer, QSize)

from app.widgets.video_bg import VideoBackground
from app.widgets.table_utils import (TEAM_COLOR, MANU_COLOR, _DEFAULT_COLOR,
                                      make_table, row_bg, GRID_ROLE)
from app.pages.p_gallery import (_Card, _make_scroll_area, _divider, _section_label)
from app.pages.p_calendar import _ISO2
from app.wizard import HISTORY_FILE as _HISTORY

_FLAGS = Path(__file__).parent.parent.parent / 'data' / 'flags'
_FLAG_CACHE: dict = {}


def _flag_pixmap(country: str, height: int = 72, width: int | None = None):
    """Flag pixmap. With `width` given, scales to an exact width×height (uniform
    size for every flag); otherwise scales to `height`, keeping aspect ratio."""
    key = (country, height, width)
    if key in _FLAG_CACHE:
        return _FLAG_CACHE[key]
    iso = _ISO2.get(country, '')
    pix = None
    if iso:
        p = _FLAGS / f'{iso}.png'
        if p.exists():
            raw = QPixmap(str(p))
            if not raw.isNull():
                if width is not None:
                    pix = raw.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
                else:
                    pix = raw.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)
    _FLAG_CACHE[key] = pix
    return pix


def _row_sizes(n: int, max_per_row: int = 5) -> list:
    """Split n boxes into balanced rows (heavier rows in the middle), e.g. 13 → [4, 5, 4]."""
    if n <= 0:
        return []
    rows = max(1, (n + max_per_row - 1) // max_per_row)
    base, rem = divmod(n, rows)
    sizes = [base] * rows
    mid = rows // 2
    order = sorted(range(rows), key=lambda i: (abs(i - mid), i))   # middle rows first
    for k in range(rem):
        sizes[order[k]] += 1
    return sizes

_TINT = QColor(5, 5, 14, 218)   # same dark veil the Gallery split views use


class _TintPanel(QWidget):
    """A panel that veils the video background with _TINT (used by the split
    views and the empty state)."""
    def paintEvent(self, event):
        QPainter(self).fillRect(self.rect(), _TINT)

# Career-totals tiles, in the order the user asked for.
_TOTAL_COLS = [('RACES', 'races'), ('WINS', 'wins'), ('PODIUMS', 'podiums'),
               ('POLES', 'poles'), ('FASTEST LAPS', 'fastest_laps'),
               ('POINTS', 'pts'), ('TITLES', 'titles')]

# Season-by-season grid: (header, width, align). Same stats minus Titles, but
# with the rider's finishing position for that season.
_SBS_COLS = [('YEAR', 96, 'c'), ('POS', 78, 'c'), ('RACES', 92, 'c'),
             ('WINS', 84, 'c'), ('PODIUMS', 108, 'c'), ('POLES', 84, 'c'),
             ('F.LAPS', 96, 'c'), ('POINTS', 96, 'c')]


def _load_history() -> list:
    if not _HISTORY.exists():
        return []
    try:
        return json.loads(_HISTORY.read_text(encoding='utf-8')).get('seasons', [])
    except (json.JSONDecodeError, OSError):
        return []


def _team_color(team: str, manu: str = '') -> QColor:
    return TEAM_COLOR.get(team) or MANU_COLOR.get(manu, _DEFAULT_COLOR)


def _lighten(c: QColor, amt: int = 80) -> QColor:
    return QColor(min(c.red() + amt, 255), min(c.green() + amt, 255),
                  min(c.blue() + amt, 255))


def _medal_color(pos):
    """Gold / silver / bronze for the top three finishers, else None."""
    return {1: '#e8b53a', 2: '#cfd2d8', 3: '#cd7f32'}.get(pos)


def _aggregate_riders(seasons: list) -> dict:
    """All-time totals per rider, plus a per-season breakdown. Poles and fastest
    laps come from the recorded season stats (older archives lack them → 0)."""
    def _blank():
        return {'team': '', 'manufacturer': '', 'titles': 0, 'wins': 0,
                'podiums': 0, 'poles': 0, 'fastest_laps': 0, 'races': 0,
                'pts': 0, 'history': []}
    agg: dict[str, dict] = {}
    for s in seasons:
        year  = s.get('year', '')
        stats = s.get('stats', {})
        pos_map = {}
        for pos, st in enumerate(s.get('standings', []), start=1):
            pos_map[st['name']] = (pos, int(st.get('points', 0)),
                                   st.get('team', ''), st.get('manufacturer', ''))
        for name in set(pos_map) | set(stats):
            a = agg.setdefault(name, _blank())
            sst   = stats.get(name, {})
            per = {
                'races':        int(sst.get('races', 0)),
                'wins':         int(sst.get('wins', 0)),
                'podiums':      int(sst.get('podiums', 0)),
                'poles':        int(sst.get('poles', 0)),
                'fastest_laps': int(sst.get('fastest_laps', 0)),
            }
            for k, v in per.items():
                a[k] += v
            if name in pos_map:
                pos, pts, team, manu = pos_map[name]
                a['pts']         += pts
                a['team']         = team          # most recent
                a['manufacturer'] = manu
            else:
                pos, pts = None, 0
            a['history'].append({'year': year, 'pos': pos, 'points': pts, **per})
        champ = s.get('champion') or {}
        if champ.get('name') in agg:
            agg[champ['name']]['titles'] += 1
    return agg


# ── Shared little building blocks ─────────────────────────────────────────────

def _make_list_panel():
    """Left-column scroll list with no header (mirrors the Gallery panel body
    without its section title)."""
    outer = QWidget()
    outer.setAutoFillBackground(False)
    outer.setStyleSheet('background: transparent;')
    lo = QVBoxLayout(outer)
    lo.setContentsMargins(0, 0, 0, 0)
    lo.setSpacing(0)

    scroll = _make_scroll_area()
    list_cont = QWidget()
    list_cont.setAutoFillBackground(False)
    list_cont.setStyleSheet('background: transparent;')
    list_lay = QVBoxLayout(list_cont)
    list_lay.setContentsMargins(0, 8, 0, 0)
    list_lay.setSpacing(0)
    list_lay.addStretch(1)

    scroll.setWidget(list_cont)
    lo.addWidget(scroll, 1)
    return outer, list_lay, scroll


def _stat_tiles(pairs: list[tuple[str, object]], spacing: int = 30) -> QWidget:
    """A row of big-value / small-label tiles (mirrors the Gallery info row)."""
    w = QWidget()
    w.setStyleSheet('background: transparent;')
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for key, val in pairs:
        col = QVBoxLayout()
        col.setSpacing(3)
        vl = QLabel(str(val))
        vl.setFont(QFont('Segoe UI', 16, QFont.Weight.Bold))
        vl.setStyleSheet('color: #ffffff; background: transparent; border: none;')
        kl = QLabel(key)
        kl.setFont(QFont('Segoe UI', 7))
        kl.setStyleSheet('color: #8a8aa2; letter-spacing: 1px; background: transparent; border: none;')
        col.addWidget(vl, 0, Qt.AlignmentFlag.AlignHCenter)
        col.addWidget(kl, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addLayout(col)
    lay.addStretch(1)
    return w


def _sbs_row(cells: list, header: bool = False, medal: str = None) -> QWidget:
    """One row of the season-by-season grid. `medal` colours the year + position
    for a top-three season; every stat value stays white."""
    w = QWidget()
    w.setStyleSheet('background: transparent;')
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    for i, ((_h, width, align), text) in enumerate(zip(_SBS_COLS, cells)):
        lbl = QLabel(str(text))
        lbl.setFixedWidth(width)
        if header:
            lbl.setFont(QFont('Segoe UI', 9))
            lbl.setStyleSheet('color: #66667a; letter-spacing: 1px; background: transparent; border: none;')
        else:
            lbl.setFont(QFont('Segoe UI', 13, QFont.Weight.Bold))
            color = (medal if medal else '#ffffff') if i <= 1 else '#ffffff'
            lbl.setStyleSheet(f'color: {color}; background: transparent; border: none;')
        flag = Qt.AlignmentFlag.AlignLeft if align == 'l' else Qt.AlignmentFlag.AlignHCenter
        lbl.setAlignment(flag | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(lbl)
    lay.addStretch(1)
    return w


def _text_row(left: str, mid: str, right: str, left_color: str,
              mid_color: str = '#ccccdd', right_color: str = '#888899',
              left_w: int = 44) -> QWidget:
    w = QWidget()
    w.setStyleSheet('background: transparent;')
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)
    a = QLabel(left)
    a.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
    a.setFixedWidth(left_w)
    a.setStyleSheet(f'color: {left_color}; background: transparent; border: none;')
    lay.addWidget(a)
    b = QLabel(mid)
    b.setFont(QFont('Segoe UI', 10, QFont.Weight.Bold))
    b.setStyleSheet(f'color: {mid_color}; background: transparent; border: none;')
    lay.addWidget(b, 1)
    c = QLabel(right)
    c.setFont(QFont('Segoe UI', 9))
    c.setStyleSheet(f'color: {right_color}; background: transparent; border: none;')
    lay.addWidget(c)
    return w


# ── List items ────────────────────────────────────────────────────────────────

class _RankItem(QWidget):
    """Left-column entry for a rider (bike number + name + title badge)."""

    clicked = pyqtSignal(str)

    def __init__(self, bike_no, name: str, titles: int, team_color: QColor):
        super().__init__()
        self._name = name
        self._tc   = team_color
        self._tclt = _lighten(team_color)
        self._selected = False
        self.setFixedHeight(50)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(10)

        self._num_lbl = QLabel(f'#{bike_no}' if bike_no is not None else '—')
        self._num_lbl.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
        self._num_lbl.setFixedWidth(44)
        self._num_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._num_lbl.setStyleSheet('background: transparent; border: none; color: #555566;')
        lay.addWidget(self._num_lbl)

        nm = QLabel(name.upper())
        nm.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
        nm.setStyleSheet('background: transparent; border: none; color: #aaaabc;')
        lay.addWidget(nm, 1)

    def set_selected(self, v: bool):
        self._selected = v
        col = self._tclt.name() if v else '#555566'
        self._num_lbl.setStyleSheet(f'background: transparent; border: none; color: {col};')
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        if self._selected:
            p.fillRect(0, 0, w, h, QColor(20, 20, 36))
            p.fillRect(0, 0, 3, h, self._tc)
        else:
            p.fillRect(0, 0, w, h, QColor(7, 7, 16))
        p.setPen(QPen(QColor(18, 18, 30)))
        p.drawLine(0, h - 1, w, h - 1)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._name)
        super().mousePressEvent(e)


class _SeasonItem(QWidget):
    """Left-column entry for a season (year + champion)."""

    clicked = pyqtSignal(str)

    def __init__(self, key: str, year, team_color: QColor):
        super().__init__()
        self._key = key
        self._tc  = team_color
        self._selected = False
        self.setFixedHeight(54)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        self._year_lbl = QLabel(f'{year}  SEASON STATS')
        self._year_lbl.setFont(QFont('Segoe UI', 13, QFont.Weight.Bold))
        self._year_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._apply_text('#aaaabc')
        lay.addWidget(self._year_lbl, 1)

        # Selected card breathes a light red, like the home-page tiles.
        self._pulse = 0.0
        self._last_alpha = -1
        self._anim = QPropertyAnimation(self, b'pulse', self)
        self._anim.setDuration(1100)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._anim.setKeyValueAt(0.0, 0.0)
        self._anim.setKeyValueAt(0.5, 1.0)
        self._anim.setKeyValueAt(1.0, 0.0)

    def _apply_text(self, color: str):
        self._year_lbl.setStyleSheet(
            f'background: transparent; border: none; color: {color}; letter-spacing: 1px;')

    def _get_pulse(self) -> float:
        return self._pulse

    def _set_pulse(self, v: float):
        self._pulse = v
        if self._selected:
            a = int(40 + v * 70) // 6 * 6      # quantise repaints
            if a != self._last_alpha:
                self._last_alpha = a
                self.update()

    pulse = pyqtProperty(float, _get_pulse, _set_pulse)

    def set_selected(self, v: bool):
        self._selected = v
        self._apply_text('#ffffff' if v else '#aaaabc')
        if v:
            self._last_alpha = -1
            if self._anim.state() != QPropertyAnimation.State.Running:
                self._anim.start()
        else:
            self._anim.stop()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        if self._selected:
            a = int(40 + self._pulse * 70)      # light red that breathes
            p.fillRect(0, 0, w, h, QColor(224, 40, 64, a))
            p.fillRect(0, 0, 3, h, QColor(224, 40, 64))
        else:
            p.fillRect(0, 0, w, h, QColor(7, 7, 16))
        p.setPen(QPen(QColor(18, 18, 30)))
        p.drawLine(0, h - 1, w, h - 1)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._key)
        super().mousePressEvent(e)


# ── Detail panels ─────────────────────────────────────────────────────────────

class _RiderRecordDetail(QWidget):
    def __init__(self):
        super().__init__()
        self.setAutoFillBackground(False)
        self.setStyleSheet('background: transparent;')
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(48, 48, 48, 48)
        self._outer.setSpacing(0)
        self._placeholder('← Select a rider')

    def _placeholder(self, text: str):
        self._clear()
        ph = QLabel(text)
        ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph.setFont(QFont('Segoe UI', 13))
        ph.setStyleSheet('color: #2d2d44; background: transparent; border: none;')
        self._outer.addStretch(1)
        self._outer.addWidget(ph, 0, Qt.AlignmentFlag.AlignCenter)
        self._outer.addStretch(1)

    def _clear(self):
        while self._outer.count():
            item = self._outer.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

    def load(self, rec: dict):
        self._clear()
        cl = self._outer

        n = QLabel(rec['name'].upper())
        n.setFont(QFont('Segoe UI', 26, QFont.Weight.Bold))
        n.setStyleSheet('color: #ffffff; background: transparent; border: none;')
        cl.addWidget(n)
        cl.addSpacing(6)

        t = QLabel(f"{rec.get('team', '')}  ·  {rec.get('manufacturer', '')}")
        t.setFont(QFont('Segoe UI', 13))
        t.setStyleSheet('color: #ffffff; background: transparent; border: none;')
        cl.addWidget(t)
        cl.addSpacing(34)

        # ── Career totals (Races, Wins, Podiums, Poles, Fastest Laps, Points, Titles)
        cl.addWidget(_section_label('CAREER TOTALS'))
        cl.addSpacing(20)
        cl.addWidget(_stat_tiles([(label, rec.get(key, 0)) for label, key in _TOTAL_COLS]))
        cl.addSpacing(34)
        cl.addWidget(_divider())
        cl.addSpacing(26)

        # ── Season by season ───────────────────────────────────────────────
        cl.addWidget(_section_label('SEASON BY SEASON'))
        cl.addSpacing(14)
        cl.addWidget(_sbs_row([h for h, _w, _a in _SBS_COLS], header=True))
        cl.addSpacing(10)
        for h in sorted(rec['history'], key=lambda x: str(x['year']), reverse=True):
            pos = h['pos']
            cl.addWidget(_sbs_row([
                str(h['year']), f'P{pos}' if pos else '—', h['races'], h['wins'],
                h['podiums'], h['poles'], h['fastest_laps'], h['points'],
            ], medal=_medal_color(pos)))
            cl.addSpacing(12)

        cl.addStretch(1)


# ── Season results palette + builders ──────────────────────────────────────────
# Result-cell colours mirror the post-round Standings grid (p4_championship).
_C_WIN  = QColor(148, 116, 24)    # 1st  — gold
_C_P2   = QColor(108, 112, 122)   # 2nd  — silver
_C_P3   = QColor(140, 84, 32)     # 3rd  — bronze
_C_PTS  = QColor(28, 96, 48)      # points finish — green
_C_NOPT = QColor(42, 58, 104)     # outside points — blue
_C_RET  = QColor(96, 42, 112)     # DNF — purple
_CELL_W = QColor(240, 240, 248)

_CODE3 = {
    'Australia': 'AUS', 'Japan': 'JPN', 'Italy': 'ITA', 'Spain': 'SPA',
    'Germany': 'GER', 'United Kingdom': 'GBR', 'Brazil': 'BRA',
    'Argentina': 'ARG', 'Netherlands': 'NED', 'France': 'FRA',
    'Portugal': 'POR', 'Thailand': 'THA', 'Qatar': 'QAT',
}


def _pos_bg(pos: int, dnf: bool) -> QColor:
    if dnf:
        return _C_RET
    return (_C_WIN if pos == 1 else _C_P2 if pos == 2 else _C_P3 if pos == 3
            else _C_PTS if pos <= 15 else _C_NOPT)


def _rank_bg(rank: int, scored: bool) -> QColor:
    return (_C_WIN if rank == 1 else _C_P2 if rank == 2 else _C_P3 if rank == 3
            else _C_PTS if scored else _C_NOPT)


def _grid_cell(text, bg: QColor) -> QTableWidgetItem:
    it = QTableWidgetItem(str(text))
    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
    it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
    it.setFont(QFont('Consolas', 9, QFont.Weight.Bold))
    it.setData(GRID_ROLE, True)
    it.setBackground(QBrush(bg))
    it.setForeground(QBrush(_CELL_W))
    return it


def _cell(text, bg, fg=_CELL_W, bold=False, center=False, size=10, accent=None) -> QTableWidgetItem:
    it = QTableWidgetItem(str(text))
    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
    it.setBackground(QBrush(bg))
    it.setForeground(QBrush(fg))
    it.setFont(QFont('Segoe UI', size, QFont.Weight.Bold if bold else QFont.Weight.Normal))
    if center:
        it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
    if accent is not None:
        it.setData(Qt.ItemDataRole.UserRole, accent)
    return it


def _tab_bar(labels, active, accent='#e02840') -> QWidget:
    w = QWidget()
    w.setStyleSheet('background: transparent;')
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)
    for i, text in enumerate(labels):
        lbl = QLabel(text)
        lbl.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
        if i == active:
            lbl.setStyleSheet(f'color:#fff; background:{accent}; border:none;'
                              ' border-radius:6px; padding:5px 14px; letter-spacing:1px;')
        else:
            lbl.setStyleSheet('color:#8a8aa2; background:rgba(255,255,255,10); border:none;'
                              ' border-radius:6px; padding:5px 14px; letter-spacing:1px;')
        lay.addWidget(lbl)
    lay.addStretch(1)
    return w


def _subcard_cards(labels, focus: int) -> QWidget:
    """A horizontal row of sub-card boxes; the focused one glows red."""
    w = QWidget()
    w.setStyleSheet('background: transparent;')
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(14)
    for i, text in enumerate(labels):
        card = QLabel(text)
        card.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.setFont(QFont('Segoe UI', 12, QFont.Weight.Bold))
        card.setFixedHeight(48)
        card.setMinimumWidth(220)
        if i == focus:
            card.setStyleSheet('color:#fff; background:#e02840; border:1px solid #ff6078;'
                               ' border-radius:10px; letter-spacing:2px;')
        else:
            card.setStyleSheet('color:#8a8aa2; background:rgba(255,255,255,8);'
                               ' border:1px solid #2a2a3a; border-radius:10px; letter-spacing:2px;')
        lay.addWidget(card)
    lay.addStretch(1)
    return w


def _season_tables_data(season: dict):
    """Flatten a season's rounds_detail into everything the matrices need.
    Returns None when the season predates per-round recording."""
    rd = season.get('rounds_detail')
    if not rd:
        return None
    codes, countries, race_maps, col_round = [], [], [], []
    for ri, rnd in enumerate(rd):
        country = str(rnd.get('country', ''))
        countries.append(country)
        codes.append(_CODE3.get(country, country[:3].upper()))
        for race in rnd.get('races', []):
            race_maps.append({r['name']: r for r in race})
            col_round.append(ri)

    names = {}
    for rm in race_maps:
        for nm, r in rm.items():
            names.setdefault(nm, {'team': r['team'], 'manufacturer': r['manufacturer'],
                                  'bike': r['bike_number']})
    rider_total = {nm: 0 for nm in names}
    for rm in race_maps:
        for nm, r in rm.items():
            rider_total[nm] += r['points']

    team_race, manu_race = [], []
    for rm in race_maps:
        td, md = {}, {}
        for r in rm.values():
            td[r['team']] = td.get(r['team'], 0) + r['points']
            md[r['manufacturer']] = max(md.get(r['manufacturer'], 0), r['points'])
        team_race.append(td)
        manu_race.append(md)
    team_total, manu_total = {}, {}
    for td in team_race:
        for t, p in td.items():
            team_total[t] = team_total.get(t, 0) + p
    for md in manu_race:
        for m, p in md.items():
            manu_total[m] = manu_total.get(m, 0) + p

    # Countback tie-breakers, matching the live Standings page: ties on points
    # are split by wins, then 2nds, then 3rds … down to P24.
    rider_cb, team_cb, manu_cb = _pos_countback(race_maps, names)
    zero = (0,) * 24

    return {
        'codes': codes, 'countries': countries, 'col_round': col_round, 'race_maps': race_maps,
        'names': names, 'rider_total': rider_total,
        'riders_sorted': sorted(names, key=lambda n: (rider_total[n],) + rider_cb.get(n, zero),
                                reverse=True),
        'team_race': team_race, 'team_total': team_total,
        'teams_sorted': sorted(team_total, key=lambda t: (team_total[t],) + team_cb.get(t, zero),
                               reverse=True),
        'manu_race': manu_race, 'manu_total': manu_total,
        'manu_sorted': sorted(manu_total, key=lambda m: (manu_total[m],) + manu_cb.get(m, zero),
                              reverse=True),
    }


def _pos_countback(race_maps, names):
    """(n_P1, …, n_P24) finish-position vectors per rider / team / manufacturer.

    Mirrors how points are earned — a rider counts their own results, a team
    both its riders', a manufacturer its best bike per race. DNFs and finishes
    past P24 don't count. Used to break ties on equal points.
    """
    rider = {nm: [0] * 24 for nm in names}
    team, manu = {}, {}
    for rm in race_maps:
        best_manu = {}
        for r in rm.values():
            if r.get('dnf'):
                continue
            pos = int(r.get('pos', 0))
            if not (1 <= pos <= 24):
                continue
            rider[r['name']][pos - 1] += 1
            team.setdefault(r['team'], [0] * 24)[pos - 1] += 1
            m = r['manufacturer']
            if pos < best_manu.get(m, 999):
                best_manu[m] = pos
        for m, pos in best_manu.items():
            manu.setdefault(m, [0] * 24)[pos - 1] += 1
    as_tuples = lambda d: {k: tuple(v) for k, v in d.items()}
    return as_tuples(rider), as_tuples(team), as_tuples(manu)


def _race_label(codes, col_round, c) -> str:
    ri = col_round[c]
    j  = c - col_round.index(ri)     # race number within its round
    return f"{codes[ri]}{j + 1}"


def _build_matrix(data: dict, kind: str):
    """kind: 'riders' | 'teams' | 'manu'. Per-round coloured results matrix."""
    codes, col_round = data['codes'], data['col_round']
    n_races = len(data['race_maps'])
    race_labels = [_race_label(codes, col_round, c) for c in range(n_races)]

    if kind == 'riders':
        headers = ['P', 'RIDER', 'MANUFACTURER'] + race_labels + ['PTS']
        keys, res0 = data['riders_sorted'], 3
    else:
        label = 'TEAM' if kind == 'teams' else 'MANUFACTURER'
        headers = ['P', label] + race_labels + ['PTS']
        keys = data['teams_sorted'] if kind == 'teams' else data['manu_sorted']
        res0 = 2

    t = make_table(headers)
    t.verticalHeader().setDefaultSectionSize(30)
    t.setIconSize(QSize(30, 20))
    # Round headers = country flags (both race columns of a round share the flag),
    # falling back to the 3-letter code when a flag file is missing.
    countries = data.get('countries', [])
    for c in range(n_races):
        country = countries[col_round[c]] if col_round[c] < len(countries) else ''
        hdr = QTableWidgetItem()
        fp = _FLAGS / f'{_ISO2.get(country, "")}.png'
        if fp.exists():
            hdr.setIcon(QIcon(str(fp)))
        else:
            hdr.setText(_CODE3.get(country, country[:3].upper()))
        hdr.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setHorizontalHeaderItem(res0 + c, hdr)
    t.setRowCount(len(keys))
    neutral = row_bg(_DEFAULT_COLOR)     # plain dark — no team tint (riders matrix)
    for i, key in enumerate(keys):
        if kind == 'riders':
            info = data['names'][key]
            total = data['rider_total'][key]
            bg = neutral
            # P / RIDER / MANUFACTURER — black background, white text, no accent.
            t.setItem(i, 0, _cell(i + 1, bg, _CELL_W, bold=True, center=True, size=9))
            t.setItem(i, 1, _cell(key.upper(), bg, _CELL_W, bold=True, size=11))
            t.setItem(i, 2, _cell(info['manufacturer'], bg, _CELL_W, size=10))
        else:
            total = data['team_total'][key] if kind == 'teams' else data['manu_total'][key]
            bg = neutral       # black background, white text, no accent
            t.setItem(i, 0, _cell(i + 1, bg, _CELL_W, bold=True, center=True, size=9))
            t.setItem(i, 1, _cell(key.upper(), bg, _CELL_W, bold=True, size=11))

        for c in range(n_races):
            col = res0 + c
            if kind == 'riders':
                rec = data['race_maps'][c].get(key)
                if rec is None:
                    t.setItem(i, col, _grid_cell('', row_bg(_DEFAULT_COLOR)))
                else:
                    txt = 'Ret' if rec['dnf'] else str(rec['pos'])
                    t.setItem(i, col, _grid_cell(txt, _pos_bg(rec['pos'], rec['dnf'])))
            else:
                dct  = data['team_race'][c] if kind == 'teams' else data['manu_race'][c]
                pts  = dct.get(key, 0)
                rank = 1 + sum(1 for v in dct.values() if v > pts)
                t.setItem(i, col, _grid_cell(pts, _rank_bg(rank, pts > 0)))

        t.setItem(i, res0 + n_races, _cell(total, bg, _CELL_W, bold=True, center=True, size=11))

    # Fixed widths (no Stretch on the name column — that squeezed it to a single
    # letter on a wide season). When the matrix is wider than the viewport the
    # table shows a horizontal scrollbar instead of truncating.
    t.setColumnWidth(0, 38)
    if kind == 'riders':
        t.setColumnWidth(1, 240)   # RIDER (roomy — some names are long)
        t.setColumnWidth(2, 140)   # MANUFACTURER
    elif kind == 'teams':
        t.setColumnWidth(1, 250)   # team names are long (e.g. "Kawasaki Factory Racing")
    else:
        t.setColumnWidth(1, 180)   # manufacturer
    for c in range(n_races):
        t.setColumnWidth(res0 + c, 42)
    t.setColumnWidth(res0 + n_races, 60)      # PTS
    t.horizontalHeader().setStretchLastSection(False)
    t.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    # Centre the PTS header so it lines up with the centred point totals below.
    pts_hdr = t.horizontalHeaderItem(res0 + n_races)
    if pts_hdr is not None:
        pts_hdr.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return t


def _esc(s: str) -> str:
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


# Two tabs of separation between podium names (HTML collapses real whitespace).
_PODIUM_SEP = '&nbsp;' * 8


def _rbr_line(label: str, value: str, color: str = '#ffffff', raw: bool = False) -> str:
    val = value if raw else _esc(value)
    return (f"<tr><td style='color:#8a8aa2; padding:3px 26px 3px 0; font-size:8pt;"
            f" letter-spacing:1px'>{label}</td>"
            f"<td style='color:{color}; font-weight:bold; font-size:10pt'>{val}</td></tr>")


def _build_race_by_race(data: dict):
    scroll = _make_scroll_area()
    cont = QWidget()
    cont.setStyleSheet('background: transparent;')
    lay = QVBoxLayout(cont)
    lay.setContentsMargins(0, 0, 12, 0)
    lay.setSpacing(14)

    codes, col_round, race_maps = data['codes'], data['col_round'], data['race_maps']

    for c, rm in enumerate(race_maps):
        race      = list(rm.values())
        pole      = next((r for r in race if r['pole']), None)
        fast      = next((r for r in race if r['fastest_lap']), None)
        finishers = sorted((r for r in race if not r['dnf']), key=lambda r: r['pos'])
        winner    = finishers[0] if finishers else None
        podium    = finishers[:3]

        card = QFrame()
        card.setStyleSheet(
            'QFrame { background: rgba(255,255,255,6); border: 1px solid #23233a; border-radius: 10px; }'
            'QLabel { background: transparent; border: none; }')
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 14, 18, 16)
        cl.setSpacing(8)

        title = QLabel(_race_label(codes, col_round, c))
        title.setFont(QFont('Segoe UI', 12, QFont.Weight.Bold))
        title.setStyleSheet('color:#ffffff; letter-spacing:1px; background:transparent; border:none;')
        cl.addWidget(title)

        podium_txt = _PODIUM_SEP.join(_esc(r['name'].upper()) for r in podium) if podium else '—'
        rows = ''.join([
            _rbr_line('POLESITTER',           pole['name'].upper() if pole else '—'),
            _rbr_line('FASTEST LAP',          fast['name'].upper() if fast else '—'),
            _rbr_line('WINNING RIDER',        winner['name'].upper() if winner else '—'),
            _rbr_line('PODIUM',               podium_txt, raw=True),
            _rbr_line('WINNING TEAM',         winner['team'].upper() if winner else '—'),
            _rbr_line('WINNING MANUFACTURER', winner['manufacturer'].upper() if winner else '—'),
        ])
        body = QLabel(f"<table cellspacing=0 cellpadding=0>{rows}</table>")
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setStyleSheet('background:transparent; border:none;')
        cl.addWidget(body)
        lay.addWidget(card)

    lay.addStretch(1)
    scroll.setWidget(cont)
    return scroll


# ── Honours (win / podium / pole leaderboards) ─────────────────────────────────

def _honours_data(data: dict) -> dict:
    """Season honour boards. A rider's win = P1, podium = P1–P3 (both finishes,
    not DNFs), pole = the pole flag. Manufacturer boards sum their riders'
    tallies — mirroring how the app already attributes results to a make."""
    names = data['names']
    rider = {nm: {'wins': 0, 'podiums': 0, 'poles': 0} for nm in names}
    for rm in data['race_maps']:
        for r in rm.values():
            if r.get('pole'):
                rider[r['name']]['poles'] += 1
            if not r.get('dnf'):
                pos = int(r.get('pos', 0))
                if pos == 1:
                    rider[r['name']]['wins'] += 1
                if 1 <= pos <= 3:
                    rider[r['name']]['podiums'] += 1

    manu: dict[str, dict] = {}
    for nm, tally in rider.items():
        m = names[nm]['manufacturer']
        md = manu.setdefault(m, {'wins': 0, 'podiums': 0, 'poles': 0})
        for k in md:
            md[k] += tally[k]

    def board(src: dict, key: str) -> list:
        # Only entries with a count; ties broken alphabetically.
        rows = [(n, v[key]) for n, v in src.items() if v[key] > 0]
        return sorted(rows, key=lambda x: (-x[1], x[0]))

    keys = ('wins', 'podiums', 'poles')
    return {
        'riders': {k: board(rider, k) for k in keys},
        'manu':   {k: board(manu, k) for k in keys},
    }


_HON_RULE = 'rgba(255, 255, 255, 90)'   # soft white rule, easy to see on the dark veil


def _hdivider() -> QFrame:
    """A thin horizontal white rule (title ↔ list separator)."""
    d = QFrame(); d.setFixedHeight(1)
    d.setStyleSheet(f'background: {_HON_RULE}; border: none;')
    return d


def _vdivider() -> QFrame:
    """A thin vertical white rule that stretches to the column height."""
    d = QFrame(); d.setFixedWidth(1)
    d.setStyleSheet(f'background: {_HON_RULE}; border: none;')
    d.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
    return d


def _honour_row(name: str, value: str, name_color: str = '#ffffff') -> QWidget:
    """One leaderboard line: name on the left, count on the right (no rank)."""
    w = QWidget(); w.setStyleSheet('background: transparent;')
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)
    nm = QLabel(name)
    nm.setFont(QFont('Segoe UI', 13, QFont.Weight.Bold))
    nm.setStyleSheet(f'color: {name_color}; background: transparent; border: none;')
    lay.addWidget(nm, 1)
    val = QLabel(value)
    val.setFont(QFont('Segoe UI', 13, QFont.Weight.Bold))
    val.setStyleSheet('color: #ffffff; background: transparent; border: none;')
    lay.addWidget(val)
    return w


def _honours_column(title: str, entries: list) -> QWidget:
    """A single ranked leaderboard: centred title over name / count rows."""
    col = QWidget(); col.setStyleSheet('background: transparent;')
    lay = QVBoxLayout(col)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    head = _section_label(title)
    head.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
    head.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    lay.addWidget(head)
    lay.addSpacing(12)
    lay.addWidget(_hdivider())         # rule between the title and the list
    lay.addSpacing(14)
    if not entries:
        ph = QLabel('—')
        ph.setFont(QFont('Segoe UI', 13))
        ph.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        ph.setStyleSheet('color: #44445a; background: transparent; border: none;')
        lay.addWidget(ph)
    else:
        for name, count in entries:
            lay.addWidget(_honour_row(name.upper(), str(count)))
            lay.addSpacing(10)
    lay.addStretch(1)
    return col


def _build_honours(board: dict):
    """Three side-by-side leaderboards (Race Wins / Podiums / Poles) for one
    category (riders or manufacturers)."""
    scroll = _make_scroll_area()
    cont = QWidget(); cont.setStyleSheet('background: transparent;')
    lay = QVBoxLayout(cont)
    lay.setContentsMargins(0, 0, 12, 0)
    lay.setSpacing(0)

    cols = QWidget(); cols.setStyleSheet('background: transparent;')
    cl = QHBoxLayout(cols)
    cl.setContentsMargins(0, 0, 0, 0)
    cl.setSpacing(36)
    cl.addWidget(_honours_column('RACE WINS', board['wins']), 1)
    cl.addWidget(_vdivider())
    cl.addWidget(_honours_column('PODIUMS', board['podiums']), 1)
    cl.addWidget(_vdivider())
    cl.addWidget(_honours_column('POLES', board['poles']), 1)
    lay.addWidget(cols)
    lay.addStretch(1)

    scroll.setWidget(cont)
    return scroll


class _GPBox(QFrame):
    """A square Grand-Prix tile: the country flag over 'Grand Prix of <country>'."""

    clicked = pyqtSignal(int)

    def __init__(self, idx: int, country: str):
        super().__init__()
        self._idx = idx
        self._selected = False
        self.setFixedSize(158, 158)

        col = QVBoxLayout(self)
        col.setContentsMargins(12, 12, 12, 12)
        col.setSpacing(10)
        col.addStretch(1)

        flag = QLabel()
        flag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = _flag_pixmap(country, 52, 78)     # uniform 78×52 for every flag
        if pix is not None:
            flag.setPixmap(pix)
            flag.setStyleSheet('background: transparent; border: none;')
        else:
            flag.setText(country[:3].upper())
            flag.setFont(QFont('Segoe UI', 16, QFont.Weight.Bold))
            flag.setStyleSheet('color:#8a8aa2; background: transparent; border: none;')
        col.addWidget(flag, 0, Qt.AlignmentFlag.AlignCenter)

        self._name = QLabel(f'Grand Prix of\n{country}')
        self._name.setWordWrap(True)
        self._name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
        self._name.setStyleSheet('color:#cfcfe0; background: transparent; border: none;')
        col.addWidget(self._name, 0, Qt.AlignmentFlag.AlignCenter)
        col.addStretch(1)

    def set_selected(self, v: bool):
        self._selected = v
        self._name.setStyleSheet(
            f'color:{"#ffffff" if v else "#cfcfe0"}; background: transparent; border: none;')
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        if self._selected:
            p.setBrush(QColor(224, 40, 64, 45))
            p.setPen(QPen(QColor('#e02840'), 2))
        else:
            p.setBrush(QColor(255, 255, 255, 8))
            p.setPen(QPen(QColor('#2a2a3a'), 1))
        p.drawRoundedRect(r, 12, 12)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._idx)
        super().mousePressEvent(e)


def _build_gp_detail(season: dict, round_idx: int):
    """Stats for one Grand Prix (its round's races)."""
    rounds = season.get('rounds_detail', [])
    rnd = rounds[round_idx] if 0 <= round_idx < len(rounds) else {}
    country = rnd.get('country', '')

    scroll = _make_scroll_area()
    cont = QWidget()
    cont.setStyleSheet('background: transparent;')
    lay = QVBoxLayout(cont)
    lay.setContentsMargins(0, 0, 12, 0)
    lay.setSpacing(14)

    head = QWidget(); head.setStyleSheet('background: transparent;')
    hl = QHBoxLayout(head); hl.setContentsMargins(0, 0, 0, 0); hl.setSpacing(16)
    fpix = _flag_pixmap(country, 46, 69)     # uniform 69×46 for every Grand Prix
    if fpix is not None:
        fl = QLabel(); fl.setPixmap(fpix)
        fl.setStyleSheet('background: transparent; border: none;')
        hl.addWidget(fl)
    title = QLabel(f'GRAND PRIX OF {country.upper()}')
    title.setFont(QFont('Segoe UI', 18, QFont.Weight.Bold))
    title.setStyleSheet('color:#ffffff; letter-spacing:1px; background: transparent; border: none;')
    hl.addWidget(title); hl.addStretch(1)
    lay.addWidget(head)
    lay.addSpacing(6)

    for rj, race in enumerate(rnd.get('races', [])):
        pole      = next((r for r in race if r['pole']), None)
        fast      = next((r for r in race if r['fastest_lap']), None)
        finishers = sorted((r for r in race if not r['dnf']), key=lambda r: r['pos'])
        winner    = finishers[0] if finishers else None
        podium    = finishers[:3]
        podium_txt = _PODIUM_SEP.join(_esc(r['name'].upper()) for r in podium) if podium else '—'
        rows = ''.join([
            _rbr_line('POLESITTER',           pole['name'].upper() if pole else '—'),
            _rbr_line('FASTEST LAP',          fast['name'].upper() if fast else '—'),
            _rbr_line('WINNING RIDER',        winner['name'].upper() if winner else '—'),
            _rbr_line('PODIUM',               podium_txt, raw=True),
            _rbr_line('WINNING TEAM',         winner['team'].upper() if winner else '—'),
            _rbr_line('WINNING MANUFACTURER', winner['manufacturer'].upper() if winner else '—'),
        ])
        card = QFrame()
        card.setStyleSheet(
            'QFrame { background: rgba(255,255,255,6); border: 1px solid #23233a; border-radius: 10px; }'
            'QLabel { background: transparent; border: none; }')
        cl = QVBoxLayout(card); cl.setContentsMargins(18, 14, 18, 16); cl.setSpacing(8)
        rt = QLabel(f'RACE {rj + 1}')
        rt.setFont(QFont('Segoe UI', 12, QFont.Weight.Bold))
        rt.setStyleSheet('color:#ffffff; letter-spacing:1px; background: transparent; border: none;')
        cl.addWidget(rt)
        body = QLabel(f"<table cellspacing=0 cellpadding=0>{rows}</table>")
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setStyleSheet('background: transparent; border: none;')
        cl.addWidget(body)
        lay.addWidget(card)

    lay.addStretch(1)
    scroll.setWidget(cont)
    return scroll


class _SeasonStatDetail(QWidget):
    SUBCARDS       = ['FINAL STANDINGS', 'RACE BY RACE', 'HONOURS']
    CATEGORIES     = ['RIDERS', 'TEAMS', 'MANUFACTURERS']
    HON_CATEGORIES = ['RIDERS', 'MANUFACTURERS']
    _GP_COLS   = 5

    def __init__(self):
        super().__init__()
        self.setAutoFillBackground(False)
        self.setStyleSheet('background: transparent;')
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(40, 40, 40, 30)
        self._outer.setSpacing(0)
        self._season = None
        self._data = None
        self._view = 'select'      # 'select' | 'fs' | 'rbr' | 'gp' | 'hon'
        self._focus = 0            # highlighted sub-card: 0 = Final Standings, 1 = Race by Race, 2 = Honours
        self._category = 0         # Riders/Teams/Manu within Final Standings
        self._hon_category = 0     # Riders/Manufacturers within Honours
        self._gp_focus = 0         # highlighted Grand-Prix box
        self._gp_boxes = []
        self._gp_rows = []
        self._matrices = {}
        self._scrollable = None
        self._warm = None
        self._clear()              # empty until a season loads

    # ── helpers ─────────────────────────────────────────────────────────────────
    def _clear(self):
        while self._outer.count():
            item = self._outer.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

    def _placeholder(self, text: str = ''):
        # Browse state (no season open): nothing shown — no annotation text.
        if self._warm is not None:
            self._warm.stop()
        self._clear()
        self._scrollable = None

    # ── build (once per season) ─────────────────────────────────────────────────
    def load(self, season: dict):
        self._season   = season
        self._data     = _season_tables_data(season)
        self._view     = 'select'
        self._focus    = 0
        self._category = 0
        self._hon_category = 0
        self._gp_focus = 0
        self._matrices = {}
        self._gp_boxes = []
        self._gp_rows = []
        self._build()

    def _build(self):
        if self._warm is not None:
            self._warm.stop()
        self._clear()
        self._scrollable = None
        if self._data is None:
            self._render_legacy(self._season)
            return

        # Sub-card cards (always on top) — highlight follows _focus.
        self._subcard_holder = QWidget()
        self._subcard_holder.setStyleSheet('background: transparent;')
        self._subcard_lay = QVBoxLayout(self._subcard_holder)
        self._subcard_lay.setContentsMargins(0, 0, 0, 0)
        self._subcard_lay.setSpacing(0)
        self._outer.addWidget(self._subcard_holder)
        self._outer.addSpacing(16)

        # One content stack, switched by view (no re-layout on transition).
        self._cstack = QStackedWidget()
        self._cstack.setStyleSheet('background: transparent;')

        self._p_empty = QWidget()
        self._p_empty.setStyleSheet('background: transparent;')
        self._cstack.addWidget(self._p_empty)

        # Final Standings: category tab bar + matrix stack (full width).
        self._p_fs = QWidget(); self._p_fs.setStyleSheet('background: transparent;')
        fsl = QVBoxLayout(self._p_fs); fsl.setContentsMargins(0, 0, 0, 0); fsl.setSpacing(0)
        self._cat_holder = QWidget(); self._cat_holder.setStyleSheet('background: transparent;')
        self._cat_lay = QVBoxLayout(self._cat_holder)
        self._cat_lay.setContentsMargins(0, 0, 0, 0); self._cat_lay.setSpacing(0)
        fsl.addWidget(self._cat_holder); fsl.addSpacing(12)
        self._fs_stack = QStackedWidget(); self._fs_stack.setStyleSheet('background: transparent;')
        fsl.addWidget(self._fs_stack, 1)
        self._cstack.addWidget(self._p_fs)

        # Race by Race: grid of Grand-Prix boxes.
        self._p_rbr = self._make_gp_grid()
        self._cstack.addWidget(self._p_rbr)

        # Grand-Prix detail: filled on demand.
        self._p_gp = QWidget(); self._p_gp.setStyleSheet('background: transparent;')
        self._gp_lay = QVBoxLayout(self._p_gp)
        self._gp_lay.setContentsMargins(0, 0, 0, 0); self._gp_lay.setSpacing(0)
        self._cstack.addWidget(self._p_gp)

        # Honours: category tab bar (Riders/Manufacturers) + win/podium/pole boards.
        honours = _honours_data(self._data)
        self._p_hon = QWidget(); self._p_hon.setStyleSheet('background: transparent;')
        honl = QVBoxLayout(self._p_hon); honl.setContentsMargins(0, 0, 0, 0); honl.setSpacing(0)
        self._hon_cat_holder = QWidget(); self._hon_cat_holder.setStyleSheet('background: transparent;')
        self._hon_cat_lay = QVBoxLayout(self._hon_cat_holder)
        self._hon_cat_lay.setContentsMargins(0, 0, 0, 0); self._hon_cat_lay.setSpacing(0)
        honl.addWidget(self._hon_cat_holder); honl.addSpacing(12)
        self._hon_stack = QStackedWidget(); self._hon_stack.setStyleSheet('background: transparent;')
        self._hon_stack.addWidget(_build_honours(honours['riders']))
        self._hon_stack.addWidget(_build_honours(honours['manu']))
        honl.addWidget(self._hon_stack, 1)
        self._cstack.addWidget(self._p_hon)

        self._outer.addWidget(self._cstack, 1)
        self._refresh()

        # Warm the Final-Standings matrices in the background.
        self._warm = QTimer(self)
        self._warm.timeout.connect(self._prewarm_step)
        self._warm.start(30)

    def _make_gp_grid(self):
        scroll = _make_scroll_area()
        cont = QWidget(); cont.setStyleSheet('background: transparent;')
        outer = QVBoxLayout(cont)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(16)
        outer.addStretch(1)                       # centre the block vertically

        rounds = self._season.get('rounds_detail', [])
        self._gp_boxes = []
        self._gp_rows = _row_sizes(len(rounds))   # e.g. 13 → [4, 5, 4]
        idx = 0
        for count in self._gp_rows:
            rw = QWidget(); rw.setStyleSheet('background: transparent;')
            row = QHBoxLayout(rw)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(16)
            row.addStretch(1)                     # centre the row horizontally
            for _ in range(count):
                rnd = rounds[idx]
                box = _GPBox(idx, rnd.get('country', ''))
                box.clicked.connect(self._open_gp)
                row.addWidget(box)
                self._gp_boxes.append(box)
                idx += 1
            row.addStretch(1)
            outer.addWidget(rw)
        outer.addStretch(1)
        scroll.setWidget(cont)
        return scroll

    def _matrix(self, kind: str):
        m = self._matrices.get(kind)
        if m is None:
            m = _build_matrix(self._data, kind)
            self._matrices[kind] = m
            self._fs_stack.addWidget(m)
        return m

    def _prewarm_step(self):
        for kind in ('riders', 'teams', 'manu'):
            if kind not in self._matrices:
                self._matrix(kind)
                return
        self._warm.stop()

    # ── refresh (light — no heavy rebuild) ──────────────────────────────────────
    def _refresh(self):
        while self._subcard_lay.count():
            it = self._subcard_lay.takeAt(0); w = it.widget()
            if w is not None:
                w.setParent(None)
        self._subcard_lay.addWidget(_subcard_cards(self.SUBCARDS, self._focus))

        if self._view == 'select':
            self._cstack.setCurrentWidget(self._p_empty)
            self._scrollable = None
        elif self._view == 'fs':
            while self._cat_lay.count():
                it = self._cat_lay.takeAt(0); w = it.widget()
                if w is not None:
                    w.setParent(None)
            self._cat_lay.addWidget(_tab_bar(self.CATEGORIES, self._category, accent='#318CE7'))
            pg = self._matrix(('riders', 'teams', 'manu')[self._category])
            self._fs_stack.setCurrentWidget(pg)
            self._cstack.setCurrentWidget(self._p_fs)
            self._scrollable = pg
        elif self._view == 'rbr':
            for i, b in enumerate(self._gp_boxes):
                b.set_selected(i == self._gp_focus)
            self._cstack.setCurrentWidget(self._p_rbr)
            self._scrollable = None
        elif self._view == 'hon':
            while self._hon_cat_lay.count():
                it = self._hon_cat_lay.takeAt(0); w = it.widget()
                if w is not None:
                    w.setParent(None)
            self._hon_cat_lay.addWidget(
                _tab_bar(self.HON_CATEGORIES, self._hon_category, accent='#318CE7'))
            pg = self._hon_stack.widget(self._hon_category)
            self._hon_stack.setCurrentWidget(pg)
            self._cstack.setCurrentWidget(self._p_hon)
            self._scrollable = pg
        elif self._view == 'gp':
            self._cstack.setCurrentWidget(self._p_gp)

    def _open_gp(self, idx: int):
        if not (0 <= idx < len(self._gp_boxes)):
            return
        self._gp_focus = idx
        while self._gp_lay.count():
            it = self._gp_lay.takeAt(0); w = it.widget()
            if w is not None:
                w.setParent(None)
        scroll = _build_gp_detail(self._season, idx)
        self._gp_lay.addWidget(scroll)
        self._view = 'gp'
        self._scrollable = scroll
        self._refresh()

    # ── navigation ──────────────────────────────────────────────────────────────
    def handle_key(self, key: int):
        """Drive the detail. Returns 'close' when the user backs out of the top
        level (so the caller reopens the season list)."""
        K = Qt.Key
        if self._data is None:
            return 'close' if key in (K.Key_Escape, K.Key_Backspace) else None

        v = self._view
        if v == 'select':
            if key in (K.Key_Left, K.Key_Right):
                self._focus = (self._focus + (1 if key == K.Key_Right else -1)) % 3
                self._refresh()
            elif key in (K.Key_Return, K.Key_Enter, K.Key_Space):
                self._view = ('fs', 'rbr', 'hon')[self._focus]
                self._gp_focus = 0
                self._refresh()
            elif key in (K.Key_Escape, K.Key_Backspace):
                return 'close'
        elif v == 'fs':
            if key in (K.Key_Left, K.Key_Right):        # scroll the wide matrix
                self._hscroll(-110 if key == K.Key_Left else 110)
            elif key in (K.Key_Up, K.Key_Down):
                self._scroll(-60 if key == K.Key_Up else 60)
            elif key in (K.Key_Return, K.Key_Enter, K.Key_Space):
                self._category = (self._category + 1) % 3   # cycle Riders/Teams/Manu
                self._refresh()
            elif key in (K.Key_Escape, K.Key_Backspace):
                self._view = 'select'
                self._refresh()
        elif v == 'rbr':
            if key in (K.Key_Left, K.Key_Right, K.Key_Up, K.Key_Down):
                self._grid_nav(key)
            elif key in (K.Key_Return, K.Key_Enter, K.Key_Space):
                self._open_gp(self._gp_focus)
            elif key in (K.Key_Escape, K.Key_Backspace):
                self._view = 'select'
                self._refresh()
        elif v == 'gp':
            if key in (K.Key_Up, K.Key_Down):
                self._scroll(-60 if key == K.Key_Up else 60)
            elif key in (K.Key_Escape, K.Key_Backspace):
                self._view = 'rbr'
                self._refresh()
        elif v == 'hon':
            if key in (K.Key_Left, K.Key_Right):    # switch Riders / Manufacturers
                self._hon_category = (self._hon_category +
                                      (1 if key == K.Key_Right else -1)) % 2
                self._refresh()
            elif key in (K.Key_Return, K.Key_Enter, K.Key_Space):
                self._hon_category = (self._hon_category + 1) % 2
                self._refresh()
            elif key in (K.Key_Up, K.Key_Down):
                self._scroll(-60 if key == K.Key_Up else 60)
            elif key in (K.Key_Escape, K.Key_Backspace):
                self._view = 'select'
                self._refresh()
        return None

    def _grid_nav(self, key: int):
        n = len(self._gp_boxes)
        if n == 0:
            return
        K = Qt.Key
        i = self._gp_focus
        rows = self._gp_rows or [n]
        starts, s = [], 0
        for c in rows:
            starts.append(s); s += c
        # locate current (row, col)
        row = col = 0
        for r, (st, ct) in enumerate(zip(starts, rows)):
            if st <= i < st + ct:
                row, col = r, i - st
                break
        if key == K.Key_Left:
            i = (i - 1) % n
        elif key == K.Key_Right:
            i = (i + 1) % n
        elif key == K.Key_Up and row > 0:
            i = starts[row - 1] + min(col, rows[row - 1] - 1)
        elif key == K.Key_Down and row < len(rows) - 1:
            i = starts[row + 1] + min(col, rows[row + 1] - 1)
        self._gp_focus = i
        self._refresh()
        self._p_rbr.ensureWidgetVisible(self._gp_boxes[i])

    def _scroll(self, delta: int):
        if self._scrollable is not None:
            bar = self._scrollable.verticalScrollBar()
            if bar is not None:
                bar.setValue(bar.value() + delta)

    def _hscroll(self, delta: int):
        if self._scrollable is not None:
            bar = self._scrollable.horizontalScrollBar()
            if bar is not None:
                bar.setValue(bar.value() + delta)

    def _render_legacy(self, s: dict):
        """Season archived before per-round recording — show a note plus the
        accurate final rider standings (two columns)."""
        note = QLabel('Detailed per-round results were not recorded for this '
                      'season. Play a new season to see the full breakdown.')
        note.setWordWrap(True)
        note.setFont(QFont('Segoe UI', 11))
        note.setStyleSheet('color: #8a8aa2; background: transparent; border: none;')
        self._outer.addWidget(note)
        self._outer.addSpacing(20)
        self._outer.addWidget(_section_label('FINAL STANDINGS'))
        self._outer.addSpacing(14)

        standings = s.get('standings', [])
        half = (len(standings) + 1) // 2
        cols = QWidget(); cols.setStyleSheet('background: transparent;')
        cols_lay = QHBoxLayout(cols)
        cols_lay.setContentsMargins(0, 0, 0, 0)
        cols_lay.setSpacing(48)
        for start in (0, half):
            col = QWidget(); col.setStyleSheet('background: transparent;')
            col_lay = QVBoxLayout(col)
            col_lay.setContentsMargins(0, 0, 0, 0)
            col_lay.setSpacing(0)
            for offset, st in enumerate(standings[start:start + half]):
                pos   = start + offset + 1
                medal = _medal_color(pos) or '#ccccdd'
                col_lay.addWidget(_text_row(
                    str(pos), st['name'].upper(), f"{int(st.get('points', 0))} PTS",
                    left_color=medal, mid_color='#ccccdd', left_w=36))
                col_lay.addSpacing(8)
            col_lay.addStretch(1)
            cols_lay.addWidget(col, 1)
        self._outer.addWidget(cols)
        self._outer.addStretch(1)


# ── Split views (3:7) ─────────────────────────────────────────────────────────

class _RiderStatsView(QWidget):
    def __init__(self, wiz):
        super().__init__()
        self._wiz     = wiz
        self._items   = {}
        self._recs    = {}
        self._current = None
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        left_outer, self._list_lay, self._left_scroll = _make_list_panel()
        root.addWidget(left_outer, 3)

        vd = QFrame(); vd.setFixedWidth(1)
        vd.setStyleSheet('background: #111122; border: none;')
        root.addWidget(vd)

        self._detail = _RiderRecordDetail()
        scroll_r = _make_scroll_area()
        scroll_r.setWidget(self._detail)
        root.addWidget(scroll_r, 7)

    def _bike_numbers(self) -> dict:
        df = getattr(self._wiz, 'df', None)
        if df is None:
            return {}
        return {str(r['name']): int(r['bike_number']) for _, r in df.iterrows()}

    def rebuild(self, seasons: list):
        for it in self._items.values():
            it.setParent(None)
        self._items.clear()
        self._recs.clear()
        self._current = None

        agg      = _aggregate_riders(seasons)
        bike_no  = self._bike_numbers()
        # sort by bike number (unknown numbers sink to the bottom, then by name)
        order = sorted(agg.items(),
                       key=lambda kv: (bike_no.get(kv[0], 10_000), kv[0]))
        self._recs = {name: rec for name, rec in order}
        for name, rec in order:
            tc = _team_color(rec.get('team', ''), rec.get('manufacturer', ''))
            item = _RankItem(bike_no.get(name), name, rec['titles'], tc)
            item.clicked.connect(self._on_select)
            self._list_lay.insertWidget(self._list_lay.count() - 1, item)
            self._items[name] = item
        if order:
            self._on_select(order[0][0])
        else:
            self._detail._placeholder('No records yet')

    def _on_select(self, name: str):
        if self._current and self._current in self._items:
            self._items[self._current].set_selected(False)
        self._current = name
        self._items[name].set_selected(True)
        self._detail.load({'name': name, **self._recs[name]})

    def move_selection(self, forward: bool):
        names = list(self._items.keys())
        if not names:
            return
        idx = names.index(self._current) if self._current in names else -1
        new = names[(idx + (1 if forward else -1)) % len(names)]
        self._on_select(new)
        self._left_scroll.ensureWidgetVisible(self._items[new])

    def paintEvent(self, event):
        QPainter(self).fillRect(self.rect(), _TINT)


class _SeasonStatsView(QWidget):
    def __init__(self, wiz):
        super().__init__()
        self._wiz     = wiz
        self._items   = {}       # key -> _SeasonItem (insertion-ordered)
        self._seasons = {}
        self._focus_key  = None  # highlighted card (cursor)
        self._opened_key = None  # season whose stats are shown
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._left_outer, self._list_lay, self._left_scroll = _make_list_panel()
        root.addWidget(self._left_outer, 3)

        self._vd = QFrame(); self._vd.setFixedWidth(1)
        self._vd.setStyleSheet('background: #111122; border: none;')
        root.addWidget(self._vd)

        # The season list (left) is hidden once a season is opened, so the detail
        # takes the whole width; the detail manages its own internal scrolling.
        self._detail = _SeasonStatDetail()
        root.addWidget(self._detail, 7)

    def rebuild(self, seasons: list):
        for it in self._items.values():
            it.setParent(None)
        self._items.clear()
        self._seasons.clear()

        ordered = sorted(enumerate(seasons),
                         key=lambda kv: str(kv[1].get('year', kv[0])), reverse=True)
        for i, s in ordered:
            key = str(s.get('year', f'S{i:02d}'))
            champ = s.get('champion') or {}
            tc = _team_color(champ.get('team', ''), champ.get('manufacturer', ''))
            item = _SeasonItem(key, s.get('year', key), tc)
            item.clicked.connect(self._open_key)
            self._list_lay.insertWidget(self._list_lay.count() - 1, item)
            self._items[key] = item
            self._seasons[key] = s
        self.reset_selection()

    def reset_selection(self):
        """Back to browsing: show the season list, empty detail, no annotation."""
        self._opened_key = None
        self._focus_key  = None
        self._left_outer.show()
        self._vd.show()
        self._detail._placeholder()
        if self._items:
            self._set_focus(next(iter(self._items)))

    def _set_focus(self, key: str):
        for k, it in self._items.items():
            it.set_selected(k == key)
        self._focus_key = key

    def move_focus(self, forward: bool):
        keys = list(self._items)
        if not keys:
            return
        idx = keys.index(self._focus_key) if self._focus_key in keys else -1
        new = keys[(idx + (1 if forward else -1)) % len(keys)]
        self._set_focus(new)
        self._left_scroll.ensureWidgetVisible(self._items[new])

    def open_focused(self):
        if self._focus_key is not None:
            self._open_key(self._focus_key)

    def _open_key(self, key: str):
        if key not in self._seasons:
            return
        self._set_focus(key)
        self._opened_key = key
        self._left_outer.hide()                 # season list gone → full-width detail
        self._vd.hide()
        self._detail.load(self._seasons[key])

    def handle_key(self, key: int):
        """All keys while the Season Stats view is showing. Returns 'back' when
        the caller should leave the split view."""
        if self._opened_key is None:            # browsing season cards
            if key in (Qt.Key.Key_Escape, Qt.Key.Key_Backspace):
                return 'back'
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                self.move_focus(key == Qt.Key.Key_Down)
            elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                self.open_focused()
            return True

        # A season is open — the detail owns its own key handling. When it backs
        # out of its top level, reopen the season list.
        if self._detail.handle_key(key) == 'close':
            self.reset_selection()
        return True

    def paintEvent(self, event):
        QPainter(self).fillRect(self.rect(), _TINT)


# ── Page ──────────────────────────────────────────────────────────────────────

class HistoryPage(QWizardPage):
    """Championship archive laid out like the Gallery: two cards
    (Rider's Overall Stats / Season Stats), each opening a 3:7 master-detail
    split view over the video background."""

    def __init__(self, wiz):
        super().__init__()
        self._wiz = wiz
        self._vbg = VideoBackground.instance()
        self._vbg.frame_ready.connect(self._on_bg_frame)
        self.setTitle('')
        self.setSubTitle('')

        self._stack = QStackedWidget(self)
        self._stack.setAutoFillBackground(False)
        self._stack.setStyleSheet('background: transparent;')

        # ── Index 0: card selection ───────────────────────────────────────────
        cards_w = QWidget()
        cards_w.setAutoFillBackground(False)
        cards_w.setStyleSheet('background: transparent;')
        cw_l = QVBoxLayout(cards_w)
        cw_l.setContentsMargins(0, 0, 0, 0)
        cw_l.addStretch(2)
        row = QHBoxLayout()
        row.addStretch(1)
        self._card_riders = _Card(
            "RIDER'S OVERALL\nSTATS",
            'All-time records and career totals\nacross every completed season', '#e02840')
        self._card_seasons = _Card(
            'SEASON\nSTATS',
            'Champions and final standings\nof each past season', '#318CE7')
        self._card_riders.clicked.connect(self._open_riders)
        self._card_seasons.clicked.connect(self._open_seasons)
        row.addWidget(self._card_riders)
        row.addSpacing(28)
        row.addWidget(self._card_seasons)
        row.addStretch(1)
        cw_l.addLayout(row)
        cw_l.addStretch(3)
        self._stack.addWidget(cards_w)                       # index 0

        self._riders_view = _RiderStatsView(wiz)
        self._stack.addWidget(self._riders_view)             # index 1
        self._seasons_view = _SeasonStatsView(wiz)
        self._stack.addWidget(self._seasons_view)            # index 2

        # ── Index 3: empty state ──────────────────────────────────────────────
        empty_w = _TintPanel()
        el = QVBoxLayout(empty_w)
        self._empty_lbl = QLabel('No championship has been completed yet — '
                                 'finish a season and it will be recorded here.')
        self._empty_lbl.setFont(QFont('Segoe UI', 12))
        self._empty_lbl.setStyleSheet('color: #ffffff; background: transparent; border: none;')
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        el.addStretch(1)
        el.addWidget(self._empty_lbl)
        el.addStretch(1)
        self._stack.addWidget(empty_w)                       # index 3

        self._card_focus = 0  # 0 = Riders, 1 = Seasons

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._stack)

    # ── Wizard flow ───────────────────────────────────────────────────────────

    def initializePage(self):
        seasons = _load_history()
        if not seasons:
            self._stack.setCurrentIndex(3)
            return
        self._riders_view.rebuild(seasons)
        self._seasons_view.rebuild(seasons)
        self._stack.setCurrentIndex(0)
        self._card_focus = 0
        self._card_riders.set_focused(True)
        self._card_seasons.set_focused(False)

    def nextId(self):
        return -1

    def handle_key(self, key: int) -> bool:
        idx = self._stack.currentIndex()
        if idx == 0:
            if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                self._card_focus = 1 - self._card_focus
                self._card_riders.set_focused(self._card_focus == 0)
                self._card_seasons.set_focused(self._card_focus == 1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                (self._open_riders if self._card_focus == 0 else self._open_seasons)()
                return True
        elif idx == 1:                         # Riders: navigate selects live
            if key in (Qt.Key.Key_Escape, Qt.Key.Key_Backspace):
                self._stack.setCurrentIndex(0)
                return True
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                self._riders_view.move_selection(key == Qt.Key.Key_Down)
            return True
        elif idx == 2:                         # Season Stats owns its own keys
            if self._seasons_view.handle_key(key) == 'back':
                self._stack.setCurrentIndex(0)
            return True
        return False

    def _open_riders(self):
        self._stack.setCurrentIndex(1)

    def _open_seasons(self):
        # Enter the split view with an empty detail — the user picks a season
        # and presses Enter to reveal its stats.
        self._seasons_view.reset_selection()
        self._stack.setCurrentIndex(2)

    # ── Background painting (mirrors GalleryPage) ─────────────────────────────

    def _on_bg_frame(self):
        if self.isVisible():
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        offset = self.mapTo(self._wiz, self.rect().topLeft())
        self._vbg.paint(p, self, full_size=self._wiz.size(), offset=offset)

    def paint_gap_overlay(self, painter, rect):
        if self._stack.currentIndex() in (1, 2, 3):
            painter.fillRect(rect, _TINT)
