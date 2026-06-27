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
