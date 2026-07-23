"""
Custom-rider stat progression: XP earned per race, split equally across the
five growth stats (the bike stats are always fixed). Tuned via the Monte Carlo
harness in test_formula.py at the project root; keep that formula in sync with
this one by hand, it isn't imported from here on purpose (test_formula.py is
meant to stay a standalone scratchpad for trying out other formulas later).

XP = W1 + (W2 + W3) / (5 * YoR)

wet_performance is normally frozen, but a WET race additionally awards it
W3 / (5 * YoR) on top of the usual 5-stat split (see wet_perf_bonus) — a
rider only sharpens its wet craft by actually racing in the wet.
"""

GROWTH_STATS = ['rider_braking', 'rider_cornering', 'aggression',
                'tyre_management', 'consistency']
STAT_CAP = 99.0

P_TIERS   = [(1, 3, 6), (4, 6, 5), (7, 9, 4), (10, 12, 3), (13, 15, 2)]
EXP_TIERS = [(1, 3, 4), (4, 10, 3), (11, 15, 2)]


def _w1_years(year):
    """W1 — Years of Racing weight."""
    if year <= 2:
        return 1.0
    if year <= 5:
        return 0.5
    return 0.0


def _tier_weight(position, tiers, over_weight=1.0):
    """position: 1-based finish, or None for a Ret/DNF (weight 0)."""
    if position is None:
        return 0.0
    for lo, hi, weight in tiers:
        if lo <= position <= hi:
            return weight
    return over_weight


def xp_for_race(position, year):
    """position: 1-based finish, or None for a DNF. year: years of racing (1-based)."""
    w1 = _w1_years(year)
    w2 = _tier_weight(position, P_TIERS)
    w3 = _tier_weight(position, EXP_TIERS)
    return w1 + (w2 + w3) / (5 * year)


def wet_perf_bonus(position, year):
    """Wet race only: XP added to wet_performance on top of the normal 5-stat
    split. Uses the EXP/W3 position weight alone: W3 / (5 * year)."""
    w3 = _tier_weight(position, EXP_TIERS)
    return w3 / (5 * year)


def apply_growth(rider: dict, xp: float, wet_bonus: float = 0.0) -> dict:
    """Split xp equally across the 5 growth stats, capped at STAT_CAP, and (in
    a wet race) add wet_bonus to wet_performance. Mutates `rider` in place;
    returns {stat: (old, new, delta)} — including 'wet_performance' only when
    wet_bonus > 0."""
    per_stat = xp / len(GROWTH_STATS)
    result = {}
    for stat in GROWTH_STATS:
        old = float(rider.get(stat, 0.0))
        new = min(old + per_stat, STAT_CAP)
        rider[stat] = new
        result[stat] = (old, new, new - old)
    if wet_bonus > 0:
        old = float(rider.get('wet_performance', 0.0))
        new = min(old + wet_bonus, STAT_CAP)
        rider['wet_performance'] = new
        result['wet_performance'] = (old, new, new - old)
    return result
