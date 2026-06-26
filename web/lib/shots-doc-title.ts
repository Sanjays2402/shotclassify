// Document-title derivation for the /shots list (F58). A deep-linked or
// filtered shots tab was historically indistinguishable from any other in the
// browser's tab bar -- every one read the app's default title. This turns the
// live filter state into a concise, identifiable tab title ("Receipt · >=90%
// confidence · Shots") so a user juggling several filtered views can tell them
// apart at a glance, and a bookmarked deep-link names itself.
//
// Pure + DOM-free so the string-building is unit-testable; the page applies it
// in a small effect. Reuses F52's shotsFilterParts so the tab title, the
// copy-link toast, and the breadcrumb all describe a filter identically.

import { shotsFilterParts, type ShotsFilterState } from "./shots-deeplink";

// The trailing section label every shots title ends with, so the tab is
// recognisable as the shots list even when no filter is active.
export const SHOTS_TITLE_BASE = "Shots";

// Build the tab title for the current filter state. With no active filter it's
// just the base ("Shots"); with filters the active phrases lead, joined by the
// app's mid-dot separator, then the base -- "Receipt · >=90% confidence ·
// Shots". The parts come straight from F52 so the wording is consistent with
// the copy-link toast.
export function shotsDocTitle(
  state: ShotsFilterState,
  base = SHOTS_TITLE_BASE,
): string {
  const parts = shotsFilterParts(state);
  if (parts.length === 0) return base;
  return `${parts.join(" · ")} · ${base}`;
}
