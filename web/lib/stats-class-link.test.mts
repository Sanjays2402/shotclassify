// Pure tests for the /stats class-tile windowed deep-link (F60). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import { sinceForWindow, statsClassLink } from "./stats-class-link.ts";
import { parseShotsDeepLink } from "./shots-deeplink.ts";

// A fixed reference instant: 2026-06-20T12:00:00Z.
const NOW = Date.UTC(2026, 5, 20, 12, 0, 0);

test("sinceForWindow: 24h / 7d / 30d back from now (UTC, date-granular)", () => {
  assert.equal(sinceForWindow(24, NOW), "2026-06-19"); // 1 day back
  assert.equal(sinceForWindow(168, NOW), "2026-06-13"); // 7 days back
  assert.equal(sinceForWindow(720, NOW), "2026-05-21"); // 30 days back
});

test("sinceForWindow: invalid windows yield no since", () => {
  assert.equal(sinceForWindow(0, NOW), undefined);
  assert.equal(sinceForWindow(-5, NOW), undefined);
  assert.equal(sinceForWindow(NaN, NOW), undefined);
  assert.equal(sinceForWindow(Infinity, NOW), undefined);
  assert.equal(sinceForWindow(24, NaN), undefined);
});

test("sinceForWindow: crossing a month boundary borrows correctly", () => {
  // 30 days before June 20 lands in May.
  assert.equal(sinceForWindow(720, NOW), "2026-05-21");
  // 24h before the 1st of a month rolls to the previous month's last day.
  const firstOfMarch = Date.UTC(2026, 2, 1, 6, 0, 0);
  assert.equal(sinceForWindow(24, firstOfMarch), "2026-02-28");
});

test("statsClassLink: builds a class + since deep-link", () => {
  const href = statsClassLink("receipt", 168, NOW);
  assert.equal(href, "/shots?category=receipt&since=2026-06-13");
});

test("statsClassLink: a custom base produces an absolute URL", () => {
  const href = statsClassLink("chart", 24, NOW, "https://app.example/shots");
  assert.equal(href, "https://app.example/shots?category=chart&since=2026-06-19");
});

test("statsClassLink: an invalid window degrades to a bare class link", () => {
  assert.equal(statsClassLink("meme", 0, NOW), "/shots?category=meme");
});

test("round-trip: the parser reads back exactly what the link encodes", () => {
  // The destination page (F30 parser) must extract the same class + since the
  // tile encoded, so the windowed link actually pre-filters the list.
  for (const [cat, hours] of [
    ["receipt", 24],
    ["code_snippet", 168],
    ["error_stacktrace", 720],
  ] as const) {
    const href = statsClassLink(cat, hours, NOW);
    const qs = href.slice(href.indexOf("?"));
    const parsed = parseShotsDeepLink(new URLSearchParams(qs));
    assert.equal(parsed.category, cat);
    assert.equal(parsed.since, sinceForWindow(hours, NOW));
  }
});
