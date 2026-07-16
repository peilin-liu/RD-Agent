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
      "ohlcv_fields": ["$open", "$high", "$low", "$close", "$adjclose", "$factor"],
      "tech_fields": ["$volume", "$turnover", "$amount", "$change"]
    },
    "hk": {"qlib_data_path": "/path/to/hk/", "market": "hsi", "benchmark": "HSI"},
    "us": {"qlib_data_path": "/path/to/us/", "market": "sp500", "benchmark": "SPX"}
  },
  "default_region": "cn"
}
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


@dataclass
class RegionInfo:
    qlib_data_path: str
    market: str
    benchmark: str
    symbols_path: str = "/data/qlib_data/symbols"
    ohlcv_fields: list[str] = field(default_factory=lambda: ["$open", "$close", "$high", "$low"])
    tech_fields: list[str] = field(default_factory=lambda: ["$volume"])


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
        return RegionInfo(
            qlib_data_path=_resolve_path(ri["qlib_data_path"]),
            market=ri["market"],
            benchmark=ri["benchmark"],
            symbols_path=_resolve_path(ri.get("symbols_path", "/data/qlib_data/symbols")),
            ohlcv_fields=ri.get("ohlcv_fields", legacy_fields or ["$open", "$close", "$high", "$low"]),
            tech_fields=ri.get("tech_fields", []),
        )

    if region in _DEFAULT_REGIONS:
        ri = _DEFAULT_REGIONS[region]
        return RegionInfo(
            qlib_data_path=_resolve_path(ri["qlib_data_path"]),
            market=ri["market"],
            benchmark=ri["benchmark"],
            symbols_path="/data/qlib_data/symbols",
            ohlcv_fields=["$open", "$close", "$high", "$low"],
            tech_fields=["$volume"],
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
