export type Mode = 'paper' | 'testnet' | 'live';
export type Interval = '1m' | '3m' | '5m' | '15m' | '30m' | '1h' | '4h' | '1d';
export interface StrategyConfig {
  mode: Mode; market_source: 'demo' | 'binance'; symbols: string[]; interval: Interval;
  leverage: number; margin_mode: 'isolated' | 'cross'; initial_balance: number;
  order_margin: number; max_position_margin: number; daily_loss_limit: number;
  stop_loss_pct: number; take_profit_pct: number; macd_fast: number; macd_slow: number;
  macd_signal: number; reverse_on_signal: boolean; fee_bps: number; slippage_bps: number;
}
export interface Candle { time: number; open: number; high: number; low: number; close: number; volume: number; close_time: number }
export interface Indicator { time: number; macd: number | null; signal: number | null; histogram: number | null }
export interface MarketSnapshot {
  symbol: string; interval: Interval; source: string; candles: Candle[]; last_price: number;
  change_pct: number; updated_at: number; error: string | null; indicators: Indicator[];
}
export interface Position {
  symbol: string; side: 'long' | 'short'; quantity: number; entry_price: number; mark_price: number;
  leverage: number; margin: number; unrealized_pnl: number; stop_loss: number; take_profit: number; opened_at: number;
}
export interface Order {
  id: string; timestamp: number; symbol: string; side: 'long' | 'short'; action: 'open' | 'close';
  quantity: number; price: number; fee: number; realized_pnl: number; reason: string; mode: Mode; status: string; fee_estimated?: boolean;
}
export interface Log { id: number | string; timestamp: number; level: 'info' | 'warning' | 'error'; message: string }
export interface Connections {
  testnet_configured: boolean; live_configured: boolean; live_enabled: boolean;
  testnet_managed: boolean; live_managed: boolean;
}
export interface ConsoleState {
  config: StrategyConfig;
  status: { state: 'stopped' | 'running' | 'error' | 'risk_stopped'; last_tick: number | null; last_error: string | null; started_at: number | null };
  summary: { initial_balance: number; wallet_balance: number; available_balance: number | null; account_synced: boolean; equity: number; unrealized_pnl: number; realized_pnl: number; fees: number; total_trades: number; win_rate: number; exposure: number; daily_pnl: number };
  positions: Position[]; orders: Order[]; logs: Log[]; connections: Connections;
}
export interface SymbolInfo { symbol: string; base_asset: string; quote_asset: string }
export interface SymbolResponse { symbols: SymbolInfo[]; source: 'binance' | 'demo'; error?: string }
export interface BacktestResult {
  symbol: string; bars: number; start_time: number; end_time: number; initial_balance: number;
  final_equity: number; return_pct: number; max_drawdown_pct: number; total_trades: number;
  win_rate: number; fees: number; trades: unknown[]; equity_curve: { time: number; equity: number }[]; assumptions: string[];
}
export type Page = 'overview' | 'strategy' | 'trades' | 'backtest' | 'settings';
