// Pure tests for the /batch class-distribution tally (this tick). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  classDistribution,
  distinctClassCount,
  classSliceTitle,
  type ClassifiedRow,
} from "./batch-classes.ts";

const row = (status: string, primary?: ClassifiedRow["primary"]): ClassifiedRow => ({
  status,
  primary,
});

test("classDistribution: counts done rows by class, count-desc", () => {
  const rows: ClassifiedRow[] = [
    row("done", "receipt"),
    row("done", "chat_screenshot"),
    row("done", "receipt"),
    row("done", "receipt"),
    row("done", "chat_screenshot"),
  ];
  const d = classDistribution(rows);
  assert.deepEqual(
    d.map((s) => [s.category, s.count]),
    [
      ["receipt", 3],
      ["chat_screenshot", 2],
    ],
  );
});

test("classDistribution: share percents over the classified total", () => {
  const d = classDistribution([
    row("done", "receipt"),
    row("done", "receipt"),
    row("done", "code_snippet"),
    row("done", "chat_screenshot"),
  ]);
  const receipt = d.find((s) => s.category === "receipt")!;
  assert.equal(receipt.count, 2);
  assert.equal(receipt.sharePct, 50);
});

test("classDistribution: skips non-done and primary-less rows", () => {
  const d = classDistribution([
    row("done", "receipt"),
    row("error"),
    row("queued"),
    row("running"),
    row("done", undefined),
  ]);
  assert.deepEqual(d.map((s) => s.category), ["receipt"]);
  // Share is over the ONE real classification, not the five rows.
  assert.equal(d[0].sharePct, 100);
});

test("classDistribution: label resolves to the human name", () => {
  const d = classDistribution([row("done", "ui_mockup")]);
  assert.equal(d[0].label, "UI mockup");
});

test("classDistribution: empty / non-array yields []", () => {
  assert.deepEqual(classDistribution([]), []);
  assert.deepEqual(classDistribution(null), []);
  assert.deepEqual(classDistribution(undefined), []);
  assert.deepEqual(classDistribution([row("queued"), row("error")]), []);
});

test("classDistribution: same-count ties keep first-seen order", () => {
  const d = classDistribution([
    row("done", "chat_screenshot"),
    row("done", "receipt"),
  ]);
  // Both count 1 -- chat appeared first in the table, so it leads.
  assert.deepEqual(d.map((s) => s.category), ["chat_screenshot", "receipt"]);
});

test("distinctClassCount: counts the slices", () => {
  const d = classDistribution([
    row("done", "receipt"),
    row("done", "code_snippet"),
    row("done", "receipt"),
  ]);
  assert.equal(distinctClassCount(d), 2);
  assert.equal(distinctClassCount([]), 0);
});

test("classSliceTitle: names label, count and share", () => {
  const d = classDistribution([
    row("done", "receipt"),
    row("done", "receipt"),
    row("done", "chat_screenshot"),
  ]);
  assert.equal(classSliceTitle(d[0]), "Receipt: 2 (67%)");
});
