"""Tests for fundamental analysis tools."""
from __future__ import annotations

import pandas as pd
import pytest

from quantagent.tools.fundamental import (
    compute_dcf,
    compute_magic_formula_rank,
    peer_comparison,
    score_altman_z,
    score_piotroski_f,
)


def test_compute_dcf():
    result = compute_dcf(
        free_cash_flows=[100.0, 110.0, 120.0],
        growth_rate=0.05,
        discount_rate=0.10,
        terminal_growth=0.02,
        shares_outstanding=10.0,
    )
    assert "intrinsic_value" in result
    assert "intrinsic_value_per_share" in result
    assert result["intrinsic_value"] > 0
    assert result["intrinsic_value_per_share"] > 0


def test_compute_dcf_invalid_rates():
    with pytest.raises(ValueError, match="discount_rate must be greater than terminal_growth"):
        compute_dcf(
            free_cash_flows=[100.0],
            growth_rate=0.05,
            discount_rate=0.02,
            terminal_growth=0.03,
            shares_outstanding=10.0,
        )


def test_score_piotroski_f():
    fundamentals = {
        "roa": 0.10,
        "operating_cash_flow": 100.0,
        "net_income": 80.0,
        "roa_current": 0.12,
        "roa_prior": 0.08,
        "total_liabilities_current": 50.0,
        "total_assets_current": 200.0,
        "total_liabilities_prior": 60.0,
        "total_assets_prior": 200.0,
        "current_ratio_current": 2.0,
        "current_ratio_prior": 1.8,
        "shares_outstanding_current": 100.0,
        "shares_outstanding_prior": 100.0,
        "gross_margin_current": 0.40,
        "gross_margin_prior": 0.38,
        "asset_turnover_current": 0.50,
        "asset_turnover_prior": 0.48,
    }
    result = score_piotroski_f(fundamentals)
    assert 0 <= result["score"] <= 9
    assert result["max_score"] == 9
    assert "breakdown" in result


def test_score_altman_z():
    fundamentals = {
        "working_capital": 50.0,
        "retained_earnings": 100.0,
        "ebit": 30.0,
        "total_assets": 200.0,
        "total_liabilities": 80.0,
        "sales": 150.0,
        "market_cap": 300.0,
    }
    result = score_altman_z(fundamentals)
    assert "score" in result
    assert "zone" in result
    assert result["zone"] in ("safe", "grey", "distress")


def test_score_altman_z_zero_assets():
    result = score_altman_z({"total_assets": 0})
    assert result["score"] is None
    assert result["zone"] == "unknown"


def test_peer_comparison():
    data = {
        "AAPL": {"pe_ratio": 30.0, "pb_ratio": 10.0, "roe": 0.25},
        "MSFT": {"pe_ratio": 25.0, "pb_ratio": 8.0, "roe": 0.30},
    }
    df = peer_comparison(data)
    assert isinstance(df, pd.DataFrame)
    assert "AAPL" in df.index
    assert "MSFT" in df.index


def test_compute_magic_formula_rank():
    data = {
        "AAPL": {"ebit": 100.0, "working_capital": 50.0, "fixed_assets": 30.0, "enterprise_value": 500.0},
        "MSFT": {"ebit": 80.0, "working_capital": 40.0, "fixed_assets": 20.0, "enterprise_value": 400.0},
    }
    df = compute_magic_formula_rank(data)
    assert isinstance(df, pd.DataFrame)
    assert "magic_formula_rank" in df.columns
    assert df["magic_formula_rank"].min() == 1
