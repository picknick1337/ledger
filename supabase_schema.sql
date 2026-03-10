-- ============================================================
-- Ledger — Supabase Schema
-- Run this in your Supabase SQL Editor (supabase.com/dashboard)
-- ============================================================

-- Transactions (one row per parsed email)
create table if not exists transactions (
  id                uuid        default gen_random_uuid() primary key,
  user_id           text        not null,
  gmail_message_id  text        unique not null,
  merchant          text,
  amount            numeric(10,2),
  currency          text        default 'USD',
  date              date,
  category          text,
  cashback_rate     numeric(4,2),
  cashback_earned   numeric(8,2),
  raw_subject       text,
  raw_snippet       text,
  created_at        timestamptz default now()
);

-- Sync history
create table if not exists sync_log (
  id                   uuid        default gen_random_uuid() primary key,
  user_id              text        not null,
  synced_at            timestamptz default now(),
  emails_processed     int         default 0,
  transactions_added   int         default 0,
  status               text        default 'success',
  error                text
);

-- Stored Google OAuth tokens (service role only)
create table if not exists user_tokens (
  user_id        text        primary key,
  access_token   text        not null,
  refresh_token  text,
  expires_at     int,
  scope          text,
  updated_at     timestamptz default now()
);

-- Per-user cashback rate overrides
create table if not exists cashback_rules (
  id          uuid    default gen_random_uuid() primary key,
  user_id     text    not null,
  category    text    not null,
  rate        numeric(4,2) not null default 1.0,
  card_name   text,
  created_at  timestamptz default now(),
  unique (user_id, category)
);

-- ── Row Level Security ─────────────────────────────────────────────────────

alter table transactions    enable row level security;
alter table sync_log        enable row level security;
alter table cashback_rules  enable row level security;
-- user_tokens accessed only via service role key (no RLS needed)

create policy "user_transactions"   on transactions    for all using (user_id = auth.uid()::text);
create policy "user_sync_log"       on sync_log        for all using (user_id = auth.uid()::text);
alter table sync_log enable row level security;
create policy "user_cashback_rules" on cashback_rules  for all using (user_id = auth.uid()::text);

-- ── Indexes ────────────────────────────────────────────────────────────────

create index if not exists idx_transactions_user_date on transactions (user_id, date desc);
create index if not exists idx_transactions_category  on transactions (user_id, category);
create index if not exists idx_sync_log_user          on sync_log (user_id, synced_at desc);

-- ── Enable Realtime ────────────────────────────────────────────────────────
-- Allows the frontend to receive new transactions live during sync

alter publication supabase_realtime add table transactions;
