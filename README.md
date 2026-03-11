# Ledger — Credit Card Expense Dashboard

Full-stack app: Gmail → Gemini parsing → Supabase → React dashboard, deployed on Vercel.

## Stack
- **Frontend**: React + Recharts (Vercel static)
- **Backend**: Python serverless functions (`/api/*.py`) on Vercel
- **Database**: Supabase (Postgres + Auth + Realtime)
- **Parsing**: Google Gemini API (email → structured transaction)
- **Gmail**: Google OAuth2 + Gmail API

---

## 1. Prerequisites

- Node.js 18+
- Python 3.9+
- A [Supabase](https://supabase.com) project
- A [Google Cloud](https://console.cloud.google.com) project with Gmail API enabled
- A [Google AI Studio](https://aistudio.google.com) API key for Gemini
- A [Vercel](https://vercel.com) account

---

## 2. Supabase Setup

Run this SQL in your Supabase SQL editor:

```sql
-- Transactions table
create table transactions (
  id uuid default gen_random_uuid() primary key,
  user_id text not null,
  gmail_message_id text unique not null,
  merchant text,
  amount numeric(10,2),
  currency text default 'USD',
  date date,
  category text,
  cashback_rate numeric(4,2),
  cashback_earned numeric(8,2),
  raw_subject text,
  raw_snippet text,
  created_at timestamptz default now()
);

-- Sync log
create table sync_log (
  id uuid default gen_random_uuid() primary key,
  user_id text not null,
  synced_at timestamptz default now(),
  emails_processed int default 0,
  transactions_added int default 0,
  status text default 'success',
  error text
);

-- Cashback rules (editable per user)
create table cashback_rules (
  id uuid default gen_random_uuid() primary key,
  user_id text not null,
  category text not null,
  rate numeric(4,2) not null default 1.0,
  card_name text,
  created_at timestamptz default now()
);

-- Row Level Security
alter table transactions enable row level security;
alter table sync_log enable row level security;
alter table cashback_rules enable row level security;

create policy "Users see own transactions" on transactions for all using (user_id = auth.uid()::text);
create policy "Users see own sync_log"    on sync_log    for all using (user_id = auth.uid()::text);
create policy "Users see own rules"       on cashback_rules for all using (user_id = auth.uid()::text);
```

---

## 3. Google Cloud Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project → Enable **Gmail API**
3. OAuth consent screen → External → add scope: `gmail.readonly`
4. Credentials → OAuth 2.0 Client ID → Web Application
   - Authorized redirect URIs: `https://your-app.vercel.app/api/auth/callback`
5. Download client secret JSON → extract `client_id` and `client_secret`

---

## 4. Environment Variables

Create `.env.local` for local dev, and add all to Vercel dashboard:

```env
# Supabase
NEXT_PUBLIC_SUPABASE_URL=https://xxxx.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key

# Google OAuth
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
GOOGLE_REDIRECT_URI=https://your-app.vercel.app/api/auth/callback

# Google Gemini
GEMINI_API_KEY=your-gemini-api-key

# App
NEXTAUTH_SECRET=random-secret-string-32chars
APP_URL=https://your-app.vercel.app
```

---

## 5. Local Development

```bash
npm install
pip install -r requirements.txt
npm run dev        # starts Vercel dev server (handles /api/* Python functions)
```

---

## 6. Deploy to Vercel

```bash
npm install -g vercel
vercel login
vercel --prod
```

Add all environment variables in Vercel dashboard → Settings → Environment Variables.

---

## Architecture

```
User Browser
  │
  ├─ React App (Vercel CDN)
  │    └─ @supabase/supabase-js  ──► Supabase DB (realtime)
  │
  └─ API calls
       ├─ GET  /api/auth/login     → Google OAuth redirect
       ├─ GET  /api/auth/callback  → Exchange code, store tokens
       ├─ POST /api/sync           → Fetch Gmail → Gemini → Supabase
       ├─ GET  /api/transactions   → Query Supabase
       └─ GET  /api/insights       → Aggregate analytics
```
