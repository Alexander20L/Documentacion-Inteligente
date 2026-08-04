# Repository Instructions

## Boundaries and entrypoints

- There is no root workspace or root build command. Run Python commands from `backend/` and npm commands from `frontend/angular-app/`.
- `backend/main.py` exposes the FastAPI `main:app`; `backend/worker.py` is a separate required process. C4 analysis and publication are leased queue jobs, so they never complete if only the API is running.
- The Angular app is standalone and boots from `frontend/angular-app/src/main.ts`; routing, authentication initialization, and the bearer-token interceptor are wired in `src/app/app.config.ts`.
- Browser authentication talks directly to Supabase. Backend requests receive the Supabase access token through `auth.interceptor.ts`.

## Commands

From `backend/` (Python 3.11+ is required because the models use `enum.StrEnum`):

```text
python -m venv .venv
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
python worker.py
python -m unittest discover -s tests -v
```

- Create `backend/.env` from `.env.example` before importing or starting the backend.
- Backend tests use the standard-library `unittest` runner above; no backend lint or formatter command is configured.

From `frontend/angular-app/` (use Node `20.19.0` from `.nvmrc`; npm is pinned in `package.json`):

```text
npm ci
npm start
npm run build
npm test -- --no-watch
npm test -- --no-watch --include src/app/app.spec.ts
npx prettier --check .
```

- `npm run build` is the configured strict TypeScript/template check. There is no lint or separate typecheck script.
- The test builder uses Vitest globals; currently `src/app/app.spec.ts` is the only test file.

## Configuration and services

- Backend import requires `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (or `SUPABASE_KEY`), and `SUPABASE_ANON_KEY`; the admin client is created at module import time.
- C4 analysis needs Git, Graphify, Tree-sitter, a configured LLM provider, and a knowledge backend. `C4_LLM_PROVIDER=ollama` runs the agents locally; `gemini` remains optional. Production defaults to self-hosted Dify through `DIFY_BASE_URL` and `DIFY_API_KEY`; `C4_KNOWLEDGE_BACKEND=memory` is only for tests or local development.
- C4 publication needs Java, Structurizr CLI, and PlantUML. Configure `STRUCTURIZR_CLI_PATH`, `PLANTUML_JAR`, and optionally `JAVA_BIN`; missing render tools fail publication rather than producing incomplete documents. Mermaid export is optional and never replaces the validated PlantUML output.
- Frontend settings are runtime data in `frontend/angular-app/public/runtime-config.js`, loaded before Angular and copied into the build. It is public: never place a service-role key or another secret there.
- Local defaults are intentionally inconsistent: Angular targets port `8000`, while `backend/.env.example`, PM2, and deployment use `8001`. Keep `apiBaseUrl`, the Uvicorn port, and proxy configuration aligned when changing environments.
- Production starts both backend processes from the repository root with `pm2 start ecosystem.config.cjs`; Nginx serves `frontend/angular-app/dist/angular-app/browser` and proxies API routes to `127.0.0.1:8001`.

## Database and processing invariants

- The Supabase SQL is ordered: an existing `public.proyectos` table is required, then apply `001_auth_rls.sql`, `002_async_worker.sql`, `003_c4_pipeline.sql`, `004_semantic_rag.sql`, and `005_c4_progress_controls.sql`. These files cannot initialize an empty database by themselves.
- `003_c4_pipeline.sql` replaces active legacy jobs, adds leased atomic claims with the attempt number as a fencing token, and permits only one active run/task per repository. Preserve its ownership checks and service-role-only mutations.
- `004_semantic_rag.sql` stores only operational metadata, identifiers, counts, and hashes. Source chunks and retrieved text remain in the canonical local run artifacts and must not be copied into database audit metadata.
- C4 execution/task states and phases are lowercase values shared by SQL, backend, and Angular. Update all consumers together.
- New uploads are immutable under the configured `REPOSITORY_STORAGE_ROOT`; C4 attempts and canonical runs use compact generated paths under `C4_STORAGE_ROOT`. Graphify cleanup runs only against the exact generated analysis attempt directory. Never point it at the immutable source or a working checkout.
- Graphify is evidence, not the C4 model. The pipeline preserves raw `graph.json`, requires explicit review of every inferred candidate, then deterministically generates the canonical Structurizr DSL, validated diagrams, Markdown, DOCX, evidence, and hashes.
- Dify is a retrieval index, not the canonical knowledge source. Tenant, repository, and immutable source hash scope every lookup; stale or unknown Dify results must be rejected against the local chunk manifest.
- Publication must not become `completado` unless Structurizr validation and every required SVG/PNG render succeed. There is no Mermaid fallback in the C4 pipeline.
