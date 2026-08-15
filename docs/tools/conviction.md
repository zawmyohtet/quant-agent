# conviction.py

Fuses the market-level sub-analyses (regime, breadth, timing, sector rotation,
sentiment) into one 0-100 conviction score with an explicit signal-convergence
bonus. Adapted from the Druckenmiller-style synthesizer in
`claude-trading-skills`. Source: `quantagent/tools/conviction.py`.

## synthesize_conviction

**Agent-facing tool name:** `synthesize_conviction_tool`

Note: the agent-facing wrapper (`_synthesize_conviction_tool` in
`quantagent/agent/tools_registry.py`) takes **no parameters** other than the
injected provider — it always runs against the default `universe="sp500"`.
The `universe` argument only exists on the underlying Python function,
callable directly for other universes (e.g. `nasdaq100`).

**Purpose:** Answers "how bullish should I be right now?" by combining five
independent market read-outs — regime, breadth, timing (distribution days +
follow-through day), sector rotation, and sentiment — into a single 0-100
conviction score, a stance label, and a recommended equity exposure band.

**Why built this way:**

- No single indicator reliably calls market direction, so the function leans
  on sub-analyses that are themselves already composites (`detect_market_regime`,
  `count_distribution_days`, `detect_follow_through_day`,
  `detect_sector_rotation`, `compute_market_sentiment` — from
  `market_breadth.py` and `sector_analysis.py`) rather than raw price data.
- The five components plus a convergence term are combined with fixed weights
  reflecting relative reliability: `regime` (the broadest cross-asset
  composite) gets the largest single weight, `timing` (tactical, IBD-style)
  is next, and `sentiment` (noisiest, single fast-path composite) gets the
  least.
- The **signal-convergence bonus** exists because independent signals
  agreeing is stronger evidence than any one signal being strongly
  bullish/bearish while the others disagree — it rewards breadth of
  agreement, not just the average score.
- All five sub-analyses are fetched concurrently via `asyncio.gather` since
  they are independent, I/O-bound calls.
- Missing/unavailable sub-scores degrade to neutral (50.0) rather than
  raising or biasing the composite (e.g. `breadth_raw is None → 50.0`,
  unknown `dist.signal`/`rotation.rotation_signal` → default 50.0), and every
  component is passed through `_clip` to guarantee it stays in `[0, 100]`
  even if an upstream calculation could overshoot.

**Math:**

Weights (`_WEIGHTS`, sum to 1.00):

| Component | Weight |
|---|---|
| regime | 0.30 |
| timing | 0.20 |
| breadth | 0.15 |
| rotation | 0.15 |
| sentiment | 0.10 |
| convergence | 0.10 |

Per-component scoring (each mapped to 0-100 before weighting):

1. **regime** — used as-is: `regime["score"]`, the 0-100 composite already
   produced by `detect_market_regime` (itself `50 * (1 + weighted_mean)` of
   9 cross-asset/trend/volatility/breadth sub-scores each in `[-1, 1]`).
2. **breadth** — pulled from the regime detector's own breadth sub-score,
   `regime["components"]["scores"]["breadth"]` (range `[-1, 1]`), rescaled:
   `breadth_score = (breadth_raw + 1) * 50`. Defaults to `50.0` if absent.
3. **timing** — `_DISTRIBUTION_SCORES[dist.signal] + _FTD_ADJUST[ftd.status]`,
   clipped to `[0, 100]`:
   - distribution-day base: `healthy=80.0`, `caution=50.0`,
     `under-pressure=20.0`
   - follow-through-day adjustment: `confirmed-uptrend=+15.0`,
     `rally-attempt=0.0`, `correction=-15.0`
4. **rotation** — `_ROTATION_SCORES[rotation.rotation_signal]`:
   `risk-on=75.0`, `neutral=50.0`, `risk-off=25.0` (default 50.0 if unknown).
5. **sentiment** — `sentiment.score` is in `[-100, 100]`; rescaled via
   `_clip((sentiment_score + 100) / 2)` → `[0, 100]`.

**Convergence bonus:** for the 5 components above, `sides = [score >= 50 for
each component]`; `agreeing = max(count(True), count(False))` (i.e. the size
of the majority side, out of 5 → minimum possible value is 3). Bonus
`= round(agreeing / 5 * 100, 2)`. E.g. 4 of 5 components on the same side of
50 → `bonus = 4/5*100 = 80.0`. This bonus itself carries weight `0.10` in the
final sum, so full 5/5 agreement contributes `+10.0` points versus the
minimum possible convergence contribution of `+6.0` points (3/5 agreement).

**Final score:**

```
conviction_score = round(
    sum(component.score * component.weight for component in
        [regime, breadth, timing, rotation, sentiment, convergence]),
    2,
)
```

**Stance mapping** (`_STANCES`, first matching threshold from the top wins):

| Score | Stance |
|---|---|
| >= 80 | `aggressive` |
| >= 60 | `constructive` |
| >= 40 | `selective` |
| >= 20 | `defensive` |
| < 20 | `risk-off` |

**Exposure band** — `exposure_band(score)` (`market_breadth.py`) reuses the
same 80/60/40/20 threshold cuts as the market-regime bands (not a separate
schedule), applied here to the conviction score itself:

| Score | Regime label reused | min_pct | max_pct | label |
|---|---|---|---|---|
| >= 80 | strong-bull | 90 | 100 | strong |
| >= 60 | bull | 70 | 90 | healthy |
| >= 40 | neutral | 50 | 70 | neutral |
| >= 20 | bear | 40 | 60 | weakening |
| < 20 | strong-bear | 25 | 40 | critical |

**Key risks** (`_key_risks`, any subset may fire, list may be empty):

- `dist.count >= 5` → `"{count} distribution days in {lookback_days} sessions
  — institutional selling pressure"`
- `ftd.status == "correction"` → `"Market in correction with no
  follow-through day yet"`
- `regime.confidence < 0.6` → `"Regime components disagree — low-confidence
  reading"`
- `rotation.rotation_signal == "risk-off"` and `regime.regime in ("bull",
  "strong-bull")` → `"Defensive sector rotation diverging from bull regime"`
- `sentiment.score > 60` → `"Sentiment at extreme greed — complacency risk"`
- `sentiment.score < -60` → `"Sentiment at extreme fear — expect high
  volatility"`

**Usage:**

```python
result = await synthesize_conviction(provider, universe="sp500")
```

- `provider: AbstractDataProvider` — market data provider.
- `universe: str = "sp500"` — universe for the regime/breadth components
  (Python function only; not exposed on the agent tool, which is fixed to
  `sp500`).

Returns a dict:

```json
{
  "conviction_score": 62.4,
  "stance": "constructive",
  "recommended_exposure": {"min_pct": 70, "max_pct": 90, "label": "healthy"},
  "components": {
    "regime": {"score": 65.2, "weight": 0.30, "signal": "bull"},
    "breadth": {"score": 58.0, "weight": 0.15, "signal": "healthy"},
    "timing": {"score": 65.0, "weight": 0.20, "signal": "healthy / confirmed-uptrend"},
    "rotation": {"score": 75.0, "weight": 0.15, "signal": "risk-on"},
    "sentiment": {"score": 55.0, "weight": 0.10, "signal": "neutral"},
    "convergence": {"score": 80.0, "weight": 0.10, "signal": "4/5 components agree"}
  },
  "convergence": {"agreeing": 4, "total": 5, "bonus": 80.0},
  "key_risks": [],
  "as_of": "2026-08-15"
}
```

Agent-facing call (no arguments):

```
synthesize_conviction_tool()
```
