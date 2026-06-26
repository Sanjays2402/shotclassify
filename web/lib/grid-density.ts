// Column-density control for the /shots grid view (F29). The card grid
// shipped with a fixed responsive column count (1/2/3/4 across breakpoints);
// this lets a user trade card size for scan-density -- "roomy" for big cards
// you can read OCR-forward, "dense" for cramming more shots above the fold.
// Persisted like the view mode / page size so a return visit reopens on the
// density you last used.
//
// Pure + DOM-free so parse/serialize/class-resolution is unit-testable. The
// component is a thin renderer over this. IMPORTANT: the column classes are
// full static strings, NOT interpolated, because Tailwind's compiler only
// emits classes it can see literally in the source -- a `lg:grid-cols-${n}`
// would never make it into the stylesheet.

export type GridDensity = "roomy" | "default" | "dense";

export const GRID_DENSITY_STORAGE_KEY = "shotclassify.shots.grid.density";

export const GRID_DENSITY_DEFAULT: GridDensity = "default";

// Order matches the on-screen toggle (fewest columns -> most).
export const GRID_DENSITIES: GridDensity[] = ["roomy", "default", "dense"];

// Full, static Tailwind class strings per density. Each climbs the same
// breakpoint ladder the grid always used, just capped at a different max so
// the cards grow / shrink coherently. "default" reproduces the original
// grid-cols-1 sm:2 lg:3 xl:4 exactly so this is a no-op for existing users.
const DENSITY_CLASSES: Record<GridDensity, string> = {
  roomy: "grid-cols-1 sm:grid-cols-2 lg:grid-cols-2 xl:grid-cols-3",
  default: "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4",
  dense: "grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6",
};

function isKnownDensity(s: string): s is GridDensity {
  return (GRID_DENSITIES as string[]).includes(s);
}

// Coerce a persisted value into a known density. Anything unrecognised -- a
// corrupt blob, a future-schema value, null -- falls back to the default so
// the grid always renders a valid column count.
export function parseGridDensity(
  raw: string | null | undefined,
): GridDensity {
  if (typeof raw !== "string") return GRID_DENSITY_DEFAULT;
  const t = raw.trim().toLowerCase();
  return isKnownDensity(t) ? t : GRID_DENSITY_DEFAULT;
}

// Serialize back to the stored string. Symmetric with parseGridDensity.
export function serializeGridDensity(d: GridDensity): string {
  return d;
}

// The static column classes for a density. Always returns a valid string,
// coercing an unknown input through the default so a caller can't render an
// empty grid.
export function gridColumnsClass(d: GridDensity): string {
  return DENSITY_CLASSES[isKnownDensity(d) ? d : GRID_DENSITY_DEFAULT];
}

// Human label for the toggle's aria / title.
export function labelForGridDensity(d: GridDensity): string {
  if (d === "roomy") return "Roomy";
  if (d === "dense") return "Dense";
  return "Default";
}

// --- Browser wrappers (no-throw) -----------------------------------------

// Read the persisted density. Returns the default on SSR / blocked storage /
// a corrupt value. Safe to call from a mount effect.
export function readGridDensity(): GridDensity {
  if (typeof window === "undefined") return GRID_DENSITY_DEFAULT;
  try {
    return parseGridDensity(
      window.localStorage.getItem(GRID_DENSITY_STORAGE_KEY),
    );
  } catch {
    return GRID_DENSITY_DEFAULT;
  }
}

// Persist the selected density. No-throw: swallows quota / privacy-mode
// errors so a write failure never breaks the toggle.
export function writeGridDensity(d: GridDensity): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      GRID_DENSITY_STORAGE_KEY,
      serializeGridDensity(d),
    );
  } catch {
    // Ignore -- the in-memory selection still works for this session.
  }
}
