// Match-highlight segmentation for the /shots OCR search results. The list
// shows a clipped OCR snippet per row; once a user searches, nothing tells them
// WHERE the term matched in that line. This splits a string into ordered
// segments tagged match / plain so a thin renderer wraps the matches in a
// felt-green <mark> with zero regex in the component. Pure + DOM-free; the
// matcher is case-insensitive, overlap-free, and bounds the work so a huge OCR
// blob can't lock up the row.

export type MarkSegment = { text: string; match: boolean };

// Cap so an enormous OCR dump with a one-char query can't produce thousands of
// fragments. Past this we stop marking and emit the tail as one plain run.
const MAX_SEGMENTS = 200;

// Split `text` on every case-insensitive occurrence of `query`, returning the
// in-order segments. Empty / blank query (or empty text) yields a single plain
// segment so the caller always renders the original string. Matches don't
// overlap (scan advances past each hit). Query length is honoured verbatim, so
// the wrapped run is exactly what matched.
export function markMatches(
  text: string,
  query: string | null | undefined,
): MarkSegment[] {
  const src = typeof text === "string" ? text : "";
  const q = typeof query === "string" ? query.trim() : "";
  if (!src) return [{ text: "", match: false }];
  if (!q) return [{ text: src, match: false }];

  const hay = src.toLowerCase();
  const needle = q.toLowerCase();
  const out: MarkSegment[] = [];
  let i = 0;
  while (i < src.length && out.length < MAX_SEGMENTS) {
    const hit = hay.indexOf(needle, i);
    if (hit < 0) break;
    if (hit > i) out.push({ text: src.slice(i, hit), match: false });
    out.push({ text: src.slice(hit, hit + needle.length), match: true });
    i = hit + needle.length;
  }
  if (i < src.length) out.push({ text: src.slice(i), match: false });
  return out.length ? out : [{ text: src, match: false }];
}

// True when the query actually appears in the text -- lets a row decide whether
// to bother rendering the marked segments vs the plain string.
export function hasMatch(
  text: string,
  query: string | null | undefined,
): boolean {
  const src = typeof text === "string" ? text : "";
  const q = typeof query === "string" ? query.trim() : "";
  if (!src || !q) return false;
  return src.toLowerCase().includes(q.toLowerCase());
}
