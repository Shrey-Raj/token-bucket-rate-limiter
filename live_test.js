import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';

const allowed = new Counter('allowed_200');
const limited = new Counter('limited_429');

http.setResponseCallback(http.expectedStatuses(200, 429));

const BASE_URL = __ENV.BASE_URL;
const API_KEY = __ENV.API_KEY;

export const options = {
  scenarios: {
    burst: {
      executor: 'shared-iterations',
      vus: 20,
      iterations: 300,
      maxDuration: '60s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    allowed_200: ['count>=100'],
    limited_429: ['count>0'],
  },
};

export default function () {
  const res = http.get(`${BASE_URL}/v1/check`, { headers: { 'X-API-Key': API_KEY } });
  if (res.status === 200) allowed.add(1);
  if (res.status === 429) limited.add(1);
  check(res, {
    'status is 200 or 429': (r) => r.status === 200 || r.status === 429,
    'rate limit headers present': (r) => r.headers['X-Ratelimit-Limit'] !== undefined,
    '429 has Retry-After': (r) => r.status !== 429 || r.headers['Retry-After'] !== undefined,
  });
}