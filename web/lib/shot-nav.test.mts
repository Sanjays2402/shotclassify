// Pure tests for the recently-viewed prev/next neighbour math (F49). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  neighborShots,
  hasShotNav,
  shotNavLabel,
  neighborLabel,
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
    prevLabel: null,
    nextLabel: null,
  });
  assert.deepEqual(neighborShots(null, "a"), {
    index: -1,
    total: 0,
    prevId: null,
    nextId: null,
    prevLabel: null,
    nextLabel: null,
  });
  assert.deepEqual(neighborShots(undefined, "a"), {
    index: -1,
    total: 0,
    prevId: null,
    nextId: null,
    prevLabel: null,
    nextLabel: null,
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

// --- F62: legible neighbour labels on the chevrons -----------------------

// A ring whose entries carry real labels (not just id == label).
const LABELLED: RecentShot[] = [
  { id: "id-aaaa1111", label: "Lunch receipt", category: "receipt", viewedAt: 30 },
  { id: "id-bbbb2222", label: "", category: "code_snippet", viewedAt: 20 },
  { id: "id-cccc3333", label: "A very long label that overflows the header", category: "meme", viewedAt: 10 },
];

test("neighborShots: exposes neighbour labels for the chevrons", () => {
  const n = neighborShots(LABELLED, "id-bbbb2222");
  assert.equal(n.prevId, "id-aaaa1111");
  assert.equal(n.nextId, "id-cccc3333");
  // Newer neighbour shows its label verbatim (under the length cap).
  assert.equal(n.prevLabel, "Lunch receipt");
  // Older neighbour's long label is ellipsised to stay compact.
  assert.equal(n.nextLabel, "A very long label\u2026");
});

test("neighborShots: head / tail get one label, the absent side is null", () => {
  const head = neighborShots(LABELLED, "id-aaaa1111");
  assert.equal(head.prevLabel, null); // no newer neighbour
  assert.equal(head.nextId, "id-bbbb2222");
  // The older neighbour has a blank label, so it falls back to its short id.
  assert.equal(head.nextLabel, "id-bbbb2");
  const tail = neighborShots(LABELLED, "id-cccc3333");
  assert.equal(tail.nextLabel, null); // no older neighbour
  assert.equal(tail.prevId, "id-bbbb2222");
  assert.equal(tail.prevLabel, "id-bbbb2");
});

test("neighborLabel: prefers label, falls back to short id, ellipsises long", () => {
  assert.equal(
    neighborLabel({ id: "id-aaaa1111", label: "Receipt", category: "receipt", viewedAt: 1 }),
    "Receipt",
  );
  // Blank label -> first 8 chars of the id.
  assert.equal(
    neighborLabel({ id: "id-bbbb2222", label: "   ", category: "meme", viewedAt: 1 }),
    "id-bbbb2",
  );
  // Over the cap -> trimmed with an ellipsis (total length == cap).
  const out = neighborLabel({
    id: "x",
    label: "abcdefghijklmnopqrstuvwxyz",
    category: "other",
    viewedAt: 1,
  })!;
  assert.equal(out.length, 18);
  assert.ok(out.endsWith("\u2026"));
  // Null / undefined are tolerated.
  assert.equal(neighborLabel(null), null);
  assert.equal(neighborLabel(undefined), null);
});
