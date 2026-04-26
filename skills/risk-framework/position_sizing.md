# Position Sizing Examples

## Conservative (win_rate=0.45, profit_factor=1.3)
Kelly: 0.45 - 0.55/1.3 = 0.027 → Half-Kelly = 1.35% → capped at 10%
Recommended: 1.4% of portfolio

## Moderate (win_rate=0.55, profit_factor=1.6)
Kelly: 0.55 - 0.45/1.6 = 0.269 → Half-Kelly = 13.4% → capped at 10%
Recommended: 10.0% of portfolio

## Aggressive (win_rate=0.60, profit_factor=2.0)
Kelly: 0.60 - 0.40/2.0 = 0.40 → Half-Kelly = 20.0% → capped at 10%
Recommended: 10.0% of portfolio

## Notes
- Never exceed 10% per position without explicit user override
- In high-volatility regimes, halve the recommended size
- Round to nearest 0.1% for user-facing output
