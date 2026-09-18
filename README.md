# GridPulse

> **Electricity Distribution Infrastructure Intelligence**

GridPulse provides software-first, cloud-native, hardware-agnostic intelligence for electricity distribution infrastructure. By transforming existing, underutilized field telemetry into deterministic physical insight and actionable decisions, GridPulse helps distribution asset managers reduce unpredicted failures, optimize capital allocation, and enhance reliability.

---

## 1. Initial Product: Distribution Asset Intelligence Layer (DAIL)

GridPulse's initial commercial and technological product is the **Distribution Asset Intelligence Layer (DAIL)**.

### Initial Focus

DAIL focuses squarely on **distribution transformer intelligence**. Distribution transformers represent critical, capital-intensive nodes within medium- and low-voltage distribution networks. Despite being mission-critical, they often operate with sparse, unvalidated, or fragmented monitoring. GridPulse extracts high-fidelity physical diagnostics from legitimate existing telemetry (such as SCADA, AMR, AMI, and interval data) without requiring mandatory proprietary hardware replacement.

### Approach

- **Cloud-Native**: Horizontally scalable time-series ingestion and analytical processing.
- **Software-First**: Immediate value delivery through data synthesis rather than prolonged sensor hardware rollouts.
- **Hardware-Agnostic**: Compatible with standard industrial protocols, utility data formats, and diverse meter manufacturers.

### Target Customer Segments

1. **Private Industrial Facilities**: Continuous-process manufacturing, chemical, automotive, and metallurgy plants where unscheduled distribution outages incur catastrophic downtime costs.
2. **Private Utilities**: Concessionaires and private power distribution entities seeking operational expenditure efficiency and rigorous asset life extension.
3. **High-Reliability Campuses & Data Centers**: Mission-critical facilities where transformer failure or power quality degradation directly threatens uptime SLAs.
4. **AMISP & System Integrators**: Advanced Metering Infrastructure Service Providers needing an intelligence layer above raw metering head-end systems.

_Subsequent Expansion_: Public distribution utilities (DISCOMs) and large regional power networks will be addressed only after formal technical validation, measurable customer ROI verification, and proven enterprise repeatability.

### Long-Term Trajectory

```
Distribution Asset Intelligence (DAIL)
  ↳ Distribution Grid Intelligence (Feeder & Substation Topology)
      ↳ Intelligent Grid Infrastructure (Automated Network Optimization)
```

_Explicit Scope Exclusions_: GridPulse does not build products for agriculture or consumer healthcare.

---

## 2. Locked Scientific Architecture

GridPulse enforces a strict separation among three computational tiers to ensure physical validity and operational safety:

```
┌─────────────────────────────────────────────────────────────┐
│ Tier 1: Deterministic Electrical Engineering                │
│ (Physics, IEC/IEEE loading equations, thermal models, loss) │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│ Tier 2: Statistical Analytics & Machine Learning             │
│ (Time-series drift, baseline clustering, anomaly detection) │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│ Tier 3: Grounded Generative AI                              │
│ (Diagnostic explanation, executive synthesis, triage reports)│
└─────────────────────────────────────────────────────────────┘
```

### Core Principle: The LLM is NOT the Scientific Engine

- Large Language Models (LLMs) are **never** permitted to calculate power flow, predict transformer temperatures, or fabricate electrical metrics.
- Physical parameters must originate exclusively from deterministic mathematical equations governed by recognized engineering standards (IEEE C57 / IEC 60076).
- Generative AI is deployed strictly as an interpretation and synthesis layer, grounded entirely in validated deterministic and statistical outputs.
- Telemetry is never presumed to measure what it cannot directly observe.

### Scientific Evidence Classification

Every metric, alert, and diagnostic produced by GridPulse carries an explicit scientific evidence label:

| Evidence Label   | Definition                                                                    | Example in DAIL                                                     |
| :--------------- | :---------------------------------------------------------------------------- | :------------------------------------------------------------------ |
| **`MEASURED`**   | Direct physical observation from calibrated sensors or meters                 | Phase voltage ($V$), line current ($I$), frequency ($f$)            |
| **`CALCULATED`** | Exact mathematical or electrical formula derived from measured inputs         | Apparent power ($S$), active power ($P$), power factor ($\cos\phi$) |
| **`MODELED`**    | Deterministic physical or empirical model output with documented assumptions  | Top-oil temperature, hot-spot temperature, thermal aging rate       |
| **`INFERRED`**   | Statistical or machine learning correlation based on historical distributions | Operational regime clustering, anomaly score                        |
| **`UNKNOWN`**    | Telemetry missing, unvalidated, out-of-bounds, or physically indeterminate    | Unmetered phase loading, uncalibrated oil quality                   |

---

## 3. Locked Technology Stack

The GridPulse architecture is built upon a validated, production-grade foundation:

- **Frontend Application**:
  - **Framework**: Next.js 16 (App Router, React 19, TypeScript)
  - **Styling & UI**: Tailwind CSS v4, shadcn/ui (Base UI foundation, Nova preset)
  - **Icons & Motion**: Lucide React, Framer Motion
  - **Visualization**: Recharts (time-series, load profiles, harmonic spectra)
  - **Data Tables**: TanStack Table v8
  - **Form & Validation**: React Hook Form, Zod

- **Authentication & Application Database**:
  - **Authentication**: Firebase Authentication
  - **Application Database**: Firebase Cloud Firestore (structured asset metadata, access controls, event streams)

- **File & Blob Storage**:
  - **Storage Provider**: Supabase Storage **ONLY** (raw interval files, diagnostic attachments, bulk telemetry exports)
  - _Architectural Note_: Supabase is strictly file storage; it is **not** the application database.

- **AI Inference Layer**:
  - **Primary**: Groq (ultra-low latency structured reasoning & diagnostic summarization)
  - **Secondary**: Gemini (multimodal document ingestion and complex asset report synthesis)

- **Scientific Engine**:
  - **Runtime**: Python 3.12
  - **Core Computation**: NumPy, Pandas, SciPy, scikit-learn
  - **Service Architecture**: FastAPI backend service (when decoupled execution is required)

- **Source Control & Deployment**:
  - **VCS**: Git + GitHub (`https://github.com/rohitkalyan505-design/gridpulse.git`)
  - **Hosting**: Vercel (Next.js Application), Firebase, Supabase Storage

- **Testing & Quality Assurance**:
  - **Frontend / Integration**: Vitest, Playwright
  - **Scientific Engine**: pytest (Python unit & numerical validation suites)
  - **Code Quality**: TypeScript strict mode (`tsc --noEmit`), ESLint, Prettier

---

## 4. Repository Structure

```
gridpulse/
├── app/                      # Next.js App Router (pages, layouts, route handlers)
│   ├── (public)/             # Public access routes
│   ├── dashboard/            # Executive operational dashboard
│   ├── assets/               # Distribution asset hierarchy (substations, transformers)
│   ├── analytics/            # High-resolution time-series & load profile analysis
│   ├── alerts/               # Physical threshold & anomaly triage management
│   ├── reports/              # Automated engineering and executive asset health reports
│   ├── settings/             # Organization and ingestion configuration
│   └── admin/                # System administration and access control
├── components/               # UI components
│   ├── ui/                   # Reusable base primitives (shadcn Base UI / Nova)
│   ├── charts/               # Electrical charts, load curves, heatmaps
│   ├── tables/               # High-density asset & telemetry data tables
│   ├── forms/                # Ingestion configuration and parameter forms
│   └── domain/               # Domain-specific transformer & feeder components
├── lib/                      # Shared libraries & utilities
│   ├── firebase/             # Firebase Auth and Firestore client initialization
│   ├── supabase/             # Supabase Storage client wrapper
│   ├── auth/                 # Authentication state and token helpers
│   ├── permissions/          # Role-based access control (RBAC) definitions
│   ├── api/                  # API client bindings
│   └── validation/           # Zod schemas for application data
├── services/                 # Server-side orchestration & domain services
│   ├── analytics/            # Telemetry aggregation & feature extraction orchestration
│   ├── alerts/               # Alert generation, escalation, and deduplication
│   ├── reports/              # Report generation and export pipeline
│   ├── integrations/         # External utility system connectors
│   └── ai/                   # Grounded AI synthesis prompts & provider clients
├── scientific/               # Pure Python Scientific Engine
│   ├── ingestion/            # Raw telemetry parsers and interval normalizers
│   ├── validation/           # Physical boundary checking and sanity filtering
│   ├── features/             # Electrical feature engineering (unbalance, harmonics, THD)
│   ├── thermal/              # IEEE/IEC transformer thermal & loss-of-life models
│   ├── imbalance/            # Symmetrical component & phase imbalance calculations
│   ├── anomaly/              # Statistical drift and anomaly detection algorithms
│   ├── decisions/            # Deterministic asset health indexing & decision logic
│   ├── tests/                # Scientific validation and numerical unit tests
│   └── requirements.txt      # Pinned scientific Python dependencies
├── tests/                    # Application-level automated tests
│   ├── unit/                 # Frontend unit tests
│   └── e2e/                  # End-to-end integration workflows (Playwright)
├── docs/                     # Technical, architectural, and scientific documentation
│   ├── architecture/         # System architecture specifications
│   ├── science/              # Engineering equations, standards, and references
│   ├── api/                  # API schemas and endpoint contracts
│   └── security/             # Security, credential isolation, and RBAC policies
├── .env.example              # Documented environment variable template
├── .gitignore                # Comprehensive security & environment protection
├── .prettierrc               # Prettier code formatting standards
├── package.json              # Node.js project manifest & scripts
└── README.md                 # Project & company documentation
```

---

## 5. Development Principles

1. **Engineering Grounding**: Physical laws (Ohm's Law, Kirchhoff's Laws, symmetrical components, thermal dynamics) govern core logic. No probabilistic approximation may override physical constraints.
2. **Deterministic Reproducibility**: Given the same input telemetry, the scientific engine produces identical diagnostic results every time.
3. **Defense in Depth**: Zero secrets in source control. Strict boundary separation between public web code, server execution, and scientific environments.
4. **Clean Decoupling**: Frontend components never perform direct heavy numerical calculations; the scientific engine is independent of presentation concerns.
5. **No Premature Claims**: We do not claim features that have not undergone rigorous mathematical validation, peer review against engineering standards, and complete acceptance testing.

---

## 6. Current Development Status

**Current Phase: Phase 1 — Development Foundation**

- Next.js 16 + TypeScript + Tailwind CSS initialized and verified.
- shadcn/ui (Base UI + Nova preset) configured.
- ESLint and Prettier configured and passing.
- Python 3.12 scientific virtual environment initialized with NumPy, Pandas, SciPy, and scikit-learn.
- Repository architecture established.
- Security boundaries, `.gitignore`, and `.env.example` templates locked.
- _Notice_: Scientific algorithms, thermal calculations, transformer loading analytics, AI prompts, and customer dashboards are **not yet implemented**. They are formally scheduled for **Phase 2 (Scientific Engine & Core Intelligence)** and subsequent phases.
