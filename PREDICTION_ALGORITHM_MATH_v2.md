# Metal Price Prediction Algorithm v2.0 / v3.0
## Mathematical Specification Document

**Version:** 2.0 + v3.0 (Prediction Tab)  
**Date:** February 2026  
**Purpose:** Technical documentation reflecting analyst improvements and advisor-backed prediction accuracy fixes.

**Best use (backtest):** The algorithm is most useful as a **likely band** (Low–High) for price in 7 days (~64% in-range). Direction and point forecast are not reliable (direction ~50%, point error ~5%). The UI leads with the range and de-emphasizes up/down and exact level.

---

## Summary of v2.0 Changes

| Issue | Fix Applied |
|-------|-------------|
| Time-scale mismatch | Range multiplier changed from 1.5 to √7 ≈ 2.65 |
| SMA "ghosting" | Implemented Wilder's EMA for RSI and ATR |
| Linear momentum bias | Clamped ExpectedMove to ±10% |
| Missing macro factor | Added DXY (USD Index) as 6th confidence factor |
| Fixed ratio pressure | Adaptive ratio pressure: `|ρ| × 0.15` |
| Equal confidence weights | Correlation now weighted 40%, DXY factor added |
| Poor Copper pairing | Auto-suggests S&P 500 for Copper |
| Simple returns | Switched to log returns throughout |

---

## Summary of v3.0 Prediction-Tab Changes (Advisor-Backed)

| Issue (from backtests) | Fix Applied |
|------------------------|-------------|
| Down-market accuracy ~23% (Silver/Gold) | Regime detection (S&P 500 vs 50d MA); in Bear regime apply 0.8× safety to ExpectedMove and shrink beta |
| Static ±10% clamp missed large moves | Dynamic clamp: Normal ±10%, Elevated vol ±15%, Crisis/regime change ±25% |
| Momentum lag; ratio pressure in downtrends | Bearish filter: when primary 14d momentum &lt; 0, zero out ratio pressure |
| 60-day correlation misses regime changes | Dual correlation: 10-day (fast) and 60-day (slow); if divergence &gt; 0.3 → regime change, cap confidence at 50%, shrink beta |
| Beta amplifies errors in crashes | Regime-aware beta: multiply beta by 0.7 in Bear regime or when regime change detected |
| Confidence not predictive of accuracy | Reweight: Correlation 50%, DXY 15%, Regime Fit 15%, RSI/Volatility/Ratio 10% each; cap confidence at 50% when regime change |

---

## 1. Data Inputs

### Source Data
- **Primary Metal (P)**: The metal being predicted (Gold, Silver, Platinum, Copper)
- **Secondary (S)**: Comparison asset (Gold, Silver, Platinum, Copper, or S&P 500)
- **DXY**: US Dollar Index (fetched automatically for confidence calculation)
- **Data Period**: 3 months (~63 trading days)

### Auto-Suggested Pairings
| Primary | Suggested Secondary | Rationale |
|---------|---------------------|-----------|
| Silver | Gold | Traditional Gold-Silver Ratio |
| Gold | Silver | Inverse GSR |
| Platinum | Gold | Both precious metals |
| Copper | S&P 500 | Industrial correlation |

### Constants
```python
SQRT_7 = 2.6457513110645907  # √7 for weekly volatility scaling
TROY_OUNCE_TO_GRAMS = 31.1035
```

---

## 2. RSI (Relative Strength Index) - Wilder's EMA

### Formula (Updated v2.0)

**Step 1: Calculate daily price changes**
$$\Delta_i = P_i - P_{i-1}$$

**Step 2: Separate gains and losses**
$$\text{Gain}_i = \max(\Delta_i, 0)$$
$$\text{Loss}_i = \max(-\Delta_i, 0)$$

**Step 3: Seed with SMA for first 14 periods**
$$\text{AvgGain}_0 = \frac{1}{14} \sum_{i=1}^{14} \text{Gain}_i$$
$$\text{AvgLoss}_0 = \frac{1}{14} \sum_{i=1}^{14} \text{Loss}_i$$

**Step 4: Apply Wilder's smoothing for subsequent periods**
$$\text{AvgGain}_t = \frac{(\text{AvgGain}_{t-1} \times 13) + \text{Gain}_t}{14}$$
$$\text{AvgLoss}_t = \frac{(\text{AvgLoss}_{t-1} \times 13) + \text{Loss}_t}{14}$$

**Step 5: Calculate RSI**
$$RS = \frac{\text{AvgGain}_t}{\text{AvgLoss}_t}$$
$$RSI = 100 - \frac{100}{1 + RS}$$

### Why Wilder's EMA?
- Eliminates "ghosting" where old data dropping off causes sudden jumps
- Gives more weight to recent data
- Industry standard for RSI calculation

---

## 3. ATR (Average True Range) - Wilder's EMA

### Formula (Updated v2.0)

**Step 1: Calculate True Range**
$$TR_i = \max(H_i - L_i, |H_i - C_{i-1}|, |L_i - C_{i-1}|)$$

**Step 2: Seed with SMA**
$$ATR_0 = \frac{1}{14} \sum_{i=1}^{14} TR_i$$

**Step 3: Apply Wilder's smoothing**
$$ATR_t = \frac{(ATR_{t-1} \times 13) + TR_t}{14}$$

---

## 4. Momentum - Log Returns

### Formula (Updated v2.0)

**Internal calculation using log returns:**
$$M_{log} = \ln\left(\frac{P_0}{P_{-n}}\right)$$

**Conversion to percentage for display:**
$$M_{\%} = (e^{M_{log}} - 1) \times 100$$

### Why Log Returns?
- Additive over time (can sum daily log returns for period return)
- Symmetric: -50% and +50% don't cancel to 0%
- Better handles the "volatility smile"
- Standard in quantitative finance

---

## 5. Dynamic Beta - Log Returns

### Formula (Updated v2.0)

**Step 1: Calculate daily log returns**
$$r^P_i = \ln\left(\frac{P_i}{P_{i-1}}\right)$$
$$r^S_i = \ln\left(\frac{S_i}{S_{i-1}}\right)$$

**Step 2: Calculate means**
$$\bar{r}^P = \frac{1}{n} \sum_{i=1}^{n} r^P_i$$
$$\bar{r}^S = \frac{1}{n} \sum_{i=1}^{n} r^S_i$$

**Step 3: Calculate covariance and variance**
$$\text{Cov}(P,S) = \frac{1}{n} \sum_{i=1}^{n} (r^P_i - \bar{r}^P)(r^S_i - \bar{r}^S)$$
$$\text{Var}(S) = \frac{1}{n} \sum_{i=1}^{n} (r^S_i - \bar{r}^S)^2$$

**Step 4: Calculate beta**
$$\beta = \frac{\text{Cov}(P,S)}{\text{Var}(S)}$$

**Clamped to:** $[0.1, 5.0]$

---

## 6. Correlation

### Formula
$$\rho = \frac{\text{Cov}(P,S)}{\sqrt{\text{Var}(P)} \cdot \sqrt{\text{Var}(S)}}$$

Uses the same log returns as beta calculation.

---

## 7. Predicted Price (Updated v2.0)

### Formula

**Step 1: Secondary momentum (log returns)**
$$M^S_{log} = \ln\left(\frac{\bar{S}_{7d}}{\bar{S}_{14d}}\right)$$
$$M^S = e^{M^S_{log}} - 1$$

**Step 2: Expected move with CLAMP**
$$\text{RawMove} = M^S \times \beta$$
$$\text{ExpectedMove} = \text{clamp}(\text{RawMove}, -0.10, +0.10)$$

The ±10% clamp prevents extreme predictions from "fat tail" events.

**Step 3: Adaptive Ratio Pressure**
$$\text{RatioDeviation} = \frac{R_0 - \bar{R}_{28d}}{\bar{R}_{28d}}$$

$$\text{PressureMultiplier} = \begin{cases} 
0 & \text{if } \rho < 0 \\
|\rho| \times 0.15 & \text{otherwise}
\end{cases}$$

$$\text{RatioPressure} = \text{RatioDeviation} \times \text{PressureMultiplier}$$

**Why adaptive?**
- Strong correlation (ρ = 0.9): multiplier = 0.135 → mean reversion likely
- Weak correlation (ρ = 0.3): multiplier = 0.045 → metals decoupled
- Negative correlation: multiplier = 0 → ratio pressure disabled

**Step 4: Final prediction**
$$\hat{P} = P_0 \times (1 + \text{ExpectedMove} + \text{RatioPressure})$$

---

## 7b. v3.0 Prediction-Tab Additions (Advisor-Backed)

### Regime Detection
- **Data:** S&P 500 (^GSPC) is fetched for prediction tab when not already the secondary; 50-day MA is computed.
- **Regimes:**
  - **BULL:** S&P 500 > 50d MA → full sensitivity, recommend Gold as secondary.
  - **BEAR:** S&P 500 < 50d MA → apply safety factor 0.8× to ExpectedMove, shrink beta by 0.7×.
  - **SIDEWAYS:** Primary RSI between 45–55 → double ratio pressure (mean reversion).

### Dynamic Clamp (replaces fixed ±10%)
- **Normal:** ±10% when volatility (ATR/price) < 4%.
- **Elevated:** ±15% when volatility ≥ 4%.
- **Crisis:** ±25% when volatility ≥ 8% or when regime change is detected (fast vs slow correlation divergence > 0.3).

### Dual Correlation & Regime Change
- **Fast correlation:** 10-day log-return correlation between primary and secondary.
- **Slow correlation:** 60-day (existing beta window).
- **Regime change:** If |ρ_fast − ρ_slow| > 0.3 → cap confidence at 50%, shrink beta by 0.7×, allow ±25% clamp.

### Bearish Filter
- When primary 14-day momentum is negative, **ratio pressure is set to zero** to avoid false “buy” signals in downtrends.

### Confidence v3 Weights
- Correlation 50%, DXY 15%, Regime Fit 15%, RSI 10%, Volatility 10%, Ratio 10%.
- **Regime Fit:** Full points when (BULL + Gold), (BEAR + S&P 500), or (SIDEWAYS + ratio within 10% of average).
- **Cap:** Confidence is capped at 50% when regime change is detected.

---

## 8. Price Range (Updated v2.0)

### Formula
$$\text{Low} = \hat{P} - (ATR \times \sqrt{7})$$
$$\text{High} = \hat{P} + (ATR \times \sqrt{7})$$

### Why √7?
Volatility scales with the square root of time:
- Daily ATR represents 1-day volatility
- 7-day volatility ≈ Daily volatility × √7 ≈ 2.65×

Previous multiplier (1.5) was too narrow, causing frequent "failed" predictions.

---

## 9. Confidence Score (Updated v2.0)

### 6-Factor System with Weighted Scoring

**Non-Copper Metals (Silver, Gold, Platinum):**
| Factor | Max Points | Description |
|--------|------------|-------------|
| Trend Agreement | 12 | Both assets trending same direction |
| RSI Range | 12 | RSI in neutral zone (30-70) |
| Volatility | 12 | Low volatility (< 2%) |
| Ratio Stability | 12 | Ratio within 5% of 28d average |
| **Correlation** | **40** | Strong correlation (≥ 0.7) |
| DXY Health | 12 | Inverse correlation with USD |
| **Total** | **100** | |

**Copper (Industrial Metal):**
| Factor | Max Points | Description |
|--------|------------|-------------|
| Trend Agreement | 14 | |
| RSI Range | 14 | |
| Volatility | 14 | |
| Ratio Stability | 14 | |
| **Correlation** | **40** | |
| DXY Health | **4** | Less relevant for industrial metal |
| **Total** | **100** | |

### Factor 6: DXY Health (New in v2.0)

**Logic:**
Precious metals are priced in dollars. A "healthy" trend is when metals move inversely to the dollar.

**Calculation:**
1. Fetch 14-day correlation between primary metal and DXY
2. Score based on correlation:

| DXY Correlation | Points | Interpretation |
|-----------------|--------|----------------|
| ≤ -0.5 | Full | Healthy inverse relationship |
| -0.5 to 0 | Partial (scaled) | Mild inverse |
| ≥ 0 | 0 | Unhealthy - both rising together |

---

## 10. Complete Prediction Flow

```
┌─────────────────────────────────────────────────────────────┐
│                     DATA FETCHING                           │
├─────────────────────────────────────────────────────────────┤
│  Yahoo Finance API                                          │
│  ├── Primary Metal (3 months OHLC)                         │
│  ├── Secondary Asset (3 months OHLC)                       │
│  └── DXY - US Dollar Index (3 months)                      │
│                                                             │
│  Convert metals to $/gram                                   │
│  S&P 500 and DXY: no conversion (index points)             │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              TECHNICAL INDICATORS (Wilder's EMA)            │
├─────────────────────────────────────────────────────────────┤
│  RSI = 100 - (100 / (1 + RS))          [14-day, EMA]       │
│  ATR = Wilder's smoothed True Range    [14-day, EMA]       │
│  Momentum = (e^log_return - 1) × 100   [7d and 14d]        │
│  Volatility = ATR / Price × 100%                           │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              CROSS-ASSET METRICS (Log Returns)              │
├─────────────────────────────────────────────────────────────┤
│  Beta = Cov(P,S) / Var(S)              [60-day window]     │
│  Correlation = Cov / (σP × σS)         [Pearson]           │
│  DXY Correlation                       [14-day window]      │
│  Metal Ratio = S / P                                        │
│  Ratio Deviation = (R₀ - R̄₂₈) / R̄₂₈                        │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    PREDICTION FORMULA (v3)                   │
├─────────────────────────────────────────────────────────────┤
│  Regime = BULL | BEAR | SIDEWAYS (S&P 50d MA + primary RSI) │
│  Dual correlation: 10d and 60d; regime change if |ρ₁₀−ρ₆₀|>0.3 │
│                                                             │
│  Secondary Momentum = (7d_avg / 14d_avg) - 1   [log]       │
│  Beta_shrunk = Beta × 0.7 if BEAR or regime change          │
│  Expected Move = Momentum × Beta_shrunk                     │
│  Expected Move ×= 0.8 if BEAR (safety factor)              │
│  Expected Move = CLAMP(ExpectedMove, ±10%|±15%|±25%)       │
│    (dynamic: normal / elevated vol / crisis or regime chg)  │
│                                                             │
│  Pressure Multiplier = |correlation| × 0.15 (×2 if SIDEWAYS)│
│  Ratio Pressure = 0 if primary 14d momentum < 0 (bearish)    │
│  else Ratio Pressure = Deviation × Multiplier              │
│                                                             │
│  Predicted Price = P₀ × (1 + ExpectedMove + RatioPressure) │
│  Range Low  = Predicted - (ATR × √7)                       │
│  Range High = Predicted + (ATR × √7)                       │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  CONFIDENCE CALCULATION (v3)                │
├─────────────────────────────────────────────────────────────┤
│  Factor 1: Regime Fit             (15 pts)                  │
│  Factor 2: RSI Range              (10 pts)                  │
│  Factor 3: Volatility             (10 pts)                  │
│  Factor 4: Ratio Stability        (10 pts)                  │
│  Factor 5: Correlation            (50 pts) ← HEAVY WEIGHT   │
│  Factor 6: DXY Health             (15 pts; Copper: 5)      │
│  ─────────────────────────────────────────                 │
│  Total: 100 points                                          │
│  Cap: confidence ≤ 50% when regime change detected         │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   OUTPUT & DISPLAY                          │
├─────────────────────────────────────────────────────────────┤
│  Predicted Price: $X.XXXX/g                                │
│  Change: +X.XX% / -X.XX%                                   │
│  Confidence: XX%                                            │
│  Range: $Low - $High                                        │
│  Breakdown: All calculation steps shown                     │
└─────────────────────────────────────────────────────────────┘
```

---

## 11. Validation & Grading

The system tracks predictions and grades them after the 7-day target:

**Metrics Calculated:**
- Direction accuracy: Did we predict up/down correctly?
- Error %: `(Actual - Predicted) / Predicted × 100`
- Grade: A+ (< 1% error) to F (> 10% error)

**Grading Scale:**
| Error | Grade |
|-------|-------|
| < 1% | A+ |
| 1-2% | A |
| 2-3% | B+ |
| 3-4% | B |
| 4-5% | C+ |
| 5-7% | C |
| 7-10% | D |
| > 10% | F |

---

## Appendix: Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| RSI Period | 14 days | Industry standard |
| ATR Period | 14 days | Industry standard |
| Beta Window | 60 days | Balance of responsiveness and stability |
| Ratio History | 28 days | Monthly average |
| Range Multiplier | √7 ≈ 2.65 | Proper time-scaling |
| Beta Clamp | [0.1, 5.0] | Prevent extreme values |
| ExpectedMove Clamp (v3) | ±10% / ±15% / ±25% | Dynamic: normal / elevated / crisis |
| Pressure Scaling | |ρ| × 0.15 | Linear; ×2 in SIDEWAYS regime |
| Correlation Weight (v3) | 50/100 pts | Strongest predictor in backtests |
| DXY Weight (v3, metals) | 15/100 pts | USD strength primary for silver |
| DXY Weight (v3, copper) | 5/100 pts | Less relevant for industrial |
| Regime MA | 50 days | S&P 500 vs 50d MA for BULL/BEAR |
| Correlation Fast | 10 days | Regime change: |ρ₁₀−ρ₆₀| > 0.3 |
| Bear Safety Factor | 0.8 | Scale ExpectedMove in BEAR regime |
| Regime Beta Shrink | 0.7 | In BEAR or regime change |
| Confidence Cap (regime change) | 50% | Avoid over-confidence before failure |

---

*Document updated to reflect v2.0 and v3.0 (prediction-tab) analyst/advisor improvements. All formulas implemented in `metal_calculator_gui.py`.*
