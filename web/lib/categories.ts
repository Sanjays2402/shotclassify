// Category metadata. Mirrors packages/common/.../schemas.py Category enum.
export type Category =
  | "receipt"
  | "code_snippet"
  | "error_stacktrace"
  | "chat_screenshot"
  | "meme"
  | "document"
  | "ui_mockup"
  | "chart"
  | "other";

export const CATEGORIES: Category[] = [
  "receipt",
  "code_snippet",
  "error_stacktrace",
  "chat_screenshot",
  "meme",
  "document",
  "ui_mockup",
  "chart",
  "other",
];

// Short broadcast-style label, max 11 chars.
export const SHORT: Record<Category, string> = {
  receipt: "RECEIPT",
  code_snippet: "CODE",
  error_stacktrace: "ERROR",
  chat_screenshot: "CHAT",
  meme: "MEME",
  document: "DOC",
  ui_mockup: "UI",
  chart: "CHART",
  other: "OTHER",
};

export const LONG: Record<Category, string> = {
  receipt: "Receipt",
  code_snippet: "Code snippet",
  error_stacktrace: "Error stacktrace",
  chat_screenshot: "Chat screenshot",
  meme: "Meme",
  document: "Document",
  ui_mockup: "UI mockup",
  chart: "Chart",
  other: "Other",
};

// Confidence tier color.
export function confTier(score: number): "high" | "mid" | "low" {
  if (score >= 0.8) return "high";
  if (score >= 0.55) return "mid";
  return "low";
}

export function confColor(score: number): string {
  const t = confTier(score);
  if (t === "high") return "var(--color-conf-high)";
  if (t === "mid") return "var(--color-conf-mid)";
  return "var(--color-conf-low)";
}

export function pct(x: number, digits = 1): string {
  return (x * 100).toFixed(digits) + "%";
}

export function ms(n: number): string {
  if (n < 1000) return `${n} ms`;
  return `${(n / 1000).toFixed(2)} s`;
}

export function shortId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id;
}
