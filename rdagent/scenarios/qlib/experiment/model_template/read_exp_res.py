import pickle
from pathlib import Path

import pandas as pd
import qlib
from mlflow.entities import ViewType
from mlflow.tracking import MlflowClient

qlib.init()

from qlib.workflow import R

# here is the documents of the https://qlib.readthedocs.io/en/latest/component/recorder.html

# TODO: list all the recorder and metrics

# Assuming you have already listed the experiments
experiments = R.list_experiments()

# Iterate through each experiment to find the latest recorder
experiment_name = None
latest_recorder = None
for experiment in experiments:
    recorders = R.list_recorders(experiment_name=experiment)
    for recorder_id in recorders:
        if recorder_id is not None:
            experiment_name = experiment
            recorder = R.get_recorder(recorder_id=recorder_id, experiment_name=experiment)
            end_time = recorder.info["end_time"]
            try:
                # Check if the recorder has a valid end time
                if end_time is not None:
                    if latest_recorder is None or end_time > latest_recorder.info["end_time"]:
                        latest_recorder = recorder
                else:
                    print(f"Warning: Recorder {recorder_id} has no valid end time")
            except Exception as e:
                print(f"Error: {e}")

# Check if the latest recorder is found
if latest_recorder is None:
    print("No recorders found")
else:
    print(f"Latest recorder: {latest_recorder}")

    # Load the specified file from the latest recorder
    metrics = pd.Series(latest_recorder.list_metrics())

    # Extract trading-level metrics from portfolio_analysis artifacts.
    # mlflow metrics already include IC/ICIR/Rank IC/Rank ICIR/annualized
    # return/max drawdown, but turnover / trade count / holding days / total
    # cost live in the portfolio_analysis pickles, so we compute them here
    # and merge into the metrics series for downstream reporting.
    try:
        report_df = latest_recorder.load_object("portfolio_analysis/report_normal_1day.pkl")
        indicators_df = latest_recorder.load_object("portfolio_analysis/indicators_normal_1day.pkl")
        positions_obj = latest_recorder.load_object("portfolio_analysis/positions_normal_1day.pkl")

        # Average daily turnover (fraction of portfolio traded per day).
        metrics["avg_daily_turnover"] = float(report_df["turnover"].mean())
        # Total trading cost (cumulative cost at last day, in account currency).
        metrics["total_cost"] = float(report_df["total_cost"].iloc[-1])
        # Average daily trade count (number of stocks traded per day) and
        # total trade count (sum of per-day stock trade counts).
        metrics["avg_daily_trade_count"] = float(indicators_df["count"].mean())
        metrics["total_trade_count"] = float(indicators_df["count"].sum())
        # Average holding days per symbol. Build a per-stock holding-day set
        # from daily positions, then average across all stocks ever held.
        holding_days = []
        for day in sorted(positions_obj.keys()):
            pos = positions_obj[day]
            try:
                amt_dict = pos.get_stock_amount_dict()
            except Exception:
                amt_dict = {}
            for stock, amount in amt_dict.items():
                if amount and amount > 0:
                    holding_days.append((stock, day))
        if holding_days:
            stock_days = {}
            for stock, day in holding_days:
                stock_days.setdefault(stock, set()).add(day)
            counts = [len(s) for s in stock_days.values()]
            metrics["avg_holding_days_per_symbol"] = float(sum(counts) / len(counts))
        else:
            metrics["avg_holding_days_per_symbol"] = 0.0
    except Exception as e:
        print(f"Warning: failed to extract portfolio metrics: {e}")

    output_path = Path(__file__).resolve().parent / "qlib_res.csv"
    metrics.to_csv(output_path)

    print(f"Output has been saved to {output_path}")

    ret_data_frame = latest_recorder.load_object("portfolio_analysis/report_normal_1day.pkl")
    ret_data_frame.to_pickle("ret.pkl")
