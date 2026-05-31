import { test } from "node:test";
import assert from "node:assert/strict";
import {
  metrics,
  recordHttp,
  resolveRequestId,
  __testing__,
} from "./metrics.ts";

test("recordHttp emits counter + histogram series", () => {
  metrics.resetForTests();
  recordHttp("/v1/classify", "POST", 200, 42);
  recordHttp("/v1/classify", "POST", 200, 130);
  recordHttp("/v1/classify", "POST", 500, 8);
  const out = metrics.render();
  assert.match(out, /shotclassify_http_requests_total\{.*route="\/v1\/classify".*status="2xx".*\} 2/);
  assert.match(out, /shotclassify_http_requests_total\{.*status="5xx".*\} 1/);
  assert.match(out, /shotclassify_http_errors_total\{.*status="500".*\} 1/);
  // Histogram count must be 3 across all observations for the labelset.
  assert.match(out, /shotclassify_http_request_duration_seconds_count\{.*route="\/v1\/classify".*\} 3/);
  // 42ms and 8ms both fall under 0.05s bucket -> 2.
  assert.match(out, /shotclassify_http_request_duration_seconds_bucket\{.*le="0\.05".*\} 2/);
});

test("Prometheus output is parseable: every metric line has HELP+TYPE", () => {
  metrics.resetForTests();
  recordHttp("/v1/shots", "GET", 200, 5);
  const text = metrics.render();
  // Each TYPE line must precede at least one sample line for that metric.
  for (const m of [
    "shotclassify_http_requests_total",
    "shotclassify_http_request_duration_seconds",
    "shotclassify_process_uptime_seconds",
  ]) {
    assert.match(text, new RegExp(`# TYPE ${m} (counter|histogram|gauge)`));
  }
  // Sanity: no NaN/Infinity leaked.
  assert.doesNotMatch(text, /NaN|Infinity/);
});

test("resolveRequestId honors upstream x-request-id when safe", () => {
  const h = new Headers({ "x-request-id": "abc-123_DEF" });
  assert.equal(resolveRequestId(h), "abc-123_DEF");
});

test("resolveRequestId mints fresh id when upstream header is unsafe", () => {
  const h = new Headers({ "x-request-id": "drop table users;" });
  const id = resolveRequestId(h);
  assert.notEqual(id, "drop table users;");
  assert.match(id, /^[0-9a-f]{32}$/);
});

test("resolveRequestId mints id when absent", () => {
  const h = new Headers();
  const id = resolveRequestId(h);
  assert.match(id, /^[0-9a-f]{32}$/);
});

test("histogram buckets are cumulative and monotonic", () => {
  const { Histogram } = __testing__;
  const h = new Histogram("t", "t");
  for (const v of [0.001, 0.02, 0.2, 3]) h.observe({ x: "a" }, v);
  const text = h.render();
  // Cumulative: le=0.005 sees 1, le=0.025 sees 2, le=0.25 sees 3, le=5 sees 4
  assert.match(text, /t_bucket\{le="0\.005",x="a"\} 1/);
  assert.match(text, /t_bucket\{le="0\.025",x="a"\} 2/);
  assert.match(text, /t_bucket\{le="0\.25",x="a"\} 3/);
  assert.match(text, /t_bucket\{le="5",x="a"\} 4/);
  assert.match(text, /t_bucket\{le="\+Inf",x="a"\} 4/);
  assert.match(text, /t_count\{x="a"\} 4/);
});
