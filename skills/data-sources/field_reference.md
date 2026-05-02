# Field Reference

## OHLCV Fields
- `Open`, `High`, `Low`, `Close`, `Volume`
- All numeric, volume is integer shares

## Quote Fields
- `price`, `change`, `change_percent`, `volume`, `market_cap`, `bid`, `ask`, `spread`

## Fundamental Fields
- `pe_ratio`, `pb_ratio`, `ev_ebitda`, `roe`, `roa`, `debt_equity`, `free_cash_flow`, `dividend_yield`, `eps`, `revenue_growth`, `eps_growth`, `beta`

## News Fields
- `title`, `source`, `url`, `published_at`, `sentiment` (positive|neutral|negative)

## Earnings Calendar Fields
- `symbol`, `date` (ISO 8601), `eps_estimate`, `eps_actual`, `quarter`
- `eps_actual` is null for future dates; `quarter` is fiscal period (e.g. "Q1-2026")

## Sector Performance Fields
- `etf` (ticker), `price`, `performance_1d`, `performance_1w`, `performance_1m`, `performance_3m`, `performance_ytd`, `rank`, `best_stock`
- All performance values are decimals (0.05 = 5%), not percentages
- Alpha Vantage also returns `rank` (1-11 ranking)

## Economic Indicators Fields
- `vix` (current level), `10y_yield` (decimal, 0.04 = 4%), `2y_yield` (decimal)
- `sp500_pe`, `gdp_growth` (decimal), `cpi` (index level), `unemployment_rate` (decimal)
- Fields unavailable from the provider are returned as `null`
