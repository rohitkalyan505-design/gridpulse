# GridPulse Transformer Thermal Analysis & Insulation Degradation

## Phase 2 — Step 5 Specification (v2.5.0)

This document provides the formal engineering specification, governing equations, parameter provenance rules, numerical safety invariants, and implementation contracts for transformer thermal analysis and insulation degradation in GridPulse Phase 2 Step 5.

All derivations operate strictly on validated telemetry and deterministic loading results from Phase 2 Step 4, enforce physical thermodynamics, produce granular evidence classifications (`MEASURED`, `CALCULATED`, `MODELED`, `UNKNOWN`), and maintain end-to-end calculation provenance.

---

## 1. Locked Pipeline Architecture

```
Validated Loading Results (TransformerLoadingResult from Step 4)
  ↓
Thermal Parameters Provenance Gate
  - Reject ENGINEERING_ASSUMPTION and UNKNOWN
  - Admit only FACTORY_TEST, MANUFACTURER_DOCUMENT, ASSET_VERIFIED
  - Verify positive physical values and standard-specific exponent bounds
  ↓
Telemetry Ingestion & Sensor Preservation Gate
  - Ambient sensor: MEASURED or UNKNOWN (zero synthetic ambient)
  - Top-oil sensor: MEASURED or UNKNOWN
  - Winding hot-spot sensor: MEASURED or UNKNOWN
  - Anomalous gradient preservation (WARN_ANOMALOUS_MEASURED_GRADIENT)
  ↓
Thermal State Initialization Gate
  - Reject assumed zero rise, rated rise, or steady-state initialization
  - Establish only from direct physical sensors or valid contiguous prior state
  - Missing required state → UNKNOWN with ERR_UNESTABLISHED_INITIAL_THERMAL_STATE
  ↓
Standard-Specific Differential Thermal Modeling
  - IEEE profile: Δθ_hs,u = Δθ_hs,rated × K^(2 * y_ieee)
  - IEC profile:  Δθ_hs,u = (H × g_rated) × K^(y_iec)
  - Exponential recurrence over continuous observation intervals
  ↓
Independent Degradation Kinetics Evaluation
  - IEEE Aging Acceleration Factor: F_AA (Clause 5)
  - IEC Relative Ageing Rate: V (Clause 6)
  - Pure domain numerical safety: Absolute zero guard and float overflow prevention
  ↓
Forward-Interval Loss-of-Life Integration
  - Mandatory AgingStandardPreference (IEEE or IEC, zero default fallback)
  - Sample k governs [t_k, t_{k+1}); final sample duration = 0.0 h
  - Continuity breaks sever ODE state and prevent speculative bridging
  - Cumulative window completeness tracking (WARN_INCOMPLETE_INTEGRATION_WINDOW)
  ↓
Reference-Life Normalization
  - Asset-specific validated reference life required for %L_OL
  - Zero hard-coded 180,000-hour fallback (WARN_UNCONFIGURED_REFERENCE_LIFE)
  ↓
Structured Results & Output Packaging
  - Evidence: Direct hot spot → CALCULATED degradation | Modeled → MODELED degradation
  - ThermalIntervalResult & ThermalStateResult
```

---

## 2. Standards Formulations & Mathematical Divergence

GridPulse strictly distinguishes between the **Thermal-Model Standard** (governing differential temperature rise) and the **Aging-Integration Standard** (governing equivalent loss of life).

### 2.1 IEEE Std C57.91-2011 Profile

#### A. Top-Oil Rise (Clause 7 & Annex G)

The top-oil rise over ambient temperature $\Delta\theta_{\text{oil}}(t)$ under loading ratio $K = I / I_{\text{rated}}$ satisfies:
$$\tau_{\text{oil}} \frac{d\Delta\theta_{\text{oil}}}{dt} = \Delta\theta_{\text{oil, u}} - \Delta\theta_{\text{oil}}$$
where ultimate top-oil rise is:
$$\Delta\theta_{\text{oil, u}} = \Delta\theta_{\text{oil, rated}} \cdot \left( \frac{K^2 R + 1}{R + 1} \right)^x$$

- $\tau_{\text{oil}}$: Top-oil thermal time constant (`time_constant_oil_hours`).
- $\Delta\theta_{\text{oil, rated}}$: Rated top-oil rise over ambient at rated load ($\text{K}$).
- $R$: Ratio of load losses to no-load losses at rated load ($P_{\text{load, rated}} / P_{\text{no-load}}$).
- $x$: Oil thermal exponent (typically $0.8$ for ONAN).

#### B. Winding Hot-Spot Rise Over Top Oil (Clause 7)

$$\Delta\theta_{\text{hs, u}} = \Delta\theta_{\text{hs, rated}} \cdot K^{2 y_{\text{IEEE}}}$$

- $\tau_{\text{w}}$: Winding time constant (`time_constant_winding_hours`, typically $0.05 - 0.15\,\text{h}$).
- $\Delta\theta_{\text{hs, rated}}$: Rated hot-spot rise over top oil at rated load ($\text{K}$).
- $y_{\text{IEEE}}$: IEEE winding exponent applied to current squared ($K^2$). Typical value $0.8$, valid range $[0.5, 1.2]$.

#### C. Aging Acceleration Factor ($F_{AA}$, Clause 5)

$$F_{AA} = \exp\left( \frac{15000}{T_{\text{ref}} + 273.15} - \frac{15000}{\theta_{\text{hs}} + 273.15} \right)$$

- **Thermally Upgraded Paper (120°C class):** $T_{\text{ref}} = 110.0^\circ\text{C}$ ($383.15\,\text{K}$).
- **Non-Thermally Upgraded Paper (105°C class):** $T_{\text{ref}} = 95.0^\circ\text{C}$ ($368.15\,\text{K}$).

---

### 2.2 IEC 60076-7:2018 Profile

#### A. Top-Oil Rise (Clause 7)

$$\Delta\theta_{\text{oil, u}} = \Delta\theta_{\text{oil, rated}} \cdot \left( \frac{1 + K^2 R}{1 + R} \right)^x$$
Algebraically identical to the IEEE top-oil formulation.

#### B. Winding Hot-Spot Rise Over Top Oil (Clause 7)

$$\Delta\theta_{\text{hs, u}} = H \cdot g_{\text{rated}} \cdot K^{y_{\text{IEC}}} = \Delta\theta_{\text{hs, rated}} \cdot K^{y_{\text{IEC}}}$$

- $H$: Hot-spot factor (dimensionless, typically $1.1 - 1.5$).
- $g_{\text{rated}}$: Rated winding-to-average-oil temperature gradient ($\text{K}$).
- $\Delta\theta_{\text{hs, rated}} = H \cdot g_{\text{rated}}$ at rated load $K = 1.0$.
- $y_{\text{IEC}}$: IEC winding exponent applied directly to current ratio $K$. Typical value $1.3 - 1.6$, valid range $[1.0, 2.2]$.

#### C. Relative Ageing Rate ($V$, Clause 6)

- **Non-Thermally Upgraded Paper:**
  $$V = 2^{(\theta_{\text{hs}} - 98.0) / 6.0}, \quad T_{\text{ref}} = 98.0^\circ\text{C}$$
- **Thermally Upgraded Paper:**
  $$V = \exp\left( \frac{15000}{110.0 + 273.15} - \frac{15000}{\theta_{\text{hs}} + 273.15} \right), \quad T_{\text{ref}} = 110.0^\circ\text{C}$$

---

### 2.3 Mathematical Divergence Demonstration

Consider a transformer loaded at $K = 1.2$ with $\Delta\theta_{\text{hs, rated}} = 25.0\,\text{K}$:

- **IEEE Model ($y_{\text{IEEE}} = 0.8 \implies 2y = 1.6$):**
  $$\Delta\theta_{\text{hs, u}} = 25.0 \times 1.2^{1.6} \approx 25.0 \times 1.338721 = 33.468\,\text{K}$$
- **IEC Model ($y_{\text{IEC}} = 1.3$):**
  $$\Delta\theta_{\text{hs, u}} = 25.0 \times 1.2^{1.3} \approx 25.0 \times 1.267468 = 31.687\,\text{K}$$

Because the exponent formulations differ fundamentally, cross-standard parameter reuse is prohibited. An IEEE exponent ($0.8$) applied to an IEC formula would drastically underestimate winding heating, while an IEC exponent ($1.3$) applied to an IEEE formula would severely overestimate winding heating.

---

## 3. Parameter Provenance & High-Consequence Policy

Physical parameters governing thermal differential equations must carry explicit provenance metadata (`ParameterSourceClass`):

| Source Classification    | Description                                          | Production Admission                                |
| :----------------------- | :--------------------------------------------------- | :-------------------------------------------------- |
| `FACTORY_TEST`           | Factory acceptance test (FAT) or heat-run test sheet | **ADMITTED**                                        |
| `MANUFACTURER_DOCUMENT`  | Certified manufacturer transformer design data       | **ADMITTED**                                        |
| `ASSET_VERIFIED`         | Verified asset engineering documentation             | **ADMITTED**                                        |
| `ENGINEERING_ASSUMPTION` | Generic/typical standards default values             | **REJECTED** (`ERR_UNVALIDATED_THERMAL_PARAMETERS`) |
| `UNKNOWN`                | Unspecified or unverified parameter records          | **REJECTED** (`ERR_UNVALIDATED_THERMAL_PARAMETERS`) |

### Rejection Invariant

If any required thermal parameter carries `ENGINEERING_ASSUMPTION`, `UNKNOWN`, or has `is_verified=False`, all modeled thermal calculations are halted. The engine emits `ERR_UNVALIDATED_THERMAL_PARAMETERS` and outputs `UNKNOWN` for modeled temperatures and degradation rates. Direct physical sensor measurements remain accessible.

---

## 4. Telemetry Ingestion & Ambient Integrity

1. **Ambient Temperature:**
   - Physical sensor: `MEASURED`.
   - Missing sensor: `UNKNOWN` (None).
   - The engine strictly prohibits synthetic ambient generation (no default 25°C, no regional average, no external weather API bridging).
2. **Top-Oil Temperature:**
   - Physical sensor: `MEASURED`.
   - Missing sensor: Modeled via exponential ODE if parameters and ambient are valid (`MODELED`); otherwise `UNKNOWN`.
3. **Winding Hot-Spot Temperature:**
   - Fiber-optic probe: `MEASURED`.
   - Missing probe: Derived from top-oil plus ODE hot-spot rise (`MODELED`); otherwise `UNKNOWN`.
4. **Physical Gradient Validation:**
   - If physical sensors report $\theta_{\text{hs, meas}} < \theta_{\text{oil, meas}}$, the raw measurements are preserved as `MEASURED`, and the engine emits `WARN_ANOMALOUS_MEASURED_GRADIENT`.
   - Calculated top-oil rise $\Delta\theta_{\text{oil}} = \theta_{\text{oil, meas}} - \theta_{\text{amb, meas}}$ is permitted to be negative during rapid cooling without validation errors.

---

## 5. Initial Thermal State Contract & Post-Gap Recovery

### 5.1 Prohibition of Assumed Initial Rise

The engine will never:

- Assume an initial rise of $0\,\text{K}$.
- Initialize to rated temperature rise.
- Assume steady state at $t_0$.
- Infer an unmeasured winding hot-spot rise solely from top-oil sensors.

If telemetry begins without direct sensor readings and without a chained prior thermal state from a contiguous run ($|t_0 - t_{\text{prior}}| \le \text{tolerance}$), modeled thermal states at $t_0$ are marked `UNKNOWN` and quarantined with `ERR_UNESTABLISHED_INITIAL_THERMAL_STATE`.

### 5.2 Post-Gap State Resumption Matrix

When elapsed time $\Delta t > \text{continuity\_tolerance\_seconds}$:

1. A continuity break is registered (`WARN_TELEMETRY_GAP`).
2. Prior ODE state is severed ($\Delta\theta_{\text{oil, prev}} = \text{None}$, $\Delta\theta_{\text{hs, prev}} = \text{None}$).
3. The gap interval is excluded from loss-of-life integration.
4. Resumption at the post-gap timestamp follows independent sensor availability:
   - **Both sensors present:** Both report as `MEASURED`; full modeling resumes.
   - **Top-oil only present:** Top oil reports as `MEASURED`; unmeasured hot spot remains `UNKNOWN`.
   - **Hot-spot only present:** Hot spot reports as `MEASURED`; aging rates evaluate as `CALCULATED`; top oil remains `UNKNOWN`.
   - **Neither sensor present:** Both quarantined as `UNKNOWN` with `ERR_UNESTABLISHED_INITIAL_THERMAL_STATE`.

---

## 6. Forward-Interval Loss-of-Life Integration

### 6.1 Interval Mechanics

Given ordered samples $k = 0, 1, \dots, N-1$ at timestamps $t_0 < t_1 < \dots < t_{N-1}$:

- Sample $k \in [0, N-2]$ strictly governs the forward half-open interval $[t_k, t_{k+1})$.
- Interval duration: $\Delta t_k = (t_{k+1} - t_k)$ in hours.
- If $\Delta t_k \le \text{tolerance}$:
  $$\Delta L_{OL, k} = \text{Rate}_k \cdot \Delta t_k \quad (\text{hours})$$
  where $\text{Rate}_k = F_{AA, k}$ if `AgingStandardPreference.IEEE`, else $V_k$ if `AgingStandardPreference.IEC`.
- Final sample $k = N-1$ defines no forward interval within the batch ($\Delta t_{N-1} = 0.0\,\text{h}$) and contributes $0.0\,\text{h}$ equivalent aging.

### 6.2 Cumulative Completeness Invariant

- **Complete Window:** If all $N-1$ forward intervals in the batch are continuous and valid:
  $$L_{OL, \text{cum}} = \sum_{k=0}^{N-2} \Delta L_{OL, k}$$
- **Incomplete Window:** If ANY interval in the batch is a continuity gap ($\Delta t > \text{tolerance}$), chronological violation (duplicate or out-of-order timestamp), quarantined, or unconfigured:
  - Cumulative equivalent aging hours is marked `UNKNOWN` (None).
  - Loss-of-life percentage is marked `UNKNOWN` (None).
  - The engine emits `WARN_INCOMPLETE_INTEGRATION_WINDOW`.
  - Individual valid interval contributions $\Delta L_{OL, k}$ remain recorded in `forward_interval_result` for auditability, but are never speculatively bridged to form a complete batch total.

---

## 7. Evidence Classification Propagation

Evidence classifications adhere to GridPulse's immutable 5-level taxonomy:

| Computational Input                      | Intermediate State | Degradation Metric         | Loss of Life Result         |
| :--------------------------------------- | :----------------- | :------------------------- | :-------------------------- |
| Direct Fiber Sensor $\theta_{\text{hs}}$ | `MEASURED`         | `CALCULATED` ($F_{AA}, V$) | **`CALCULATED`** ($L_{OL}$) |
| ODE Model $\Delta\theta_{\text{hs}}$     | `MODELED`          | `MODELED` ($F_{AA}, V$)    | **`MODELED`** ($L_{OL}$)    |
| Missing / Quarantined Input              | `UNKNOWN`          | `UNKNOWN`                  | **`UNKNOWN`**               |

_Under no circumstances is loss of life assigned `MODELED` by default when the underlying hot spot is physically measured._

---

## 8. Reference-Life Normalization

The loss-of-life percentage is computed only when cumulative equivalent aging is valid and an approved asset-specific reference life parameter is configured:
$$\%L_{OL} = \frac{L_{OL, \text{cum}}}{L_{\text{normal}}} \cdot 100\%$$

- If `reference_life_hours` ($L_{\text{normal}}$) is missing or has an unverified source class:
  - $\%L_{OL}$ resolves to `UNKNOWN` (None).
  - The engine emits `WARN_UNCONFIGURED_REFERENCE_LIFE`.
  - The universal 180,000-hour default is strictly eradicated.

---

## 9. Numerical Safety & Physical Domain Invariants

1. **Absolute Zero Guard:** If $\theta_{\text{hs}} \le -273.15^\circ\text{C}$, the temperature violates thermodynamics. The engine emits `ERR_UNSAFE_ARRHENIUS_EVALUATION` and returns `UNKNOWN`.
2. **Float Overflow Guard:** Exponent evaluation is verified against IEEE 754 limits. If an exponent would exceed safe floating-point capacity (e.g. $u \ge 700.0$ or $2^p \ge 2^{1020}$), `ERR_UNSAFE_ARRHENIUS_EVALUATION` is emitted and the metric returns `UNKNOWN`.
3. **No Arbitrary Clamping:** Valid physical operating temperatures ($-50^\circ\text{C}$ to $300^\circ\text{C}$) are evaluated with exact double precision without artificial clamping.
4. **Reference Temperature Invariants:**
   - IEEE Upgraded at $110.0^\circ\text{C} \implies F_{AA} = 1.000000$.
   - IEEE Non-upgraded at $95.0^\circ\text{C} \implies F_{AA} = 1.000000$.
   - IEC Upgraded at $110.0^\circ\text{C} \implies V = 1.000000$.
   - IEC Non-upgraded at $98.0^\circ\text{C} \implies V = 1.000000$.

---

## 10. Diagnostic Issues Reference

| Issue Code                                | Severity   | Description                                                                                    |
| :---------------------------------------- | :--------- | :--------------------------------------------------------------------------------------------- |
| `ERR_UNSPECIFIED_AGING_STANDARD`          | `CRITICAL` | `aging_standard` was not explicitly provided or is invalid.                                    |
| `ERR_UNSPECIFIED_THERMAL_MODEL_STANDARD`  | `CRITICAL` | `thermal_model_standard` was not explicitly provided or is invalid.                            |
| `ERR_UNVALIDATED_THERMAL_PARAMETERS`      | `CRITICAL` | Thermal parameters lack approved source provenance (`FACTORY_TEST`, etc.).                     |
| `ERR_INVALID_PARAMETER_VALUE`             | `CRITICAL` | Parameter value is non-positive ($\le 0.0$).                                                   |
| `ERR_INVALID_EXPONENT_RANGE`              | `CRITICAL` | Winding exponent is outside valid standard range ($y_{\text{IEEE}}$ or $y_{\text{IEC}}$).      |
| `ERR_UNESTABLISHED_INITIAL_THERMAL_STATE` | `CRITICAL` | Initial thermal state cannot be established without sensors or prior state.                    |
| `ERR_UNSAFE_ARRHENIUS_EVALUATION`         | `CRITICAL` | Absolute zero thermodynamic violation or floating-point numerical overflow.                    |
| `WARN_UNCONFIGURED_REFERENCE_LIFE`        | `WARNING`  | Missing or unverified reference life hours. $\%L_{OL}$ set to `UNKNOWN`.                       |
| `WARN_ANOMALOUS_MEASURED_GRADIENT`        | `WARNING`  | Physical sensor reports $\theta_{\text{hs}} < \theta_{\text{oil}}$. Raw reading preserved.     |
| `WARN_TELEMETRY_GAP`                      | `WARNING`  | Telemetry interval exceeded continuity tolerance. Chained ODE state severed.                   |
| `WARN_INCOMPLETE_INTEGRATION_WINDOW`      | `WARNING`  | Evaluation batch contains gaps or quarantined intervals. Cumulative $L_{OL}$ marked `UNKNOWN`. |
| `WARN_NON_MONOTONIC_TIMESTAMPS`           | `WARNING`  | Telemetry sequence contains duplicate or out-of-order timestamps. State severed.               |

---

## 11. Standards Boundary & Governance

Citations to IEEE Std C57.91-2011 and IEC 60076-7:2018 establish engineering provenance for the implemented profiles. They do not constitute an assertion of compliance with every clause of either standard.

Implementation profiles in Step 5 apply to mineral-oil-immersed power and distribution transformers with stationary cooling modes. Dynamic cooler stage switching, per-phase thermal dissipation, and non-mineral ester fluids are deferred to subsequent scientific milestones.
