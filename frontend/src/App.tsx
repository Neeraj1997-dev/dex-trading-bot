import { useEffect, useMemo, useState } from "react";
import { api } from "./api/client";
import type { DashboardSnapshot, RiskLimits } from "./types";
import "./styles.css";

type Tab =
  | "overview"
  | "positions"
  | "orders"
  | "signals"
  | "markets"
  | "history"
  | "settings";

function money(n: number) {
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  });
}

function pnlClass(n: number) {
  return n >= 0 ? "positive" : "negative";
}

function statusTone(value: string): "ok" | "warn" | "bad" | "info" {
  const v = value.toUpperCase();
  if (
    v.includes("CONNECTED") ||
    v === "RUNNING" ||
    v === "FILLED" ||
    v === "EXECUTED" ||
    v === "OPEN"
  ) {
    return "ok";
  }
  if (
    v.includes("KILL") ||
    v.includes("DISCONNECTED") ||
    v === "FAILED" ||
    v.includes("REJECTED")
  ) {
    return "bad";
  }
  if (v === "PAUSED" || v.includes("PENDING") || v === "DEGRADED" || v === "STOPPED") {
    return "warn";
  }
  return "info";
}

function StatusBadge({ value }: { value: string }) {
  return <span className={`badge ${statusTone(value)}`}>{value.replaceAll("_", " ")}</span>;
}

function ConfirmModal({
  title,
  message,
  confirmLabel,
  danger,
  onConfirm,
  onCancel,
}: {
  title: string;
  message: string;
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <div className="modal">
        <h3>{title}</h3>
        <p>{message}</p>
        <div className="modal-actions">
          <button className="btn" onClick={onCancel}>
            Cancel
          </button>
          <button
            className={`btn ${danger ? "btn-danger" : "btn-primary"}`}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

function Login({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState("admin@localhost");
  const [password, setPassword] = useState("ChangeMeNow!123");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await api.login(email, password);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={submit}>
        <div className="brand">
          <div className="brand-mark">Δ</div>
          <div className="brand-text">
            <strong>Delta Trading Console</strong>
            <span>Automated trading control panel</span>
          </div>
        </div>
        <h1>Sign in</h1>
        <p className="subtitle">
          Manage paper, approval, and auto trading. Secrets stay on the server.
        </p>
        {error && <div className="alert error">{error}</div>}
        <div className="field">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <button className="btn btn-primary" disabled={loading}>
          {loading ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}

function Empty({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {hint}
    </div>
  );
}

export default function App() {
  const [authed, setAuthed] = useState(api.isAuthed());
  const [data, setData] = useState<DashboardSnapshot | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<Tab>("overview");
  const [riskDraft, setRiskDraft] = useState<RiskLimits | null>(null);
  const [confirmKill, setConfirmKill] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [waStatus, setWaStatus] = useState<{
    enabled: boolean;
    provider: string;
    to: string;
    configured: boolean;
  } | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  async function refresh() {
    try {
      const snap = await api.dashboard();
      setData(snap);
      setRiskDraft(snap.bot.risk_limits);
      setError("");
      setLastRefresh(new Date());
      try {
        setWaStatus(await api.whatsappStatus());
      } catch {
        /* optional */
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load";
      setError(msg);
      if (msg === "Unauthorized") setAuthed(false);
    }
  }

  useEffect(() => {
    if (!authed) return;
    refresh();
    const id = setInterval(refresh, 8000);
    return () => clearInterval(id);
  }, [authed]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await action();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  const pendingSignals = useMemo(
    () => data?.signals.filter((s) => s.status === "PENDING_APPROVAL").length ?? 0,
    [data]
  );

  if (!authed) return <Login onDone={() => setAuthed(true)} />;

  if (!data || !riskDraft) {
    return (
      <div className="loading-page">
        <div>
          <div className="spinner" />
          <div>{error || "Loading dashboard…"}</div>
        </div>
      </div>
    );
  }

  const { bot, portfolio, positions, orders, signals, connections, recent_market, trade_history } =
    data;

  const uniqueMarkets = recent_market.filter(
    (m, i, arr) => arr.findIndex((x) => x.symbol === m.symbol) === i
  );

  const nav: { id: Tab; label: string; count?: number }[] = [
    { id: "overview", label: "Overview" },
    { id: "positions", label: "Positions", count: positions.length },
    { id: "orders", label: "Orders", count: orders.length },
    { id: "signals", label: "Signals", count: pendingSignals || undefined },
    { id: "markets", label: "Markets" },
    { id: "history", label: "History" },
    { id: "settings", label: "Settings" },
  ];

  const selectTab = (id: Tab) => {
    setTab(id);
    setMenuOpen(false);
  };

  return (
    <div className={`app ${menuOpen ? "menu-open" : ""}`}>
      <header className="topnav">
        <div className="topnav-left">
          <button
            type="button"
            className="icon-btn menu-toggle"
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((v) => !v)}
          >
            <span className="hamburger" data-open={menuOpen} />
          </button>
          <div className="brand">
            <div className="brand-mark">Δ</div>
            <div className="brand-text">
              <strong>Delta Trading</strong>
              <span className="brand-sub">Console</span>
            </div>
          </div>
        </div>
        <div className="nav-right">
          <div className="dot-row status-desktop">
            <StatusBadge value={bot.status} />
            <StatusBadge value={bot.mode} />
            <StatusBadge value={`DEX ${connections.dex}`} />
            <StatusBadge value={`DB ${connections.database}`} />
          </div>
          <div className="dot-row status-mobile">
            <StatusBadge value={bot.status} />
          </div>
          <button
            className="btn btn-ghost btn-sm hide-sm"
            onClick={() => refresh()}
            title="Refresh"
          >
            Refresh
          </button>
          <button
            className="icon-btn show-sm"
            aria-label="Refresh"
            onClick={() => refresh()}
          >
            ↻
          </button>
          <button
            className="btn btn-sm hide-sm"
            onClick={() => {
              api.logout();
              setAuthed(false);
            }}
          >
            Sign out
          </button>
        </div>
      </header>

      {menuOpen && (
        <button
          type="button"
          className="drawer-backdrop"
          aria-label="Close menu"
          onClick={() => setMenuOpen(false)}
        />
      )}

      <div className="layout">
        <aside className={`sidebar ${menuOpen ? "open" : ""}`}>
          <div className="sidebar-head show-sm">
            <strong>Menu</strong>
            <button type="button" className="icon-btn" aria-label="Close" onClick={() => setMenuOpen(false)}>
              ✕
            </button>
          </div>
          {nav.map((item) => (
            <button
              key={item.id}
              className={`nav-item ${tab === item.id ? "active" : ""}`}
              onClick={() => selectTab(item.id)}
            >
              {item.label}
              {item.count !== undefined && <span className="count">{item.count}</span>}
            </button>
          ))}
          <div className="sidebar-footer show-sm">
            <div className="dot-row" style={{ marginBottom: "0.75rem" }}>
              <StatusBadge value={bot.mode} />
              <StatusBadge value={`DEX ${connections.dex}`} />
            </div>
            <button
              className="btn btn-sm"
              style={{ width: "100%" }}
              onClick={() => {
                api.logout();
                setAuthed(false);
              }}
            >
              Sign out
            </button>
          </div>
        </aside>

        <main className="main">
          <div className="mobile-status-strip show-sm">
            <StatusBadge value={bot.mode} />
            <StatusBadge value={`DEX ${connections.dex}`} />
            <StatusBadge value={`DB ${connections.database}`} />
          </div>
          {error && <div className="alert error">{error}</div>}
          {bot.kill_switch && (
            <div className="alert error">
              Kill switch is active — new trades are blocked. Reset it in Overview or Settings.
            </div>
          )}
          {bot.circuit_breaker_open && (
            <div className="alert warn">
              Circuit breaker open: {bot.circuit_breaker_reason || "abnormal conditions"}
            </div>
          )}

          {tab === "overview" && (
            <>
              <div className="page-header">
                <div>
                  <h1>Overview</h1>
                  <p>
                    Portfolio health and bot controls
                    {lastRefresh
                      ? ` · Updated ${lastRefresh.toLocaleTimeString()}`
                      : ""}
                  </p>
                </div>
              </div>

              <div className="kpi-grid">
                <div className="card kpi">
                  <div className="kpi-label">Portfolio value</div>
                  <div className="kpi-value">{money(portfolio.total_value_usd)}</div>
                  <div className="kpi-sub">Invested {money(portfolio.invested_usd)}</div>
                </div>
                <div className="card kpi">
                  <div className="kpi-label">Available balance</div>
                  <div className="kpi-value">{money(portfolio.available_balance_usd)}</div>
                  <div className="kpi-sub">Ready to deploy</div>
                </div>
                <div className="card kpi">
                  <div className="kpi-label">Unrealized P&amp;L</div>
                  <div className={`kpi-value ${pnlClass(portfolio.unrealized_pnl_usd)}`}>
                    {money(portfolio.unrealized_pnl_usd)}
                  </div>
                  <div className="kpi-sub">
                    Daily {money(portfolio.daily_pnl_usd)} · Realized{" "}
                    {money(portfolio.realized_pnl_usd)}
                  </div>
                </div>
                <div className="card kpi">
                  <div className="kpi-label">Win rate</div>
                  <div className="kpi-value">{portfolio.win_rate.toFixed(1)}%</div>
                  <div className="kpi-sub">
                    {portfolio.wins}W / {portfolio.losses}L · {portfolio.total_trades} trades
                  </div>
                </div>
              </div>

              <div className="card" style={{ marginBottom: "1rem" }}>
                <div className="toolbar">
                  <button
                    className="btn btn-primary"
                    disabled={busy || bot.kill_switch}
                    onClick={() => run(() => api.control("START"))}
                  >
                    Start
                  </button>
                  <button className="btn" disabled={busy} onClick={() => run(() => api.control("STOP"))}>
                    Stop
                  </button>
                  <button className="btn" disabled={busy} onClick={() => run(() => api.control("PAUSE"))}>
                    Pause
                  </button>
                  <button
                    className="btn"
                    disabled={busy || bot.kill_switch}
                    onClick={() => run(() => api.control("RESUME"))}
                  >
                    Resume
                  </button>
                  <span className="sep" />
                  <button className="btn" disabled={busy} onClick={() => run(() => api.runCycle())}>
                    Run cycle
                  </button>
                  <button className="btn btn-danger" disabled={busy} onClick={() => setConfirmKill(true)}>
                    Kill switch
                  </button>
                  <button
                    className="btn"
                    disabled={busy}
                    onClick={() => run(() => api.control("RESET_KILL_SWITCH"))}
                  >
                    Reset kill / circuit
                  </button>
                  <select
                    aria-label="Trading mode"
                    value={bot.mode}
                    disabled={busy}
                    onChange={(e) => run(() => api.setMode(e.target.value))}
                  >
                    <option value="PAPER">Paper trading</option>
                    <option value="MANUAL_APPROVAL">Manual approval</option>
                    <option value="AUTO">Auto trading</option>
                  </select>
                </div>
                <div className="card-pad muted" style={{ fontSize: "0.85rem" }}>
                  Mode changes apply immediately. Paper uses live Delta prices with simulated fills.
                  Manual approval queues signals for review. Auto executes only after risk checks.
                </div>
              </div>

              <div className="grid-2">
                <div className="card">
                  <div className="card-head">
                    <h2>Open positions</h2>
                    <button className="btn btn-sm" onClick={() => setTab("positions")}>
                      View all
                    </button>
                  </div>
                  {positions.length === 0 ? (
                    <Empty title="No open positions" hint="Start the bot to begin scanning markets." />
                  ) : (
                    <div className="table-wrap">
                      <table className="data">
                        <thead>
                          <tr>
                            <th>Symbol</th>
                            <th>Entry / Mark</th>
                            <th>uPnL</th>
                          </tr>
                        </thead>
                        <tbody>
                          {positions.slice(0, 5).map((p) => (
                            <tr key={p.id}>
                              <td>
                                <strong>{p.symbol}</strong>
                                <div className="muted">{p.side}</div>
                              </td>
                              <td className="num">
                                {p.entry_price.toFixed(2)} / {p.current_price.toFixed(2)}
                              </td>
                              <td className={`num ${pnlClass(p.unrealized_pnl_usd)}`}>
                                {money(p.unrealized_pnl_usd)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>

                <div className="card">
                  <div className="card-head">
                    <h2>Latest signals</h2>
                    <button className="btn btn-sm" onClick={() => setTab("signals")}>
                      View all
                    </button>
                  </div>
                  {signals.length === 0 ? (
                    <Empty title="No signals yet" hint="Signals appear after an engine cycle." />
                  ) : (
                    <div className="table-wrap">
                      <table className="data">
                        <thead>
                          <tr>
                            <th>Symbol</th>
                            <th>Decision</th>
                            <th>Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          {signals.slice(0, 5).map((s) => (
                            <tr key={s.id}>
                              <td>
                                <strong>{s.symbol}</strong>
                                <div className="muted">conf {s.confidence}</div>
                              </td>
                              <td>{s.decision}</td>
                              <td>
                                <StatusBadge value={s.status} />
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>
            </>
          )}

          {tab === "positions" && (
            <>
              <div className="page-header">
                <div>
                  <h1>Positions</h1>
                  <p>Open exposure, entry, targets, and stop levels</p>
                </div>
              </div>
              <div className="card">
                {positions.length === 0 ? (
                  <Empty title="No open positions" hint="Filled orders will appear here." />
                ) : (
                  <div className="table-wrap" style={{ maxHeight: "none" }}>
                    <table className="data">
                      <thead>
                        <tr>
                          <th>Symbol</th>
                          <th>Side</th>
                          <th>Size</th>
                          <th>Entry</th>
                          <th>Mark</th>
                          <th>Take profit</th>
                          <th>Stop loss</th>
                          <th>uPnL</th>
                          <th>Fees</th>
                          <th>Tx</th>
                        </tr>
                      </thead>
                      <tbody>
                        {positions.map((p) => (
                          <tr key={p.id}>
                            <td>
                              <strong>{p.symbol}</strong>
                            </td>
                            <td>
                              <StatusBadge value={p.side} />
                            </td>
                            <td className="num">{money(p.size_usd)}</td>
                            <td className="num">{p.entry_price.toFixed(4)}</td>
                            <td className="num">{p.current_price.toFixed(4)}</td>
                            <td className="num">{p.take_profit.toFixed(4)}</td>
                            <td className="num">{p.stop_loss.toFixed(4)}</td>
                            <td className={`num ${pnlClass(p.unrealized_pnl_usd)}`}>
                              {money(p.unrealized_pnl_usd)}
                            </td>
                            <td className="num">{money(p.fees_usd + p.gas_usd)}</td>
                            <td className="mono">{p.entry_tx_hash?.slice(0, 14) || "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </>
          )}

          {tab === "orders" && (
            <>
              <div className="page-header">
                <div>
                  <h1>Orders</h1>
                  <p>Execution history with transaction references</p>
                </div>
              </div>
              <div className="card">
                {orders.length === 0 ? (
                  <Empty title="No orders" hint="Orders are created when signals execute." />
                ) : (
                  <div className="table-wrap" style={{ maxHeight: "none" }}>
                    <table className="data">
                      <thead>
                        <tr>
                          <th>Time</th>
                          <th>Symbol</th>
                          <th>Side</th>
                          <th>Size</th>
                          <th>Fill</th>
                          <th>Status</th>
                          <th>Tx / error</th>
                        </tr>
                      </thead>
                      <tbody>
                        {orders.map((o) => (
                          <tr key={o.id}>
                            <td className="mono">
                              {new Date(o.created_at).toLocaleString()}
                            </td>
                            <td>
                              <strong>{o.symbol}</strong>
                            </td>
                            <td>{o.side}</td>
                            <td className="num">{money(o.size_usd)}</td>
                            <td className="num">
                              {o.filled_price != null ? o.filled_price.toFixed(4) : "—"}
                            </td>
                            <td>
                              <StatusBadge value={o.status} />
                            </td>
                            <td className="mono">
                              {o.tx_hash?.slice(0, 18) || o.failure_reason || "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </>
          )}

          {tab === "signals" && (
            <>
              <div className="page-header">
                <div>
                  <h1>Signals &amp; AI analysis</h1>
                  <p>Structured decisions with entry, take-profit, and stop-loss</p>
                </div>
              </div>
              <div className="card">
                {signals.length === 0 ? (
                  <Empty title="No signals" hint="Run a cycle or wait for the scheduler." />
                ) : (
                  <div className="table-wrap" style={{ maxHeight: "none" }}>
                    <table className="data">
                      <thead>
                        <tr>
                          <th>Symbol</th>
                          <th>Decision</th>
                          <th>Levels</th>
                          <th>Confidence</th>
                          <th>Status</th>
                          <th>Analysis</th>
                          <th>Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {signals.map((s) => (
                          <tr key={s.id}>
                            <td>
                              <strong>{s.symbol}</strong>
                              <div className="muted">{s.risk_level}</div>
                            </td>
                            <td>{s.decision}</td>
                            <td className="num">
                              E {s.entry_price.toFixed(2)}
                              <br />
                              TP {s.take_profit.toFixed(2)}
                              <br />
                              SL {s.stop_loss.toFixed(2)}
                            </td>
                            <td className="num">{s.confidence}</td>
                            <td>
                              <StatusBadge value={s.status} />
                            </td>
                            <td style={{ maxWidth: 240 }}>
                              <span className="muted">{s.reasoning_summary}</span>
                            </td>
                            <td>
                              {s.status === "PENDING_APPROVAL" ? (
                                <div className="btn-group">
                                  <button
                                    className="btn btn-primary btn-sm"
                                    disabled={busy}
                                    onClick={() => run(() => api.approveSignal(s.id, true))}
                                  >
                                    Approve
                                  </button>
                                  <button
                                    className="btn btn-sm"
                                    disabled={busy}
                                    onClick={() => run(() => api.approveSignal(s.id, false))}
                                  >
                                    Reject
                                  </button>
                                </div>
                              ) : (
                                <span className="muted">—</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </>
          )}

          {tab === "markets" && (
            <>
              <div className="page-header">
                <div>
                  <h1>Markets</h1>
                  <p>Live Delta Exchange tickers for enabled pairs</p>
                </div>
              </div>
              <div className="card">
                {uniqueMarkets.length === 0 ? (
                  <Empty title="No market data" hint="Check DEX connection and enabled pairs." />
                ) : (
                  <div className="table-wrap" style={{ maxHeight: "none" }}>
                    <table className="data">
                      <thead>
                        <tr>
                          <th>Symbol</th>
                          <th>Price</th>
                          <th>24h change</th>
                          <th>Volume</th>
                          <th>Liquidity</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {uniqueMarkets.map((m) => (
                          <tr key={m.symbol}>
                            <td>
                              <strong>{m.symbol}</strong>
                            </td>
                            <td className="num">{m.price.toFixed(4)}</td>
                            <td className={`num ${pnlClass(m.price_change_24h_pct)}`}>
                              {m.price_change_24h_pct.toFixed(2)}%
                            </td>
                            <td className="num">{m.volume_24h.toLocaleString()}</td>
                            <td className="num">{money(m.liquidity_usd)}</td>
                            <td>
                              {m.stale ? (
                                <StatusBadge value="STALE" />
                              ) : (
                                <StatusBadge value="LIVE" />
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </>
          )}

          {tab === "history" && (
            <>
              <div className="page-header">
                <div>
                  <h1>Trade history</h1>
                  <p>Closed trades with realized P&amp;L</p>
                </div>
              </div>
              <div className="card">
                {trade_history.length === 0 ? (
                  <Empty
                    title="No closed trades"
                    hint="History fills when take-profit or stop-loss exits complete."
                  />
                ) : (
                  <div className="table-wrap" style={{ maxHeight: "none" }}>
                    <table className="data">
                      <thead>
                        <tr>
                          <th>Time</th>
                          <th>Symbol</th>
                          <th>Reason</th>
                          <th>Exit</th>
                          <th>P&amp;L</th>
                        </tr>
                      </thead>
                      <tbody>
                        {trade_history.map((t) => (
                          <tr key={t.id}>
                            <td className="mono">
                              {new Date(t.created_at).toLocaleString()}
                            </td>
                            <td>
                              <strong>{t.symbol}</strong>
                            </td>
                            <td>{t.reason}</td>
                            <td className="num">{t.exit_price.toFixed(4)}</td>
                            <td className={`num ${pnlClass(t.pnl_usd)}`}>{money(t.pnl_usd)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </>
          )}

          {tab === "settings" && (
            <>
              <div className="page-header">
                <div>
                  <h1>Settings</h1>
                  <p>Risk limits, pairs, and trading mode</p>
                </div>
              </div>
              <div className="grid-2">
                <div className="card">
                  <div className="card-head">
                    <h2>Risk limits</h2>
                    <button
                      className="btn btn-primary btn-sm"
                      disabled={busy}
                      onClick={() => run(() => api.updateRisk(riskDraft))}
                    >
                      Save
                    </button>
                  </div>
                  <div className="card-pad">
                    <div className="form-grid">
                      {(
                        [
                          ["max_position_size_usd", "Max position ($)"],
                          ["max_daily_loss_usd", "Max daily loss ($)"],
                          ["max_trades_per_day", "Max trades / day"],
                          ["max_portfolio_exposure_pct", "Max exposure (%)"],
                          ["stop_loss_pct", "Stop-loss (%)"],
                          ["take_profit_pct", "Take-profit (%)"],
                          ["max_slippage_bps", "Max slippage (bps)"],
                          ["min_liquidity_usd", "Min liquidity ($)"],
                          ["max_gas_usd", "Max fee / gas ($)"],
                          ["min_confidence", "Min AI confidence"],
                          ["max_open_positions", "Max open positions"],
                        ] as const
                      ).map(([key, label]) => (
                        <div className="field" key={key}>
                          <label htmlFor={key}>{label}</label>
                          <input
                            id={key}
                            type="number"
                            value={riskDraft[key]}
                            onChange={(e) =>
                              setRiskDraft({ ...riskDraft, [key]: Number(e.target.value) })
                            }
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="stack">
                  <div className="card">
                    <div className="card-head">
                      <h2>Trading pairs</h2>
                    </div>
                    <div className="card-pad">
                      <div className="switch-list">
                        {bot.pairs.map((p) => (
                          <label key={p.symbol} className="switch-row">
                            <div>
                              <strong>{p.symbol}</strong>
                              <div className="muted" style={{ fontSize: "0.78rem" }}>
                                {p.base_token}/{p.quote_token}
                              </div>
                            </div>
                            <input
                              type="checkbox"
                              checked={p.enabled}
                              onChange={(e) =>
                                run(() => api.togglePair(p.symbol, e.target.checked))
                              }
                            />
                          </label>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div className="card">
                    <div className="card-head">
                      <h2>Connections</h2>
                    </div>
                    <div className="card-pad">
                      <div className="switch-list">
                        <div className="switch-row">
                          <strong>Delta Exchange</strong>
                          <StatusBadge value={connections.dex} />
                        </div>
                        <div className="switch-row">
                          <strong>OpenAI</strong>
                          <StatusBadge value={connections.openai} />
                        </div>
                        <div className="switch-row">
                          <strong>MongoDB</strong>
                          <StatusBadge value={connections.database} />
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="card">
                    <div className="card-head">
                      <h2>WhatsApp alerts</h2>
                      <button
                        className="btn btn-primary btn-sm"
                        disabled={busy}
                        onClick={() =>
                          run(async () => {
                            await api.whatsappTest();
                          })
                        }
                      >
                        Send test
                      </button>
                    </div>
                    <div className="card-pad">
                      <div className="switch-list">
                        <div className="switch-row">
                          <strong>Recipient</strong>
                          <span className="mono">{waStatus?.to || "+916206240867"}</span>
                        </div>
                        <div className="switch-row">
                          <strong>Provider</strong>
                          <span>{waStatus?.provider || "—"}</span>
                        </div>
                        <div className="switch-row">
                          <strong>Status</strong>
                          <StatusBadge
                            value={
                              waStatus?.configured
                                ? "CONFIGURED"
                                : waStatus?.enabled
                                  ? "NEEDS_API_KEY"
                                  : "DISABLED"
                            }
                          />
                        </div>
                      </div>
                      <p className="muted" style={{ marginTop: "0.85rem", fontSize: "0.82rem" }}>
                        Optional. Disabled by default. Set{" "}
                        <code>WHATSAPP_ENABLED=true</code> and{" "}
                        <code>CALLMEBOT_APIKEY</code> (or Twilio/Meta) in{" "}
                        <code>.env</code>, then rebuild the API container.
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </>
          )}
        </main>
      </div>

      <nav className="bottom-nav show-sm" aria-label="Primary">
        {(
          [
            { id: "overview" as Tab, label: "Home" },
            { id: "positions" as Tab, label: "Pos" },
            { id: "signals" as Tab, label: "Signals", count: pendingSignals },
            { id: "markets" as Tab, label: "Mkts" },
            { id: "settings" as Tab, label: "More" },
          ] as const
        ).map((item) => (
          <button
            key={item.id}
            type="button"
            className={`bottom-nav-item ${tab === item.id ? "active" : ""}`}
            onClick={() => selectTab(item.id)}
          >
            <span className="bottom-nav-label">{item.label}</span>
            {"count" in item && item.count ? (
              <span className="bottom-nav-badge">{item.count}</span>
            ) : null}
          </button>
        ))}
      </nav>

      {confirmKill && (
        <ConfirmModal
          title="Activate kill switch?"
          message="This immediately blocks all new trades. Open positions are not closed automatically."
          confirmLabel="Activate kill switch"
          danger
          onCancel={() => setConfirmKill(false)}
          onConfirm={() => {
            setConfirmKill(false);
            run(() => api.control("KILL_SWITCH"));
          }}
        />
      )}
    </div>
  );
}
