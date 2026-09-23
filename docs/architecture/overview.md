# GridPulse Architecture Overview

## Status Demarcation

- **CURRENT (Phase 1 & Phase 2 Steps 1–3)**: Development Foundation, Scientific Architecture, Data Validation, and Deterministic Electrical Calculations. Next.js 16 App Router, TypeScript, Tailwind CSS, shadcn/ui, Prettier, ESLint, Python 3.12 scientific virtual environment (`.venv`), repository scaffolding, security boundaries, formal Scientific Engine Architecture & Shared Contracts (`scientific/contracts/`), data validation engine (`scientific/validation/`), and deterministic electrical calculations (`scientific/features/`).
- **PLANNED (Phase 2 Step 4+)**: Python Scientific Engine Domain Implementations (IEEE/IEC transformer loading, thermal degradation modeling, symmetrical component unbalance, statistical anomaly detection, decision intelligence).
- **PLANNED (Phase 3)**: Core Services & Infrastructure (Firebase Auth, Firestore asset graph, Supabase Storage client, Groq/Gemini synthesis, FastAPI service bridge).
- **FUTURE (Phase 4+)**: Customer Intelligence Interfaces (executive dashboards, high-resolution load profiles, automated utility reporting, enterprise DISCOM integrations).

## Component Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    Presentation Layer                        │
│   Next.js 16 (React 19, TypeScript, Tailwind CSS, shadcn)    │
│   [CURRENT: Scaffolding | PLANNED: UI / Dashboard]           │
└──────────────┬───────────────────────────────┬───────────────┘
               │                               │
┌──────────────▼───────────────┐ ┌─────────────▼───────────────┐
│     Authentication & Data    │ │      File Storage ONLY      │
│   Firebase Auth & Firestore  │ │      Supabase Storage       │
│         [PLANNED]            │ │          [PLANNED]          │
└──────────────┬───────────────┘ └─────────────┬───────────────┘
               │                               │
┌──────────────▼───────────────────────────────▼───────────────┐
│               Service Orchestration Layer                    │
│   Next.js Server Actions & API Route Handlers                │
│         [PLANNED]                                            │
└──────────────┬───────────────────────────────┬───────────────┘
               │                               │
┌──────────────▼───────────────┐ ┌─────────────▼───────────────┐
│     Grounded AI Inference    │ │   Python Scientific Engine  │
│         Groq & Gemini        │ │   NumPy, Pandas, SciPy,     │
│   (Synthesis & Explanation)  │ │   scikit-learn (FastAPI)    │
│         [PLANNED]            │ │   [CURRENT: Env | PLANNED]  │
└──────────────────────────────┘ └─────────────────────────────┘
```

## System Responsibilities

1. **Frontend / UI**: Presentation, visualization (Recharts), tabular data interaction (TanStack Table), and user role enforcement. No heavy numerical or electrical engineering calculations are performed on the client.
2. **Persistence**: Firebase Firestore stores asset definitions, operational logs, and alarm states. Supabase Storage stores high-density interval telemetry files, raw CSV/JSON dumps, and generated PDF reports.
3. **Scientific Engine**: Executes pure mathematical, physical, and statistical computations. Fully decoupled from web framework concerns.
4. **AI Inference**: Provides human-readable diagnostic interpretation and executive briefings grounded strictly in validated scientific outputs.
