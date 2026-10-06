"""Command-line interface. See run.py for entry-point examples."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from dataclasses import asdict, replace
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from vwaps.backtest import compare_truth, summarize_loo
from vwaps.config import Config, load_config, validate_fallback_config
from vwaps.dates import parse_reference_dates
from vwaps.enrich import enrich_input
from vwaps.fill import CurveFiller
from vwaps.io_eex import EexBook
from vwaps.io_vwap import load_input
from vwaps.identity import CurveKey, IDENTITY_COLUMNS, curve_keys, normalize_identity
from vwaps.log import get_logger, setup_logging
from vwaps.mapping import (COLUMNS, ProductMap, check_mapping, eex_path, guess_row,
                           load_mapping, migrate_legacy_mapping)
from vwaps.synthetic import make_synthetic
from vwaps.tenors import parse_tenor, resolve_tenor

SOURCES = ["own", "eex+local", "eex+cross", "eex+hist", "eex+smooth", "eex", "arbitrage", "missing"]
KEYS = ["reference_date", *IDENTITY_COLUMNS]
ENRICHED_KEYS = [f"curve_{name}" for name in KEYS]


def main(argv: list[str], config_path: Path) -> int:
    ap = argparse.ArgumentParser(prog="run.py", description="Power curve filling: own VWAPs + EEX")
    ap.add_argument("--config", type=Path, default=config_path)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("mapping", help="create/update and validate the configured product mapping")
    p.add_argument("--vwap", default=None, help="VWAP file(s); override config.toml")

    p = sub.add_parser("daily", help="fill one reference date (default: today)")
    p.add_argument("--date", type=date.fromisoformat, default=None)
    p.add_argument("--vwap", default=None)

    p = sub.add_parser("refill", help="fill a historical date range")
    p.add_argument("--from", dest="start", type=date.fromisoformat, default=None)
    p.add_argument("--to", dest="end", type=date.fromisoformat, default=None)
    p.add_argument("--vwap", default=None)

    p = sub.add_parser("catchup", help="process pending date/curve groups through today")
    p.add_argument("--from", dest="start", type=date.fromisoformat, default=None)
    p.add_argument("--to", dest="end", type=date.fromisoformat, default=None)
    p.add_argument("--vwap", default=None)

    p = sub.add_parser("status", help="summarize the filled curve history")
    p.add_argument("--last", type=int, default=10, help="number of dates to display")

    p = sub.add_parser("backtest", help="leave-one-out prediction errors by method")
    p.add_argument("--from", dest="start", type=date.fromisoformat, default=None)
    p.add_argument("--to", dest="end", type=date.fromisoformat, default=None)
    p.add_argument("--vwap", default=None)
    p.add_argument("--truth", default=None, help="synthetic ground truth from make-synthetic")

    p = sub.add_parser("detect-conventions", help="compare D+n / WE+n conventions against EEX")
    p.add_argument("--vwap", default=None)

    p = sub.add_parser("tune", help="compare parameter combinations and validate the selected configuration on later dates")
    p.add_argument("--from", dest="start", type=date.fromisoformat, default=None)
    p.add_argument("--to", dest="end", type=date.fromisoformat, default=None)
    p.add_argument("--vwap", default=None)
    p.add_argument("--basis-modes", default="auto,ratio,additive", help="comma-separated calculation modes")
    p.add_argument("--tau-log", default=None, help="comma-separated positive anchor-distance parameters; default: configured value")
    p.add_argument("--shrink-k", default=None, help="comma-separated positive shrinkage parameters; default: configured value")
    p.add_argument("--hist-modes", default=None, help="comma-separated on/off/auto; default: configured value")
    p.add_argument("--correlation", default=None, help="comma-separated off/on; default: configured value")
    p.add_argument("--cross", default=None, help="comma-separated off/on; default: configured value")
    p.add_argument("--validation-days", type=int, default=20,
                   help="number of latest distinct observation dates reserved for validation")
    p.add_argument("--max-trials", type=int, default=50, help="maximum number of parameter combinations")

    p = sub.add_parser("make-synthetic", help="generate synthetic VWAPs from EEX for testing")
    p.add_argument("--areas", default="DE,FR,NL,AT", help="comma-separated areas")
    p.add_argument("--profiles", default="Base,Peak")
    p.add_argument("--from", dest="start", type=date.fromisoformat, default=date(2000, 1, 1))
    p.add_argument("--to", dest="end", type=date.fromisoformat, default=date(2100, 1, 1))
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--mode", choices=["ratio", "additive"], default="ratio",
                   help="how to generate the VWAP-EEX difference (controls synthetic model bias)")
    p.add_argument("--out", default="data")

    for command in ("daily", "refill", "catchup", "backtest", "tune"):
        parser = sub.choices[command]
        group = parser.add_argument_group("EEX fallback transformation (override config for this run)")
        group.add_argument("--eex-price-method", dest="fallback_price_method", choices=("simple", "ewma"),
                           default=None, help="finite-window price average: equal or exponential weights")
        group.add_argument("--eex-price-window", dest="fallback_price_window", type=int, default=None,
                           help="complete price window in EEX publication dates, at least 2")
        group.add_argument("--eex-ewma-halflife", dest="fallback_ewma_halflife", type=float, default=None,
                           help="positive exponential weight half-life in observations within the price window")
        group.add_argument("--eex-spread-window", dest="fallback_spread_window", type=int, default=None,
                           help="complete simple-average monthly spread window, at least 2 dates")
        group.add_argument("--eex-anchor-months", dest="fallback_anchor_months", type=int, default=None,
                           help="directly averaged months from the current calendar month, at least 1")

    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    setup_logging(cfg.output_dir / "_logs", " ".join(["run.py", *argv]))
    try:
        overrides = {name: getattr(a, name) for name in (
            "fallback_price_method", "fallback_price_window", "fallback_ewma_halflife",
            "fallback_spread_window", "fallback_anchor_months",
        ) if getattr(a, name, None) is not None}
        cfg = replace(cfg, **overrides)
        validate_fallback_config(cfg)
        return {
            "mapping": cmd_mapping, "daily": cmd_daily, "refill": cmd_refill,
            "catchup": cmd_catchup, "status": cmd_status,
            "backtest": cmd_backtest, "detect-conventions": cmd_detect,
            "make-synthetic": cmd_synthetic,
            "tune": cmd_tune,
        }[a.cmd](cfg, a)
    except (FileNotFoundError, ValueError) as exc:
        get_logger().error(str(exc))
        return 1


# ---------------------------------------------------------------- helpers
def _out(*parts) -> None:
    get_logger().info(" ".join(str(p) for p in parts))


def _table(df: pd.DataFrame, index: bool = False) -> str:
    with pd.option_context("display.max_rows", 500, "display.width", 250,
                           "display.max_colwidth", 60):
        return df.to_string(index=index)


def _books(cfg: Config, maps: list[ProductMap]) -> dict[CurveKey, EexBook | None]:
    books: dict[CurveKey, EexBook | None] = {}
    cache: dict[Path, EexBook | None] = {}
    for m in maps:
        if not m.active:
            continue
        path = eex_path(cfg, m)
        if path is None:
            get_logger().warning(f"{m.label}: no EEX mapping -> own VWAPs "
                                 f"(contract reconstruction enabled: {cfg.layer_arbitrage})")
            books[m.key] = None
            continue
        if path in cache:
            books[m.key] = cache[path]
            continue
        try:
            books[m.key] = EexBook.from_file(path)
        except FileNotFoundError:
            get_logger().error(f"{m.product}: EEX file {path} does not exist -> no EEX "
                               f"(check eex_file in {cfg.mapping_file.name})")
            books[m.key] = None
        except Exception as exc:
            get_logger().error(f"{m.product}: cannot read {path}: {exc} -> no EEX")
            books[m.key] = None
        cache[path] = books[m.key]
    return books


def _load(cfg: Config, override: str | None):
    """Load VWAPs, original rows, mapping and EEX; report unmatched products."""
    vw, raw = load_input(override or cfg.vwap_input, cfg)
    maps = load_mapping(cfg)
    known = {m.key for m in maps}
    new = sorted(set(curve_keys(raw, cfg)) - known)
    if new:
        get_logger().warning(f"{len(new)} input curves are not mapped (preserved in enriched output; "
                             f"add them with `python run.py mapping`): {new[:10]}"
                             + (" ..." if len(new) > 10 else ""))
    fill = [m.key for m in maps if m.active and m.use == "fill"]
    helpers = [m.key for m in maps if m.active and m.use == "helper"]
    _out(f"Curves to fill: {len(fill)}" + (f" | helpers: {len(helpers)}" if helpers else ""))
    active = {m.key for m in maps if m.active}
    vw = vw[curve_keys(vw).isin(active)].reset_index(drop=True)
    return vw, raw, maps, _books(cfg, maps)


def _upsert(path: Path, new: pd.DataFrame, replaced_groups: pd.DataFrame | None = None) -> None:
    if new.empty and (replaced_groups is None or replaced_groups.empty):
        return
    if new.empty and not path.exists():
        return  # No prior rows or column schema to preserve.
    replaced = new[KEYS] if replaced_groups is None else replaced_groups[KEYS]
    if path.exists():
        _validate_output_schema(path, KEYS)
        old = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
        if "product" in old.columns:
            old["reference_date"] = pd.to_datetime(old["reference_date"]).dt.date
            done = set(map(tuple, replaced.drop_duplicates().to_numpy()))
            old = old.loc[[tuple(r) not in done for r in old[KEYS].to_numpy()]]
            new = pd.concat([old, new], ignore_index=True) if not new.empty else old
    path.parent.mkdir(parents=True, exist_ok=True)
    new.sort_values(KEYS + ["delivery_start"] if "delivery_start" in new else KEYS).to_csv(
        path, index=False, encoding="utf-8-sig")


def _require_complete(res) -> None:
    if res.errors:
        products = ", ".join(sorted({error["product"] for error in res.errors}))
        raise ValueError(f"Incomplete run: {len(res.errors)} errors in {products}. "
                         "No results written; check the log and run again.")


def _merge_enriched(path: Path, new: pd.DataFrame) -> None:
    """Replace date/curve groups without aggregating or sorting original rows."""
    keys = ENRICHED_KEYS
    if path.exists():
        _validate_output_schema(path, keys)
        # Read text to preserve identifiers such as 001 when rewriting
        # earlier dates that are outside the current run.
        old = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
        old["curve_reference_date"] = pd.to_datetime(old["curve_reference_date"]).dt.date
        done = set(map(tuple, new[keys].drop_duplicates().to_numpy()))
        old = old[[tuple(row) not in done for row in old[keys].to_numpy()]]
        new = pd.concat([old, new], ignore_index=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    new.to_csv(path, index=False, encoding="utf-8-sig")


def _validate_output_schema(path: Path, keys: list[str]) -> None:
    """Reject ambiguous legacy histories before any result files are written."""
    if not path.exists():
        return
    columns = pd.read_csv(path, encoding="utf-8-sig", nrows=0).columns
    missing = [key for key in keys if key not in columns]
    if missing:
        raise ValueError(f"Legacy output {path} lacks curve identity columns {missing}. "
                         "Set paths.output_dir to a new directory and run refill to rebuild "
                         "with product, region and unit. No result files written.")


def _write(cfg: Config, res, enriched: pd.DataFrame) -> None:
    _require_complete(res)
    out = cfg.output_dir
    for name in ("filled_history.csv", "consistency_history.csv"):
        _validate_output_schema(out / name, KEYS)
    _validate_output_schema(out / "enriched_history.csv", ENRICHED_KEYS)
    if not res.filled.empty:
        for day in res.filled["reference_date"].unique():
            _validate_output_schema(out / "filled" / f"{day}.csv", KEYS)
    if not enriched.empty:
        for day in enriched["curve_reference_date"].unique():
            _validate_output_schema(out / "enriched" / f"{day}.csv", ENRICHED_KEYS)
    (out / "filled").mkdir(parents=True, exist_ok=True)
    groups = res.filled.groupby("reference_date") if not res.filled.empty else []
    for day, g in groups:
        f = out / "filled" / f"{day}.csv"
        if f.exists():  # Preserve curves that were not recalculated on this date.
            old = pd.read_csv(f, encoding="utf-8-sig", dtype=str, keep_default_na=False)
            if "product" in old.columns:
                old = old[~curve_keys(old).isin(set(curve_keys(g)))]
                g = pd.concat([old, g], ignore_index=True)
        g.to_csv(f, index=False, encoding="utf-8-sig")
    _upsert(out / "filled_history.csv", res.filled)
    recalculated = res.filled[KEYS] if not res.filled.empty else None
    _upsert(out / "consistency_history.csv", res.consistency, recalculated)
    if not enriched.empty:
        for day, g in enriched.groupby("curve_reference_date", sort=False):
            _merge_enriched(out / "enriched" / f"{day}.csv", g)
        _merge_enriched(out / "enriched_history.csv", enriched)


def _print_summary(filled: pd.DataFrame) -> None:
    if filled.empty:
        _out("No curve points to fill in this range.")
        return
    n_prod = len(set(curve_keys(filled)))
    n_days = filled["reference_date"].nunique()
    # Summarize by product for large runs; daily details remain in filled_history.csv / status.
    index = IDENTITY_COLUMNS if n_prod > 1 and n_days > 1 else KEYS
    t = filled.pivot_table(index=index, columns="source", values="tenor", aggfunc="count", fill_value=0)
    t = t.reindex(columns=[s for s in SOURCES if s in t.columns])
    if "missing" in t.columns:
        t["% missing"] = (100 * t["missing"] / t.sum(axis=1)).round(1)
    _out(_table(t, index=True))
    miss = filled[filled["source"] == "missing"]
    if not miss.empty:
        by = miss.groupby("tenor").size().sort_values(ascending=False)
        _out("\nUnfilled tenors (cells): " + ", ".join(f"{k}={v}" for k, v in by.items()))
    n = len(filled)
    _out(f"\n{n} cells | " + " | ".join(
        f"{s} {100 * (filled['source'] == s).sum() / n:.1f}%" for s in SOURCES
        if (filled['source'] == s).any()))


def _layers(cfg: Config) -> str:
    on = [n for n, v in [("local", cfg.layer_local), ("correlation", cfg.layer_correlation),
                         ("cross", cfg.layer_cross), ("arbitrage", cfg.layer_arbitrage)] if v]
    return f"Layers: {', '.join(on)} | hist={cfg.layer_hist} | mode={cfg.basis_mode}"


# --------------------------------------------------------------- commands
def cmd_mapping(cfg: Config, a) -> int:
    """Append exact curve identities while preserving manual mapping choices."""
    vw, raw = load_input(a.vwap or cfg.vwap_input, cfg)
    identities = normalize_identity(raw, cfg).drop_duplicates()
    products = sorted(set(curve_keys(identities)))
    path = cfg.mapping_file
    migrated = False
    if path.exists():
        cur = pd.read_csv(path, dtype=str, encoding="utf-8-sig", keep_default_na=False)
        migrated = any(name not in cur for name in IDENTITY_COLUMNS)
        cur = migrate_legacy_mapping(cur, identities)
    else:
        cur = pd.DataFrame(columns=COLUMNS)
    if "comment" not in cur:
        cur["comment"] = ""
    new = [p for p in products if p not in set(curve_keys(cur))]
    if new:
        cur = pd.concat([cur, pd.DataFrame([
            guess_row(p, cfg, region=r, unit=u) for p, r, u in new])], ignore_index=True)
    if new or migrated:
        path.parent.mkdir(parents=True, exist_ok=True)
        cur[COLUMNS].to_csv(path, index=False, encoding="utf-8-sig")
        _out(f"{len(new)} new curves added to {path} (draft: review these entries)"
             + ("; legacy mapping migrated to product/region/unit" if migrated else ""))
    else:
        _out(f"{path}: no new curves")
    maps = load_mapping(cfg)
    chk = check_mapping(maps, cfg, vw)
    _out("\n" + _table(chk))
    gone = [m.label for m in maps if m.key not in set(products)]
    if gone:
        get_logger().warning(f"Mapped but absent from the VWAP input: {', '.join(gone)}")
    bad = chk[(chk["use"] != "off") & (chk["eex"] == "MISSING")]
    if not bad.empty:
        get_logger().error(f"{len(bad)} products refer to a missing EEX file")
    _out("\nReview the mapping (use = fill / helper / off, eex_file, hours, timezone), then run "
         "`python run.py mapping` again to validate it.")
    return 0


def cmd_refill(cfg: Config, a) -> int:
    vw, raw, maps, books = _load(cfg, a.vwap)
    eex_dates = [d for b in books.values() if b for d in b.trade_dates]
    date_col = cfg.vwap_columns.get("reference_date", "reference_date")
    dates = list(parse_reference_dates(raw[date_col]).dt.date) + eex_dates
    if not dates and (a.start is None or a.end is None):
        raise ValueError("No input or EEX dates available; specify --from and --to")
    start = a.start or min(dates)
    end = a.end or max(dates)
    first_eex = min(eex_dates) if eex_dates else None
    _out(f"Refill {start} -> {end} | VWAPs: {len(vw)} rows | EEX starts on {first_eex}")
    _out(_layers(cfg))
    if first_eex and start < first_eex:
        get_logger().warning(f"no EEX before {first_eex}: those dates use own VWAPs "
                             f"(contract reconstruction enabled: {cfg.layer_arbitrage})")
    res = CurveFiller(cfg, vw, maps, books).run(start, end)
    _require_complete(res)
    enriched = enrich_input(raw, res.filled, cfg, maps, start, end)
    _write(cfg, res, enriched)
    _print_summary(res.filled)
    _out(f"\nWritten to {cfg.output_dir}")
    return 0


def cmd_daily(cfg: Config, a) -> int:
    day = a.date or date.today()
    vw, raw, maps, books = _load(cfg, a.vwap)
    _out(_layers(cfg))
    if not (vw["date"] == day).any():
        get_logger().warning(f"no own VWAPs on {day}: using EEX and available historical adjustments")
    res = CurveFiller(cfg, vw, maps, books).run(day, day)
    _require_complete(res)
    enriched = enrich_input(raw, res.filled, cfg, maps, day, day)
    _write(cfg, res, enriched)
    _print_summary(res.filled)
    _out(f"\nWritten to {cfg.output_dir} (curve and enriched original rows)")
    return 0


def _history_point_keys(path: Path, enriched: bool = False) -> set[tuple]:
    """Presence means processed, including rows whose price is missing."""
    if not path.exists():
        return set()
    prefix = "curve_" if enriched else ""
    columns = [f"{prefix}{name}" for name in [*KEYS, "tenor"]]
    _validate_output_schema(path, columns)
    frame = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False,
                        usecols=columns)
    frame = frame.rename(columns={column: column.removeprefix(prefix) for column in columns}) if prefix else frame
    dates = pd.to_datetime(frame["reference_date"], format="mixed", errors="coerce").dt.date
    if dates.isna().any():
        raise ValueError(f"Output history {path} contains empty or invalid reference dates")
    return {(day, *curve, str(tenor).strip())
            for day, curve, tenor in zip(dates, curve_keys(frame), frame["tenor"])}


def cmd_catchup(cfg: Config, a) -> int:
    """Fill pending date/curve groups while replaying all original history."""
    end = a.end or date.today()
    if end > date.today():
        raise ValueError("catchup --to cannot be later than today")
    if a.start is not None and a.start > end:
        raise ValueError("The start date cannot be later than the end date")
    _validate_output_schema(cfg.output_dir / "consistency_history.csv", KEYS)
    completed_filled = _history_point_keys(cfg.output_dir / "filled_history.csv")
    completed_enriched = _history_point_keys(cfg.output_dir / "enriched_history.csv", enriched=True)
    vw, raw, maps, books = _load(cfg, a.vwap)
    outputs = [m for m in maps if m.active and m.use == "fill"]
    if not outputs:
        _out("Catchup: no active fill curves with an assigned EEX path; nothing to process.")
        return 0
    date_col = cfg.vwap_columns.get("reference_date", "reference_date")
    raw_dates = parse_reference_dates(raw[date_col]).dt.date
    eex_dates = {day for book in books.values() if book is not None for day in book.trade_dates}
    available_dates = set(raw_dates) | eex_dates
    if a.start is None and not available_dates:
        raise ValueError("No input or EEX dates are available; specify catchup --from")
    start = a.start if a.start is not None else min(available_dates)
    if start > end:
        raise ValueError("The start date cannot be later than the end date")

    active = {m.key for m in maps if m.active}
    observed_dates = set(raw_dates[curve_keys(raw, cfg).isin(active)]) | eex_dates
    days = {day for day in observed_dates if start <= day <= end}
    days.update(start + timedelta(days=offset) for offset in range((end - start).days + 1)
                if (start + timedelta(days=offset)).weekday() < 5)
    pending: set[tuple[date, CurveKey]] = set()
    for day in sorted(days):
        targets = [label for label in dict.fromkeys(cfg.tenors)
                   if resolve_tenor(label, day, cfg.day_convention, cfg.weekend_offset) is not None]
        for m in outputs:
            if any((day, *m.key, tenor) not in completed_filled
                   or (day, *m.key, tenor) not in completed_enriched for tenor in targets):
                pending.add((day, m.key))
    if not pending:
        _out(f"Catchup {start} -> {end}: all resolvable targets are already present in both histories.")
        return 0

    for day in {day for day, _ in pending}:
        _validate_output_schema(cfg.output_dir / "filled" / f"{day}.csv", [*KEYS, "tenor"])
        _validate_output_schema(cfg.output_dir / "enriched" / f"{day}.csv", [*ENRICHED_KEYS, "curve_tenor"])
    _out(f"Catchup {start} -> {end}: {len(pending)} pending date/curve groups; completed groups are preserved.")
    _out(_layers(cfg))
    res = CurveFiller(cfg, vw, maps, books).run(start, end, output_keys=pending)
    _require_complete(res)
    # Retain all originals when deriving metadata; write only selected groups.
    enriched = enrich_input(raw, res.filled, cfg, maps, start, end)
    selected = {(day, *curve) for day, curve in pending}
    enriched = enriched.loc[[tuple(row) in selected
                             for row in enriched[ENRICHED_KEYS].itertuples(index=False, name=None)]].reset_index(drop=True)
    _write(cfg, res, enriched)
    _print_summary(res.filled)
    _out(f"\nWritten pending groups to {cfg.output_dir}")
    return 0


def cmd_status(cfg: Config, a) -> int:
    path = cfg.output_dir / "filled_history.csv"
    if not path.exists():
        _out(f"No filled history yet ({path}). Run refill first.")
        return 1
    _validate_output_schema(path, KEYS)
    h = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    days = sorted(h["reference_date"].unique())
    _out(f"{path}\n{len(days)} dates: {days[0]} -> {days[-1]} | {len(set(curve_keys(h)))} curves\n")
    last = h[h["reference_date"].isin(days[-a.last:])]
    t = last.pivot_table(index="reference_date", columns="source", values="tenor",
                         aggfunc="count", fill_value=0)
    _out(_table(t.reindex(columns=[s for s in SOURCES if s in t.columns]), index=True))
    d0, d1 = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
    have = set(days)
    gaps = [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]
    gaps = [d for d in gaps if d.weekday() < 5 and d.isoformat() not in have]
    if gaps:
        _out(f"\nUnfilled weekdays: {', '.join(map(str, gaps))}")
    return 0


def cmd_backtest(cfg: Config, a) -> int:
    vw, _, maps, books = _load(cfg, a.vwap)
    if vw.empty:
        raise ValueError("No valid VWAPs from active products are available for backtesting")
    start = a.start or min(vw["date"])
    end = a.end or max(vw["date"])
    res = CurveFiller(cfg, vw, maps, books).run(start, end, loo=True)
    _require_complete(res)
    if res.loo.empty:
        _out("No VWAPs with matching EEX in this range: nothing to evaluate.")
        return 1
    rep = summarize_loo(res.loo)
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    res.loo.to_csv(cfg.output_dir / "backtest_loo.csv", index=False, encoding="utf-8-sig")
    rep.to_csv(cfg.output_dir / "backtest_report.csv", index=False, encoding="utf-8-sig")
    _out("Leave-one-out: hide each own VWAP and predict it from the remaining observations (error = pred - own)\n")
    _out(_table(rep))
    if a.truth:
        truth = pd.read_csv(cfg.resolve(a.truth), encoding="utf-8-sig", keep_default_na=False,
                            dtype={name: str for name in IDENTITY_COLUMNS})
        truth["date"] = pd.to_datetime(truth["date"]).dt.date
        _out("\nFilled curve vs synthetic ground truth (cells without own VWAPs):\n")
        _out(_table(compare_truth(res.filled, truth)))
    return 0


def _grid_values(value: str | None, default, *, allowed=None, numeric=False) -> list:
    """Parse explicit trial values without accepting empty or invalid options."""
    if value is None:
        return [default]
    values = [part.strip() for part in value.split(",")]
    if not values or any(not part for part in values):
        raise ValueError("Parameter grids require nonempty comma-separated values")
    if numeric:
        values = [float(part) for part in values]
        if any(not math.isfinite(number) or number <= 0 for number in values):
            raise ValueError("tau-log and shrink-k grid values must be positive and finite")
    elif allowed is not None and any(part not in allowed for part in values):
        raise ValueError(f"Grid values must be selected from {', '.join(allowed)}")
    return list(dict.fromkeys(values))


def _json_finite(value):
    """Keep audit JSON standards-compliant when a diagnostic is unavailable."""
    if isinstance(value, dict):
        return {key: _json_finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_finite(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def cmd_tune(cfg: Config, a) -> int:
    """Write evaluation reports without changing the production configuration."""
    from vwaps.tuning import tune_parameters

    grid = {
        "basis_mode": _grid_values(a.basis_modes, cfg.basis_mode, allowed=("auto", "ratio", "additive")),
        "tau_log": _grid_values(a.tau_log, cfg.tau_log, numeric=True),
        "shrink_k": _grid_values(a.shrink_k, cfg.shrink_k, numeric=True),
        "layer_hist": _grid_values(a.hist_modes, cfg.layer_hist, allowed=("auto", "on", "off")),
        "layer_correlation": [item == "on" for item in _grid_values(
            a.correlation, "on" if cfg.layer_correlation else "off", allowed=("off", "on"))],
        "layer_cross": [item == "on" for item in _grid_values(
            a.cross, "on" if cfg.layer_cross else "off", allowed=("off", "on"))],
    }
    vw, _, maps, books = _load(cfg, a.vwap)
    if vw.empty:
        raise ValueError("No valid original observations are available for parameter evaluation")
    result = tune_parameters(cfg, vw, maps, books, a.start or min(vw["date"]),
                             a.end or max(vw["date"]), grid, a.validation_days, a.max_trials)
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    result.calibration_report.to_csv(cfg.output_dir / "tuning_calibration.csv", index=False, encoding="utf-8-sig")
    result.validation_report.to_csv(cfg.output_dir / "tuning_validation.csv", index=False, encoding="utf-8-sig")
    selected = result.selected_config
    patch = {
        "method": {name: selected[name] for name in ("basis_mode", "tau_log", "shrink_k")},
        "layers": {name.removeprefix("layer_"): selected[name]
                   for name in ("layer_hist", "layer_correlation", "layer_cross")},
    }
    report = {"selected_parameters": patch, "metadata": result.metadata,
              "base_configuration": asdict(cfg), "input_pattern": a.vwap or cfg.vwap_input,
              "selection": "Calibration dates only; validation dates are evaluated after selection.",
              "config_changed": False}
    (cfg.output_dir / "tuning_selected.json").write_text(
        json.dumps(_json_finite(report), indent=2, ensure_ascii=False, allow_nan=False, default=str), encoding="utf-8")
    _out("Selected parameters (configuration unchanged):\n" + json.dumps(patch, indent=2))
    _out("Later-date validation:\n" + _table(result.validation_report))
    _out(f"Reports written to {cfg.output_dir}: tuning_calibration.csv, tuning_validation.csv, tuning_selected.json")
    return 0


def cmd_detect(cfg: Config, a) -> int:
    vw, _, maps, books = _load(cfg, a.vwap)
    rows = vw[vw["tenor"].map(lambda t: (parse_tenor(t) or ("",))[0] in ("D", "WE"))]
    _out("Difference |VWAP - EEX| for D+n and WE+n by convention (lower means a closer match)\n")
    for conv in ("calendar", "business"):
        for off in (0, 1):
            diffs: dict[str, dict[str, list[float]]] = {}
            for product, g in rows.groupby(curve_keys(rows)):
                book = books.get(product)
                if book is None:
                    continue
                unit_diffs = diffs.setdefault(product[2], {"D": [], "WE": []})
                for d, t, v in g[["date", "tenor", "vwap"]].itertuples(index=False):
                    per = resolve_tenor(t, d, conv, off)
                    q, asof = book.quotes(d, 0)  # Same-day settlements only.
                    if per is None or asof is None or per.key not in q:
                        continue
                    unit_diffs[parse_tenor(t)[0]].append(abs(v - q[per.key]))
            for unit, terms in sorted(diffs.items()):
                cells = [f"{k}: n={len(x):4d} median={statistics.median(x):7.2f}" if x else f"{k}: n=   0"
                         for k, x in terms.items()]
                _out(f"unit={unit!r} day={conv:8s} weekend_offset={off}  |  " + "  |  ".join(cells))
            if not diffs:
                _out(f"day={conv:8s} weekend_offset={off}  |  no comparable curves")
    return 0


def cmd_synthetic(cfg: Config, a) -> int:
    maps = []
    for area in [x.strip() for x in a.areas.split(",") if x.strip()]:
        for profile in [x.strip() for x in a.profiles.split(",") if x.strip()]:
            r = guess_row(f"{area}_{profile} load", cfg,
                          unit="GBP/MWh" if area == "GB" else "EUR/MWh")
            if r["eex_file"]:
                r["use"] = "fill"  # Temporary synthetic-generation map; persisted drafts stay off.
                maps.append(ProductMap(**r))
    books = _books(cfg, maps)
    maps = [m for m in maps if books.get(m.key) is not None]
    if not maps:
        _out("No EEX curves are available for synthetic generation.")
        return 1
    v, t = make_synthetic(cfg, maps, books, a.start, a.end, seed=a.seed, mode=a.mode)
    out = cfg.resolve(a.out)
    out.mkdir(parents=True, exist_ok=True)
    v.to_csv(out / "synthetic_vwaps.csv", index=False, encoding="utf-8-sig")
    t.to_csv(out / "synthetic_truth.csv", index=False, encoding="utf-8-sig")
    _out(f"{len(v)} synthetic VWAPs across {len(maps)} products -> {out / 'synthetic_vwaps.csv'} "
         f"(+ synthetic_truth.csv)")
    return 0
