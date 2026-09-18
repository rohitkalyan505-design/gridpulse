# GridPulse Security & Credential Isolation Baseline

## Security Principles

1. **Zero Credentials in Source Control**: No production keys, service account credentials, certificates, or private keys may ever be committed to Git.
2. **Environment Variable Hygiene**: All configurable variables are registered in `.env.example` with descriptive placeholders. Local execution uses `.env.local`, which is strictly ignored by `.gitignore`.
3. **Public vs. Server Boundary**:
   - `NEXT_PUBLIC_*` variables are exposed to client-side JavaScript in the browser. They must only contain public identifiers (e.g., Firebase web client configuration, Supabase anon public key).
   - Server-only variables (e.g., `FIREBASE_PRIVATE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`) must never be prefixed with `NEXT_PUBLIC_` and must never be imported into client components.
4. **Least Privilege Principle**:
   - Web clients authenticate via Firebase Auth.
   - Firestore security rules govern document-level read/write permissions.
   - Supabase Storage access is restricted via signed URLs or backend service-role operations.
   - Scientific computing microservice endpoints are protected via shared secret token headers or internal VPC boundaries.
