import { test } from 'node:test';
import assert from 'node:assert/strict';
import { request } from '../src/api.ts';

test('带取消信号的行情请求仍受超时限制', async context => {
  const timeout = new AbortController();
  const caller = new AbortController();
  let signal;
  context.mock.method(AbortSignal, 'timeout', () => timeout.signal);
  context.mock.method(globalThis, 'fetch', async (_, init) => {
    signal = init.signal;
    return new Response(JSON.stringify({ ok: true }), { status: 200 });
  });
  await request('/market', { signal: caller.signal });
  timeout.abort(new DOMException('timeout', 'TimeoutError'));
  assert.equal(signal.aborted, true);
  assert.equal(caller.signal.aborted, false);
});

test('切换行情时调用方仍可取消请求', async context => {
  const caller = new AbortController();
  let signal;
  context.mock.method(globalThis, 'fetch', async (_, init) => {
    signal = init.signal;
    return new Response(JSON.stringify({ ok: true }), { status: 200 });
  });
  await request('/market', { signal: caller.signal });
  caller.abort();
  assert.equal(signal.aborted, true);
});
