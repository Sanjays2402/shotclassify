// Pure share-link helpers for the /compare page (this tick). The page promises
// a "Shareable" view in its subhead, but the only share affordance was a Stat
// that printed `/compare?a=${shortId(a)}&b=${shortId(b)}` -- and shortId
// TRUNCATES an id to 8 chars, so the advertised URL was a BROKEN link that
// resolves to nothing when pasted. This module is the single, DOM-free source
// of truth for the compare deep link: it serialises the two FULL shot ids back
// into the `?a=ID&b=ID` query the page already parses on mount, so the copy
// button and the displayed path can never disagree (and never truncate).
//
// Mirrors lib/shots-deeplink's contract: build only the params that are set,
// clean back to a bare /compare when nothing is selected, and expose a toast
// message + a can-share predicate so the component stays a thin renderer.

// Trim an id to a usable token, or "" when it isn't a real id. Guards the
// non-string / blank cases so a half-loaded picker state can't emit `?a=`.
function cleanId(id: string | null | undefined): string {
  return typeof id === "string" ? id.trim() : "";
}

// True when there are two distinct sides worth sharing. A link with only one
// side reopens an unfinished comparison, so the button stays disabled until
// both are chosen. (Identical ids are allowed -- comparing a shot to itself is
// a legitimate, if unusual, link.)
export function canShareCompare(
  a: string | null | undefined,
  b: string | null | undefined,
): boolean {
  return cleanId(a) !== "" && cleanId(b) !== "";
}

// Serialise the current selection into a compare URL. `base` is prefixed
// verbatim (pass an absolute origin for the clipboard, "" for a relative
// display path). Only the sides that are set appear, in stable a-then-b order,
// so a one-sided selection still yields a valid (if partial) link and an empty
// selection collapses to a bare `${base}/compare`. Ids are emitted in FULL --
// never truncated -- so the link actually resolves.
export function buildCompareLink(
  a: string | null | undefined,
  b: string | null | undefined,
  base = "",
): string {
  const params = new URLSearchParams();
  const ca = cleanId(a);
  const cb = cleanId(b);
  if (ca) params.set("a", ca);
  if (cb) params.set("b", cb);
  const qs = params.toString();
  return `${base}/compare${qs ? `?${qs}` : ""}`;
}

// Toast copy after a successful copy-to-clipboard. Names how many sides the
// link carries so the user knows what a teammate will see when they open it.
export function compareShareToastMessage(
  a: string | null | undefined,
  b: string | null | undefined,
): string {
  const both = canShareCompare(a, b);
  return both
    ? "Copied a link to this comparison."
    : "Copied a link to this shot.";
}
