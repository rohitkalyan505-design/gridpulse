# GridPulse Deterministic Electrical Calculations

## Phase 2 — Step 3 Specification

This document details the deterministic electrical engineering calculations executed in Phase 2 Step 3. All calculations operate exclusively on validated telemetry, enforce physical conservation laws, and produce explicitly classified `CALCULATED` results with complete provenance.

---

## 1. Locked Calculation Flow

```
Validated Telemetry (ValidatedTelemetryRecord)
  ↓
Unit Normalization & Compatibility Verification
  ↓
Deterministic Closed-Form Formulas (No LLM, Pure Mathematics)
  ↓
Numerical Safety & Physical Domain Checks (Unit-Independent Near-Zero S, No Silent Clamping)
  ↓
Output Packaging (Evidence = CALCULATED)
  ↓
ElectricalFeaturesResult (Measured & Calculated Coexistence)
```

---

## 2. Mathematical Formulations

### A. Apparent Power from Active and Reactive Power

- **Formula**:
  $$S = \sqrt{P^2 + Q^2}$$
- **Input Quantities**:
  - $P$: Active power (`Measurement[float]`, evidence `MEASURED` or `CALCULATED`)
  - $Q$: Reactive power (`Measurement[float]`, evidence `MEASURED` or `CALCULATED`)
- **Compatible Units**:
  - $\text{kW} + \text{kVAR} \rightarrow \text{kVA}$
  - $\text{W} + \text{VAR} \rightarrow \text{VA}$
  - $\text{MW} + \text{MVAR} \rightarrow \text{MVA}$
  - Cross-prefix inputs are normalized to canonical $\text{kW}$ and $\text{kVAR}$ to yield $\text{kVA}$.
- **Output Quantity**: Apparent power $S$ (`Measurement[float]`)
- **Evidence Classification**: Strictly `EvidenceClassification.CALCULATED`.
- **Formula Identifier**: `"APPARENT_POWER_FROM_P_Q"`
- **Missing-Data Behavior**: If either $P$ or $Q$ is missing or `None`, $S$ cannot be derived. $Q$ is **never** assumed to be zero. A structured `ProcessingIssue` with code `ERR_INSUFFICIENT_TELEMETRY` is generated.
- **Numerical Edge Cases**: Non-finite values (`NaN`, `Inf`) are rejected with `ERR_NON_FINITE_INPUT`.

---

### B. GridPulse Signed Power Factor

- **Formula**:
  $$\text{PF} = \frac{P}{S}$$
- **Input Quantities**:
  - $P$: Active power (`Measurement[float]`)
  - $S$: Apparent power (`Measurement[float]`, derived or measured)
- **GridPulse Signed Convention**:
  - $P > 0$: Import / Power Consumption $\rightarrow \text{PF} > 0$
  - $P < 0$: Export / Power Generation $\rightarrow \text{PF} < 0$
  - $S \ge 0$: Apparent power magnitude is non-negative
  - Domain: $\text{PF} \in [-1.0, 1.0]$
  - Quadrant indicator: If $Q$ is available, $Q \ge 0$ indicates Inductive/Lagging; $Q < 0$ indicates Capacitive/Leading.
- **Unit-Independent Numerical Safety**:
  - To prevent division by zero or numerical instability on near-zero loads, $S$ is normalized to canonical $\text{kVA}$.
  - Threshold:
    $$S_{\text{canonical}} \le 10^{-6} \text{ kVA} \quad (1 \text{ mVA} = 0.001 \text{ VA})$$
  - If $S_{\text{canonical}}$ is at or below this threshold, division is avoided and `WARN_NEAR_ZERO_APPARENT_POWER` is logged. This threshold has a single consistent physical meaning regardless of whether $S$ is in $\text{VA}$, $\text{kVA}$, or $\text{MVA}$.
- **No Silent Clamping**:
  - If calculated $|\text{PF}| > 1.0$ (beyond floating-point precision tolerance $10^{-12}$), the engine **does not clamp** the result to $\pm 1.0$.
  - Clamping would mask corrupt active or apparent power inputs. Instead, the calculation is rejected with `ERR_CALCULATED_PF_DOMAIN_VIOLATION` to preserve diagnostic integrity.
- **Output Quantity**: Power factor (`Measurement[float]`, unit `"ratio"`)
- **Evidence Classification**: Strictly `EvidenceClassification.CALCULATED`.
- **Formula Identifier**: `"POWER_FACTOR_FROM_P_S"`

---

### C. Three-Phase Average Phase RMS Voltage

- **Formula**:
  $$V_{\text{avg}} = \frac{V_A + V_B + V_C}{3}$$
- **Explicit Physical Definition**: Average phase RMS voltage across the three electrical phases.
- **Scope Restriction**: This metric is strictly the arithmetic mean of phase voltages. It is **not** line-to-line voltage, not total three-phase voltage, and not a phase-balance metric.
- **Input Requirements**: All three phase voltages ($V_A, V_B, V_C$) must be present and valid with identical units.
- **Missing-Data Behavior**: If any phase voltage is missing or null, the calculation is aborted with `ERR_INSUFFICIENT_TELEMETRY`. Missing phase voltages are **never** invented.
- **Output Quantity**: Average phase voltage (`Measurement[float]`, unit matching input)
- **Evidence Classification**: Strictly `EvidenceClassification.CALCULATED`.
- **Formula Identifier**: `"AVERAGE_PHASE_VOLTAGE_3P"`

---

### D. Three-Phase Average Phase RMS Current

- **Formula**:
  $$I_{\text{avg}} = \frac{I_A + I_B + I_C}{3}$$
- **Explicit Physical Definition**: Average phase RMS current across the three electrical phases.
- **Scope Restriction**: This metric is strictly the arithmetic mean of phase currents. It is **not** total load current, not neutral current, and not a current unbalance factor.
- **Input Requirements**: All three phase currents ($I_A, I_B, I_C$) must be present and valid with identical units.
- **Missing-Data Behavior**: If any phase current is missing, $I_{\text{avg}}$ is not calculated and `ERR_INSUFFICIENT_TELEMETRY` is logged. Missing phase currents are **never** invented.
- **Output Quantity**: Average phase current (`Measurement[float]`, unit matching input)
- **Evidence Classification**: Strictly `EvidenceClassification.CALCULATED`.
- **Formula Identifier**: `"AVERAGE_PHASE_CURRENT_3P"`

---

## 3. Coexistence of Measured and Calculated Quantities

Telemetry systems often report both raw meter channels and derived meter quantities (e.g. meter-reported $S$ or $\text{PF}$). GridPulse preserves both values side-by-side in `ElectricalFeaturesResult`:

| Quantity       | Directly Metered Telemetry                 | Engine Closed-Form Formula                     | Coexistence in `ElectricalFeaturesResult`                                       |
| :------------- | :----------------------------------------- | :--------------------------------------------- | :------------------------------------------------------------------------------ |
| Apparent Power | `apparent_power_measured_kva` (`MEASURED`) | `apparent_power_calculated_kva` (`CALCULATED`) | Both preserved; primary `apparent_power_kva` retains measured value if present. |
| Power Factor   | `power_factor_measured` (`MEASURED`)       | `power_factor_calculated` (`CALCULATED`)       | Both preserved; primary `power_factor` retains measured value if present.       |

**Zero Silent Overwrite Rule**: A directly measured telemetry value is never overwritten or replaced by a calculated result.

---

## 4. Calculation Provenance Structure

Every calculated metric embeds structured provenance in its `Measurement.metadata`:

```json
{
  "formula_id": "APPARENT_POWER_FROM_P_Q",
  "equation": "sqrt(P^2 + Q^2)",
  "inputs": {
    "p": { "value": 125.0, "unit": "kW", "evidence": "MEASURED" },
    "q": { "value": 60.0, "unit": "kVAR", "evidence": "MEASURED" }
  },
  "asset_id": "TX-SUB01-DT04",
  "calculation_timestamp": "2026-09-23T12:00:00+00:00"
}
```

---

## 5. Scope Exclusions (Deferred to Later Steps)

In strict adherence to the Phase 2 roadmap:

- **No Three-Phase Total Power Aggregation**: Excluded from Step 3.
- **No Transformer Loading**: Loading ratios ($S / S_{\text{rated}}$) and capacity utilization are deferred to Step 4.
- **No Thermal Degradation**: Top-oil and hot-spot differential equations are deferred to Step 5.
- **No Phase Imbalance / Symmetrical Components**: Fortescue transformations, VUF, PVUR, and CUF are deferred to Step 6.
- **No Machine Learning / Anomaly Detection**: Deferred to Step 7.
- **No Decision Scoring / Health Indices**: Deferred to Step 8.
