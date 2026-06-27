// Per-slot collapse state for the shot-detail right rail (F77). The detail
// page's right column stacks OCR / rationale / umpire / tags / frame; on a
// long shot that's a lot to scroll past. This lets each subsection fold up,
// and remembers which are collapsed across visits so a user who only cares
// about, say, the rationale can keep the rest tucked away.
//
// Pure + DOM-free so parse / serialize / toggle is unit-testable; the
// <CollapsibleSection> component is a thin renderer over this. State is the
// SET of collapsed slot keys (everything not listed is expanded -- the
// friendly default where a brand-new visitor sees everything open).

// The known foldable slots, in the order they stack in the rail. A persisted
// value naming an unknown slot is dropped on parse so a future-schema or
// corrupt blob can never collapse a section that doesn't exist.
export const DETAIL_RAIL_SLOTS = [
  "ocr",
  "rationale",
  "umpire",
  "tags",
  "frame",
] as const;

export type DetailRailSlot = (typeof DETAIL_RAIL_SLOTS)[number];

export const DETAIL_RAIL_STORAGE_KEY = "shotclassify.detail.rail.collapsed";

// The collapse state is just the set of collapsed slot keys.
export type DetailRailState = Set<DetailRailSlot>;

function isKnownSlot(s: string): s is DetailRailSlot {
  return (DETAIL_RAIL_SLOTS as readonly string[]).includes(s);
}

// Parse a persisted value into the set of collapsed slots. Accepts a
// comma-separated list (the serialized form) and tolerates whitespace,
// casing, duplicates, and unknown tokens -- only known slots survive, so the
// rail always renders a valid state. null / undefined / junk -> empty set
// (everything expanded).
export function parseDetailRail(
  raw: string | null | undefined,
): DetailRailState {
  const out = new Set<DetailRailSlot>();
  if (typeof raw !== "string") return out;
  for (const tokenRaw of raw.split(",")) {
    const t = tokenRaw.trim().toLowerCase();
    if (t && isKnownSlot(t)) out.add(t);
  }
  return out;
}

// Serialize back to the stored string: known slots only, in canonical
// DETAIL_RAIL_SLOTS order (so the blob is stable regardless of insertion
// order -- a clean round-trip and no spurious storage churn). Empty set ->
// "" so "nothing collapsed" persists explicitly.
export function serializeDetailRail(state: DetailRailState): string {
  return DETAIL_RAIL_SLOTS.filter((slot) => state.has(slot)).join(",");
}

// Is a given slot currently collapsed? An unknown slot is never collapsed.
export function isCollapsed(
  state: DetailRailState,
  slot: DetailRailSlot,
): boolean {
  return state.has(slot);
}

// Return a NEW state with the slot's collapsed-ness flipped (immutable so
// React state updates stay clean). An unknown slot is ignored, returning a
// copy unchanged.
export function toggleSlot(
  state: DetailRailState,
  slot: DetailRailSlot,
): DetailRailState {
  const next = new Set(state);
  if (!isKnownSlot(slot)) return next;
  if (next.has(slot)) next.delete(slot);
  else next.add(slot);
  return next;
}

// --- Expand all / Collapse all (F82) -------------------------------------
// A header affordance on the rail folds or unfolds every section at once.
// These pure helpers back it: collapseAll() returns the full set, expandAll()
// returns the empty set, and allCollapsed() / allExpanded() let the control
// pick which action to offer (and disable the no-op one).

// True when EVERY known slot is collapsed -- the "Expand all" state.
export function allCollapsed(state: DetailRailState): boolean {
  return DETAIL_RAIL_SLOTS.every((slot) => state.has(slot));
}

// True when nothing is collapsed -- the friendly default / "Collapse all"
// state. Cheap convenience so the control can disable a no-op button.
export function allExpanded(state: DetailRailState): boolean {
  return state.size === 0;
}

// A fresh state with every known slot collapsed. New Set so React sees a
// changed reference.
export function collapseAll(): DetailRailState {
  return new Set(DETAIL_RAIL_SLOTS);
}

// A fresh state with nothing collapsed (everything expanded).
export function expandAll(): DetailRailState {
  return new Set();
}

// How many known sections are currently collapsed (F111). Backs a faint
// "(N folded)" count badge next to the Expand/Collapse-all control so the
// partial state -- some sections folded, some not -- is legible at a glance
// without scanning every section. Counts ONLY known slots so a stale / corrupt
// entry can't inflate the badge past the real section count.
export function collapsedCount(state: DetailRailState): number {
  return DETAIL_RAIL_SLOTS.reduce(
    (n, slot) => (state.has(slot) ? n + 1 : n),
    0,
  );
}

// The "(N folded)" badge label, or null when the count isn't worth showing.
// Returns null at zero (nothing folded -> no inert noise) AND when everything
// is folded (the Expand-all button already says so -- the badge is only useful
// for the in-between, partially-folded state). "folded" is an adjective so it
// reads the same at any count ("1 folded" / "3 folded").
export function foldedCountLabel(state: DetailRailState): string | null {
  const n = collapsedCount(state);
  if (n <= 0) return null;
  if (n >= DETAIL_RAIL_SLOTS.length) return null;
  return `${n} folded`;
}

// --- Per-section header affordance (F96) ---------------------------------
// Each foldable rail section's header is a toggle, but it only carried an
// aria-expanded -- screen-reader + hover users got no verb. This pure helper
// builds a consistent "Collapse <title> section" / "Expand <title> section"
// label so every section header reads the action it performs, matching the
// wording of the rail's Expand/Collapse-all control. Kept here (not inline in
// the component) so the phrasing is unit-tested and stays in lockstep with the
// all-control. A blank / non-string title degrades to a generic "section".
export function sectionToggleHint(
  title: string,
  collapsed: boolean,
): string {
  const verb = collapsed ? "Expand" : "Collapse";
  const name = typeof title === "string" && title.trim() ? title.trim() : "section";
  return `${verb} ${name} section`;
}

// --- Expand/collapse-all keyboard chords (F93) ---------------------------
// Shift+E expands every rail section, Shift+C collapses every section. A pure
// matcher keeps the page handler thin and unit-testable. We check shift
// EXPLICITLY (rather than reusing lib/shortcuts' matchesShortcut, whose
// bare-combo path is built around shifted glyphs like "?" and would also
// accept a bare "e" / "c") so a plain letter press never folds the rail.

// The minimal key-event shape the matcher reads -- KeyboardEvent satisfies it.
export type RailChordKey = {
  key: string;
  shiftKey?: boolean;
  metaKey?: boolean;
  ctrlKey?: boolean;
  altKey?: boolean;
};

export type RailChordAction = "expand" | "collapse";

// Resolve a key event to a rail chord action, or null when it isn't one.
// Requires SHIFT and forbids Cmd / Ctrl / Alt so the chord never collides
// with a browser / OS shortcut. Case-insensitive on the letter (Shift makes
// the browser deliver an uppercase "E" / "C", but we tolerate either).
export function railChordAction(ev: RailChordKey): RailChordAction | null {
  if (!ev || typeof ev.key !== "string") return null;
  if (!ev.shiftKey) return null;
  if (ev.metaKey || ev.ctrlKey || ev.altKey) return null;
  const k = ev.key.toLowerCase();
  if (k === "e") return "expand";
  if (k === "c") return "collapse";
  return null;
}

// --- Browser wrappers (no-throw) -----------------------------------------

// Read the persisted collapse state. Returns an empty set (all expanded) on
// SSR / blocked storage / a corrupt value. Safe to call from a mount effect.
export function readDetailRail(): DetailRailState {
  if (typeof window === "undefined") return new Set();
  try {
    return parseDetailRail(
      window.localStorage.getItem(DETAIL_RAIL_STORAGE_KEY),
    );
  } catch {
    return new Set();
  }
}

// Persist the collapse state. No-throw: swallows quota / privacy-mode errors
// so a write failure never breaks folding.
export function writeDetailRail(state: DetailRailState): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      DETAIL_RAIL_STORAGE_KEY,
      serializeDetailRail(state),
    );
  } catch {
    // Ignore -- the in-memory state still works for this session.
  }
}

// Remove the persisted collapse state entirely (F105), so the rail reopens at
// the friendly all-expanded default on the next visit -- distinct from
// writeDetailRail(expandAll()) which persists an explicit empty blob. Backs
// the "Reset" affordance next to Expand/Collapse all. No-throw: a blocked /
// throwing storage is swallowed so the reset still applies in memory.
export function clearDetailRail(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(DETAIL_RAIL_STORAGE_KEY);
  } catch {
    // Ignore -- the caller still resets the in-memory state to expandAll().
  }
}
