# GridPulse Scientific Engine Architecture & Contracts

## Status: Phase 2 — Step 1 Architecture Foundation

This document defines the architectural specifications, shared contracts, and operational invariants for the GridPulse Python Scientific Engine.

---

## 1. Scientific Engine Boundaries & Execution Topology

The GridPulse Scientific Engine is an isolated, deterministic numerical computing package residing in `scientific/`.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        External Service Layer                          │
│     (Next.js App / Future FastAPI Adapter / Firestore / Supabase)      │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Ingests Telemetry & Asset Spec
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                GridPulse Scientific Engine Boundary                     │
│  (Python 3.12, NumPy, Pandas, SciPy, scikit-learn | Pure Computation)  │
│                                                                        │
│   Shared Contracts Source of Truth: scientific/contracts/              │
│                                                                        │
│   Electrical Data                                                      │
│     ↓                                                                  │
│   Data Validation                                                      │
│     ↓                                                                  │
│   Electrical Calculations                                              │
│     ↓                                                                  │
│   Transformer Loading                                                  │
│     ↓                                                                  │
│   Thermal Analysis                                                     │
│     ↓                                                                  │
│   Phase Imbalance                                                      │
│     ↓                                                                  │
│   Anomaly Detection                                                    │
│     ↓                                                                  │
│   Decision Intelligence                                                │
│     ↓                                                                  │
│   Structured Scientific Results                                        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Emits ScientificRunResult (Immutable)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                     Grounded AI Synthesis Layer                        │
│   (Groq / Gemini in services/ai/ | Natural Language Diagnostics Only)  │
└────────────────────────────────────────────────────────────────────────┘
```

### Strict Engine Invariants

1. **Zero External I/O**: The scientific engine performs no network calls, HTTP requests, database transactions, or cloud blob interactions.
2. **Zero LLM Dependency**: The engine does not call Groq, Gemini, or any LLM. All engineering derivations are deterministic mathematical and physical formulations.
3. **No Algorithmic Premature Execution in Step 1**: Step 1 establishes purely the data models, contracts, boundary interfaces, and architectural specifications required for Step 2 and beyond.

---

## 2. Locked Scientific Pipeline Flow

The execution sequence within the scientific engine follows a strict linear physical dependency chain:

1. **Electrical Data**: Raw channel telemetry readings and sensor packets received by `ingestion/`.
2. **Data Validation**: Sanity checks, physical boundary rules, and rate-of-change validation performed by `validation/`.
3. **Electrical Calculations**: Deterministic RMS values, power quantities, and fundamental feature derivations in `features/`.
4. **Transformer Loading**: Per-phase and three-phase apparent power loading ratios against rated nameplate capacity in `features/`.
5. **Thermal Analysis**: Ambient temperature coupling, top-oil rise, and winding hot-spot differential tracking in `thermal/`.
6. **Phase Imbalance**: Symmetrical component transformation, negative-sequence/zero-sequence ratios (VUF, PVUR, CUF), and neutral current estimation in `imbalance/`.
7. **Anomaly Detection**: Statistical deviation tracking, baseline distribution profiling, and multivariate outlier detection in `anomaly/`.
8. **Decision Intelligence**: Deterministic Health Index (DHI), operating risk classification, and prioritized maintenance guidance in `decisions/`.
9. **Structured Scientific Results**: Comprehensive immutable container (`ScientificRunResult`) encapsulating all outputs, issues, and provenance.

---

## 3. Shared Scientific Contracts Source of Truth

To prevent competing or divergent definitions, **`scientific/contracts/` is the single source of truth** for all shared data types across the engine.

Module-specific packages (`ingestion/`, `validation/`, `features/`, `thermal/`, `imbalance/`, `anomaly/`, `decisions/`) import and reference these shared contracts without defining competing structures.

### Key Shared Types

| Class / Enum             | Module                             | Role & Invariants                                                                              |
| :----------------------- | :--------------------------------- | :--------------------------------------------------------------------------------------------- |
| `EvidenceClassification` | `scientific.contracts.enums`       | Locked 5-level evidence tag (`MEASURED`, `CALCULATED`, `MODELED`, `INFERRED`, `UNKNOWN`).      |
| `MeasurementQuality`     | `scientific.contracts.enums`       | Telemetry status (`GOOD`, `SUSPECT`, `BAD`, `MISSING`, `OUT_OF_RANGE`, `CALIBRATION_EXPIRED`). |
| `Measurement[T]`         | `scientific.contracts.measurement` | Generic container binding a physical value to unit, evidence, quality, and UTC timestamp.      |
| `UnitMetadata`           | `scientific.contracts.measurement` | Dimensional metadata and canonical unit mapping.                                               |
| `TransformerAssetSpec`   | `scientific.contracts.asset`       | Static transformer nameplate ratings and design parameters.                                    |
| `StandardReference`      | `scientific.contracts.standards`   | Formal standard citation with identifier, edition/year, purpose, and context.                  |
| `EngineeringAssumption`  | `scientific.contracts.provenance`  | Explicit assumption tracking with parameter, value, rationale, and sensitivity impact.         |
| `ProvenanceMetadata`     | `scientific.contracts.provenance`  | Execution metadata, input SHA-256 digest, standards list, and evidence tally.                  |
| `ProcessingIssue`        | `scientific.contracts.issues`      | Structured diagnostics for non-crashing execution.                                             |
| `ScientificRunResult`    | `scientific.contracts.results`     | Top-level immutable container for full pipeline execution.                                     |

---

## 4. Core Measurement Representation

Every physical observation in GridPulse is represented as an instance of `Measurement[T]`:

```python
@dataclass(frozen=True)
class Measurement(Generic[T]):
    value: Optional[T]
    unit: str
    evidence: EvidenceClassification
    quality: MeasurementQuality
    timestamp: datetime
    sensor_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
```

### Invariants:

- `timestamp` must be timezone-aware and set strictly to UTC (`timezone.utc`).
- If `quality == MeasurementQuality.MISSING`, then `value` must be `None`, and `evidence` must be `EvidenceClassification.UNKNOWN`.
- Missing telemetry must never be silently fabricated or substituted with zeros or averages.

---

## 5. Asset Identification Requirements

Every telemetry packet and scientific execution must bind to a unique, immutable distribution transformer specification (`TransformerAssetSpec`):

- **Unique Identifier**: `asset_id` (e.g., `TX-SUB04-DT012`).
- **Nameplate Electrical Ratings**: `rated_power_kva`, `primary_voltage_v`, `secondary_voltage_v`, `rated_frequency_hz` (50.0 or 60.0), `phases` (1 or 3).
- **Physical Design Specifications**: `cooling_type` (`ONAN`, `ONAF`, etc.), `winding_material` (`COPPER`, `ALUMINUM`), `insulation_class` (`CLASS_A_105`, etc.), `vector_group` (e.g., `Dyn11`).
- **Losses & Impedance**: `impedance_percent` (%Z), `no_load_loss_kw`, `full_load_loss_kw`.
- **Operational Boundaries**: `operational_limits` (`OperationalLimits`) specifying continuous overload limit, emergency limit, and maximum allowable hot-spot and top-oil temperatures.

---

## 6. Timestamp Requirements and Conventions

- **Timezone**: Strictly ISO 8601 UTC. Naive datetimes without timezone information are rejected immediately at validation boundary.
- **Cadence**: Ingestion and validation record `nominal_interval_seconds` (e.g., 60, 300, 900 seconds).
- **Monotonicity**: Interval sequences must be strictly monotonically increasing. Backward timestamp jumps or duplicate timestamps are flagged as invalid data.
- **Explicit Gaps**: If an expected interval is missing, an explicit missing interval record is created with `quality=MISSING` rather than silently interpolating.

---

## 7. Measurement Units & Unit Metadata

`UnitMetadata` defines baseline dimensional metadata and establishes canonical units:

| Dimension             | Canonical Unit | Alternate Supported Units |
| :-------------------- | :------------- | :------------------------ |
| Voltage               | `V`            | `kV`                      |
| Current               | `A`            | `mA`                      |
| Active Power          | `kW`           | `W`, `MW`                 |
| Reactive Power        | `kVAR`         | `VAR`, `MVAR`             |
| Apparent Power        | `kVA`          | `VA`, `MVA`               |
| Frequency             | `Hz`           | —                         |
| Temperature           | `degC`         | —                         |
| Dimensionless / Ratio | `ratio`        | `pu`, `percent`           |
| Time                  | `seconds`      | `hours`                   |

_Note_: UnitMetadata establishes dimensions and canonical units; full automated conversion engines are deferred to later steps.

---

## 8. Measurement Quality & Status Representation

Telemetry points carry explicit `MeasurementQuality` tags:

1. `GOOD`: Physical measurement verified within normal operational and physical bounds.
2. `SUSPECT`: Physically plausible, but exhibiting abnormal gradients, improbable power factors, or sudden spikes.
3. `BAD`: Physically impossible reading (e.g., negative frequency, negative voltage magnitude, ambient temperature > 80°C).
4. `MISSING`: Data packet dropped, communication timeout, or unmetered channel. Value is `None`.
5. `OUT_OF_RANGE`: Sensor transducer saturation or hardware clipping limits exceeded.
6. `CALIBRATION_EXPIRED`: Sensor calibration period has lapsed.

---

## 9. Evidence Classification System

The 5 locked evidence classifications represent the degree of physical certainty:

1. **`MEASURED`**: Direct physical observation from hardware CT, PT, or calibrated sensor.
2. **`CALCULATED`**: Exact mathematical derivation derived directly from `MEASURED` data using closed-form electrical formulas.
3. **`MODELED`**: Output of deterministic physical differential or empirical models (e.g., IEEE C57.91 thermal models) requiring design parameters.
4. **`INFERRED`**: Statistical distribution correlation, unsupervised clustering, or ML anomaly score based on historical data.
5. **`UNKNOWN`**: Unmetered, indeterminate, corrupted, or physically unobservable parameter.

### Integrity Rule:

Evidence levels are strictly immutable and can never be artificially upgraded. An `INFERRED` value can never be presented as `CALCULATED` or `MEASURED`.

---

## 10. Missing-Data & Invalid-Data Behavior

### Missing Data:

- Represented explicitly: `value = None`, `quality = MeasurementQuality.MISSING`, `evidence = EvidenceClassification.UNKNOWN`.
- Never forward-filled, back-filled, or zero-filled silently.
- If an unmetered input (such as ambient temperature) is required by a physical model, an explicit `EngineeringAssumption` must be registered, and the output evidence downgraded appropriately to `MODELED`.

### Invalid Data:

- Telemetry marked `BAD` or `OUT_OF_RANGE` is quarantined from deterministic calculations.
- If insufficient valid telemetry exists to evaluate a formula, the output remains `None` with `evidence=UNKNOWN`, and a `ProcessingIssue` is logged.

---

## 11. Error-Handling Principles & Exceptions

The engine provides dual execution modes:

- **Strict Mode**: Raises typed domain exceptions (`TelemetryValidationError`, `PhysicalBoundaryError`, `ContractViolationError`) immediately upon failure.
- **Fault-Tolerant Mode**: Captures issues into `ProcessingIssue` records (`CRITICAL`, `WARNING`, `INFO`) while computing all physically observable metrics.

---

## 12. Provenance, Traceability & Standards Representation

Every `ScientificRunResult` embeds a `ProvenanceMetadata` object:

- `pipeline_version`: Version string of the scientific engine.
- `execution_timestamp`: Exact UTC execution time.
- `telemetry_digest`: SHA-256 cryptographic digest of raw telemetry data, guaranteeing mathematical reproducibility.
- `standards_referenced`: List of `StandardReference` instances.
- `assumptions_applied`: List of `EngineeringAssumption` instances.
- `evidence_tally`: Dictionary tallying metrics across the 5 evidence levels.

### Standards Representation Rule:

Citing an engineering standard (e.g., `IEEE C57.91-2011`, `IEC 60076-7:2018`) documents the design context, edition, and target methodology. It does **not** claim that a calculation is validated merely because the standard is cited. Actual implementation and numerical validation occur in subsequent steps.

---

## 13. Separation of Concerns

```
┌─────────────────────────────────────────────────────────────┐
│ Tier 1: Deterministic Physics (Closed-Form IEEE / IEC)      │
│ (features/, thermal/, imbalance/ | Pure Mathematics)        │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│ Tier 2: Statistical Analytics & Machine Learning            │
│ (anomaly/ | Distribution Baselines, Outlier Scores)         │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│ Tier 3: Grounded Generative AI Explanation                  │
│ (services/ai/ | Natural Language Synthesis ONLY)            │
└─────────────────────────────────────────────────────────────┘
```

- Large Language Models (LLMs) are **never** permitted inside `scientific/`.
- AI models only consume the structured `ScientificRunResult` and translate validated metrics into natural language briefings.

---

## 14. Module Responsibilities

| Directory                | Core Responsibility                                                         | Primary Output Contract                                |
| :----------------------- | :-------------------------------------------------------------------------- | :----------------------------------------------------- |
| `scientific/ingestion/`  | Raw telemetry parsing, interval alignment, schema normalization.            | `RawTelemetryBatch`                                    |
| `scientific/validation/` | Physical boundary filtering, sanity checking, quality tagging.              | `ValidatedTelemetryBatch`                              |
| `scientific/features/`   | Deterministic electrical derivations and transformer loading ratios.        | `ElectricalFeaturesResult`, `TransformerLoadingResult` |
| `scientific/thermal/`    | IEEE/IEC thermal differential modeling, hot-spot and loss-of-life analysis. | `ThermalStateResult`                                   |
| `scientific/imbalance/`  | Symmetrical component unbalance (VUF, PVUR, CUF) and neutral current.       | `PhaseImbalanceResult`                                 |
| `scientific/anomaly/`    | Statistical baseline learning, time-series drift, and outlier detection.    | `AnomalyAssessmentResult`                              |
| `scientific/decisions/`  | Deterministic Health Index, operating risk classification, and guidance.    | `AssetDecisionResult`                                  |
| `scientific/tests/`      | Unit tests, physical conservation law tests, and contract verification.     | Automated Test Suite                                   |
| `scientific/contracts/`  | **Single source of truth** for all shared data types and schemas.           | Shared Contracts Library                               |
