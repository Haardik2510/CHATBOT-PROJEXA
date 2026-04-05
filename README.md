# SET Academic Chatbot

A university assistant for K.R. Mangalam University / SET built with:

- a React frontend
- a FastAPI backend
- Supabase Auth
- Supabase Postgres
- Supabase Storage
- Supabase `pgvector`
- Ollama for local chat and embeddings
- a seeded KRMU knowledge dataset for bootstrap answers

The current stack supports local development, Docker-based local deployment, and a hosted split deployment such as Vercel + Render + Supabase with Ollama running on a separate machine.

## What The Project Does

The chatbot supports:

- student, faculty, and admin portals
- Supabase email/password and Google sign-in
- chat with retrieval-augmented generation
- document upload and URL ingestion
- admin analytics and user-role management
- seeded institutional knowledge for KRMU answers
- streaming backend chat endpoint support

## Tech Stack

- Frontend: React 19, CRACO, Tailwind CSS, Radix UI, Framer Motion
- Backend: FastAPI, Pydantic, httpx
- Auth: Supabase Auth
- Database: Supabase Postgres
- Vector Store: Supabase `pgvector`
- File Uploads: Supabase Storage
- Local Models: Ollama chat model plus Ollama embedding model

## Repository Structure

```text
.
├── backend/
│   ├── auth.py
│   ├── document_processor.py
│   ├── knowledge_seeder.py
│   ├── rag_engine.py
│   ├── server.py
│   ├── datasets/
│   │   └── krmu_official_knowledge.json
│   └── requirements*.txt
├── frontend/
│   ├── public/
│   ├── src/
│   ├── package.json
│   └── jsconfig.json
└── README.md
```

## Current Status

### Working

- backend starts on `http://localhost:8001`
- frontend is configured to use `http://localhost:3000`
- Supabase auth is active for email/password and Google
- Supabase document metadata, sessions, messages, analytics, storage, and vector retrieval are active
- curated KRMU dataset exists at `backend/datasets/krmu_official_knowledge.json`
- KRMU data can be seeded into the live backend
- backend streaming route exists at `POST /api/chat/stream`
- Docker support is included for frontend and backend

### Working With Limitations

- local chat generation works only as fast as the local Ollama model allows
- if Ollama stays on a weak local machine, reply latency will still be hardware-bound
- the backend still keeps a Chroma emergency fallback path in code, though live retrieval is intended to use Supabase `pgvector`

## Prerequisites

- Python 3.10+ if running without Docker
- Node.js 18+ if running without Docker
- Docker Desktop if running with Docker
- Ollama
- Supabase project

## Required Local Models

Pull at least:

```powershell
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

If local speed is a problem, a smaller installed model such as `qwen2.5:3b` is a better local-hosting choice.

## Environment Setup

### Backend

Copy `backend/.env.example` to `backend/.env` and fill it in:

```env
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_ANON_KEY=your_supabase_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key
SUPABASE_STORAGE_BUCKET=documents
JWT_SECRET_KEY=replace-with-a-strong-secret
CORS_ORIGINS=http://localhost:3000
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=meta-llama/Meta-Llama-3-8B-Instruct
LLM_REQUEST_TIMEOUT=60
LLM_MAX_TOKENS=384
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_CHAT_MODEL=llama3.2:3b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
ENABLE_WEB_FALLBACK=false
```

### Frontend

Copy `frontend/.env.example` to `frontend/.env` and fill it in:

```env
REACT_APP_BACKEND_URL=http://localhost:8001
REACT_APP_SUPABASE_URL=https://your-project-ref.supabase.co
REACT_APP_SUPABASE_ANON_KEY=your_supabase_anon_key
REACT_APP_SUPABASE_PROJECT_REF=your-project-ref
```

## Local Run Steps

### 1. Start Ollama

```powershell
ollama serve
```

### 2. Start Backend

```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
python server.py
```

### 3. Start Frontend

```powershell
cd frontend
npm install
npm start
```

### 4. Open The App

- Frontend: `http://localhost:3000`
- Backend health: `http://localhost:8001/api/health`
- API docs: `http://localhost:8001/docs`

## Docker Run Steps

### 1. Prepare Env Files

- create `backend/.env` from `backend/.env.example`
- create `frontend/.env` from `frontend/.env.example`

### 2. Start Ollama On The Host

For the default Docker setup, Ollama is expected to run on your machine, not inside Compose:

```powershell
ollama serve
```

### 3. Build And Run

From the repo root:

```powershell
docker compose build
docker compose up -d
```

This starts:

- frontend on `http://localhost:3000`
- backend on `http://localhost:8001`

### 4. Optional Ollama Container

If you want Ollama inside Docker too:

```powershell
docker compose --profile local-ollama up -d
```

Then set `OLLAMA_BASE_URL=http://ollama:11434` for the backend service before using that mode.

## Supabase Setup

Run the SQL in:

- `backend/sql/supabase_schema.sql`

Also create a storage bucket named:

- `documents`

Enable:

- Email auth
- Google auth if needed

Set redirect URLs for your frontend domain and local development.

## Knowledge Base Seeding

The project includes a curated local KRMU dataset and a seeding pipeline.

Relevant files:

- `backend/knowledge_seeder.py`
- `backend/datasets/krmu_official_knowledge.json`

Admin endpoints:

- `POST /api/admin/seed-knowledge-base`
- `GET /api/admin/seed-status`
- `DELETE /api/admin/clear-seeds`

Recommended seeding flow:

1. Clear old seed documents if you want a fresh seed run.
2. Run the seed endpoint.
3. Confirm indexed documents through seed status and documents listing.

## Main API Areas

### Authentication

- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/auth/me`

### Chat

- `POST /api/chat`
- `POST /api/chat/stream`
- `GET /api/chat/sessions`
- `GET /api/chat/sessions/{session_id}`

### Documents

- `GET /api/documents`
- `POST /api/documents/upload`
- `POST /api/documents/url`
- `DELETE /api/documents/{document_id}`

### Analytics

- `GET /api/analytics/overview`
- `GET /api/analytics/daily`

### Admin

- `GET /api/admin/users`

## Hosted Deployment Notes

Recommended hosted split:

- Frontend: Vercel
- Backend: Render
- Auth/DB/Storage/Vectors: Supabase
- LLM: Ollama on a reachable machine

If Ollama runs on your local device, the hosted backend must reach it through a public tunnel such as ngrok or through a public server/domain. That setup is fine for demos, but it is not stable production infrastructure.
- `PATCH /api/admin/users/{user_id}/role`
- `POST /api/admin/seed-knowledge-base`
- `GET /api/admin/seed-status`
- `DELETE /api/admin/clear-seeds`
- `POST /api/admin/refresh-models`

## Local Hosting Notes

Because this project is currently hosted locally:

- Ollama speed depends entirely on the local machine
- the backend should stay on `8001`
- MongoDB must stay running locally
- Clerk keys must be configured locally in both frontend and backend env files
- for a smoother demo, use a smaller Ollama model if `llama3` is too slow

## Recommended Immediate Improvements

- switch local chat model from `llama3` to a faster local model for demos
- rebuild Chroma after confirming the final embedding model
- keep only curated seed data plus verified uploads in the production knowledge base
- attach this workspace to the correct GitHub repository before release work

## Known Deployment Direction

The expected release path is:

1. make the local project stable
2. update the GitHub repository with the latest code
3. hand over a clean repo plus environment checklist
4. move the app to the Projexa platform later

## Important Repository Note

This workspace currently has project files but no `.git` directory. That means the code is ready to be committed, but GitHub update work still requires one of these:

- reconnect this folder to the old GitHub repository
- clone the old repository and copy these changes into it
- initialize a fresh repo here and push to the intended remote
