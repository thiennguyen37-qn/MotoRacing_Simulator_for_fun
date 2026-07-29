'''
Công thức XP cho custom rider được tính toán như sau:
XP = W1 + (W2 + W3) / YoR
'''

import math
import numpy as np

from src.engine import circuit_weights, perf_score_race, norm, FORM_STD, \
    CRASH_PROB_BASE, CRASH_PROB_K, CRASH_PROB_WET_MULT
from src.loader import load_riders, load_circuits
from src.simulator import WET_RACE_PROB_PCT
from app.wizard import RAW

# ── Monte Carlo config ──────────────────────────────────────────────────────
N_TRIALS        = 1000
YEARS           = 15
RACES_PER_ROUND = 2      # Race 1 + Race 2 per Grand Prix weekend
GROWTH_STATS    = ['rider_braking', 'rider_cornering', 'aggression',
                    'tyre_management', 'consistency']
STAT_CAP        = 99.0

CUSTOM_START = {
    'rider_braking': 65.0, 'rider_cornering': 65.0, 'aggression': 65.0,
    'tyre_management': 65.0, 'consistency': 65.0,
    'wet_performance': 80.0,            # excluded from growth, kept fixed
    'top_speed': 83.0, 'acceleration': 83.0,
    'bike_braking': 68.0, 'bike_cornering': 81.0, 'stability': 78.0,
}


# ── XP formula pieces (from the table) ──────────────────────────────────────

def w1_years(year):
    """W1 — Years of Racing weight."""
    if year <= 2:
        return 1.0
    if year <= 5:
        return 0.5
    return 0.0


def _tier_weight(position, tiers, over_weight):
    """position: int (1-based finish) or None for Ret/DNF."""
    if position is None:
        return 0.0
    for lo, hi, weight in tiers:
        if lo <= position <= hi:
            return weight
    return over_weight


P_TIERS   = [(1, 3, 6), (4, 6, 5), (7, 9, 4), (10, 12, 3), (13, 15, 2)]
EXP_TIERS = [(1, 3, 4), (4, 10, 3), (11, 15, 2)]


def w2_position(position):
    return _tier_weight(position, P_TIERS, over_weight=1.0)


def w3_exp(position):
    return _tier_weight(position, EXP_TIERS, over_weight=1.0)


# ── Field setup (fixed 24-rider grid, reused every race) ────────────────────

opponents = load_riders(RAW)
circuits  = load_circuits(RAW)
N_ROUNDS  = len(circuits)

opp_stats = {col: opponents[col].to_numpy(dtype=float) for col in
             ['rider_braking', 'rider_cornering', 'aggression', 'tyre_management',
              'consistency', 'wet_performance', 'top_speed', 'acceleration',
              'bike_braking', 'bike_cornering', 'stability']}
N_OPP = len(opponents)


def opponent_dnf_prob(laps, is_wet_mask):
    """Per-race DNF probability for each opponent, shape (N_TRIALS, N_OPP)."""
    base = CRASH_PROB_BASE + CRASH_PROB_K * norm(opp_stats['aggression']) * \
        (1 - norm(opp_stats['consistency']))                      # (N_OPP,)
    per_lap = base[None, :] * np.where(is_wet_mask[:, None], CRASH_PROB_WET_MULT, 1.0)
    return 1 - (1 - per_lap) ** max(laps - 1, 0)


def custom_dnf_prob(aggression, consistency, laps, is_wet_mask):
    base = CRASH_PROB_BASE + CRASH_PROB_K * norm(aggression) * (1 - norm(consistency))
    per_lap = base * np.where(is_wet_mask, CRASH_PROB_WET_MULT, 1.0)
    return 1 - (1 - per_lap) ** max(laps - 1, 0)


# ── Simulation state: one array per stat, one slot per Monte Carlo trial ────

state = {stat: np.full(N_TRIALS, CUSTOM_START[stat]) for stat in GROWTH_STATS}
wet_performance = np.full(N_TRIALS, CUSTOM_START['wet_performance'])
bike_fixed = {k: CUSTOM_START[k] for k in
              ['top_speed', 'acceleration', 'bike_braking', 'bike_cornering', 'stability']}

for year in range(1, YEARS + 1):
    w1 = w1_years(year)
    for round_idx in range(N_ROUNDS):
        circuit = circuits.iloc[round_idx]
        w_spd, w_cor, w_brk = circuit_weights(circuit)
        total_laps = math.ceil(100 / circuit['lap_length_km'])

        opp_row = {**opp_stats}
        opp_base_score = perf_score_race(opp_row, w_spd, w_cor, w_brk)   # (N_OPP,)

        for _race in range(RACES_PER_ROUND):
            is_wet = np.random.uniform(0, 100, size=N_TRIALS) <= WET_RACE_PROB_PCT

            # Opponents: per-race form noise + DNF roll.
            opp_noise_std = FORM_STD * (1 - 0.4 * norm(opp_stats['consistency']))
            opp_noise = np.random.normal(0.0, opp_noise_std[None, :], size=(N_TRIALS, N_OPP))
            opp_score = np.clip(opp_base_score[None, :] + opp_noise, 0.0, 1.0)
            opp_dnf = np.random.uniform(size=(N_TRIALS, N_OPP)) < opponent_dnf_prob(total_laps, is_wet)

            # Custom rider: build a row of per-trial arrays for perf_score_race.
            custom_row = {**bike_fixed, **{s: state[s] for s in GROWTH_STATS}}
            custom_score = perf_score_race(custom_row, w_spd, w_cor, w_brk)   # (N_TRIALS,)
            custom_noise_std = FORM_STD * (1 - 0.4 * norm(state['consistency']))
            custom_score = np.clip(
                custom_score + np.random.normal(0.0, custom_noise_std), 0.0, 1.0)
            custom_dnf = np.random.uniform(size=N_TRIALS) < custom_dnf_prob(
                state['aggression'], state['consistency'], total_laps, is_wet)

            # Position = 1 + number of non-DNF opponents that out-scored the
            # custom rider; Ret (None) if the custom rider itself DNF'd.
            beaten_by = ((opp_score > custom_score[:, None]) & (~opp_dnf)).sum(axis=1)
            position = beaten_by + 1

            xp = np.empty(N_TRIALS)
            for t in range(N_TRIALS):
                pos = None if custom_dnf[t] else int(position[t])
                xp[t] = w1 + (w2_position(pos) + w3_exp(pos)) / (5 * year)

            gain = xp / len(GROWTH_STATS)
            for stat in GROWTH_STATS:
                state[stat] = np.minimum(state[stat] + gain, STAT_CAP)


# ── Report ───────────────────────────────────────────────────────────────────

for stat in GROWTH_STATS:
    print(f"{stat} = {round(state[stat].mean(), 2)}")
