# How to read files.
For example, if you want to read `filename.h5`
```Python
import pandas as pd
df = pd.read_hdf("filename.h5", key="data")
```
NOTE: **key is always "data" for all hdf5 files **.

# Here is a short description about the data

| Filename             | Description                                                      |
| -------------------- | ---------------------------------------------------------------- |
| "daily_pv.h5"        | Adjusted daily price and volume data.                            |
| "daily_pit_debug.h5" | Point-in-Time financial indicators (debug sample, 100 stocks).   |


# For different data, We have some basic knowledge for them

## Daily price and volume data
$open: open price of the stock on that day.
$close: close price of the stock on that day.
$high: high price of the stock on that day.
$low: low price of the stock on that day.
$volume: volume of the stock on that day.
$factor: factor value of the stock on that day.

## Point-in-Time (PIT) financial data
PIT data is the latest financial indicator **known at each trading day** (no
look-ahead). Query it with the `P($$field)` operator; `P` collapses the
quarterly/annual <period, value> revisions onto each day. Field names end with
`_q` (quarterly) or `_a` (annual). You CANNOT query `$$field` directly — always
wrap in `P(...)`, e.g. `P($$eps_q)`.

Per-share / valuation inputs (combined with `$close` to build PE/PB/PCF):
- P($$eps_q):            earnings per share (cumulative).
- P($$eps_single_q):     single-quarter earnings per share.
- P($$bvps_q):           book value per share.
- P($$fcf_q):            free cash flow per share.

Profitability:
- P($$roe_q):            return on equity (ROE).
- P($$gross_margin_q):   gross profit margin.
- P($$net_margin_q):     net profit margin.
- P($$operating_margin_q): operating profit margin.
- P($$nim_q):            net interest margin (banks).

Growth (YoY):
- P($$revenue_growth_yoy_q):    revenue YoY growth.
- P($$net_income_growth_yoy_q): net income YoY growth.
- P($$eps_growth_yoy_q):        EPS YoY growth.
- P($$ocf_growth_yoy_q):        operating cash flow YoY growth.

Quality / safety:
- P($$debt_ratio_q):       debt-to-asset ratio.
- P($$goodwill_ratio_q):   goodwill to total assets.
- P($$ocf_to_np_q):        operating cash flow / net income (cash quality).
- P($$capex_to_revenue_q): capex / revenue.

Derived valuation examples (use `$close/$factor` for the raw price, since
`$close` is adjustment-factor adjusted):
- PE  = ($close/$factor)/(P($$eps_q)+1e-12)
- PB  = ($close/$factor)/(P($$bvps_q)+1e-12)
- PCF = ($close/$factor)/(P($$fcf_q)+1e-12)
- PEG = (($close/$factor)/(P($$eps_q)+1e-12))/(P($$eps_growth_yoy_q)+1e-12)

NOTE: PIT does NOT support referencing future periods, e.g.
`Ref($$eps_q, -1)` is invalid. Backward references like
`Ref(P($$roe_q), 60)` are fine.