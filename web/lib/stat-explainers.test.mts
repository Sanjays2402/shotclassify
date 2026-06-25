// Pure tests for the /stats KPI explainer content + window helpers (F34).
import test from "node:test";
import assert from "node:assert/strict";

import {
  STAT_EXPLAINERS,
  statExplainer,
  windowLabel,
  scopeNote,
  type StatId,
} from "./stat-explainers.ts";

const IDS: StatId[] = ["lifetime", "mean_confidence", "p95_latency", "corrections"];

test("STAT_EXPLAINERS covers exactly the four KPI cards", () => {
  assert.deepEqual(Object.keys(STAT_EXPLAINERS).sort(), [...IDS].sort());
});

test("every explainer has non-empty copy and a known scope", () => {
  for (const id of IDS) {
    const e = STAT_EXPLAINERS[id];
    assert.equal(e.id, id, "id field matches its key");
    assert.ok(e.title.length > 0);
    assert.ok(e.definition.length > 0);
    assert.ok(e.computed.length > 0);
    assert.ok(e.scope === "window" || e.scope === "lifetime");
  }
});

test("statExplainer accessor returns the matching entry", () => {
  assert.equal(statExplainer("p95_latency").title, "P95 latency");
  assert.equal(statExplainer("lifetime").scope, "lifetime");
});

test("lifetime is the only all-time metric; the rest are windowed", () => {
  assert.equal(STAT_EXPLAINERS.lifetime.scope, "lifetime");
  assert.equal(STAT_EXPLAINERS.mean_confidence.scope, "window");
  assert.equal(STAT_EXPLAINERS.p95_latency.scope, "window");
  assert.equal(STAT_EXPLAINERS.corrections.scope, "window");
});

test("windowLabel: whole-day spans collapse to Nd, 24h stays 24h", () => {
  assert.equal(windowLabel(24), "24h");
  assert.equal(windowLabel(24 * 7), "7d");
  assert.equal(windowLabel(24 * 30), "30d");
});

test("windowLabel: sub-day spans stay in hours; junk -> generic phrase", () => {
  assert.equal(windowLabel(6), "6h");
  assert.equal(windowLabel(1), "1h");
  assert.equal(windowLabel(0), "this window");
  assert.equal(windowLabel(-5), "this window");
  assert.equal(windowLabel(NaN), "this window");
});

test("scopeNote: lifetime says all-time; windowed names the window", () => {
  const life = scopeNote(STAT_EXPLAINERS.lifetime, 24 * 7);
  assert.match(life, /all-time/i);
  // The window length should NOT leak into the lifetime note.
  assert.doesNotMatch(life, /7d/);

  const win = scopeNote(STAT_EXPLAINERS.mean_confidence, 24 * 7);
  assert.match(win, /7d/);
  assert.match(win, /switch windows/i);
});
