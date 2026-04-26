"""Fundamental analysis tool functions."""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def compute_dcf(
    free_cash_flows: list[float],
    growth_rate: float,
    discount_rate: float,
    terminal_growth: float,
    shares_outstanding: float,
) -> dict:
    """Compute discounted cash flow valuation.

    Args:
        free_cash_flows: List of projected FCFs (typically 5 years).
        growth_rate: Growth rate for projection period (decimal).
        discount_rate: WACC / discount rate (decimal).
        terminal_growth: Perpetual growth rate (decimal).
        shares_outstanding: Shares outstanding in millions.

    Returns:
        Dict with intrinsic_value, intrinsic_value_per_share, and assumptions.
    """
    if discount_rate <= terminal_growth:
        raise ValueError("discount_rate must be greater than terminal_growth")

    # Project FCFs
    projected = []
    last_fcf = free_cash_flows[-1] if free_cash_flows else 0.0
    for year in range(1, 6):
        fcf = last_fcf * ((1 + growth_rate) ** year)
        projected.append(fcf)

    # Discount projected FCFs
    pv_projected = sum(fcf / ((1 + discount_rate) ** (i + 1)) for i, fcf in enumerate(projected))

    # Terminal value (Gordon Growth Model)
    terminal_fcf = projected[-1] * (1 + terminal_growth)
    terminal_value = terminal_fcf / (discount_rate - terminal_growth)
    pv_terminal = terminal_value / ((1 + discount_rate) ** len(projected))

    intrinsic_value = pv_projected + pv_terminal
    iv_per_share = intrinsic_value / shares_outstanding if shares_outstanding else None

    return {
        "intrinsic_value": round(intrinsic_value, 4),
        "intrinsic_value_per_share": round(iv_per_share, 4) if iv_per_share else None,
        "pv_projected": round(pv_projected, 4),
        "pv_terminal": round(pv_terminal, 4),
        "projected_fcf": [round(f, 4) for f in projected],
        "assumptions": {
            "growth_rate": growth_rate,
            "discount_rate": discount_rate,
            "terminal_growth": terminal_growth,
            "shares_outstanding": shares_outstanding,
        },
    }


def score_piotroski_f(fundamentals: dict) -> dict:
    """Compute Piotroski F-Score (0-9) from fundamental data.

    Args:
        fundamentals: Dict with roa, operating_cash_flow, net_income,
            total_assets_current, total_assets_prior, total_liabilities_current,
            total_liabilities_prior, gross_margin_current, gross_margin_prior,
            asset_turnover_current, asset_turnover_prior, shares_outstanding_current,
            shares_outstanding_prior.

    Returns:
        Dict with score (0-9) and per-criterion breakdown.
    """
    score = 0
    breakdown = {}

    # Profitability
    roa = fundamentals.get("roa", 0)
    ocf = fundamentals.get("operating_cash_flow", 0)
    net_income = fundamentals.get("net_income", 0)

    breakdown["positive_roa"] = roa > 0
    if breakdown["positive_roa"]:
        score += 1

    breakdown["positive_ocf"] = ocf > 0
    if breakdown["positive_ocf"]:
        score += 1

    breakdown["roa_improving"] = fundamentals.get("roa_current", roa) > fundamentals.get(
        "roa_prior", roa
    )
    if breakdown["roa_improving"]:
        score += 1

    breakdown["ocf_gt_net_income"] = ocf > net_income
    if breakdown["ocf_gt_net_income"]:
        score += 1

    # Leverage / Liquidity
    leverage_current = fundamentals.get("total_liabilities_current", 0) / max(
        fundamentals.get("total_assets_current", 1), 1
    )
    leverage_prior = fundamentals.get("total_liabilities_prior", 0) / max(
        fundamentals.get("total_assets_prior", 1), 1
    )
    breakdown["leverage_improving"] = leverage_current < leverage_prior
    if breakdown["leverage_improving"]:
        score += 1

    breakdown["liquidity_improving"] = fundamentals.get("current_ratio_current", 0) > fundamentals.get(
        "current_ratio_prior", 0
    )
    if breakdown["liquidity_improving"]:
        score += 1

    breakdown["no_new_shares"] = fundamentals.get("shares_outstanding_current", 0) <= fundamentals.get(
        "shares_outstanding_prior", 0
    )
    if breakdown["no_new_shares"]:
        score += 1

    # Efficiency
    breakdown["margin_improving"] = fundamentals.get("gross_margin_current", 0) > fundamentals.get(
        "gross_margin_prior", 0
    )
    if breakdown["margin_improving"]:
        score += 1

    breakdown["turnover_improving"] = fundamentals.get(
        "asset_turnover_current", 0
    ) > fundamentals.get("asset_turnover_prior", 0)
    if breakdown["turnover_improving"]:
        score += 1

    return {
        "score": score,
        "max_score": 9,
        "breakdown": breakdown,
    }


def score_altman_z(fundamentals: dict) -> dict:
    """Compute Altman Z-Score.

    Args:
        fundamentals: Dict with working_capital, retained_earnings, ebit,
            total_assets, total_liabilities, sales, market_cap.

    Returns:
        Dict with score and zone (safe|grey|distress).
    """
    working_capital = fundamentals.get("working_capital", 0)
    retained_earnings = fundamentals.get("retained_earnings", 0)
    ebit = fundamentals.get("ebit", 0)
    total_assets = fundamentals.get("total_assets", 1)
    total_liabilities = fundamentals.get("total_liabilities", 1)
    sales = fundamentals.get("sales", 0)
    market_cap = fundamentals.get("market_cap", 0)

    if total_assets <= 0:
        return {"score": None, "zone": "unknown", "reason": "total_assets <= 0"}

    z = (
        1.2 * (working_capital / total_assets)
        + 1.4 * (retained_earnings / total_assets)
        + 3.3 * (ebit / total_assets)
        + 0.6 * (market_cap / total_liabilities)
        + 1.0 * (sales / total_assets)
    )

    if z > 2.99:
        zone = "safe"
    elif z > 1.81:
        zone = "grey"
    else:
        zone = "distress"

    return {"score": round(z, 4), "zone": zone}


def peer_comparison(symbol_fundamentals: dict[str, dict]) -> pd.DataFrame:
    """Compare fundamentals across peers.

    Args:
        symbol_fundamentals: Dict mapping symbol -> fundamentals dict.

    Returns:
        DataFrame with one row per symbol, columns for key metrics.
    """
    fields = [
        "pe_ratio",
        "pb_ratio",
        "ev_ebitda",
        "roe",
        "roa",
        "debt_equity",
        "dividend_yield",
        "eps",
        "revenue_growth",
        "eps_growth",
        "beta",
    ]
    rows: list[dict[str, Any]] = []
    for symbol, data in symbol_fundamentals.items():
        row: dict[str, Any] = {"symbol": symbol}
        for f in fields:
            row[f] = data.get(f)
        rows.append(row)
    return pd.DataFrame(rows).set_index("symbol").round(4)


def compute_magic_formula_rank(symbol_fundamentals: dict[str, dict]) -> pd.DataFrame:
    """Rank symbols by Joel Greenblatt's Magic Formula.

    Ranking = combine ROC (EBIT / (Net Working Capital + Net Fixed Assets))
    and Earnings Yield (EBIT / Enterprise Value).

    Args:
        symbol_fundamentals: Dict mapping symbol -> fundamentals dict.

    Returns:
        DataFrame with rank, roc, earnings_yield for each symbol.
    """
    rows = []
    for symbol, data in symbol_fundamentals.items():
        ebit = data.get("ebit", 0)
        working_capital = data.get("working_capital", 0)
        fixed_assets = data.get("fixed_assets", 0)
        enterprise_value = data.get("enterprise_value", 0)

        roc = ebit / (working_capital + fixed_assets) if (working_capital + fixed_assets) > 0 else None
        earnings_yield = ebit / enterprise_value if enterprise_value > 0 else None

        rows.append(
            {
                "symbol": symbol,
                "roc": roc,
                "earnings_yield": earnings_yield,
            }
        )

    df = pd.DataFrame(rows)
    df["roc_rank"] = df["roc"].rank(ascending=False, method="min")
    df["ey_rank"] = df["earnings_yield"].rank(ascending=False, method="min")
    df["magic_formula_rank"] = (df["roc_rank"] + df["ey_rank"]).rank(method="min").astype(int)
    df = df.sort_values("magic_formula_rank")
    return df[["symbol", "magic_formula_rank", "roc", "earnings_yield"]].set_index("symbol").round(4)
