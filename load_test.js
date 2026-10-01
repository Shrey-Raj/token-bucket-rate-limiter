import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';

const allowed = new Counter('allowed_200');
const limited = new Counter('limited_429');
const unavailable = new Counter('unavailable_503');

http.setResponseCallback(http.expectedStatuses(200, 429, 503));

const URL = 'http://localhost:8000/v1/check';
const TEST = __ENV.TEST || 'burst';

const scenarios = {
  // 1000 requests on one key, as fast as possible
  burst: {
    executor: 'shared-iterations',
    vus: 100,
    iterations: 1000,
    maxDuration: '30s',
    exec: 'singleKey',
  },
  // 30 req/s for 30s on one key (900 requests)
  sustained: {
    executor: 'constant-arrival-rate',
    rate: 30,
    timeUnit: '1s',
    duration: '30s',
    preAllocatedVUs: 20,
    exec: 'singleKey',
  },
  // 200 req/s, a fresh key per request: nothing is limited, measures latency
  manykeys: {
    executor: 'constant-arrival-rate',
    rate: 200,
    timeUnit: '1s',
    duration: '30s',
    preAllocatedVUs: 50,
    exec: 'perUserKey',
  },
  // Ramp up to find where latency climbs or iterations get dropped
  stress: {
    executor: 'ramping-arrival-rate',
    startRate: 100,
    timeUnit: '1s',
    preAllocatedVUs: 200,
    maxVUs: 500,
    stages: [
      { target: 500, duration: '20s' },
      { target: 1000, duration: '20s' },
      { target: 2000, duration: '20s' },
    ],
    exec: 'perUserKey',
  },
  // Run this, then `docker compose stop redis` partway through, then `start redis`
  outage: {
    executor: 'constant-arrival-rate',
    rate: 100,
    timeUnit: '1s',
    duration: '60s',
    preAllocatedVUs: 150,
    maxVUs: 300,
    exec: 'outageKey',
  },
};

// Pass/fail rules per test. Thresholds must be flat keys (one scenario runs at a time).
const thresholdsByTest = {
  burst: {
    allowed_200: ['count>=100', 'count<=115'],
  },
  sustained: {
    allowed_200: ['count>=390', 'count<=410'],
    checks: ['rate==1'],
  },
  manykeys: {
    checks: ['rate==1'],
    http_req_duration: ['p(95)<50', 'p(99)<100'],
  },
  stress: {
    // informational: read where p95 and dropped_iterations start to climb
    http_req_duration: [{ threshold: 'p(95)<500', abortOnFail: false }],
  },
  outage: {
    // latency will rise during the outage (Redis timeouts)
    unavailable_503: ['count>0'],
  },
};

export const options = {
  scenarios: { [TEST]: scenarios[TEST] },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    ...thresholdsByTest[TEST],
  },
};

export function setup() {
  return { runId: Date.now() };
}

export function singleKey(data) {
  const res = http.get(URL, {
    headers: { 'X-API-Key': `k6_${TEST}_${data.runId}` },
  });
  if (res.status === 200) allowed.add(1);
  if (res.status === 429) limited.add(1);
  check(res, {
    'status is 200 or 429': (r) => r.status === 200 || r.status === 429,
    '429 has Retry-After': (r) => r.status !== 429 || r.headers['Retry-After'] !== undefined,
  });
}

export function perUserKey(data) {
  const res = http.get(URL, {
    headers: { 'X-API-Key': `k6_user_${data.runId}_${__VU}_${__ITER}` },
  });
  check(res, { 'fresh key gets 200': (r) => r.status === 200 });
}

// new exec function; change the outage scenario to exec: 'outageKey'
export function outageKey(data) {
  const res = http.get(URL, {
    headers: { 'X-API-Key': `k6_user_${data.runId}_${__VU}_${__ITER}` },
  });
  if (res.status === 503) unavailable.add(1);
  check(res, {
    '200 or 503 only': (r) => r.status === 200 || r.status === 503,
    '503 has Retry-After': (r) => r.status !== 503 || r.headers['Retry-After'] !== undefined,
  });
}