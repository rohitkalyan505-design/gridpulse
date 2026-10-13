# GridPulse Phase Imbalance, Symmetrical Components & Derating Analytics

## Phase 2 — Step 6 Specification

This document details the deterministic electrical formulations, mathematical transformations, evidence classifications, diagnostic invariants, and safety boundaries implemented in Phase 2 Step 6 for three-phase asymmetrical loading, Fortescue symmetrical components, neutral current analysis, and evidence-grounded transformer derating.

All derivations operate exclusively on validated telemetry, deterministic electrical features from Step 3, and explicit three-phase inputs, strictly adhering to GridPulse scientific invariants.

---

## 1. Locked Calculation Flow

```
Three-Phase Inputs (ThreePhaseQuantity) or Electrical Features (ElectricalFeaturesResult)
  + Transformer Asset Specification (TransformerAssetSpec)
  ↓
Validation & Pre-computation Checks
  - Completeness of three phases (A, B, C non-null, finite, non-negative)
  - Unit consistency (all V, kV, or A; canonical normalization)
  - Timestamp synchronization (phases within <= 1.0 s; asynchronous samples rejected)
  ↓
Phase Magnitude Imbalance (Voltage & Current)
  - Arithmetic Mean: X_mean = (Xa + Xb + Xc) / 3
  - Signed Deviations: Delta X_i = X_i - X_mean
  - Absolute Deviations: |Delta X_i|
  - Max Absolute Deviation: max(|Delta X_i|)
  - Percentage Deviation: PVUR / CMUR = (max(|Delta X_i|) / X_mean) * 100%
  - Zero / Non-positive mean: returns UNKNOWN for percentage, WARN_ZERO_MEAN_MAGNITUDE
  ↓
Phasor Angle Verification & Guard
  - Are complex phase angles valid and finite?
  - YES → Proceed to Symmetrical Components
  - NO  → Reject Symmetrical Components (ERR_MISSING_PHASOR_ANGLES);
          Magnitude-only readings NEVER fabricate phase angles or sequence components
  ↓
Fortescue Symmetrical Components (When Complex Phasors Valid)
  - Sequence operator: a = exp(j * 2*pi/3) = -0.5 + j*sqrt(3)/2
  - Positive sequence convention: ABC (or configured ACB)
  - Zero sequence: X0 = (Xa + Xb + Xc) / 3
  - Positive sequence: X1 = (Xa + a*Xb + a^2*Xc) / 3
  - Negative sequence: X2 = (Xa + a^2*Xb + a*Xc) / 3
  - Inverse Reconstruction Check: |Xa - Xa_rec| < 1e-9
  - Sequence Ratios (if |X1| > 1e-6):
      VUF = 100 * |V2| / |V1|  (IEC 61000-4-30 / IEC 60076)
      CUF = 100 * |I2| / |I1|
  - Neutral return current (4-wire current phasors):
      In = -(Ia + Ib + Ic) = -3 * I0, |In| = 3 * |I0|
  ↓
Evidence-Grounded Transformer Derating Assessment
  - Maximum phase current capacity method: k_derate = mean_I / max_I
  - Loss-based negative-sequence method: requires verified factory test loss ratios
  - Operational limit verification: checks against max_voltage_unbalance_percent
  - Refusal of ungrounded motor curves (NEMA MG-1 motor curve physically invalid for transformers)
  ↓
Output Packaging (Evidence = CALCULATED / MODELED / UNKNOWN)
  ↓
PhaseImbalanceResult
```

---

## 2. Supported Input Contracts and Measurement Representation

### A. Three-Phase Quantities (`ThreePhaseQuantity`)

Each three-phase observation encapsulates three explicit phase quantities:

- **`phase_a`**, **`phase_b`**, **`phase_c`**: `PhaseQuantity` objects.
- **`neutral`**: Optional `PhaseQuantity` for four-wire connections.
- **`phase_sequence`**: Configured rotation, defaulting to `PhaseSequence.ABC`.
- **`asset_id`**: Non-empty asset identifier.
- **`timestamp`**: Timezone-aware UTC timestamp.

### B. Phase Quantity (`PhaseQuantity`)

- **`magnitude`**: `Measurement[float]` representing RMS magnitude ($V$ or $A$).
- **`angle_deg`**: Optional `Measurement[float]` representing phase angle in degrees $[-180^\circ, 180^\circ]$.
- **`angle_convention`**: Explicit reference convention (`PhasorAngleConvention.COSINE_REFERENCE`).
- **Phasor Validity**: `is_phasor` is `True` only when both magnitude and angle are finite, valid numbers and magnitude $\ge 0.0$.

### C. Fallback Extraction from Step 3 Features

When explicit synchrophasor/PMU telemetry is unavailable, the engine automatically extracts magnitude-only phase quantities from `ElectricalFeaturesResult`:
- $V_a, V_b, V_c$ from `v_a_rms, v_b_rms, v_c_rms`
- $I_a, I_b, I_c$ from `i_a_rms, i_b_rms, i_c_rms`

Because standard electrical features lack phase angles, the engine evaluates magnitude unbalance metrics (PVUR, CMUR) but **strictly refuses to fabricate symmetrical components**.

---

## 3. Mathematical Formulations

### A. Phase Magnitude Imbalance

For phase quantities $X \in \{V, I\}$ with phase magnitudes $X_a, X_b, X_c \ge 0$:

1. **Arithmetic Mean Magnitude:**
   $$\bar{X} = \frac{X_a + X_b + X_c}{3}$$

2. **Phase Signed Deviations:**
   $$\Delta X_a = X_a - \bar{X}, \quad \Delta X_b = X_b - \bar{X}, \quad \Delta X_c = X_c - \bar{X}$$

3. **Phase Absolute Deviations:**
   $$|\Delta X_a| = |X_a - \bar{X}|, \quad |\Delta X_b| = |X_b - \bar{X}|, \quad |\Delta X_c| = |X_c - \bar{X}|$$

4. **Maximum Absolute Deviation:**
   $$\Delta X_{\max} = \max\left(|\Delta X_a|, |\Delta X_b|, |\Delta X_c|\right)$$

5. **Percentage Deviation (Mean-based Denominator):**
   $$\text{Unbalance}_{\text{mag}}\% = \frac{\Delta X_{\max}}{\bar{X}} \times 100\%$$
   - **Voltage:** Referred to as the Phase Voltage Unbalance Rate (PVUR) per IEEE Std 141.
   - **Current:** Current Magnitude Unbalance Rate (CMUR).
   - **Zero-Mean Safeguard:** If $\bar{X} \le 0$, division by zero is strictly avoided; the percentage metric returns `None` (`UNKNOWN`) and emits `WARN_ZERO_MEAN_MAGNITUDE`.

### B. Fortescue Symmetrical Components

For valid complex RMS phasors $\mathbf{X}_a, \mathbf{X}_b, \mathbf{X}_c$:

1. **Complex Rotation Operator:**
   $$\alpha = e^{j 2\pi/3} = -\frac{1}{2} + j \frac{\sqrt{3}}{2}, \quad \alpha^2 = e^{j 4\pi/3} = -\frac{1}{2} - j \frac{\sqrt{3}}{2}$$

2. **Transformation Matrix (ABC Positive Sequence):**
   $$\mathbf{X}_0 = \frac{1}{3} \left(\mathbf{X}_a + \mathbf{X}_b + \mathbf{X}_c\right)$$
   $$\mathbf{X}_1 = \frac{1}{3} \left(\mathbf{X}_a + \alpha \mathbf{X}_b + \alpha^2 \mathbf{X}_c\right)$$
   $$\mathbf{X}_2 = \frac{1}{3} \left(\mathbf{X}_a + \alpha^2 \mathbf{X}_b + \alpha \mathbf{X}_c\right)$$

3. **Reverse Rotation (ACB Sequence):**
   $$\mathbf{X}_1 = \frac{1}{3} \left(\mathbf{X}_a + \alpha^2 \mathbf{X}_b + \alpha \mathbf{X}_c\right)$$
   $$\mathbf{X}_2 = \frac{1}{3} \left(\mathbf{X}_a + \alpha \mathbf{X}_b + \alpha^2 \mathbf{X}_c\right)$$

4. **Inverse Reconstruction Check:**
   $$\mathbf{X}_a' = \mathbf{X}_0 + \mathbf{X}_1 + \mathbf{X}_2$$
   $$\mathbf{X}_b' = \mathbf{X}_0 + \alpha^2 \mathbf{X}_1 + \alpha \mathbf{X}_2$$
   $$\mathbf{X}_c' = \mathbf{X}_0 + \alpha \mathbf{X}_1 + \alpha^2 \mathbf{X}_2$$
   $$\text{Error}_{\max} = \max\left(|\mathbf{X}_a - \mathbf{X}_a'|, |\mathbf{X}_b - \mathbf{X}_b'|, |\mathbf{X}_c - \mathbf{X}_c'|\right) < 10^{-9}$$

5. **Sequence Unbalance Ratios:**
   - **Voltage Unbalance Factor (VUF):**
     $$\text{VUF}\% = \frac{|\mathbf{V}_2|}{|\mathbf{V}_1|} \times 100\% \quad (\text{IEC 61000-4-30 / IEC 60076})$$
   - **Current Unbalance Factor (CUF):**
     $$\text{CUF}\% = \frac{|\mathbf{I}_2|}{|\mathbf{I}_1|} \times 100\%$$
   - **Degenerate Denominator Safeguard:** If $|\mathbf{X}_1| \le 10^{-6}$, ratios return `None` (`UNKNOWN`) and emit `ERR_DEGENERATE_POSITIVE_SEQUENCE`.

6. **Neutral Current in 4-Wire Systems:**
   $$\mathbf{I}_n = -(\mathbf{I}_a + \mathbf{I}_b + \mathbf{I}_c) = -3 \mathbf{I}_0$$
   $$I_{n, \text{rms}} = |\mathbf{I}_n| = 3 |\mathbf{I}_0|$$

---

## 4. Evidence-Grounded Transformer Derating

Derating is safety-sensitive: GridPulse explicitly enforces that **imbalance percentage alone does not automatically become a derating percentage**.

### A. Supported Methods

1. **Maximum Phase Current Capacity Method (`MAX_PHASE_CURRENT_CAPACITY`):**
   - **Physical Basis:** Under asymmetrical loading, the most heavily loaded phase conductor carries $I_{\max} = \max(I_a, I_b, I_c) > \bar{I}$. To prevent localized overheating and ensure the most loaded phase does not exceed rated continuous current, total three-phase throughput is derated:
     $$k_{\text{derate}} = \frac{\bar{I}}{I_{\max}} = \frac{1}{1 + \frac{\Delta I_{\max}}{\bar{I}}}$$
   - **Domain:** $0.0 < k_{\text{derate}} \le 1.0\text{ pu}$.
   - **Status:** Evaluated deterministically from valid current telemetry.

2. **Loss-Based Negative-Sequence Method (`LOSS_BASED_NEGATIVE_SEQUENCE`):**
   - **Physical Basis:** Additional eddy and stray losses induced by negative-sequence currents.
   - **Required Verified Parameters:**
     * Load-loss to no-load loss ratio: $R = P_{LL} / P_{NL}$
     * Winding eddy-current loss factor: $P_{\text{EC-R}}$
   - **Safety Boundary:** If $R$ or $P_{\text{EC-R}}$ are unverified or absent from the asset specification, the calculation **refuses speculative default substitution** and returns `status="UNVERIFIED"`, `derating_factor_pu=None`, and `WARN_UNVERIFIED_DERATING_PARAMETERS`.

### B. Prohibited Derating Practices

- **Induction Motor Derating Refusal:** NEMA MG-1 Clause 14.36 specifies a motor derating curve due to rotor negative-sequence slip and reverse torque ($I_2 \approx V_2 / X''$). Applying induction motor derating curves to static distribution transformers is an engineering category error and is prohibited.
- **Unverified Polynomials:** Empirical or unverified polynomial curves are rejected.

---

## 5. Diagnostic Issues Reference

| Issue Code | Severity | Description |
| :--- | :--- | :--- |
| `ERR_INCOMPLETE_THREE_PHASE_TELEMETRY` | WARNING | Telemetry missing for one or more phases (Phase A, B, or C). Imbalance calculation rejected without zero-fill. |
| `ERR_MISMATCHED_PHASE_TIMESTAMPS` | CRITICAL | Phase timestamps diverge by $> 1.0\,\text{s}$. Asynchronous observations cannot be combined. |
| `ERR_MISSING_PHASOR_ANGLES` | WARNING | Telemetry contains magnitudes only. Symmetrical components rejected without angle fabrication. |
| `ERR_INVALID_PHASE_IDENTIFICATION` | CRITICAL | Phase tag does not match required A, B, C, or N identity. |
| `ERR_INVALID_PHASE_SEQUENCE` | CRITICAL | Unrecognized phase rotation sequence (supported: ABC, ACB). |
| `ERR_DEGENERATE_POSITIVE_SEQUENCE` | WARNING | Positive-sequence magnitude $|\mathbf{X}_1| \le 10^{-6}$. Unbalance ratio calculation avoided. |
| `WARN_ZERO_MEAN_MAGNITUDE` | WARNING | Arithmetic mean magnitude $\bar{X} \le 0.0$. Percentage unbalance set to UNKNOWN. |
| `WARN_DERATING_METHOD_UNAVAILABLE` | WARNING / INFO | Requested derating method unsupported or required telemetry unavailable. |
| `WARN_UNVERIFIED_DERATING_PARAMETERS` | WARNING | Loss-based derating requested without verified asset test report coefficients ($R, P_{\text{EC}}$). |
| `WARN_VOLTAGE_UNBALANCE_EXCEEDS_LIMIT` | WARNING | Calculated voltage unbalance exceeds `operational_limits.max_voltage_unbalance_percent`. |
| `WARN_CURRENT_UNBALANCE_EXCEEDS_LIMIT` | WARNING | Calculated current unbalance exceeds `operational_limits.max_current_unbalance_percent`. |

---

## 6. Standards Verification Status

| Standard Reference | Clause / Equation | Description | Status |
| :--- | :--- | :--- | :--- |
| **IEC 61000-4-30:2015** | Clause 5.7 | Definition of Voltage Unbalance Factor: $\text{VUF} = 100 \times \|\mathbf{V}_2\| / \|\mathbf{V}_1\|$ | **Confirmed** |
| **IEC 60076-1:2011** | Clause 4.2 | Balanced voltage conditions and three-phase symmetrical component limits | **Confirmed** |
| **IEEE Std 141-1993** | Clause 3.9 | Phase Voltage Unbalance Rate (PVUR) maximum deviation from average | **Confirmed** |
| **IEEE Std C57.110-2018** | Clause 5.2 | Additional eddy-current heating from non-sinusoidal / asymmetrical currents | **Confirmed (Framework)**; requires verified asset loss parameters |
| **NEMA MG-1:2016** | Clause 14.36 | Induction motor derating curve | **Explicitly Excluded** for transformers |

---

## 7. Verification and Test Results

Run the complete scientific verification suite via:
```powershell
python -m pytest -v
```

**Results:**
- Total tests: **144 passed** (119 historical + 25 Step 6).
- Skipped / Failed: **0**.
- Execution duration: ~1.04s.
