import { test } from 'node:test';
import assert from 'node:assert/strict';
import { csvCell, price } from '../src/format.ts';

test('低价币价格与止损价保留足够精度，不显示为零或相同价格', () => {
  assert.equal(price(0.00000123), '0.00000123');
  assert.notEqual(price(0.00001234), price(0.00001234 * 0.98));
  assert.equal(price(65432.12), '65,432.12');
  assert.equal(price(Number.NaN), '—');
});

test('导出保留负数金额类型，同时防止文字单元格被识别为公式', () => {
  assert.equal(csvCell(-12.34), '"-12.34"');
  assert.equal(csvCell('=1+1'), '"\'=1+1"');
  assert.equal(csvCell('说明"文字'), '"说明""文字"');
});
