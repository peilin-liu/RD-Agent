"""Shared portfolio metrics for native traces and script-produced experiments."""

from __future__ import annotations

import math


def portfolio_metrics(report=None, indicators=None, positions=None) -> dict:
    result = {}

    def put(key, value):
        try:
            number = float(value)
            if math.isfinite(number):
                result[key] = number
        except (TypeError, ValueError):
            pass

    if report is not None and not report.empty:
        if "turnover" in report:
            put("avg_daily_turnover", report["turnover"].mean())
        if "total_cost" in report:
            put("total_cost", report["total_cost"].iloc[-1])
    if indicators is not None and not indicators.empty and "count" in indicators:
        put("avg_daily_trade_count", indicators["count"].mean())
        put("total_trade_count", indicators["count"].sum())
    if positions is not None:
        stock_days = {}
        for day, position in positions.items():
            amounts = position.get_stock_amount_dict()
            for stock, amount in amounts.items():
                if amount and amount > 0:
                    stock_days.setdefault(stock, set()).add(day)
        put("avg_holding_days_per_symbol", sum(map(len, stock_days.values())) / len(stock_days) if stock_days else 0)
    return result


def return_chart_content(report, include_plotlyjs=True) -> dict:
    import plotly.io

    from rdagent.log.ui.qlib_report_figure import report_figure

    return {"chart_html": plotly.io.to_html(report_figure(report), include_plotlyjs=include_plotlyjs)}
