// Pure tests for the /keys fleet summary (F133). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { summarizeKeys, keysSummaryChips } from "./key-summary.ts";

const NOW = 1_700_000_000_000;
const DAY = 24 * 60 * 60 * 1000;

const active = (calls: number) => ({
  last_used_at: new Date(NOW - 2 * DAY).toISOString(),
  usage_count: calls,
});
const idle = (calls: number) => ({
  last_used_at: new Date(NOW - 40 * DAY).toISOString(),
  usage_count: calls,
});
const unused = () => ({ last_used_at: null, usage_count: 0 });

test("summarizeKeys: buckets and sums a mixed fleet", () => {
  const s = summarizeKeys([active(10), active(5), idle(3), unused()], NOW);
  assert.deepEqual(s, { total: 4, active: 2, idle: 1, unused: 1, totalCalls: 18 });
});

test("summarizeKeys: buckets match keyUsageStatus exactly (boundary)", () => {
  // 30d exactly is active, 31d is idle -- same boundary as the per-row pills.
  const s = summarizeKeys(
    [
      { last_used_at: new Date(NOW - 30 * DAY).toISOString(), usage_count: 1 },
      { last_used_at: new Date(NOW - 31 * DAY).toISOString(), usage_count: 1 },
    ],
    NOW,
  );
  assert.equal(s.active, 1);
  assert.equal(s.idle, 1);
});

test("summarizeKeys: a non-array input is an all-zero summary", () => {
  assert.deepEqual(summarizeKeys(null, NOW), {
    total: 0,
    active: 0,
    idle: 0,
    unused: 0,
    totalCalls: 0,
  });
  // @ts-expect-error -- wrong type on purpose.
  assert.equal(summarizeKeys("nope", NOW).total, 0);
});

test("summarizeKeys: non-finite / negative usage_count contributes 0 calls", () => {
  const s = summarizeKeys(
    [
      { last_used_at: new Date(NOW - DAY).toISOString(), usage_count: -5 },
      // @ts-expect-error -- malformed count shouldn't NaN the sum.
      { last_used_at: new Date(NOW - DAY).toISOString(), usage_count: "x" },
      active(7),
    ],
    NOW,
  );
  assert.equal(s.totalCalls, 7);
  assert.equal(s.active, 3);
});

test("summarizeKeys: skips null / non-object entries without counting them", () => {
  // @ts-expect-error -- deliberately malformed list.
  const s = summarizeKeys([active(1), null, 42], NOW);
  assert.equal(s.total, 1);
  assert.equal(s.totalCalls, 1);
});

test("keysSummaryChips: a healthy all-active fleet shows only total + calls", () => {
  const chips = keysSummaryChips(summarizeKeys([active(10), active(20)], NOW));
  assert.deepEqual(chips.map((c) => c.key), ["total", "calls"]);
  assert.equal(chips[0].label, "2 keys");
  assert.equal(chips[1].label, "30 calls");
});

test("keysSummaryChips: idle + unused buckets surface as warn / mute chips", () => {
  const chips = keysSummaryChips(summarizeKeys([active(5), idle(2), unused()], NOW));
  assert.deepEqual(chips.map((c) => c.key), ["total", "calls", "idle", "unused"]);
  assert.equal(chips.find((c) => c.key === "idle")?.tone, "warn");
  assert.equal(chips.find((c) => c.key === "unused")?.tone, "mute");
  assert.equal(chips.find((c) => c.key === "idle")?.label, "1 idle");
  assert.equal(chips.find((c) => c.key === "unused")?.label, "1 never used");
});

test("keysSummaryChips: singular key / call wording at a total of one", () => {
  const chips = keysSummaryChips(summarizeKeys([active(1)], NOW));
  assert.equal(chips[0].label, "1 key");
  assert.equal(chips[1].label, "1 call");
});

test("keysSummaryChips: a fleet with zero calls omits the calls chip", () => {
  const chips = keysSummaryChips(summarizeKeys([unused(), unused()], NOW));
  assert.deepEqual(chips.map((c) => c.key), ["total", "unused"]);
});

test("keysSummaryChips: an empty fleet yields no chips", () => {
  assert.deepEqual(keysSummaryChips(summarizeKeys([], NOW)), []);
});
