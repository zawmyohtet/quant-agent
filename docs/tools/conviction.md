# Conviction Score

`quantagent/tools/conviction.py`

Fuses five market-level analyses — regime, breadth, timing, sector rotation, and sentiment — into one 0–100 conviction score with an explicit signal-convergence bonus. The goal is to answer "how bullish should I be right now?" by combining multiple independent signals rather than relying on any single indicator.

Adapted from the Druckenmiller-style synthesizer in `claude-trading-skills`.

---

## synthesize_conviction

**Agent tool:** `synthesize_conviction_tool`

> **Note:** The agent wrapper takes **no parameters** — it always runs against `universe="sp500"`. The `universe` argument only exists on the underlying Python function for direct use with other universes (e.g. `nasdaq100`).

### What It Does

Answers "how bullish should I be right now?" by combining five independent market read-outs into a single 0–100 conviction score, a stance label, and a recommended equity exposure band.

Instead of trying to interpret a dozen different indicators and figure out what they mean, you get one number, one stance, and one exposure range. It's not a crystal ball — it can't predict the future — but it's a systematic way of synthesizing a lot of information into a practical recommendation.

### How It Works

1. **Fetch five market analyses concurrently** — the function calls `detect_market_regime`, `count_distribution_days`, `detect_follow_through_day`, `detect_sector_rotation`, and `compute_market_sentiment` all at once using `asyncio.gather`. These are independent, I/O-bound calls, so running them in parallel is much faster than running them sequentially.

2. **Score each component 0–100** — each of the five sub-analyses is converted to a 0–100 scale. Some are already on that scale (regime), some need rescaling (sentiment from -100 to +100 becomes 0 to 100), and some are mapped from categorical values (like "healthy" → 80, "caution" → 50).

3. **Apply weights** — each component is multiplied by its weight (regime 30%, timing 20%, breadth 15%, rotation 15%, sentiment 10%). The weights reflect how much trust we place in each signal based on its historical reliability.

4. **Calculate convergence bonus** — if multiple independent signals agree on the same direction (all bullish or all bearish), that's stronger evidence than any one signal being extreme. The convergence bonus rewards this agreement and adds it as a sixth component with 10% weight.

5. **Map to stance and exposure band** — the final score is mapped to a stance label (aggressive, constructive, selective, defensive, risk-off) and a recommended equity exposure range (e.g. 70–90% for a score of 60–79).

6. **Flag key risks** — the function checks for specific warning conditions (like 5+ distribution days or extreme greed sentiment) and includes them in the output as explanatory notes.

### The Five Components

The conviction score is built from five sub-analyses, each examining a different aspect of the market. Let's walk through each one.

#### 1. Market Regime (Weight: 30%)

**What it measures:** The overall health and direction of the market, based on a composite of nine different signals including cross-asset ratios (like how equal-weight stocks are performing vs. cap-weighted stocks), trend direction (is the S&P 500 above its 200-day moving average?), volatility (what's the VIX doing?), and breadth (how many stocks are participating in the move?).

**Why it matters:** This is the broadest, most comprehensive signal. It doesn't just look at stock prices — it looks at how different parts of the market are behaving relative to each other. When everything is aligned (stocks beating bonds, cyclicals beating defensives, small caps beating large caps, low volatility, broad participation), that's a strong bullish signal. When things are diverging, that's a warning.

**How it's scored:** The market regime detector already produces a 0–100 score on its own, so we use that directly. A score of 50 is neutral, above 50 is bullish, below 50 is bearish.

**Weight rationale:** This gets the highest weight (30%) because it's the most comprehensive signal. It's looking at the big picture from multiple angles, so we trust it more than any single indicator.

#### 2. Timing Signals (Weight: 20%)

**What it measures:** Short-term market timing based on two classic techniques from William O'Neil's CANSLIM methodology:

1. **Distribution days** — days when the market closes down 0.2% or more on higher volume than the previous day. This suggests institutional selling (big funds dumping stocks). If you see 5 or more distribution days in a 25-session window, the market is "under pressure."

2. **Follow-through day** — the first day (on or after rally day 4) where the market gains 1.25% or more on higher volume after a correction. This signals that a new uptrend has begun. O'Neil found that follow-through days on rally days 1–3 are unreliable (too many false starts), but day 4 and beyond have a much better track record.

**Why it matters:** These are tactical signals that help you avoid getting caught in market tops and bottoms. Distribution days warn you when the market is rolling over. Follow-through days tell you when it's safe to get back in after a pullback.

**How it's scored:** The timing score combines two pieces:

| Distribution day signal | Base score |
|-------------------------|------------|
| Healthy (fewer than 3 distribution days) | 80 |
| Caution (3–4 distribution days) | 50 |
| Under pressure (5 or more) | 20 |

Then we add an adjustment based on the follow-through day status:

| Follow-through status | Adjustment |
|-----------------------|------------|
| Confirmed uptrend | +15 |
| Rally attempt (no FTD yet) | 0 |
| Correction (no FTD, still falling) | -15 |

The final timing score is clipped to the 0–100 range.

**Weight rationale:** This gets the second-highest weight (20%) because it's a proven tactical tool, but it's not as comprehensive as the regime signal. It's looking at one specific aspect (short-term momentum and institutional behavior) rather than the whole market picture.

#### 3. Market Breadth (Weight: 15%)

**What it measures:** How many stocks are participating in the market's move. Is it a broad-based rally where most stocks are going up, or is the index being carried by just a few big names while everything else lags?

**Why it matters:** Broad participation is a sign of a healthy, sustainable uptrend. When only a handful of stocks are driving the market higher, that's a warning sign — the rally is fragile and could reverse if those few leaders stumble.

**How it's scored:** We pull the breadth sub-score from the market regime detector (it's one of the nine components that make up the regime score). This sub-score is originally on a -1 to +1 scale, so we rescale it to 0–100 by adding 1 and multiplying by 50.

If the breadth sub-score isn't available for some reason, we default to 50 (neutral) rather than guessing.

**Weight rationale:** Breadth is important but not as reliable as the regime or timing signals. It can give false signals (for example, in a narrow market rally led by mega-cap tech stocks, the breadth might look weak even though the market continues higher). So it gets a moderate weight (15%).

#### 4. Sector Rotation (Weight: 15%)

**What it measures:** Whether money is flowing into cyclical sectors (technology, consumer discretionary, financials, industrials — stocks that do well when the economy is strong) or defensive sectors (consumer staples, utilities, healthcare — stocks that hold up when the economy is weak).

**Why it matters:** This is a classic risk-on/risk-off signal. When cyclicals are outperforming defensives, investors are optimistic about the economy and willing to take risks. When defensives are outperforming, investors are worried and seeking safety.

**How it's scored:** We look at the sector rotation detector's output, which classifies the current environment as one of three states:

| Rotation signal | Score |
|-----------------|-------|
| Risk-on (cyclicals leading) | 75 |
| Neutral (no clear leadership) | 50 |
| Risk-off (defensives leading) | 25 |

If the rotation signal is unknown or unavailable, we default to 50 (neutral).

**Weight rationale:** Sector rotation is a useful macro signal, but it's slower-moving and less precise than the timing or regime signals. It tells you the general direction of money flow, but not the exact timing. So it gets a moderate weight (15%).

#### 5. Sentiment (Weight: 10%)

**What it measures:** The overall "fear and greed" mood of the market, based on four components:

1. **VIX level** — the "fear gauge." Low VIX (below 15) suggests complacency and greed. High VIX (above 30) suggests panic and fear.
2. **VIX term structure** — whether the VIX is in "contango" (future volatility expected to be higher than current volatility, which is normal) or "backwardation" (current volatility higher than future volatility, which signals acute stress).
3. **Sector breadth** — what percentage of sector ETFs are trading above their 50-day moving average.
4. **Momentum** — the S&P 500's 1-month and 3-month returns.

These four components are combined into a sentiment score ranging from -100 (extreme fear) to +100 (extreme greed).

**Why it matters:** Sentiment is a contrarian indicator. When everyone is greedy, the market is often near a top. When everyone is fearful, the market is often near a bottom. But sentiment can stay extreme for a long time, so it's not a timing tool — it's more of a warning signal.

**How it's scored:** The sentiment score is originally on a -100 to +100 scale. We rescale it to 0–100 by adding 100 and dividing by 2. So a sentiment score of 0 (neutral) becomes 50, +100 (extreme greed) becomes 100, and -100 (extreme fear) becomes 0.

**Weight rationale:** Sentiment gets the lowest weight (10%) because it's the noisiest signal. It can stay at extremes for weeks or months without the market reversing. It's useful as a warning, but not as a primary driver of conviction.

### The Convergence Bonus (Weight: 10%)

Here's where it gets interesting. After scoring each of the five components above, we check how many of them are on the same side of 50 (the neutral line).

If 4 out of 5 components are above 50 (bullish), that's strong evidence the market is genuinely bullish. If only 3 out of 5 are above 50, the signals are more mixed.

The convergence bonus rewards agreement:

```
agreeing = the larger of (count of components >= 50) or (count of components < 50)
bonus = (agreeing / 5) * 100
```

So if all 5 components agree (all bullish or all bearish), the bonus is 100. If 4 out of 5 agree, the bonus is 80. If 3 out of 5 agree (the minimum possible majority), the bonus is 60.

This bonus itself carries a weight of 10% in the final score. So full agreement (5/5) contributes +10 points to the final score, while minimal agreement (3/5) contributes +6 points.

**Why this matters:** Independent signals agreeing is stronger evidence than any single signal being extreme. If the regime, timing, breadth, rotation, and sentiment all say "bullish," that's much more convincing than the regime saying "very bullish" while the other four are neutral. The convergence bonus captures this intuition.

### Math

#### Component Weights

| Component | Weight |
|-----------|--------|
| regime | 0.30 |
| timing | 0.20 |
| breadth | 0.15 |
| rotation | 0.15 |
| sentiment | 0.10 |
| convergence | 0.10 |

#### Per-Component Scoring

Each component is mapped to 0–100 before weighting:

1. **regime** — used as-is: `regime["score"]`, the 0–100 composite already produced by `detect_market_regime` (itself `50 * (1 + weighted_mean)` of 9 cross-asset/trend/volatility/breadth sub-scores each in `[-1, 1]`).

2. **breadth** — pulled from the regime detector's own breadth sub-score, `regime["components"]["scores"]["breadth"]` (range `[-1, 1]`), rescaled: `breadth_score = (breadth_raw + 1) * 50`. Defaults to `50.0` if absent.

3. **timing** — `_DISTRIBUTION_SCORES[dist.signal] + _FTD_ADJUST[ftd.status]`, clipped to `[0, 100]`:
   - distribution-day base: `healthy=80.0`, `caution=50.0`, `under-pressure=20.0`
   - follow-through-day adjustment: `confirmed-uptrend=+15.0`, `rally-attempt=0.0`, `correction=-15.0`

4. **rotation** — `_ROTATION_SCORES[rotation.rotation_signal]`: `risk-on=75.0`, `neutral=50.0`, `risk-off=25.0` (default 50.0 if unknown).

5. **sentiment** — `sentiment.score` is in `[-100, 100]`; rescaled via `_clip((sentiment_score + 100) / 2)` → `[0, 100]`.

#### Convergence Bonus

For the 5 components above: `sides = [score >= 50 for each component]`; `agreeing = max(count(True), count(False))` (i.e. the size of the majority side, out of 5 → minimum possible value is 3). Bonus `= round(agreeing / 5 * 100, 2)`. E.g. 4 of 5 components on the same side of 50 → `bonus = 4/5*100 = 80.0`. This bonus itself carries weight `0.10` in the final sum, so full 5/5 agreement contributes `+10.0` points versus the minimum possible convergence contribution of `+6.0` points (3/5 agreement).

#### Final Score

```
conviction_score = round(
    sum(component.score * component.weight for component in
        [regime, breadth, timing, rotation, sentiment, convergence]),
    2,
)
```

#### Stance Mapping

First matching threshold from the top wins:

| Score | Stance |
|-------|--------|
| >= 80 | aggressive |
| >= 60 | constructive |
| >= 40 | selective |
| >= 20 | defensive |
| < 20 | risk-off |

#### Exposure Band

Reuses the same 80/60/40/20 threshold cuts as the market-regime bands via `exposure_band(score)`:

| Score | min_pct | max_pct | label |
|-------|---------|---------|-------|
| >= 80 | 90 | 100 | strong |
| >= 60 | 70 | 90 | healthy |
| >= 40 | 50 | 70 | neutral |
| >= 20 | 40 | 60 | weakening |
| < 20 | 25 | 40 | critical |

#### Key Risks

Any subset may fire (list may be empty):

| Condition | Risk message |
|-----------|--------------|
| `dist.count >= 5` | "{count} distribution days in {lookback_days} sessions — institutional selling pressure" |
| `ftd.status == "correction"` | "Market in correction with no follow-through day yet" |
| `regime.confidence < 0.6` | "Regime components disagree — low-confidence reading" |
| `rotation.rotation_signal == "risk-off"` and `regime.regime in ("bull", "strong-bull")` | "Defensive sector rotation diverging from bull regime" |
| `sentiment.score > 60` | "Sentiment at extreme greed — complacency risk" |
| `sentiment.score < -60` | "Sentiment at extreme fear — expect high volatility" |

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Market data provider |
| `universe` | `str` | `"sp500"` | Universe for regime/breadth components (Python function only; not exposed on the agent tool, which is fixed to `sp500`) |

### Returns

Returns a dict with the following structure:

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

**Field explanations:**

- `conviction_score` — the final 0–100 score
- `stance` — plain-English label (aggressive, constructive, selective, defensive, risk-off)
- `recommended_exposure` — equity exposure band with min/max percentages and label
- `components` — breakdown of each component's score, weight, and signal
- `convergence` — details on how many components agreed and the resulting bonus
- `key_risks` — list of warning messages (may be empty)
- `as_of` — date the analysis was performed

### Usage

**Python API** (any universe):

```python
result = await synthesize_conviction(provider, universe="sp500")
```

**Agent tool** (no arguments, fixed to sp500):

```
synthesize_conviction_tool()
```

### Design Notes

**Why five components instead of one?** No single indicator reliably calls market direction, so the function leans on sub-analyses that are themselves already composites (`detect_market_regime`, `count_distribution_days`, `detect_follow_through_day`, `detect_sector_rotation`, `compute_market_sentiment` — from `market_breadth.py` and `sector_analysis.py`) rather than raw price data. By combining multiple independent signals, we reduce the risk of being misled by any one indicator giving a false signal.

**Why these specific weights?** The weights reflect our confidence in each signal based on historical evidence and theoretical soundness. Regime gets the highest weight because it's the most comprehensive, looking at nine different sub-signals. Timing is next because it's based on proven tactical techniques. Breadth and rotation are tied because they're both useful but less reliable. Sentiment gets the lowest weight because it's the noisiest. These weights are fixed, not dynamically adjusted — you could argue that different weights might work better in different market environments, but fixed weights keep the model simple and transparent.

**Why the convergence bonus?** The convergence bonus is based on a simple insight: when independent signals agree, that's stronger evidence than any single signal being extreme. Imagine two scenarios: (1) The regime score is 90 (very bullish), but timing, breadth, rotation, and sentiment are all at 50 (neutral). (2) All five components are at 70 (moderately bullish). Most traders would say scenario 2 is more convincing, because the agreement across multiple independent sources suggests the bullish signal is real, not just noise in one indicator. The convergence bonus captures this intuition by rewarding agreement.

**Why not use raw price data?** You might wonder why we don't just look at the S&P 500's price trend and call it a day. The answer is that price alone doesn't tell you enough. A market can be going up on low breadth (just a few stocks driving the rally), which is a warning sign. It can be going up while sentiment is at extreme greed, which suggests complacency. It can be going up while sector rotation is defensive, which suggests investors are hedging their bets. By looking at multiple dimensions — not just price, but breadth, rotation, sentiment, and timing — we get a fuller picture of what's really happening in the market.

**Why fixed thresholds?** The thresholds for stances (80/60/40/20) and exposure bands are fixed, not dynamically adjusted. You could argue that different market environments might call for different thresholds, but fixed thresholds keep the model simple, transparent, and consistent over time. These thresholds are based on historical experience and common sense: 80+ is clearly bullish, 60–79 is mostly bullish, 40–59 is neutral, 20–39 is mostly bearish, below 20 is clearly bearish.

**Why concurrent execution?** All five sub-analyses are fetched concurrently via `asyncio.gather` since they are independent, I/O-bound calls. This is much faster than running them sequentially — the total time is the slowest of the five calls, not the sum of all five.

**Why graceful degradation?** Missing/unavailable sub-scores degrade to neutral (50.0) rather than raising or biasing the composite. Every component is passed through `_clip` to guarantee it stays in `[0, 100]` even if an upstream calculation could overshoot. This ensures the conviction score is always computable, even if some data sources are temporarily unavailable.

### What This Means for You

The conviction score is designed to give you a clear, actionable answer to the question: "How much should I be invested right now?"

The score updates as market conditions change. When the market is healthy and signals are aligned, the score will be high and the recommendation will be to stay fully invested. When signals start to deteriorate, the score will drop and the recommendation will shift toward caution.

The key risks section helps you understand what's driving the score. If the score is low because of 5 distribution days and extreme greed sentiment, you know the market is showing signs of institutional selling and complacency. If the score is low because of a correction with no follow-through day, you know the market is still falling and hasn't confirmed a new uptrend yet.

Ultimately, the conviction score is a tool to help you make better decisions — not by telling you what to do, but by giving you a clear, systematic read on the market environment so you can act with confidence (or caution) as appropriate.
