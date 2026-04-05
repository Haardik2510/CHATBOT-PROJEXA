# SET Academic Chatbot - Setup Guide

## Prerequisites

Before running the application, ensure you have the following installed:

### 1. Python 3.10+ (Backend)
- Download from https://www.python.org/downloads/

### 2. Node.js 18+ (Frontend)
- Download from https://nodejs.org/

### 3. MongoDB
- Download MongoDB Community Server from https://www.mongodb.com/try/download/community
- Or use MongoDB Atlas (cloud) and update `MONGO_URL` in `.env`

### 4. Ollama (for AI responses)
- Download from https://ollama.com/
- After installation, pull the required models:

```bash
ollama pull llama3
ollama pull nomic-embed-text
```

### 5. Clerk Account (for Authentication)
- Sign up at https://clerk.com/
- Create a new application
- Copy your API keys to the `.env` files

---

## Quick Start

### Step 1: Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the server
python server.py
# Or use the batch file (Windows):
# start.bat
```

The backend will start on `http://localhost:8001`

### Step 2: Frontend Setup

```bash
cd frontend

# Install dependencies
npm install
# or
yarn install

# Start the development server
npm start
```

The frontend will start on `http://localhost:3000`

---

## Environment Configuration

### Backend (.env)

```env
MONGO_URL=mongodb://localhost:27017
DB_NAME=chatbot_db
CLERK_SECRET_KEY=sk_test_your_clerk_secret_key
CLERK_PUBLISHABLE_KEY=pk_test_your_clerk_publishable_key
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_CHAT_MODEL=llama3
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
CORS_ORIGINS=http://localhost:3000,http://localhost:8001
JWT_SECRET_KEY=your-secret-key-change-in-production
```

### Frontend (.env)

```env
REACT_APP_BACKEND_URL=http://localhost:8001
REACT_APP_CLERK_PUBLISHABLE_KEY=pk_test_your_clerk_publishable_key
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_your_clerk_publishable_key
```

---

## Clerk Configuration

### Required Settings in Clerk Dashboard

1. **Email Addresses**: Enable email/password authentication
2. **OAuth Providers**: Enable Google OAuth (optional)
3. **Redirect URLs**: Add these URLs:
   - `http://localhost:3000/auth/callback`
   - `http://localhost:3000/chat`

### Setting Up User Roles

The application uses role-based access control (RBAC) with three roles:
- `student` (default)
- `faculty` (teacher access)
- `admin` (full access)

Roles are managed through the admin dashboard or database.

---

## Ollama Configuration

### Starting Ollama Server

```bash
# Start Ollama server (if not running as a service)
ollama serve
```

### Verify Models are Installed

```bash
ollama list
```

You should see:
- `llama3` (or `mistral`)
- `nomic-embed-text`

### Test Ollama Connection

```bash
curl http://localhost:11434/api/tags
```

---

## Testing the Application

### 1. Health Check

```bash
curl http://localhost:8001/api/health
```

### 2. Register a User

```bash
curl -X POST http://localhost:8001/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@krmu.edu.in","password":"Test123!","name":"Test User","role":"student"}'
```

### 3. Access the Web Interface

Open http://localhost:3000 in your browser

---

## Troubleshooting

### Backend won't start

- Check if MongoDB is running
- Verify `.env` file exists with correct values
- Ensure port 8001 is not in use

### Frontend won't start

- Run `npm install` again
- Clear `node_modules` and reinstall: `rm -rf node_modules && npm install`
- Check if port 3000 is available

### Clerk authentication fails

- Verify keys in both `.env` files match your Clerk dashboard
- Check redirect URLs in Clerk dashboard
- Ensure Clerk domain is correctly decoded from publishable key

### Ollama not available

- Check if Ollama service is running: `ollama serve`
- Verify models are pulled: `ollama list`
- The app will use fallback mode (hash-based embeddings) if Ollama is unavailable

### CORS errors

- Ensure `CORS_ORIGINS` in backend `.env` includes your frontend URL
- Restart the backend after changing CORS settings

---

## API Endpoints

### Authentication
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login
- `POST /api/auth/clerk-exchange` - Exchange Clerk token for app JWT
- `GET /api/auth/me` - Get current user

### Chat
- `POST /api/chat` - Send chat message
- `GET /api/chat/sessions` - Get chat sessions
- `GET /api/chat/sessions/:id` - Get specific session

### Documents (Faculty/Admin)
- `GET /api/documents` - List documents
- `POST /api/documents/upload` - Upload document
- `POST /api/documents/url` - Scrape URL
- `DELETE /api/documents/:id` - Delete document

### Analytics (Faculty/Admin)
- `GET /api/analytics/overview` - Analytics overview
- `GET /api/analytics/daily` - Daily stats

### Admin
- `GET /api/admin/users` - List all users
- `PATCH /api/admin/users/:id/role` - Update user role
- `POST /api/admin/seed` - Seed knowledge base
- `GET /api/admin/seed-status` - Get seed status
- `DELETE /api/admin/clear-seeds` - Clear seeds
- `POST /api/admin/refresh-ollama` - Refresh Ollama connection

---

## Architecture Overview

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Frontend  │────▶│   Backend   │────▶│   MongoDB   │
│  (React 19) │◀────│  (FastAPI)  │◀────│  (Database) │
└─────────────┘     └─────────────┘     └─────────────┘
       │                   │                   │
       ▼                   ▼                   │
┌─────────────┐     ┌─────────────┐            │
│    Clerk    │     │   Ollama    │◀───────────┘
│   (Auth)    │     │  (LLM/RAG)  │
└─────────────┘     └─────────────┘
```

### Tech Stack

- **Frontend**: React 19, Tailwind CSS, Shadcn UI, Framer Motion, Clerk
- **Backend**: FastAPI, Motor (async MongoDB), PyJWT
- **Database**: MongoDB
- **Vector Store**: ChromaDB
- **AI/ML**: Ollama (Llama3/Mistral), nomic-embed-text
- **Auth**: Clerk + JWT

---

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review logs in the backend terminal
3. Check browser console for frontend errors
