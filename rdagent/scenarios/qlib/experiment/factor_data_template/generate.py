import os
import sys

import qlib
from qlib.data import D

_provider_uri = os.environ.get("QLIB_PROVIDER_URI", "/root/.qlib_data")
qlib.init(provider_uri=_provider_uri)

instruments = D.instruments()
fields = ["$open", "$close", "$high", "$low", "$volume", "$factor"]
data = D.features(instruments, fields, freq="day").swaplevel().sort_index().loc["2008-12-29":].sort_index()

data.to_hdf("./daily_pv_all.h5", key="data")


fields = ["$open", "$close", "$high", "$low", "$volume", "$factor"]
data = (
    (
        D.features(instruments, fields, start_time="2018-01-01", end_time="2019-12-31", freq="day")
        .swaplevel()
        .sort_index()
    )
    .swaplevel()
    .loc[data.reset_index()["instrument"].unique()[:100]]
    .swaplevel()
    .sort_index()
)

data.to_hdf("./daily_pv_debug.h5", key="data")

# Point-in-Time financial data. Lives under {provider_uri}/financial/.
# The `P($$field)` operator collapses <period, feature> onto each trading day
# using the latest revision known at that day (no look-ahead). P() is not
# vectorized, so PIT is exported only for the 100-instrument debug sample to
# keep the full `daily_pv_all.h5` fast. Only the raw PIT fields are exported
# here for data discovery — derived factors (PE/PB/ROE/...) are defined in
# ~/.rd-agent/config.json (regions[region].pit_factors), not hardcoded.
_pit_fields = [
    "P($$eps_q)",
    "P($$eps_single_q)",
    "P($$bvps_q)",
    "P($$fcf_q)",
    "P($$roe_q)",
    "P($$gross_margin_q)",
    "P($$net_margin_q)",
    "P($$operating_margin_q)",
    "P($$nim_q)",
    "P($$debt_ratio_q)",
    "P($$goodwill_ratio_q)",
    "P($$ocf_to_np_q)",
    "P($$capex_to_revenue_q)",
    "P($$revenue_growth_yoy_q)",
    "P($$net_income_growth_yoy_q)",
    "P($$eps_growth_yoy_q)",
    "P($$ocf_growth_yoy_q)",
]
_debug_instruments = data.reset_index()["instrument"].unique()[:100].tolist()
try:
    pit_data = D.features(
        _debug_instruments,
        _pit_fields,
        start_time="2018-01-01",
        end_time="2019-12-31",
        freq="day",
    ).sort_index()
    pit_data.to_hdf("./daily_pit_debug.h5", key="data")
    print(f"PIT debug export: shape={pit_data.shape}", file=sys.stderr)
except Exception as e:  # PIT data optional; never block market data export
    print(f"WARN: PIT export skipped: {e}", file=sys.stderr)
