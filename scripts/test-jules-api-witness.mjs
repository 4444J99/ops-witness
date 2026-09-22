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
