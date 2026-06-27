// Pure tests for the shot-detail rail collapse-state helper (F77). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  parseDetailRail,
  serializeDetailRail,
  isCollapsed,
  toggleSlot,
  allCollapsed,
  allExpanded,
  collapseAll,
  expandAll,
  railChordAction,
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

// --- F82: expand all / collapse all --------------------------------------

test("collapseAll: returns every known slot", () => {
  const s = collapseAll();
  assert.equal(s.size, DETAIL_RAIL_SLOTS.length);
  for (const slot of DETAIL_RAIL_SLOTS) assert.ok(s.has(slot));
});

test("expandAll: returns the empty (all-expanded) set", () => {
  assert.equal(expandAll().size, 0);
});

test("allCollapsed: true only when every slot is folded", () => {
  assert.equal(allCollapsed(collapseAll()), true);
  assert.equal(allCollapsed(new Set()), false);
  // A partial fold isn't "all collapsed".
  assert.equal(allCollapsed(new Set<DetailRailSlot>(["ocr", "frame"])), false);
});

test("allExpanded: true only for the empty set", () => {
  assert.equal(allExpanded(expandAll()), true);
  assert.equal(allExpanded(new Set<DetailRailSlot>(["ocr"])), false);
  assert.equal(allExpanded(collapseAll()), false);
});

test("collapseAll round-trips through serialize/parse as the full set", () => {
  const round = parseDetailRail(serializeDetailRail(collapseAll()));
  assert.ok(allCollapsed(round));
});

test("collapseAll / expandAll return fresh sets (new references)", () => {
  // The page swaps state by reference, so the helpers must not alias a shared
  // singleton -- two calls must be distinct objects.
  assert.notEqual(collapseAll(), collapseAll());
  assert.notEqual(expandAll(), expandAll());
});

// --- F93: Shift+E / Shift+C rail chords ----------------------------------

test("railChordAction: Shift+E expands, Shift+C collapses", () => {
  assert.equal(railChordAction({ key: "E", shiftKey: true }), "expand");
  assert.equal(railChordAction({ key: "C", shiftKey: true }), "collapse");
  // Case-insensitive on the letter (some layouts deliver lowercase + shift).
  assert.equal(railChordAction({ key: "e", shiftKey: true }), "expand");
  assert.equal(railChordAction({ key: "c", shiftKey: true }), "collapse");
});

test("railChordAction: a bare e / c (no shift) is NOT a chord", () => {
  // Critical: a plain letter must never fold the rail -- this is exactly the
  // case the generic matcher mishandles, which is why this helper exists.
  assert.equal(railChordAction({ key: "e" }), null);
  assert.equal(railChordAction({ key: "c" }), null);
  assert.equal(railChordAction({ key: "E", shiftKey: false }), null);
});

test("railChordAction: Cmd / Ctrl / Alt + Shift never fires", () => {
  assert.equal(
    railChordAction({ key: "C", shiftKey: true, metaKey: true }),
    null,
  );
  assert.equal(
    railChordAction({ key: "E", shiftKey: true, ctrlKey: true }),
    null,
  );
  assert.equal(
    railChordAction({ key: "C", shiftKey: true, altKey: true }),
    null,
  );
});

test("railChordAction: other shifted letters are not chords", () => {
  for (const k of ["A", "Z", "X", "S", "1", "?"]) {
    assert.equal(railChordAction({ key: k, shiftKey: true }), null, k);
  }
});

test("railChordAction: junk input is safe", () => {
  assert.equal(railChordAction(null as never), null);
  assert.equal(railChordAction({ key: 42 as never, shiftKey: true }), null);
  assert.equal(railChordAction({} as never), null);
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
