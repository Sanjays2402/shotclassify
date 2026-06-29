// Scroll-and-focus the API-key create form (F148). The /keys empty state read
// "Generate one above" but had no CTA -- a new user landed with no keys and no
// obvious next step. This adds the primary "Create a key" action; clicking it
// scrolls the create form into view and focuses the name field. This module is
// the DOM-free target-id + scroll-options contract so the page can call one
// helper and tests can pin the ids.

// The id on the key-name <input> (the create form's first field). Single source
// so the empty-state CTA, the page, and tests can't drift from the markup.
export const KEY_NAME_INPUT_ID = "key-name";

// scrollIntoView options for the create CTA: smooth, top-aligned so the form
// header is in view. Honour reduced-motion by dropping to instant when the
// caller reports the preference, keeping the focus jump but not the animation.
export function createFormScrollOptions(
  reducedMotion = false,
): ScrollIntoViewOptions {
  return { behavior: reducedMotion ? "auto" : "smooth", block: "start" };
}

// Run the scroll + focus against a resolver (e.g. document.getElementById).
// Pure of the DOM: the caller injects the lookup so we can test the sequence
// without a browser. Returns true when the input was found and focused.
export function scrollToCreateForm(
  getEl: (id: string) => { scrollIntoView: (o: ScrollIntoViewOptions) => void; focus: () => void } | null,
  reducedMotion = false,
): boolean {
  const el = getEl(KEY_NAME_INPUT_ID);
  if (!el) return false;
  el.scrollIntoView(createFormScrollOptions(reducedMotion));
  el.focus();
  return true;
}
