# 2026-07-13 (P0): Synthetic "ice cream sales" tutorial dataset with *planted* relationships
# (sales <- temperature, school_out, ad_spend; website_visits <- ad_spend) plus decoy columns
# (lottery_numbers, competitor_promo) that must NOT correlate with anything.
# Why: every later phase (profiling, flows, mining, PCA) needs a deterministic fixture whose
# ground truth is known, so the mining engine can be golden-tested honestly (P3 acceptance
# criterion in the build plan). stdlib-only on purpose — P0 carries no numeric dependencies.

from __future__ import annotations

import csv
import math
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any

DEFAULT_DAYS = 1095  # three years of daily rows
DEFAULT_SEED = 42
DEFAULT_START = date(2023, 1, 1)

COLUMNS: tuple[str, ...] = (
    "date",
    "day_of_week",
    "temperature_c",
    "humidity_pct",
    "school_out",
    "ad_spend",
    "website_visits",
    "competitor_promo",
    "lottery_numbers",
    "ice_cream_sales",
)

_DOW = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _is_school_out(d: date) -> bool:
    # Summer break (~mid-June to end of August) plus winter break around New Year.
    doy = d.timetuple().tm_yday
    return 166 <= doy <= 243 or doy >= 355 or doy <= 3


def generate_rows(
    days: int = DEFAULT_DAYS,
    seed: int = DEFAULT_SEED,
    start: date = DEFAULT_START,
) -> list[dict[str, Any]]:
    """Generate daily rows. Deterministic for a given (days, seed, start).

    Planted ground truth (documented so tests and the P3 golden tests can assert it):
      ice_cream_sales = 40 + 9.5*max(temp,0) + 120*school_out + 0.6*ad_spend + N(0,35)
      website_visits  = 200 + 3.5*ad_spend + N(0,60)
      humidity_pct    is mildly anti-correlated with temperature (gives PCA some structure)
      competitor_promo and lottery_numbers are pure noise (FDR must reject them).
    """
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []
    for i in range(days):
        d = start + timedelta(days=i)
        doy = d.timetuple().tm_yday
        # Seasonal sinusoid: coldest around mid-January, warmest around mid-July.
        temp = 12.0 - 10.0 * math.cos(2 * math.pi * (doy - 15) / 365.25) + rng.gauss(0, 2.5)
        humidity = min(95.0, max(20.0, 65.0 - 0.8 * (temp - 12.0) + rng.gauss(0, 6)))
        school_out = 1 if _is_school_out(d) else 0
        weekend = d.weekday() >= 5
        ad_spend = max(0.0, 50.0 + (30.0 if weekend else 0.0) + 0.02 * i + rng.gauss(0, 10))
        visits = max(0, round(200 + 3.5 * ad_spend + rng.gauss(0, 60)))
        promo = 1 if rng.random() < 0.15 else 0
        lottery = rng.randint(1, 49)
        sales = max(
            0,
            round(
                40.0 + 9.5 * max(temp, 0.0) + 120.0 * school_out + 0.6 * ad_spend + rng.gauss(0, 35)
            ),
        )
        rows.append(
            {
                "date": d.isoformat(),
                "day_of_week": _DOW[d.weekday()],
                "temperature_c": round(temp, 1),
                "humidity_pct": round(humidity, 1),
                "school_out": school_out,
                "ad_spend": round(ad_spend, 2),
                "website_visits": visits,
                "competitor_promo": promo,
                "lottery_numbers": lottery,
                "ice_cream_sales": sales,
            }
        )
    return rows


def write_csv(
    path: Path | str,
    days: int = DEFAULT_DAYS,
    seed: int = DEFAULT_SEED,
    start: date = DEFAULT_START,
) -> Path:
    """Write the dataset to CSV, creating parent directories as needed."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = generate_rows(days=days, seed=seed, start=start)
    with p.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    return p
