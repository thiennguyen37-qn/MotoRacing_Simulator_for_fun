"""
High-level session runners used by the desktop app.
"""

import math
import numpy as np
import pandas as pd

from src.engine import (
    circuit_weights, fmt_lap, fmt_gap, norm, FORM_STD,
    perf_score, simulate_lap,
    perf_score_quali, simulate_quali_lap,
    perf_score_race, simulate_race_lap,
)

POINTS = {1: 25, 2: 20, 3: 16, 4: 13, 5: 11, 6: 10,
          7: 9, 8: 8, 9: 7, 10: 6, 11: 5, 12: 4, 13: 3, 14: 2, 15: 1}


def run_practice(df, circuit, laps=15):
    """Returns DataFrame sorted by best lap. Index is 1-based position."""
    w = circuit_weights(circuit)
    bt = float(circuit['base_lap_time'])
    rows = []
    for _, r in df.sort_values('bike_number').iterrows():
        s = perf_score(r, *w)
        ts = [simulate_lap(r, bt, i + 1, s) for i in range(laps)]
        rows.append({'bike_number': int(r['bike_number']), 'name': r['name'],
                     'team': r['team'], 'manufacturer': r['manufacturer'],
                     'best_lap_sec': min(ts), 'best_lap': fmt_lap(min(ts))})
    res = pd.DataFrame(rows).sort_values('best_lap_sec').reset_index(drop=True)
    res['gap'] = res['best_lap_sec'] - res['best_lap_sec'].iloc[0]
    res['gap_fmt'] = res['gap'].apply(fmt_gap)
    res.index += 1
    return res


def _quali_session(circuit, riders, push_laps=3):
    w = circuit_weights(circuit)
    bt = float(circuit['base_lap_time'])
    total = int(900 // circuit['base_lap_time']) - 1
    push_from = total - push_laps + 1
    rows = []
    for _, r in riders.iterrows():
        s = perf_score_quali(r, *w)
        ts = []
        for lap in range(1, total + 1):
            t = simulate_quali_lap(r, bt, lap, s, lap >= push_from)
            if t is not None:
                ts.append(t)
        if ts:
            rows.append({'bike_number': int(r['bike_number']), 'name': r['name'],
                         'team': r['team'], 'manufacturer': r['manufacturer'],
                         'best_lap_sec': min(ts), 'best_lap': fmt_lap(min(ts))})
    res = pd.DataFrame(rows).sort_values('best_lap_sec').reset_index(drop=True)
    if not res.empty:
        res['gap'] = res['best_lap_sec'] - res['best_lap_sec'].iloc[0]
        res['gap_fmt'] = res['gap'].apply(fmt_gap)
        res.index += 1
    return res


def run_qualifying(df, circuit, practice_results, push_laps=3):
    """
    Returns (q1_class, q2_class, q2_advance_names, q1_nq, grid_all_df).
    grid_all_df has [grid_pos, name, bike_number, team, manufacturer, ...].
    """
    top10_names = set(practice_results.iloc[:10]['name'])

    q1_riders = df[~df['name'].isin(top10_names)].copy()
    q1_class = _quali_session(circuit, q1_riders, push_laps)

    q2_advance_names = set(q1_class.head(2)['name'])
    q2_riders = pd.concat([
        df[df['name'].isin(top10_names)],
        df[df['name'].isin(q2_advance_names)],
    ], ignore_index=True)
    q2_class = _quali_session(circuit, q2_riders, push_laps)

    q1_nq = q1_class[~q1_class['name'].isin(q2_advance_names)].reset_index(drop=True)
    q1_nq.index = range(13, 13 + len(q1_nq))
    if not q1_nq.empty:
        q1_nq = q1_nq.copy()
        q1_nq['gap'] = q1_nq['best_lap_sec'] - q1_nq['best_lap_sec'].iloc[0]
        q1_nq['gap_fmt'] = q1_nq['gap'].apply(fmt_gap)

    grid_all = pd.concat([q2_class, q1_nq]).reset_index(drop=True)
    grid_all['grid_pos'] = range(1, len(grid_all) + 1)

    return q1_class, q2_class, q2_advance_names, q1_nq, grid_all


def run_race(df, circuit, grid_all_df):
    """
    Returns (race_result_df, rider_pts_df, meta_dict).
    grid_all_df: from run_qualifying — must have name, bike_number, grid_pos, team, manufacturer.
    """
    # Merge stat columns not already in grid_all_df
    skip = set(grid_all_df.columns) - {'name', 'bike_number'}
    merge_cols = [c for c in df.columns if c not in skip]
    grid_df = grid_all_df.merge(df[merge_cols], on=['name', 'bike_number'], how='left')

    w = circuit_weights(circuit)
    bt = float(circuit['base_lap_time'])
    total_laps = math.ceil(100 / circuit['lap_length_km'])
    scores = {r['name']: perf_score_race(r, *w) for _, r in grid_df.iterrows()}

    # Per-race form: each rider gets one random "good/bad day" offset, drawn once
    # for the whole race. Steadier riders (high consistency) swing less.
    scores = {
        r['name']: min(1.0, max(0.0,
            scores[r['name']] + np.random.normal(0, FORM_STD * (1 - 0.4 * norm(r['consistency'])))))
        for _, r in grid_df.iterrows()
    }

    is_wet = np.random.uniform(0, 100) <= np.random.uniform(0, 5)

    state = {}
    for _, r in grid_df.iterrows():
        state[r['name']] = {
            'bike_number': int(r['bike_number']),
            'team': r['team'], 'manufacturer': r['manufacturer'],
            'cumul_time': 0.0, 'grid_pos': int(r['grid_pos']),
            'position': int(r['grid_pos']),
            'dnf': False, 'dnf_lap': None,
        }
    dnf_log = []
    fl = {'time': float('inf'), 'name': None, 'lap': None}

    for lap in range(1, total_laps + 1):
        for name, s in state.items():
            if s['dnf']:
                continue
            row = grid_df[grid_df['name'] == name].iloc[0]
            t = simulate_race_lap(row, lap, total_laps, scores[name], is_wet, bt, s['grid_pos'])
            if t is None:
                s['dnf'] = True
                s['dnf_lap'] = lap
                dnf_log.append({**s, 'name': name, 'lap': lap})
            else:
                s['cumul_time'] += t
                if t < fl['time']:
                    fl = {'time': t, 'name': name, 'lap': lap}
        active = sorted([(n, s) for n, s in state.items() if not s['dnf']],
                        key=lambda x: x[1]['cumul_time'])
        for pos, (name, s) in enumerate(active, 1):
            s['position'] = pos

    finishers = sorted([(n, s) for n, s in state.items() if not s['dnf']],
                       key=lambda x: x[1]['position'])
    dnf_sorted = sorted(dnf_log, key=lambda x: -x['lap'])
    leader_t = finishers[0][1]['cumul_time'] if finishers else 0

    result_rows, pts_rows = [], []
    for pos, (name, s) in enumerate(finishers, 1):
        gap = s['cumul_time'] - leader_t
        result_rows.append({'pos_label': f'P{pos}', 'pos': pos,
                            'bike_number': s['bike_number'], 'name': name,
                            'team': s['team'], 'manufacturer': s['manufacturer'],
                            'time_fmt': fmt_lap(s['cumul_time']), 'gap_fmt': fmt_gap(gap),
                            'grid_pos': s['grid_pos'],
                            'fastest_lap': name == fl['name'], 'dnf': False})
        pts_rows.append({'name': name, 'bike_number': s['bike_number'],
                         'team': s['team'], 'manufacturer': s['manufacturer'],
                         'points': POINTS.get(pos, 0)})
    for d in dnf_sorted:
        result_rows.append({'pos_label': 'DNF', 'pos': 999,
                            'bike_number': d['bike_number'], 'name': d['name'],
                            'team': d['team'], 'manufacturer': d['manufacturer'],
                            'time_fmt': '—', 'gap_fmt': f"Lap {d['lap']}",
                            'grid_pos': d['grid_pos'],
                            'fastest_lap': False, 'dnf': True})
        pts_rows.append({'name': d['name'], 'bike_number': d['bike_number'],
                         'team': d['team'], 'manufacturer': d['manufacturer'],
                         'points': 0})

    meta = {'is_wet': is_wet, 'fl_name': fl['name'],
            'fl_time': fl['time'], 'fl_lap': fl['lap'], 'total_laps': total_laps}
    return pd.DataFrame(result_rows), pd.DataFrame(pts_rows), meta
