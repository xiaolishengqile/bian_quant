import type { StrategyConfig } from './types.ts';

export function validateConfig(config: StrategyConfig): string | null {
  if (Object.values(config).some(value => typeof value === 'number' && !Number.isFinite(value))) return '请填写有效数值';
  if (config.mode !== 'paper' && config.market_source !== 'binance') return '测试网和实盘必须使用币安行情';
  if (!config.symbols.length || config.symbols.length > 8) return '请选择 1 至 8 个交易币种';
  if (new Set(config.symbols).size !== config.symbols.length) return '交易币种不能重复';
  if (config.macd_fast >= config.macd_slow) return '指标快线周期必须小于慢线周期';
  if (config.order_margin > config.max_position_margin) return '单笔保证金不能超过总保证金上限';
  if (config.max_position_margin > config.initial_balance) return '总保证金上限不能超过策略资金';
  return null;
}
