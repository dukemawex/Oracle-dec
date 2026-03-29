# OracleDeck

OracleDeck is a production-ready forecasting system made of four integrated parts:

- **Forecasting Bot (Python 3.11)**: scheduled GitHub Actions runner targeting `spring-aib-2026` and `mini-bench`, using Exa research + OpenRouter (`google/gemini-flash-1.5-8b`, `openai/gpt-5.4`, `mistralai/mistral-7b-instruct`), then syncing full batch logs to backend.
- **Backend API (TypeScript/Express/Prisma/Postgres)**: authenticated ingest, analytics endpoints (calibration, Brier, extremization), and Metaculus resolution sync.
- **Frontend Dashboard (Next.js 14 + Tailwind + SWR + Recharts)**: ISR (`revalidate=30`) + SWR polling (`30s`) + backend-triggered Vercel deploy hook for near-real-time updates. Frontend reads backend URL from `NEXT_PUBLIC_BACKEND_URL`.
- **Shared Package (TypeScript + Zod)**: canonical ingest schemas/types reused by backend for validation consistency.

## Repository Layout

- `bot/`
- `backend/`
- `frontend/`
- `shared/`

## Shared Auth Secret

`METACULUS_TOKEN` is used for:
- Metaculus API authentication
- bot-to-backend ingest authentication (Bearer)
- backend verification of ingest requests

## Quick Start

### Bot
```bash
cd /home/runner/work/Oracle-dec/Oracle-dec/bot
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m oracledeck_bot.main
```

### Backend
```bash
cd /home/runner/work/Oracle-dec/Oracle-dec/backend
npm install
npm run prisma:generate
npm run build
npm run dev
```

### Frontend
```bash
cd /home/runner/work/Oracle-dec/Oracle-dec/frontend
npm install
# configure NEXT_PUBLIC_BACKEND_URL via .env.local (see .env.example)
npm run build
npm run dev
```
