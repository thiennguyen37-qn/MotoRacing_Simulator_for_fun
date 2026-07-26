"""
Simulation engine — shared across the Practice, Qualifying, and Race sessions.
"""

import numpy as np

MAX_DELTA = 3.0

# ── Race tuning ────────────────────────────────────────────────────────────────
FORM_STD        = 0.060   # per-race form swing (score units), before consistency scaling
TRAFFIC_K       = 0.10    # seconds lost per grid slot behind, on the opening lap
TRAFFIC_LAPS    = 5       # laps over which the grid/traffic penalty fades to zero
# Race pace vs tyre wear. These two are balanced against each other: the first
# is the spread the whole combined rider+bike score is worth, the second is what
# the single tyre_management rating is worth. At 1.0/0.8 tyre wear was 80% of
# the entire skill spread and — being absent from qualifying, which uses the
# much wider MAX_DELTA — a pole-sitter with weak tyre_management fell ~3 places
# every race and never reached the podium, while a slow-qualifying tyre
# specialist gained ~4. Widening the pace spread and halving the wear keeps the
# archetypes (they still lose/gain ~1.5-3 places) without deciding the race on
# one stat.
RACE_TIME_PEN_MAX = 1.3   # seconds/lap penalty for worst-vs-best score (race only; Practice/Quali keep MAX_DELTA)
TYRE_DEG_MAX    = 0.5     # seconds lost per lap to tyre wear, worst tyre_management at full distance (dry only; wet tyre wear isn't modelled)
WET_PEN_BASE    = 1.0     # flat seconds/lap penalty applied to everyone when it's wet, so a wet lap always runs slower than the dry base lap
WET_PEN_SKILL_MAX = 1.0   # extra seconds/lap penalty for worst-vs-best wet_performance, on top of the flat penalty
CRASH_PROB_BASE = 0.0055  # per-lap DNF chance floor (calmest/steadiest riders)
CRASH_PROB_K    = 0.004   # extra per-lap DNF chance scaling with aggression x (1 - consistency)
CRASH_PROB_WET_MULT = 2.3 # multiplier applied to crash_prob when the race is wet


# ── Shared utilities ──────────────────────────────────────────────────────────

def norm(v):
    """Normalize a rating [70, 99] → [0, 1]."""
    return (v - 70) / 29


def circuit_weights(c):
    """Derive speed / cornering / braking weights from circuit layout.

    Each circuit is stretched onto a speed<->technical spectrum so power tracks
    and corner tracks reward genuinely different rider/bike archetypes instead
    of a single all-rounder winning everywhere.
    """
    sr = c['straight_length_m'] / (c['lap_length_km'] * 1000)
    cd = c['corners'] / c['lap_length_km']
    s = min(1.0, max(0.0, (sr - 0.15) / 0.09))   # 0 = technical, 1 = power
    k = min(1.0, max(0.0, (cd - 2.5) / 1.5))     # 0 = flowing,   1 = corner-heavy
    w_spd = 0.10 + 0.78 * s
    w_cor = 0.10 + 0.78 * k
    w_brk = 0.16 + 0.22 * k                       # more corners => more braking zones
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
    rw_cor = w_cor + w_spd * 0.25
    rw_brk = w_brk + w_spd * 0.25
    rw_agg = w_spd * 0.6
    rw_tot = rw_cor + rw_brk + rw_agg
    rider = (
        (rw_cor / rw_tot) * norm(row['rider_cornering'])
        + (rw_brk / rw_tot) * norm(row['rider_braking'])
        + (rw_agg / rw_tot) * norm(row['aggression'])
    )
    return 0.55 * bike + 0.45 * rider


def simulate_lap(row, base_time, lap_num, score, is_wet=False):
    """Return a single practice lap time in seconds."""
    time_penalty = (1 - score) * MAX_DELTA
    warmup       = max(0.0, (5 - lap_num) / 5.0) * 1.5  # fades after lap 5
    variance     = 0.8 * (1 - norm(row['consistency'])) * (1 - norm(row['stability']))
    noise        = np.random.uniform(-variance, variance)
    # Same flat + wet-skill penalty the race uses, so a wet practice runs
    # slower for everyone and rewards a strong wet_performance rating.
    wet_pen      = (WET_PEN_BASE + WET_PEN_SKILL_MAX * (1 - norm(row['wet_performance']))) if is_wet else 0.0
    return max(base_time + time_penalty + warmup + noise + wet_pen, base_time * 0.98)


# ── Qualifying ────────────────────────────────────────────────────────────────

def perf_score_quali(row, w_spd, w_cor, w_brk):
    """Performance score for qualifying — aggression weighted higher."""
    bike = (
        w_spd * (norm(row['top_speed']) * 0.6 + norm(row['acceleration']) * 0.4)
        + w_cor * norm(row['bike_cornering'])
        + w_brk * norm(row['bike_braking'])
    )
    rw_cor = w_cor + w_spd * 0.25
    rw_brk = w_brk + w_spd * 0.25
    rw_agg = w_spd * 0.9
    rw_tot = rw_cor + rw_brk + rw_agg
    rider = (
        (rw_cor / rw_tot) * norm(row['rider_cornering'])
        + (rw_brk / rw_tot) * norm(row['rider_braking'])
        + (rw_agg / rw_tot) * norm(row['aggression'])
    )
    return 0.55 * bike + 0.45 * rider


def simulate_quali_lap(row, base_time, lap_num, score, is_push, is_wet=False):
    """Return a qualifying lap time; returns None on crash."""
    if is_push:
        crash_prob = 0.05 + 0.06 * norm(row['aggression']) * (1 - norm(row['consistency']))
        if is_wet:
            crash_prob *= CRASH_PROB_WET_MULT   # a wet push lap is far riskier
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
    # Flat + wet-skill penalty, same as practice/race — every quali lap is
    # slower in the wet and separates riders by their wet_performance.
    wet_pen = (WET_PEN_BASE + WET_PEN_SKILL_MAX * (1 - norm(row['wet_performance']))) if is_wet else 0.0
    return max(base_time + time_pen + warmup + noise + wet_pen, base_time * 0.97)


# ── Race ──────────────────────────────────────────────────────────────────────

def perf_score_race(row, w_spd, w_cor, w_brk):
    """Performance score for race — aggression rewarded on speed-biased tracks."""
    bike = (
        w_spd * (norm(row['top_speed']) * 0.6 + norm(row['acceleration']) * 0.4)
        + w_cor * norm(row['bike_cornering'])
        + w_brk * norm(row['bike_braking'])
    )
    rw_cor = w_cor + w_spd * 0.25
    rw_brk = w_brk + w_spd * 0.25
    rw_agg = w_spd * 0.7
    rw_tot = rw_cor + rw_brk + rw_agg
    rider = (
        (rw_cor / rw_tot) * norm(row['rider_cornering'])
        + (rw_brk / rw_tot) * norm(row['rider_braking'])
        + (rw_agg / rw_tot) * norm(row['aggression'])
    )
    return 0.55 * bike + 0.45 * rider


def simulate_race_lap(row, lap_num, total_laps, score, is_wet, base_time, grid_pos=1):
    """Return a race lap time in seconds; returns None on crash (DNF)."""
    if lap_num > 1:
        crash_prob = CRASH_PROB_BASE + CRASH_PROB_K * norm(row['aggression']) * (1 - norm(row['consistency']))
        if is_wet:
            crash_prob *= CRASH_PROB_WET_MULT
        if np.random.random() < crash_prob:
            return None
    time_pen  = (1 - score) * RACE_TIME_PEN_MAX
    # Tyre wear isn't modelled in the wet (rain tyres, not the dry-tyre degradation curve).
    tyre_deg  = 0.0 if is_wet else TYRE_DEG_MAX * (1 - norm(row['tyre_management'])) * (lap_num / total_laps) ** 1.5
    fuel_gain = 0.4 * (lap_num - 1) / max(total_laps - 1, 1)
    start_pen = {1: 4.0, 2: 1.5}.get(lap_num, 0.0)
    # Track position: starting further back means fighting through traffic for
    # the opening laps; the cost fades linearly to zero over TRAFFIC_LAPS.
    traffic   = max(0.0, (TRAFFIC_LAPS - (lap_num - 1)) / TRAFFIC_LAPS) * TRAFFIC_K * (grid_pos - 1)
    wet_pen   = (WET_PEN_BASE + WET_PEN_SKILL_MAX * (1 - norm(row['wet_performance']))) if is_wet else 0.0
    var_mult  = 2.0 if lap_num <= 2 else 1.0
    variance  = var_mult * 0.5 * (1 - norm(row['consistency'])) * (1 - norm(row['stability']))
    noise     = np.random.uniform(-variance, variance)
    lap_sec   = base_time + time_pen + tyre_deg - fuel_gain + start_pen + traffic + wet_pen + noise
    return max(lap_sec, base_time * 0.97)
