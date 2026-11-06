"""Historical screening metrics shared by the K-line stock list and screener."""

import math
import threading
import time
from collections import OrderedDict

import pandas as pd

MA_PERIODS = (5, 10, 20, 30, 60, 250, 500)
# Leave room for suspensions when collecting 501 valid closes for MA500.
SCREENING_HISTORY_DAYS = max(250, 2 * max(MA_PERIODS) + 1)
CHIP_COST_FIELDS = ("weight_avg", "cost_50pct", "cost_15pct", "cost_85pct", "cost_5pct", "cost_95pct")


def chip_screening_fields(chips: dict) -> list[str]:
    fields = []
    if chips.get("rate_fields", {}).get("winner_rate"):
        fields.extend(["winner_rate", "winner_rate_position_250d", "winner_rate_change_5d", "winner_rate_change_20d"])
    prices = chips.get("price_fields", {})
    for suffix, lower, upper in ((70, "cost_15pct", "cost_85pct"), (90, "cost_5pct", "cost_95pct")):
        if prices.get(lower) and prices.get(upper):
            fields.extend([f"chip_concentration_{suffix}", f"chip_band_{suffix}_position"])
    for name, source in (("avg", "weight_avg"), ("median", "cost_50pct")):
        if prices.get(source):
            fields.append(f"chip_{name}_cost_bias")
    return fields


def chip_cost_metrics(close, costs: dict) -> dict:
    """Percent ratios using close and chip costs on the SAME price scale.

    Concentration is (upper-lower)/lower*100; smaller is tighter.
    Band positions are not clipped: values below 0 or above 100 are meaningful.
    """
    def positive(value):
        return value is not None and pd.notna(value) and math.isfinite(value) and value > 0

    def finite(value):
        return float(value) if math.isfinite(value) else None

    result = {}
    for name, source in (("avg", "weight_avg"), ("median", "cost_50pct")):
        cost = costs.get(source)
        result[f"chip_{name}_cost_bias"] = finite(100 * (close / cost - 1)) if positive(close) and positive(cost) else None
    for suffix, lower, upper in ((70, "cost_15pct", "cost_85pct"), (90, "cost_5pct", "cost_95pct")):
        lo, hi = costs.get(lower), costs.get(upper)
        result[f"chip_concentration_{suffix}"] = None
        result[f"chip_band_{suffix}_position"] = None
        if not (positive(lo) and positive(hi) and hi >= lo):
            continue
        result[f"chip_concentration_{suffix}"] = finite(100 * (hi - lo) / lo)
        if positive(close) and hi > lo:
            result[f"chip_band_{suffix}_position"] = finite(100 * (close - lo) / (hi - lo))
    return result


class ScreeningSnapshotCache:
    """Bounded per-provider cache; concurrent callers share one computation."""

    def __init__(self, ttl=300, max_entries=8):
        self.ttl = ttl
        self.max_entries = max_entries
        self._entries = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key, compute, refresh=False):
        requested_at = time.monotonic()
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                created_at, rows = cached
                # A refresh already in flight also satisfies a later refresh.
                if time.monotonic() - created_at < self.ttl and (not refresh or created_at >= requested_at):
                    self._entries.move_to_end(key)
                    return [dict(row) for row in rows]
            rows = compute()
            self._entries[key] = (time.monotonic(), rows)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
            # Prediction joins must not mutate the cached market data.
            return [dict(row) for row in rows]


def historical_screening_metrics(frame: pd.DataFrame, date: str, calendar=None) -> dict[str, dict]:
    """Use only data through date; input close is already price-adjusted.

    MA differences use consecutive valid trading observations, matching the
    chart's suspension filtering. Chip range position uses available observations
    in the last 250 market trading days, including the requested date.
    """
    end = pd.Timestamp(date)
    if frame.empty:
        return {}
    dates = pd.to_datetime(frame.index.get_level_values("date"))
    calendar_dates = pd.DatetimeIndex(pd.to_datetime(calendar)) if calendar is not None else dates
    trading_dates = calendar_dates[calendar_dates <= end].unique().sort_values()[-SCREENING_HISTORY_DAYS:]
    chip_dates = trading_dates[-250:]
    frame = frame.loc[dates.isin(trading_dates)]
    result = {}
    for symbol, history in frame.groupby(level="instrument"):
        history = history.droplevel("instrument").sort_index()
        row = {**{f"ma{period}_slope": None for period in MA_PERIODS},
               "winner_rate": None, "winner_rate_position_250d": None,
               "winner_rate_change_5d": None, "winner_rate_change_20d": None}
        result[symbol] = row
        if history.empty or pd.Timestamp(history.index[-1]) != end:
            continue
        if "close" in history:
            prices = history["close"].where(history["close"].map(lambda x: pd.notna(x) and math.isfinite(x)))
            if "volume" in history:
                prices = prices.where(history["volume"] > 0)
            # A suspended or missing current bar must not reuse an older signal.
            if pd.notna(prices.iloc[-1]):
                prices = prices.dropna()
                for period in MA_PERIODS:
                    if len(prices) > period:
                        # MA(n,t) - MA(n,t-1) = (close(t)-close(t-n))/n.
                        slope = float((prices.iloc[-1] - prices.iloc[-period - 1]) / period)
                        row[f"ma{period}_slope"] = slope if math.isfinite(slope) else None
        if "winner_rate" in history:
            rates = history.loc[history.index.isin(chip_dates), "winner_rate"]
            rates = rates.where(rates.between(0, 100))
            current = rates.iloc[-1]
            if pd.notna(current):
                row["winner_rate"] = float(current)
                for period in (5, 20):
                    if len(chip_dates) > period:
                        previous = rates.get(chip_dates[-period - 1])
                        if previous is not None and pd.notna(previous):
                            row[f"winner_rate_change_{period}d"] = float(current - previous)
                valid = rates.dropna()
                low, high = valid.min(), valid.max()
                if len(valid) >= 2 and high > low:
                    row["winner_rate_position_250d"] = float(100 * (current - low) / (high - low))
    return result
