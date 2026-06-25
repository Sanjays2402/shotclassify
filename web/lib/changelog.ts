// Static in-app changelog feed + pure helpers for the "what's new" popover.
// The header version pill opens this; after a version bump the popover
// auto-shows once (a localStorage pointer records the newest entry the user
// has seen). Keeping the data + seen/unseen logic here makes it testable
// without a DOM and gives every surface one source of truth for "what's the
// current version".

export type ChangelogEntry = {
  // Semver-ish version string. The FIRST entry is the newest.
  version: string;
  // ISO date (yyyy-mm-dd) the entry shipped.
  date: string;
  // One-line headline.
  title: string;
  // A few bullet strings describing the changes.
  highlights: string[];
};

// Newest first. Append new releases at the TOP. The header pill renders
// `v<CHANGELOG[0].version>`.
export const CHANGELOG: ChangelogEntry[] = [
  {
    version: "0.5",
    date: "2026-06-25",
    title: "Workspace polish: toasts, skeletons, palette facets",
    highlights: [
      "App-wide toast notifications replace the old per-page flash banners.",
      "Unified skeleton loaders shimmer consistently while data loads.",
      "Command palette understands class:receipt, >90%, and tag: filters.",
      "Copy any shot as JSON or Markdown straight from the detail page.",
      "This changelog popover — click the version pill any time.",
    ],
  },
  {
    version: "0.4",
    date: "2026-06-24",
    title: "Keyboard-first navigation + theming",
    highlights: [
      "Press ? anywhere for the keyboard-shortcuts cheat sheet.",
      "New Dim theme with a flash-free pre-paint init.",
      "Confidence pills now carry tier colour + screen-reader labels.",
      "Scroll-progress bar and back-to-top button on long pages.",
    ],
  },
  {
    version: "0.3",
    date: "2026-06-23",
    title: "Richer shot detail + sharing",
    highlights: [
      "Public share pages and embeddable iframe snippets per shot.",
      "Saved views let you bookmark a filter set on the shots table.",
      "Bulk tag / pin / delete from the shots list.",
    ],
  },
  {
    version: "0.2",
    date: "2026-06-21",
    title: "Analytics and calibration",
    highlights: [
      "Stats dashboard with class mix, latency, and calibration histogram.",
      "Per-shot confidence distribution chart.",
      "Compare two shots side by side.",
    ],
  },
  {
    version: "0.1",
    date: "2026-06-20",
    title: "First broadcast",
    highlights: [
      "Live classification feed with OCR + field extraction.",
      "Browse, search, and filter every shot the service has called.",
    ],
  },
];

export const CHANGELOG_STORAGE_KEY = "shotclassify.changelog.seen";

// The current (newest) version string. Safe even if the list were empty.
export function currentVersion(log: ChangelogEntry[] = CHANGELOG): string {
  return log.length > 0 ? log[0].version : "0.0";
}

// The newest entry, or undefined if the log is empty.
export function latestEntry(
  log: ChangelogEntry[] = CHANGELOG,
): ChangelogEntry | undefined {
  return log[0];
}

// Given the version pointer previously stored (whatever the user last saw),
// decide whether the popover should auto-open. True when:
//   - there's no stored pointer at all (first visit) AND there's a changelog
//   - OR the stored pointer differs from the current newest version.
// We compare by exact string rather than ordering so a rollback also
// surfaces (the user should see what changed either direction).
export function hasUnseen(
  stored: string | null | undefined,
  log: ChangelogEntry[] = CHANGELOG,
): boolean {
  if (log.length === 0) return false;
  const current = currentVersion(log);
  if (stored == null || stored === "") return true;
  return stored !== current;
}

// How many entries are newer than the stored pointer -- drives the little
// "N new" count on the pill. If the stored version isn't found in the log
// (older than everything we still list, or unknown), every entry counts as
// new. A matching pointer yields 0.
export function unseenCount(
  stored: string | null | undefined,
  log: ChangelogEntry[] = CHANGELOG,
): number {
  if (log.length === 0) return 0;
  if (stored == null || stored === "") return log.length;
  const idx = log.findIndex((e) => e.version === stored);
  if (idx === -1) return log.length;
  return idx; // entries before the stored one are newer (list is newest-first)
}

// Format an ISO date for display in the popover. Falls back to the raw
// string if it doesn't parse.
export function formatEntryDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
