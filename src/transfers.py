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
* **Flow is one-way, satellite → factory.** A factory rider who loses their
  seat leaves the championship rather than dropping down.

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
DROP_EFFICIENCY  = -3.0   # at or below this (AND beaten by teammate) → seat lost
PROMOTE_MARGIN   = 3.0    # satellite rider must beat the factory baseline by this

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

# Rookie call-up: each team aims at a target drawn from a normal distribution
# whose mean shifts with the bike, then takes the nearest available rookie.
# SHIFT 1.5 / SIGMA 3.0 gives a bike↔rider correlation of 0.43 — a real tendency
# without the championship being decided in the off-season (see the calibration
# table in transfer_market.md).
ROOKIE_SHIFT     = 1.5
ROOKIE_SIGMA     = 3.0

# Contracts run 1-2 seasons. `contract_until` is the last season covered, so a
# rider is out of contract in the Y → Y+1 off-season once contract_until <= Y.
# This is the brake on churn: only out-of-contract riders can be dropped or
# poached, which keeps replacements at ~2.4 a season and the 100-strong pool
# alive for ~40 seasons.
CONTRACT_LENGTHS = (1, 2)

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
    """A seat the player could take next season, with the bike that comes with it."""
    team: str
    manufacturer: str
    team_status: str
    power: float
    bike: dict                  # the five BIKE_STATS
    current: bool = False       # True for the player's existing team, if it wants them


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


def salvage_appeal(rider: dict) -> float:
    """How a rider who just lost their seat looks to a team further down.

    Their rating, docked for every year past the late twenties. It is the
    combination that decides them: quick and young is an easy yes, slow and old
    an easy no, and the interesting cases are the ones in between — a fading
    veteran who is still fast enough, or a modest rider young enough to be worth
    the wait. Compare against SALVAGE_BAR.
    """
    return rating(rider) - SALVAGE_AGE_K * max(0, int(rider['age']) - SALVAGE_PEAK_AGE)


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
    sign(displaced, teams[teams.team == str(old_team)].iloc[0], year, rng)
    riders.append(displaced)
    return displaced, str(old_team)


def out_of_contract(rider: dict, year: int) -> bool:
    """True once the deal has run out. `year` is the season just finished."""
    return int(rider.get('contract_until', year)) <= int(year)


def sign(rider: dict, team_row, year: int, rng: random.Random) -> None:
    """Put a rider on a team's books for next season: new colours, new bike, new
    contract. Mutates in place — callers already hold the dict."""
    rider['team'] = str(team_row['team'])
    rider['manufacturer'] = str(team_row['manufacturer'])
    rider['team_status'] = str(team_row['team_status'])
    rider.update({'top_speed': int(team_row['top_speed']),
                  'acceleration': int(team_row['acceleration']),
                  'bike_braking': int(team_row['braking']),
                  'bike_cornering': int(team_row['cornering']),
                  'stability': int(team_row['stability'])})
    rider['contract_until'] = int(year) + rng.choice(CONTRACT_LENGTHS)


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
    sign(rider, team_row, year, rng)
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
    # Who the player raced alongside LAST season — captured before the market
    # reshuffles everyone, since that is the comparison their team judges them
    # on. Reading it afterwards would compare them against next year's lineup.
    player_mates = ([r['name'] for r in riders
                     if player and r['team'] == player['team']] if player else [])

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

    # 3 ── factory seats lost to underperformance. Three conditions, all needed:
    #
    #   * out of contract — the brake on churn, without which a seventh of the
    #     grid would turn over every single season and the pool would run dry
    #     decades early;
    #   * efficiency at or below the bar — they are not repaying the machinery;
    #   * beaten by their teammate — the only exactly fair comparison there is,
    #     same bike, same season. On its own it would force every team to sack
    #     somebody every year, since one of any two riders always finishes
    #     behind the other.
    #
    # Satellite seats are exempt: they already turn over plenty through
    # promotions and retirements, and adding a second source doubled the
    # replacement rate to 3.0 a season — enough to exhaust the 100-rider pool
    # in 34 seasons.
    squads = {}
    for r in riders:
        squads.setdefault(r['team'], []).append(r)
    dropped_eff = {}
    keeping = []
    free_agents = []           # lost their seat, still looking for another
    lost_from = {}             # name -> the team that let them go
    lost_age = {}              # name -> age, kept for the departures read-out
    for r in riders:
        mates = [m for m in squads[r['team']] if m is not r]
        beaten = any(position.get(m['name'], 99) < position.get(r['name'], 99) for m in mates)
        if (r['team_status'] == 'factory' and out_of_contract(r, year)
                and eff[r['name']] <= DROP_EFFICIENCY and beaten):
            dropped_eff[r['team']] = eff[r['name']]
            lost_from[r['name']] = r['team']
            lost_age[r['name']] = r['age']
            free_agents.append(r)
        else:
            keeping.append(r)
    riders = keeping

    # 3b ── the player's own market, settled before any seat is filled: whether
    # their team is keeping them decides whether that team has one seat to fill
    # or two. It reads nothing the steps below produce — only where everyone
    # finished and who the player's team-mates were — so running it here rather
    # than at the end changes no outcome.
    if player:
        out.player_offers, out.player_dropped = _player_market(
            teams, player_mates, player, position, year)

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
            sign(hire, row, year, rng)
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
                hire = max(cands, key=lambda r: eff[r['name']])
                free_agents.remove(hire)
                sign(hire, row, year, rng)
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

    # 7 ── renew whoever is left, so nobody carries a lapsed contract into the
    # new season and becomes droppable again immediately.
    riders = [r for squad in squads.values() for r in squad]
    for r in riders:
        if out_of_contract(r, year):
            r['contract_until'] = year + rng.choice(CONTRACT_LENGTHS)

    out.riders = riders
    out.pool_used = sorted(used)
    out.extra_pool = extra_pool
    return out


def _player_market(teams, mates, player, position, year):
    """Which teams want the career rider, and did their current one keep them.

    Being dropped uses the same test as the AI (out of contract, efficiency at
    or below the bar, beaten by a teammate) — but unlike an AI factory rider,
    the player is never forced out of the championship: a satellite seat is
    always preferable to ending the career against their will, so the one-way
    flow rule is deliberately not applied to them.

    Offers are not limited to teams with a seat going. A team that rates the
    player will drop the weaker of its two riders to sign them (drop_for_player);
    what it will not do is take them at any price, which is what hire_bar is for.
    """
    p_eff = efficiency(teams, player, position.get(player['name']))
    mine = position.get(player['name'], 99)
    beaten = any(position.get(m, 99) < mine for m in mates if m != player['name'])
    dropped = (out_of_contract(player, year) and p_eff <= DROP_EFFICIENCY and beaten)

    offers = []
    for _, t in teams.iterrows():
        name = str(t['team'])
        is_current = name == player['team']
        if is_current and dropped:
            continue                       # they just let the player go
        if not is_current and p_eff < hire_bar(teams, name):
            continue                       # not good enough for this team
        offers.append(Offer(team=name, manufacturer=str(t['manufacturer']),
                            team_status=str(t['team_status']),
                            power=round(float(t['power']), 1),
                            bike=bike_for(teams, name), current=is_current))
    # Nobody wants them. Rather than ending the career — the game has no flow
    # for that, and one bad season shouldn't be terminal — the bottom team is
    # always willing. Landing on the worst bike on the grid is punishment
    # enough, and it leaves the player somewhere to climb back from.
    if not offers:
        t = teams.iloc[-1]
        offers.append(Offer(team=str(t['team']), manufacturer=str(t['manufacturer']),
                            team_status=str(t['team_status']),
                            power=round(float(t['power']), 1),
                            bike=bike_for(teams, str(t['team'])),
                            current=str(t['team']) == player['team']))

    offers.sort(key=lambda o: -o.power)
    return offers, dropped
