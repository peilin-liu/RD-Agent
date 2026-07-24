"""
Region configuration for multi-market Qlib data.

Reads from ~/rd-agent/config.json, falls back to hardcoded defaults.
Format:

{
  "regions": {
    "cn": {
      "qlib_data_path": "/path/to/cn/",
      "market": "csi300",
      "benchmark": "SH000300",
      "ohlcv_fields": {
        "open": "$open/$factor",
        "high": "$high/$factor",
        "low": "$low/$factor",
        "close": "$close/$factor"
      },
      "tech_fields": {
        "volume": "$volume",
        "amount": "$amount",
        "turnover": "$turnover",
        "change": "$change",
        "turnover_rate_f": "$turnover_rate_f",
        "volume_ratio": "$volume_ratio",
        "dividends": "$dividends",
        "total_mv": "$total_mv",
        "circ_mv": "$circ_mv"
      },
      "inject_pit_factors": false,
      "pit_factors": {
        "PE": "$pe_ttm",
        "PB": "$pb",
        "PS": "$ps_ttm",
        "DV_TTM": "$dv_ttm",
        "DV_RATIO": "$dv_ratio",
        "EARNINGS_YIELD": "1/($pe_ttm+1e-12)",
        "BOOK_YIELD": "1/($pb+1e-12)",
        "PE_MA60": "Mean($pe_ttm, 60)",
        "PB_MA60": "Mean($pb, 60)",
        "PE_MA120": "Mean($pe_ttm, 120)",
        "PB_MA120": "Mean($pb, 120)"
      },
      "pit_overlay_fields": ["PE_MA60", "PB_MA60", "PE_MA120", "PB_MA120"]
    },
    "hk": {"qlib_data_path": "/path/to/hk/", "market": "hsi", "benchmark": "HSI"},
    "us": {"qlib_data_path": "/path/to/us/", "market": "sp500", "benchmark": "SPX"}
  },
  "default_region": "cn"
}

`ohlcv_fields` / `tech_fields` map a display name (key) to a Qlib expression
(value). The backend queries by value and returns columns renamed to the key,
so the frontend shows clean names. List form ["$open", ...] is still accepted
as legacy (key = expression without the leading "$").

`pit_factors` (optional): map of factor name → Qlib expression. Despite the
legacy name, these need NOT use PIT financial data — they are regular Qlib
expressions over any field in `{qlib_data_path}/features/`. With a tushare
market-daily dump the valuation ratios come precomputed as daily fields
(`$pe_ttm`, `$pb`, `$ps_ttm`, `$dv_ttm`, ...), so just reference them directly:
`"PE": "$pe_ttm"`. If you DO have a PIT financial database under
`{qlib_data_path}/financial/`, use the `P($$field)` operator to collapse
point-in-time data (e.g. `P(Sum($$eps_single_q,4))` for TTM EPS). Set
`inject_pit_factors: true` only when expressions contain `P(...)`; otherwise
leave it `false`. When true, these factors are seeded into every factor
experiment's `base_features` so the runner uses them alongside market daily
data. Define PE/PB/PS etc. here — do NOT hardcode them in source.

`pit_overlay_fields` (optional): subset of `pit_factors` keys to overlay on
the K-line chart in the data-explorer UI (right-side secondary axis, e.g.
smoothed PE_MA60/PB_MA60). Factors NOT in this list render in the lower
indicator panel. Keys must exist in `pit_factors`.
"""

import json
from pathlib import Path
from dataclasses import dataclass, field
from threading import Lock
from typing import Optional

DEFAULT_CONFIG_PATH = Path.home() / ".rd-agent" / "config.json"

_DEFAULT_REGIONS = {
    "cn": {
        "qlib_data_path": "~/.qlib/qlib_data/cn_data",
        "market": "csi300",
        "benchmark": "SH000300",
    },
}

_DEFAULT_REGION = "cn"

_DEFAULT_OHLCV = {"open": "$open", "high": "$high", "low": "$low", "close": "$close"}
_DEFAULT_TECH = {"volume": "$volume"}


def _normalize_fields(v) -> dict:
    """Accept dict {display: expr} or legacy list of exprs; return dict {display: expr}."""
    if isinstance(v, dict):
        return {str(k): str(val) for k, val in v.items()}
    if isinstance(v, list):
        out: dict = {}
        for expr in v:
            expr = str(expr)
            key = expr[1:] if expr.startswith("$") else expr
            out[key] = expr
        return out
    return {}


@dataclass
class RegionInfo:
    qlib_data_path: str
    market: str
    benchmark: str
    symbols_path: str = "/data/qlib_data/symbols"
    industry_csv_path: str = ""  # e.g. /data/qlib_data/standard_csv/industry_reference/cn/symbol_industry.csv
    ohlcv_fields: dict = field(default_factory=lambda: dict(_DEFAULT_OHLCV))
    tech_fields: dict = field(default_factory=lambda: dict(_DEFAULT_TECH))
    inject_pit_factors: bool = False
    pit_factors: dict = field(default_factory=dict)
    pit_overlay_fields: list = field(default_factory=list)


def _load_config() -> dict:
    if DEFAULT_CONFIG_PATH.exists():
        with open(DEFAULT_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _resolve_path(path: str) -> str:
    return str(Path(path).expanduser().resolve())


def get_available_regions() -> list[str]:
    cfg = _load_config()
    regions = cfg.get("regions", {})
    if regions:
        return list(regions.keys())
    return list(_DEFAULT_REGIONS.keys())


def get_default_region() -> str:
    cfg = _load_config()
    return cfg.get("default_region", _DEFAULT_REGION)


def get_region_config(region: Optional[str] = None) -> RegionInfo:
    if region is None:
        region = get_default_region()

    cfg = _load_config()
    regions = cfg.get("regions", {})

    if region in regions:
        ri = regions[region]
        legacy_fields = ri.get("fields")
        ohlcv = _normalize_fields(ri.get("ohlcv_fields", legacy_fields if legacy_fields is not None else None))
        if not ohlcv:
            ohlcv = dict(_DEFAULT_OHLCV)
        tech = _normalize_fields(ri.get("tech_fields"))
        if not tech:
            tech = dict(_DEFAULT_TECH)
        pit_factors = _normalize_fields(ri.get("pit_factors"))
        inject_pit = bool(ri.get("inject_pit_factors", False))
        pit_overlay = [str(k) for k in ri.get("pit_overlay_fields", []) if str(k) in pit_factors]
        return RegionInfo(
            qlib_data_path=_resolve_path(ri["qlib_data_path"]),
            market=ri["market"],
            benchmark=ri["benchmark"],
            symbols_path=_resolve_path(ri.get("symbols_path", "/data/qlib_data/symbols")),
            industry_csv_path=_resolve_path(ri.get("industry_csv_path", "")) if ri.get("industry_csv_path") else "",
            ohlcv_fields=ohlcv,
            tech_fields=tech,
            inject_pit_factors=inject_pit,
            pit_factors=pit_factors,
            pit_overlay_fields=pit_overlay,
        )

    if region in _DEFAULT_REGIONS:
        ri = _DEFAULT_REGIONS[region]
        return RegionInfo(
            qlib_data_path=_resolve_path(ri["qlib_data_path"]),
            market=ri["market"],
            benchmark=ri["benchmark"],
            symbols_path="/data/qlib_data/symbols",
            ohlcv_fields=dict(_DEFAULT_OHLCV),
            tech_fields=dict(_DEFAULT_TECH),
        )

    raise KeyError(f"Unknown region: {region}. Available: {get_available_regions()}")


def save_config(regions: dict, default_region: str) -> None:
    DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DEFAULT_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"regions": regions, "default_region": default_region}, f, indent=2, ensure_ascii=False)


def set_default_region(region: str) -> None:
    cfg = _load_config()
    cfg["default_region"] = region
    DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DEFAULT_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


class MarketCache:
    """进程内单例缓存：扫描每个 region 的 instruments 目录得到可用 market 列表。

    启动时调 scan_all_regions() 初始化；运行中通过 get_cached_markets(region) 读缓存，
    不再扫盘。运行时新增 market 需重启进程生效。
    """

    _instance: Optional["MarketCache"] = None
    _lock = Lock()

    def __init__(self) -> None:
        self._cache: dict[str, list[str]] = {}

    @classmethod
    def instance(cls) -> "MarketCache":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def scan_region(self, region: str) -> list[str]:
        """扫描该 region 的 qlib_data_path/instruments/*.txt，文件名去 .txt 得 market 列表。"""
        try:
            ri = get_region_config(region)
        except KeyError:
            return []
        instruments_dir = Path(ri.qlib_data_path) / "instruments"
        if not instruments_dir.is_dir():
            return []
        markets = sorted(p.stem for p in instruments_dir.glob("*.txt") if p.is_file())
        return markets

    def scan_all_regions(self) -> dict[str, list[str]]:
        """遍历所有已配置 region，扫描各自的 instruments 目录并缓存结果。"""
        cache: dict[str, list[str]] = {}
        for region in get_available_regions():
            cache[region] = self.scan_region(region)
        self._cache = cache
        return cache

    def get_cached_markets(self, region: str) -> list[str]:
        """读缓存返回 market 列表（不扫盘）。缓存未初始化或 region 未知时返回空列表。"""
        return list(self._cache.get(region, []))


def get_cached_markets(region: str) -> list[str]:
    """便捷包装：读进程内 MarketCache 单例返回 region 的 market 列表。"""
    return MarketCache.instance().get_cached_markets(region)


def scan_all_regions() -> dict[str, list[str]]:
    """便捷包装：扫描所有 region 并初始化/刷新进程内 MarketCache。"""
    return MarketCache.instance().scan_all_regions()
