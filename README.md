# SET Academic Chatbot

A K.R. Mangalam University academic assistant with:

- React frontend
- FastAPI backend
- Supabase Auth, Postgres, Storage, and `pgvector`
- remote OpenAI-compatible chat support
- Ollama fallback for local chat and embeddings
- a curated KRMU-only knowledge base

The app supports local development, Docker-based local setup, and split deployment such as:

- Vercel for frontend
- Render for backend
- Supabase for auth, database, storage, and vectors

## What It Does

- student, faculty, and admin login flows
- Supabase email/password and Google sign-in
- database-grounded chat from indexed KRMU documents
- internet mode using DuckDuckGo, restricted to official KRMU sites
- PDF, DOCX, TXT, CSV, PPTX, and URL ingestion
- curated KRMU dataset seeding
- admin analytics, user management, and knowledge-base controls
- chunk preview, retrieval inspection, inline citations, and confidence labels

## Current Highlights

- database mode is tuned for grounded KRMU answers
- internet mode keeps results limited to official `*.krmangalam.edu.in` pages
- Vercel uses `/api/*` rewrites to proxy backend requests to Render
- bulk document delete is available for admins
- the chat layout keeps the sidebar and shell fixed while only the message area scrolls
- the seed dataset now includes more KRMU facility-specific records for hostels, library, campus facilities, research support, transport, placements, and student life

## Tech Stack

- Frontend: React 19, CRACO, Tailwind CSS, Radix UI, Framer Motion
- Backend: FastAPI, Pydantic, httpx
- Auth: Supabase Auth
- Database: Supabase Postgres
- Vector Store: Supabase `pgvector`
- File Storage: Supabase Storage
- Chat Providers:
  - remote OpenAI-compatible provider via `LLM_BASE_URL`
  - Ollama fallback
- Embeddings:
  - Ollama by default
  - optional remote OpenAI-compatible embeddings via `EMBEDDING_*`

## Repository Structure

```text
.
|-- backend/
|   |-- auth.py
|   |-- document_processor.py
|   |-- knowledge_seeder.py
|   |-- rag_engine.py
|   |-- server.py
|   |-- sql/
|   |   `-- supabase_schema.sql
|   `-- datasets/
|       `-- krmu_official_knowledge.json
|-- frontend/
|   |-- src/
|   |-- public/
|   |-- package.json
|   `-- vercel.json
|-- docker-compose.yml
`-- README.md
```

## Main Features

### 1. Authentication

- email/password login through Supabase
- Google login through Supabase OAuth
- role-based access for `student`, `faculty`, and `admin`

### 2. Chat Modes

- `Database`
  - uses indexed KRMU documents and seeded knowledge
  - adds citations and confidence labels
  - prefers grounded, structured answers
- `Internet`
  - uses DuckDuckGo-backed search
  - filters results to official KRMU domains only
  - answers only from returned KRMU snippets

### 3. Knowledge Base

- upload documents and URLs
- seed curated KRMU knowledge from `backend/datasets/krmu_official_knowledge.json`
- preview stored chunks per document
- inspect retrieval results from the admin side
- duplicate upload guards
- bulk document delete for admins

## Supported Documents

- `.pdf`
- `.docx`
- `.txt`
- `.csv`
- `.pptx`
- URL scraping

`DOCX` is the reliable Word format. Older `.doc` files are less reliable than `.docx`.

## Environment Setup

## Backend

Copy `backend/.env.example` to `backend/.env`:

```env
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_ANON_KEY=your_supabase_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key
SUPABASE_STORAGE_BUCKET=documents

JWT_SECRET_KEY=replace-with-a-strong-secret
CORS_ORIGINS=http://localhost:3000,https://your-frontend-url.com

OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_CHAT_MODEL=llama3
OLLAMA_EMBEDDING_MODEL=nomic-embed-text

LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=your_remote_llm_api_key
LLM_MODEL=llama-3.1-70b-versatile
LLM_REQUEST_TIMEOUT=60
LLM_MAX_TOKENS=384

EMBEDDING_BASE_URL=
EMBEDDING_API_KEY=
EMBEDDING_MODEL=

ENABLE_WEB_FALLBACK=false
```

Notes:

- `LLM_*` is for the remote chat model
- `EMBEDDING_*` is optional and only needed if you want remote embeddings
- if `EMBEDDING_*` is not configured, the app falls back to Ollama embeddings and then hash-based safeguards when necessary

## Frontend

Copy `frontend/.env.example` to `frontend/.env`:

```env
REACT_APP_BACKEND_URL=http://localhost:8001
REACT_APP_SUPABASE_URL=https://your-project-ref.supabase.co
REACT_APP_SUPABASE_ANON_KEY=your_supabase_anon_key
REACT_APP_SUPABASE_PROJECT_REF=your-project-ref
```

For hosted frontend builds, the app uses same-origin `/api` requests and Vercel rewrites in [`frontend/vercel.json`](/c:/Users/HP/Desktop/CHATBOT-PROJEXA-walter/frontend/vercel.json), so `REACT_APP_BACKEND_URL` is mainly for local development.

## Local Development

### 1. Start Ollama

```powershell
ollama serve
```

Recommended local pulls:

```powershell
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

### 2. Start the backend

```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
python server.py
```

### 3. Start the frontend

```powershell
cd frontend
npm install
npm start
```

### 4. Open the app

- frontend: `http://localhost:3000`
- backend health: `http://localhost:8001/api/health`
- API docs: `http://localhost:8001/docs`

## Docker Setup

### 1. Prepare env files

- create `backend/.env`
- create `frontend/.env`

### 2. Start Ollama on the host

```powershell
ollama serve
```

### 3. Build and run

```powershell
docker compose build
docker compose up -d
```

Default local endpoints:

- frontend: `http://localhost:3000`
- backend: `http://localhost:8001`

### 4. Optional Ollama in Docker

```powershell
docker compose --profile local-ollama up -d
```

If you use that profile, point the backend at:

```env
OLLAMA_BASE_URL=http://ollama:11434
```

## Supabase Setup

Run:

- [`backend/sql/supabase_schema.sql`](/c:/Users/HP/Desktop/CHATBOT-PROJEXA-walter/backend/sql/supabase_schema.sql)

Also:

- create a storage bucket named `documents`
- enable Email auth
- enable Google auth if needed
- set Supabase `Site URL` and redirect URLs for your frontend domain

## Knowledge Base Seeding

Relevant files:

- [`backend/knowledge_seeder.py`](/c:/Users/HP/Desktop/CHATBOT-PROJEXA-walter/backend/knowledge_seeder.py)
- [`backend/datasets/krmu_official_knowledge.json`](/c:/Users/HP/Desktop/CHATBOT-PROJEXA-walter/backend/datasets/krmu_official_knowledge.json)

Admin endpoints:

- `POST /api/admin/seed-knowledge-base`
- `GET /api/admin/seed-status`
- `DELETE /api/admin/clear-seeds`

Recommended flow:

1. Clear old seed documents if you want a fresh seed run.
2. Seed the knowledge base.
3. Confirm indexed documents from seed status and the documents page.
4. Re-seed after major dataset updates.

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
- `GET /api/documents/{document_id}/chunks`
- `DELETE /api/documents/{document_id}`
- `POST /api/documents/bulk-delete`

### Analytics

- `GET /api/analytics/overview`
- `GET /api/analytics/daily`

### Admin

- `GET /api/admin/users`
- `PATCH /api/admin/users/{user_id}/role`
- `POST /api/admin/seed-knowledge-base`
- `GET /api/admin/seed-status`
- `DELETE /api/admin/clear-seeds`
- `POST /api/admin/refresh-models`
- `POST /api/admin/retrieval-evaluate`

## Hosted Deployment Notes

Recommended split deployment:

- frontend: Vercel
- backend: Render
- auth/db/storage/vectors: Supabase

### Frontend deployment

The hosted frontend is designed to use same-origin API calls:

- local development uses `REACT_APP_BACKEND_URL`
- hosted deployment uses `/api`
- Vercel rewrites `/api/*` to the Render backend

Current rewrite config:

- [`frontend/vercel.json`](/c:/Users/HP/Desktop/CHATBOT-PROJEXA-walter/frontend/vercel.json)

### Backend deployment

Make sure Render has:

- valid Supabase keys
- correct `CORS_ORIGINS`
- remote LLM env vars if using hosted chat

### Health checks

Use:

- `GET /api/health`

It reports key status like:

- database connectivity
- indexed chunk count
- vector backend
- embedding provider/model
- active chat provider/model

## Recent Improvements Reflected In This Repo

- KRMU-only curated dataset expanded for better facility-level answers
- database retrieval improved with lexical fallback and better grounding logic
- database answers formatted more cleanly and conservatively
- internet mode added with DuckDuckGo-backed answers
- internet results restricted to official KRMU domains
- chunk preview and retrieval inspection tools added for admins
- confidence labels and inline citations added in chat
- duplicate upload prevention added
- bulk document deletion added
- chat shell and sidebar layout cleaned up for long conversations
- Vercel proxy setup added for simpler hosted frontend API calls

## Suggested Usage

- use `Database` mode for campus, admission, hostel, fee, placement, and policy questions
- use `Internet` mode when you want a live answer from official KRMU webpages
- keep the seeded knowledge base refreshed when the curated dataset changes
- prefer verified uploads and official KRMU content for the best grounded answers
