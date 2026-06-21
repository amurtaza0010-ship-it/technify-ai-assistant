# Technify Academic AI Assistant (TAIA) 🎓🤖

> AI-powered academic assistant integrated with Technify University ERP

## 🏗️ Project Overview

TAIA is an intelligent chatbot microservice that integrates with the Technify University ERP system. It provides natural language support to students, faculty, and administrators for academic queries.

**Key Features:**
- 💬 Natural language Q&A for academic information
- 🔒 Role-based access control (Student, Faculty, Admin, Finance, Exam Officer)
- 📚 Knowledge base with RAG for university policies
- 📊 Study recommendations and planning
- 🔗 Secure ERP API integration (no direct database access)

## 🛠️ Tech Stack

| Technology | Purpose |
|-----------|---------|
| Python 3.11+ | Core language |
| FastAPI | Web framework |
| LangChain | LLM orchestration |
| ChromaDB | Vector database for RAG |
| OpenAI GPT / Llama | LLM backbone |
| JWT | Authentication |

## 📁 Project Structure

```
technify-ai-assistant/
├── app/
│   ├── main.py              # FastAPI entry point
│   ├── auth/                # JWT & RBAC
│   ├── api/                 # API routes & middleware
│   ├── services/            # Business logic
│   ├── chains/              # LangChain chains
│   ├── prompts/             # Prompt templates
│   └── models/              # Data models
├── data/
│   ├── synthetic/           # Test data
│   ├── documents/           # Policy PDFs
│   └── vector_store/        # ChromaDB storage
├── mock_erp/                # Mock ERP for testing
├── scripts/                 # Utility scripts
├── tests/                   # Test files
└── docs/                    # Documentation
```

## 🚀 Quick Start & Deployment

We have prepared a comprehensive setup guide that covers everything from Git cloning, environment variables, Mock Data generation, and Docker Deployment.

**Please refer to the official [TAIA Setup & Deployment Guide](./team_setup_guide.md) for full instructions.**

### Phase 1 — Project Setup (First-Time Install)

Run these commands once after cloning the repository (with your virtual environment activated):

```bash
# Clone and enter the project
git clone https://github.com/your-org/technify-ai-assistant.git
cd technify-ai-assistant

# Create and activate virtual environment
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Generate mock data and vector store (required — not committed to git)
python scripts/generate_data.py
python scripts/ingest_documents.py
```

Create a `.env` file in the project root (see `team_setup_guide.md` for the full variable list).

### Phase 2 — Development Mode (3 Terminals)

Start all three services in **separate terminal windows** (venv activated in each):

**Terminal 1 — Mock ERP (port 8001):**
```bash
uvicorn mock_erp.main:app --port 8001
```

**Terminal 2 — FastAPI AI Backend (port 8000):**
```bash
python -m app.main
```

**Terminal 3 — Flask UI with React Chat Widget (port 5000):**
```bash
python ui_app/app.py
```

Open the UI at: **http://127.0.0.1:5000**

#### Rebuilding the React Chat Widget

After making changes inside `chat_widget/`, rebuild and redeploy static assets:

```bash
cd chat_widget
npm run build
```

Then copy the generated `.js` and `.css` files from `chat_widget/dist/assets/` into `ui_app/static/` and update the filenames in `ui_app/templates/index.html` if they changed.

For local React development (hot reload on port 5173):

```bash
cd chat_widget
npm run dev
```

The Vite dev server proxies `/api` requests to `http://localhost:8000`.

### Key Deployment Features
- **Development Mode**: Run locally with direct access to FastAPI, Mock ERP, and the Flask Frontend.
- **Production Mode**: One-click deployment using `docker-compose up --build -d` which spins up the AI Gateway, Mock ERP, and a Redis container.
- **Admin Dashboard**: Integrated UI dashboard to view all user queries, latency metrics, and roles from the SQLite audit logs.

## 👥 Team

| Role | Responsibility |
|------|---------------|
| Team Lead | Architecture, LangChain pipeline, code review |
| Backend Dev 1 | FastAPI, JWT auth, API gateway |
| Backend Dev 2 | ERP connectors, audit logging |
| AI/NLP Dev | LangChain chains, prompts, conversation |
| RAG Dev | ChromaDB, document ingestion, knowledge base |
| Data/Test | Synthetic data, testing, documentation |

## 📋 Modules

1. **User Auth Verification** — JWT validation & role checking
2. **Academic Info Retrieval** — ERP API connectors
3. **Knowledge Base (RAG)** — University policy Q&A
4. **Study Recommendations** — Study plans & course suggestions
5. **Conversation Management** — Context-aware multi-turn chat

## 📄 License

Internal project — Technify Software House © 2026
