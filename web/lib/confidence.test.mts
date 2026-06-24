// Pure tests for the confidence formatting helpers.
import test from "node:test";
import assert from "node:assert/strict";

import {
  confAriaLabel,
  confDisplay,
  confTier,
  confTokenName,
  confTooltip,
  TIER_LABEL,
} from "./confidence.ts";

test("confTier: bands match the visual palette thresholds", () => {
  assert.equal(confTier(0.0), "low");
  assert.equal(confTier(0.32), "low");
  assert.equal(confTier(0.549999), "low");
  assert.equal(confTier(0.55), "mid");
  assert.equal(confTier(0.79), "mid");
  assert.equal(confTier(0.8), "high");
  assert.equal(confTier(1.0), "high");
});

test("confTier: defensive clamping is not done here; high inputs stay high", () => {
  // Confidence > 1.0 isn't valid but we still want a stable tier.
  assert.equal(confTier(1.5), "high");
});

test("TIER_LABEL: covers every tier with screen-reader-grade copy", () => {
  assert.equal(TIER_LABEL.high, "High confidence");
  assert.equal(TIER_LABEL.mid, "Medium confidence");
  assert.equal(TIER_LABEL.low, "Low confidence");
});

test("confAriaLabel: composes number + tier copy", () => {
  assert.equal(
    confAriaLabel(0.92),
    "92.0 percent. High confidence.",
  );
  assert.equal(
    confAriaLabel(0.4),
    "40.0 percent. Low confidence.",
  );
  // Custom digits.
  assert.equal(
    confAriaLabel(0.7345, 2),
    "73.45 percent. Medium confidence.",
  );
});

test("confAriaLabel: clamps out-of-range input", () => {
  assert.equal(
    confAriaLabel(1.5),
    "100.0 percent. High confidence.",
  );
  assert.equal(
    confAriaLabel(-0.4),
    "0.0 percent. Low confidence.",
  );
});

test("confDisplay: default zero digits, never above 100", () => {
  assert.equal(confDisplay(0.92), "92%");
  assert.equal(confDisplay(0.92, 1), "92.0%");
  assert.equal(confDisplay(0.005), "1%"); // 0.5 rounds up at 0 digits
  assert.equal(confDisplay(1.5), "100%");
  assert.equal(confDisplay(-0.1), "0%");
});

test("confTokenName: maps tier to CSS variable name", () => {
  assert.equal(confTokenName(0.95), "--color-conf-high");
  assert.equal(confTokenName(0.7), "--color-conf-mid");
  assert.equal(confTokenName(0.2), "--color-conf-low");
});

test("confTooltip: shows two-decimal precision and tier suffix", () => {
  assert.equal(confTooltip(0.9215), "92.15% · high confidence");
  assert.equal(confTooltip(0.55), "55.00% · medium confidence");
  // Out-of-range clamped.
  assert.equal(confTooltip(2.0), "100.00% · high confidence");
});
