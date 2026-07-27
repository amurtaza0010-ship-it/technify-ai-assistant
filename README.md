# Technify Academic AI Assistant (TAIA)

ERP-integrated academic chatbot microservice that answers natural-language queries for students, faculty, and administrators using JWT/RBAC, dual RAG, and multi-LLM fallback.

## Key Features

- **Natural-language academic Q&A** — Intent classification, ERP data fetch, and contextual LLM replies for attendance, results, fees, timetable, exams, and more
- **Role-based access control (RBAC)** — Student, Faculty, Admin, Finance Officer, and Exam Officer scopes enforced on chat and demo APIs
- **JWT authentication** — Tokens issued by Mock ERP (or real ERP); FastAPI validates Bearer tokens on protected routes
- **Policy knowledge base (RAG)** — ChromaDB + `all-MiniLM-L6-v2` embeddings over university policy markdown in `data/documents/`
- **Admin hybrid RAG** — Upload CSV / XLSX / JSON / PDF / DOCX; FAISS + BM25 (RRF) retrieval with streaming answers
- **Streaming chat** — Server-Sent Events (SSE) via `/api/v1/chat/stream` and `/api/v1/chat/rag`
- **Multi-LLM fallback** — Groq (primary) → OpenRouter → Google Gemini Flash
- **Conversation memory** — Redis-backed chat history with in-memory fallback
- **Study planner** — Rule-based study recommendations from student results
- **Audit & usage analytics** — SQLite audit log with admin dashboard endpoints and UI
- **Flask UI + React chat widget** — Login, main chat, admin dashboard, and admin RAG chat pages
- **Mock ERP** — FastAPI stand-in for university ERP REST APIs (synthetic JSON datasets)

## Tech Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.10+ / 3.11 |
| AI API | FastAPI, Uvicorn / Gunicorn |
| UI | Flask (Jinja) + React 19 / Vite / Tailwind chat widget |
| LLM orchestration | LangChain (`langchain-openai`, `langchain-community`, `langchain-chroma`, `langchain-huggingface`) |
| LLM providers | Groq, OpenRouter, Google Gemini |
| Policy vector store | ChromaDB |
| Admin RAG | FAISS (`faiss-cpu`) + BM25 (`rank-bm25`) |
| Embeddings | sentence-transformers / HuggingFace `all-MiniLM-L6-v2` |
| Memory | Redis (+ in-memory fallback) |
| Auth | python-jose (JWT HS256) |
| Audit DB | SQLAlchemy + SQLite |
| HTTP client | httpx |
| Docs / data | pandas, pdfplumber, python-docx, openpyxl, Faker |
| Containers | Docker Compose (Redis, Mock ERP, FastAPI, Flask) |

## Architecture Overview

```
Browser (Flask UI :5000)
  │  login  → Flask proxy → Mock ERP /api/v1/auth/login → JWT
  │  chat   → Authorization: Bearer <jwt>
  ▼
FastAPI TAIA (:8000)  POST /api/v1/chat[/stream]
  │  verify JWT → classify intent → RBAC check
  ├─ study_plan     → study_planner (rule-based)
  ├─ policy / rules → Chroma knowledge base (RAG)
  ├─ profile / hello → JWT + prompt context
  └─ ERP intents    → Mock ERP REST (:8801 / :8001)
  ▼
LLM reply (Groq → OpenRouter → Gemini) + Redis history + audit log
```

**Admin RAG path:** upload file → FAISS + BM25 index → `POST /api/v1/chat/rag` → hybrid retrieve → streamed LLM answer (no ERP).

## Installation

```bash
# Clone and enter the project
git clone https://github.com/your-org/technify-ai-assistant.git
cd technify-ai-assistant

# Create and activate a virtual environment
python -m venv venv
# Windows:
.\venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Generate synthetic ERP data and ingest policy documents into ChromaDB
python scripts/generate_data.py
python scripts/ingest_documents.py
```

Copy `.env.example` to `.env` and set at least one LLM key (`GROQ_API_KEY`, `OPENROUTER_API_KEY`, or `GEMINI_API_KEY`) plus `JWT_SECRET_KEY` (must match the ERP).

Optional (all-in-one npm runner):

```bash
npm install
```

## How to Run

### Development (three terminals)

**Terminal 1 — Mock ERP** (port `8801`; Docker maps `8001`):

```bash
uvicorn mock_erp.main:app --reload --host 127.0.0.1 --port 8801
```

**Terminal 2 — FastAPI AI backend** (port `8000`):

```bash
python -m app.main
# or: uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**Terminal 3 — Flask UI** (port `5000`):

```bash
python ui_app/app.py
```

Open **http://127.0.0.1:5000**

Or run all three with:

```bash
npm run dev
# or: scripts/start_dev.ps1  /  scripts/start_dev.sh
```

### Docker

```bash
docker-compose up --build -d
```

Services: Redis (`6379`), Mock ERP (`8001`), FastAPI (`8000`), Flask (`5000`).

### React chat widget

```bash
cd chat_widget
npm install
npm run build   # copy dist assets into ui_app/static/ if filenames change
npm run dev     # hot reload on :5173 (proxies /api → :8000)
```

## API Endpoints

### FastAPI AI backend (`:8000`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Service info |
| `GET` | `/health` | Health + vector-store warmup status |
| `GET` | `/docs`, `/redoc` | OpenAPI docs |
| `POST` | `/api/v1/chat` | Main chat (JWT); `{response, intent, time, perf}` |
| `POST` | `/api/v1/chat/stream` | Same pipeline over SSE |
| `GET` | `/api/v1/chat/history/list/{user_id}` | List chat sessions |
| `GET` | `/api/v1/chat/history/{user_id}` | Load session messages (`?session_id=`) |
| `POST` | `/api/v1/chat/rag` | Admin RAG chat (SSE) |
| `GET` | `/api/v1/admin/audit-logs` | Recent audit rows (Admin) |
| `GET` | `/api/v1/admin/usage-stats` | Usage stats (Admin) |
| `GET` | `/api/v1/admin/rag/status` | Admin RAG index status |
| `POST` | `/api/v1/admin/rag/upload` | Upload & ingest admin RAG file |
| `GET` | `/api/v1/student/attendance` | Demo student attendance |
| `GET` | `/api/v1/faculty/at-risk-students` | Demo faculty at-risk list |
| `GET` | `/api/v1/admin/fee-report` | Demo admin fee report |

### Flask UI (`:5000`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Main chat UI |
| `GET` | `/admin` | Admin dashboard (audit / metrics) |
| `GET` | `/admin/rag-chat` | Admin RAG upload + chat UI |
| `POST` | `/api/v1/auth/login` | Proxy login → Mock ERP |

### Mock ERP (`:8801` / `:8001`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/`, `/health` | Health |
| `POST` | `/api/v1/auth/login` | Issue JWT `{user_id, role}` |
| `GET` | `/api/v1/student/{id}/*` | Profile, attendance, results, GPA, courses, timetable, exams, assignments, fees |
| `GET` | `/api/v1/faculty/{id}/*` | Teaching, courses, assignments, course analytics |
| `GET` | `/api/v1/admin/*` | Statistics, fees, at-risk, exams, finance |

## Environment Variables

Create a `.env` in the project root (see `.env.example`). Important variables:

| Variable | Purpose |
|----------|---------|
| `GROQ_API_KEY` / `LLM_API_KEY` / `OPENAI_API_KEY` | Primary LLM credentials (Groq preferred) |
| `LLM_BASE_URL` | OpenAI-compatible base URL (default Groq or OpenRouter) |
| `GROQ_PRIMARY_MODEL` / `LLM_MODEL` | Primary chat model |
| `LLM_FALLBACK_MODEL` | OpenRouter fallback model |
| `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL` | OpenRouter fallback |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Gemini tertiary fallback |
| `ERP_API_BASE_URL` | Mock/real ERP API root (e.g. `http://127.0.0.1:8801/api/v1`) |
| `TAIA_API_URL` | Browser-facing FastAPI URL (`http://127.0.0.1:8000`) |
| `ERP_PUBLIC_URL` | Browser-facing ERP URL |
| `JWT_SECRET_KEY`, `JWT_ALGORITHM` | Must match ERP JWT config (`HS256`) |
| `CHROMA_PERSIST_DIR` | Policy vector store path (`./data/vector_store`) |
| `ADMIN_RAG_PERSIST_DIR`, `ADMIN_BM25_INDEX_PATH` | Admin hybrid RAG storage |
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_DB`, `REDIS_URL` | Chat memory |
| `DATABASE_URL` | Audit SQLite/DB URL (defaults to local `.audit.db`) |
| `CORS_ALLOW_ALL`, `CORS_ORIGINS` | CORS for UI origins |
| `APP_HOST`, `APP_PORT`, `APP_DEBUG`, `LOG_LEVEL` | Server / logging |
| `SECRETS_ENCRYPTION_KEY` | Optional secrets encryption |

## Project Structure

```
technify-ai-assistant/
├── app/                      # FastAPI AI backend
│   ├── main.py               # Entry point & API routes
│   ├── config.py             # Settings (LLM, ERP, Admin RAG)
│   ├── auth/                 # JWT + RBAC
│   ├── chains/               # Intent, memory, ERP handlers, chat
│   ├── services/             # LLM, RAG, ERP, audit, study planner
│   ├── middleware/           # JWT middleware
│   ├── prompts/              # Prompt templates
│   └── models/               # Data models
├── ui_app/                   # Flask frontend
│   ├── app.py
│   ├── templates/            # index, admin, rag_chat
│   └── static/               # CSS/JS + built React widget
├── chat_widget/              # React + Vite + Tailwind chat UI
├── mock_erp/                 # Mock university ERP (FastAPI)
├── config/                   # Shared ERP / Redis / secrets / logging
├── memory/                   # Redis conversation memory
├── logging/                  # Audit logger & telemetry
├── data/
│   ├── documents/            # Policy markdown (RAG corpus)
│   ├── synthetic/            # Generated Mock ERP JSON
│   ├── vector_store/         # ChromaDB (generated)
│   └── admin_rag_store/      # FAISS + BM25 (generated)
├── scripts/                  # Data gen, ingest, audit helpers
├── tests/                    # pytest suite
├── docs/                     # Architecture & API docs
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## Future Improvements

- Connect to a production ERP instead of the Mock ERP
- Persistent multi-tenant conversation analytics and dashboards
- Stronger evaluation harness for retrieval quality and hallucination checks
- Optional PostgreSQL for audit logs at scale
- Hardened production secrets management and rate limiting per role

## License and Credits

**Internal project — Technify Software House © 2026**

Built by the Technify AI internship team (architecture, FastAPI gateway, ERP connectors, LangChain / RAG, synthetic data, and UI). See `docs/` and `team_setup_guide.md` for deeper setup and sprint notes.
