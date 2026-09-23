# GridPulse Scientific Data Validation & Electrical Ingestion Rules

## Phase 2 — Step 2 Specification

This document details the scientific data-quality layer for the GridPulse Python Scientific Engine. Telemetry must be screened structurally, temporally, and physically before it can reach downstream electrical calculations or physical models.

---

## 1. Locked Validation Pipeline

```
Raw Electrical Telemetry
  ↓
Schema Validation
  ↓
Timestamp Validation
  ↓
Unit Validation
  ↓
Range Validation (Generic Sanity Boundaries vs. Asset Operating Limits)
  ↓
Missing Data Detection
  ↓
Duplicate Detection (Identical vs. Conflicting)
  ↓
Flatline Detection (Data-Quality Diagnostic Signal)
  ↓
Quality Classification (GOOD, SUSPECT, BAD, MISSING, OUT_OF_RANGE)
  ↓
Validated Telemetry (ValidatedTelemetryBatch)
```

---

## 2. Ingestion Boundary & Telemetry Input Contract

The scientific ingestion layer (`scientific/ingestion/`) ingests raw telemetry payloads without requiring external network connectors or cloud database dependencies.

### Telemetry Record Requirements

Every incoming telemetry record must specify:

1. `asset_id`: Immutable string identifying the monitored transformer asset (e.g., `TX-SUB04-DT012`).
2. `timestamp`: Timezone-aware observation time, canonicalized strictly to UTC.
3. `channel_tag`: Recognized electrical or environmental measurement identifier.
4. `raw_value`: Numeric reading (`float` or `int`), or `None` if unmetered.
5. `source_unit`: Standard engineering unit string (e.g., `V`, `A`, `kW`, `Hz`).
6. `sensor_id` (optional): Hardware instrument or transducer identifier.
7. `metadata` (optional): Channel metadata or diagnostic tags.

---

## 3. Supported Measurement Types

The validator recognizes the following standardized measurement channels:

| Measurement Type                      | Description                              | Allowed Engineering Units      |
| :------------------------------------ | :--------------------------------------- | :----------------------------- |
| `VOLTAGE_A`, `VOLTAGE_B`, `VOLTAGE_C` | RMS Phase Voltages                       | `V`, `kV`                      |
| `VOLTAGE_AVG`                         | Three-Phase Average RMS Voltage          | `V`, `kV`                      |
| `CURRENT_A`, `CURRENT_B`, `CURRENT_C` | RMS Phase Line Currents                  | `A`, `mA`, `kA`                |
| `CURRENT_AVG`                         | Three-Phase Average RMS Current          | `A`, `mA`, `kA`                |
| `ACTIVE_POWER`                        | Three-Phase or Single-Phase Active Power | `W`, `kW`, `MW`                |
| `REACTIVE_POWER`                      | Reactive Power                           | `VAR`, `kVAR`, `MVAR`          |
| `APPARENT_POWER`                      | Apparent Power                           | `VA`, `kVA`, `MVA`             |
| `POWER_FACTOR`                        | Total or Phase Power Factor              | `ratio`, `pu`, `percent`, `""` |
| `FREQUENCY`                           | System Operating Frequency               | `Hz`                           |
| `AMBIENT_TEMPERATURE`                 | Local Ambient Temperature                | `degC`, `C`, `°C`              |

---

## 4. Power Factor Validation Domain & Convention

- **Validation Domain**: Physically and mathematically, power factor magnitude cannot exceed unity: $-1.0 \le \text{PF} \le 1.0$.
- **Sign Convention**: IEEE convention where the sign denotes the direction of reactive power or load characteristic (positive for lagging/inductive power factor, negative for leading/capacitive power factor).
- **No Calculation in Step 2**: Step 2 strictly validates an _externally supplied_ power factor measurement. Deriving power factor from active and apparent power ($P / S$) is reserved for Step 3 (Electrical Calculations).
- **Invalid Handling**: Any supplied power factor measurement outside $[-1.0, 1.0]$ is marked `BAD` or `OUT_OF_RANGE`.

---

## 5. Timestamp Conventions & Validation

- **Canonical Timezone**: All timestamps must be timezone-aware UTC (`timezone.utc`).
- **Naive Datetimes**: Timezone-naive timestamps are strictly rejected. The engine never silently guesses or assumes a local timezone.
- **Monotonicity**: Interval sequences must be monotonically increasing. Out-of-order timestamps generate warning diagnostics (`WARN_TIMESTAMP_OUT_OF_ORDER`).
- **Duplicate Timestamps**: Handled through explicit duplicate detection policies.

---

## 6. Missing-Data Policy

- **Explicit Representation**:
  $$\text{value} = \text{None}, \quad \text{quality} = \text{MISSING}, \quad \text{evidence} = \text{UNKNOWN}$$
- **Prohibited Practices**:
  - Never replace missing voltage or current with zero.
  - Never silently mean-impute or forward-fill missing intervals.
  - Never synthesize artificial readings.
- **Downstream Consequence**: If a downstream physical equation requires a missing channel, that calculation must report `InsufficientTelemetryError` rather than computing with fabricated inputs.

---

## 7. Duplicate Telemetry Policy & Traceability

Duplicates are evaluated on the composite identity:
$$\text{Asset ID} + \text{Measurement Type} + \text{Timestamp} + \text{Sensor ID}$$

### A. Identical Duplicates

- Occur when duplicate records carry the same value within tolerance.
- Action: Retained as a single clean reading for downstream processing.
- Traceability: An informational issue (`INFO_DUPLICATE_IDENTICAL`) is recorded in the result summary documenting the duplicate count and consolidation.

### B. Conflicting Duplicates

- Occur when duplicate records carry divergent values for the same channel at the same timestamp.
- Action: The measurement quality is flagged as `SUSPECT`.
- Traceability: A warning issue (`WARN_DUPLICATE_CONFLICTING`) is generated recording all conflicting values, preventing ambiguous data from being treated as clean telemetry.

---

## 8. Sensor Flatline Detection & Tolerance Semantics

- **Data-Quality Diagnostic Only**: Flatline detection signals that a channel has remained constant over consecutive intervals. It indicates potential telemetry freezing, communication packet repetition, or legitimate steady-state operation.
- **Explicit Invariant**: Flatline detection **never claims sensor failure, sensor malfunction, asset failure, or asset abnormality**. It produces a quality signal requiring diagnostic review.
- **Quality State**: Readings flagged for flatline receive `SUSPECT` quality and generate `WARN_FLATLINE_DETECTED`.
- **Scale-Appropriate Tolerances**:
  - Voltages: `abs_tol = 0.1 V` (avoids rounding noise on distribution scales).
  - Currents: `abs_tol = 0.05 A`.
  - Frequency: `abs_tol = 0.005 Hz`.
  - Power Factor: `abs_tol = 0.001`.
  - Temperature: `abs_tol = 0.05 °C`.
  - Configurable consecutive threshold (default: 5 intervals).

---

## 9. Generic Sanity Limits vs. Asset Operating Limits

### A. Generic Sanity Boundaries (GridPulse Data-Quality Conventions)

- These bounds represent **GridPulse data-quality conventions** designed to detect corrupted hardware readings, sensor saturation, or physical impossibilities:
  - Voltage: $0 \le V \le 100,000 \text{ V}$
  - Current: $0 \le I \le 50,000 \text{ A}$
  - Frequency: $30 \le f \le 75 \text{ Hz}$
  - Ambient Temp: $-50 \le T_{\text{amb}} \le 80 \text{ }^\circ\text{C}$
- _Classification_: Values crossing generic sanity bounds are marked `BAD` or `OUT_OF_RANGE`.
- _Documentation Rule_: These bounds are explicit software data-quality filters, NOT universal transformer operating ratings.

### B. Asset-Specific Operating Limits

- Configured via `TransformerAssetSpec.operational_limits` (e.g., continuous overload ratio, voltage tolerances $\pm 10\%$).
- **Decoupled Quality Rule**: If a physically plausible reading exceeds an asset operating limit (e.g. secondary voltage at $1.15 \text{ pu}$):
  - The measurement is **preserved** with `quality = GOOD`.
  - It is **not** marked `BAD` or corrupted.
  - A separate operational finding (`OPERATIONAL_LIMIT_VOLTAGE_EXCURSION`) is recorded.
  - An operating-limit excursion is an operational condition, NOT a data-quality failure.

---

## 10. Strict Mode vs. Fault-Tolerant Mode

### Strict Mode (`config.strict_mode = True`)

- Designed for unit testing, strict contract enforcement, and laboratory verification.
- Any fatal schema defect, unparseable timestamp, unsupported engineering unit, or physical sanity violation immediately raises a domain exception (`TelemetryValidationError`, `PhysicalBoundaryError`).

### Fault-Tolerant Mode (`config.strict_mode = False`, Default)

- Designed for production utility pipelines.
- Valid records and valid channels are processed cleanly.
- Corrupted or invalid readings are isolated with `BAD` or `OUT_OF_RANGE` quality tags.
- Detailed diagnostics are preserved in `ValidationSummary` and `ProcessingIssue` lists without halting batch execution.
