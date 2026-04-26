# Strategy Parameter Templates

## SMA Crossover
Default: fast=50, slow=200. Suitable for: large-cap equities, long-term trends.
Min period: 3y (needs time to generate enough crossovers).

## EMA Crossover
Default: fast=12, slow=26. Suitable for: swing trading, 1d interval.
Faster signal than SMA — more trades, higher commission impact.

## RSI Mean Reversion
Default: rsi_period=14, oversold=30, overbought=70.
Suitable for: ranging markets (ADX < 20). Avoid in strong trends.

## MACD Momentum
Default: fast=12, slow=26, signal=9. Suitable for: trending markets (ADX > 25).
Useless in ranging markets — always check ADX before recommending.

## Bollinger Breakout
Default: period=20, std=2. Suitable for: volatility expansion setups.
Works best after a Bollinger squeeze (band width at 6-month low).

## Buy and Hold
No parameters. Always use as the baseline comparison.
