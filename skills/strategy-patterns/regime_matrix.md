# Regime Classification Matrix

## Primary Classification

| ADX(14) | Price vs SMA(200) | VIX | Regime | Action |
|---|---|---|---|---|
| > 25 | > SMA200 | < 25 | Bull trend | Trend-following long |
| > 25 | < SMA200 | < 25 | Bear trend | Defensive / cash |
| < 20 | Any | < 25 | Ranging | Mean-reversion |
| Any | Any | > 25 | High volatility | Reduce size, wait |

## Edge Cases

### ADX 20-25 (transition zone)
Wait for clear directional move. Do not initiate new positions.
Use smaller position sizes if forced to trade.

### Price near SMA(200) within 2%
Neutral bias. Require additional confirmation from volume or momentum.

### VIX spike > 30
Historical volatility regime. Expect sharp reversals.
All position sizes reduced by 50%. No new trend entries.

### Earnings season (within 2 weeks)
Increase ATR multiples for stops (2.5x instead of 2x).
Avoid holding through earnings unless explicitly requested.
