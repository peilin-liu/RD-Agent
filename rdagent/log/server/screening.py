"""Historical screening metrics shared by the K-line stock list and screener."""

import math

import pandas as pd


def historical_screening_metrics(frame: pd.DataFrame, date: str) -> dict[str, dict]:
    """Use only data through date; input close is already price-adjusted.

    MA differences use consecutive valid trading observations, matching the
    chart's suspension filtering. Chip range position uses available observations
    in the last 250 market trading days, including the requested date.
    """
    end = pd.Timestamp(date)
    if frame.empty:
        return {}
    dates = pd.to_datetime(frame.index.get_level_values("date"))
    trading_dates = dates[dates <= end].unique().sort_values()[-250:]
    frame = frame.loc[dates.isin(trading_dates)]
    result = {}
    for symbol, history in frame.groupby(level="instrument"):
        history = history.droplevel("instrument").sort_index()
        row = {"ma5_slope": None, "ma20_slope": None, "ma60_slope": None,
               "winner_rate": None, "winner_rate_position_250d": None}
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
                for period in (5, 20, 60):
                    if len(prices) > period:
                        # MA(n,t) - MA(n,t-1) = (close(t)-close(t-n))/n.
                        slope = float((prices.iloc[-1] - prices.iloc[-period - 1]) / period)
                        row[f"ma{period}_slope"] = slope if math.isfinite(slope) else None
        if "winner_rate" in history:
            rates = history["winner_rate"].where(history["winner_rate"].between(0, 100))
            current = rates.iloc[-1]
            if pd.notna(current):
                row["winner_rate"] = float(current)
                valid = rates.dropna()
                low, high = valid.min(), valid.max()
                if len(valid) >= 2 and high > low:
                    row["winner_rate_position_250d"] = float(100 * (current - low) / (high - low))
    return result
