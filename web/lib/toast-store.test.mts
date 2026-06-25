// Pure tests for the toast store. A fake scheduler gives us a deterministic
// clock so auto-dismiss is exercised without real timers or a DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  createToastStore,
  reduceAdd,
  reduceDismiss,
  droppedIds,
  resolveDuration,
  DEFAULT_DURATIONS,
  MAX_TOASTS,
  type Scheduler,
  type Toast,
} from "./toast-store.ts";

// A controllable scheduler: timers fire only when we advance the clock.
function fakeScheduler() {
  let clock = 1000;
  let nextHandle = 1;
  const pending: { handle: number; at: number; fn: () => void }[] = [];
  const sched: Scheduler = {
    now: () => clock,
    schedule(fn, ms) {
      const handle = nextHandle++;
      pending.push({ handle, at: clock + ms, fn });
      return handle;
    },
    clear(handle) {
      const i = pending.findIndex((p) => p.handle === handle);
      if (i >= 0) pending.splice(i, 1);
    },
  };
  return {
    sched,
    advance(ms: number) {
      clock += ms;
      // Fire everything due, in time order. Snapshot first because a fired
      // callback may schedule/clear more timers.
      const due = pending
        .filter((p) => p.at <= clock)
        .sort((a, b) => a.at - b.at);
      for (const d of due) {
        const i = pending.findIndex((p) => p.handle === d.handle);
        if (i >= 0) pending.splice(i, 1);
        d.fn();
      }
    },
    pendingCount: () => pending.length,
  };
}

const t = (id: string, kind: Toast["kind"] = "info"): Toast => ({
  id,
  kind,
  message: id,
  duration: 1000,
  createdAt: 0,
});

test("resolveDuration: explicit wins, 0 is sticky, default otherwise", () => {
  assert.equal(resolveDuration("success", 2000), 2000);
  assert.equal(resolveDuration("error", 0), 0);
  assert.equal(resolveDuration("info"), DEFAULT_DURATIONS.info);
  // Non-finite falls back to the per-kind default.
  assert.equal(resolveDuration("success", Number.NaN), DEFAULT_DURATIONS.success);
  // Negative clamps to 0 (sticky).
  assert.equal(resolveDuration("error", -50), 0);
});

test("reduceAdd: newest-first and capped to max", () => {
  let list: Toast[] = [];
  list = reduceAdd(list, t("a"), 3);
  list = reduceAdd(list, t("b"), 3);
  list = reduceAdd(list, t("c"), 3);
  assert.deepEqual(list.map((x) => x.id), ["c", "b", "a"]);
  list = reduceAdd(list, t("d"), 3);
  // 'a' (oldest, tail) evicted.
  assert.deepEqual(list.map((x) => x.id), ["d", "c", "b"]);
});

test("reduceDismiss: removes by id and is identity on a miss", () => {
  const list = [t("a"), t("b")];
  const next = reduceDismiss(list, "a");
  assert.deepEqual(next.map((x) => x.id), ["b"]);
  // Missing id returns the SAME reference (no needless re-render).
  assert.equal(reduceDismiss(list, "zzz"), list);
});

test("droppedIds: reports ids present in prev but absent in next", () => {
  assert.deepEqual(droppedIds([t("a"), t("b"), t("c")], [t("b")]), ["a", "c"]);
  assert.deepEqual(droppedIds([t("a")], [t("a")]), []);
});

test("store: add returns id, snapshot is newest-first", () => {
  const f = fakeScheduler();
  const store = createToastStore(f.sched);
  const id1 = store.success("saved");
  const id2 = store.error("nope");
  assert.match(id1, /^toast-/);
  assert.notEqual(id1, id2);
  assert.deepEqual(
    store.getSnapshot().map((x) => x.message),
    ["nope", "saved"],
  );
  assert.equal(store.getSnapshot()[0].kind, "error");
});

test("store: subscribers fire on add and dismiss", () => {
  const f = fakeScheduler();
  const store = createToastStore(f.sched);
  let hits = 0;
  const unsub = store.subscribe(() => hits++);
  const id = store.info("hi");
  assert.equal(hits, 1);
  store.dismiss(id);
  assert.equal(hits, 2);
  unsub();
  store.info("again");
  assert.equal(hits, 2); // no longer listening
});

test("store: auto-dismiss fires after the resolved duration", () => {
  const f = fakeScheduler();
  const store = createToastStore(f.sched);
  store.success("quick", { duration: 1000 });
  assert.equal(store.getSnapshot().length, 1);
  f.advance(500);
  assert.equal(store.getSnapshot().length, 1);
  f.advance(600); // total 1100 > 1000
  assert.equal(store.getSnapshot().length, 0);
  assert.equal(f.pendingCount(), 0);
});

test("store: duration 0 is sticky (never auto-dismisses)", () => {
  const f = fakeScheduler();
  const store = createToastStore(f.sched);
  store.error("read me", { duration: 0 });
  f.advance(1_000_000);
  assert.equal(store.getSnapshot().length, 1);
  assert.equal(f.pendingCount(), 0); // no timer was ever scheduled
});

test("store: eviction by cap clears the evicted toast's pending timer", () => {
  const f = fakeScheduler();
  const store = createToastStore(f.sched);
  // Fill past the cap; each has a live timer.
  for (let i = 0; i < MAX_TOASTS + 2; i++) {
    store.info(`n${i}`, { duration: 5000 });
  }
  assert.equal(store.getSnapshot().length, MAX_TOASTS);
  // Only the surviving toasts keep timers -- evicted ones were cleared.
  assert.equal(f.pendingCount(), MAX_TOASTS);
});

test("store: clearAll empties the stack and cancels every timer", () => {
  const f = fakeScheduler();
  const store = createToastStore(f.sched);
  store.success("a");
  store.error("b");
  store.clearAll();
  assert.equal(store.getSnapshot().length, 0);
  assert.equal(f.pendingCount(), 0);
  // A subsequent advance does nothing (no dangling callbacks).
  f.advance(100000);
  assert.equal(store.getSnapshot().length, 0);
});

test("store: dismiss is a no-op for an unknown id", () => {
  const f = fakeScheduler();
  const store = createToastStore(f.sched);
  store.info("x");
  const before = store.getSnapshot();
  store.dismiss("does-not-exist");
  assert.equal(store.getSnapshot(), before); // same reference, no churn
});
