# GridPulse Phase Imbalance, Symmetrical Components & Derating Analytics

## Phase 2 — Step 6 Specification (Corrective Revision)

This document details the deterministic electrical formulations, mathematical transformations, evidence classifications, diagnostic invariants, and safety boundaries implemented in Phase 2 Step 6 for three-phase asymmetrical loading, Fortescue symmetrical components, neutral current analysis, and evidence-grounded transformer derating, incorporating all corrective resolutions from the independent scientific audit (Findings F-01 through F-07).

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
  - Strict Timestamp Synchronization:
      * All phase timestamps must be timezone-aware (UTC) and present.
      * Mismatched timestamps (> 1.0 s maximum divergence) rejected.
      * Missing timestamps rejected with ERR_MISSING_TIMESTAMP; NEVER synthesized.
      * Zero wall-clock fallbacks (no datetime.now() substitution).
  ↓
Phase Magnitude Imbalance (Voltage & Current)
  - Arithmetic Mean: X_mean = (Xa + Xb + Xc) / 3
  - Direct Maximum Phase Magnitude: X_max = max(Xa, Xb, Xc) (F-01 resolution)
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
  - Inverse Reconstruction Check & Tolerance Enforcement (F-05 resolution):
      Xa' = X0 + X1 + X2
      Xb' = X0 + a^2*X1 + a*X2
      Xc' = X0 + a*X1 + a^2*X2
      Residual = max(|Xa - Xa'|, |Xb - Xb'|, |Xc - Xc'|) <= 1e-9 (RECONSTRUCTION_TOLERANCE)
      If Residual > 1e-9 or non-finite: Reject with ERR_RECONSTRUCTION_TOLERANCE_EXCEEDED
  - Sequence Ratios (if |X1| > 1e-6):
      VUF = 100 * |V2| / |V1|  (IEC 61000-4-30 / IEC 60076)
      CUF = 100 * |I2| / |I1|
  - Neutral return current (4-wire current phasors):
      In = -(Ia + Ib + Ic) = -3 * I0, |In| = 3 * |I0|
  ↓
Evidence-Grounded Transformer Derating Assessment
  - Conductor-Current Throughput Constraint (MAX_PHASE_CURRENT_CAPACITY):
      * i_max = max(Ia, Ib, Ic)
      * k_throughput = mean_I / i_max
      * Categorized as CONDUCTOR_CURRENT_THROUGHPUT_LIMIT, NOT universal thermal derating
  - Disabled Negative-Sequence Loss-Based Derating (F-02 resolution):
      * IEEE C57.110 applies solely to harmonics (h > 1), NOT fundamental negative sequence.
      * Permanently disabled: returns derating_factor_pu=None, status="UNKNOWN",
        and WARN_DERATING_METHOD_UNAVAILABLE.
  - Strict Parameter Provenance Enforcement (F-03 resolution):
      * Bare floats and ENGINEERING_ASSUMPTION strictly rejected.
      * ParameterWithProvenance required with source suitability check.
      * NAMEPLATE rejected for loss parameters (loss ratio, eddy factor).
  - Conservative Evidence Propagation (F-07 resolution):
      * MEASURED inputs → CALCULATED output.
      * Any MODELED input → MODELED output (never upgraded to measured facts).
      * SUSPECT quality or missing timestamps → SUSPECT / UNKNOWN.
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
- **`timestamp`**: Timezone-aware UTC timestamp. Mandatory; no wall-clock synthesis permitted.

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

2. **Maximum Phase Magnitude (Direct Calculation — Audit Finding F-01):**
   $$X_{\max} = \max\left(X_a, X_b, X_c\right)$$
   *Audit Correction:* Previously reconstructed via $\bar{X} + \Delta X_{\max}$. In asymmetrical conditions with depressed phases (e.g., $60\text{ A}, 90\text{ A}, 90\text{ A}$), $\Delta X_{\max} = |60 - 80| = 20\text{ A}$, which incorrectly reconstructed $80 + 20 = 100\text{ A}$ instead of the true maximum $90\text{ A}$. The direct calculation computes the exact maximum under all asymmetrical permutations.

3. **Phase Signed Deviations:**
   $$\Delta X_a = X_a - \bar{X}, \quad \Delta X_b = X_b - \bar{X}, \quad \Delta X_c = X_c - \bar{X}$$

4. **Phase Absolute Deviations:**
   $$|\Delta X_a| = |X_a - \bar{X}|, \quad |\Delta X_b| = |X_b - \bar{X}|, \quad |\Delta X_c| = |X_c - \bar{X}|$$

5. **Maximum Absolute Deviation:**
   $$\Delta X_{\max} = \max\left(|\Delta X_a|, |\Delta X_b|, |\Delta X_c|\right)$$

6. **Percentage Deviation (Mean-based Denominator):**
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

4. **Inverse Reconstruction Check & Tolerance Enforcement (Audit Finding F-05):**
   $$\mathbf{X}_a' = \mathbf{X}_0 + \mathbf{X}_1 + \mathbf{X}_2$$
   $$\mathbf{X}_b' = \mathbf{X}_0 + \alpha^2 \mathbf{X}_1 + \alpha \mathbf{X}_2$$
   $$\mathbf{X}_c' = \mathbf{X}_0 + \alpha \mathbf{X}_1 + \alpha^2 \mathbf{X}_2$$
   $$\text{Residual}_{\max} = \max\left(|\mathbf{X}_a - \mathbf{X}_a'|, |\mathbf{X}_b - \mathbf{X}_b'|, |\mathbf{X}_c - \mathbf{X}_c'|\right)$$
   - The contract defines $\text{RECONSTRUCTION\_TOLERANCE} = 10^{-9}$ (expressed in primary units: Volts or Amperes).
   - If $\text{Residual}_{\max} > 10^{-9}$ or if the residual is non-finite, the transformation fails closed: symmetrical components return `None`, `status="UNKNOWN"`, and structured diagnostic `ERR_RECONSTRUCTION_TOLERANCE_EXCEEDED` is emitted.

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

### A. Supported Conductor Throughput Capacity Constraint

1. **Formulation:**
   $$k_{\text{throughput}} = \frac{\bar{I}}{I_{\max}} = \frac{\frac{1}{3}(I_a + I_b + I_c)}{\max(I_a, I_b, I_c)}$$
   - **Benchmark Test Cases:**
     * $60\text{ A}, 90\text{ A}, 90\text{ A} \implies \bar{I} = 80\text{ A}, I_{\max} = 90\text{ A}, k = 80/90 = 0.888889$
     * $0\text{ A}, 60\text{ A}, 60\text{ A} \implies \bar{I} = 40\text{ A}, I_{\max} = 60\text{ A}, k = 40/60 = 0.666667$
     * Balanced: $100\text{ A}, 100\text{ A}, 100\text{ A} \implies k = 1.000000$
     * Zero: $0\text{ A}, 0\text{ A}, 0\text{ A} \implies$ Denominator safeguard returns `None` (`UNKNOWN`), `WARN_ZERO_MEAN_MAGNITUDE`.
2. **Explicit Physical Scope & Assumptions:**
   - **Scope:** Conductor and bushing thermal-ampacity limit. It restricts total throughput such that the highest-loaded phase conductor does not exceed its continuous current rating.
   - **Not Universal Transformer Thermal Derating:** This ratio does NOT model internal winding hot-spot dynamics, top-oil thermal time constants, core stray flux heating, or oil circulation modes. It is labeled explicitly as `CONDUCTOR_CURRENT_THROUGHPUT_LIMIT` with metadata `is_universal_thermal_derating = False`.

### B. Prohibited and Disabled Derating Methods

1. **Disabled Negative-Sequence Loss-Based Derating (Audit Finding F-02):**
   - **Invalidity of Prior Claims:** IEEE Std C57.110 applies specifically to non-sinusoidal (harmonic) load currents ($h > 1$) and harmonic loss factors ($F_{HL}, F_{HL-STR}$). It provides no formula or basis for fundamental-frequency ($h = 1$) negative-sequence current derating.
   - **Enforcement:** `DeratingMethod.LOSS_BASED_NEGATIVE_SEQUENCE` is permanently disabled in the engine. Calling it returns `derating_factor_pu = None`, `status = "UNKNOWN"`, and structured diagnostic `WARN_DERATING_METHOD_UNAVAILABLE`.
   - **No Reactivation Path:** Supplying arbitrary parameters will not reactivate this method.
2. **Induction Motor Derating Refusal:**
   - NEMA MG-1 Clause 14.36 specifies motor derating curves based on rotor negative-sequence slip and reverse torque ($I_2 \approx V_2 / X''$). Applying induction motor derating curves to static distribution transformers is an engineering category error and is prohibited.

### C. Parameter Provenance Enforcement (Audit Finding F-03)

- **Typed Provenance Contract:** Parameters must be encapsulated in `ParameterWithProvenance`.
- **Rejection of Unsuitable Sources:**
  * Transformer nameplates provide rated kVA, voltages, and impedance %Z, but **do not** specify winding eddy-current loss factors ($P_{\text{EC}}$) or load-to-no-load loss ratios ($R = P_{LL}/P_{NL}$).
  * `source_class="NAMEPLATE"` is explicitly rejected as unsuitable for loss parameters (`ERR_UNVALIDATED_DERATING_PARAMETERS`).
  * Only verified certified test reports (`source_class="FACTORY_TEST"`) or vendor certified reports with `is_verified=True` and approved provenance are accepted.
- **Rejection of Assumptions & Raw Floats:**
  * Bare floats raise `TypeError`.
  * `ENGINEERING_ASSUMPTION` or unverified sources (`is_verified=False`) are rejected.

---

## 5. Diagnostic Issues Reference

| Issue Code | Severity | Description |
| :--- | :--- | :--- |
| `ERR_INCOMPLETE_THREE_PHASE_TELEMETRY` | WARNING | Telemetry missing for one or more phases (Phase A, B, or C). Imbalance calculation rejected without zero-fill. |
| `ERR_MISMATCHED_PHASE_TIMESTAMPS` | CRITICAL | Phase timestamps diverge by $> 1.0\,\text{s}$. Asynchronous observations cannot be combined. |
| `ERR_MISSING_TIMESTAMP` | CRITICAL | Measurement timestamp missing, timezone-naive, or unestablished. Wall-clock synthesis strictly prohibited. |
| `ERR_RECONSTRUCTION_TOLERANCE_EXCEEDED` | CRITICAL | Inverse sequence reconstruction residual exceeds $10^{-9}$ primary units or is non-finite. |
| `ERR_UNVALIDATED_DERATING_PARAMETERS` | CRITICAL | Parameters unverified, lack approved provenance, or source class is unsuitable for the parameter. |
| `ERR_MISSING_PHASOR_ANGLES` | WARNING | Telemetry contains magnitudes only. Symmetrical components rejected without angle fabrication. |
| `ERR_INVALID_PHASE_IDENTIFICATION` | CRITICAL | Phase tag does not match required A, B, C, or N identity. |
| `ERR_INVALID_PHASE_SEQUENCE` | CRITICAL | Unrecognized phase rotation sequence (supported: ABC, ACB). |
| `ERR_DEGENERATE_POSITIVE_SEQUENCE` | WARNING | Positive-sequence magnitude $|\mathbf{X}_1| \le 10^{-6}$. Unbalance ratio calculation avoided. |
| `WARN_ZERO_MEAN_MAGNITUDE` | WARNING | Arithmetic mean magnitude $\bar{X} \le 0.0$. Percentage unbalance set to UNKNOWN. |
| `WARN_DERATING_METHOD_UNAVAILABLE` | WARNING / INFO | Requested derating method unsupported, unverified, or disabled. |
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
| **IEEE Std C57.110-2018** | Clause 5.2 | Additional eddy-current heating from non-sinusoidal / harmonic currents ($h > 1$) | **Confirmed Scope Limitation**: Does NOT apply to fundamental negative-sequence derating |
| **Negative-Sequence Derating** | N/A | Loss-based negative sequence derating formula | **Unverified / Disabled**: Returns UNKNOWN |
| **NEMA MG-1:2016** | Clause 14.36 | Induction motor derating curve | **Explicitly Excluded** for transformers |

---

## 7. Verification and Test Results

Run the complete scientific verification suite via:
```powershell
python -m pytest -v
```
or standard library unittest:
```powershell
python -m unittest discover -s scientific -p "test_*.py" -v
```

**Results:**
- Total tests: **162 passed** (119 historical Steps 1–5 + 43 Step 6 tests).
- Regression suite: 17 dedicated Step 6 audit regression tests covering F-01 through F-07.
- Skipped / Failed: **0**.
- Execution duration: ~0.51s (pytest) / ~0.04s (unittest).

