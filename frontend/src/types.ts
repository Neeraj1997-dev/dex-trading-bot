export interface RiskLimits {
  max_position_size_usd: number;
  max_daily_loss_usd: number;
  max_trades_per_day: number;
  max_portfolio_exposure_pct: number;
  stop_loss_pct: number;
  take_profit_pct: number;
  max_slippage_bps: number;
  min_liquidity_usd: number;
  max_gas_usd: number;
  min_confidence: number;
  max_open_positions: number;
}

export interface TradingPair {
  symbol: string;
  base_token: string;
  quote_token: string;
  enabled: boolean;
}

export interface AgentStatus {
  step: string;
  detail: string;
  runs: number;
  last_run_at?: string | null;
  last_result: Record<string, unknown>;
}

export interface DashboardSnapshot {
  agent: AgentStatus;
  bot: {
    status: string;
    mode: string;
    kill_switch: boolean;
    paused: boolean;
    risk_limits: RiskLimits;
    pairs: TradingPair[];
    last_cycle_at?: string;
    circuit_breaker_open: boolean;
    circuit_breaker_reason?: string;
  };
  portfolio: {
    total_value_usd: number;
    available_balance_usd: number;
    invested_usd: number;
    unrealized_pnl_usd: number;
    realized_pnl_usd: number;
    daily_pnl_usd: number;
    open_positions: number;
    win_rate: number;
    total_trades: number;
    wins: number;
    losses: number;
  };
  positions: Array<{
    id: string;
    symbol: string;
    side: string;
    status: string;
    entry_price: number;
    current_price: number;
    size: number;
    size_usd: number;
    unrealized_pnl_usd: number;
    take_profit: number;
    stop_loss: number;
    fees_usd: number;
    gas_usd: number;
    entry_tx_hash?: string;
    opened_at: string;
  }>;
  orders: Array<{
    id: string;
    symbol: string;
    side: string;
    status: string;
    filled_price?: number;
    size_usd: number;
    tx_hash?: string;
    failure_reason?: string;
    created_at: string;
  }>;
  signals: Array<{
    id: string;
    symbol: string;
    decision: string;
    status: string;
    confidence: number;
    risk_level: string;
    entry_price: number;
    take_profit: number;
    stop_loss: number;
    reasoning_summary: string;
    created_at: string;
  }>;
  connections: {
    dex: string;
    openai: string;
    database: string;
    last_market_update?: string;
  };
  recent_market: Array<{
    symbol: string;
    price: number;
    liquidity_usd: number;
    volume_24h: number;
    price_change_24h_pct: number;
    stale: boolean;
    timestamp: string;
  }>;
  trade_history: Array<{
    id: string;
    symbol: string;
    pnl_usd: number;
    reason: string;
    exit_price: number;
    created_at: string;
  }>;
}
