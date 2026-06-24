// Pure helpers for the scroll-progress / back-to-top affordance. Computing
// the scroll percent is trivial in isolation, but it's worth pulling the
// math out so the component stays focused on lifecycle (rAF coalescing,
// passive listeners) and the math is unit-testable.

// Compute the 0..1 scroll progress through a scrolled element. The clamp
// is defensive -- some browsers report scrollTop transiently outside the
// expected range during overscroll bounce on macOS / iOS.
export function scrollProgress(
  scrollTop: number,
  scrollHeight: number,
  clientHeight: number,
): number {
  const max = scrollHeight - clientHeight;
  if (!Number.isFinite(max) || max <= 0) return 0;
  if (!Number.isFinite(scrollTop)) return 0;
  const ratio = scrollTop / max;
  if (ratio < 0) return 0;
  if (ratio > 1) return 1;
  return ratio;
}

// Decide whether the "back to top" floating action button should be
// visible. Hidden when the user is in the top region of the page (less
// than threshold pixels scrolled). The default 600px maps roughly to one
// hero band on most layouts.
export function backToTopVisible(
  scrollTop: number,
  threshold = 600,
): boolean {
  if (!Number.isFinite(scrollTop)) return false;
  return scrollTop > threshold;
}
