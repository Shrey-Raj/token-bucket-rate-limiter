import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';

const allowed = new Counter('allowed_200');
const limited = new Counter('limited_429');
const unavailable = new Counter('unavailable_503');

http.setResponseCallback(http.expectedStatuses(200, 429, 401, 503));

const URL = 'http://localhost:8000/v1/check';
const TEST = __ENV.TEST || 'burst';

const scenarios = {
  burst: {
    executor: 'shared-iterations',
    vus: 100, iterations: 1000, maxDuration: '30s',
    exec: 'singleClient',
  },
  sustained: {
    executor: 'constant-arrival-rate',
    rate: 30, timeUnit: '1s', duration: '30s',
    preAllocatedVUs: 20, exec: 'singleClient',
  },
  manykeys: {
    executor: 'constant-arrival-rate',
    rate: 200, timeUnit: '1s', duration: '30s',
    preAllocatedVUs: 50, exec: 'perClient',
  },
  stress: {
    executor: 'ramping-arrival-rate',
    startRate: 100, timeUnit: '1s',
    preAllocatedVUs: 200, maxVUs: 500,
    stages: [
      { target: 500, duration: '20s' },
      { target: 1000, duration: '20s' },
      { target: 2000, duration: '20s' },
    ],
    exec: 'perClient',
  },
  outage: {
    executor: 'constant-arrival-rate',
    rate: 100, timeUnit: '1s', duration: '60s',
    preAllocatedVUs: 150, maxVUs: 300,
    exec: 'outageClient',
  },
  auth: {
    executor: 'per-vu-iterations',
    vus: 1, iterations: 1, maxDuration: '30s',
    exec: 'authCheck',
  },
  spoof: {
    executor: 'shared-iterations',
    vus: 20, iterations: 300, maxDuration: '30s',
    exec: 'spoofClient',
  },
};

const thresholdsByTest = {
  burst: { allowed_200: ['count>=100', 'count<=115'] },
  sustained: { allowed_200: ['count>=390', 'count<=410'], checks: ['rate==1'] },
  manykeys: {
    checks: ['rate==1'],
    http_req_duration: ['p(95)<50', 'p(99)<100'],
  },
  stress: {
    http_req_duration: [{ threshold: 'p(95)<500', abortOnFail: false }],
  },
  outage: { unavailable_503: ['count>0'] },
  auth: { checks: ['rate==1'] },
  spoof: { allowed_200: ['count>=90', 'count<=115'] },
};

export const options = {
  scenarios: { [TEST]: scenarios[TEST] },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    ...thresholdsByTest[TEST],
  },
};

export function setup() {
  return { runId: Date.now() % 16777216 };
}

function runIp(runId) {
  return `10.${(runId >>> 16) & 255}.${(runId >>> 8) & 255}.${runId & 255}`;
}

function uniqueIp() {
  return `${11 + (__VU >> 8)}.${__VU & 255}.${(__ITER >> 8) & 255}.${__ITER & 255}`;
}

export function singleClient(data) {
  const res = http.get(URL, { headers: { 'X-Forwarded-For': runIp(data.runId) } });
  if (res.status === 200) allowed.add(1);
  if (res.status === 429) limited.add(1);
  check(res, {
    'status is 200 or 429': (r) => r.status === 200 || r.status === 429,
    '429 has Retry-After': (r) => r.status !== 429 || r.headers['Retry-After'] !== undefined,
  });
}

export function perClient() {
  const res = http.get(URL, { headers: { 'X-Forwarded-For': uniqueIp() } });
  check(res, { 'fresh client gets 200': (r) => r.status === 200 });
}

export function outageClient() {
  const res = http.get(URL, { headers: { 'X-Forwarded-For': uniqueIp() } });
  if (res.status === 503) unavailable.add(1);
  check(res, {
    '200 or 503 only': (r) => r.status === 200 || r.status === 503,
    '503 has Retry-After': (r) => r.status !== 503 || r.headers['Retry-After'] !== undefined,
  });
}

export function authCheck(data) {
  const ip = { 'X-Forwarded-For': runIp(data.runId) };

  const bad = http.get(URL, { headers: { ...ip, 'X-API-Key': 'definitely-not-a-valid-key' } });
  check(bad, { 'invalid key gets 401': (r) => r.status === 401 });

  if (__ENV.API_KEY) {
    const good = http.get(URL, { headers: { ...ip, 'X-API-Key': __ENV.API_KEY } });
    check(good, { 'valid key gets 200': (r) => r.status === 200 });
  } else {
    console.warn('API_KEY not provided: skipped the valid-key check');
  }
}

export function spoofClient() {
  const forged = `100.${__VU & 255}.${(__ITER >> 8) & 255}.${__ITER & 255}`;
  const res = http.get(URL, { headers: { 'X-Forwarded-For': forged } });
  if (res.status === 200) allowed.add(1);
  if (res.status === 429) limited.add(1);
}