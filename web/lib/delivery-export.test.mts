// Pure tests for the /webhooks per-row delivery export (F123). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  parsePayloadPreview,
  deliveryToExportObject,
  deliveryToJson,
  deliveryToMarkdown,
  serializeDelivery,
  DELIVERY_EXPORT_FORMATS,
  type DeliveryExportInput,
} from "./delivery-export.ts";

const FULL: DeliveryExportInput = {
  id: "dlv_abc123",
  event: "classify.completed",
  url: "https://example.com/hook",
  status: "failed",
  attempt: 3,
  http_status: 500,
  error: "upstream timeout",
  latency_ms: 1240,
  created_at: "2026-06-27T19:00:00Z",
  payload_preview: '{"id":"shot_1","category":"receipt"}',
};

test("parsePayloadPreview: valid JSON parses to a structure", () => {
  assert.deepEqual(parsePayloadPreview('{"a":1,"b":[2,3]}'), {
    a: 1,
    b: [2, 3],
  });
});

test("parsePayloadPreview: non-JSON returns the trimmed raw string", () => {
  assert.equal(parsePayloadPreview("  not json at all  "), "not json at all");
  // A truncated preview that breaks mid-object is kept raw, not dropped.
  assert.equal(parsePayloadPreview('{"id":"shot_1",'), '{"id":"shot_1",');
});

test("parsePayloadPreview: blank / null / non-string is undefined (omitted)", () => {
  assert.equal(parsePayloadPreview(""), undefined);
  assert.equal(parsePayloadPreview("   "), undefined);
  assert.equal(parsePayloadPreview(null), undefined);
  assert.equal(parsePayloadPreview(undefined), undefined);
  assert.equal(parsePayloadPreview(42 as never), undefined);
});

test("deliveryToExportObject: full row keeps every populated slot + parsed payload", () => {
  const obj = deliveryToExportObject(FULL);
  assert.deepEqual(obj, {
    id: "dlv_abc123",
    event: "classify.completed",
    url: "https://example.com/hook",
    status: "failed",
    attempt: 3,
    http_status: 500,
    error: "upstream timeout",
    latency_ms: 1240,
    created_at: "2026-06-27T19:00:00Z",
    payload: { id: "shot_1", category: "receipt" },
  });
});

test("deliveryToExportObject: omits empty optionals", () => {
  const obj = deliveryToExportObject({
    id: "dlv_x",
    event: "webhook.test",
    url: "https://e/h",
    status: "pending",
    attempt: 1,
    http_status: null,
    error: "",
    latency_ms: null,
    payload_preview: null,
  });
  assert.deepEqual(obj, {
    id: "dlv_x",
    event: "webhook.test",
    url: "https://e/h",
    status: "pending",
    attempt: 1,
  });
  // Explicitly absent, not present-with-falsy.
  assert.equal("http_status" in obj, false);
  assert.equal("error" in obj, false);
  assert.equal("latency_ms" in obj, false);
  assert.equal("payload" in obj, false);
});

test("deliveryToExportObject: a zero HTTP/latency is kept (number guard, not truthiness)", () => {
  const obj = deliveryToExportObject({
    ...FULL,
    http_status: 0,
    latency_ms: 0,
  });
  assert.equal(obj.http_status, 0);
  assert.equal(obj.latency_ms, 0);
});

test("deliveryToJson: pretty-printed, round-trips to the export object", () => {
  const json = deliveryToJson(FULL);
  assert.ok(json.includes("\n  "), "should be 2-space indented");
  assert.deepEqual(JSON.parse(json), deliveryToExportObject(FULL));
});

test("deliveryToMarkdown: heading + summary table + fenced JSON payload", () => {
  const md = deliveryToMarkdown(FULL);
  assert.ok(md.startsWith("# Delivery dlv_abc123 — classify.completed"));
  assert.ok(md.includes("| Status | `failed` |"));
  assert.ok(md.includes("| HTTP | 500 |"));
  assert.ok(md.includes("| Latency | 1240 ms |"));
  assert.ok(md.includes("| Error | upstream timeout |"));
  assert.ok(md.includes("## Payload"));
  assert.ok(md.includes("```json"));
  // Pretty-printed parsed payload, not the raw one-line string.
  assert.ok(md.includes('"category": "receipt"'));
});

test("deliveryToMarkdown: raw non-JSON preview prints verbatim in the fence", () => {
  const md = deliveryToMarkdown({ ...FULL, payload_preview: "truncated..." });
  assert.ok(md.includes("```json\ntruncated...\n```"));
});

test("deliveryToMarkdown: no payload section when preview is blank", () => {
  const md = deliveryToMarkdown({ ...FULL, payload_preview: "" });
  assert.equal(md.includes("## Payload"), false);
});

test("deliveryToMarkdown: pipes in a value are escaped so the table stays intact", () => {
  const md = deliveryToMarkdown({
    ...FULL,
    error: "a | b | c",
    payload_preview: null,
  });
  assert.ok(md.includes("| Error | a \\| b \\| c |"));
});

test("DELIVERY_EXPORT_FORMATS: exactly JSON + Markdown, no CSV", () => {
  assert.deepEqual(
    DELIVERY_EXPORT_FORMATS.map((f) => f.key),
    ["json", "markdown"],
  );
});

test("serializeDelivery: dispatches by key", () => {
  assert.equal(serializeDelivery("json", FULL), deliveryToJson(FULL));
  assert.equal(serializeDelivery("markdown", FULL), deliveryToMarkdown(FULL));
});
