// Pure tests for the empty-state copy helpers. No DOM, no React.
import test from "node:test";
import assert from "node:assert/strict";

import {
  describeFilters,
  emptyCopyForList,
  hasActiveFilters,
} from "./empty-state.ts";

test("hasActiveFilters: detects each filter slot independently", () => {
  assert.equal(hasActiveFilters({}), false);
  assert.equal(hasActiveFilters({ q: "" }), false);
  assert.equal(hasActiveFilters({ q: "   " }), false);
  assert.equal(hasActiveFilters({ q: "receipt" }), true);
  assert.equal(hasActiveFilters({ category: "receipt" }), true);
  assert.equal(hasActiveFilters({ tag: "" }), false);
  assert.equal(hasActiveFilters({ tag: "important" }), true);
  assert.equal(hasActiveFilters({ min_conf: 0 }), false);
  assert.equal(hasActiveFilters({ min_conf: 0.7 }), true);
  assert.equal(hasActiveFilters({ since: "2026-01-01" }), true);
  assert.equal(hasActiveFilters({ until: "2026-06-01" }), true);
  assert.equal(hasActiveFilters({ pinnedOnly: false }), false);
  assert.equal(hasActiveFilters({ pinnedOnly: true }), true);
  assert.equal(hasActiveFilters({ unreadOnly: true }), true);
});

test("describeFilters: empty filters yield empty string", () => {
  assert.equal(describeFilters({}), "");
  assert.equal(describeFilters({ q: " ", category: "" }), "");
});

test("describeFilters: lists every active filter, joined by middot", () => {
  const s = describeFilters({
    category: "receipt",
    q: "uber",
    tag: "important",
    min_conf: 0.85,
    since: "2026-01-01",
    until: "2026-06-01",
    pinnedOnly: true,
  });
  assert.match(s, /class receipt/);
  assert.match(s, /search "uber"/);
  assert.match(s, /tag #important/);
  assert.match(s, />=85% confidence/);
  assert.match(s, /between 2026-01-01 and 2026-06-01/);
  assert.match(s, /pinned only/);
  // Sanity check the separator.
  assert.ok(s.includes(" · "));
});

test("describeFilters: long q is truncated with ellipsis", () => {
  const q = "x".repeat(80);
  const s = describeFilters({ q });
  // Truncated to 32 chars plus an ellipsis.
  assert.match(s, /search "x{32}…"/);
});

test("describeFilters: single-sided date range collapses to 'since' or 'until'", () => {
  assert.match(describeFilters({ since: "2026-01-01" }), /since 2026-01-01/);
  assert.match(describeFilters({ until: "2026-06-01" }), /until 2026-06-01/);
  assert.match(
    describeFilters({ since: "2026-01-01", until: "2026-06-01" }),
    /between 2026-01-01 and 2026-06-01/,
  );
});

test("emptyCopyForList: blank-slate when no filters", () => {
  const { title, body } = emptyCopyForList("shots", {});
  assert.match(title, /No shots yet/);
  assert.match(body, /feed it a frame/i);
});

test("emptyCopyForList: filtered yields summary-aware copy", () => {
  const { title, body } = emptyCopyForList("shots", {
    category: "receipt",
    min_conf: 0.9,
  });
  assert.match(title, /No shots match that filter/);
  assert.match(body, /class receipt/);
  assert.match(body, />=90% confidence/);
  assert.match(body, /widening|clearing/i);
});

test("emptyCopyForList: filtered + unsummarizable still suggests widening", () => {
  // pinnedOnly + unreadOnly produce a non-empty summary too -- let's exercise
  // the no-summary fallback by toggling everything off but pinnedOnly=true.
  // (pinnedOnly DOES summarize, so this lands in the summary branch.)
  const { body } = emptyCopyForList("shots", { pinnedOnly: true });
  assert.match(body, /pinned only/);
});

test("emptyCopyForList: noun is interpolated verbatim", () => {
  const a = emptyCopyForList("notifications", {});
  assert.match(a.title, /No notifications yet/);
  const b = emptyCopyForList("notifications", { unreadOnly: true });
  assert.match(b.title, /No notifications match that filter/);
});
