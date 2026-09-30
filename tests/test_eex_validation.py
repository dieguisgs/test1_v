"""Unusable EEX prices never enter pricing or replace earlier valid fixings."""

import logging
import math
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from vwaps.config import load_config
from vwaps.fill import CurveFiller
from vwaps.io_eex import EexBook, REQUIRED, load_eex_frame
from vwaps.log import get_logger
from vwaps.mapping import ProductMap


DAY = date(2026, 9, 30)


@pytest.fixture
def eex_logs(caplog):
    logger = get_logger()
    previous_level, previous_propagation = logger.level, logger.propagate
    logger.setLevel(logging.WARNING)
    logger.propagate = True
    caplog.set_level(logging.WARNING, logger="vwaps")
    yield caplog
    logger.setLevel(previous_level)
    logger.propagate = previous_propagation


def test_file_loader_discards_bad_prices_but_keeps_zero_negative_and_finite(tmp_path, eex_logs):
    path = tmp_path / "eex.csv"
    values = ["100.25", "not a price", "inf", "-inf", "", "0", "-12.5"]
    pd.DataFrame([
        (DAY, "Day", DAY + timedelta(days=i + 1), value)
        for i, value in enumerate(values)
    ], columns=REQUIRED).to_csv(path, index=False)
    frame = load_eex_frame(path)
    assert frame["settlPx"].tolist() == [100.25, 0.0, -12.5]
    assert frame["deliveryStart"].tolist() == [DAY + timedelta(days=i) for i in (1, 6, 7)]
    assert frame["tradeDate"].tolist() == [DAY] * 3
    assert len(eex_logs.records) == 1
    assert "excluded 4" in eex_logs.text and "retained 3" in eex_logs.text


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), "bad", None, ""])
def test_direct_book_rejects_invalid_prices_without_losing_valid_quotes(bad, eex_logs):
    frame = pd.DataFrame([
        (DAY, "Month", date(2026, 10, 1), 100.0),
        (DAY, "Month", date(2026, 11, 1), bad),
        (DAY, "Month", date(2026, 12, 1), -5.0),
    ], columns=REQUIRED)
    book = EexBook(frame)
    quotes, asof = book.quotes(DAY, None)
    assert asof == DAY
    assert quotes == {
        (date(2026, 10, 1), date(2026, 11, 1)): 100.0,
        (date(2026, 12, 1), date(2027, 1, 1)): -5.0,
    }
    assert len(eex_logs.records) == 1 and "excluded 1" in eex_logs.text


def test_invalid_duplicate_and_later_fixing_do_not_overwrite_valid_prices(eex_logs):
    delivery = DAY - timedelta(days=1)
    tomorrow = DAY + timedelta(days=1)
    book = EexBook(pd.DataFrame([
        (DAY, "Day", delivery, 75.0),
        (DAY, "Day", delivery, float("inf")),
        (tomorrow, "Day", delivery, float("nan")),
        (tomorrow, "Month", date(2026, 11, 1), 100.0),
    ], columns=REQUIRED))
    quotes, asof = book.quotes(tomorrow, None)
    assert asof == tomorrow
    assert quotes[(delivery, delivery + timedelta(days=1))] == 75.0
    assert all(math.isfinite(value) for value in quotes.values())
    assert len(eex_logs.records) == 1 and "excluded 2" in eex_logs.text


def test_all_invalid_file_returns_empty_book_and_logs_once(tmp_path, eex_logs):
    path = tmp_path / "invalid.csv"
    pd.DataFrame([
        (DAY, "Month", date(2026, 10, 1), "inf"),
        (DAY, "Month", date(2026, 11, 1), "bad"),
    ], columns=REQUIRED).to_csv(path, index=False)
    book = EexBook.from_file(path)
    assert book.trade_dates == []
    assert book.quotes(DAY, None) == ({}, None)
    assert len(eex_logs.records) == 1 and "excluded 2" in eex_logs.text


def test_empty_file_with_required_headers_is_supported(tmp_path, eex_logs):
    path = tmp_path / "empty.csv"
    pd.DataFrame(columns=REQUIRED).to_csv(path, index=False)
    book = EexBook.from_file(path)
    assert book.trade_dates == []
    assert book.quotes(DAY, None) == ({}, None)
    assert not eex_logs.records


def test_infinite_eex_target_becomes_missing_without_poisoning_finite_curve_points():
    cfg = replace(load_config(Path(__file__).resolve().parents[1] / "config.toml"),
                  tenors=["M+1", "M+2", "M+3"], layer_hist="off", layer_arbitrage=False,
                  layer_cross=False, layer_correlation=False)
    mapping = ProductMap("DE_Base load", "fill", "DE", "Base", "fixture.csv", "Base",
                         "Europe/Berlin", region="DE", unit="EUR/MWh")
    own = pd.DataFrame([dict(date=DAY, product=mapping.product, region=mapping.region,
                            unit=mapping.unit, tenor="M+1", vwap=110.0, volume=10.0)])
    book = EexBook(pd.DataFrame([
        (DAY, "Month", date(2026, 10, 1), 100.0),
        (DAY, "Month", date(2026, 11, 1), float("inf")),
        (DAY, "Month", date(2026, 12, 1), 120.0),
    ], columns=REQUIRED))
    result = CurveFiller(cfg, own, [mapping], {mapping.key: book}).run(DAY, DAY)
    assert not result.errors
    curve = result.filled.set_index("tenor")
    assert curve.loc["M+1", "price"] == 110.0
    assert curve.loc["M+2", "source"] == curve.loc["M+2", "data_origin"] == "missing"
    assert math.isnan(curve.loc["M+2", "price"])
    assert curve.loc["M+3", "data_origin"] == "estimated"
    available = result.filled[result.filled["source"] != "missing"]
    assert available["price"].map(math.isfinite).all()
