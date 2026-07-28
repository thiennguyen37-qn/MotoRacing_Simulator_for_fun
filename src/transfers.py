"""
Off-season transfer market ("silly season") for Career mode.

Pure logic — no Qt, no file IO beyond reading the raw CSVs, so the whole thing
can be run thousands of times by the test harness. The wizard owns persistence
(see wizard.load_roster / save_roster); this module only takes a roster in and
hands a new one back.

The design and the reasoning behind every constant here live in
`transfer_market.md` at the project root. The short version:

* **AI ratings never change.** Riders only age and retire. Replacements come
  from `data/raw/riders_pool.csv`, whose ratings already span the grid's own
  range, so the grid keeps its character forever without a progression system.
  Simulation showed the alternatives (potential + age curves, or a frozen
  low-rated pool) both drag the field below the player within ~15 seasons.
* **A rider is judged against their machinery.** `efficiency()` is how many
  championship places they beat their bike by — the only fair way to compare a
  satellite rider with a factory one, and the thing a factory team is shopping
  for.
* **Contracts are what open seats, and they are absolute.** A rider still under
  contract cannot be dropped, poached or promoted — nothing here touches them.
  When a deal runs out the team almost always goes again (`renew_probability`);
  the exception is a season that failed to meet expectations at all, which
  vacates the seat.
* **A strong season buys a better seat, not a safer one.** Renewal odds are the
  same for a rider who scraped by and one who dragged a Phoenix into the points.
  What the second one gets is a route UP: promotion to their factory squad
  (`PROMOTE_MARGIN`) or a stronger team poaching them (`hire_bar`).
* **How long a deal runs depends on how you got the seat.** Kept on, promoted or
  called up as a rookie is two seasons; signing somewhere new after your contract
  lapsed is one.
* **Losing a seat is a demotion, not an exit.** A rider nobody renews drops to
  a weaker team if one will have them (`salvage_appeal`), and how far down turns
  on their age (`drop_tolerance`) — the young land near where they were, the
  veterans fall away. Only those nobody wants actually leave the championship,
  and moves are one-way up the grid otherwise.

The player takes a real seat. The grid is 24 riders in 12 two-seat teams and the
career rider is one of them, so whichever team they join runs the player plus one
AI rider, never three bikes. Making room is `drop_for_player`: the weaker of the
two sitting there loses the seat, and either swaps into the one the player just
vacated or drops into the career's own pool (`pool_entry`) to be called up again
in some later off-season.

Their offers are still "teams that want you" rather than "seats still empty",
though — a team will always make room for a rider it rates, so the player is
judged on efficiency like everyone else and never has to wait for a vacancy.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.loader import load_bikes, load_riders

# ── Tunables ──────────────────────────────────────────────────────────────────
# Every number here was calibrated against the real grid and 10 archived seasons
# of career slot0; see transfer_market.md for the tables behind each one.

RETIRE_MIN_AGE   = 32     # below this, never
RETIRE_FORCE_AGE = 38     # at this age, always
RETIRE_K         = 0.10   # per year past 31
RETIRE_SKILL_MAX = 1.6    # multiplier for the weakest rider…
RETIRE_SKILL_K   = 0.9    # …falling by this much across the rating range

# Efficiency is measured in championship places gained over what the bike alone
# would deliver. Across 10 real seasons it ranged -6.9 … +7.6 with a standard
# deviation of 3.7, so 3.0 is a little under one sigma: a clear difference, not
# a rounding error.
# The one line that matters: at or below this, the season did not meet
# expectations and the seat is lost. Above it — including finishing a little
# worse than the bike deserved — the deal is renewed.
#
# It sits at -3.0 rather than 0.0 for a reason worth keeping in mind. expected_rank
# gives every team two consecutive places (Ducati is worth P1-P2, baseline 1.5)
# and a finishing position is a whole number, so efficiency only ever lands on
# half steps: -0.5 means finishing in the second of your team's own two expected
# places, which is meeting expectations, not missing them. An earlier version put
# the boundary at 0.0 and split those two adjacent, equally-deserving results into
# a 6% and a 21% chance of losing the seat.
DROP_EFFICIENCY  = -3.0
# Clearly better than the machinery. This is the line for "far exceeded
# expectations", the band that earns a move UP the grid rather than just a
# renewal — and it needs no constant of its own, because that band is expressed
# entirely by the two gates a move already has to pass: PROMOTE_MARGIN for a
# satellite rider going to their factory squad, and hire_bar for being poached.
PROMOTE_MARGIN   = 3.0

# Hiring from another team: how far above the baseline a rider must be before a
# team of this strength will take them. Strong teams can hold out for someone
# good; the weakest factory has to take whoever is going.
HIRE_MIN_BAR     = -2.0   # what the weakest team on the grid will settle for
HIRE_MAX_BAR     = 2.0    # what the strongest demands

# Salvage: a rider who has just lost a factory seat is looking for a ride
# further down the grid, and a team down there weighs two things — how quick
# they still are, and how many years they have left. Age costs nothing until
# the late twenties and then bites hard, so a 26-year-old who had one bad
# season is worth a punt while a 35-year-old on the same ratings is not.
# Tuned to leave roughly three quarters of them on the grid; the rest are done.
SALVAGE_PEAK_AGE = 28     # age past which the years start counting against them
SALVAGE_AGE_K    = 1.8    # rating points a year beyond that is worth
SALVAGE_BAR      = 76.0   # what a team needs to see before signing them

# …and how far down the grid they are expected to fall. A rider still in their
# twenties lands near what they left; a veteran takes whatever is going. The
# allowance passes the grid's whole power range (19.6) by age 35, which is the
# same as no limit. See drop_tolerance / salvage_rank.
SALVAGE_DROP_TOLERANCE = 3.0    # power a rider under SALVAGE_PEAK_AGE gives up
SALVAGE_DROP_K         = 2.5    # extra power allowed per year past that age
SALVAGE_DROP_PENALTY   = 3.0    # rating points per power point beyond tolerance

# Rookie call-up: each team aims at a target drawn from a normal distribution
# whose mean shifts with the bike, then takes the nearest available rookie. The
# mean for the strongest bike sits SHIFT standard-deviations-of-power above the
# pool average and the weakest the same below, so a strong team reliably gets the
# better prospect — while sigma keeps it a tendency and not a draft order.
ROOKIE_SHIFT     = 2.5
ROOKIE_SIGMA     = 3.0

# `contract_until` is the last season a deal covers, so a rider is out of
# contract in the Y → Y+1 off-season once contract_until <= Y. In contract they
# are untouchable — not droppable, not poachable, not promotable. That is what
# keeps the market from reshuffling the whole grid every winter, and it is
# absolute: nothing in this module moves a rider who is still under contract.
#
# How long a new deal runs depends entirely on how the rider got there. Staying
# put, being promoted or arriving as a rookie all buy two seasons; taking a seat
# at a new team after your contract ran out buys one, so a rider who has just
# been let go has to prove it again straight away.
RENEW_YEARS    = 2    # kept on by the team they already ride for
PROMOTE_YEARS  = 2    # promoted from a satellite to its factory squad
ROOKIE_YEARS   = 2    # called up from the pool
MOVE_YEARS     = 1    # out of contract, signing somewhere new

# When a contract runs out the team decides whether to go again, on the same
# efficiency scale everything else here uses. Two outcomes, not a sliding scale:
# meet expectations (or miss them only slightly) and you are kept, fail to and
# you are not. Neither is quite certain — a winter with no surprises at all reads
# as a spreadsheet rather than a silly season.
RENEW_KEEP   = 0.95   # eff above DROP_EFFICIENCY
RENEW_FAILED = 0.10   # eff at or below it

RIDER_STATS = ['rider_braking', 'rider_cornering', 'aggression',
               'tyre_management', 'wet_performance', 'consistency']
# Which of the two riders already at a team makes way for the player. Wet
# performance is left out on purpose: it turns on the two or three wet races a
# calendar happens to throw up, so counting it lets a rain specialist keep a
# seat that a full season's evidence says they should lose.
DISPLACE_STATS = ['rider_braking', 'rider_cornering', 'aggression',
                  'tyre_management', 'consistency']
BIKE_STATS  = ['top_speed', 'acceleration', 'bike_braking', 'bike_cornering',
               'stability']
# riders_pool.csv uses the unprefixed names, same as riders_rating.csv
POOL_STATS  = {'braking': 'rider_braking', 'cornering': 'rider_cornering',
               'aggression': 'aggression', 'tyre_management': 'tyre_management',
               'wet_performance': 'wet_performance', 'consistency': 'consistency'}

RESERVED_NUMBERS = {1, 2, 3}   # kept free for the player's top-3 reward


# ── Results ───────────────────────────────────────────────────────────────────

@dataclass
class Offer:
    """A seat the player could take next season, with the bike that comes with it,
    and what the team would ask of them on each length of deal."""
    team: str
    manufacturer: str
    team_status: str
    power: float
    bike: dict                  # the five BIKE_STATS
    current: bool = False       # True for the player's existing team, if it wants them
    # {term in CONTRACT_TERMS: finishing position demanded, or None for "just
    # see the season out"}. Worked out here rather than in the UI so the target
    # the player is shown is the one they will actually be held to.
    objectives: dict = field(default_factory=dict)


@dataclass
class Outcome:
    """Everything the off-season did, ready for the UI to narrate."""
    year: int                              # the season this roster is FOR
    riders: list = field(default_factory=list)        # the new 24-rider AI grid
    retired: list = field(default_factory=list)       # [{name, team, age}]
    # Lost their factory seat. `landed` is the weaker team that took them, or
    # None if nobody would — those also appear in `left`, and only those are
    # actually off the grid next season.
    dropped: list = field(default_factory=list)
    left: list = field(default_factory=list)
    rookies: list = field(default_factory=list)       # [{name, team, age, ...}]
    moves: list = field(default_factory=list)         # [{name, from, to, kind}]
    pool_used: list = field(default_factory=list)     # cumulative, for the roster
    # The career's own pool: riders who lost their seat to the player, aged on
    # each off-season and callable again like any riders_pool.csv row.
    extra_pool: list = field(default_factory=list)
    player_offers: list = field(default_factory=list) # [Offer]
    player_dropped: bool = False           # their team declined to keep them
    # How the player's contract season went — see contract_verdict(). None
    # outside career mode. The UI narrates it and writes `misses` back.
    player_verdict: dict | None = None


# ── Teams ─────────────────────────────────────────────────────────────────────

def team_table(raw_path) -> pd.DataFrame:
    """The 12 teams with their bike and its power, strongest first.

    Power is the mean of the five bike stats. It drives everything: pick order,
    what a team can demand of a recruit, which rookie it aims for, and — through
    `expected_rank` — the baseline each rider is judged against.
    """
    bikes = load_bikes(raw_path).rename(columns={'bike_braking': 'braking',
                                                 'bike_cornering': 'cornering'})
    entries = pd.read_csv(Path(raw_path) / 'entry_info.csv')
    teams = (entries[['team', 'manufacturer', 'team_status']].drop_duplicates()
             .merge(bikes, on=['manufacturer', 'team_status']))
    teams['power'] = teams[['top_speed', 'acceleration', 'braking',
                            'cornering', 'stability']].mean(axis=1)
    teams = teams.sort_values('power', ascending=False).reset_index(drop=True)
    teams['rank'] = teams.index
    return teams


def satellite_of(teams: pd.DataFrame, manufacturer: str) -> str | None:
    """The satellite team of a manufacturer, or None — Suzuki and Kawasaki run a
    factory effort only, so those two can never promote from within."""
    m = teams[(teams.manufacturer == manufacturer) & (teams.team_status == 'satellite')]
    return None if m.empty else str(m.iloc[0]['team'])


def bike_for(teams: pd.DataFrame, team: str) -> dict:
    """The five bike stats a rider inherits by signing for this team. Changing
    team means changing machinery — that is the whole point of a transfer."""
    row = teams[teams.team == team].iloc[0]
    return {'top_speed': int(row['top_speed']), 'acceleration': int(row['acceleration']),
            'bike_braking': int(row['braking']), 'bike_cornering': int(row['cornering']),
            'stability': int(row['stability'])}


def expected_rank(teams: pd.DataFrame, team: str) -> float:
    """Championship position a seat at this team is worth on the bike alone.

    Teams are ranked by power and given two consecutive places each, so the
    strongest team's seats are 'worth' P1-P2 (baseline 1.5), the next P3-P4, and
    so on. Measuring the bikes directly with the race engine (identical riders,
    12 seasons) produced almost exactly this ordering — see the points column in
    transfer_market.md — so the cheap version is used here.
    """
    return 2.0 * int(teams[teams.team == team].iloc[0]['rank']) + 1.5


def hire_bar(teams: pd.DataFrame, team: str) -> float:
    """How good a recruit this team insists on, in efficiency terms.

    Scales with the bike: Ducati Factory can demand a proven over-performer,
    while the weakest factory has to take the leftovers — which is exactly the
    behaviour asked for, and why the bar goes negative at the bottom.
    """
    n = max(len(teams) - 1, 1)
    frac = 1.0 - int(teams[teams.team == team].iloc[0]['rank']) / n
    return HIRE_MIN_BAR + (HIRE_MAX_BAR - HIRE_MIN_BAR) * frac


# ── Rider metrics ─────────────────────────────────────────────────────────────

def rating(rider: dict) -> float:
    """Mean of the six rider stats — the single number teams and the retirement
    roll judge a rider by."""
    return sum(float(rider[s]) for s in RIDER_STATS) / len(RIDER_STATS)


def _norm(v: float) -> float:
    return min(1.0, max(0.0, (v - 70.0) / 29.0))


def efficiency(teams: pd.DataFrame, rider: dict, position: int | None) -> float:
    """Championship places this rider beat their bike by. Positive is good.

    The fair way to compare riders on different machinery, and the reason a
    ratio (`points scored / points the bike deserved`) is not used: the bottom
    teams' expected points round to nothing, so the ratio explodes there —
    Phoenix Motorsport "deserves" 2.4 points a season but really scores 50, a
    21x ratio, against Ducati's 0.86x. Places are bounded at both ends and so
    stay comparable right down the grid.

    `position` of None (didn't appear in the standings at all) reads as a
    bottom-of-the-field result rather than a blank.
    """
    if position is None:
        position = 25
    return expected_rank(teams, rider['team']) - float(position)


# ── Contract objectives ───────────────────────────────────────────────────────
# What a team writes into the player's contract: finish this position or better.
#
# The target has to account for the RIDER as well as the bike. expected_rank()
# alone answers "where should this machinery finish", which is the right question
# for the AI grid — everyone there is rated around 84 — but the wrong one for the
# player, who spends their first five seasons as the only sub-84 rider on it. A
# rating-62 rookie finishes P24 on a midfield bike, so a bike-par target is
# unreachable by construction rather than by riding badly: measured over full
# careers, that version was met 0% of the time in season two.
#
# So the baseline is measured on both axes. Each cell is the median championship
# finish for a rider of that rating on that team's bike, over 400 synthetic
# seasons scored with the race engine's own perf_score_race. Rows are
# BASELINE_RATINGS; columns are the team's power rank, index 0 being the
# strongest bike. Regenerate with tools/contracts/contract_targets.py — and note
# that a change to bikes_rating.csv or the 24 CSV riders invalidates the whole
# table, which is what the 84.5 row check in test_transfers.py guards.
#
# A linear fit was tried and rejected: R^2 0.932 sounds fine but it is off by up
# to 7 places, worst exactly where it matters most (a quick rider on a fast bike,
# where finishing position is squashed against P1). The fit put a three-year
# Ducati target at P5 where the measured answer is P2.
BASELINE_RATINGS = (62.0, 67.0, 73.0, 78.0, 82.0, 84.5, 86.5, 88.0, 89.5,
                    91.0, 93.0, 95.0)
BASELINE_FINISH = (
    (20, 22, 23, 23, 23, 24, 24, 24, 24, 24, 24, 24),   # 62 — a debut season
    (17, 19, 21, 21, 21, 23, 23, 24, 24, 24, 24, 24),   # 67
    (11, 15, 16, 17, 17, 20, 20, 22, 23, 24, 24, 24),   # 73
    (8,  10, 12, 12, 13, 16, 16, 18, 20, 21, 23, 24),   # 78
    (4,   8,  9,  9, 10, 12, 13, 15, 18, 18, 20, 24),   # 82
    (2,   6,  7,  7,  8, 11, 11, 13, 16, 16, 19, 22),   # 84.5 — the grid median
    (1,   4,  6,  6,  7,  9, 10, 11, 14, 15, 16, 21),   # 86.5
    (1,   3,  4,  5,  5,  9,  9, 10, 13, 13, 16, 20),   # 88
    (1,   2,  3,  3,  4,  7,  8,  9, 12, 11, 14, 19),   # 89.5 — top of the AI grid
    # Above the grid's own range, because the player goes there and the AI never
    # does: XP is earned by finishing position, so a career spent at the front
    # compounds up to the 95.0 ceiling (five growth stats capped at 99, wet stuck
    # at 75). Without these rows the table would clamp at 89.5 and a champion's
    # contract would quietly stop asking anything of them.
    (1,   2,  3,  3,  3,  6,  6,  8, 11, 11, 13, 18),   # 91
    (1,   1,  2,  2,  2,  4,  5,  6,  9,  9, 11, 16),   # 93
    (1,   1,  1,  2,  1,  3,  3,  5,  8,  8,  9, 15),   # 95 — the stat ceiling
)

# How much worse than par the team will tolerate, by contract length. A longer
# deal buys the rider a season they cannot be dropped in, so the team asks for
# more in return: two years is held to par exactly, one year gets two places of
# grace. Measured pass rates are 97% and 69% — and the point of the whole
# rating-aware baseline is that those hold steady from a rookie's 62 to a
# champion's 95 instead of collapsing in the early career.
#
# Only one and two years exist, because that is what road racing actually signs.
# Three was measured too and sat at 69% with two years on 89%, which made the
# two-year deal nearly free and so not a choice at all; dropping the long option
# is what forces the remaining two apart to 97/69.
OBJECTIVE_SLACK = {1: 2.0, 2: 0.0}
CONTRACT_TERMS  = (1, 2)         # lengths the player can be offered
GRID_SIZE       = 24


def baseline_finish(teams: pd.DataFrame, team: str, rider_rating: float) -> float:
    """Where a rider of this rating would normally finish on this team's bike.

    Interpolates BASELINE_FINISH on rating; the team picks the column outright,
    since there are exactly twelve of them. Outside the measured rating range the
    nearest row is used rather than an extrapolation — both ends are already
    against a wall (P24 at the bottom, P1 at the top), so running the line on
    would only invent precision the measurement does not have.
    """
    col = int(teams[teams.team == str(team)].iloc[0]['rank'])
    column = [row[col] for row in BASELINE_FINISH]
    r = float(rider_rating)
    if r <= BASELINE_RATINGS[0]:
        return float(column[0])
    if r >= BASELINE_RATINGS[-1]:
        return float(column[-1])
    for i in range(1, len(BASELINE_RATINGS)):
        hi = BASELINE_RATINGS[i]
        if r <= hi:
            lo = BASELINE_RATINGS[i - 1]
            frac = (r - lo) / (hi - lo)
            return column[i - 1] + frac * (column[i] - column[i - 1])
    return float(column[-1])                      # unreachable; keeps mypy calm


def sign_player_contract(player: dict, teams: pd.DataFrame, team: str,
                         year: int, length: int) -> None:
    """Write the player's new deal onto their rider record. Mutates in place.

    `year` is the season just finished, so a deal agreed in this off-season
    starts at year + 1 and a one-year term covers exactly that season. The
    objective is fixed at signing and does not move afterwards: the player is
    held to what they agreed to, even if they improve enough during the deal
    that the same seat would ask more of them today.

    `misses` resets, because it counts misses within one contract.
    """
    player['contract_from']  = int(year) + 1
    player['contract_until'] = int(year) + int(length)
    player['objective'] = objective_for(teams, team, rating(player), length)
    player['misses'] = 0


def contract_verdict(player: dict, position: int | None, year: int) -> dict:
    """How the player's contract season went, read off the final standings.

    `objective` is the position their deal asked for, stored on the rider when
    they signed; None means the deal only asked them to finish the season, which
    is what a seat on the worst bike on the grid is worth. A rider missing from
    the standings entirely counts as not having delivered.

    `misses` accumulates across the seasons of one contract and resets when a new
    one is signed. On a two-year deal the first miss is only a warning — the seat
    is under contract and cannot be taken — so it exists to be shown to the
    player, not to drive the drop. Only `final_year and not met` costs the seat.
    """
    objective = player.get('objective')
    met = objective is None or (position is not None and position <= int(objective))
    return {'objective': objective,
            'position': position,
            'met': met,
            'final_year': out_of_contract(player, year),
            'misses': int(player.get('misses', 0)) + (0 if met else 1)}


def objective_for(teams: pd.DataFrame, team: str, rider_rating: float,
                  length: int) -> int | None:
    """The position a contract of this length demands — or None for no target.

    None means the bike is slow enough that "a bit better than par" lands past
    the back of the grid, so the deal asks only that they finish the season. It
    is the honest answer for a Phoenix Motorsport seat, and it keeps the UI from
    printing a target of P26.
    """
    target = round(baseline_finish(teams, team, rider_rating)
                   + OBJECTIVE_SLACK[int(length)])
    return None if target >= GRID_SIZE else int(target)


# ── Off-season steps ──────────────────────────────────────────────────────────

def retire_probability(rider: dict) -> float:
    """Chance this rider hangs up their helmet. Nobody retires before 32,
    everybody has by 38, and a rider still riding well hangs on longer than a
    fading one of the same age."""
    age = int(rider['age'])
    if age < RETIRE_MIN_AGE:
        return 0.0
    if age >= RETIRE_FORCE_AGE:
        return 1.0
    relief = RETIRE_SKILL_MAX - RETIRE_SKILL_K * _norm(rating(rider))
    return min(1.0, max(0.0, RETIRE_K * (age - RETIRE_MIN_AGE + 1) * relief))


def renew_probability(eff: float) -> float:
    """Chance the rider's own team hands them another RENEW_YEARS seasons.

    Rolled for every seat whose contract has run out, factory and satellite
    alike, and it turns on one thing: did the season meet expectations. Missing
    them a little still counts as meeting them — see DROP_EFFICIENCY for why the
    line is not at zero.

    Deliberately near-certain rather than certain in both directions. The odds
    exist so a silly season can still surprise, not to model a sliding scale of
    merit: what a strong season really buys is not a safer seat but a better one,
    through the promotion and poaching paths.
    """
    return RENEW_KEEP if eff > DROP_EFFICIENCY else RENEW_FAILED


def salvage_appeal(rider: dict) -> float:
    """How a rider who just lost their seat looks to a team further down.

    Their rating, docked for every year past the late twenties. It is the
    combination that decides them: quick and young is an easy yes, slow and old
    an easy no, and the interesting cases are the ones in between — a fading
    veteran who is still fast enough, or a modest rider young enough to be worth
    the wait. Compare against SALVAGE_BAR.
    """
    return rating(rider) - SALVAGE_AGE_K * max(0, int(rider['age']) - SALVAGE_PEAK_AGE)


def drop_tolerance(rider: dict) -> float:
    """How much bike power this rider is expected to give up, losing their seat.

    A rider who still has years ahead of them lands close to where they were —
    the good teams that are still looking want them, and they have no reason to
    settle. A veteran has no such pull and takes whatever is left, however far
    down the grid that is. Past the mid-thirties the allowance exceeds the whole
    grid's power range (91.8 down to 72.2, so 19.6), which is the same as no
    limit at all.
    """
    return SALVAGE_DROP_TOLERANCE + SALVAGE_DROP_K * max(
        0, int(rider['age']) - SALVAGE_PEAK_AGE)


def salvage_rank(rider: dict, drop: float) -> float:
    """Which rider a team takes first when several have just lost their seat.

    `drop` is the bike power this particular move would cost them. The vacancy
    queue runs strongest bike first, so what this ranking really decides is how
    far down the grid each rider falls.

    Two parts. `salvage_appeal` is how quick they still are, docked for age — the
    same figure that decides whether they are signable at all. Subtracted from it
    is whatever the drop exceeds their `drop_tolerance`, which is what separates
    young from old: a 24-year-old looks poor value to a team four power off what
    they just left, so the strong teams still looking take them first and the
    veterans fall through to the bottom.

    It is a preference, never a bar. A weak team with one candidate still signs
    them — otherwise a young rider with no near-equivalent seat available would
    be pushed out of the championship altogether, which is the opposite of the
    intent: it is the veterans who are supposed to run out of options.

    Last season's efficiency is deliberately not part of it, for the same reason
    it is left out of salvage_appeal: they lost the seat over that season, and
    counting it twice would leave nobody signable.
    """
    over = max(0.0, float(drop) - drop_tolerance(rider))
    return salvage_appeal(rider) - SALVAGE_DROP_PENALTY * over


def displace_rating(rider: dict) -> float:
    """Mean of DISPLACE_STATS — how a team ranks its two riders when one of them
    has to make way for the player."""
    return sum(float(rider[s]) for s in DISPLACE_STATS) / len(DISPLACE_STATS)


def pool_entry(rider: dict) -> dict:
    """A grid rider re-shaped as a riders_pool.csv record, so a career's own pool
    can hold them in the same columns as the rows read from that file.

    Everything tied to the seat they just lost — team, bike, number, contract —
    is dropped: those come back from whichever team calls them up (see `sign`).
    """
    entry = {'name': str(rider['name']), 'age': int(rider['age']),
             'nationality': str(rider.get('nationality', ''))}
    for src, dst in POOL_STATS.items():
        entry[src] = float(rider[dst])
    return entry


def _grid_shape(entry: dict) -> dict:
    """A pool record back in grid column names, so the shared rider metrics
    (rating, retire_probability) read it without a special case."""
    rider = {'name': entry['name'], 'age': int(entry['age'])}
    for src, dst in POOL_STATS.items():
        rider[dst] = float(entry[src])
    return rider


def drop_for_player(riders: list, team: str) -> dict | None:
    """Free up one of `team`'s two seats for the player, weaker rider first.

    Mutates `riders` and hands back whoever lost the seat, or None if the team
    was already down to one rider — which is the normal case for the team the
    player is re-signing with, since the market left their seat open for them.
    """
    squad = [r for r in riders if str(r['team']) == str(team)]
    if len(squad) < 2:
        return None
    out = min(squad, key=displace_rating)
    riders.remove(out)
    return out


def seat_player(riders: list, teams: pd.DataFrame, old_team: str, new_team: str,
                year: int, rng: random.Random) -> tuple[dict | None, str | None]:
    """Sit the player in one of `new_team`'s two seats, and say what became of
    the rider they displaced.

    Signing the player costs a team its weaker rider (drop_for_player) the seat.
    If the player is moving, that rider takes the one they left behind — a
    straight swap, which is what keeps all twelve teams two-handed year after
    year. If there is nowhere to put them (the player is re-signing, or their old
    team already refilled the seat because it was the team that dropped them)
    they are off the grid, and the caller should pool_entry() them.

    This can't happen inside run_silly_season: which team the player signs for
    isn't known until they pick an offer, which is long after the market has
    finished placing everybody else.

    Mutates `riders`. Returns (displaced rider, the team they moved to, or None
    if they left the grid).
    """
    displaced = drop_for_player(riders, new_team)
    if displaced is None:
        return None, None                      # the market left the seat open
    if str(old_team) == str(new_team) or \
            sum(1 for r in riders if str(r['team']) == str(old_team)) >= 2:
        return displaced, None
    # A swap into the seat the player just vacated, which is a move to a new team
    # — one year, same as anyone else out of contract signing somewhere new.
    sign(displaced, teams[teams.team == str(old_team)].iloc[0], year, MOVE_YEARS)
    riders.append(displaced)
    return displaced, str(old_team)


def out_of_contract(rider: dict, year: int) -> bool:
    """True once the deal has run out. `year` is the season just finished."""
    return int(rider.get('contract_until', year)) <= int(year)


def sign(rider: dict, team_row, year: int, years: int = MOVE_YEARS) -> None:
    """Put a rider on a team's books for next season: new colours, new bike, new
    contract. Mutates in place — callers already hold the dict.

    `years` is the term, and every caller states it: how a rider arrived is what
    decides how long they get (see the note by MOVE_YEARS). The default is the
    one-year deal an out-of-contract rider gets at a new team, which is the
    commonest route through here.
    """
    rider['team'] = str(team_row['team'])
    rider['manufacturer'] = str(team_row['manufacturer'])
    rider['team_status'] = str(team_row['team_status'])
    rider.update({'top_speed': int(team_row['top_speed']),
                  'acceleration': int(team_row['acceleration']),
                  'bike_braking': int(team_row['braking']),
                  'bike_cornering': int(team_row['cornering']),
                  'stability': int(team_row['stability'])})
    rider['contract_until'] = int(year) + int(years)


def call_up(pool: pd.DataFrame, used: set, team_row, taken_numbers: set,
            year: int, rng: random.Random) -> dict | None:
    """Take a rookie out of the pool for this team.

    The team aims at a target rating drawn from a normal distribution centred a
    little above or below the pool average depending on its bike, then signs
    whoever is closest to that target. Nobody can see how a rookie will turn
    out, so this is a nudge and not a scouting system: a strong team usually
    lands a good one, but the pool's best prospect regularly ends up somewhere
    unglamorous.
    """
    free = pool[~pool['name'].isin(used)]
    if free.empty:
        return None
    ratings = free['rating'].to_numpy()
    power_std = pool.attrs['power_std']
    z = 0.0 if not power_std else (float(team_row['power']) - pool.attrs['power_mean']) / power_std
    target = rng.gauss(float(pool['rating'].mean()) + ROOKIE_SHIFT * z, ROOKIE_SIGMA)
    row = free.iloc[int((abs(ratings - target)).argmin())]

    rider = {'name': str(row['name']), 'age': int(row['age']),
             'nationality': str(row['nationality'])}
    for src, dst in POOL_STATS.items():
        rider[dst] = float(row[src])
    rider['bike_number'] = free_number(taken_numbers, rng)
    taken_numbers.add(rider['bike_number'])
    sign(rider, team_row, year, ROOKIE_YEARS)
    used.add(rider['name'])
    return rider


def free_number(taken: set, rng: random.Random) -> int:
    """A random bike number nobody is using, from 4-99.

    Random rather than lowest-free so a run of rookies doesn't come up wearing
    #4, #5, #6. 1-3 are never handed out: they belong to the player's top-three
    reward (see p4_championship._maybe_offer_number_switch).

    `taken` is rebuilt each off-season from the riders actually on the grid, so
    a number goes back into circulation once its owner retires or drops out.
    """
    free = [n for n in range(4, 100) if n not in taken]
    return rng.choice(free) if free else max(taken) + 1


# ── The market ────────────────────────────────────────────────────────────────

def _load_pool(raw_path, teams: pd.DataFrame, extra: list | None = None) -> pd.DataFrame:
    """The rookie pool: the shared CSV, plus this career's own displaced riders.

    `extra` are pool_entry() records — riders the player pushed out of a seat.
    They sit in the same columns as the CSV rows and are picked the same way, so
    a call-up can just as easily bring back a 29-year-old who lost their ride
    three seasons ago as hand a debut to an 18-year-old.
    """
    pool = pd.read_csv(Path(raw_path) / 'riders_pool.csv')
    if extra:
        pool = pd.concat([pool, pd.DataFrame(extra)[pool.columns]], ignore_index=True)
    pool['rating'] = pool[list(POOL_STATS)].mean(axis=1)
    pool.attrs['power_mean'] = float(teams['power'].mean())
    pool.attrs['power_std'] = float(teams['power'].std())
    return pool


def run_silly_season(roster: dict, standings: list, player: dict | None,
                     year: int, raw_path, rng: random.Random | None = None) -> Outcome:
    """Roll the grid from `year` into `year + 1`.

    `roster`  — the wizard's roster dict (riders / retired / pool_used /
                extra_pool).
    `standings` — the finished season's championship order, as archived in
                  history.json: [{'name', 'team', 'points'}, …] best first.
    `player`  — the career rider dict, or None outside career mode. Not one of
                `roster['riders']`, but they do hold a seat at their team, so
                the seat count below leaves it open for them.

    Returns an Outcome; nothing is written to disk here.
    """
    rng = rng or random.Random()
    year = int(year)
    teams = team_table(raw_path)
    extra_pool = [dict(e) for e in (roster.get('extra_pool') or [])]
    pool = _load_pool(raw_path, teams, extra_pool)
    by_team = {str(t['team']): t for _, t in teams.iterrows()}

    position = {str(s['name']): i + 1 for i, s in enumerate(standings or [])}
    riders = [dict(r) for r in roster.get('riders', [])]
    used = set(roster.get('pool_used', []))
    out = Outcome(year=year + 1, pool_used=list(used))

    # Efficiency is measured on the season just finished, before anyone moves.
    eff = {r['name']: efficiency(teams, r, position.get(r['name'])) for r in riders}

    # 1 ── everyone gets a year older, including whoever is sitting out in the
    # career's own pool: a rider the player displaced has to be the age they
    # would actually be when a team comes back for them. (The CSV pool is not
    # aged — those are the perpetual crop of newcomers, not real people waiting.)
    for r in riders:
        r['age'] = int(r['age']) + 1
    for e in extra_pool:
        e['age'] = int(e['age']) + 1

    # 2 ── retirements
    staying = []
    for r in riders:
        if rng.random() < retire_probability(r):
            out.retired.append({'name': r['name'], 'team': r['team'], 'age': r['age']})
        else:
            staying.append(r)
    riders = staying
    # Sitting out, they eventually stop waiting for the call. Same roll as the
    # grid, but not announced: they left the championship seasons ago and a
    # retirement notice for someone nobody has seen race would read as a bug.
    extra_pool = [e for e in extra_pool
                  if e['name'] in used
                  or rng.random() >= retire_probability(_grid_shape(e))]

    # 3 ── renewals. Every seat whose contract has run out gets a roll, factory
    # and satellite alike, weighted by how the season went (renew_probability).
    # Lose the roll and the seat is genuinely vacated: they become a free agent
    # and take their chances further down the grid at step 5c.
    #
    # This is probabilistic on purpose. transfer_market.md records what a
    # deterministic "underperform and you are out" rule did when applied to all
    # 24 seats — 3.0 replacements a season, pool exhausted by season 34. Rolling
    # for it instead, with a bad season worth a 20% chance rather than a
    # certainty, lands at ~2.2 and keeps the pool alive past season 45.
    #
    # NOTE: winning the roll does NOT stamp the new term here. The contract stays
    # lapsed for the rest of this off-season, because promotion (5a) and poaching
    # (5b) both select on out_of_contract() — stamping now empties their
    # candidate pools and silently kills both paths, with no error and a market
    # that still appears to run. Step 7 does the stamping. See contracts.md.
    dropped_eff = {}
    keeping = []
    free_agents = []           # lost their seat, still looking for another
    lost_from = {}             # name -> the team that let them go
    lost_age = {}              # name -> age, kept for the departures read-out
    for r in riders:
        if not out_of_contract(r, year):
            keeping.append(r)
            continue
        if rng.random() < renew_probability(eff[r['name']]):
            keeping.append(r)
        else:
            dropped_eff[r['team']] = eff[r['name']]
            lost_from[r['name']] = r['team']
            lost_age[r['name']] = r['age']
            free_agents.append(r)
    riders = keeping

    # 3b ── the player's own market, settled before any seat is filled: whether
    # their team is keeping them decides whether that team has one seat to fill
    # or two. It reads nothing the steps below produce — only where everyone
    # finished and who the player's team-mates were — so running it here rather
    # than at the end changes no outcome.
    if player:
        out.player_offers, out.player_dropped, out.player_verdict = _player_market(
            teams, player, position, year)

    # 4 ── who sits where now, and which seats need filling
    squads = {str(t): [] for t in teams['team']}
    for r in riders:
        squads[r['team']].append(r)
    # Free agents keep their number reserved for the whole market: they may yet
    # be signed further down the grid, and a rookie called up in the meantime
    # must not be handed the same one.
    taken_numbers = {int(r['bike_number']) for r in riders}
    taken_numbers |= {int(r['bike_number']) for r in free_agents}
    if player:
        taken_numbers.add(int(player['bike_number']))

    # The player holds one of their team's two seats unless that team has just
    # let them go, so that team is a rider short on paper and must NOT have the
    # gap filled — do that and it would run three bikes the moment the player
    # re-signs. Their seat only reopens to the AI if they were dropped; if they
    # then leave of their own accord, the team they join hands its spare rider
    # over to the one they left (see drop_for_player and p_transfers._commit).
    held = (str(player['team']) if player and not out.player_dropped else None)

    def occupancy(team: str) -> int:
        return len(squads[team]) + (1 if team == held else 0)

    queue = []
    for _, t in teams.iterrows():                 # strongest bike picks first
        name = str(t['team'])
        for _ in range(2 - occupancy(name)):
            queue.append({'team': name, 'baseline': dropped_eff.get(name, 0.0)})

    # 5 ── fill them, cascading: promoting a satellite rider opens their seat,
    # which joins the back of the queue rather than jumping the order.
    guard = 0
    while queue and guard < 200:
        guard += 1
        seat = queue.pop(0)
        row = by_team[seat['team']]
        if occupancy(seat['team']) >= 2:
            continue                              # already filled by a cascade

        hire = None
        kind = ''

        # (a) factory first refusal on its own satellite
        if row['team_status'] == 'factory':
            sat = satellite_of(teams, str(row['manufacturer']))
            if sat:
                cands = [r for r in squads[sat] if out_of_contract(r, year)]
                if cands:
                    best = max(cands, key=lambda r: eff[r['name']])
                    if eff[best['name']] - seat['baseline'] >= PROMOTE_MARGIN:
                        hire, kind = best, 'promote'

        # (b) recruit from a weaker team — never the other way, so a rider who
        # lost a factory seat is gone rather than dropping into a satellite.
        if hire is None:
            bar = hire_bar(teams, seat['team'])
            cands = []
            for other, squad in squads.items():
                o = by_team[other]
                if float(o['power']) >= float(row['power']) or occupancy(other) <= 1:
                    continue                      # not a step up, or would gut them
                if row['team_status'] == 'satellite' and \
                        o['manufacturer'] == row['manufacturer']:
                    continue                      # satellites don't raid their own factory
                cands += [r for r in squad if out_of_contract(r, year)
                          and eff[r['name']] >= bar]
            if cands:
                hire, kind = max(cands, key=lambda r: eff[r['name']]), 'hire'

        if hire is not None:
            old = hire['team']
            squads[old].remove(hire)
            # A promotion is a team backing a rider it already knows, so it comes
            # with two seasons. Being poached is a new team taking a chance on
            # someone whose deal just lapsed — one season, prove it again.
            sign(hire, row, year,
                 PROMOTE_YEARS if kind == 'promote' else MOVE_YEARS)
            squads[seat['team']].append(hire)
            out.moves.append({'name': hire['name'], 'from': old,
                              'to': seat['team'], 'kind': kind})
            queue.append({'team': old, 'baseline': 0.0})   # cascade
            continue

        # (c) a rider who lost their factory seat, before an unknown rookie.
        #
        # A real season produces two or three genuine newcomers, not eight — so
        # a proven rider dropping down the grid is far more plausible than the
        # championship reinventing a quarter of itself every winter. They can
        # only go to a weaker team than the one that let them go (that IS the
        # demotion), and they have to still look worth signing — see
        # salvage_appeal, which is what stops a 36-year-old with fading ratings
        # walking into a seat a rookie could have had. Their season's efficiency
        # is deliberately NOT part of it: they were just dropped for exactly
        # that, and judging them on it twice would leave nobody signable.
        # This replaced the earlier "a dropped factory rider leaves the
        # championship" rule, and it cut replacements from 2.4 a season to ~1.9.
        if free_agents:
            cands = [r for r in free_agents
                     if float(by_team[lost_from[r['name']]]['power']) > float(row['power'])
                     and salvage_appeal(r) >= SALVAGE_BAR]
            if cands:
                hire = max(cands, key=lambda r: salvage_rank(
                    r, float(by_team[lost_from[r['name']]]['power']) - float(row['power'])))
                free_agents.remove(hire)
                sign(hire, row, year, MOVE_YEARS)
                squads[seat['team']].append(hire)
                out.moves.append({'name': hire['name'], 'from': lost_from[hire['name']],
                                  'to': seat['team'], 'kind': 'demoted'})
                continue                       # no cascade: their old seat is the one being filled

        # (d) nobody left — call up a rookie
        rookie = call_up(pool, used, row, taken_numbers, year, rng)
        if rookie is None:
            break                                  # pool exhausted; leave the seat
        squads[seat['team']].append(rookie)
        out.rookies.append(dict(rookie))

    # 6 ── record what became of everyone who lost a seat: most drop down the
    # grid, and only the ones nobody would take are actually gone.
    landed = {m['name']: m['to'] for m in out.moves if m['kind'] == 'demoted'}
    still_free = {r['name'] for r in free_agents}
    for name, old_team in lost_from.items():
        entry = {'name': name, 'team': old_team, 'age': lost_age[name],
                 'efficiency': round(eff[name], 1), 'landed': landed.get(name)}
        out.dropped.append(entry)
        if name in still_free:
            out.left.append(entry)

    # 7 ── stamp the renewals agreed back at step 3. Anyone still carrying a
    # lapsed contract kept their seat there and was not poached away since, so
    # this is where their new term actually goes on the books. Doing it here
    # rather than at step 3 is what leaves them visible to promotion and poaching
    # in between — see the note at step 3.
    riders = [r for squad in squads.values() for r in squad]
    for r in riders:
        if out_of_contract(r, year):
            r['contract_until'] = year + RENEW_YEARS

    out.riders = riders
    out.pool_used = sorted(used)
    out.extra_pool = extra_pool
    return out


def _one_offer(teams, team: str, player: dict) -> Offer:
    name = str(team)
    row = teams[teams.team == name].iloc[0]
    return Offer(team=name, manufacturer=str(row['manufacturer']),
                 team_status=str(row['team_status']),
                 power=round(float(row['power']), 1),
                 bike=bike_for(teams, name),
                 current=name == player['team'],
                 objectives={L: objective_for(teams, name, rating(player), L)
                             for L in CONTRACT_TERMS})


def _player_market(teams, player, position, year):
    """Which teams want the career rider, and did their current one keep them.

    Unlike an AI rider the player is judged on the objective written into their
    contract rather than on a renewal roll: they agreed to a position, so they
    are held to it and nothing else. Missing it in the deal's final year costs
    the seat. Missing it earlier does not — the contract is still running, and
    that protection is the whole reason a longer term is worth considering.

    They are never forced out of the championship, though. A satellite seat beats
    ending a career against the player's will, so the one-way flow rule that
    applies to the AI is deliberately not applied here.

    Offers are not limited to teams with a seat going. A team that rates the
    player will drop the weaker of its two riders to sign them (drop_for_player);
    what it will not do is take them at any price, which is what hire_bar is for.
    """
    verdict = contract_verdict(player, position.get(player['name']), year)

    # Still under contract: the seat is theirs, and nobody else can talk to them.
    # This is what the player actually buys with a two-year deal, and the cost of
    # it — a better bike coming free this winter is simply not on the table.
    if not verdict['final_year']:
        return [_one_offer(teams, player['team'], player)], False, verdict

    p_eff = efficiency(teams, player, position.get(player['name']))
    dropped = not verdict['met']

    offers = []
    for _, t in teams.iterrows():
        name = str(t['team'])
        is_current = name == player['team']
        if is_current and dropped:
            continue                       # they just let the player go
        if not is_current and p_eff < hire_bar(teams, name):
            continue                       # not good enough for this team
        offers.append(_one_offer(teams, name, player))
    # Nobody wants them. Rather than ending the career — the game has no flow
    # for that, and one bad season shouldn't be terminal — the bottom team is
    # always willing. Landing on the worst bike on the grid is punishment
    # enough, and it leaves the player somewhere to climb back from.
    if not offers:
        offers.append(_one_offer(teams, str(teams.iloc[-1]['team']), player))

    offers.sort(key=lambda o: -o.power)
    return offers, dropped, verdict
