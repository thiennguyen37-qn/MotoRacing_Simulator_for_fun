"""Full player careers under contract objectives.

Question the design has to answer with numbers, not vibes: if every offer comes
with a target position derived from expected_rank(), does the career still climb,
and how often does the player actually miss?

The player's growth is the real XP formula (src/progression), the field is the
real transfer market (src/transfers), and standings use the Race session's own
scoring plus a form wobble — the same shortcut test_transfers.py takes.

Policy modelled for the player: always take the strongest bike offered, on the
longest term available. That is the greedy player, i.e. the one most likely to
sign for a seat they cannot hold — exactly the case the objective must punish
without ending the career.
"""
import random
import statistics
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, '.')
from src.engine import circuit_weights, perf_score_race
from src.loader import load_circuits, load_riders
from src.progression import GROWTH_STATS, apply_growth, xp_for_race
from src.transfers import (RIDER_STATS, bike_for, expected_rank, hire_bar,
                           pool_entry, run_silly_season, seat_player, team_table)

RAW = 'data/raw'
FORM_STD = 0.05
SEASONS = 25
SEEDS = 60
ROUNDS, RACES = 13, 2

CUSTOM_START = {'rider_braking': 65.0, 'rider_cornering': 65.0, 'aggression': 65.0,
                'tyre_management': 65.0, 'consistency': 65.0, 'wet_performance': 80.0}

# Slack over expected_rank by contract length: a longer deal buys security, so
# the team asks for more in return. 1 year is the lenient, exposed option.
SLACK = {1: 4.0, 2: 3.0, 3: 2.0}


def target_for(teams, team, length):
    """The position the contract demands, or None when the bike is so bad that
    'beat the bike by a bit' lands past the back of a 24-rider grid."""
    t = expected_rank(teams, team) + SLACK[length]
    return None if t >= 24.5 else int(round(t))


def mean_weights():
    circuits = load_circuits(RAW)
    w = np.array([circuit_weights(c) for _, c in circuits.iterrows()])
    return tuple(w.mean(axis=0))


def rating(r):
    return sum(float(r[s]) for s in RIDER_STATS) / len(RIDER_STATS)


def standings_for(riders, player, weights, rng):
    scored = [(perf_score_race(r, *weights) + rng.gauss(0, FORM_STD), r['name'])
              for r in riders]
    scored.append((perf_score_race(player, *weights) + rng.gauss(0, FORM_STD),
                   player['name']))
    scored.sort(key=lambda x: -x[0])
    by_name = {r['name']: r for r in riders}
    by_name[player['name']] = player
    return [{'name': n, 'team': by_name[n]['team'], 'points': 0} for _, n in scored]


def run_one(seed, weights, teams):
    rng = random.Random(seed)
    base = load_riders(RAW).to_dict('records')
    riders = [{k: (v.item() if hasattr(v, 'item') else v) for k, v in r.items()}
              for r in base]
    for r in riders:
        r['contract_until'] = 2026 + rng.choice((0, 1))

    # The player starts at a satellite team, as p_career forces.
    sats = [str(t['team']) for _, t in teams.iterrows() if t['team_status'] == 'satellite']
    start = rng.choice(sats)
    row = teams[teams.team == start].iloc[0]
    player = dict(CUSTOM_START)
    player.update({'name': 'PLAYER', 'age': 25, 'team': start,
                   'manufacturer': str(row['manufacturer']),
                   'team_status': 'satellite', 'bike_number': 77,
                   **bike_for(teams, start)})
    length = 2
    player['contract_until'] = 2026 + length - 1
    signed_year = 2026

    # The player takes a seat, so the AI grid runs one short.
    mates = [r for r in riders if str(r['team']) == start]
    riders.remove(min(mates, key=rating))
    roster = {'year': 2026, 'riders': riders, 'retired': [], 'pool_used': [],
              'extra_pool': []}

    log = []
    for s in range(SEASONS):
        year = 2026 + s
        table = standings_for(roster['riders'], player, weights, rng)
        order = [e['name'] for e in table]
        pos = 1 + order.index('PLAYER')

        # Contract verdict, evaluated on the season that just finished.
        tgt = target_for(teams, player['team'], length)
        met = tgt is None or pos <= tgt
        final_year = int(player['contract_until']) <= year
        log.append({'year': year, 'career': s + 1, 'rating': rating(player),
                    'team': player['team'], 'pos': pos, 'target': tgt,
                    'met': met, 'final': final_year, 'length': length,
                    'power': float(teams[teams.team == player['team']].iloc[0]['power'])})

        # Growth: the real XP curve, using the season position for every race.
        for _ in range(ROUNDS * RACES):
            apply_growth(player, xp_for_race(pos, s + 1))

        # A missed target in the contract's final year means the team does not
        # keep them — modelled by letting the contract lapse, which is what the
        # market already treats as droppable.
        if final_year and not met:
            player['contract_until'] = year          # lapsed -> exposed
        elif final_year:
            player['contract_until'] = year          # up for renewal either way

        out = run_silly_season(roster, table, player, year, RAW, rng)
        offers = out.player_offers
        # Greedy: strongest bike on offer.
        pick = max(offers, key=lambda o: o.power)
        old_team = player['team']
        player.update({'team': pick.team, 'manufacturer': pick.manufacturer,
                       'team_status': pick.team_status, **pick.bike})
        new_riders = out.riders
        displaced, to = seat_player(new_riders, teams, old_team, pick.team, year, rng)
        extra = list(out.extra_pool)
        if displaced is not None and to is None:
            extra.append(pool_entry(displaced))
        length = 3 if pick.power >= 80 else 2      # greedy: longest on offer
        player['contract_until'] = year + length
        player['age'] += 1
        roster = {'year': out.year, 'riders': new_riders,
                  'retired': roster['retired'] + out.retired,
                  'pool_used': out.pool_used, 'extra_pool': extra}
    return log


def main():
    weights = mean_weights()
    teams = team_table(RAW)

    print('targets by team and contract length (position or better):')
    print(f'{"team":<24} {"exp":>5} {"1yr":>5} {"2yr":>5} {"3yr":>5}')
    for _, t in teams.iterrows():
        nm = str(t['team'])
        f = lambda L: (lambda v: 'finish' if v is None else f'P{v}')(target_for(teams, nm, L))
        print(f'{nm:<24} {expected_rank(teams, nm):>5.1f} {f(1):>5} {f(2):>5} {f(3):>5}')
    print(f'\nhire_bar (efficiency needed for an offer): '
          f'Ducati {hire_bar(teams, "Ducati Factory Racing"):+.1f}  '
          f'Phoenix {hire_bar(teams, "Phoenix Motorsport"):+.1f}')

    logs = [run_one(seed, weights, teams) for seed in range(SEEDS)]

    print('\ncareer trajectory (median across seeds):')
    print(f'{"yr":>3} {"rating":>7} {"pos":>4} {"power":>6} {"met%":>6} {"team (mode)":<24}')
    for i in range(SEASONS):
        rows = [lg[i] for lg in logs]
        met = 100.0 * sum(r['met'] for r in rows) / len(rows)
        team = Counter(r['team'] for r in rows).most_common(1)[0][0]
        print(f'{i+1:>3} {statistics.median(r["rating"] for r in rows):>7.1f} '
              f'{statistics.median(r["pos"] for r in rows):>4.0f} '
              f'{statistics.median(r["power"] for r in rows):>6.1f} '
              f'{met:>6.0f} {team:<24}')

    flat = [r for lg in logs for r in lg]
    misses = [r for r in flat if not r['met']]
    print(f'\noverall target met: {100.0*(len(flat)-len(misses))/len(flat):.0f}%'
          f'   ({len(misses)} misses in {len(flat)} seasons)')
    fatal = [r for r in misses if r['final']]
    print(f'misses in a contract final year (i.e. cost the seat): {len(fatal)}'
          f'  = {len(fatal)/SEEDS:.2f} per career')
    print('\nmisses by team power band:')
    for lo, hi, lbl in [(88, 99, 'top 3 (Duc/Suz/Kaw)'), (83, 88, 'mid factory+Razor'),
                        (0, 83, 'bottom 5')]:
        band = [r for r in flat if lo <= r['power'] < hi]
        if band:
            m = sum(1 for r in band if not r['met'])
            print(f'  {lbl:<22} {len(band):>5} seasons  miss {100.0*m/len(band):>3.0f}%')

    print('\nrating when first holding a top-3 bike:')
    firsts = []
    for lg in logs:
        for r in lg:
            if r['power'] >= 88:
                firsts.append((r['career'], r['rating']))
                break
    if firsts:
        print(f'  career year {statistics.median(c for c, _ in firsts):.0f}, '
              f'rating {statistics.median(x for _, x in firsts):.1f}  '
              f'({len(firsts)}/{SEEDS} careers got there)')


if __name__ == '__main__':
    main()
