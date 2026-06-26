// Pure tests for the shot-detail rail collapse-state helper (F77). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  parseDetailRail,
  serializeDetailRail,
  isCollapsed,
  toggleSlot,
  readDetailRail,
  writeDetailRail,
  DETAIL_RAIL_SLOTS,
  DETAIL_RAIL_STORAGE_KEY,
  type DetailRailSlot,
} from "./detail-rail.ts";

test("DETAIL_RAIL constants are stable", () => {
  assert.equal(DETAIL_RAIL_STORAGE_KEY, "shotclassify.detail.rail.collapsed");
  assert.deepEqual(
    [...DETAIL_RAIL_SLOTS],
    ["ocr", "rationale", "umpire", "tags", "frame"],
  );
});

test("parseDetailRail: empty / junk yields an all-expanded (empty) set", () => {
  for (const v of [null, undefined, "", "   ", 42 as never]) {
    assert.equal(parseDetailRail(v as never).size, 0, JSON.stringify(v));
  }
});

test("parseDetailRail: keeps only known slots, case / space tolerant", () => {
  const s = parseDetailRail(" OCR , rationale ,bogus,, FRAME ");
  assert.ok(s.has("ocr"));
  assert.ok(s.has("rationale"));
  assert.ok(s.has("frame"));
  assert.ok(!s.has("umpire"));
  // "bogus" and the empty tokens are dropped.
  assert.equal(s.size, 3);
});

test("parseDetailRail: duplicates collapse to one entry", () => {
  const s = parseDetailRail("ocr,ocr,ocr");
  assert.equal(s.size, 1);
  assert.ok(s.has("ocr"));
});

test("serializeDetailRail: canonical slot order regardless of insertion order", () => {
  // Insert out of order; the serialized blob follows DETAIL_RAIL_SLOTS order.
  const s = new Set<DetailRailSlot>(["frame", "ocr", "umpire"]);
  assert.equal(serializeDetailRail(s), "ocr,umpire,frame");
});

test("serializeDetailRail: empty set serializes to the empty string", () => {
  assert.equal(serializeDetailRail(new Set()), "");
});

test("serialize -> parse round-trips every subset shape", () => {
  for (const slots of [
    [] as DetailRailSlot[],
    ["ocr"],
    ["ocr", "frame"],
    [...DETAIL_RAIL_SLOTS],
  ] as DetailRailSlot[][]) {
    const s = new Set<DetailRailSlot>(slots);
    const round = parseDetailRail(serializeDetailRail(s));
    assert.deepEqual(
      Array.from(round).sort(),
      Array.from(s).sort(),
      JSON.stringify(slots),
    );
  }
});

test("isCollapsed: true only for slots in the set", () => {
  const s = new Set<DetailRailSlot>(["rationale"]);
  assert.equal(isCollapsed(s, "rationale"), true);
  assert.equal(isCollapsed(s, "ocr"), false);
});

test("toggleSlot: flips collapsed-ness immutably", () => {
  const a = new Set<DetailRailSlot>();
  const b = toggleSlot(a, "ocr");
  assert.notEqual(a, b, "returns a new set, doesn't mutate the input");
  assert.equal(a.size, 0, "input untouched");
  assert.ok(b.has("ocr"));
  const c = toggleSlot(b, "ocr");
  assert.ok(!c.has("ocr"), "second toggle expands again");
});

test("toggleSlot: an unknown slot is ignored (copy unchanged)", () => {
  const a = new Set<DetailRailSlot>(["ocr"]);
  const b = toggleSlot(a, "bogus" as never);
  assert.deepEqual([...b], ["ocr"]);
});

test("readDetailRail: SSR (no window) returns an empty set", () => {
  assert.equal(typeof (globalThis as { window?: unknown }).window, "undefined");
  assert.equal(readDetailRail().size, 0);
});

test("read/writeDetailRail: round-trip through a stubbed localStorage", () => {
  const store = new Map<string, string>();
  const g = globalThis as { window?: unknown };
  g.window = {
    localStorage: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    },
  };
  try {
    assert.equal(readDetailRail().size, 0);
    writeDetailRail(new Set<DetailRailSlot>(["ocr", "frame"]));
    assert.equal(store.get(DETAIL_RAIL_STORAGE_KEY), "ocr,frame");
    const back = readDetailRail();
    assert.ok(back.has("ocr") && back.has("frame"));
    // A corrupt stored value coerces back to an empty (all-expanded) set.
    store.set(DETAIL_RAIL_STORAGE_KEY, "garbage,more-garbage");
    assert.equal(readDetailRail().size, 0);
  } finally {
    delete g.window;
  }
});

test("writeDetailRail: a throwing storage is swallowed", () => {
  const g = globalThis as { window?: unknown };
  g.window = {
    localStorage: {
      setItem: () => {
        throw new Error("quota");
      },
    },
  };
  try {
    assert.doesNotThrow(() =>
      writeDetailRail(new Set<DetailRailSlot>(["ocr"])),
    );
  } finally {
    delete g.window;
  }
});
