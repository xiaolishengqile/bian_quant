import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validateConfig } from '../src/config-validation.ts';

const config = {
  mode: 'paper', market_source: 'demo', symbols: ['BTCUSDT'], interval: '15m', leverage: 3,
  margin_mode: 'isolated', initial_balance: 10000, order_margin: 100,
  max_position_margin: 1000, daily_loss_limit: 200, stop_loss_pct: 2, take_profit_pct: 4,
  macd_fast: 12, macd_slow: 26, macd_signal: 9, reverse_on_signal: true, fee_bps: 4, slippage_bps: 2,
};
test('拒绝实盘使用演示行情', () => assert.match(validateConfig({ ...config, mode: 'live' }), /币安行情/));
test('拒绝倒置的指标周期', () => assert.match(validateConfig({ ...config, macd_fast: 30 }), /快线/));
test('拒绝超过总额度的单笔仓位', () => assert.match(validateConfig({ ...config, order_margin: 2000 }), /单笔/));
test('拒绝超过策略资金的保证金上限', () => assert.match(validateConfig({ ...config, max_position_margin: 20000 }), /策略资金/));
test('拒绝清空所有交易币种', () => assert.match(validateConfig({ ...config, symbols: [] }), /币种/));
test('拒绝非法数值', () => assert.match(validateConfig({ ...config, leverage: Number.NaN }), /数值/));
test('接受合法的完整配置', () => assert.equal(validateConfig(config), null));
