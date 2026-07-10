"""
Region configuration for multi-market Qlib data.

Reads from ~/rd-agent/config.json, falls back to hardcoded defaults.
Format:

{
  "regions": {
    "cn": {"qlib_data_path": "/path/to/cn/", "market": "csi300", "benchmark": "SH000300"},
    "hk": {"qlib_data_path": "/path/to/hk/", "market": "hsi", "benchmark": "HSI"},
    "us": {"qlib_data_path": "/path/to/us/", "market": "sp500", "benchmark": "SPX"}
  },
  "default_region": "cn"
}
"""

import json
from pathlib import Path
from dataclasses import dataclass, field
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
    fields: list[str] = field(default_factory=lambda: ["$open", "$close", "$high", "$low", "$volume"])


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
        return RegionInfo(
            qlib_data_path=_resolve_path(ri["qlib_data_path"]),
            market=ri["market"],
            benchmark=ri["benchmark"],
            symbols_path=_resolve_path(ri.get("symbols_path", "/data/qlib_data/symbols")),
            fields=ri.get("fields", []),
        )

    if region in _DEFAULT_REGIONS:
        ri = _DEFAULT_REGIONS[region]
        return RegionInfo(
            qlib_data_path=_resolve_path(ri["qlib_data_path"]),
            market=ri["market"],
            benchmark=ri["benchmark"],
            symbols_path="/data/qlib_data/symbols",
            fields=[],
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
