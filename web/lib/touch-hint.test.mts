// Pure tests for the notifications touch-affordance hint state (F126). The
// shouldShowTouchHint truth table is DOM-free; the environment probes
// (isCoarsePointer / storage) are tested against a stubbed global window.
import test from "node:test";
import assert from "node:assert/strict";

import {
  shouldShowTouchHint,
  isCoarsePointer,
  hasSeenTouchHint,
  markTouchHintSeen,
  TOUCH_HINT_SEEN_KEY,
} from "./touch-hint.ts";

// --- shouldShowTouchHint (pure truth table) -------------------------------

test("shouldShowTouchHint: coarse pointer, unseen, with rows -> true", () => {
  assert.equal(shouldShowTouchHint(true, false, 3), true);
  assert.equal(shouldShowTouchHint(true, false, 1), true);
});

test("shouldShowTouchHint: a fine (mouse) pointer never shows the hint", () => {
  assert.equal(shouldShowTouchHint(false, false, 3), false);
});

test("shouldShowTouchHint: already-seen never re-shows", () => {
  assert.equal(shouldShowTouchHint(true, true, 3), false);
});

test("shouldShowTouchHint: no rows -> nothing to dismiss, hidden", () => {
  assert.equal(shouldShowTouchHint(true, false, 0), false);
  assert.equal(shouldShowTouchHint(true, false, -2), false);
  assert.equal(shouldShowTouchHint(true, false, NaN), false);
});

// --- environment probes (stubbed window) ----------------------------------

// Swap in a fake window for one test body, always restoring the original.
function withWindow(fake: unknown, fn: () => void): void {
  const g = globalThis as { window?: unknown };
  const had = "window" in g;
  const prev = g.window;
  g.window = fake;
  try {
    fn();
  } finally {
    if (had) g.window = prev;
    else delete g.window;
  }
}

test("isCoarsePointer: true when (pointer: coarse) matches", () => {
  withWindow(
    {
      matchMedia: (q: string) => ({ matches: q === "(pointer: coarse)" }),
    },
    () => {
      assert.equal(isCoarsePointer(), true);
    },
  );
});

test("isCoarsePointer: false for a fine pointer", () => {
  withWindow({ matchMedia: () => ({ matches: false }) }, () => {
    assert.equal(isCoarsePointer(), false);
  });
});

test("isCoarsePointer: no matchMedia / throwing matchMedia fails closed", () => {
  withWindow({}, () => {
    assert.equal(isCoarsePointer(), false);
  });
  withWindow(
    {
      matchMedia: () => {
        throw new Error("blocked");
      },
    },
    () => {
      assert.equal(isCoarsePointer(), false);
    },
  );
});

test("hasSeenTouchHint / markTouchHintSeen: round-trip through storage", () => {
  const store = new Map<string, string>();
  withWindow(
    {
      localStorage: {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => void store.set(k, v),
        removeItem: (k: string) => void store.delete(k),
      },
    },
    () => {
      assert.equal(hasSeenTouchHint(), false);
      markTouchHintSeen();
      assert.equal(store.get(TOUCH_HINT_SEEN_KEY), "1");
      assert.equal(hasSeenTouchHint(), true);
    },
  );
});

test("hasSeenTouchHint: storage that throws fails open as seen (don't nag)", () => {
  withWindow(
    {
      localStorage: {
        getItem: () => {
          throw new Error("private mode");
        },
      },
    },
    () => {
      assert.equal(hasSeenTouchHint(), true);
    },
  );
});

test("markTouchHintSeen: a throwing setItem is swallowed (no-op)", () => {
  withWindow(
    {
      localStorage: {
        setItem: () => {
          throw new Error("quota");
        },
      },
    },
    () => {
      assert.doesNotThrow(() => markTouchHintSeen());
    },
  );
});
