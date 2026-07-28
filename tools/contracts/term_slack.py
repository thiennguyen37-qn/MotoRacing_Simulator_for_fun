"""Re-tune OBJECTIVE_SLACK now that the player only ever signs 1 or 2 years.

With three terms the ladder was 97% / 89% / 69% and the three-year deal carried
the risk. Drop it and the remaining two sit at 97% and 89% — close enough that
taking the longer deal is free, which is not a decision. This measures what the
two-term ladder looks like at each candidate slack, using the engine's own
baseline table so the tool cannot drift from the game.
"""
import random
import statistics
import sys

import numpy as np

sys.path.insert(0, '.')
from src.engine import circuit_weights, perf_score_race
from src.loader import load_circuits, load_riders
from src.transfers import (GRID_SIZE, RIDER_STATS, baseline_finish, team_table)

RAW = 'data/raw'
FORM_STD = 0.05
SEASONS = 600
RATINGS = [62, 67, 73, 78, 82, 84.5, 86.5, 88, 89.5, 91, 93, 95]


def target(teams, team, rating, slack):
    t = round(baseline_finish(teams, team, rating) + slack)
    return None if t >= GRID_SIZE else int(t)


def main():
    circuits = load_circuits(RAW)
    weights = tuple(np.array([circuit_weights(c) for _, c in circuits.iterrows()]).mean(axis=0))
    teams = team_table(RAW)
    grid = [{k: (v.item() if hasattr(v, 'item') else v) for k, v in r.items()}
            for r in load_riders(RAW).to_dict('records')]
    rng = random.Random(5)

    dist = {}
    for R in RATINGS:
        for _, t in teams.iterrows():
            team = str(t['team'])
            field = [r for r in grid if str(r['team']) != team]
            mates = [r for r in grid if str(r['team']) == team]
            field.append(max(mates, key=lambda r: sum(float(r[s]) for s in RIDER_STATS)))
            p = {s: R for s in RIDER_STATS}
            p.update({'top_speed': int(t['top_speed']), 'acceleration': int(t['acceleration']),
                      'bike_braking': int(t['braking']), 'bike_cornering': int(t['cornering']),
                      'stability': int(t['stability'])})
            base = [perf_score_race(r, *weights) for r in field]
            pb = perf_score_race(p, *weights)
            dist[(R, team)] = [
                1 + sum(1 for s in base
                        if s + rng.gauss(0, FORM_STD) > pb + rng.gauss(0, FORM_STD))
                for _ in range(SEASONS)]

    def rate(slack, ratings=RATINGS):
        ok = tot = 0
        for R in ratings:
            for _, t in teams.iterrows():
                pos = dist[(R, str(t['team']))]
                tgt = target(teams, str(t['team']), R, slack)
                ok += len(pos) if tgt is None else sum(1 for p in pos if p <= tgt)
                tot += len(pos)
        return 100.0 * ok / tot

    print('pass rate by slack (engine baseline table, all ratings x teams):')
    for s in (-1, 0, 1, 2, 3):
        print(f'  {s:>+3}  {rate(s):>5.0f}%')

    print('\ncandidate two-term ladders:')
    for one, two in ((2, 0), (2, 1), (3, 1), (3, 0)):
        print(f'  1yr {one:+d} / 2yr {two:+d}  ->  {rate(one):.0f}% / {rate(two):.0f}%'
              f'   spread {rate(one) - rate(two):.0f} points')

    print('\nchosen 1yr +2 / 2yr 0 — by career stage:')
    print(f'{"rating":>7} {"1yr":>7} {"2yr":>7}')
    for R in RATINGS:
        print(f'{R:>7} {rate(2, [R]):>6.0f}% {rate(0, [R]):>6.0f}%')

    print('\nmiss both seasons of a 2-year deal (the early-termination valve):')
    p = 0.0
    n = 0
    for R in RATINGS:
        for _, t in teams.iterrows():
            pos = dist[(R, str(t['team']))]
            tgt = target(teams, str(t['team']), R, 0)
            miss = 0.0 if tgt is None else sum(1 for x in pos if x > tgt) / len(pos)
            p += miss ** 2
            n += 1
    print(f'  {100.0 * p / n:.1f}% of two-year deals')

    print('\ntargets shown at rating 84.5:')
    print(f'{"team":<24} {"par":>4} {"1yr":>8} {"2yr":>8}')
    for _, t in teams.iterrows():
        nm = str(t['team'])
        f = lambda s: (lambda v: 'finish' if v is None else f'P{v}')(target(teams, nm, 84.5, s))
        print(f'{nm:<24} {baseline_finish(teams, nm, 84.5):>4.0f} {f(2):>8} {f(0):>8}')


if __name__ == '__main__':
    main()
