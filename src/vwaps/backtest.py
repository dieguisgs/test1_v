"""Backtest summaries."""

from __future__ import annotations

import pandas as pd

from vwaps.identity import IDENTITY_COLUMNS, normalize_identity


def _with_identity(frame: pd.DataFrame) -> pd.DataFrame:
    identity = normalize_identity(frame)
    return frame.assign(**{column: identity[column] for column in IDENTITY_COLUMNS})


def summarize_loo(loo: pd.DataFrame) -> pd.DataFrame:
    """Errors by unit/method/group and improvement over EEX on matching cases.

    A positive mae_improvement means the method improves on EEX. Columns
    ending in *_paired exclude cases where either prediction is unavailable.
    """
    if loo.empty:
        return loo
    loo = _with_identity(loo)
    report_keys = ["unit", "method", "group"]
    g = loo.groupby(report_keys)["error"]
    out = pd.DataFrame({
        "n": g.size(),
        "mae": g.apply(lambda e: e.abs().mean()),
        "bias": g.mean(),
        "rmse": g.apply(lambda e: (e**2).mean() ** 0.5),
    }).reset_index()
    tot = loo.groupby(["unit", "method"])["error"]
    allg = pd.DataFrame({
        "group": "ALL", "n": tot.size(), "mae": tot.apply(lambda e: e.abs().mean()),
        "bias": tot.mean(), "rmse": tot.apply(lambda e: (e**2).mean() ** 0.5),
    }).reset_index()
    report = pd.concat([allg, out], ignore_index=True)
    keys = ["reference_date", *IDENTITY_COLUMNS, "tenor"]
    if "scenario" in loo.columns:
        keys.append("scenario")
    baseline = loo.loc[loo["method"] == "eex", [*keys, "error"]].rename(
        columns={"error": "error_eex"})
    if baseline.duplicated(keys).any():
        raise ValueError("Backtest: multiple EEX predictions for the same observation")
    paired = loo.merge(baseline, on=keys, how="inner", validate="many_to_one")
    paired = paired.dropna(subset=["error", "error_eex"])
    paired = paired.assign(abs_error=paired["error"].abs(), abs_eex=paired["error_eex"].abs())
    paired = pd.concat([paired, paired.assign(group="ALL")], ignore_index=True)
    paired_report = paired.groupby(report_keys).agg(
        n_paired=("error", "size"), mae_paired=("abs_error", "mean"),
        mae_eex_paired=("abs_eex", "mean"),
    ).reset_index()
    paired_report["mae_improvement"] = paired_report["mae_eex_paired"] - paired_report["mae_paired"]
    report = report.merge(paired_report, on=report_keys, how="left", validate="one_to_one")
    report["n_paired"] = report["n_paired"].fillna(0).astype(int)
    return report.sort_values(["unit", "group", "mae"]).round(4)


def compare_truth(filled: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    """Compare prices with matching synthetic truth, grouped by unit/source."""
    t = _with_identity(truth.rename(columns={"date": "reference_date"}))
    filled = _with_identity(filled)
    keys = ["reference_date", *IDENTITY_COLUMNS, "tenor"]
    duplicate = t.duplicated(keys, keep=False)
    if duplicate.any():
        example = t.loc[duplicate, keys].iloc[0].to_dict()
        raise ValueError(
            f"Synthetic truth has duplicate keys ({example}). Older CSV files may "
            "contain conflicting truths for W+2; regenerate synthetic data in a new "
            "directory and use the VWAPs and truth from that same generation together.")
    period_keys = ["reference_date", *IDENTITY_COLUMNS, "delivery_start", "delivery_end"]
    if all(k in t.columns for k in period_keys):
        if (t.groupby(period_keys)["truth"].nunique(dropna=False) > 1).any():
            raise ValueError("Inconsistent synthetic truth: aliases for one delivery period have different prices")
    if filled.duplicated(keys).any():
        raise ValueError("Filled curve has duplicate date, product, region, unit and tenor keys")
    m = filled.merge(t[[*keys, "truth"]],
                     on=keys, how="inner", validate="one_to_one")
    m = m[m["source"] != "own"].dropna(subset=["price"])
    if m.empty:
        return m
    m["error"] = m["price"] - m["truth"]
    g = m.groupby(["unit", "source"])["error"]
    return pd.DataFrame({
        "n": g.size(), "mae": g.apply(lambda e: e.abs().mean()), "bias": g.mean(),
    }).reset_index().round(4)
