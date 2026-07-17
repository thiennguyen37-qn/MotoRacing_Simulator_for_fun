"""
Data loading utilities for the simulator.
"""

import pandas as pd
from pathlib import Path


def load_bikes(raw_path):
    """Load bikes_rating CSV, renamed to the bike_* columns used everywhere else."""
    return pd.read_csv(Path(raw_path) / 'bikes_rating.csv').rename(columns={
        'braking': 'bike_braking', 'cornering': 'bike_cornering'
    })


def load_riders(raw_path):
    """Load and merge entry_info + riders_rating + bikes_rating into one DataFrame."""
    raw = Path(raw_path)
    entry_info    = pd.read_csv(raw / 'entry_info.csv')
    riders_rating = pd.read_csv(raw / 'riders_rating.csv').rename(columns={
        'braking': 'rider_braking', 'cornering': 'rider_cornering'
    })
    bikes_rating  = load_bikes(raw)
    return (
        entry_info
        .merge(riders_rating, on='name', how='left')
        .merge(bikes_rating,  on=['manufacturer', 'team_status'], how='left')
    )


def load_circuits(raw_path):
    """Load circuits CSV."""
    return pd.read_csv(Path(raw_path) / 'circuits.csv')
