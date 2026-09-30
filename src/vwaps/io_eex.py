"""EEX settlements from eex_scraper curves.

Read curves/POWER/<AREA>/<Product>.csv in long format using four columns:
tradeDate, maturityType, deliveryStart, settlPx. Other EEX sources
(DataSource, an Excel file...) are supported when converted to this format.
"""

from __future__ import annotations

from bisect import bisect_right
from datetime import date, timedelta
import math
from pathlib import Path

import pandas as pd

from vwaps.log import get_logger
from vwaps.tenors import Key, period_from_eex

REQUIRED = ["tradeDate", "maturityType", "deliveryStart", "settlPx"]


def load_eex_frame(path: Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"EEX curve not found: {path}")
    df = pd.read_csv(path, encoding="utf-8-sig", usecols=lambda c: c in REQUIRED)
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    prices = pd.to_numeric(df["settlPx"], errors="coerce")
    valid = prices.map(math.isfinite).astype(bool)
    invalid_count = int((~valid).sum())
    if invalid_count:
        get_logger().warning(
            "%s: excluded %d missing, invalid or nonfinite EEX settlements; retained %d rows",
            path, invalid_count, int(valid.sum()),
        )
    df = df.loc[valid].copy()
    df["settlPx"] = prices.loc[valid]
    df["tradeDate"] = pd.to_datetime(df["tradeDate"]).dt.date
    df["deliveryStart"] = pd.to_datetime(df["deliveryStart"]).dt.date
    return df


class EexBook:
    """Date-indexed EEX curve for one product, loaded from one file."""

    def __init__(self, df: pd.DataFrame):
        by_date: dict[date, dict[Key, float]] = {}
        day_history: dict[date, dict[date, float]] = {}
        invalid_count = 0
        for td, mt, ds, px in df[REQUIRED].itertuples(index=False):
            try:
                price = float(px)
            except (TypeError, ValueError, OverflowError):
                invalid_count += 1
                continue
            if not math.isfinite(price):
                invalid_count += 1
                continue
            per = period_from_eex(mt, ds)
            if per is None:
                continue
            by_date.setdefault(td, {})[per.key] = price
            # Keep fixings published after delivery as well. Select them
            # at query time to avoid look-ahead bias.
            if mt == "Day":
                day_history.setdefault(ds, {})[td] = price
        if invalid_count:
            get_logger().warning(
                "EEX table: excluded %d missing, invalid or nonfinite settlements; retained %d input rows",
                invalid_count, len(df) - invalid_count,
            )
        self._by_date = by_date
        self._dates = sorted(by_date)
        self._day_history = {
            day: (sorted(publications), publications)
            for day, publications in day_history.items()
        }
        self._cache: dict[tuple[date, int], tuple[dict[Key, float], date | None]] = {}

    @classmethod
    def from_file(cls, path: Path) -> EexBook:
        return cls(load_eex_frame(path))

    @property
    def trade_dates(self) -> list[date]:
        return self._dates

    def asof(self, t: date, max_stale_days: int | None) -> date | None:
        """Last publication date <= t. max_stale_days: None = unlimited; 0 = t only."""
        i = bisect_right(self._dates, t)
        if i == 0:
            return None
        d = self._dates[i - 1]
        return d if max_stale_days is None or (t - d).days <= max_stale_days else None

    def quotes(self, t: date, max_stale_days: int | None) -> tuple[dict[Key, float], date | None]:
        """Quotes available on t: settlements from the last date <= t, subject
        to the age limit, plus delivered days for BOM/BOW residual pricing."""
        ck = (t, -1 if max_stale_days is None else max_stale_days)
        if ck in self._cache:
            return self._cache[ck]
        d = self.asof(t, max_stale_days)
        if d is None:
            out: tuple[dict[Key, float], date | None] = ({}, None)
        else:
            q: dict[Key, float] = {}
            lo = d - timedelta(days=45)
            for day, (publication_dates, publications) in self._day_history.items():
                if lo <= day < d:
                    i = bisect_right(publication_dates, d)
                    if i:
                        q[(day, day + timedelta(days=1))] = publications[publication_dates[i - 1]]
            q.update(self._by_date[d])
            out = (q, d)
        self._cache[ck] = out
        return out
