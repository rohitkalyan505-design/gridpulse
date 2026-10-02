# GridPulse Overall Transformer Loading & Overload Analytics

## Phase 2 — Step 4 Specification

This document details the deterministic physical formulations, screening-band conventions, forward-interval time-weighted loading algorithms, and overload cycle tracking implemented in Phase 2 Step 4. All derivations operate exclusively on validated telemetry and deterministic electrical features from Step 3, enforce physical conservation laws, produce strictly `CALCULATED` evidence, and maintain comprehensive provenance.

---

## 1. Locked Calculation Flow

```
Electrical Features (ElectricalFeaturesResult) + Asset Specification (TransformerAssetSpec)
  ↓
Operational Limits & Threshold Invariant Verification
  - 0 < continuous_threshold < emergency_threshold
  - 0.80 <= continuous_threshold < emergency_threshold
  - (No silent default substitution, no silent clamping)
  ↓
Canonical kVA Normalization (VA / kVA / MVA → kVA)
  ↓
Instantaneous Loading Metrics (L = S_actual / S_rated, L% = L * 100)
  ↓
Deterministic Screening-Band Classification
  - LIGHT | NORMAL | ELEVATED | CONTINUOUS_OVERLOAD | EMERGENCY_OVERLOAD
  ↓
Forward-Interval Time-Weighted Average (Zero Interpolation)
  - L_k governs [t_k, t_{k+1}); Δt_k = t_{k+1} - t_k; final Δt_N = 0
  - Continuity breaks on gaps > max_gap or BAD / MISSING quality
  ↓
Peak Loading Tracking (From Usable Observations Only)
  ↓
Deterministic Overload Cycles & Continuity Break Segmentation
  ↓
Output Packaging (Evidence = CALCULATED, Zero Per-Phase Fields)
  ↓
TransformerLoadingResult
```

---

## 2. Configuration Invariants & Threshold Validation

### A. Threshold Invariants

Every transformer evaluation strictly verifies:

1. $0 < \text{continuous\_threshold} < \text{emergency\_threshold}$
2. $0.80 \le \text{continuous\_threshold} < \text{emergency\_threshold}$
3. Both thresholds must be finite, non-zero positive numbers (`math.isfinite(threshold) == True`).

where:

- $\text{continuous\_threshold} = \text{asset\_spec.operational\_limits.max\_continuous\_loading\_pu}$
- $\text{emergency\_threshold} = \text{asset\_spec.operational\_limits.emergency\_loading\_pu}$

### B. Rejection Behavior

If any invariant is violated:

- The engine **does not silently substitute defaults** (e.g., $1.0\text{ pu}$ or $1.4\text{ pu}$).
- The engine **does not silently clamp or modify thresholds**.
- The engine **does not calculate a loading state**.
- The invalid configuration is preserved in the diagnostic payload.
- Execution emits a `ProcessingIssue` with `severity=IssueSeverity.CRITICAL` and `code="ERR_INVALID_LOADING_THRESHOLD_CONFIGURATION"`.

### C. Rated Capacity Invariant

- $S_{\text{rated, kVA}} = \text{asset\_spec.rated\_power\_kva}$ must be strictly positive and finite ($S_{\text{rated, kVA}} > 0$).
- Non-positive or non-finite values are rejected with `ERR_NON_POSITIVE_RATED_CAPACITY`.
- Values $< 1.0\text{ kVA}$ trigger an engineering advisory warning `WARN_NEAR_ZERO_RATED_POWER`.

---

## 3. Deterministic Screening Bands & Standards Qualification

### A. Screening Bands

GridPulse segments overall transformer loading into five deterministic intervals:

| Screening Band          | Loading Ratio Range                                                | Operational Significance                      |
| :---------------------- | :----------------------------------------------------------------- | :-------------------------------------------- |
| **LIGHT**               | $0.00 \le L < 0.30$                                                | Low asset utilization regime                  |
| **NORMAL**              | $0.30 \le L \le 0.80$                                              | Optimal, efficient operating regime           |
| **ELEVATED**            | $0.80 < L \le \text{continuous\_threshold}$                        | High utilization approaching rated capacity   |
| **CONTINUOUS_OVERLOAD** | $\text{continuous\_threshold} < L \le \text{emergency\_threshold}$ | Operating beyond continuous rating            |
| **EMERGENCY_OVERLOAD**  | $L > \text{emergency\_threshold}$                                  | Operating beyond emergency screening boundary |

### B. Clarification of Screening Boundaries

> The $0.30$ and $0.80\text{ pu}$ boundaries are GridPulse configurable screening conventions used to segment asset utilization regimes. They are not universal transformer physical limits. In contrast, $\text{continuous\_threshold}$ and $\text{emergency\_threshold}$ represent active, asset-specific operational limits derived from manufacturer nameplate ratings and utility operating standards.

### C. Mandatory 1.4 pu Reference Qualification

> **"1.4 pu is the GridPulse default screening convention when no asset-specific emergency threshold is configured. It is not a universal physical emergency limit established for every transformer by the cited standards."**

Citations to **IEC 60076-7** and **IEEE C57.91** serve purely as engineering reference context for standard loading guide nomenclature and baseline conventions. They do **not** imply that thermal validation has been performed. Actual permissible emergency loading duration and peak magnitude remain strictly asset-, cooling-, and ambient condition-dependent. Thermal analysis, hot-spot rise, and loss-of-life calculations are deferred to **Phase 2 Step 5**.

---

## 4. Mathematical Formulations

### A. Canonical Apparent Power Resolution

- **Input Quantities**: Effective apparent power $S$ from `ElectricalFeaturesResult`.
- **Coexistence Preservation**: Both `apparent_power_measured_kva` and `apparent_power_calculated_kva` are preserved without destroying provenance.
- **Unit Normalization**:
  $$ S_{\text{actual, kVA}} = \begin{cases}
  S \times 0.001 & \text{if unit } = \text{"VA"} \\
  S \times 1.0 & \text{if unit } = \text{"kVA"} \\
  S \times 1000.0 & \text{if unit } = \text{"MVA"}
  \end{cases}$$
  $$

### B. Instantaneous Loading Ratios

- **Loading Ratio ($L$)**:
  $$L = \frac{S_{\text{actual, kVA}}}{S_{\text{rated, kVA}}} \quad [\text{unit: "pu"}]$$
- **Loading Percentage ($L_{\%}$)**:
  $$L_{\%} = L \times 100.0 \quad [\text{unit: "percent"}]$$
- **Evidence Classification**: Strictly `EvidenceClassification.CALCULATED`.

### C. Forward-Interval Sample-and-Hold Time-Weighted Average

For a chronological sequence of telemetry observations $(t_0, L_0), (t_1, L_1), \dots, (t_N, L_N)$:

- The observation $L_k$ at $t_k$ represents the system loading state across the **forward interval**:
  $$[t_k, t_{k+1})$$
- The interval duration is:
  $$\Delta t_k = t_{k+1} - t_k$$
- The time-weighted average loading is:
  $$\bar{L}_{\text{tw}} = \frac{\sum (L_k \times \Delta t_k)}{\sum \Delta t_k}$$
- **Boundary Rules**:
  - The first observation $L_0$ governs $[t_0, t_1)$.
  - The final observation $(t_N, L_N)$ has no following observation and contributes:
    $$\Delta t_N = 0$$
- **Zero Interpolation Mandate**:
  - **Do NOT use trapezoidal averaging**: $\frac{L_k + L_{k+1}}{2} \times \Delta t$ is strictly prohibited.
  - **Do NOT assume linear or continuous behavior** between discrete observations.

### D. Data Quality & Continuity Constraints

An interval $[t_k, t_{k+1})$ contributes to $\bar{L}_{\text{tw}}$ if and only if:

1. Both record $k$ and record $k+1$ are valid and usable.
2. $0 < \Delta t_k \le \text{max\_gap}$, where $\text{max\_gap} = 2 \times \text{nominal\_interval\_seconds}$.
3. Neither record carries `MeasurementQuality.BAD`, `OUT_OF_RANGE`, or `MISSING`.
4. Neither record carries `EvidenceClassification.UNKNOWN`.

If continuity is broken, the interval is excluded from duration and weighted loading sums. The engine **never bridges or interpolates across gaps**.

### E. Peak Loading Tracking

$$L_{\text{peak}} = \max_{k \in \text{usable}} (L_k)$$
$L_{\text{peak}}$ is tracked alongside its observed UTC timestamp $t_{\text{peak}}$ and observed apparent power $S_{\text{peak, kVA}}$. Corrupted, missing, or invalid telemetry records cannot become the peak.

### F. Deterministic Overload Cycles

1. **Cycle Start**: A cycle begins at the first valid record where $L_k > \text{continuous\_threshold}$.
2. **Cycle Accumulation**: Duration accumulates forward intervals $[t_k, t_{k+1})$ where continuous overload is verified.
3. **Normal Termination**: Terminated at $t_{k+1}$ when $L_{k+1} \le \text{continuous\_threshold}$.
4. **Continuity Break**: If $\Delta t_k > \text{max\_gap}$ or bad/missing telemetry occurs while overloaded:
   - The cycle is closed immediately at the last valid overloaded timestamp $t_k$.
   - No unobserved duration is added.
   - `continuity_break_detected` is set to `True`.
   - A structured `WARN_TELEMETRY_CONTINUITY_BREAK` warning is emitted.
5. **Cycle Severity**:
   - `CONTINUOUS_OVERLOAD`: if $\max(L_{\text{cycle}}) \le \text{emergency\_threshold}$.
   - `EMERGENCY_OVERLOAD`: if $\max(L_{\text{cycle}}) > \text{emergency\_threshold}$.

---

## 5. Contract Schema & Zero Phase-Loading Invariant

`TransformerLoadingResult` defines overall transformer loading only:

```python
@dataclass(frozen=True)
class TransformerLoadingResult:
    is_computed: bool = False
    loading_ratio_pu: Optional[Measurement[float]] = None
    loading_percent: Optional[Measurement[float]] = None
    loading_state: Optional[LoadingState] = None
    total_apparent_power_kva: Optional[Measurement[float]] = None
    time_weighted_average_loading_pu: Optional[Measurement[float]] = None
    peak_loading_ratio_pu: Optional[Measurement[float]] = None
    peak_loading_timestamp: Optional[datetime] = None
    is_overloaded: bool = False
    is_emergency: bool = False
    total_overload_duration_seconds: float = 0.0
    overload_cycles: List[OverloadCycle] = field(default_factory=list)
    calculation_provenance: Dict[str, Any] = field(default_factory=dict)
```

**Zero Per-Phase Fields Rule**:
`TransformerLoadingResult` contains **NO** `phase_a_loading_pu`, `phase_b_loading_pu`, or `phase_c_loading_pu`. These fields are completely excluded and deferred to **Phase 2 Step 6**.

---

## 6. Diagnostic Issue Codes

| Issue Code                                    | Severity   | Description                                                                                                         |
| :-------------------------------------------- | :--------- | :------------------------------------------------------------------------------------------------------------------ |
| `ERR_INVALID_LOADING_THRESHOLD_CONFIGURATION` | `CRITICAL` | Threshold order ($0 < \text{cont} < \text{emerg}$) or lower bound ($\text{cont} \ge 0.80$) violated, or non-finite. |
| `ERR_NON_POSITIVE_RATED_CAPACITY`             | `CRITICAL` | Nameplate rating $S_{\text{rated, kVA}} \le 0$ or non-finite.                                                       |
| `ERR_INSUFFICIENT_TELEMETRY`                  | `WARNING`  | Missing or null apparent power in telemetry record.                                                                 |
| `ERR_NON_FINITE_INPUT`                        | `CRITICAL` | Apparent power is `NaN` or `Inf`.                                                                                   |
| `WARN_TELEMETRY_CONTINUITY_BREAK`             | `WARNING`  | Telemetry gap $> \text{max\_gap}$ or bad telemetry during active overload.                                          |
| `WARN_NEAR_ZERO_RATED_POWER`                  | `WARNING`  | Asset rated capacity $< 1.0\text{ kVA}$.                                                                            |
