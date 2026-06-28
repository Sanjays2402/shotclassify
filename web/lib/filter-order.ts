// Keyboard Tab-order for the /shots filter toolbar (F138, closing the long-open
// F20/F75/F87/F99/F121 chain). The toolbar packs class / OCR-search / page-size
// / sort / tag / from / to / min-conf / pinned controls. Source order put the
// OCR box second, so Tab jumped there before the class select read; power users
// want to walk the filter controls in a predictable left-to-right order. This
// pure, DOM-free module names the canonical order and turns a control id into
// its tabIndex, so the page can assign a roving sequence the keyboard honours
// regardless of DOM nesting. Tested via the order array + the index helper.

// The filter controls in the order Tab should visit them. The class selector
// leads (the primary facet), then search, then the refinements. Keep in sync
// with the toolbar JSX -- the page reads these ids onto each control.
export type ShotsFilterControl =
  | "class"
  | "search"
  | "pageSize"
  | "sort"
  | "tag"
  | "from"
  | "to"
  | "minConf"
  | "pinned";

export const SHOTS_FILTER_ORDER: ShotsFilterControl[] = [
  "class",
  "search",
  "pageSize",
  "sort",
  "tag",
  "from",
  "to",
  "minConf",
  "pinned",
];

// Base tabIndex so the toolbar sits ahead of body controls but after the top
// nav (which uses the default 0). 10..18 leaves room and never collides with
// implicit 0 elements (they tab last after positive values).
export const SHOTS_FILTER_TABINDEX_BASE = 10;

// The tabIndex for a control. Known controls get BASE + position (1-based);
// unknown controls fall back to 0 so a stray element joins the natural order
// rather than wedging into the sequence. A roving sequence (BASE+1..) means
// Tab walks the filters left-to-right, then the rest of the page.
export function filterTabIndex(control: ShotsFilterControl | string): number {
  const i = (SHOTS_FILTER_ORDER as string[]).indexOf(control);
  return i < 0 ? 0 : SHOTS_FILTER_TABINDEX_BASE + i + 1;
}

// The next control id when cycling with Tab (wraps). Lets a hook move focus
// explicitly if the page wants to trap focus inside the toolbar; unknown -> the
// first control so a bad current value lands somewhere valid.
export function nextFilterControl(
  control: ShotsFilterControl,
): ShotsFilterControl {
  const i = SHOTS_FILTER_ORDER.indexOf(control);
  if (i < 0) return SHOTS_FILTER_ORDER[0];
  return SHOTS_FILTER_ORDER[(i + 1) % SHOTS_FILTER_ORDER.length];
}

// The previous control (Shift+Tab), wrapping the other way.
export function prevFilterControl(
  control: ShotsFilterControl,
): ShotsFilterControl {
  const i = SHOTS_FILTER_ORDER.indexOf(control);
  if (i < 0) return SHOTS_FILTER_ORDER[SHOTS_FILTER_ORDER.length - 1];
  return SHOTS_FILTER_ORDER[
    (i - 1 + SHOTS_FILTER_ORDER.length) % SHOTS_FILTER_ORDER.length
  ];
}
