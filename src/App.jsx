// src/App.jsx
// Ledger — full dashboard wired to real Supabase + API data

import { useState, useEffect, useCallback } from "react";
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer, LineChart, Line,
} from "recharts";
import {
  supabase,
  signInWithEmail, signUpWithEmail, signOut,
  getGmailAuthUrl, triggerSync,
  fetchInsights, fetchTransactions,
  subscribeToTransactions,
} from "./lib/supabase";

const FONTS = `@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@300;400;500&family=Instrument+Sans:wght@400;500;600&display=swap');`;

const CAT_COLORS = {
  "Food & Dining":  "#F59E0B",
  "Travel":         "#10B981",
  "Shopping":       "#6366F1",
  "Utilities":      "#EC4899",
  "Entertainment":  "#8B5CF6",
  "Health":         "#14B8A6",
  "Subscriptions":  "#F97316",
  "Other":          "#64748B",
};

// ── Shared UI ──────────────────────────────────────────────────────────────

const Tooltip_ = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background:"#0F1117", border:"1px solid #2A2D3A", borderRadius:8, padding:"10px 14px" }}>
      <p style={{ color:"#F59E0B", fontFamily:"DM Mono", fontSize:11, marginBottom:6 }}>{label}</p>
      {payload.map((p, i) => (
        <p key={i} style={{ color:p.color, fontFamily:"DM Mono", fontSize:12, margin:"2px 0" }}>
          {p.name}: ₹{Number(p.value).toLocaleString("en-IN")}
        </p>
      ))}
    </div>
  );
};

const KPI = ({ label, value, sub, accent, delay=0 }) => (
  <div style={{ background:"#0F1117", border:"1px solid #1E2130", borderRadius:12,
    padding:"20px 24px", position:"relative", overflow:"hidden",
    animation:`fadeUp 0.5s ease ${delay}s both` }}>
    <div style={{ position:"absolute", top:0, left:0, right:0, height:2,
      background:`linear-gradient(90deg,transparent,${accent},transparent)` }} />
    <p style={{ fontFamily:"Instrument Sans", fontSize:11, color:"#4B5563",
      textTransform:"uppercase", letterSpacing:"0.12em", marginBottom:8 }}>{label}</p>
    <p style={{ fontFamily:"DM Serif Display", fontSize:30, color:"#F8F9FA",
      marginBottom:4, lineHeight:1 }}>{value}</p>
    {sub && <p style={{ fontFamily:"DM Mono", fontSize:11, color:"#6B7280" }}>{sub}</p>}
  </div>
);

const Card = ({ children, style={}, delay=0 }) => (
  <div style={{ background:"#0F1117", border:"1px solid #1E2130", borderRadius:12,
    padding:24, animation:`fadeUp 0.5s ease ${delay}s both`, ...style }}>
    {children}
  </div>
);

const CardTitle = ({ children }) => (
  <p style={{ fontFamily:"Instrument Sans", fontSize:11, fontWeight:600,
    textTransform:"uppercase", letterSpacing:"0.12em", color:"#4B5563", marginBottom:18 }}>
    {children}
  </p>
);

// ── Auth Screen ────────────────────────────────────────────────────────────

function AuthScreen({ onAuth }) {
  const [mode, setMode] = useState("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const submit = async () => {
    setLoading(true); setErr("");
    try {
      const fn = mode === "signin" ? signInWithEmail : signUpWithEmail;
      const { data, error } = await fn(email, password);
      if (error) throw error;
      onAuth(data.session || data.user);
    } catch (e) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight:"100vh", background:"#080B12", display:"flex",
      alignItems:"center", justifyContent:"center", fontFamily:"Instrument Sans, sans-serif" }}>
      <div style={{ width:380, background:"#0F1117", border:"1px solid #1E2130",
        borderRadius:16, padding:40, animation:"fadeUp 0.5s ease both" }}>
        <div style={{ display:"flex", alignItems:"center", gap:10, marginBottom:32 }}>
          <div style={{ width:36, height:36, borderRadius:8,
            background:"linear-gradient(135deg,#F59E0B,#D97706)",
            display:"flex", alignItems:"center", justifyContent:"center", fontSize:18 }}>💳</div>
          <span style={{ fontFamily:"DM Serif Display", fontSize:22, color:"#F8F9FA" }}>Ledger</span>
        </div>

        <p style={{ fontFamily:"DM Mono", fontSize:11, color:"#4B5563",
          textTransform:"uppercase", letterSpacing:"0.1em", marginBottom:20 }}>
          {mode === "signin" ? "Sign in to your account" : "Create an account"}
        </p>

        {[["Email", email, setEmail, "email"], ["Password", password, setPassword, "password"]].map(([label, val, setter, type]) => (
          <div key={label} style={{ marginBottom:14 }}>
            <p style={{ fontFamily:"DM Mono", fontSize:10, color:"#6B7280", marginBottom:6, textTransform:"uppercase", letterSpacing:"0.08em" }}>{label}</p>
            <input type={type} value={val} onChange={e => setter(e.target.value)}
              style={{ width:"100%", background:"#13161F", border:"1px solid #2A2D3A",
                borderRadius:8, padding:"10px 14px", color:"#F8F9FA",
                fontFamily:"DM Mono", fontSize:13, outline:"none" }}
              onKeyDown={e => e.key === "Enter" && submit()} />
          </div>
        ))}

        {err && <p style={{ fontFamily:"DM Mono", fontSize:11, color:"#EF4444", marginBottom:12 }}>{err}</p>}

        <button onClick={submit} disabled={loading}
          style={{ width:"100%", background:"#F59E0B", border:"none", borderRadius:8,
            padding:"12px 0", fontFamily:"Instrument Sans", fontSize:14, fontWeight:600,
            color:"#000", cursor:"pointer", marginBottom:14 }}>
          {loading ? "..." : mode === "signin" ? "Sign In" : "Create Account"}
        </button>

        <p style={{ fontFamily:"DM Mono", fontSize:11, color:"#4B5563", textAlign:"center" }}>
          {mode === "signin" ? "No account? " : "Already have one? "}
          <span style={{ color:"#F59E0B", cursor:"pointer" }}
            onClick={() => setMode(mode === "signin" ? "signup" : "signin")}>
            {mode === "signin" ? "Sign up" : "Sign in"}
          </span>
        </p>
      </div>
    </div>
  );
}

// ── Connect Gmail Banner ───────────────────────────────────────────────────

function ConnectGmail({ userId }) {
  return (
    <div style={{ background:"rgba(245,158,11,0.08)", border:"1px solid rgba(245,158,11,0.3)",
      borderRadius:12, padding:"20px 28px", display:"flex", alignItems:"center",
      justifyContent:"space-between", marginBottom:24, animation:"fadeUp 0.4s ease both" }}>
      <div>
        <p style={{ fontFamily:"Instrument Sans", fontSize:14, fontWeight:600, color:"#F8F9FA", marginBottom:4 }}>
          Connect your Gmail to import transactions
        </p>
        <p style={{ fontFamily:"DM Mono", fontSize:11, color:"#6B7280" }}>
          We scan for credit card notification emails only — read-only access.
        </p>
      </div>
      <a href={getGmailAuthUrl(userId)}
        style={{ background:"#F59E0B", color:"#000", border:"none", borderRadius:8,
          padding:"10px 20px", fontFamily:"Instrument Sans", fontSize:13, fontWeight:600,
          cursor:"pointer", textDecoration:"none", whiteSpace:"nowrap" }}>
        Connect Gmail →
      </a>
    </div>
  );
}

// ── Main Dashboard ─────────────────────────────────────────────────────────

export default function App() {
  const [session, setSession]     = useState(null);
  const [loading, setLoading]     = useState(true);
  const [tab, setTab]             = useState("overview");
  const [insights, setInsights]   = useState(null);
  const [txns, setTxns]           = useState([]);
  const [syncing, setSyncing]     = useState(false);
  const [syncMsg, setSyncMsg]     = useState("");
  const [gmailConnected, setGmailConnected] = useState(false);
  const [dataLoading, setDataLoading] = useState(false);

  // ── Auth listener ──────────────────────────────────────────────────────
  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setLoading(false);
    });
    const { data: listener } = supabase.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => listener.subscription.unsubscribe();
  }, []);

  // ── Check URL params (post-OAuth redirect) ─────────────────────────────
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    if (p.get("gmail_connected") === "true") {
      setGmailConnected(true);
      window.history.replaceState({}, "", "/");
    }
  }, []);

  // ── Load data when session available ──────────────────────────────────
  const loadData = useCallback(async () => {
    if (!session?.user?.id) return;
    setDataLoading(true);
    try {
      const [insData, txData] = await Promise.all([
        fetchInsights(session.user.id, 6),
        fetchTransactions(session.user.id, { limit: 30 }),
      ]);
      setInsights(insData);
      setTxns(txData.transactions || []);
      if ((insData.transaction_count || 0) > 0) setGmailConnected(true);
    } catch (e) {
      console.error(e);
    } finally {
      setDataLoading(false);
    }
  }, [session]);

  useEffect(() => { loadData(); }, [loadData]);

  // ── Realtime: new transactions stream in during sync ───────────────────
  useEffect(() => {
    if (!session?.user?.id) return;
    const channel = subscribeToTransactions(session.user.id, (newTxn) => {
      setTxns(prev => [newTxn, ...prev].slice(0, 30));
    });
    return () => supabase.removeChannel(channel);
  }, [session]);

  // ── Trigger manual sync ────────────────────────────────────────────────
  const handleSync = async () => {
    setSyncing(true); setSyncMsg("");
    try {
      const result = await triggerSync(session.user.id);
      setSyncMsg(`✓ ${result.transactions_added} new transactions added`);
      await loadData();
    } catch (e) {
      setSyncMsg(`✗ ${e.message}`);
    } finally {
      setSyncing(false);
    }
  };

  if (loading) return (
    <div style={{ minHeight:"100vh", background:"#080B12", display:"flex",
      alignItems:"center", justifyContent:"center" }}>
      <span style={{ fontFamily:"DM Mono", fontSize:12, color:"#374151" }}>Loading…</span>
    </div>
  );

  if (!session) return <AuthScreen onAuth={() => {}} />;

  const ins = insights;
  const totalSpend    = ins?.total_spend ?? 0;
  const totalCashback = ins?.total_cashback ?? 0;
  const byCategory    = ins?.by_category ?? [];
  const byMonth       = ins?.by_month ?? [];
  const merchants     = ins?.top_merchants ?? [];
  const opps          = ins?.opportunities ?? [];

  return (
    <>
      <style>{FONTS}</style>
      <style>{`
        * { box-sizing:border-box; margin:0; padding:0; }
        @keyframes fadeUp { from{opacity:0;transform:translateY(16px)} to{opacity:1;transform:translateY(0)} }
        .tab { background:none; border:none; cursor:pointer; font-family:"Instrument Sans",sans-serif;
          font-size:13px; font-weight:500; padding:8px 18px; border-radius:8px; transition:all 0.2s; }
        .tab.on { background:#F59E0B; color:#000; }
        .tab.off { color:#6B7280; }
        .tab.off:hover { background:#1A1D2A; color:#9CA3AF; }
        .txn { display:flex; justify-content:space-between; align-items:center;
          padding:10px 0; border-bottom:1px solid #13161F; }
        .txn:last-child { border-bottom:none; }
        ::-webkit-scrollbar { width:4px } ::-webkit-scrollbar-thumb { background:#2A2D3A; border-radius:4px }
      `}</style>

      <div style={{ minHeight:"100vh", background:"#080B12", fontFamily:"Instrument Sans,sans-serif" }}>

        {/* Header */}
        <div style={{ borderBottom:"1px solid #1A1D2A", padding:"0 32px",
          display:"flex", alignItems:"center", justifyContent:"space-between", height:64 }}>
          <div style={{ display:"flex", alignItems:"center", gap:10 }}>
            <div style={{ width:30, height:30, borderRadius:7,
              background:"linear-gradient(135deg,#F59E0B,#D97706)",
              display:"flex", alignItems:"center", justifyContent:"center", fontSize:15 }}>💳</div>
            <span style={{ fontFamily:"DM Serif Display", fontSize:20, color:"#F8F9FA" }}>Ledger</span>
          </div>

          <div style={{ display:"flex", gap:4 }}>
            {["overview","trends","merchants","optimize"].map(t => (
              <button key={t} className={`tab ${tab===t?"on":"off"}`} onClick={() => setTab(t)}>
                {t[0].toUpperCase()+t.slice(1)}
              </button>
            ))}
          </div>

          <div style={{ display:"flex", alignItems:"center", gap:12 }}>
            {syncMsg && <span style={{ fontFamily:"DM Mono", fontSize:11,
              color: syncMsg.startsWith("✓") ? "#10B981" : "#EF4444" }}>{syncMsg}</span>}
            <button onClick={handleSync} disabled={syncing}
              style={{ background:"#13161F", border:"1px solid #2A2D3A", borderRadius:8,
                padding:"7px 16px", color:"#9CA3AF", fontFamily:"DM Mono", fontSize:11,
                cursor:"pointer" }}>
              {syncing ? "Syncing…" : "↻ Sync Gmail"}
            </button>
            <button onClick={() => signOut()}
              style={{ background:"none", border:"none", color:"#374151",
                fontFamily:"DM Mono", fontSize:11, cursor:"pointer" }}>
              Sign out
            </button>
          </div>
        </div>

        <div style={{ padding:"28px 32px" }}>

          {!gmailConnected && <ConnectGmail userId={session.user.id} />}

          {dataLoading && (
            <div style={{ textAlign:"center", padding:"60px 0" }}>
              <span style={{ fontFamily:"DM Mono", fontSize:12, color:"#374151" }}>Loading your data…</span>
            </div>
          )}

          {!dataLoading && ins && (
            <>
              {/* ── OVERVIEW ── */}
              {tab === "overview" && (
                <>
                  <div style={{ display:"grid", gridTemplateColumns:"repeat(4,1fr)", gap:16, marginBottom:24 }}>
                    <KPI label="Total Spend" value={`₹${totalSpend.toLocaleString("en-IN")}`}
                      sub="Last 6 months" accent="#F59E0B" delay={0.0} />
                    <KPI label="Avg Monthly"
                      value={`₹${Math.round(totalSpend/6).toLocaleString("en-IN")}`}
                      sub={`${ins.transaction_count} transactions`} accent="#6366F1" delay={0.1} />
                    <KPI label="Cashback Earned" value={`₹${totalCashback.toFixed(2)}`}
                      sub="At current rates" accent="#10B981" delay={0.2} />
                    <KPI label="Last Sync"
                      value={ins.recent_sync ? new Date(ins.recent_sync.synced_at).toLocaleDateString() : "—"}
                      sub={ins.recent_sync ? `+${ins.recent_sync.transactions_added} txns` : "Never synced"}
                      accent="#EC4899" delay={0.3} />
                  </div>

                  <div style={{ display:"grid", gridTemplateColumns:"2fr 1fr", gap:16, marginBottom:16 }}>
                    <Card delay={0.1}>
                      <CardTitle>Monthly Spending</CardTitle>
                      <ResponsiveContainer width="100%" height={220}>
                        <AreaChart data={byMonth}>
                          <defs>
                            <linearGradient id="ag" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor="#F59E0B" stopOpacity={0.3}/>
                              <stop offset="95%" stopColor="#F59E0B" stopOpacity={0}/>
                            </linearGradient>
                          </defs>
                          <XAxis dataKey="label" tick={{ fill:"#4B5563", fontSize:11, fontFamily:"DM Mono" }} axisLine={false} tickLine={false}/>
                          <YAxis tick={{ fill:"#4B5563", fontSize:11, fontFamily:"DM Mono" }} axisLine={false} tickLine={false} tickFormatter={v=>`₹${(v/1000).toFixed(1)}k`}/>
                          <Tooltip content={<Tooltip_ />} />
                          <Area type="monotone" dataKey="total" name="Total" stroke="#F59E0B" strokeWidth={2} fill="url(#ag)" dot={{ fill:"#F59E0B", r:3 }}/>
                        </AreaChart>
                      </ResponsiveContainer>
                    </Card>

                    <Card delay={0.2}>
                      <CardTitle>By Category</CardTitle>
                      <ResponsiveContainer width="100%" height={150}>
                        <PieChart>
                          <Pie data={byCategory} cx="50%" cy="50%" innerRadius={38} outerRadius={62}
                            dataKey="total" paddingAngle={2} stroke="none">
                            {byCategory.map((c, i) => (
                              <Cell key={i} fill={CAT_COLORS[c.category] || "#64748B"} />
                            ))}
                          </Pie>
                          <Tooltip formatter={v=>`₹${Number(v).toLocaleString('en-IN')}`}
                            contentStyle={{ background:"#0F1117", border:"1px solid #2A2D3A", borderRadius:8, fontFamily:"DM Mono", fontSize:11 }} />
                        </PieChart>
                      </ResponsiveContainer>
                      <div style={{ display:"flex", flexWrap:"wrap", gap:"5px 10px", marginTop:6 }}>
                        {byCategory.slice(0,6).map((c, i) => (
                          <div key={i} style={{ display:"flex", alignItems:"center", gap:4 }}>
                            <div style={{ width:6, height:6, borderRadius:"50%", background:CAT_COLORS[c.category]||"#64748B" }}/>
                            <span style={{ fontFamily:"DM Mono", fontSize:10, color:"#6B7280" }}>{c.category.split(" ")[0]}</span>
                            <span style={{ fontFamily:"DM Mono", fontSize:10, color:CAT_COLORS[c.category]||"#64748B" }}>{c.pct}%</span>
                          </div>
                        ))}
                      </div>
                    </Card>
                  </div>

                  <Card delay={0.3}>
                    <CardTitle>Recent Transactions</CardTitle>
                    {txns.length === 0
                      ? <p style={{ fontFamily:"DM Mono", fontSize:12, color:"#374151", padding:"20px 0" }}>No transactions yet. Connect Gmail and sync.</p>
                      : txns.map((t, i) => (
                          <div key={i} className="txn">
                            <div style={{ display:"flex", alignItems:"center", gap:14 }}>
                              <span style={{ fontFamily:"DM Mono", fontSize:11, color:"#374151", width:72 }}>
                                {t.date ? new Date(t.date).toLocaleDateString("en-US",{month:"short",day:"numeric"}) : "—"}
                              </span>
                              <span style={{ fontFamily:"Instrument Sans", fontSize:13, color:"#E5E7EB", fontWeight:500 }}>{t.merchant || "Unknown"}</span>
                              <span style={{ fontFamily:"DM Mono", fontSize:10, color:"#374151",
                                background:"#13161F", padding:"2px 8px", borderRadius:4 }}>{t.category}</span>
                            </div>
                            <div style={{ display:"flex", alignItems:"center", gap:20 }}>
                              <span style={{ fontFamily:"DM Mono", fontSize:11, color:"#10B981" }}>
                                +₹{(t.cashback_earned||0).toFixed(2)}
                              </span>
                              <span style={{ fontFamily:"DM Mono", fontSize:13, color:"#F8F9FA", fontWeight:500 }}>
                                ₹{(t.amount||0).toLocaleString("en-IN")}
                              </span>
                            </div>
                          </div>
                        ))
                    }
                  </Card>
                </>
              )}

              {/* ── TRENDS ── */}
              {tab === "trends" && (
                <>
                  <Card style={{ marginBottom:16 }} delay={0.1}>
                    <CardTitle>Spending by Category Over Time</CardTitle>
                    <ResponsiveContainer width="100%" height={280}>
                      <BarChart data={byMonth} barSize={10}>
                        <XAxis dataKey="label" tick={{ fill:"#4B5563", fontSize:11, fontFamily:"DM Mono" }} axisLine={false} tickLine={false}/>
                        <YAxis tick={{ fill:"#4B5563", fontSize:11, fontFamily:"DM Mono" }} axisLine={false} tickLine={false} tickFormatter={v=>`₹${v}`}/>
                        <Tooltip content={<Tooltip_ />} />
                        {Object.entries(CAT_COLORS).slice(0,6).map(([cat, color], i) => (
                          <Bar key={cat} dataKey={`breakdown.${cat}`} stackId="a" fill={color} name={cat}
                            radius={i===5?[4,4,0,0]:[0,0,0,0]}/>
                        ))}
                      </BarChart>
                    </ResponsiveContainer>
                  </Card>

                  <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:16 }}>
                    <Card delay={0.2}>
                      <CardTitle>Total Monthly Trend</CardTitle>
                      <ResponsiveContainer width="100%" height={180}>
                        <LineChart data={byMonth}>
                          <XAxis dataKey="label" tick={{ fill:"#4B5563", fontSize:11, fontFamily:"DM Mono" }} axisLine={false} tickLine={false}/>
                          <YAxis tick={{ fill:"#4B5563", fontSize:11, fontFamily:"DM Mono" }} axisLine={false} tickLine={false} tickFormatter={v=>`₹${(v/1000).toFixed(1)}k`}/>
                          <Tooltip content={<Tooltip_ />} />
                          <Line type="monotone" dataKey="total" name="Total" stroke="#F59E0B" strokeWidth={2} dot={{ fill:"#F59E0B", r:3 }}/>
                        </LineChart>
                      </ResponsiveContainer>
                    </Card>

                    <Card delay={0.3}>
                      <CardTitle>Category Totals (6 mo)</CardTitle>
                      <div style={{ display:"flex", flexDirection:"column", gap:10, marginTop:4 }}>
                        {byCategory.map((c, i) => (
                          <div key={i}>
                            <div style={{ display:"flex", justifyContent:"space-between", marginBottom:4 }}>
                              <span style={{ fontFamily:"Instrument Sans", fontSize:12, color:"#9CA3AF" }}>{c.category}</span>
                              <span style={{ fontFamily:"DM Mono", fontSize:11, color:CAT_COLORS[c.category]||"#64748B" }}>
                                ₹{c.total.toLocaleString("en-IN")}
                              </span>
                            </div>
                            <div style={{ height:3, background:"#1A1D2A", borderRadius:4 }}>
                              <div style={{ height:"100%", width:`${c.pct}%`, background:CAT_COLORS[c.category]||"#64748B", borderRadius:4 }}/>
                            </div>
                          </div>
                        ))}
                      </div>
                    </Card>
                  </div>
                </>
              )}

              {/* ── MERCHANTS ── */}
              {tab === "merchants" && (
                <Card delay={0.1}>
                  <CardTitle>Top Merchants by Spend</CardTitle>
                  <div style={{ display:"grid", gridTemplateColumns:"2fr 1fr 1fr 1fr 1fr",
                    gap:0, marginBottom:12 }}>
                    {["Merchant","Spend","Transactions","Avg Txn","Category"].map(h => (
                      <span key={h} style={{ fontFamily:"DM Mono", fontSize:10, color:"#374151",
                        textTransform:"uppercase", letterSpacing:"0.08em", padding:"0 4px 10px" }}>{h}</span>
                    ))}
                  </div>
                  {merchants.map((m, i) => (
                    <div key={i} style={{ display:"grid", gridTemplateColumns:"2fr 1fr 1fr 1fr 1fr",
                      padding:"10px 0", borderBottom:"1px solid #13161F", transition:"background 0.15s" }}>
                      <div style={{ display:"flex", alignItems:"center", gap:10 }}>
                        <div style={{ width:28, height:28, borderRadius:6, background:"#13161F",
                          display:"flex", alignItems:"center", justifyContent:"center",
                          fontFamily:"DM Mono", fontSize:12, color:"#F59E0B", fontWeight:600 }}>
                          {(m.merchant||"?")[0]}
                        </div>
                        <span style={{ fontFamily:"Instrument Sans", fontSize:13, color:"#E5E7EB", fontWeight:500 }}>
                          {m.merchant}
                        </span>
                      </div>
                      <span style={{ fontFamily:"DM Mono", fontSize:13, color:"#F8F9FA", alignSelf:"center" }}>
                        ₹{m.total.toLocaleString("en-IN")}
                      </span>
                      <span style={{ fontFamily:"DM Mono", fontSize:12, color:"#6B7280", alignSelf:"center" }}>{m.count}</span>
                      <span style={{ fontFamily:"DM Mono", fontSize:12, color:"#6B7280", alignSelf:"center" }}>₹{m.avg_txn}</span>
                      <span style={{ fontFamily:"DM Mono", fontSize:11, color:CAT_COLORS[m.category]||"#64748B", alignSelf:"center",
                        background:`${CAT_COLORS[m.category]||"#64748B"}18`, padding:"2px 8px", borderRadius:4, width:"fit-content" }}>
                        {m.category}
                      </span>
                    </div>
                  ))}
                </Card>
              )}

              {/* ── OPTIMIZE ── */}
              {tab === "optimize" && (
                <>
                  <div style={{ display:"grid", gridTemplateColumns:"repeat(3,1fr)", gap:16, marginBottom:24 }}>
                    <KPI label="Current Cashback" value={`₹${totalCashback.toFixed(0)}/yr`}
                      sub="Estimated annualized" accent="#6B7280" delay={0.0} />
                    <KPI label="Potential Cashback"
                      value={`₹${(totalCashback + opps.reduce((s,o)=>s+o.annual_gain,0)).toFixed(0)}/yr`}
                      sub="With optimal card use" accent="#F59E0B" delay={0.1} />
                    <KPI label="Leaving on Table"
                      value={`₹${opps.reduce((s,o)=>s+o.annual_gain,0).toFixed(0)}/yr`}
                      sub={`${opps.length} opportunities found`} accent="#EF4444" delay={0.2} />
                  </div>

                  <div style={{ display:"grid", gridTemplateColumns:"1.3fr 1fr", gap:16 }}>
                    <div>
                      <p style={{ fontFamily:"DM Mono", fontSize:10, color:"#4B5563",
                        textTransform:"uppercase", letterSpacing:"0.12em", marginBottom:12 }}>
                        Optimization Opportunities
                      </p>
                      {opps.length === 0
                        ? <Card><p style={{ fontFamily:"DM Mono", fontSize:12, color:"#374151" }}>No opportunities found yet — sync more transactions for analysis.</p></Card>
                        : opps.map((o, i) => {
                            const bc = o.impact==="high"?"#F59E0B":o.impact==="medium"?"#6366F1":"#374151";
                            return (
                              <div key={i} style={{ background:"#0A0D15", borderRadius:10,
                                padding:16, borderLeft:`3px solid ${bc}`, marginBottom:10,
                                animation:`fadeUp 0.5s ease ${i*0.08}s both` }}>
                                <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start", marginBottom:6 }}>
                                  <span style={{ fontFamily:"Instrument Sans", fontSize:13, color:"#F8F9FA", fontWeight:600 }}>
                                    Switch {o.category} to {o.card}
                                  </span>
                                  <span style={{ fontFamily:"DM Mono", fontSize:12, color:"#10B981",
                                    background:"rgba(16,185,129,0.1)", padding:"2px 8px", borderRadius:4, whiteSpace:"nowrap", marginLeft:8 }}>
                                    +₹{o.annual_gain}/yr
                                  </span>
                                </div>
                                <p style={{ fontFamily:"Instrument Sans", fontSize:12, color:"#6B7280", lineHeight:1.5 }}>
                                  {o.note}. You're earning {o.current_rate}% — this card gives {o.best_rate}%.
                                </p>
                                <div style={{ display:"flex", gap:8, marginTop:8 }}>
                                  <span style={{ fontFamily:"DM Mono", fontSize:10, color:bc,
                                    background:`${bc}18`, padding:"2px 8px", borderRadius:4 }}>{o.impact} impact</span>
                                  <span style={{ fontFamily:"DM Mono", fontSize:10, color:"#374151",
                                    background:"#13161F", padding:"2px 8px", borderRadius:4 }}>card-switch</span>
                                </div>
                              </div>
                            );
                          })
                      }
                    </div>

                    <Card delay={0.2}>
                      <CardTitle>Cashback by Category</CardTitle>
                      <ResponsiveContainer width="100%" height={220}>
                        <BarChart data={byCategory} layout="vertical" barSize={8}>
                          <XAxis type="number" tick={{ fill:"#4B5563", fontSize:10, fontFamily:"DM Mono" }}
                            axisLine={false} tickLine={false} tickFormatter={v=>`₹${v}`}/>
                          <YAxis type="category" dataKey="category" tick={{ fill:"#6B7280", fontSize:10, fontFamily:"DM Mono" }}
                            axisLine={false} tickLine={false} width={90}
                            tickFormatter={v=>v.split(" ")[0]}/>
                          <Tooltip content={<Tooltip_ />} />
                          <Bar dataKey="cashback_earned" name="Cashback ($)" radius={[0,4,4,0]}>
                            {byCategory.map((c, i) => (
                              <Cell key={i} fill={CAT_COLORS[c.category]||"#64748B"}/>
                            ))}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </Card>
                  </div>
                </>
              )}
            </>
          )}

          {!dataLoading && !ins && gmailConnected && (
            <div style={{ textAlign:"center", padding:"80px 0" }}>
              <p style={{ fontFamily:"DM Mono", fontSize:13, color:"#374151", marginBottom:16 }}>
                Gmail connected. Click "Sync Gmail" to import your transactions.
              </p>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
