// Pure tests for the /keys activity helpers (F131). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  keyRelativeLabel,
  keyUsageStatus,
  keyStatusLabel,
  keyStatusHint,
  KEY_IDLE_AFTER_MS,
} from "./key-activity.ts";

const NOW = 1_700_000_000_000;
const DAY = 24 * 60 * 60 * 1000;

test("keyRelativeLabel: a recent ISO renders the shared relative phrasing", () => {
  assert.equal(keyRelativeLabel(new Date(NOW - 3 * DAY).toISOString(), NOW), "3d ago");
  assert.equal(keyRelativeLabel(new Date(NOW - 5 * 60_000).toISOString(), NOW), "5m ago");
});

test("keyRelativeLabel: null / blank / unparseable yields an empty string", () => {
  assert.equal(keyRelativeLabel(null, NOW), "");
  assert.equal(keyRelativeLabel(undefined, NOW), "");
  assert.equal(keyRelativeLabel("   ", NOW), "");
  assert.equal(keyRelativeLabel("not a date", NOW), "");
});

test("keyUsageStatus: never-used keys read as unused", () => {
  assert.equal(keyUsageStatus({ last_used_at: null, usage_count: 0 }, NOW), "unused");
  assert.equal(keyUsageStatus({ last_used_at: "", usage_count: 0 }, NOW), "unused");
  assert.equal(keyUsageStatus({ usage_count: 0 }, NOW), "unused");
});

test("keyUsageStatus: used within 30 days is active, beyond is idle", () => {
  assert.equal(keyUsageStatus({ last_used_at: new Date(NOW - 2 * DAY).toISOString() }, NOW), "active");
  assert.equal(keyUsageStatus({ last_used_at: new Date(NOW - 29 * DAY).toISOString() }, NOW), "active");
  assert.equal(keyUsageStatus({ last_used_at: new Date(NOW - 31 * DAY).toISOString() }, NOW), "idle");
});

test("keyUsageStatus: the boundary is exclusive -- exactly 30d is still active", () => {
  const at = new Date(NOW - KEY_IDLE_AFTER_MS).toISOString();
  assert.equal(keyUsageStatus({ last_used_at: at }, NOW), "active");
  const justOver = new Date(NOW - KEY_IDLE_AFTER_MS - 1000).toISOString();
  assert.equal(keyUsageStatus({ last_used_at: justOver }, NOW), "idle");
});

test("keyUsageStatus: a future (clock-skewed) timestamp counts as active", () => {
  assert.equal(keyUsageStatus({ last_used_at: new Date(NOW + DAY).toISOString() }, NOW), "active");
});

test("keyUsageStatus: an unparseable timestamp degrades to unused", () => {
  assert.equal(keyUsageStatus({ last_used_at: "garbage" }, NOW), "unused");
});

test("keyStatusLabel: only the exceptional states get a pill word", () => {
  assert.equal(keyStatusLabel("unused"), "never used");
  assert.equal(keyStatusLabel("idle"), "idle");
  assert.equal(keyStatusLabel("active"), null);
});

test("keyStatusHint: every status has a non-empty sentence", () => {
  assert.match(keyStatusHint("unused"), /never authenticated/);
  assert.match(keyStatusHint("idle"), /over 30 days/);
  assert.match(keyStatusHint("active"), /recently/);
});
