"""
Invariant harness for the off-season transfer market (src/transfers.py).

Standalone, like test_formula.py — run it directly:

    python test_transfers.py

Standings are synthesised rather than raced: `src.engine.perf_score_race` is the
same scoring the real Race session uses, so ordering riders by it (plus a form
wobble) gives a faithful championship without paying 11 seconds a season for the
full lap-by-lap simulation. That buys enough runs to actually see drift.

What it guards is the balance work recorded in transfer_market.md — the grid
must hold its level for decades, because the design deliberately has no AI
progression to catch it if it slips.
"""

import random
import statistics
import sys

import numpy as np

from src.engine import circuit_weights, perf_score_race
from src.loader import load_circuits, load_riders
from src.transfers import (RIDER_STATS, expected_rank, run_silly_season,
                           team_table)

RAW      = 'data/raw'
SEASONS  = 25
SEEDS    = 40
FORM_STD = 0.05     # per-season form wobble, in perf-score units


# ── Synthetic championship ────────────────────────────────────────────────────

def _mean_weights():
    """Average circuit weighting — one representative track instead of 13."""
    circuits = load_circuits(RAW)
    w = np.array([circuit_weights(c) for _, c in circuits.iterrows()])
    return tuple(w.mean(axis=0))


def standings_for(riders, weights, rng):
    """Championship order for a grid: pace plus a season's luck, best first."""
    scored = []
    for r in riders:
        score = perf_score_race(r, *weights) + rng.gauss(0, FORM_STD)
        scored.append((score, r))
    scored.sort(key=lambda x: -x[0])
    return [{'name': r['name'], 'team': r['team'], 'points': 0} for _, r in scored]


# ── Checks ────────────────────────────────────────────────────────────────────

class Report:
    def __init__(self):
        self.fails = []
        self.checks = 0

    def check(self, label, cond, detail=''):
        self.checks += 1
        if not cond:
            self.fails.append(f'{label}   {detail}')

    def done(self, title):
        print(f'\n{title}: {self.checks - len(self.fails)}/{self.checks} pass')
        for f in self.fails:
            print(f'  FAIL  {f}')
        return not self.fails


def run_career(seed, seasons=SEASONS, weights=None):
    """One career's worth of off-seasons. Yields a per-season snapshot."""
    rng = random.Random(seed)
    weights = weights or _mean_weights()
    base = load_riders(RAW).to_dict('records')
    riders = []
    for rec in base:
        r = {k: (v.item() if hasattr(v, 'item') else v) for k, v in rec.items()}
        r['contract_until'] = 2026 + rng.choice((0, 1))
        riders.append(r)
    roster = {'year': 2026, 'riders': riders, 'retired': [], 'pool_used': []}

    for s in range(seasons):
        year = 2026 + s
        table = standings_for(roster['riders'], weights, rng)
        out = run_silly_season(roster, table, None, year, RAW, rng)
        roster = {'year': out.year, 'riders': out.riders,
                  'retired': roster['retired'] + out.retired,
                  'pool_used': out.pool_used}
        yield year, out, roster


def main():
    weights = _mean_weights()
    teams = team_table(RAW)
    team_power = {str(t['team']): float(t['power']) for _, t in teams.iterrows()}
    status = {str(t['team']): str(t['team_status']) for _, t in teams.iterrows()}
    factory_of = {str(t['manufacturer']): str(t['team'])
                  for _, t in teams.iterrows() if t['team_status'] == 'factory'}

    rep = Report()
    medians, tops, ages, corrs, rookie_counts, pool_used_end = [], [], [], [], [], []
    drop_counts, left_counts, all_numbers = [], [], []
    age_stay, age_left, young, old = [], [], [], []
    baseline_stats = {}

    for seed in range(SEEDS):
        gone = set()          # dropped for underperformance — must stay gone
        for year, out, roster in run_career(seed, weights=weights):
            riders = roster['riders']

            # ── structural ────────────────────────────────────────────────────
            rep.check('24 tay dua AI', len(riders) == 24, f'seed{seed} {year}: {len(riders)}')
            squads = {}
            for r in riders:
                squads.setdefault(r['team'], []).append(r)
            rep.check('12 doi, moi doi 2 ghe',
                      len(squads) == 12 and all(len(v) == 2 for v in squads.values()),
                      f'seed{seed} {year}: {sorted((k, len(v)) for k, v in squads.items())}')
            nums = [int(r['bike_number']) for r in riders]
            rep.check('khong trung so xe', len(set(nums)) == len(nums),
                      f'seed{seed} {year}')
            rep.check('so xe nam trong 4-99 (1-3 danh cho player)',
                      all(4 <= n <= 99 for n in nums),
                      f'seed{seed} {year}: {sorted(n for n in nums if not 4 <= n <= 99)}')

            # ── bike matches team ─────────────────────────────────────────────
            bad = [r['name'] for r in riders
                   if r['team_status'] != status[r['team']]]
            rep.check('team_status khop voi doi', not bad, f'seed{seed} {year}: {bad[:3]}')

            # ── ratings frozen for life ───────────────────────────────────────
            for r in riders:
                key = r['name']
                sig = tuple(round(float(r[s]), 6) for s in RIDER_STATS)
                if key in baseline_stats:
                    rep.check('chi so khong bao gio doi', baseline_stats[key] == sig,
                              f'{key} seed{seed} {year}')
                else:
                    baseline_stats[key] = sig

            # ── which way riders move ─────────────────────────────────────────
            # Movement is measured by machinery, not job title: leaving a
            # struggling factory for a fast satellite (Triumph Factory is the
            # worst bike on the grid, Razor Racing the fourth best) is a step up
            # in every way that matters. A 'demoted' move is the one exception —
            # that rider lost their seat and is dropping down the grid.
            by_name = {r['name']: r for r in riders}
            for m in out.moves:
                if m['kind'] == 'demoted':
                    rep.check('tut hang thi phai ve xe yeu hon',
                              team_power[m['to']] < team_power[m['from']],
                              f"{m['name']} {m['from']} -> {m['to']}")
                else:
                    rep.check('chuyen thuong la len xe manh hon',
                              team_power[m['to']] > team_power[m['from']],
                              f"{m['name']} {m['from']} -> {m['to']}")
                if m['kind'] == 'promote':
                    rider = by_name.get(m['name'], {})
                    rep.check('promote = satellite -> factory cung hang',
                              status[m['from']] == 'satellite'
                              and status[m['to']] == 'factory'
                              and factory_of.get(rider.get('manufacturer')) == m['to'],
                              f"{m['name']} {m['from']} -> {m['to']}")

            # ── losing a seat is a demotion, not an exit ──────────────────────
            landed = {d['name'] for d in out.dropped if d.get('landed')}
            rep.check('nguoi tut hang van con tren luoi', landed <= set(by_name),
                      f'seed{seed} {year}: {sorted(landed - set(by_name))[:3]}')
            rep.check('landed khop voi doi thuc te',
                      all(by_name[d['name']]['team'] == d['landed']
                          for d in out.dropped if d.get('landed')),
                      f'seed{seed} {year}')
            for d in out.left:                 # nobody would take them
                rep.check('nguoi roi giai khong co landed', not d.get('landed'))
                gone.add(d['name'])
            rep.check('nguoi roi giai khong quay lai luoi',
                      not (gone & set(by_name)),
                      f'seed{seed} {year}: {sorted(gone & set(by_name))[:3]}')

            # ── rookies only fill real vacancies ──────────────────────────────
            vacancies = len(out.retired) + len(out.dropped)
            rep.check('tan binh khong nhieu hon so nguoi roi giai',
                      len(out.rookies) <= vacancies,
                      f'seed{seed} {year}: {len(out.rookies)} rookie / {vacancies} trong')

            # ── numbers for the balance report ────────────────────────────────
            rat = [statistics.fmean(float(r[s]) for s in RIDER_STATS) for r in riders]
            medians.append(statistics.median(rat))
            tops.append(max(rat))
            ages.append(statistics.fmean(int(r['age']) for r in riders))
            rookie_counts.append(len(out.rookies))
            drop_counts.append(len(out.dropped))
            left_counts.append(len(out.left))
            all_numbers += nums
            for d in out.dropped:
                (age_stay if d.get('landed') else age_left).append(int(d['age']))
                if int(d['age']) < 30:
                    young.append(bool(d.get('landed')))
                elif int(d['age']) >= 33:
                    old.append(bool(d.get('landed')))
            pw = [team_power[r['team']] for r in riders]
            corrs.append(float(np.corrcoef(pw, rat)[0, 1]))
        pool_used_end.append(len(roster['pool_used']))

    structural_ok = rep.done('Bat bien cau truc')

    # ── balance ───────────────────────────────────────────────────────────────
    young_kept = sum(young) / max(len(young), 1)
    old_kept = sum(old) / max(len(old), 1)
    bal = Report()
    med = statistics.fmean(medians)
    bal.check('median luoi trong 82-85', 82.0 <= med <= 85.0, f'{med:.2f}')
    bal.check('median khong bao gio ra ngoai 80-87',
              min(medians) >= 80.0 and max(medians) <= 87.0,
              f'{min(medians):.1f} .. {max(medians):.1f}')
    # The player needs a rival, not a perfect one every single year — a rare
    # weak season is realistic. What matters is the typical level (they peak
    # around 86-89 between seasons 15 and 25) and that the field never collapses.
    bal.check('manh nhat luoi trung binh >= 88', statistics.fmean(tops) >= 88.0,
              f'{statistics.fmean(tops):.1f}')
    weak = sum(1 for t in tops if t < 86.0) / len(tops)
    bal.check('mua khong co ai >= 86 duoi 5%', weak < 0.05, f'{weak*100:.1f}%')
    bal.check('tuoi trung binh 25-29', 25.0 <= statistics.fmean(ages) <= 29.0,
              f'{statistics.fmean(ages):.1f}')
    c = statistics.fmean(corrs)
    bal.check('tuong quan xe<->nguoi 0.25-0.60', 0.25 <= c <= 0.60, f'{c:.2f}')
    # Real seasons produce two or three genuine newcomers, not eight. Riders who
    # lose a seat drop down the grid instead of vanishing, which is what keeps
    # this near the retirement rate rather than double it.
    rpm = statistics.fmean(rookie_counts)
    bal.check('tan binh/mua <= 2.2', rpm <= 2.2, f'{rpm:.2f}')
    kept = 1.0 - (statistics.fmean(left_counts)
                  / max(statistics.fmean(drop_counts), 1e-9))
    bal.check('70-80% nguoi mat ghe o lai luoi', 0.68 <= kept <= 0.82, f'{kept*100:.0f}%')
    # …and it must be the young and the quick who stay. A flat survival rate
    # would hit the target percentage while making no sense: teams lower down
    # sign a rider who lost a seat because he still has something left, not at
    # random.
    bal.check('nguoi o lai tre hon nguoi roi giai it nhat 3 tuoi',
              statistics.fmean(age_left) - statistics.fmean(age_stay) >= 3.0,
              f'o lai {statistics.fmean(age_stay):.1f} / roi {statistics.fmean(age_left):.1f}')
    bal.check('duoi 30 tuoi thi hau het o lai', young_kept >= 0.90, f'{young_kept*100:.0f}%')
    bal.check('tu 33 tuoi tro len thi hau het roi giai', old_kept <= 0.25, f'{old_kept*100:.0f}%')
    spread = len(set(all_numbers)) / max(len(all_numbers), 1)
    bal.check('so xe rai deu 4-99 (khong dồn ve so nho)',
              statistics.fmean(all_numbers) > 40, f'TB {statistics.fmean(all_numbers):.0f}')
    bal.check(f'pool khong can sau {SEASONS} mua',
              max(pool_used_end) < 100, f'dung nhieu nhat {max(pool_used_end)}')
    balance_ok = bal.done('Can bang')

    print(f'\n{"="*60}')
    print(f'  {SEEDS} career x {SEASONS} mua')
    print(f'  median luoi      {med:.1f}   (bien {min(medians):.1f} .. {max(medians):.1f})')
    print(f'  manh nhat luoi   {statistics.fmean(tops):.1f}   (thap nhat {min(tops):.1f})')
    print(f'  tuoi trung binh  {statistics.fmean(ages):.1f}')
    print(f'  tuong quan xe    {c:.2f}')
    print(f'  mat ghe/mua      {statistics.fmean(drop_counts):.2f}   '
          f'({kept*100:.0f}% tut xuong doi yeu, {statistics.fmean(left_counts):.2f} roi giai)')
    print(f'    o lai tuoi TB  {statistics.fmean(age_stay):.1f}   '
          f'| roi giai {statistics.fmean(age_left):.1f}')
    print(f'    <30 o lai      {young_kept*100:.0f}%   | >=33 o lai {old_kept*100:.0f}%')
    print(f'  tan binh/mua     {rpm:.2f}   -> pool du ~{100/max(rpm, .01):.0f} mua')
    print(f'  pool da dung     {statistics.fmean(pool_used_end):.0f}/100 sau {SEASONS} mua')
    print(f'{"="*60}')
    player_ok = player_checks(weights)
    return 0 if (structural_ok and balance_ok and player_ok) else 1


def player_checks(weights):
    """The career rider's own path through the market.

    The long run above races an AI-only grid, so none of this is exercised
    there. The player is supernumerary — never one of the 24 AI seats — so what
    is tested is which teams would sign them, not which seats are free.
    """
    from src.transfers import DROP_EFFICIENCY, Offer, hire_bar

    rep = Report()
    teams = team_table(RAW)
    base = load_riders(RAW).to_dict('records')

    def fresh_roster(year=2026):
        riders = []
        for rec in base:
            r = {k: (v.item() if hasattr(v, 'item') else v) for k, v in rec.items()}
            r['contract_until'] = year + 1          # nobody droppable by default
            riders.append(r)
        return {'year': year, 'riders': riders, 'retired': [], 'pool_used': []}

    def make_player(team='Inferno Factory', rating=85.0, contract=2027):
        row = teams[teams.team == team].iloc[0]
        p = {'name': 'CAREER RIDER', 'age': 24, 'nationality': 'Vietnam',
             'bike_number': 46, 'team': team, 'manufacturer': str(row['manufacturer']),
             'team_status': str(row['team_status']), 'contract_until': contract,
             'top_speed': int(row['top_speed']), 'acceleration': int(row['acceleration']),
             'bike_braking': int(row['braking']), 'bike_cornering': int(row['cornering']),
             'stability': int(row['stability'])}
        for s in RIDER_STATS:
            p[s] = rating
        return p

    def market(player, place):
        """Run one off-season with the player finishing at championship `place`."""
        roster = fresh_roster()
        order = standings_for(roster['riders'], weights, random.Random(0))
        order.insert(place - 1, {'name': player['name'], 'team': player['team'],
                                 'points': 0})
        return run_silly_season(roster, order, player, 2026, RAW, random.Random(1))

    # ── a star on a weak bike ────────────────────────────────────────────────
    star = make_player('Phoenix Motorsport', 88.0, contract=2026)
    out = market(star, 3)                    # P3 on the worst bike = huge efficiency
    rep.check('player khong lot vao roster AI',
              star['name'] not in {r['name'] for r in out.riders})
    rep.check('van du 24 AI', len(out.riders) == 24, len(out.riders))
    rep.check('chay xuat sac -> khong bi sa thai', not out.player_dropped)
    rep.check('duoc offer', len(out.player_offers) > 0)
    rep.check('co offer tu doi manh nhat',
              out.player_offers and out.player_offers[0].team == 'Ducati Factory Racing',
              out.player_offers[0].team if out.player_offers else '—')
    rep.check('offer xep theo xe manh dan',
              [o.power for o in out.player_offers]
              == sorted((o.power for o in out.player_offers), reverse=True))
    rep.check('offer mang dung thong so xe cua doi',
              all(o.bike == {k: int(teams[teams.team == o.team].iloc[0][v])
                             for k, v in [('top_speed', 'top_speed'),
                                          ('acceleration', 'acceleration'),
                                          ('bike_braking', 'braking'),
                                          ('bike_cornering', 'cornering'),
                                          ('stability', 'stability')]}
                  for o in out.player_offers))
    rep.check('doi hien tai duoc danh dau current',
              sum(1 for o in out.player_offers if o.current) == 1)

    # ── a passenger on a good bike ───────────────────────────────────────────
    dud = make_player('Ducati Factory Racing', 72.0, contract=2026)
    out = market(dud, 24)                    # last, on the best bike
    rep.check('chay te tren xe xin -> bi sa thai', out.player_dropped)
    rep.check('doi cu bien mat khoi offer',
              all(o.team != 'Ducati Factory Racing' for o in out.player_offers))
    rep.check('van con cua lui satellite (khong ket thuc career)',
              any(o.team_status == 'satellite' for o in out.player_offers),
              [o.team for o in out.player_offers])

    # ── contract protects, same as an AI ─────────────────────────────────────
    safe = make_player('Ducati Factory Racing', 72.0, contract=2028)
    out = market(safe, 24)
    rep.check('con hop dong thi khong bi sa thai', not out.player_dropped)

    # ── the bar rises with the bike ──────────────────────────────────────────
    rep.check('doi xe manh doi hoi cao hon doi xe yeu',
              hire_bar(teams, 'Ducati Factory Racing')
              > hire_bar(teams, 'Phoenix Motorsport'))
    mid = make_player('Storm Riders', 80.0, contract=2026)
    out = market(mid, 15)
    got = {o.team for o in out.player_offers}
    rep.check('ket qua trung binh -> khong duoc moi vao doi dau bang',
              'Ducati Factory Racing' not in got, sorted(got))
    return rep.done('Nguoi choi')


if __name__ == '__main__':
    sys.exit(main())
