// Pure tests for the recently-viewed prev/next neighbour math (F49). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  neighborShots,
  hasShotNav,
  shotNavLabel,
} from "./shot-nav.ts";
import type { RecentShot } from "./recent-shots.ts";

// Build a newest-first ring of ids with descending viewedAt.
function ring(ids: string[]): RecentShot[] {
  return ids.map((id, i) => ({
    id,
    label: id,
    category: "receipt",
    viewedAt: 1_000_000 - i,
  }));
}

const R = ring(["a", "b", "c", "d"]); // a newest ... d oldest

test("neighborShots: a middle shot has both neighbours", () => {
  const n = neighborShots(R, "b");
  assert.equal(n.index, 1);
  assert.equal(n.total, 4);
  assert.equal(n.prevId, "a"); // newer (toward head)
  assert.equal(n.nextId, "c"); // older (toward tail)
});

test("neighborShots: the head has no newer neighbour", () => {
  const n = neighborShots(R, "a");
  assert.equal(n.index, 0);
  assert.equal(n.prevId, null);
  assert.equal(n.nextId, "b");
});

test("neighborShots: the tail has no older neighbour", () => {
  const n = neighborShots(R, "d");
  assert.equal(n.index, 3);
  assert.equal(n.prevId, "c");
  assert.equal(n.nextId, null);
});

test("neighborShots: a shot absent from the ring yields index -1, no nav", () => {
  const n = neighborShots(R, "zzz");
  assert.equal(n.index, -1);
  assert.equal(n.total, 4);
  assert.equal(n.prevId, null);
  assert.equal(n.nextId, null);
  assert.equal(hasShotNav(n), false);
});

test("neighborShots: single-entry ring has no neighbours", () => {
  const n = neighborShots(ring(["solo"]), "solo");
  assert.equal(n.index, 0);
  assert.equal(n.total, 1);
  assert.equal(n.prevId, null);
  assert.equal(n.nextId, null);
  assert.equal(hasShotNav(n), false);
});

test("neighborShots: defensive against empty / non-array / blank id", () => {
  assert.deepEqual(neighborShots([], "a"), {
    index: -1,
    total: 0,
    prevId: null,
    nextId: null,
  });
  assert.deepEqual(neighborShots(null, "a"), {
    index: -1,
    total: 0,
    prevId: null,
    nextId: null,
  });
  assert.deepEqual(neighborShots(undefined, "a"), {
    index: -1,
    total: 0,
    prevId: null,
    nextId: null,
  });
  const n = neighborShots(R, "   ");
  assert.equal(n.index, -1);
  assert.equal(n.total, 4);
});

test("neighborShots: current id is trimmed before lookup", () => {
  const n = neighborShots(R, "  b  ");
  assert.equal(n.index, 1);
  assert.equal(n.prevId, "a");
  assert.equal(n.nextId, "c");
});

test("hasShotNav: true when either neighbour exists", () => {
  assert.equal(hasShotNav(neighborShots(R, "a")), true); // next only
  assert.equal(hasShotNav(neighborShots(R, "d")), true); // prev only
  assert.equal(hasShotNav(neighborShots(R, "b")), true); // both
});

test("shotNavLabel: 1-based position, empty when absent", () => {
  assert.equal(shotNavLabel(neighborShots(R, "a")), "1 of 4");
  assert.equal(shotNavLabel(neighborShots(R, "c")), "3 of 4");
  assert.equal(shotNavLabel(neighborShots(R, "missing")), "");
  assert.equal(shotNavLabel(neighborShots([], "a")), "");
});
