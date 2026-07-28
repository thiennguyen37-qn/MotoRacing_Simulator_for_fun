"""
Transfer Market — the off-season screen, shown once between two career seasons.

Sits between the Season Hub's "TO NEXT SEASON" summary and next year's calendar
setup: the player sees who retired, who lost their seat, which teams want them,
and the grid they'll be racing next year. Signing is the one decision on the
page; everything else is a read-out of what src.transfers already decided.

Keyboard only, like every other page (MotoWizard.eventFilter):
    ← →     switch tab
    ↑ ↓     move within a tab / scroll
    Enter   sign the highlighted offer, or start the season from the last tab

The market itself is rolled in initializePage() and held in memory until the
player confirms — nothing is written until then, so backing out of the page
leaves the career exactly as it was.

One thing this page decides rather than reports: which rider loses their seat to
the player. src.transfers can't, because it runs before the offer is picked — so
_seat_player applies it here, both for the grid preview and for real on commit.
"""

import random

from PyQt6.QtWidgets import (QWizardPage, QVBoxLayout, QHBoxLayout, QWidget,
                             QLabel, QFrame, QStackedWidget, QSizePolicy)
from PyQt6.QtGui import QFont, QColor, QPainter
from PyQt6.QtCore import Qt, QTimer

from app.pages.p_gallery import _make_scroll_area
from app.pages.p_season_hub import _StaticBackground, _TopTabBar, _panel_title, _HUB_BG
from app.widgets.table_utils import TEAM_COLOR, _DEFAULT_COLOR
from app.wizard import RAW
from src.transfers import (CONTRACT_TERMS, RIDER_STATS, pool_entry,
                           run_silly_season, seat_player, sign_player_contract,
                           team_table)

_TABS = ['DEPARTURES', 'YOUR CONTRACT', 'NEXT SEASON GRID', 'START NEXT SEASON']

_BIKE_LABELS = [('top_speed', 'TOP SPEED'), ('acceleration', 'ACCEL'),
                ('bike_braking', 'BRAKING'), ('bike_cornering', 'CORNERING'),
                ('stability', 'STABILITY')]


def _team_color(team: str) -> QColor:
    return TEAM_COLOR.get(team, _DEFAULT_COLOR)


def _label(text, size=10, bold=False, color='#e8e8f0', align=None) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont('Segoe UI', size, QFont.Weight.Bold if bold else QFont.Weight.Normal))
    lbl.setStyleSheet(f'color: {color}; background: transparent; border: none;')
    if align is not None:
        lbl.setAlignment(align)
    return lbl


def _card(child: QWidget, accent: str = '#1e1e2e', bg: int = 10) -> QFrame:
    f = QFrame()
    f.setStyleSheet(f'QFrame {{ background: rgba(255,255,255,{bg}); '
                    f'border: 1px solid {accent}; border-radius: 10px; }} '
                    f'QLabel {{ background: transparent; border: none; }}')
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 12, 16, 14)
    lay.setSpacing(6)
    lay.addWidget(child)
    return f


# ── Tab 1: who left ───────────────────────────────────────────────────────────

class _DeparturesPanel(QWidget):
    """Retirements on the left, riders whose contract was not renewed on the
    right — the two ways a seat opens, kept apart because they read very
    differently: one is a career ending on its own terms, the other is a team
    deciding not to go again.

    The right column is the busy one and gets the room to match. Renewal is a
    roll rather than a verdict, so a winter can vacate a dozen seats against one
    or two retirements, and both columns scroll because either can overflow.
    """

    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        root = QHBoxLayout(self)
        root.setContentsMargins(60, 10, 60, 20)
        root.setSpacing(28)
        self._cols = []
        self._scrolls = []
        # Not renewed outnumbers retired roughly three to one, so it gets the
        # wider column rather than an even split that leaves half the page blank.
        for title, weight in (('RETIRED', 10), ('CONTRACT NOT RENEWED', 14)):
            col = QVBoxLayout()
            col.setSpacing(10)
            col.addWidget(_panel_title(title))
            holder = QWidget()
            holder.setStyleSheet('background: transparent;')
            body = QVBoxLayout(holder)
            body.setContentsMargins(0, 0, 0, 0)
            body.setSpacing(8)
            scroll = _make_scroll_area()
            scroll.setWidget(holder)
            col.addWidget(scroll, 1)
            root.addLayout(col, weight)
            self._cols.append(body)
            self._scrolls.append(scroll)

    def scroll_by(self, dy: int):
        """Both columns move together. Qt clamps a column that has nothing to
        scroll, so the short one simply stays where it is — and the alternative,
        picking a column to drive, would need a focus concept this tab has no
        other use for."""
        for s in self._scrolls:
            bar = s.verticalScrollBar()
            bar.setValue(bar.value() + dy)

    def load(self, retired: list, dropped: list):
        for body in self._cols:
            while body.count():
                item = body.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

        for body, rows, empty in ((self._cols[0], retired, 'Nobody hung up their helmet'),
                                  (self._cols[1], dropped, 'Every seat was renewed')):
            if not rows:
                body.addWidget(_label(empty, 9, color='#666677'))
                body.addStretch(1)      # keep it at the top, not floating mid-column
                continue
            for r in rows:
                inner = QWidget()
                inner.setStyleSheet('background: transparent;')
                lay = QVBoxLayout(inner)
                lay.setContentsMargins(0, 0, 0, 0)
                lay.setSpacing(2)
                lay.addWidget(_label(str(r['name']).upper(), 11, bold=True))
                if 'efficiency' in r:
                    # Losing a seat is a demotion, not an exit — say where they
                    # ended up, since three quarters find a ride further down.
                    #
                    # The efficiency is shown without comment because it no
                    # longer explains the departure: renewal is a roll, so a
                    # rider who beat their bike can still be let go, and the
                    # figure is there as context rather than as a verdict.
                    where = (f"→ {r['landed']}" if r.get('landed')
                             else 'no ride found — out of the championship')
                    detail = f"{r['team']}   •   {r['efficiency']:+.1f} vs the bike"
                    lay.addWidget(_label(detail, 8, color='#9a9ab2'))
                    lay.addWidget(_label(
                        where, 8, bold=True,
                        color='#9a9ab2' if r.get('landed') else '#f87171'))
                else:
                    lay.addWidget(_label(f"{r['team']}   •   age {r['age']}",
                                         8, color='#9a9ab2'))
                body.addWidget(_card(inner, _team_color(r['team']).name()))
            body.addStretch(1)


# ── Tab 2: the player's offers ────────────────────────────────────────────────

def _verdict_line(verdict: dict | None) -> str:
    """One line on how last season measured against what the contract asked.

    A release has to be explainable at the moment it happens, otherwise it reads
    as the game deciding at random — so this says the target, the finish, and
    (mid-deal) how many seasons have now gone the wrong way.
    """
    if not verdict:
        return ''
    pos = verdict.get('position')
    where = f'finished P{pos}' if pos else 'never made the standings'
    target = verdict.get('objective')
    if target is None:
        return f'Last season: {where}  •  no target to hit'
    if verdict['met']:
        return f'Last season: target P{target} — {where}  ✓'
    tail = ''
    if not verdict.get('final_year', True):
        n = verdict.get('misses', 1)
        tail = f'   ({n} season{"s" if n != 1 else ""} missed on this deal)'
    return f'Last season: target P{target} — {where}  ✗{tail}'


class _OfferRow(QFrame):
    """One team's offer, with its bike measured against the player's current
    one — the only number that actually decides whether a move is worth it."""

    def __init__(self, offer, current_bike: dict):
        super().__init__()
        self._offer = offer
        self._focused = False
        self._signed = False
        self._term = CONTRACT_TERMS[0]
        self._existing = None      # set by show_existing() when mid-contract

        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 12, 18, 12)
        lay.setSpacing(20)

        left = QVBoxLayout()
        left.setSpacing(3)
        title = f'{offer.team.upper()}'
        if offer.current:
            title += '   (STAY)'
        left.addWidget(_label(title, 12, bold=True))
        left.addWidget(_label(
            f'{offer.manufacturer}  •  {offer.team_status}  •  bike {offer.power}',
            8, color='#9a9ab2'))
        lay.addLayout(left, 1)

        # Term and the target that comes with it, side by side: the whole point
        # is that these two move together, so a longer deal visibly costs
        # something rather than being a free upgrade.
        deal = QVBoxLayout()
        deal.setSpacing(1)
        deal.addWidget(_label('CONTRACT', 7, color='#666677',
                              align=Qt.AlignmentFlag.AlignCenter))
        self._term_lbl = _label('', 12, bold=True,
                                align=Qt.AlignmentFlag.AlignCenter)
        deal.addWidget(self._term_lbl)
        self._obj_lbl = _label('', 8, align=Qt.AlignmentFlag.AlignCenter)
        deal.addWidget(self._obj_lbl)
        lay.addLayout(deal)
        self._refresh_deal()

        for key, name in _BIKE_LABELS:
            new = int(offer.bike[key])
            delta = new - int(current_bike.get(key, new))
            box = QVBoxLayout()
            box.setSpacing(1)
            box.addWidget(_label(name, 7, color='#666677', align=Qt.AlignmentFlag.AlignCenter))
            box.addWidget(_label(str(new), 12, bold=True,
                                 align=Qt.AlignmentFlag.AlignCenter))
            if delta:
                col = '#4ade80' if delta > 0 else '#f87171'
                box.addWidget(_label(f'{delta:+d}', 8, color=col,
                                     align=Qt.AlignmentFlag.AlignCenter))
            else:
                box.addWidget(_label('—', 8, color='#555566',
                                     align=Qt.AlignmentFlag.AlignCenter))
            lay.addLayout(box)

        self._badge = _label('', 9, bold=True, color='#4ade80')
        self._badge.setFixedWidth(70)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._badge)
        self._apply()

    @property
    def offer(self):
        return self._offer

    @property
    def term(self) -> int:
        return self._term

    def cycle_term(self, step: int):
        """Step through the lengths this seat can be signed for."""
        i = CONTRACT_TERMS.index(self._term)
        self._term = CONTRACT_TERMS[(i + step) % len(CONTRACT_TERMS)]
        self._refresh_deal()

    def show_existing(self, until: int, objective):
        """Mid-contract: this row is the deal already running, not a new one.

        Without this the row advertises a fresh one-year term and whatever target
        that would carry — which is not what the player is signed to, and reads
        as the game having quietly changed their contract.
        """
        self._existing = (until, objective)
        self._refresh_deal()

    def _refresh_deal(self):
        if self._existing is not None:
            until, target = self._existing
            self._term_lbl.setText(f'THROUGH {until}')
            self._set_target(target)
            return
        years = 'YEAR' if self._term == 1 else 'YEARS'
        label = f'{self._term} {years}'
        self._term_lbl.setText(f'‹ {label} ›' if self._focused else label)
        self._set_target(self._offer.objectives.get(self._term))

    def _set_target(self, target):
        # No target at all is genuinely good news on a bad bike — say so in the
        # same green the bike gains use, rather than leaving a blank.
        if target is None:
            self._obj_lbl.setText('finish the season')
            self._obj_lbl.setStyleSheet('color:#4ade80; background:transparent; border:none;')
        else:
            self._obj_lbl.setText(f'target  P{target}')
            self._obj_lbl.setStyleSheet('color:#e8b64c; background:transparent; border:none;')

    def set_focused(self, v: bool):
        self._focused = v
        self._refresh_deal()
        self._apply()

    def set_signed(self, v: bool):
        self._signed = v
        self._badge.setText('SIGNED' if v else '')
        self._apply()

    def _apply(self):
        accent = _team_color(self._offer.team).name()
        if self._focused:
            border, bg = '#e02840', 'rgba(224,40,64,26)'
        elif self._signed:
            border, bg = '#4ade80', 'rgba(74,222,128,20)'
        else:
            border, bg = accent, 'rgba(255,255,255,8)'
        self.setStyleSheet(f'QFrame {{ background: {bg}; border: 1px solid {border}; '
                           f'border-radius: 10px; }} '
                           f'QLabel {{ background: transparent; border: none; }}')


class _OffersPanel(QWidget):
    """The player's own market. Whether their old team is on the list at all is
    the story: a released rider simply doesn't see it."""

    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        root = QVBoxLayout(self)
        root.setContentsMargins(50, 10, 50, 16)
        root.setSpacing(10)

        self._headline = _label('', 11, bold=True, align=Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._headline)
        # Last season's contract result, above the offers: what was asked, what
        # was delivered. Without it a release reads as the game being arbitrary.
        self._verdict = _label('', 9, align=Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._verdict)

        self._body = QWidget()
        self._body.setStyleSheet('background: transparent;')
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(0, 0, 0, 0)
        self._body_lay.setSpacing(8)
        self._scroll = _make_scroll_area()
        self._scroll.setWidget(self._body)
        root.addWidget(self._scroll, 1)

        self._rows = []
        self._focus = 0
        self._signed = None
        self._locked = False       # True while the player is mid-contract

    @property
    def signed(self):
        return self._signed

    @property
    def term(self) -> int:
        """Length of the deal on the row the player signed."""
        for r in self._rows:
            if r.offer is self._signed:
                return r.term
        return CONTRACT_TERMS[0]

    @property
    def locked(self) -> bool:
        return self._locked

    def load(self, offers: list, dropped: bool, current_bike: dict,
             current_team: str, verdict: dict | None = None,
             until: int | None = None):
        for r in self._rows:
            r.setParent(None)
            r.deleteLater()
        self._rows, self._focus, self._signed = [], 0, None
        # Mid-contract: the engine hands back exactly one offer, the seat they
        # already hold. There is no decision, so don't dress it up as one —
        # explain, and sign it for them so the flow moves on.
        self._locked = bool(verdict and not verdict.get('final_year', True))

        if self._locked:
            self._headline.setText(
                f'UNDER CONTRACT WITH {current_team.upper()} '
                f'THROUGH {until} — NOTHING TO DECIDE')
            self._headline.setStyleSheet('color:#7dd3fc; background:transparent; border:none;')
        elif dropped:
            self._headline.setText(
                f'{current_team.upper()} HAVE LET YOU GO — PICK YOUR NEXT RIDE')
            self._headline.setStyleSheet('color:#f87171; background:transparent; border:none;')
        else:
            self._headline.setText('CHOOSE YOUR TEAM FOR NEXT SEASON')
            self._headline.setStyleSheet('color:#e8e8f0; background:transparent; border:none;')

        self._verdict.setText(_verdict_line(verdict))
        self._verdict.setStyleSheet(
            f"color: {'#9a9ab2' if not verdict or verdict['met'] else '#f87171'}; "
            f'background: transparent; border: none;')

        for o in offers:
            row = _OfferRow(o, current_bike)
            self._rows.append(row)
            self._body_lay.addWidget(row)
        self._body_lay.addStretch(1)
        if self._locked and self._rows:
            self._rows[0].show_existing(until, (verdict or {}).get('objective'))
            self._signed = self._rows[0].offer
            self._rows[0].set_signed(True)
        self._sync()

    def _sync(self):
        for i, r in enumerate(self._rows):
            r.set_focused(i == self._focus)
        if self._rows:
            self._scroll.ensureWidgetVisible(self._rows[self._focus], 0, 40)

    def handle_key(self, key: int) -> bool:
        if not self._rows or self._locked:
            return False              # under contract: nothing here to change
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            step = -1 if key == Qt.Key.Key_Up else 1
            self._focus = (self._focus + step) % len(self._rows)
            self._sync()
            return True
        # Space cycles the term rather than Left/Right, which this page already
        # spends on switching tabs. With only two lengths on offer a single
        # toggle key says everything an arrow pair would.
        if key == Qt.Key.Key_Space:
            self._rows[self._focus].cycle_term(1)
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._signed = self._rows[self._focus].offer
            for i, r in enumerate(self._rows):
                r.set_signed(i == self._focus)
            return True
        return False


# ── Tab 3: next season's grid ─────────────────────────────────────────────────

class _GridPanel(QWidget):
    """All 12 teams as they'll line up next season, strongest bike first, with
    the arrivals marked so the reshuffle is readable at a glance."""

    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: transparent;')
        root = QVBoxLayout(self)
        root.setContentsMargins(50, 10, 50, 16)
        root.setSpacing(8)
        self._body = QWidget()
        self._body.setStyleSheet('background: transparent;')
        self._grid = QVBoxLayout(self._body)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(8)
        self._scroll = _make_scroll_area()
        self._scroll.setWidget(self._body)
        root.addWidget(self._scroll, 1)

    def load(self, teams, riders: list, rookies: set, moved: dict, player=None,
             year: int | None = None):
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        squads = {}
        for r in riders:
            squads.setdefault(r['team'], []).append(r)
        if player:
            squads.setdefault(player['team'], []).append(player)

        for _, t in teams.iterrows():
            name = str(t['team'])
            block = QFrame()
            accent = _team_color(name).name()
            block.setStyleSheet(f'QFrame {{ background: rgba(255,255,255,8); '
                                f'border-left: 3px solid {accent}; border-radius: 6px; }} '
                                f'QLabel {{ background: transparent; border: none; }}')
            lay = QHBoxLayout(block)
            lay.setContentsMargins(14, 8, 14, 8)
            lay.setSpacing(16)

            head = QVBoxLayout()
            head.setSpacing(1)
            head.addWidget(_label(name.upper(), 10, bold=True))
            head.addWidget(_label(f"bike {t['power']:.1f}", 8, color='#9a9ab2'))
            lay.addLayout(head, 2)

            for r in squads.get(name, []):
                is_player = player is not None and r is player
                cell = QVBoxLayout()
                cell.setSpacing(1)
                rating = sum(float(r[s]) for s in RIDER_STATS) / len(RIDER_STATS)
                cell.addWidget(_label(str(r['name']).upper(), 9, bold=True,
                                      color='#ffd24a' if is_player else '#e8e8f0'))
                tag = ''
                if is_player:
                    tag = 'YOU'
                elif r['name'] in rookies:
                    tag = 'ROOKIE'
                elif r['name'] in moved:
                    tag = f"← {moved[r['name']]}"
                cell.addWidget(_label(
                    f"{rating:.1f}   age {r['age']}" + (f'   •   {tag}' if tag else ''),
                    8, color='#4ade80' if tag in ('ROOKIE', 'YOU') else '#9a9ab2'))
                # Who is out of contract at the end of the season being set up —
                # i.e. who is on the market in the NEXT silly season. Reading
                # that off the grid is the only way to see a move coming.
                # None from a career that predates contracts, NaN if the rider
                # ever arrives via a DataFrame row — int() raises on both.
                until = r.get('contract_until')
                if until is not None and until == until:
                    final = year is not None and int(until) <= int(year)
                    cell.addWidget(_label(
                        'contract up this season' if final else f'under contract to {int(until)}',
                        7, color='#e8b64c' if final else '#666677'))
                lay.addLayout(cell, 3)
            lay.addStretch(1)
            self._grid.addWidget(block)
        self._grid.addStretch(1)

    def scroll_by(self, dy: int):
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.value() + dy)


# ── The page ──────────────────────────────────────────────────────────────────

class TransfersPage(QWizardPage):
    """Career only. Rolls the off-season, shows it, and commits it when the
    player signs — see transfer_market.md for the rules behind what it shows."""

    def __init__(self, wiz):
        super().__init__()
        self._wiz = wiz
        self.setTitle('')
        self.setSubTitle('')
        self._outcome = None
        self._teams = None
        self._seed = 0          # re-derived per off-season in initializePage
        self._tab = 0
        self._skipping = False

        self._bar = _TopTabBar(_TABS)
        self._departures = _DeparturesPanel()
        self._offers = _OffersPanel()
        self._grid = _GridPanel()

        self._start = QWidget()
        self._start.setStyleSheet('background: transparent;')
        s = QVBoxLayout(self._start)
        s.addStretch(1)
        self._start_msg = _label('', 12, bold=True, align=Qt.AlignmentFlag.AlignCenter)
        s.addWidget(self._start_msg)
        s.addStretch(1)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet('background: transparent;')
        for w in (self._departures, self._offers, self._grid, self._start):
            self._stack.addWidget(w)

        self._year = _label('', 10, bold=True, color='#9a9ab2',
                            align=Qt.AlignmentFlag.AlignCenter)
        self._hint = _label('◀ ▶  tab      ▲ ▼  move      Enter  select', 8,
                            color='#666677', align=Qt.AlignmentFlag.AlignCenter)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._bar)
        root.addSpacing(6)
        root.addWidget(self._year)
        root.addSpacing(10)
        root.addWidget(self._stack, 1)
        root.addWidget(self._hint)
        root.addSpacing(10)

        self._vbg = _StaticBackground(_HUB_BG)

    # ── Flow ─────────────────────────────────────────────────────────────────

    def initializePage(self):
        wiz = self._wiz
        target = int(wiz.season_year) + 1

        # Already rolled for this year (the player came back to the page, or the
        # app was restarted after confirming): there is nothing left to decide,
        # so hand straight over to calendar setup rather than re-running the
        # market and offering a second, different set of contracts.
        if wiz.transfers_done_for(target):
            self._skipping = True
            QTimer.singleShot(0, wiz.begin_next_season_setup)
            return
        self._skipping = False

        roster = wiz.ensure_roster(wiz.season_year)
        player = wiz.load_career_rider()
        self._teams = team_table(RAW)
        # Seeded from the career slot and the season, not left to chance. Leaving
        # this page and coming back re-runs the market, and with a fresh Random()
        # that handed back an entirely different winter each time — different
        # retirements, different moves, different offers. Nothing is written to
        # disk before signing (deliberately: quitting must not leave a career
        # half-transferred), so the only way to make the answer stable is to make
        # it reproducible. Same slot, same year, same market — including across a
        # restart.
        self._seed = int(wiz.career_slot or 0) * 10000 + int(wiz.season_year)
        self._outcome = run_silly_season(
            roster, self._standings(), player, int(wiz.season_year), RAW,
            random.Random(self._seed))

        self._year.setText(f'SILLY SEASON  —  {wiz.season_year} → {target}')
        until = player.get('contract_until') if player else None
        self._departures.load(self._outcome.retired, self._outcome.dropped)
        self._offers.load(self._outcome.player_offers, self._outcome.player_dropped,
                          {k: player[k] for k in
                           ('top_speed', 'acceleration', 'bike_braking',
                            'bike_cornering', 'stability')} if player else {},
                          player['team'] if player else '',
                          self._outcome.player_verdict,
                          int(until) if until is not None and until == until else None)
        self._refresh_grid()
        self._tab = 1 if self._outcome.player_offers else 0
        self._sync()

    def _standings(self) -> list:
        """Final order of the season just finished, newest archive entry. The
        market reads it to work out who beat their bike and who didn't."""
        try:
            seasons = self._wiz.load_history_seasons()
        except AttributeError:
            seasons = []
        return seasons[-1].get('standings', []) if seasons else []

    def _seat_player(self, riders: list, old_team: str, new_team: str, rng):
        """transfers.seat_player against this page's team table and season."""
        return seat_player(riders, self._teams, old_team, new_team,
                           self._outcome.year - 1, rng)

    def _refresh_grid(self):
        """Redraw the grid tab, showing the player at whichever team they have
        signed for so far (their current one until they pick), and the knock-on
        move their signing forces."""
        if self._outcome is None:
            return
        player = self._wiz.load_career_rider()
        signed = self._offers.signed
        riders = self._outcome.riders
        moved = {m['name']: m['from'] for m in self._outcome.moves}
        if player and signed:
            old_team = str(player['team'])
            player = dict(player)
            player.update({'team': signed.team, 'manufacturer': signed.manufacturer,
                           'team_status': signed.team_status, **signed.bike})
            # The grid shows contract length, so the preview has to show the deal
            # they just picked rather than the one that has already run out.
            # Mid-contract there is nothing to preview — the existing deal stands.
            verdict = self._outcome.player_verdict or {}
            if verdict.get('final_year', True):
                player['contract_until'] = (self._outcome.year - 1
                                            + self._offers.term)
            # Works on copies, and on the SAME seed _commit will use. The rng
            # here settles the displaced rider's new contract length, which the
            # grid now prints as a badge — so a different seed would preview a
            # deal that then changes the moment the player confirms.
            riders = [dict(r) for r in riders]
            displaced, to = self._seat_player(riders, old_team, signed.team,
                                              random.Random(self._seed + 1))
            if displaced is not None and to is not None:
                moved[displaced['name']] = signed.team
        rookies = {r['name'] for r in self._outcome.rookies}
        self._grid.load(self._teams, riders, rookies, moved, player,
                        self._outcome.year)

    _HINT_DEFAULT = '◀ ▶  tab      ▲ ▼  move      Enter  select'
    _HINT_OFFERS  = ('◀ ▶  tab      ▲ ▼  move      '
                     'Space  contract length      Enter  sign')

    def _sync(self):
        for i, c in enumerate(self._bar.cards()):
            c.set_focused(i == self._tab)
        self._stack.setCurrentIndex(self._tab)
        # The offers tab is the only one with a second axis to it, so it is the
        # only one that needs the extra key spelled out.
        self._hint.setText(
            self._HINT_OFFERS if self._tab == 1 and not self._offers.locked
            else self._HINT_DEFAULT)
        needs_pick = bool(self._outcome and self._outcome.player_offers
                          and self._offers.signed is None)
        self._start_msg.setText(
            'Sign a contract first — go back to YOUR CONTRACT'
            if needs_pick else 'Press Enter to set up next season')
        self._start_msg.setStyleSheet(
            f"color: {'#f87171' if needs_pick else '#4ade80'}; "
            f'background: transparent; border: none;')

    # ── Input ────────────────────────────────────────────────────────────────

    def handle_key(self, key: int) -> bool:
        if self._skipping or self._outcome is None:
            return True                      # mid-handover; swallow everything
        K = Qt.Key
        if key in (K.Key_Left, K.Key_Right):
            step = -1 if key == K.Key_Left else 1
            self._tab = (self._tab + step) % len(_TABS)
            self._sync()
            return True

        if self._tab == 1:
            if self._offers.handle_key(key):
                if key in (K.Key_Return, K.Key_Enter, K.Key_Space):
                    self._refresh_grid()
                    self._sync()
                return True
            return False

        # Both list tabs scroll the same way. Departures needs it as much as the
        # grid does: a first off-season can vacate a dozen seats, well past what
        # the column shows at once.
        if self._tab in (0, 2) and key in (K.Key_Up, K.Key_Down):
            panel = self._departures if self._tab == 0 else self._grid
            panel.scroll_by(-60 if key == K.Key_Up else 60)
            self._wiz.suppress_next_sfx = True
            return True

        if self._tab == 3 and key in (K.Key_Return, K.Key_Enter, K.Key_Space):
            self._commit()
            return True
        return False

    def _commit(self):
        """Point of no return: write the new grid and the player's contract,
        then hand over to next year's calendar.

        Nothing above this line touched disk — quitting on this page re-rolls
        the market next time rather than leaving a career half-transferred."""
        wiz, out = self._wiz, self._outcome
        if out.player_offers and self._offers.signed is None:
            return                            # the last tab says so already

        player = wiz.load_career_rider()
        signed = self._offers.signed
        riders, extra = out.riders, list(out.extra_pool)
        if player and signed:
            verdict = out.player_verdict or {}
            old_team = str(player['team'])
            player.update({'team': signed.team, 'manufacturer': signed.manufacturer,
                           'team_status': signed.team_status, **signed.bike})
            if verdict.get('final_year', True):
                # The old deal has run out, so this is a new one — new term, new
                # objective, misses back to zero.
                sign_player_contract(player, self._teams, signed.team,
                                     out.year - 1, self._offers.term)
            else:
                # Mid-contract: the only offer was the seat they already hold, so
                # the deal carries on untouched. All that changes is the tally of
                # seasons they have missed the target in.
                player['misses'] = verdict.get('misses', player.get('misses', 0))
            wiz.save_career_rider(player)
            displaced, to = self._seat_player(riders, old_team, signed.team,
                                              random.Random(self._seed + 1))
            if displaced is not None and to is None:
                extra.append(pool_entry(displaced))

        roster = wiz.load_roster() or {}
        roster.update({'year': out.year, 'riders': riders,
                       'pool_used': out.pool_used, 'extra_pool': extra,
                       'retired': (roster.get('retired') or []) + out.retired})
        wiz.save_roster(roster)
        wiz.apply_roster_to_df(roster)
        wiz.begin_next_season_setup()

    # ── Background ───────────────────────────────────────────────────────────

    _TINT = QColor(0, 0, 8, 190)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        offset = self.mapTo(self._wiz, self.rect().topLeft())
        self._vbg.paint(p, self, full_size=self._wiz.size(), offset=offset)
        # This page is dense text over a busy night-race photo — the Season Hub
        # gets away without a full-page tint because its content sits inside
        # tinted panels, but three columns of names and numbers need the whole
        # backdrop knocked back or the photo reads straight through them.
        p.fillRect(self.rect(), self._TINT)

    def paint_gap_overlay(self, painter, rect):
        painter.fillRect(rect, self._TINT)      # same knock-back below the page

    def nextId(self):
        return self._wiz.ID_CALENDAR
