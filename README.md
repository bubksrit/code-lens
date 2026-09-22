# PRISM Agentic Code Intelligence

> **Samsung PRISM Gen AI Hackathon 3.0 - Theme 1 Prototype**
> An agentic developer assistant for exploring Python codebases using controlled, deterministic tools, gathering validated evidence, and synthesizing grounded answers with exact file and line references.

---

## Technical Stack

- **Backend**: Python 3.10+, FastAPI, Pydantic v2, Pytest, Uvicorn
- **Frontend**: React 18, TypeScript, Vite
- **Retrieval & Analysis**: BM25 Lexical Retrieval, Python AST Structural Analysis
- **Architecture**: LLM provider interface with deterministic Mock Provider (for offline tests) & Gemini/OpenAI integration.

---

## Directory Structure

```text
.
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI routers & health check endpoint
│   │   ├── models/       # Grounded evidence & tool schemas
│   │   ├── ingestion/    # Repository parsing & AST analysis
│   │   ├── retrieval/    # BM25 lexical retrieval engine
│   │   ├── graph/        # Static call graph builder
│   │   ├── agent/        # Controlled tool registry & agent loop
│   │   ├── validation/   # Evidence line-level validator
│   │   └── config.py     # Pydantic v2 settings
│   └── tests/            # Pytest test suite (100% offline runnable)
├── frontend/             # Vite + React + TypeScript web application
├── data/
│   └── demo_repo/        # Sample Python repository for testing
├── docs/                 # Architecture & design documentation
├── scripts/              # Development launcher scripts
├── pyproject.toml
├── .env.example
├── Dockerfile
└── README.md
```

---

## Quick Start & Setup Instructions

### 1. Environment Configuration

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

*(Optional API keys like `GEMINI_API_KEY` can be left blank for offline mock mode).*

### 2. Backend Setup & Run

Install dependencies:
```bash
python -m pip install -e .[dev]
```

Run backend tests:
```bash
python -m pytest backend/tests -v
```

Start backend FastAPI server:
```bash
python -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```
Or on Windows:
```cmd
scripts\run_dev.bat
```
Or on Linux/macOS:
```bash
bash scripts/run_dev.sh
```

Access the interactive API docs at `http://localhost:8000/docs` and test `GET /health` at `http://localhost:8000/health`.

---

### 3. Frontend Setup & Run

Navigate to frontend directory and install Node dependencies:
```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000` in your browser.

---

### 4. Run via Docker

Build Docker container:
```bash
docker build -t prism-agentic-code-intelligence .
```

Run Docker container:
```bash
docker run -p 8000:8000 prism-agentic-code-intelligence
```

---

## Verification & Testing

Run all unit tests:
```bash
python -m pytest backend/tests -v
```

Expected output:
```text
backend/tests/test_config.py PASSED
backend/tests/test_health.py PASSED
backend/tests/test_main.py PASSED
7 passed
```

---

## Security & Grounding Principles

1. **No Untrusted Shell/Code Execution**: The LLM agent operates exclusively through sandboxed, read-only tools.
2. **Deterministic Evidence Validation**: Claims in synthesized answers are checked against physical file bounds (`file:start_line-end_line`).
3. **No Secrets**: Zero credentials or hardcoded keys are committed.
