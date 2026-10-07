"""Read and validate config.toml."""

from __future__ import annotations

import math
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    base_dir: Path
    vwap_input: str
    mapping_file: Path
    eex_curves_dir: Path
    output_dir: Path
    # Layers
    layer_local: bool
    layer_correlation: bool
    layer_cross: bool
    layer_hist: str  # on | off | auto
    layer_arbitrage: bool
    # EEX
    max_stale_days: int | None
    warn_stale_days: int
    timezones: dict[str, str]
    tenors: list[str]
    day_convention: str
    weekend_offset: int
    # Method
    basis_mode: str
    min_volume: float
    tau_log: float
    other_kind_weight: float
    shrink_k: float
    ewma_halflife_days: float
    max_anchor_dev: float
    hist_auto_min_obs: float
    corr_halflife_days: float
    corr_prior_obs: float
    cross_min_corr: float
    cross_min_obs: float
    cross_halflife_days: float
    warmup_days: int
    vwap_columns: dict[str, str]
    ratio_eex_floor: float = 1.0
    max_ratio_deviation: float = 1.0
    hist_max_age_days: int = 60
    fallback_price_method: str = "ewma"
    fallback_price_window: int = 5
    fallback_ewma_halflife: float = 2.0
    fallback_spread_window: int = 9
    fallback_anchor_months: int = 2
    shape_mode: str = "off"
    shape_adjust_originals: bool = False
    shape_smoothness_weight: float = 1.0
    shape_coherence_weight: float = 10.0
    shape_max_abs_adjustment: float = 10.0
    shape_original_weight: float = 10.0
    shape_coherence_tolerance: float = 0.01

    def tz(self, area: str) -> str:
        return self.timezones.get(area, self.timezones.get("default", "Europe/Berlin"))

    def resolve(self, p: str | Path) -> Path:
        p = Path(os.path.expandvars(os.path.expanduser(str(p))))
        return p if p.is_absolute() else (self.base_dir / p)


def validate_fallback_config(cfg: Config) -> None:
    """Validate the finite-window EEX transformation, including CLI overrides."""
    if cfg.fallback_price_method not in ("simple", "ewma"):
        raise ValueError("eex_fallback.price_method must be simple or ewma")
    for name, minimum in (("price_window", 2), ("spread_window", 2), ("anchor_months", 1)):
        value = getattr(cfg, f"fallback_{name}")
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(f"eex_fallback.{name} must be an integer >= {minimum}")
    half = cfg.fallback_ewma_halflife
    if (isinstance(half, bool) or not isinstance(half, (int, float))
            or not math.isfinite(half) or half <= 0):
        raise ValueError("eex_fallback.ewma_halflife must be a finite positive number")


def validate_shape_config(cfg: Config) -> None:
    """Validate optional shape controls without coercing strings or booleans."""
    if cfg.shape_mode not in ("off", "audit", "adjust"):
        raise ValueError("shape.mode must be off, audit or adjust")
    if not isinstance(cfg.shape_adjust_originals, bool):
        raise ValueError("shape.adjust_originals must be a boolean")
    for name in ("smoothness_weight", "coherence_weight", "max_abs_adjustment", "original_weight",
                 "coherence_tolerance"):
        value = getattr(cfg, f"shape_{name}")
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value)):
            raise ValueError(f"shape.{name} must be a finite number")
        if name in ("smoothness_weight", "coherence_weight", "coherence_tolerance") and value < 0:
            raise ValueError(f"shape.{name} must be >= 0")
        if name == "max_abs_adjustment" and value <= 0:
            raise ValueError("shape.max_abs_adjustment must be > 0")
        if name == "original_weight" and value < 1:
            raise ValueError("shape.original_weight must be >= 1")


def load_config(path: str | Path) -> Config:
    path = Path(path).resolve()
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    paths = raw.get("paths", {})
    layers = raw.get("layers", {})
    method = raw.get("method", {})
    conv = raw.get("conventions", {})
    eex = raw.get("eex", {})
    corr = raw.get("correlation", {})
    cross = raw.get("cross", {})
    fallback = raw.get("eex_fallback", {})
    shape = raw.get("shape", {})
    cfg = Config(
        base_dir=path.parent,
        vwap_input=paths.get("vwap_input", "data/vwaps.csv"),
        mapping_file=Path(), eex_curves_dir=Path(), output_dir=Path(),
        layer_local=bool(layers.get("local", True)),
        layer_correlation=bool(layers.get("correlation", False)),
        layer_cross=bool(layers.get("cross", False)),
        layer_hist=str(layers.get("hist", "auto")).lower(),
        layer_arbitrage=bool(layers.get("arbitrage", False)),
        max_stale_days=int(eex.get("max_stale_days", 0)) or None,
        warn_stale_days=int(eex.get("warn_stale_days", 3)),
        timezones=dict(raw.get("timezones", {"default": "Europe/Berlin"})),
        tenors=list(raw.get("targets", {}).get("tenors", [])),
        day_convention=conv.get("day", "calendar"),
        weekend_offset=int(conv.get("weekend_offset", 0)),
        basis_mode=method.get("basis_mode", "auto"),
        min_volume=float(method.get("min_volume", 0)),
        tau_log=float(method.get("tau_log", 0.5)),
        other_kind_weight=float(method.get("other_kind_weight", 0.6)),
        shrink_k=float(method.get("shrink_k", 1.0)),
        ewma_halflife_days=float(method.get("ewma_halflife_days", 10)),
        max_anchor_dev=float(method.get("max_anchor_dev", 0)),
        hist_auto_min_obs=float(method.get("hist_auto_min_obs", 10)),
        corr_halflife_days=float(corr.get("halflife_days", 20)),
        corr_prior_obs=float(corr.get("prior_obs", 8)),
        cross_min_corr=float(cross.get("min_corr", 0.5)),
        cross_min_obs=float(cross.get("min_obs", 8)),
        cross_halflife_days=float(cross.get("halflife_days", 20)),
        warmup_days=int(raw.get("run", {}).get("warmup_days", 0)),
        vwap_columns=dict(raw.get("vwap_columns", {})),
        ratio_eex_floor=float(method.get("ratio_eex_floor", 1.0)),
        max_ratio_deviation=float(method.get("max_ratio_deviation", 1.0)),
        hist_max_age_days=int(method.get("hist_max_age_days", 60)),
        fallback_price_method=fallback.get("price_method", "ewma"),
        fallback_price_window=fallback.get("price_window", 5),
        fallback_ewma_halflife=fallback.get("ewma_halflife", 2.0),
        fallback_spread_window=fallback.get("spread_window", 9),
        fallback_anchor_months=fallback.get("anchor_months", 2),
        shape_mode=shape.get("mode", "off"),
        shape_adjust_originals=shape.get("adjust_originals", False),
        shape_smoothness_weight=shape.get("smoothness_weight", 1.0),
        shape_coherence_weight=shape.get("coherence_weight", 10.0),
        shape_max_abs_adjustment=shape.get("max_abs_adjustment", 10.0),
        shape_original_weight=shape.get("original_weight", 10.0),
        shape_coherence_tolerance=shape.get("coherence_tolerance", 0.01),
    )
    cfg.mapping_file = cfg.resolve(paths.get("mapping", "mappings/products.csv"))
    cfg.eex_curves_dir = cfg.resolve(paths.get("eex_curves_dir", "../eex_scraper/output/curves/POWER"))
    cfg.output_dir = cfg.resolve(paths.get("output_dir", "output"))
    if cfg.basis_mode not in ("auto", "additive", "ratio"):
        raise ValueError(f"basis_mode must be auto, additive or ratio, not {cfg.basis_mode!r}")
    if cfg.day_convention not in ("calendar", "business"):
        raise ValueError(f"conventions.day must be calendar or business, not {cfg.day_convention!r}")
    if cfg.layer_hist not in ("on", "off", "auto"):
        raise ValueError(f"layers.hist must be on, off or auto, not {cfg.layer_hist!r}")
    if cfg.tau_log <= 0 or cfg.shrink_k <= 0 or cfg.ewma_halflife_days <= 0:
        raise ValueError("tau_log, shrink_k and ewma_halflife_days must be positive")
    if cfg.ratio_eex_floor <= 0 or cfg.max_ratio_deviation <= 0 or cfg.hist_max_age_days <= 0:
        raise ValueError("ratio_eex_floor, max_ratio_deviation and hist_max_age_days must be positive")
    if cfg.warmup_days < 0:
        raise ValueError("warmup_days must be >= 0; 0 replays all original history")
    validate_fallback_config(cfg)
    validate_shape_config(cfg)
    return cfg
