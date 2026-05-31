// Onboarding state. First-run tour is gated by a localStorage flag so
// returning visitors don't see it again. We expose a tiny helper so other
// pages (e.g. Account) can reset the flag to replay the tour.

export const ONBOARDING_KEY = "shotclassify.onboarded.v1";

export function isOnboarded(): boolean {
  if (typeof window === "undefined") return true;
  try {
    return window.localStorage.getItem(ONBOARDING_KEY) === "1";
  } catch {
    return true;
  }
}

export function markOnboarded(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(ONBOARDING_KEY, "1");
  } catch {
    // Storage unavailable (private mode, quota). Treat as a no-op so we
    // fail open rather than blocking the page.
  }
}

export function resetOnboarded(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(ONBOARDING_KEY);
  } catch {
    // ignore
  }
}

export type TourStep = {
  title: string;
  body: string;
  cta: { label: string; href: string };
};

export const TOUR_STEPS: TourStep[] = [
  {
    title: "Classify a screenshot",
    body:
      "Drop a screenshot on the Demo page and ShotClassify returns a category plus confidence scores across receipt, chat, code, document, and stacktrace.",
    cta: { label: "Open Demo", href: "/demo" },
  },
  {
    title: "Every run is saved",
    body:
      "Your classifications land in Shots. Filter by category, search the filename, re-run with a different model, or export the whole table as CSV or JSON.",
    cta: { label: "View Shots", href: "/shots" },
  },
  {
    title: "Build on it",
    body:
      "Generate an API key, hit the /v1/classify endpoint from your own code, and wire webhooks so downstream systems get notified the moment a shot is classified.",
    cta: { label: "Get an API key", href: "/keys" },
  },
];
