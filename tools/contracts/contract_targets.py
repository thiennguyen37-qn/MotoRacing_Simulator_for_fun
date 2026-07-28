"""What championship position is actually reachable from each seat?

Contract objectives have to be expressed in something the player can read off
the standings ("finish P8 or better"), but they only make sense if the number is
achievable on that bike. This measures it with the same scoring the Race session
uses: put a rider of rating R on team T, run seasons, record where they finish.

Output: a rating x team grid of median finishing positions, plus what slack over
expected_rank() each tier implies.
"""
import random
import statistics
import sys

import numpy as np

sys.path.insert(0, '.')
from src.engine import circuit_weights, perf_score_race
from src.loader import load_circuits, load_riders
from src.transfers import RIDER_STATS, expected_rank, team_table

RAW = 'data/raw'
FORM_STD = 0.05
SEASONS = 400

RATINGS = [67, 73, 78, 82, 84.5, 86.5, 88, 89.5]


def mean_weights():
    circuits = load_circuits(RAW)
    w = np.array([circuit_weights(c) for _, c in circuits.iterrows()])
    return tuple(w.mean(axis=0))


def main():
    weights = mean_weights()
    teams = team_table(RAW)
    grid = load_riders(RAW).to_dict('records')
    grid = [{k: (v.item() if hasattr(v, 'item') else v) for k, v in r.items()}
            for r in grid]

    # The player takes a seat, so one AI rider makes way: drop the weaker rider
    # of the team in question rather than racing 25 bikes.
    rng = random.Random(7)
    print(f'{"rating":>7} | ' + ' | '.join(f'{int(t["rank"])+1:>2}' for _, t in teams.iterrows()))
    print(' ' * 9 + '-' * 12 * 4)

    med = {}
    for R in RATINGS:
        row = []
        for _, t in teams.iterrows():
            team = str(t['team'])
            field = [r for r in grid if str(r['team']) != team]
            mates = [r for r in grid if str(r['team']) == team]
            keep = max(mates, key=lambda r: sum(float(r[s]) for s in RIDER_STATS))
            field.append(keep)

            player = {s: R for s in RIDER_STATS}
            player.update({'name': 'PLAYER', 'team': team,
                           'top_speed': int(t['top_speed']),
                           'acceleration': int(t['acceleration']),
                           'bike_braking': int(t['braking']),
                           'bike_cornering': int(t['cornering']),
                           'stability': int(t['stability'])})

            base = [(perf_score_race(r, *weights), r['name']) for r in field]
            pbase = perf_score_race(player, *weights)
            pos = []
            for _ in range(SEASONS):
                scored = [(s + rng.gauss(0, FORM_STD), n) for s, n in base]
                scored.append((pbase + rng.gauss(0, FORM_STD), 'PLAYER'))
                scored.sort(key=lambda x: -x[0])
                pos.append(1 + [n for _, n in scored].index('PLAYER'))
            med[(R, team)] = pos
            row.append(statistics.median(pos))
        print(f'{R:>7} | ' + ' | '.join(f'{v:>2.0f}' for v in row))

    print('\nexpected_rank per team (bike alone):')
    for _, t in teams.iterrows():
        print(f'  {int(t["rank"])+1:>2}. {str(t["team"]):<24} power {t["power"]:>5.1f}  '
              f'exp P{expected_rank(teams, str(t["team"])):>4.1f}')

    # What slack does a given pass rate need? For each team, at the rating a
    # player realistically has when they get that seat, find the position they
    # beat X% of the time.
    print('\nposition beaten with probability p, for rating 84.5:')
    print(f'{"team":<24} {"exp":>5} {"p90":>4} {"p75":>4} {"p50":>4} {"p25":>4}')
    for _, t in teams.iterrows():
        team = str(t['team'])
        p = sorted(med[(84.5, team)])
        n = len(p)
        q = lambda f: p[min(n - 1, int(f * n))]
        print(f'{team:<24} {expected_rank(teams, team):>5.1f} '
              f'{q(0.90):>4} {q(0.75):>4} {q(0.50):>4} {q(0.25):>4}')


if __name__ == '__main__':
    main()
