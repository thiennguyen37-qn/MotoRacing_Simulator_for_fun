"""
Data loading utilities — shared across all session notebooks and the pipeline.
"""

import pandas as pd
from pathlib import Path


def load_riders(raw_path):
    """Load and merge entry_info + riders_rating + bikes_rating into one DataFrame."""
    raw = Path(raw_path)
    entry_info    = pd.read_csv(raw / 'entry_info.csv')
    riders_rating = pd.read_csv(raw / 'riders_rating.csv').rename(columns={
        'braking': 'rider_braking', 'cornering': 'rider_cornering'
    })
    bikes_rating  = pd.read_csv(raw / 'bikes_rating.csv').rename(columns={
        'braking': 'bike_braking', 'cornering': 'bike_cornering'
    })
    return (
        entry_info
        .merge(riders_rating, on='name', how='left')
        .merge(bikes_rating,  on=['manufacturer', 'team_status'], how='left')
    )


def load_circuits(raw_path):
    """Load circuits CSV."""
    return pd.read_csv(Path(raw_path) / 'circuits.csv')


def parse_practice_md(report_dir):
    """Parse Practice.md → DataFrame with columns [position, name]."""
    md   = (Path(report_dir) / 'Practice.md').read_text(encoding='utf-8')
    rows = [l for l in md.split('\n') if l.startswith('| P') and not l.startswith('| P |')]
    result = []
    for line in rows:
        parts = [p.strip() for p in line.split('|')]
        result.append({'position': int(parts[1][1:]), 'name': parts[3]})
    return pd.DataFrame(result)


def parse_grid_md(report_dir):
    """Parse grid.md → DataFrame with columns [grid_pos, bike_number, name]."""
    md   = (Path(report_dir) / 'grid.md').read_text(encoding='utf-8')
    rows = [l for l in md.split('\n') if l.startswith('| P') and not l.startswith('| P |')]
    grid = []
    for line in rows:
        parts = [p.strip() for p in line.split('|')]
        grid.append({
            'grid_pos'   : int(parts[1][1:]),
            'bike_number': int(parts[2][1:]),
            'name'       : parts[3],
        })
    return pd.DataFrame(grid).sort_values('grid_pos').reset_index(drop=True)
