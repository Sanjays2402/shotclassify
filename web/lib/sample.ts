import type { Category } from "./categories";
import { CATEGORIES } from "./categories";

// Deterministic-but-varied sample data for UI states when the API has no rows.
// Always render with a visible "sample" badge in the UI.

export type SampleShot = {
  id: string;
  filename: string;
  primary_category: Category;
  confidence: number;
  elapsed_ms: number;
  source: string;
  created_at: string; // ISO
  ocr_text: string;
};

const SOURCES = ["api/upload", "macos/quick-action", "cli/classify", "batch/dropbox"];
const FILES: Record<Category, string[]> = {
  receipt: ["safeway-2026-05-12.png", "uber-receipt.jpg", "amzn-order-9912.png"],
  code_snippet: ["snippet-tsx.png", "py-handler.png", "rust-fn.png"],
  error_stacktrace: ["nullpointer-jvm.png", "pyerr-traceback.png", "ts-compile-fail.png"],
  chat_screenshot: ["slack-incident.png", "imessage-7pm.jpg", "discord-thread.png"],
  meme: ["distracted-bf.jpg", "stonks.png", "drake-no-yes.jpg"],
  document: ["lease-page-3.png", "tax-form-w2.png", "memo-q2-plan.png"],
  ui_mockup: ["figma-onboarding.png", "wire-checkout.png", "dash-mock.png"],
  chart: ["bar-mau-q1.png", "line-latency-p95.png", "donut-share.png"],
  other: ["unknown-001.png", "blurry-frame.png", "ambient-002.png"],
};

function pick<T>(arr: T[], n: number): T {
  return arr[n % arr.length];
}

// Realistic-looking confidence per category.
function sampleConf(cat: Category, seed: number): number {
  const base: Record<Category, number> = {
    receipt: 0.94,
    code_snippet: 0.91,
    error_stacktrace: 0.88,
    chat_screenshot: 0.86,
    meme: 0.78,
    document: 0.74,
    ui_mockup: 0.69,
    chart: 0.83,
    other: 0.52,
  };
  const jitter = ((seed * 9301 + 49297) % 233280) / 233280; // 0..1
  const v = base[cat] - (jitter * 0.18);
  return Math.max(0.32, Math.min(0.995, v));
}

export function makeSampleShots(count = 24, startEpoch = Date.now()): SampleShot[] {
  const out: SampleShot[] = [];
  for (let i = 0; i < count; i++) {
    const cat = CATEGORIES[i % CATEGORIES.length];
    const ageMs = i * 47_000 + (i * i * 1300) % 90_000;
    const ts = new Date(startEpoch - ageMs).toISOString();
    out.push({
      id: `smp_${(i + 1).toString(36).padStart(4, "0")}${(startEpoch & 0xfff).toString(16)}`,
      filename: pick(FILES[cat], i),
      primary_category: cat,
      confidence: sampleConf(cat, i),
      elapsed_ms: 240 + ((i * 137) % 980),
      source: pick(SOURCES, i),
      created_at: ts,
      ocr_text: "",
    });
  }
  return out;
}

// 24h counts per category for the header ticker.
export function makeSampleCounts(): Record<Category, number> {
  return {
    receipt: 412,
    code_snippet: 388,
    error_stacktrace: 271,
    chat_screenshot: 196,
    meme: 142,
    document: 117,
    ui_mockup: 88,
    chart: 73,
    other: 54,
  };
}

// Per-class probabilities for the detail view when API record lacks them.
export function sampleDistribution(primary: Category, primaryScore: number) {
  const rest = 1 - primaryScore;
  const others = CATEGORIES.filter((c) => c !== primary);
  // Distribute remaining mass with decay.
  const weights = others.map((_, i) => 1 / (i + 2));
  const wsum = weights.reduce((a, b) => a + b, 0);
  const dist = [
    { category: primary, score: primaryScore },
    ...others.map((c, i) => ({ category: c, score: (weights[i] / wsum) * rest })),
  ];
  return dist.sort((a, b) => b.score - a.score);
}

// Reliability diagram bins: predicted prob vs empirical accuracy.
// Realistic, slightly underconfident model.
export function sampleReliability() {
  const bins = [0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95];
  return bins.map((p) => {
    // accuracy slightly tracks p, with mild S-curve.
    const acc = Math.max(0, Math.min(1, p + (p - 0.5) * 0.08 + (Math.random() < 0.5 ? -0.02 : 0.02)));
    const n = Math.round(380 - Math.abs(p - 0.5) * 320);
    return { conf: p, acc, n };
  });
}
