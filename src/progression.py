"""Custom-rider stat progression: XP earned per race, banked into a pool the
player spends by hand in Your Profile -> Rating. Tuned via the Monte Carlo
harness in test_formula.py at the project root; keep that formula in sync with
this one by hand, it isn't imported from here on purpose (test_formula.py is
meant to stay a standalone scratchpad for trying out other formulas later).

XP = W1 + (W2 + W3) / (5 * YoR)

Nothing is applied to a stat automatically. A race banks its XP into one of two
pools on the rider: a DRY race feeds `xp_pool`, which buys the five growth
stats, and a WET race feeds `xp_pool_wet` in full, which buys wet_performance
alone — a rider only sharpens its wet craft by actually racing in the wet, and
a wet weekend teaches nothing about the dry.

Spending is quantised to XP_STEP (0.01), the precision the rating bars already
display: 1 XP buys 100 steps, so a pool converts 1:1 into total stat points but
the player chooses where they land instead of having them split five ways.
"""

GROWTH_STATS = ['rider_braking', 'rider_cornering', 'aggression',
                'tyre_management', 'consistency']
WET_STAT  = 'wet_performance'
STAT_CAP  = 99.0

# One step of spendable progress, and what it costs out of the pool. A step is
# 0.01 of a stat and costs 0.01 XP, so `steps = XP * 100`.
XP_STEP   = 0.01

DRY_POOL  = 'xp_pool'
WET_POOL  = 'xp_pool_wet'

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


# ── The two pools ────────────────────────────────────────────────────────────

def _round(x: float) -> float:
    """Trim binary-float dust off a stat or a pool balance."""
    return round(float(x), 6)


def pool_key(stat: str) -> str:
    """Which pool pays for `stat`."""
    return WET_POOL if stat == WET_STAT else DRY_POOL


def pool(rider: dict, key: str) -> float:
    """Banked XP in one pool. Absent on riders saved before pools existed."""
    return float(rider.get(key, 0.0) or 0.0)


def bank_xp(rider: dict, xp: float, is_wet: bool = False) -> str:
    """Add a race's XP to the pool that race feeds. Mutates `rider` in place and
    returns the pool key that took it. Stored as a plain float: save_career_rider
    serialises with `default=int`, which would truncate a numpy scalar."""
    key = WET_POOL if is_wet else DRY_POOL
    rider[key] = pool(rider, key) + float(xp)
    return key


def steps_available(rider: dict, stat: str) -> int:
    """How many 0.01 steps the pool behind `stat` can still pay for. Rounded
    rather than floored so a pool of exactly 1.0 XP buys 100 steps and not 99,
    which float error would otherwise cost the player."""
    return max(0, int(round(pool(rider, pool_key(stat)) / XP_STEP)))


def steps_to_cap(rider: dict, stat: str) -> int:
    """How many steps `stat` has left before STAT_CAP — the other ceiling."""
    return max(0, int(round((STAT_CAP - float(rider.get(stat, 0.0))) / XP_STEP)))


def max_steps(rider: dict, stat: str) -> int:
    """Largest X the player may spend on `stat` right now."""
    return min(steps_available(rider, stat), steps_to_cap(rider, stat))


def spend_xp(rider: dict, stat: str, steps: int):
    """Raise `stat` by XP_STEP * steps and charge the matching pool.

    Mutates `rider` in place and returns (old, new, cost_in_xp), or None when
    `steps` is not a positive amount the rider can currently afford — the
    caller decides how to tell the player, and nothing is charged."""
    steps = int(steps)
    if steps <= 0 or steps > max_steps(rider, stat):
        return None
    key  = pool_key(stat)
    cost = steps * XP_STEP
    old  = float(rider.get(stat, 0.0))
    # Rounded because a spend is now one step per keypress rather than one
    # typed total: a hundred presses of +0.01 otherwise leaves binary-float
    # crumbs (70.03000000000002) in the stat and in the saved rider.json. Six
    # places is far finer than the 0.01 grid, so nothing real is disturbed.
    new  = _round(min(old + cost, STAT_CAP))
    rider[stat]  = new
    rider[key]   = _round(max(0.0, pool(rider, key) - cost))
    return old, new, cost


def refund_xp(rider: dict, stat: str, steps: int):
    """Undo a spend: drop `stat` by XP_STEP * steps and hand the XP back to the
    matching pool.

    Mutates `rider` in place and returns (old, new, refunded_xp), or None when
    `steps` isn't positive. Nothing here remembers what was spent, so it would
    happily walk a stat below where the player found it — how far back an undo
    may reach is the caller's to enforce (Your Profile -> Rating only lets Left
    take back steps bought in that same visit)."""
    steps = int(steps)
    if steps <= 0:
        return None
    key    = pool_key(stat)
    refund = steps * XP_STEP
    old    = float(rider.get(stat, 0.0))
    new    = _round(max(0.0, old - refund))
    rider[stat] = new
    rider[key]  = _round(pool(rider, key) + refund)
    return old, new, refund
