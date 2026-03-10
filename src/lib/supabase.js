// src/lib/supabase.js
// Supabase client + shared data hooks used across the dashboard

import { createClient } from "@supabase/supabase-js";

export const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY
);

// ── Auth helpers ───────────────────────────────────────────────────────────

export async function signInWithEmail(email, password) {
  return supabase.auth.signInWithPassword({ email, password });
}

export async function signUpWithEmail(email, password) {
  return supabase.auth.signUp({ email, password });
}

export async function signOut() {
  return supabase.auth.signOut();
}

export async function getSession() {
  const { data } = await supabase.auth.getSession();
  return data.session;
}

// ── Gmail connection ───────────────────────────────────────────────────────

export function getGmailAuthUrl(userId) {
  return `/api/auth/login?user_id=${userId}`;
}

export async function triggerSync(userId) {
  const res = await fetch("/api/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.error || "Sync failed");
  }
  return res.json();
}

// ── Data fetching ──────────────────────────────────────────────────────────

export async function fetchInsights(userId, months = 6) {
  const res = await fetch(`/api/insights?user_id=${userId}&months=${months}`);
  if (!res.ok) throw new Error("Failed to load insights");
  return res.json();
}

export async function fetchTransactions(userId, { limit = 50, offset = 0, category, month } = {}) {
  const params = new URLSearchParams({ user_id: userId, limit, offset });
  if (category) params.append("category", category);
  if (month) params.append("month", month);
  const res = await fetch(`/api/transactions?${params}`);
  if (!res.ok) throw new Error("Failed to load transactions");
  return res.json();
}

// ── Realtime subscription ──────────────────────────────────────────────────
// Subscribe to new transactions as they are inserted during sync

export function subscribeToTransactions(userId, onInsert) {
  return supabase
    .channel(`transactions:${userId}`)
    .on(
      "postgres_changes",
      {
        event: "INSERT",
        schema: "public",
        table: "transactions",
        filter: `user_id=eq.${userId}`,
      },
      (payload) => onInsert(payload.new)
    )
    .subscribe();
}
