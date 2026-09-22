import test from 'node:test';
import assert from 'node:assert/strict';
import { decodeObservation, runWitness } from './jules-orchestrator.mjs';
const valid = () => ({ schema_version: 'limen.jules_api_observation.v1', status: 'observed',
  observed_at: '2026-09-21T20:00:00Z', window_start: '2026-09-20T20:00:00Z',
  pagination_complete: true, pages: 1, sources_observed: 4, sessions_observed: 2,
  observed_rolling_starts: 2, nonterminal_sessions: 1, states: { COMPLETED: 1, PAUSED: 1 },
  vendor_quota_remaining: null, history_is_billing_ledger: false, provider_completed_is_merged: false });
const child = (row, status = 0) => ({ status, stdout: JSON.stringify(row) });
test('valid provider observation is retained, not called dispatched', () => {
  const got = decodeObservation(child(valid()));
  assert.equal(got.exitCode, 0); assert.equal(got.observation.status, 'observed');
  assert.equal(got.observation.vendor_quota_remaining, null);
});
test('unknown credentials do not become zero usage', () => {
  const got = decodeObservation(child({ schema_version: valid().schema_version, status: 'unavailable',
    error_code: 'jules_api_key_missing_or_invalid' }, 2));
  assert.equal(got.exitCode, 2); assert.equal(got.observation.observed_rolling_starts, null);
});
test('nonzero exit cannot be converted into success by JSON', () => {
  assert.equal(decodeObservation(child(valid(), 1)).exitCode, 2);
});
test('incomplete pagination does not establish capacity', () => {
  assert.equal(decodeObservation(child({ ...valid(), pagination_complete: false })).exitCode, 2);
});
test('invented vendor quota rejected', () => {
  assert.equal(decodeObservation(child({ ...valid(), vendor_quota_remaining: 98 })).exitCode, 2);
});
test('mismatched state totals rejected', () => {
  assert.equal(decodeObservation(child({ ...valid(), nonterminal_sessions: 0 })).exitCode, 2);
});
test('unknown state rejected', () => {
  assert.equal(decodeObservation(child({ ...valid(), states: { NEW_STATE: 2 } })).exitCode, 2);
});
test('negative counts rejected', () => {
  assert.equal(decodeObservation(child({ ...valid(), observed_rolling_starts: -1 })).exitCode, 2);
});
test('provider prose and extra keys do not escape', () => {
  const got = decodeObservation(child({ ...valid(), prompt: 'PRIVATE', api_key: 'SECRET' }));
  assert.ok(!JSON.stringify(got).includes('PRIVATE')); assert.ok(!JSON.stringify(got).includes('SECRET'));
});
test('timeout retained as unavailable, no stderr disclosure', () => {
  const got = decodeObservation({ error: new Error('SECRET'), stderr: 'SECRET', status: null });
  assert.equal(got.exitCode, 2); assert.ok(!JSON.stringify(got).includes('SECRET'));
});
test('malformed JSON unavailable', () => {
  assert.equal(decodeObservation({ stdout: 'not json', status: 0 }).exitCode, 2);
});
test('missing client never calls an alternative dispatcher', () => {
  let calls = 0;
  const got = runWitness({ clientFile: '/does/not/exist', runner: () => { calls++; } });
  assert.equal(calls, 0); assert.equal(got.exitCode, 2); assert.equal(got.receipt.provider_mutations, 0);
});
test('timestamp coercions and non-RFC3339 strings rejected', () => {
  for (const timestamp of [0, [], ['2026-09-21'], '2026-09-21', '09/21/2026', '2026-09-21T20:00:00']) {
    const got = decodeObservation(child({ ...valid(), observed_at: timestamp }));
    assert.equal(got.exitCode, 2, JSON.stringify(timestamp));
    assert.equal(got.observation.observed_rolling_starts, null);
  }
});
test('impossible calendar dates rejected instead of normalized', () => {
  for (const timestamp of ['2026-02-30T20:00:00Z', '2026-02-29T20:00:00Z',
    '2026-04-31T20:00:00Z', '2026-09-21T24:00:00Z']) {
    assert.equal(decodeObservation(child({ ...valid(), observed_at: timestamp })).exitCode, 2, timestamp);
  }
});
test('rolling window must be exactly 24 hours, never a calendar-day guess', () => {
  for (const timestamp of ['2026-09-20T00:00:00Z', '2026-09-21T20:00:00Z', '2026-09-22T20:00:00Z']) {
    assert.equal(decodeObservation(child({ ...valid(), window_start: timestamp })).exitCode, 2, timestamp);
  }
});
test('timezone offsets and emitter microseconds preserve the same rolling window', () => {
  const got = decodeObservation(child({ ...valid(), observed_at: '2026-09-21T16:00:00.123456-04:00',
    window_start: '2026-09-20T20:00:00.123456+00:00' }));
  assert.equal(got.exitCode, 0);
});
test('valid leap dates retained', () => {
  const got = decodeObservation(child({ ...valid(), observed_at: '2028-03-01T00:00:00Z',
    window_start: '2028-02-29T00:00:00Z' }));
  assert.equal(got.exitCode, 0);
});
test('zero pages cannot assert completed pagination', () => {
  assert.equal(decodeObservation(child({ ...valid(), pages: 0 })).exitCode, 2);
});
test('empty catalogue needs an actual observed page', () => {
  assert.equal(decodeObservation(child({ ...valid(), states: {}, sessions_observed: 0,
    nonterminal_sessions: 0, observed_rolling_starts: 0, sources_observed: 0 })).exitCode, 0);
});
test('invocation interval rejects stale and future replay', () => {
  for (const context of [
    { startedAt: '2026-09-22T20:00:00Z', endedAt: '2026-09-22T20:02:00Z' },
    { startedAt: '2026-09-20T20:00:00Z', endedAt: '2026-09-20T20:02:00Z' },
  ]) {
    const got = decodeObservation(child(valid()), context);
    assert.equal(got.exitCode, 2);
    assert.equal(got.observation.nonterminal_sessions, null);
  }
});
test('observed time is bounded by actual invocation, inclusive', () => {
  for (const context of [
    { startedAt: '2026-09-21T19:59:00Z', endedAt: '2026-09-21T20:01:00Z' },
    { startedAt: '2026-09-21T20:00:00Z', endedAt: '2026-09-21T20:00:00Z' },
  ]) assert.equal(decodeObservation(child(valid()), context).exitCode, 0);
});
test('incomplete, malformed, or inverted invocation interval rejected', () => {
  for (const context of [
    { startedAt: '2026-09-21T19:59:00Z' },
    { endedAt: '2026-09-21T20:01:00Z' },
    { startedAt: 0, endedAt: '2026-09-21T20:01:00Z' },
    { startedAt: '2026-09-21T20:01:00Z', endedAt: '2026-09-21T19:59:00Z' },
  ]) assert.equal(decodeObservation(child(valid()), context).exitCode, 2);
});
test('missing subprocess result does not throw or claim success', () => {
  for (const result of [null, undefined, 0]) assert.equal(decodeObservation(result).exitCode, 2);
});

test('sub-millisecond shorter and longer windows rejected exactly', () => {
  for (const [observed, start] of [
    ['2026-09-21T20:00:00.0001Z', '2026-09-20T20:00:00.0009Z'],
    ['2026-09-21T20:00:00.0009Z', '2026-09-20T20:00:00.0001Z'],
    ['2026-09-21T20:00:00.123456789Z', '2026-09-20T20:00:00.123456788Z'],
    ['2026-09-21T20:00:00.123456788Z', '2026-09-20T20:00:00.123456789Z'],
  ]) {
    const got = decodeObservation(child({ ...valid(), observed_at: observed, window_start: start }));
    assert.equal(got.exitCode, 2, `${observed} / ${start}`);
    assert.equal(got.observation.error_code, 'observer_invalid_window');
  }
});
test('equivalent fractional precision and timezone offsets retained', () => {
  for (const [observed, start] of [
    ['2026-09-21T16:00:00.123456789-04:00', '2026-09-20T20:00:00.123456789Z'],
    ['2026-09-21T20:00:00.100000000Z', '2026-09-20T20:00:00.1+00:00'],
    ['2026-09-21T20:00:00Z', '2026-09-20T20:00:00.000000000Z'],
  ]) assert.equal(decodeObservation(child({ ...valid(), observed_at: observed, window_start: start })).exitCode, 0);
});
