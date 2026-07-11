import json
from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout, QLabel,
                              QFrame, QWidget, QStackedWidget, QSizePolicy)
from PyQt6.QtGui import QFont, QPainter, QColor, QPen
from PyQt6.QtCore import Qt, pyqtSignal

from app.widgets.video_bg import VideoBackground
from app.widgets.table_utils import TEAM_COLOR, MANU_COLOR, _DEFAULT_COLOR
from app.pages.p_gallery import (_Card, _make_scroll_area, _divider, _section_label)
from app.wizard import HISTORY_FILE as _HISTORY

_TINT = QColor(5, 5, 14, 218)   # same dark veil the Gallery split views use

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

    def __init__(self, key: str, year, champion: str, team_color: QColor):
        super().__init__()
        self._key = key
        self._tc  = team_color
        self._selected = False
        self.setFixedHeight(58)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 10, 14, 10)
        lay.setSpacing(4)

        self._year_lbl = QLabel(str(year))
        self._year_lbl.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
        self._year_lbl.setStyleSheet('background: transparent; border: none; color: #aaaabc;')
        lay.addWidget(self._year_lbl)

        self._champ_lbl = QLabel(champion.upper())
        self._champ_lbl.setFont(QFont('Segoe UI', 8))
        self._champ_lbl.setStyleSheet('background: transparent; border: none; color: #555566;')
        lay.addWidget(self._champ_lbl)

    def set_selected(self, v: bool):
        self._selected = v
        self._year_lbl.setStyleSheet(
            f'background: transparent; border: none; color: {"#ffffff" if v else "#aaaabc"};')
        self._champ_lbl.setStyleSheet(
            f'background: transparent; border: none; color: {"#888899" if v else "#555566"};')
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


class _SeasonStatDetail(QWidget):
    def __init__(self):
        super().__init__()
        self.setAutoFillBackground(False)
        self.setStyleSheet('background: transparent;')
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(48, 48, 48, 48)
        self._outer.setSpacing(0)
        self._placeholder('← Select a season')

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

    def load(self, season: dict):
        self._clear()
        s = season
        champ = s.get('champion') or {}
        stats = s.get('stats', {})
        standings = s.get('standings', [])
        tc = _team_color(champ.get('team', ''), champ.get('manufacturer', ''))

        n = QLabel(f"{s.get('year', '')} SEASON")
        n.setFont(QFont('Segoe UI', 24, QFont.Weight.Bold))
        n.setStyleSheet(f'color: {_lighten(tc, 60).name()}; background: transparent; border: none;')
        self._outer.addWidget(n)
        self._outer.addSpacing(6)

        sub = QLabel(f"Champion: {champ.get('name', '—')}  ·  {champ.get('manufacturer', '—')}")
        sub.setFont(QFont('Segoe UI', 13))
        sub.setStyleSheet('color: #ffffff; background: transparent; border: none;')
        self._outer.addWidget(sub)
        self._outer.addSpacing(22)
        self._outer.addWidget(_divider())
        self._outer.addSpacing(22)

        body = QWidget()
        body.setStyleSheet('background: transparent;')
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(36)

        # LEFT: final standings
        left = QWidget()
        left.setStyleSheet('background: transparent;')
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(0)
        left_lay.addWidget(_section_label('FINAL STANDINGS'))
        left_lay.addSpacing(14)
        for pos, st in enumerate(standings, start=1):
            medal = _medal_color(pos) or '#ccccdd'
            left_lay.addWidget(_text_row(
                str(pos), st['name'].upper(), f"{int(st.get('points', 0))} PTS",
                left_color=medal, mid_color='#ccccdd', left_w=36))
            left_lay.addSpacing(7)
        left_lay.addStretch(1)

        # RIGHT: season facts + champion
        right = QWidget()
        right.setStyleSheet('background: transparent;')
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)
        right_lay.addWidget(_section_label('SEASON FACTS'))
        right_lay.addSpacing(18)
        right_lay.addWidget(_stat_tiles([('ROUNDS', s.get('rounds', 0)),
                                         ('RIDERS', len(standings))]))
        right_lay.addSpacing(24)
        right_lay.addWidget(_divider())
        right_lay.addSpacing(18)
        right_lay.addWidget(_section_label('CHAMPION'))
        right_lay.addSpacing(18)
        cstats = stats.get(champ.get('name', ''), {})
        right_lay.addWidget(_stat_tiles([('POINTS', champ.get('points', 0)),
                                         ('WINS', cstats.get('wins', 0)),
                                         ('PODIUMS', cstats.get('podiums', 0))]))
        right_lay.addStretch(1)

        body_lay.addWidget(left, 5)
        body_lay.addWidget(right, 5)
        self._outer.addWidget(body)
        self._outer.addSpacing(40)


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
        self._items   = {}
        self._seasons = {}
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

        self._detail = _SeasonStatDetail()
        scroll_r = _make_scroll_area()
        scroll_r.setWidget(self._detail)
        root.addWidget(scroll_r, 7)

    def rebuild(self, seasons: list):
        for it in self._items.values():
            it.setParent(None)
        self._items.clear()
        self._seasons.clear()
        self._current = None

        ordered = sorted(enumerate(seasons),
                         key=lambda kv: str(kv[1].get('year', kv[0])), reverse=True)
        for i, s in ordered:
            key = str(s.get('year', f'S{i:02d}'))
            champ = s.get('champion') or {}
            tc = _team_color(champ.get('team', ''), champ.get('manufacturer', ''))
            item = _SeasonItem(key, s.get('year', key), champ.get('name', '—'), tc)
            item.clicked.connect(self._on_select)
            self._list_lay.insertWidget(self._list_lay.count() - 1, item)
            self._items[key] = item
            self._seasons[key] = s
        if ordered:
            self._on_select(next(iter(self._items)))
        else:
            self._detail._placeholder('No seasons yet')

    def _on_select(self, key: str):
        if self._current and self._current in self._items:
            self._items[self._current].set_selected(False)
        self._current = key
        self._items[key].set_selected(True)
        self._detail.load(self._seasons[key])

    def move_selection(self, forward: bool):
        keys = list(self._items.keys())
        if not keys:
            return
        idx = keys.index(self._current) if self._current in keys else -1
        new = keys[(idx + (1 if forward else -1)) % len(keys)]
        self._on_select(new)
        self._left_scroll.ensureWidgetVisible(self._items[new])

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
        empty_w = QWidget()
        empty_w.setStyleSheet('background: transparent;')
        el = QVBoxLayout(empty_w)
        self._empty_lbl = QLabel('No championship has been completed yet — '
                                 'finish a season and it will be recorded here.')
        self._empty_lbl.setFont(QFont('Segoe UI', 12))
        self._empty_lbl.setStyleSheet('color: #8a8aa2; background: transparent; border: none;')
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
        elif idx in (1, 2):
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                view = self._riders_view if idx == 1 else self._seasons_view
                view.move_selection(key == Qt.Key.Key_Down)
                return True
            if key in (Qt.Key.Key_Escape, Qt.Key.Key_Backspace):
                self._stack.setCurrentIndex(0)
                return True
            return True  # consume all other keys in the split views
        return False

    def _open_riders(self):
        self._stack.setCurrentIndex(1)

    def _open_seasons(self):
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
        if self._stack.currentIndex() in (1, 2):
            painter.fillRect(rect, _TINT)
