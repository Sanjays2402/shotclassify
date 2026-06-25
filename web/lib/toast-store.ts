// Toast notification store. Framework-free so the reducer + scheduling logic
// is unit-testable without jsdom. The codebase currently rolls a bespoke
// `flash` / `bulkFlash` state machine on every page that wants to confirm an
// action (shots bulk ops, webhooks, saved views, admin seats). This is the
// canonical, app-wide replacement: an imperative `toast.success(...)` API
// backed by a tiny external store the <Toaster> subscribes to.
//
// Design notes:
// - The store is built by `createToastStore(scheduler)` so tests can inject a
//   fake clock + scheduler and assert auto-dismiss deterministically. The
//   browser singleton at the bottom wires in real Date.now / setTimeout.
// - `getSnapshot` returns a stable reference between mutations so it composes
//   with React 18's `useSyncExternalStore` without tearing.
// - Newest toast renders on top; the list is capped so a runaway loop can't
//   paper the screen. Dropped toasts have their pending timers cleared.

export type ToastKind = "success" | "error" | "info";

export type Toast = {
  id: string;
  kind: ToastKind;
  message: string;
  // ms until auto-dismiss. 0 (or negative) means the toast is sticky and only
  // leaves on an explicit dismiss / user click.
  duration: number;
  createdAt: number;
};

export type ToastInput = {
  kind?: ToastKind;
  message: string;
  // Override the default per-kind auto-dismiss. Pass 0 for a sticky toast.
  duration?: number;
};

export type ToastOptions = Omit<ToastInput, "kind" | "message">;

// Errors linger longest (the user likely needs to read + act); successes are
// quick confirmations; info sits in between.
export const DEFAULT_DURATIONS: Record<ToastKind, number> = {
  success: 3500,
  info: 4500,
  error: 6500,
};

// Hard cap on simultaneously visible toasts. Beyond this, the oldest is
// evicted so the stack stays readable in the bottom-right corner.
export const MAX_TOASTS = 4;

// Resolve the effective duration for a toast: an explicit `duration` (incl. 0
// for sticky) always wins; otherwise fall back to the per-kind default.
export function resolveDuration(
  kind: ToastKind,
  duration?: number,
): number {
  if (typeof duration === "number" && Number.isFinite(duration)) {
    return Math.max(0, Math.trunc(duration));
  }
  return DEFAULT_DURATIONS[kind];
}

// Pure: append a toast to the front (newest-first) and evict from the tail
// down to `max`. Returns a NEW array so the store's snapshot reference flips.
export function reduceAdd(
  list: Toast[],
  toast: Toast,
  max = MAX_TOASTS,
): Toast[] {
  const next = [toast, ...list];
  if (next.length <= max) return next;
  return next.slice(0, max);
}

// Pure: drop a toast by id. Returns the same array reference when the id is
// absent so callers can skip a needless re-render.
export function reduceDismiss(list: Toast[], id: string): Toast[] {
  if (!list.some((t) => t.id === id)) return list;
  return list.filter((t) => t.id !== id);
}

// Compute which ids vanished between two snapshots -- used to clear the timers
// of toasts that were evicted by the cap so we don't leak pending callbacks.
export function droppedIds(prev: Toast[], next: Toast[]): string[] {
  const keep = new Set(next.map((t) => t.id));
  return prev.filter((t) => !keep.has(t.id)).map((t) => t.id);
}

export type Scheduler = {
  now: () => number;
  schedule: (fn: () => void, ms: number) => unknown;
  clear: (handle: unknown) => void;
};

export type ToastStore = {
  getSnapshot: () => Toast[];
  subscribe: (listener: () => void) => () => void;
  add: (input: ToastInput) => string;
  dismiss: (id: string) => void;
  clearAll: () => void;
  success: (message: string, opts?: ToastOptions) => string;
  error: (message: string, opts?: ToastOptions) => string;
  info: (message: string, opts?: ToastOptions) => string;
};

const EMPTY: Toast[] = [];

export function createToastStore(scheduler: Scheduler): ToastStore {
  let list: Toast[] = EMPTY;
  const listeners = new Set<() => void>();
  const timers = new Map<string, unknown>();
  let seq = 0;

  function emit() {
    for (const fn of listeners) fn();
  }

  function commit(next: Toast[]) {
    const dropped = droppedIds(list, next);
    for (const id of dropped) {
      const h = timers.get(id);
      if (h !== undefined) {
        scheduler.clear(h);
        timers.delete(id);
      }
    }
    if (next === list) return;
    list = next;
    emit();
  }

  function dismiss(id: string) {
    const h = timers.get(id);
    if (h !== undefined) {
      scheduler.clear(h);
      timers.delete(id);
    }
    commit(reduceDismiss(list, id));
  }

  function add(input: ToastInput): string {
    const kind = input.kind ?? "info";
    const duration = resolveDuration(kind, input.duration);
    const stamp = scheduler.now();
    const id = `toast-${++seq}-${stamp}`;
    const toast: Toast = {
      id,
      kind,
      message: input.message,
      duration,
      createdAt: stamp,
    };
    commit(reduceAdd(list, toast));
    // Only schedule auto-dismiss for toasts that survived the cap.
    if (duration > 0 && list.some((t) => t.id === id)) {
      const handle = scheduler.schedule(() => dismiss(id), duration);
      timers.set(id, handle);
    }
    return id;
  }

  function clearAll() {
    for (const h of timers.values()) scheduler.clear(h);
    timers.clear();
    commit(EMPTY);
  }

  return {
    getSnapshot: () => list,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    add,
    dismiss,
    clearAll,
    success: (message, opts) => add({ ...opts, kind: "success", message }),
    error: (message, opts) => add({ ...opts, kind: "error", message }),
    info: (message, opts) => add({ ...opts, kind: "info", message }),
  };
}

// Stable server snapshot for useSyncExternalStore -- always the same empty
// reference so SSR renders nothing and hydration doesn't warn.
export const serverSnapshot: Toast[] = EMPTY;

// Browser singleton. Every `toast.success(...)` call site shares this store;
// the single <Toaster> mounted in the root layout renders it.
export const toast: ToastStore = createToastStore({
  now: () => Date.now(),
  schedule: (fn, ms) => setTimeout(fn, ms),
  clear: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
});
