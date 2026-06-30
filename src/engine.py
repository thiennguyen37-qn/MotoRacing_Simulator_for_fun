"""
Simulation engine — shared across Practice, Qualifying, and Race notebooks.
"""

import numpy as np

MAX_DELTA = 3.0


# ── Shared utilities ──────────────────────────────────────────────────────────

def norm(v):
    """Normalize a rating [70, 99] → [0, 1]."""
    return (v - 70) / 29


def circuit_weights(c):
    """Derive speed / cornering / braking weights from circuit layout."""
    sr = c['straight_length_m'] / (c['lap_length_km'] * 1000)
    cd = c['corners'] / c['lap_length_km']
    w_spd, w_cor, w_brk = sr * 3, cd / 5, 0.30
    t = w_spd + w_cor + w_brk
    return w_spd / t, w_cor / t, w_brk / t


def fmt_lap(s):
    """Format seconds as MM:SS.mmm."""
    m = int(s // 60)
    return f'{m:02d}:{s % 60:06.3f}'


def fmt_gap(g):
    return '—' if g == 0 else f'+{g:.3f}'


# ── Practice ──────────────────────────────────────────────────────────────────

def perf_score(row, w_spd, w_cor, w_brk):
    """Combined rider + bike performance score ∈ [0, 1] for practice."""
    bike = (
        w_spd * (norm(row['top_speed']) * 0.6 + norm(row['acceleration']) * 0.4)
        + w_cor * norm(row['bike_cornering'])
        + w_brk * norm(row['bike_braking'])
    )
    rw_cor = w_cor + w_spd * 0.3
    rw_brk = w_brk + w_spd * 0.5
    rw_agg = w_spd * 0.2
    rw_tot = rw_cor + rw_brk + rw_agg
    rider = (
        (rw_cor / rw_tot) * norm(row['rider_cornering'])
        + (rw_brk / rw_tot) * norm(row['rider_braking'])
        + (rw_agg / rw_tot) * norm(row['aggression'])
    )
    return 0.55 * bike + 0.45 * rider


def simulate_lap(row, base_time, lap_num, score):
    """Return a single practice lap time in seconds."""
    time_penalty = (1 - score) * MAX_DELTA
    warmup       = max(0.0, (5 - lap_num) / 5.0) * 1.5  # fades after lap 5
    variance     = 0.8 * (1 - norm(row['consistency'])) * (1 - norm(row['stability']))
    noise        = np.random.uniform(-variance, variance)
    return max(base_time + time_penalty + warmup + noise, base_time * 0.98)


# ── Qualifying ────────────────────────────────────────────────────────────────

def perf_score_quali(row, w_spd, w_cor, w_brk):
    """Performance score for qualifying — aggression weighted higher."""
    bike = (
        w_spd * (norm(row['top_speed']) * 0.6 + norm(row['acceleration']) * 0.4)
        + w_cor * norm(row['bike_cornering'])
        + w_brk * norm(row['bike_braking'])
    )
    rw_cor = w_cor + w_spd * 0.2
    rw_brk = w_brk + w_spd * 0.3
    rw_agg = w_spd * 0.5
    rw_tot = rw_cor + rw_brk + rw_agg
    rider = (
        (rw_cor / rw_tot) * norm(row['rider_cornering'])
        + (rw_brk / rw_tot) * norm(row['rider_braking'])
        + (rw_agg / rw_tot) * norm(row['aggression'])
    )
    return 0.55 * bike + 0.45 * rider


def simulate_quali_lap(row, base_time, lap_num, score, is_push):
    """Return a qualifying lap time; returns None on crash."""
    if is_push:
        crash_prob = 0.05 + 0.06 * norm(row['aggression']) * (1 - norm(row['consistency']))
        if np.random.random() < crash_prob:
            return None
        push_gain = 0.3 + 0.2 * norm(row['aggression'])
        time_pen  = max(0.0, (1 - score) * MAX_DELTA - push_gain)
        variance  = 0.8 * (1 - norm(row['consistency']) * 0.5)
    else:
        time_pen = (1 - score) * MAX_DELTA
        variance = 0.5 * (1 - norm(row['consistency'])) * (1 - norm(row['stability']))
    warmup = 0.5 if lap_num == 1 else 0.0
    noise  = np.random.uniform(-variance, variance)
    return max(base_time + time_pen + warmup + noise, base_time * 0.97)


# ── Race ──────────────────────────────────────────────────────────────────────

def perf_score_race(row, w_spd, w_cor, w_brk):
    """Performance score for race — braking weighted higher than practice."""
    bike = (
        w_spd * (norm(row['top_speed']) * 0.6 + norm(row['acceleration']) * 0.4)
        + w_cor * norm(row['bike_cornering'])
        + w_brk * norm(row['bike_braking'])
    )
    rw_cor = w_cor + w_spd * 0.3
    rw_brk = w_brk + w_spd * 0.5
    rw_agg = w_spd * 0.2
    rw_tot = rw_cor + rw_brk + rw_agg
    rider = (
        (rw_cor / rw_tot) * norm(row['rider_cornering'])
        + (rw_brk / rw_tot) * norm(row['rider_braking'])
        + (rw_agg / rw_tot) * norm(row['aggression'])
    )
    return 0.55 * bike + 0.45 * rider


def simulate_race_lap(row, lap_num, total_laps, score, is_wet, base_time):
    """Return a race lap time in seconds; returns None on crash (DNF)."""
    if lap_num > 1:
        crash_prob = 0.003 + 0.004 * norm(row['aggression']) * (1 - norm(row['consistency']))
        if np.random.random() < crash_prob:
            return None
    time_pen  = (1 - score) * MAX_DELTA
    tyre_deg  = 2.0 * (1 - norm(row['tyre_management'])) * (lap_num / total_laps) ** 1.5
    fuel_gain = 0.4 * (lap_num - 1) / max(total_laps - 1, 1)
    start_pen = {1: 4.0, 2: 1.5}.get(lap_num, 0.0)
    wet_pen   = 2.5 * (1 - norm(row['wet_performance'])) if is_wet else 0.0
    var_mult  = 2.0 if lap_num <= 2 else 1.0
    variance  = var_mult * 0.5 * (1 - norm(row['consistency'])) * (1 - norm(row['stability']))
    noise     = np.random.uniform(-variance, variance)
    lap_sec   = base_time + time_pen + tyre_deg - fuel_gain + start_pen + wet_pen + noise
    return max(lap_sec, base_time * 0.97)
