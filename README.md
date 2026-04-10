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
- official KRMU happenings/news event summaries with image cards
- chat-to-PDF export with view, edit, and download actions
- PDF, DOCX, TXT, CSV, PPTX, and URL ingestion
- curated KRMU dataset seeding
- reviewed official-KRMU webpage manifest seeding
- admin analytics, user management, and knowledge-base controls
- chunk preview, retrieval inspection, and source-backed answers

## Current Highlights

- database mode is tuned for grounded KRMU answers
- official KRMU happenings/news pages can be used for current event summaries and images
- chat can export recent messages and event summaries as PDFs
- Vercel uses `/api/*` rewrites to proxy backend requests to Render
- bulk document delete is available for admins
- the chat layout keeps the sidebar and shell fixed while only the message area scrolls
- the seed dataset now includes more KRMU facility-specific records for hostels, library, campus facilities, research support, transport, placements, and student life
- admins can append a reviewed batch of official KRMU webpages into the indexed archive
- answer formatting is cleaner and production-style, with sources shown at the end of each reply
- an optional large-PDF indexing pipeline is available for heavy documents without making the main Render deploy depend on the full ML stack

## Tech Stack

- Frontend: React 19, CRACO, Tailwind CSS, Radix UI, Framer Motion
- Backend: FastAPI, Pydantic, httpx
- Auth: Supabase Auth
- Database: Supabase Postgres
- Vector Store: Supabase `pgvector`
- File Storage: Supabase Storage
- Chat Providers:
  - remote OpenAI-compatible provider via `LLM_BASE_URL`
  - optional Gemini chat switch via `GEMINI_API_KEY` and `GEMINI_CHAT_MODEL`
  - Ollama fallback
- Multimodal/Event Enrichment:
  - optional Gemini via `GEMINI_API_KEY`
  - official KRMU happenings/news scraping via `requests` + `BeautifulSoup`
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
|       |-- krmu_official_knowledge.json
|       `-- krmu_official_url_manifest.json
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
  - keeps answers grounded in retrieved chunks only
  - shows sources at the end of the response
  - prefers clean, production-style answers instead of template headings

### 3. Event & Media Enrichment

- official KRMU happenings/news scraping from:
  - `https://www.krmangalam.edu.in/happenings/news-and-events`
- event-related questions can return:
  - grounded event summaries
  - official event images
  - source links to the official KRMU page
- optional Gemini enrichment can make event summaries cleaner and more visual-aware when configured

### 4. Chat Exports

- natural-language PDF export from chat
- supported prompts include:
  - `convert this message to pdf`
  - `convert my last message to pdf`
  - `export this answer as pdf`
  - `export this event summary as pdf`
- exported PDFs can be:
  - viewed
  - edited and regenerated
  - downloaded

### 5. Knowledge Base

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

Large PDFs:

- standard uploads continue to use the main document pipeline
- very large PDFs can use the optional high-capacity indexing path in [`backend/large_pdf_rag.py`](/c:/Users/HP/Desktop/CHATBOT-PROJEXA-walter/backend/large_pdf_rag.py)
- that advanced path is intentionally optional so the main Render web service can deploy reliably

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

# Optional OpenAI chat-provider switch
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
OPENAI_BASE_URL=https://api.openai.com/v1

# Optional Gemini chat switch + official KRMU events/news enrichment
GEMINI_API_KEY=
GEMINI_CHAT_MODEL=gemini-1.5-flash
GEMINI_MODEL=gemini-2.5-flash

EMBEDDING_BASE_URL=
EMBEDDING_API_KEY=
EMBEDDING_MODEL=

ENABLE_WEB_FALLBACK=false

KRMU_SEED_LIVE_URLS=true
KRMU_SEED_URL_LIMIT=40
KRMU_SEED_URL_DELAY_SECONDS=0.2
```

Notes:

- `LLM_*` is for the default Groq/OpenAI-compatible remote chat model
- `OPENAI_*` is optional and powers the OpenAI option in the chat model switcher
- `GEMINI_*` is optional and powers Gemini chat plus official KRMU happenings/news enrichment
- `EMBEDDING_*` is optional and only needed if you want remote embeddings
- `KRMU_SEED_*` controls the reviewed official-KRMU webpage seeding pass
- if `EMBEDDING_*` is not configured, the app falls back to Ollama embeddings and then hash-based safeguards when necessary
- the advanced large-PDF hybrid pipeline is kept optional and is not required for the normal Render deployment

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
- [`backend/datasets/krmu_official_url_manifest.json`](/c:/Users/HP/Desktop/CHATBOT-PROJEXA-walter/backend/datasets/krmu_official_url_manifest.json)

Admin endpoints:

- `POST /api/admin/seed-knowledge-base`
- `POST /api/admin/seed-official-urls`
- `GET /api/admin/seed-status`
- `DELETE /api/admin/clear-seeds`

Recommended flow:

1. Clear old seed documents if you want a fresh seed run.
2. Seed the knowledge base.
3. Confirm indexed documents from seed status and the documents page.
4. Re-seed after major dataset updates.
5. Click `Add Official KRMU Pages` in Knowledge Base Settings to append the reviewed live webpage manifest without deleting uploaded files.

## Main API Areas

### Authentication

- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/auth/me`

### Chat

- `POST /api/chat`
- `POST /api/chat/stream`
- `POST /api/chat/export-pdf`
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
- `POST /api/admin/seed-official-urls`
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
- optional `OPENAI_API_KEY` and `OPENAI_MODEL` if you want the OpenAI chat-provider option
- optional `GEMINI_API_KEY` and `GEMINI_MODEL` if you want enriched KRMU event summaries/images
- the default web service does not need the full optional large-PDF ML dependency stack to start successfully

### Health checks

Use:

- `GET /api/health`

It reports key status like:

- database connectivity
- indexed chunk count
- vector backend
- embedding provider/model
- active chat provider/model
- Gemini event enrichment status

## Recent Improvements Reflected In This Repo

- KRMU-only curated dataset expanded for better facility-level answers
- database retrieval improved with lexical fallback and better grounding logic
- multi-turn retrieval rewrites follow-up questions with the active conversation topic
- database answers formatted more cleanly and conservatively
- chat answers can be switched between Auto, Groq, Gemini, and OpenAI from the chat toolbar
- raw dataset tags/internal metadata are stripped from generated chat answers
- PDF, DOCX, and PPTX table rows are preserved as labeled facts during indexing
- PDF ingestion now preserves page text, table rows, OCR recovery, image text, and Gemini image descriptions when available
- official KRMU happenings/news scraping added for event summaries and images
- optional Gemini enrichment added for event/news responses
- chunk preview and retrieval inspection tools added for admins
- reviewed official KRMU URL manifest plus admin indexing action added for broader archive coverage
- answer presentation cleaned up so sources appear at the end of the reply
- duplicate upload prevention added
- bulk document deletion added
- chat shell and sidebar layout cleaned up for long conversations
- Vercel proxy setup added for simpler hosted frontend API calls
- chat PDF export workflow added with view/edit/download controls
- optional large-PDF hybrid RAG module added and integrated as a guarded backend path

## Suggested Usage

- use `Database` mode for campus, admission, hostel, fee, placement, and policy questions
- ask about `current events`, `latest happenings`, or `tell me about this event` to use the official KRMU happenings/news flow
- after a useful answer, say `convert this message to pdf` or `export this event summary as pdf` to create a downloadable PDF
- keep the seeded knowledge base refreshed when the curated dataset changes
- prefer verified uploads and official KRMU content for the best grounded answers
