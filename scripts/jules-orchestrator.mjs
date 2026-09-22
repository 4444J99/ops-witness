#!/usr/bin/env node
/** Legacy entry point, now an independent read-only Jules API witness.
 * Execution belongs to Limen. No LLM-generated debt, issue writes, or fake dispatch.
 */
import { createHash } from 'node:crypto';
import { readFileSync, statSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';

// Source: 4444J99/limen@ec33e5bc4d5d097cac6569516f24ccabee78891a
// cli/src/limen/jules_api.py; changing this pin requires reviewed source.
export const CLIENT_SHA256 = 'd067f2dbe4c2c6d3bef1c1fb07614124e441a8d615313fb9687045bb007bea2d';
const SCHEMA = 'limen.jules_api_observation.v1';
const STATES = new Set(['COMPLETED', 'FAILED', 'QUEUED', 'PLANNING', 'IN_PROGRESS',
  'AWAITING_PLAN_APPROVAL', 'AWAITING_USER_FEEDBACK', 'PAUSED']);
const safeError = (code) => ({ schema_version: SCHEMA, status: 'unavailable',
  error_code: code, observed_rolling_starts: null, nonterminal_sessions: null,
  vendor_quota_remaining: null });
const count = (value) => Number.isSafeInteger(value) && value >= 0;

// Date.parse alone coerces non-strings and normalizes impossible calendar dates.
// Accept real timezone-qualified instants, including Python's microsecond output.
const timestamp = (value) => {
  if (typeof value !== 'string') return NaN;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?(?:Z|[+-](\d{2}):(\d{2}))$/.exec(value);
  if (!match) return NaN;
  const [, year, month, day, hour, minute, second, offsetHour = '00', offsetMinute = '00'] = match;
  const y = Number(year); const m = Number(month); const d = Number(day);
  const leap = y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (m < 1 || m > 12 || d < 1 || d > days[m - 1] || Number(hour) > 23
      || Number(minute) > 59 || Number(second) > 59 || Number(offsetHour) > 23
      || Number(offsetMinute) > 59) return NaN;
  return Date.parse(value);
};

export function decodeObservation(child, context = {}) {
  if (!child || typeof child !== 'object' || child.error || child.signal) return { exitCode: 2, observation: safeError('observer_transport_unavailable') };
  let row;
  try { row = JSON.parse(child.stdout); }
  catch { return { exitCode: 2, observation: safeError('observer_invalid_json') }; }
  if (!row || row.schema_version !== SCHEMA) return { exitCode: 2, observation: safeError('observer_invalid_schema') };
  if (row.status !== 'observed' || child.status !== 0) {
    const code = typeof row.error_code === 'string' && /^[a-z_]{1,80}$/.test(row.error_code)
      ? row.error_code : 'observer_execution_failed';
    return { exitCode: 2, observation: safeError(code) };
  }
  if (row.pagination_complete !== true || !count(row.observed_rolling_starts)
      || !count(row.nonterminal_sessions) || !count(row.sessions_observed)
      || !count(row.sources_observed) || !count(row.pages) || row.pages < 1
      || row.vendor_quota_remaining !== null || row.history_is_billing_ledger !== false
      || row.provider_completed_is_merged !== false || !row.states
      || typeof row.states !== 'object' || Array.isArray(row.states)
      || !Number.isFinite(timestamp(row.observed_at)) || !Number.isFinite(timestamp(row.window_start))) {
    return { exitCode: 2, observation: safeError('observer_incomplete_evidence') };
  }
  const observed = timestamp(row.observed_at); const windowStart = timestamp(row.window_start);
  if (observed - windowStart !== 24 * 60 * 60 * 1000) {
    return { exitCode: 2, observation: safeError('observer_invalid_window') };
  }
  // Standalone decoding can inspect historical evidence; a live invocation must
  // additionally bind that evidence to its actual start/end, not a new wrapper date.
  if ('startedAt' in context || 'endedAt' in context) {
    const start = timestamp(context.startedAt); const end = timestamp(context.endedAt);
    if (!Number.isFinite(start) || !Number.isFinite(end) || start > end
        || observed < start || observed > end) {
      return { exitCode: 2, observation: safeError('observer_outside_invocation') };
    }
  }
  let total = 0; let active = 0;
  for (const [state, value] of Object.entries(row.states)) {
    if (!STATES.has(state) || !count(value)) return { exitCode: 2, observation: safeError('observer_invalid_states') };
    total += value;
    if (!['COMPLETED', 'FAILED'].includes(state)) active += value;
  }
  if (total !== row.sessions_observed || active !== row.nonterminal_sessions
      || row.observed_rolling_starts > total) {
    return { exitCode: 2, observation: safeError('observer_inconsistent_counts') };
  }
  // A strict output whitelist prevents provider prose, prompts, keys or URLs leaking.
  return { exitCode: 0, observation: { schema_version: SCHEMA, status: 'observed',
    observed_at: row.observed_at, window_start: row.window_start,
    pagination_complete: true, pages: row.pages, sources_observed: row.sources_observed,
    sessions_observed: row.sessions_observed, observed_rolling_starts: row.observed_rolling_starts,
    nonterminal_sessions: row.nonterminal_sessions, states: row.states,
    vendor_quota_remaining: null, history_is_billing_ledger: false,
    provider_completed_is_merged: false } };
}

export function runWitness({ clientFile, env = process.env, runner = spawnSync } = {}) {
  const started = new Date().toISOString();
  let result;
  try {
    if (!clientFile || statSync(clientFile).size > 65536) throw new Error('client');
    const source = readFileSync(clientFile);
    if (createHash('sha256').update(source).digest('hex') !== CLIENT_SHA256) throw new Error('pin');
    const childEnv = {};
    for (const key of ['PATH', 'HOME', 'SYSTEMROOT', 'WINDIR', 'TMPDIR', 'TEMP', 'TMP', 'LD_LIBRARY_PATH']) {
      if (typeof env[key] === 'string') childEnv[key] = env[key];
    }
    childEnv.JULES_API_KEY = env.JULES_API_KEY || '';
    // Execute the already-hashed bytes, not a path that could change after validation.
    const child = runner(env.LIMEN_PYTHON_BIN || 'python3', ['-I', '-c', source.toString('utf8'), 'observe'],
      { encoding: 'utf8', env: childEnv, timeout: 110000, maxBuffer: 131072, shell: false });
    result = decodeObservation(child, { startedAt: started, endedAt: new Date().toISOString() });
  } catch {
    result = { exitCode: 2, observation: safeError('observer_client_unavailable_or_unverified') };
  }
  return { ...result, receipt: { witness: 'ops-witness/jules-api', started_at: started,
    ended_at: new Date().toISOString(), status: result.exitCode === 0 ? 'observed' : 'unavailable',
    client_sha256: CLIENT_SHA256, provider_mutations: 0, merges_performed: 0 } };
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  const result = runWitness({ clientFile: process.env.LIMEN_JULES_API_CLIENT });
  console.log(JSON.stringify({ ...result.observation, witness_receipt: result.receipt }));
  process.exitCode = result.exitCode;
}
