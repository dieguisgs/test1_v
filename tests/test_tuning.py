"""Parameter selection uses comparable earlier observations, never holdout fit."""

from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from vwaps.config import load_config
from vwaps.fill import CurveFiller
from vwaps.io_eex import EexBook, REQUIRED
from vwaps.mapping import ProductMap
from vwaps.tuning import tune_parameters


@pytest.fixture
def dataset(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text("", encoding="utf-8")
    cfg = replace(load_config(config), tenors=["M+1", "M+2", "M+3"], tau_log=10.0,
                  shrink_k=0.01, layer_hist="off", layer_arbitrage=False)
    days = list(pd.bdate_range("2026-09-01", periods=12).date)
    mapping = ProductMap("P", "fill", "DE", "Base", "fixture.csv", "Base", "Europe/Berlin",
                         region="North", unit="EUR/MWh")
    own, settlements = [], []
    for i, day in enumerate(days):
        for n in (1, 2, 3):
            eex = n * (100.0 + i)
            own.append(dict(date=day, product="P", region="North", unit="EUR/MWh",
                            tenor=f"M+{n}", vwap=eex + 10.0, volume=100.0))
            settlements.append((day, "Month", date(2026, 9 + n, 1), eex))
    frame = pd.DataFrame(own)
    books = {mapping.key: EexBook(pd.DataFrame(settlements, columns=REQUIRED))}
    return cfg, frame, [mapping], books, days


def tune(dataset, grid=None, **kwargs):
    cfg, own, maps, books, days = dataset
    return tune_parameters(cfg, own, maps, books, days[0], days[-1],
                           grid or {"basis_mode": ["auto", "ratio", "additive"]},
                           kwargs.get("validation_days", 3), kwargs.get("max_trials", 50))


def test_real_engine_selects_additive_on_calibration_and_evaluates_only_winner(dataset, monkeypatch):
    cfg, own, _, _, days = dataset
    input_before = own.copy(deep=True)
    config_before = cfg.__dict__.copy()
    calls = []
    original = CurveFiller.run

    def counted(self, start, end, loo=False):
        calls.append((self.cfg.basis_mode, start, end, loo))
        return original(self, start, end, loo=loo)

    monkeypatch.setattr(CurveFiller, "run", counted)
    result = tune(dataset)
    assert result.selected_config["basis_mode"] == "additive"
    assert calls == [(mode, days[0], days[8], True) for mode in ("auto", "ratio", "additive")] + [
        ("additive", days[9], days[-1], True),
    ]
    assert result.metadata["calibration_days"] == 9 and result.metadata["validation_days"] == 3
    assert result.metadata["calibration_n_paired"] == 27
    assert result.metadata["validation_n_paired"] == 9
    assert result.metadata["validation_score"] < 0.01
    validation = result.validation_report.set_index("scope")
    assert validation.loc["unit", "unit"] == "EUR/MWh"
    assert validation.loc["unit", "mae_eex"] == pytest.approx(10.0)
    assert validation.loc["unit", "rmse_model"] >= validation.loc["unit", "mae_model"]
    assert pd.isna(validation.loc["overall", "mae_model"])
    assert cfg.__dict__ == config_before
    pd.testing.assert_frame_equal(own, input_before)


def test_changing_holdout_truth_cannot_change_selection_or_calibration_report(dataset):
    first = tune(dataset)
    cfg, own, maps, books, days = dataset
    altered = own.copy(deep=True)
    later = altered["date"].isin(days[-3:])
    altered.loc[later, "vwap"] = (altered.loc[later, "vwap"] - 10) * 1.1
    second = tune((cfg, altered, maps, books, days))
    assert second.selected_config == first.selected_config
    pd.testing.assert_frame_equal(second.calibration_report, first.calibration_report)
    assert second.metadata["validation_score"] != pytest.approx(first.metadata["validation_score"])


def test_zero_observed_prices_are_valid_real_engine_backtest_cases(dataset):
    cfg, own, maps, books, days = dataset
    zero = own.assign(vwap=0.0)
    result = tune((cfg, zero, maps, books, days), {"basis_mode": ["auto", "additive"]})
    assert result.metadata["calibration_n_paired"] == 27
    assert result.metadata["validation_n_paired"] == 9
    assert 0 <= result.metadata["validation_score"] < float("inf")


def test_unmapped_later_observations_do_not_define_holdout_dates(dataset):
    cfg, own, maps, books, days = dataset
    later = date(2026, 10, 1)
    unmapped = own.iloc[[0]].assign(date=later, product="UNMAPPED")
    frame = pd.concat([own, unmapped], ignore_index=True)
    result = tune((cfg, frame, maps, books, [*days, later]))
    assert result.metadata["validation_end"] == days[-1].isoformat()
    assert result.metadata["validation_days"] == 3


def test_cartesian_grid_reports_every_parameter_and_stable_tie(dataset):
    result = tune(dataset, {"basis_mode": ["auto", "ratio"], "tau_log": [1.0, 2.0],
                            "shrink_k": [0.5, 1.0]})
    overall = result.calibration_report[result.calibration_report["scope"] == "overall"]
    assert len(overall) == result.metadata["n_trials"] == 8
    assert len(overall[["basis_mode", "tau_log", "shrink_k"]].drop_duplicates()) == 8
    assert set(result.selected_config) == {
        "basis_mode", "tau_log", "shrink_k", "layer_hist", "layer_correlation", "layer_cross",
    }
    assert result.selected_config["basis_mode"] == "auto"  # Same predictions as ratio on this data.


@pytest.mark.parametrize("grid,max_trials,match", [
    ({"basis_mode": []}, 50, "nonempty"),
    ({"basis_mode": ["unknown"]}, 50, "basis_mode"),
    ({"tau_log": [0]}, 50, "finite positive"),
    ({"shrink_k": [float("nan")]}, 50, "finite positive"),
    ({"layer_hist": ["maybe"]}, 50, "layer_hist"),
    ({"layer_cross": ["true"]}, 50, "booleans"),
    ({"tenors": [[]]}, 50, "Unsupported"),
    ({"basis_mode": ["auto", "ratio", "additive"], "tau_log": [1, 2]}, 5, "6 trials"),
])
def test_invalid_or_oversized_grid_fails_before_running_engine(dataset, monkeypatch, grid, max_trials, match):
    def forbidden(*args, **kwargs):
        pytest.fail("The engine must not run for an invalid search space")

    monkeypatch.setattr(CurveFiller, "run", forbidden)
    with pytest.raises(ValueError, match=match):
        tune(dataset, grid, max_trials=max_trials)


@pytest.mark.parametrize("validation_days", [0, 11, 12, 20])
def test_split_requires_two_calibration_days_and_positive_holdout(dataset, validation_days):
    with pytest.raises(ValueError, match="validation_days"):
        tune(dataset, validation_days=validation_days)


def test_limited_warmup_is_rejected_without_mutating_config(dataset):
    cfg, *rest = dataset
    limited = replace(cfg, warmup_days=5)
    with pytest.raises(ValueError, match="warmup_days = 0"):
        tune((limited, *rest))
    assert limited.warmup_days == 5


def test_calibration_requires_two_dates_with_actual_pairs(dataset, monkeypatch):
    monkeypatch.setattr(CurveFiller, "run", lambda self, start, end, loo=False:
                        SimpleNamespace(errors=[], loo=fake_loo(start, start, 1.0, 2.0)))
    with pytest.raises(ValueError, match="two dates with paired"):
        tune(dataset)


def test_missing_holdout_contract_coverage_fails_before_trying_candidates(dataset, monkeypatch):
    cfg, own, maps, _, days = dataset
    def forbidden(*args, **kwargs):
        pytest.fail("No models should run without holdout EEX coverage")

    monkeypatch.setattr(CurveFiller, "run", forbidden)
    with pytest.raises(ValueError, match="No holdout observations match"):
        tune((cfg, own, maps, {maps[0].key: None}, days))


def fake_loo(start, end, model_error, baseline_error, units=("EUR/MWh",)):
    rows = []
    for day in pd.bdate_range(start, end).date:
        for unit in units:
            for method, error in (("pipeline_configured", model_error), ("eex", baseline_error)):
                rows.append(dict(reference_date=day, product="P", region="North", unit=unit,
                                 tenor="M+1", method=method, own=0.0, pred=error))
    return pd.DataFrame(rows)


@pytest.mark.parametrize("model_error,expected", [(0.0, 1.0), (1.0, float("inf"))])
def test_zero_baseline_and_zero_observed_price_have_defined_scores(dataset, monkeypatch, model_error, expected):
    monkeypatch.setattr(CurveFiller, "run", lambda self, start, end, loo=False:
                        SimpleNamespace(errors=[], loo=fake_loo(start, end, model_error, 0.0)))
    result = tune(dataset, {"basis_mode": ["auto"]})
    assert result.metadata["calibration_score"] == expected
    assert result.metadata["validation_score"] == expected


def test_objective_weights_curves_equally_and_reports_units_separately(dataset, monkeypatch):
    def scores(self, start, end, loo=False):
        euro = fake_loo(start, end, 2.0, 1.0)
        pound = fake_loo(start, end, 10.0, 100.0, units=("GBP/MWh",))
        # GBP has twice as many observations. Its row count and price scale
        # must not outweigh EUR when selecting the configuration.
        pound = pd.concat([pound, pound.assign(tenor="M+2")], ignore_index=True)
        return SimpleNamespace(errors=[], loo=pd.concat([euro, pound], ignore_index=True))

    monkeypatch.setattr(CurveFiller, "run", scores)
    result = tune(dataset, {"basis_mode": ["auto"]})
    assert result.metadata["calibration_score"] == pytest.approx((2.0 + 0.1) / 2)
    report = result.validation_report[result.validation_report["scope"] == "unit"].set_index("unit")
    assert report.loc["EUR/MWh", "mae_model"] == 2.0
    assert report.loc["GBP/MWh", "mae_model"] == 10.0
    assert report.loc["GBP/MWh", "n_paired"] == 2 * report.loc["EUR/MWh", "n_paired"]


@pytest.mark.parametrize("failure", ["engine", "duplicate", "missing_pair", "different_cases", "nonfinite"])
def test_candidate_failure_aborts_instead_of_selecting_a_partial_winner(dataset, monkeypatch, failure):
    def broken(self, start, end, loo=False):
        rows = fake_loo(start, end, 1.0, 2.0)
        errors = []
        if self.cfg.basis_mode == "ratio":
            if failure == "engine":
                errors = [dict(product="P", phase="prepare")]
            elif failure == "duplicate":
                rows = pd.concat([rows, rows.iloc[[0]]], ignore_index=True)
            elif failure == "missing_pair":
                rows = rows.iloc[1:].copy()
            elif failure == "different_cases":
                rows = rows[rows["reference_date"] != start].copy()
            else:
                rows.loc[0, "pred"] = float("inf")
        return SimpleNamespace(errors=errors, loo=rows)

    monkeypatch.setattr(CurveFiller, "run", broken)
    with pytest.raises(ValueError):
        tune(dataset, {"basis_mode": ["auto", "ratio"]})
