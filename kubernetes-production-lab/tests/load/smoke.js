// k6 smoke/load test against the docker compose stack (through the frontend
// nginx, like a real user). Ramps to 20 virtual users and holds for 30s.
//
//   docker compose up -d --build
//   docker run --rm -i --network host -e BASE_URL=http://localhost:8081 \
//     grafana/k6:1.3.0 run - < tests/load/smoke.js
//
// Fails (non-zero exit) when p95 latency >= 500ms or more than 1% of requests fail.
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8081';

export const options = {
  stages: [
    { duration: '10s', target: 20 }, // ramp up
    { duration: '30s', target: 20 }, // hold
    { duration: '5s', target: 0 },   // ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'],
    http_req_failed: ['rate<0.01'],
    checks: ['rate>0.99'],
  },
};

export default function () {
  const db = http.get(`${BASE_URL}/api/database`, { tags: { name: '/api/database' } });
  check(db, {
    'database 200': (r) => r.status === 200,
    'database message': (r) => r.body && r.body.includes('Backend and PostgreSQL are working'),
  });

  const ready = http.get(`${BASE_URL}/api/health/ready`, { tags: { name: '/api/health/ready' } });
  check(ready, { 'ready 200': (r) => r.status === 200 });

  const page = http.get(`${BASE_URL}/`, { tags: { name: '/' } });
  check(page, { 'frontend 200': (r) => r.status === 200 });

  sleep(0.5);
}
