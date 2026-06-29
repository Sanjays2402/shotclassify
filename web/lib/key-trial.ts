// /keys/[id] "Try it" empty-key affordance (F155). When a key has never been
// revealed (the secret is hashed at rest) the snippet shows only the prefix --
// there's nothing to paste yet. The block read "Rotate to mint a fresh one" but
// gave no path back to /keys to generate one cleanly. This pure module owns the
// trial-state copy + the CTA target so the page is a thin renderer and tests
// pin the wording + link.

// Where the "Generate one above" CTA goes -- back to the key list, anchored to
// the create form (KEY_NAME_INPUT_ID lives there). Single source for the link.
export const KEYS_CREATE_HREF = "/keys#key-name";

export type KeyTrialState = {
  // Is a full, copy-pasteable secret available (just rotated/created)?
  revealed: boolean;
  // Whether this view is a usable key or a not-yet-minted placeholder.
  callable: boolean;
  // The hint sentence under the snippet.
  hint: string;
  // CTA label, or null when no CTA is needed (a usable key needs none).
  cta: string | null;
};

// Decide what the Try-it block should say. revealed -> full secret on screen,
// no hint/CTA. Hidden but rotated-before -> prefix-only with the rotate hint.
// Never revealed -> direct the user back to /keys to generate one. Pure.
export function keyTrialState(revealed: boolean): KeyTrialState {
  if (revealed) {
    return { revealed: true, callable: true, hint: "", cta: null };
  }
  return {
    revealed: false,
    callable: true,
    hint: "The secret is hashed at rest, so the snippet shows the prefix. Rotate to mint a fresh one you can paste in.",
    cta: "Generate one above",
  };
}
