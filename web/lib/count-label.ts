// Shared "N of M <noun>" count-label helper (F112). Three list views grew
// their own copy of this phrasing: the /shots filter pill, the /webhooks
// "Filtering N of M deliveries" line, and the /notifications "N of M match"
// line. They drifted in tiny ways (prefix verb, singular/plural noun, whether
// to hide when nothing is hidden). This is the single, configurable,
// framework-free source of truth so the wording can't diverge again and the
// clamp / finite-guard logic lives in exactly one tested place.
//
// The two distinct call shapes it has to reproduce byte-for-byte:
//   webhooks:      "Filtering 3 of 10 deliveries"   (prefix + plural noun, hide when not narrowed)
//   notifications: "3 of 10 match"                  (no prefix, fixed noun, always show under filter)

export type OfTotalOptions = {
  // Optional verb prefix rendered before the count, e.g. "Filtering ".
  // Include its trailing space -- it is concatenated verbatim.
  prefix?: string;
  // Noun used when the total is exactly one, e.g. "delivery" / "match".
  singular: string;
  // Noun used for every other total. Defaults to `singular` when omitted
  // (the notifications case wants a fixed "match" for both).
  plural?: string;
  // When true (the default), the helper returns null unless the view is
  // actually narrowed (shown < total and total > 0) so the caller renders no
  // inert "10 of 10" noise. Pass false for surfaces that always want to show
  // the count whenever a filter is engaged (notifications).
  onlyWhenNarrowed?: boolean;
};

// Build the "<prefix>S of T <noun>" label, or null when there is nothing
// worth showing. Defensive: non-finite inputs no-op to null; total floors at
// zero; shown is clamped into [0, total] so a transient render can never print
// "12 of 10". Fractional inputs are truncated toward zero (counts are whole).
export function ofTotalLabel(
  shown: number,
  total: number,
  opts: OfTotalOptions,
): string | null {
  if (!Number.isFinite(shown) || !Number.isFinite(total)) return null;
  const t = Math.max(0, Math.trunc(total));
  const s = Math.min(Math.max(0, Math.trunc(shown)), t);
  const onlyWhenNarrowed = opts.onlyWhenNarrowed ?? true;
  if (onlyWhenNarrowed) {
    if (t <= 0) return null;
    // Only signal when the view is actually narrowed.
    if (s >= t) return null;
  }
  const noun = t === 1 ? opts.singular : opts.plural ?? opts.singular;
  const prefix = opts.prefix ?? "";
  return `${prefix}${s} of ${t} ${noun}`;
}
