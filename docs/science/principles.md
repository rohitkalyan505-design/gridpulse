# GridPulse Scientific Principles & Evidence Classification

## Core Principle: Physical Separation of Concerns

GridPulse enforces an uncompromised separation between deterministic electrical engineering, statistical analysis, and generative artificial intelligence.

```
Deterministic Physics (IEEE / IEC)
           ↓
Statistical Learning & ML (Anomaly Baselines)
           ↓
Grounded Generative AI (Interpretation & Synthesis)
```

### The LLM is NOT the Scientific Engine

- Large Language Models (LLMs) are **never** permitted to compute electrical power, solve thermal differential equations, or infer unmeasured electrical parameters.
- AI models are used solely to translate verified numerical and physical results into natural language briefings, triage recommendations, and operational alerts.
- Every claim made by the AI layer must trace directly back to an engineering calculation or verified statistical metric.

## Scientific Evidence Classification System

All diagnostic insights, alerts, and operational metrics in GridPulse must be tagged with one of the following five standardized evidence levels:

### 1. `MEASURED`

- **Definition**: Direct physical measurement obtained from a calibrated hardware sensor, meter, or transducer.
- **Examples**:
  - RMS Phase Voltages ($V_A, V_B, V_C$)
  - RMS Line Currents ($I_A, I_B, I_C$)
  - Grid Frequency ($f$)
  - Ambient Temperature ($T_{amb}$)

### 2. `CALCULATED`

- **Definition**: Exact mathematical derivation or closed-form electrical formula computed directly from `MEASURED` data without unverified physical assumptions.
- **Examples**:
  - Apparent Power: $S = \sqrt{3} \cdot V_{LL} \cdot I_L$
  - Active Power: $P = \sqrt{3} \cdot V_{LL} \cdot I_L \cdot \cos\phi$
  - Reactive Power: $Q = \sqrt{S^2 - P^2}$
  - Power Factor: $\cos\phi = P / S$
  - Current Unbalance Ratio (symmetrical components): $I_2 / I_1$

### 3. `MODELED`

- **Definition**: Output of a deterministic physical or empirical differential model (e.g., IEEE C57.91 / IEC 60076-7 thermal models) driven by measured inputs and documented transformer design parameters.
- **Examples**:
  - Top-Oil Temperature ($T_O$)
  - Winding Hot-Spot Temperature ($T_{HS}$)
  - Thermal Aging Acceleration Factor ($F_{AA}$)
  - Equivalent Loss of Life ($L_{OL}$)

### 4. `INFERRED`

- **Definition**: Output of statistical distributions, unsupervised clustering, or machine learning models that identify deviations from baseline historical behavior.
- **Examples**:
  - Load profile regime clustering
  - Statistical anomaly score
  - Historical degradation trajectory projection

### 5. `UNKNOWN`

- **Definition**: Parameter that is unmetered, physically indeterminate from available inputs, corrupted, or whose sensor calibration is unverified.
- **Examples**:
  - Unmetered neutral current in unbalanced 3-phase 4-wire systems lacking neutral CTs
  - Winding temperature when oil thermal time-constants cannot be calibrated
  - Oil moisture content in the absence of chemical DGA/dielectric sensors

## Integrity Mandate

Under no circumstances may a metric be upgraded to a higher evidence classification without verified instrumentation.

- An `INFERRED` metric must never be presented as `MEASURED`.
- A `MODELED` value must never be presented as physical fact without stating the underlying model assumptions.
