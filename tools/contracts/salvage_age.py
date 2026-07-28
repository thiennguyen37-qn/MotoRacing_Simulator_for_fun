"""How far down the grid does a rider drop, and does age decide it?

Step 5c currently ranks salvage candidates by last season's efficiency, so which
team picks a rider up has nothing to do with their age. The queue of vacant seats
runs strongest bike first, so whoever ranks highest lands the best seat going.

Swap that key for salvage_appeal — rating minus 1.8 per year past 28, the number
that already decides whether they are signable at all — and the strong teams take
the young ones while the veterans fall to the bottom of the grid. This measures
both versions on the same seeds.

    python diag_salvage.py            # current: rank by efficiency
    python diag_salvage.py --appeal   # proposed: rank by salvage_appeal
"""
import random
import statistics
import sys

import numpy as np

sys.path.insert(0, '.')
import src.transfers as T
from src.engine import circuit_weights, perf_score_race
from src.loader import load_circuits, load_riders

RAW = 'data/raw'
SEEDS, SEASONS = 30, 20


_LAST_EFF = {}


def rank_by_efficiency(rider: dict, drop: float = 0.0) -> float:
    """The old behaviour, for comparison: whoever had the best season goes first,
    regardless of how many years they have left."""
    return _LAST_EFF.get(rider['name'], 0.0)


def main(rank_by_appeal: bool):
    circuits = load_circuits(RAW)
    w = tuple(np.array([circuit_weights(c) for _, c in circuits.iterrows()]).mean(axis=0))
    teams = T.team_table(RAW)
    power = {str(t['team']): float(t['power']) for _, t in teams.iterrows()}

    drops, by_age, stayed, left = [], {}, {}, {}

    for seed in range(SEEDS):
        rng = random.Random(seed)
        riders = [{k: (v.item() if hasattr(v, 'item') else v) for k, v in r.items()}
                  for r in load_riders(RAW).to_dict('records')]
        for r in riders:
            r['contract_until'] = 2026
        roster = {'year': 2026, 'riders': riders, 'retired': [], 'pool_used': []}

        for s in range(SEASONS):
            year = 2026 + s
            scored = sorted(((perf_score_race(r, *w) + rng.gauss(0, 0.05), r)
                             for r in roster['riders']), key=lambda x: -x[0])
            table = [{'name': r['name'], 'team': r['team'], 'points': 0} for _, r in scored]
            ages = {r['name']: int(r['age']) + 1 for r in roster['riders']}
            pos = {e['name']: i + 1 for i, e in enumerate(table)}
            _LAST_EFF.clear()
            _LAST_EFF.update({r['name']: T.efficiency(teams, r, pos.get(r['name']))
                              for r in roster['riders']})
            out = T.run_silly_season(roster, table, None, year, RAW, rng)

            for d in out.dropped:
                age = ages.get(d['name'], 0)
                band = ('<=25' if age <= 25 else '26-28' if age <= 28
                        else '29-31' if age <= 31 else '32+')
                if d.get('landed'):
                    drop = power[d['team']] - power[d['landed']]
                    drops.append((age, drop))
                    by_age.setdefault(band, []).append(drop)
                    stayed[band] = stayed.get(band, 0) + 1
                else:
                    left[band] = left.get(band, 0) + 1

            roster = {'year': out.year, 'riders': out.riders,
                      'retired': roster['retired'] + out.retired,
                      'pool_used': out.pool_used, 'extra_pool': []}

    label = 'salvage_appeal' if rank_by_appeal else 'efficiency'
    print(f'ranked by: {label}\n')
    print(f'{"age band":<10} {"landed":>7} {"left":>6} {"stay%":>7} '
          f'{"mean drop":>10} {"median":>7} {"max":>6}')
    for band in ('<=25', '26-28', '29-31', '32+'):
        got = by_age.get(band, [])
        n_left = left.get(band, 0)
        tot = len(got) + n_left
        if not tot:
            continue
        print(f'{band:<10} {len(got):>7} {n_left:>6} {100.0*len(got)/tot:>6.0f}% '
              f'{(statistics.mean(got) if got else 0):>10.1f} '
              f'{(statistics.median(got) if got else 0):>7.1f} '
              f'{(max(got) if got else 0):>6.1f}')

    if drops:
        xs = np.array([a for a, _ in drops], dtype=float)
        ys = np.array([d for _, d in drops], dtype=float)
        print(f'\ncorrelation age <-> size of the drop: {np.corrcoef(xs, ys)[0,1]:+.3f}')
        print('  (positive = older riders fall further, which is the goal)')


if __name__ == '__main__':
    # Default run measures the OLD rule so the two can be compared; --appeal
    # leaves the module's own salvage_rank in place.
    use_appeal = '--appeal' in sys.argv
    if not use_appeal:
        T.salvage_rank = rank_by_efficiency
    main(use_appeal)
