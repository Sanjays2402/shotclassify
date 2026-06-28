// Name validation for the /keys create form (F132). Today the name input has
// no feedback: a blank name is silently renamed "Untitled key" by the server,
// a duplicate name is accepted with no warning (so you end up with three keys
// all called "ci" and can't tell them apart), and the 80-char cap is enforced
// only by the maxLength attribute with no explanation. This is the pure,
// DOM-free validator the form uses to (a) show an inline hint as you type and
// (b) gate the Generate button, mirroring the server's slice(0,80)/trim rules
// so the client and server agree on what a valid name is.

// Same cap the server applies in createKeyAt (keystore-core.ts slice(0, 80)).
export const KEY_NAME_MAX = 80;

export type KeyNameValidity = "ok" | "empty" | "too-long" | "duplicate";

export type KeyNameValidation = {
  // True only when the name is safe to submit as-is.
  ok: boolean;
  // The trimmed value that will actually be stored (so the form can submit the
  // normalised string rather than the raw input with stray whitespace).
  normalized: string;
  // Coarse reason code, for styling / testing.
  kind: KeyNameValidity;
  // Human sentence for the inline hint. Empty string when ok (nothing to say).
  message: string;
};

// Validate a candidate key name against the existing names. `existing` is the
// list of names already in the workspace; the duplicate check is
// case-insensitive and whitespace-trimmed so "CI " and "ci" collide (they'd be
// indistinguishable in the list). Defensive: a non-string name is treated as
// empty; a non-array `existing` is treated as no existing names.
export function validateKeyName(
  name: unknown,
  existing: readonly string[] = [],
): KeyNameValidation {
  const raw = typeof name === "string" ? name : "";
  const normalized = raw.trim();

  if (!normalized) {
    return {
      ok: false,
      normalized: "",
      kind: "empty",
      message: "Give the key a name so you can tell it apart later.",
    };
  }

  if (normalized.length > KEY_NAME_MAX) {
    return {
      ok: false,
      normalized,
      kind: "too-long",
      message: `Keep the name under ${KEY_NAME_MAX} characters (currently ${normalized.length}).`,
    };
  }

  const taken = Array.isArray(existing)
    ? existing.some(
        (n) => typeof n === "string" && n.trim().toLowerCase() === normalized.toLowerCase(),
      )
    : false;
  if (taken) {
    return {
      ok: false,
      normalized,
      kind: "duplicate",
      message: "You already have a key with this name. Pick something distinct.",
    };
  }

  return { ok: true, normalized, kind: "ok", message: "" };
}

// Convenience predicate for the Generate button's disabled state. A pristine
// (never-touched) empty field shouldn't show a red error, but it still can't
// be submitted -- the button stays disabled until a valid name is entered.
export function canSubmitKeyName(
  name: unknown,
  existing: readonly string[] = [],
): boolean {
  return validateKeyName(name, existing).ok;
}
