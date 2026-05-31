import test from "node:test";
import assert from "node:assert/strict";

import {
  makePeriod,
  renderDigestHTML,
  renderDigestText,
  renderEml,
  summarize,
  type DigestRow,
} from "./digest.ts";

const NOW = new Date("2026-06-01T00:00:00.000Z");

function row(over: Partial<DigestRow> = {}): DigestRow {
  return {
    id: "id-x",
    filename: "x.png",
    primary_category: "receipt",
    confidence: 0.9,
    created_at: "2026-05-30T12:00:00.000Z",
    ...over,
  };
}

test("makePeriod clamps and produces ISO bounds", () => {
  const p = makePeriod(7, NOW);
  assert.equal(p.days, 7);
  assert.equal(p.until, NOW.toISOString());
  assert.equal(p.since, "2026-05-25T00:00:00.000Z");

  assert.equal(makePeriod(0, NOW).days, 1);
  assert.equal(makePeriod(500, NOW).days, 90);
});

test("summarize: empty rows returns empty digest with zero per_day", () => {
  const p = makePeriod(7, NOW);
  const s = summarize([], p, NOW);
  assert.equal(s.empty, true);
  assert.equal(s.total_shots, 0);
  assert.equal(s.avg_confidence, 0);
  assert.equal(s.by_category.length, 0);
  assert.equal(s.top_shots.length, 0);
  assert.equal(s.per_day.length, 7);
  assert.ok(s.per_day.every((d) => d.count === 0));
});

test("summarize: filters by period, aggregates by category, sorts desc", () => {
  const p = makePeriod(7, NOW);
  const rows: DigestRow[] = [
    row({ id: "a", primary_category: "receipt", confidence: 0.8, created_at: "2026-05-30T10:00:00Z" }),
    row({ id: "b", primary_category: "receipt", confidence: 1.0, created_at: "2026-05-31T10:00:00Z" }),
    row({ id: "c", primary_category: "code_snippet", confidence: 0.5, created_at: "2026-05-29T10:00:00Z" }),
    // out of range
    row({ id: "old", primary_category: "receipt", confidence: 0.95, created_at: "2026-04-01T00:00:00Z" }),
    // unknown category dropped
    row({ id: "u", primary_category: "garbage", confidence: 0.99, created_at: "2026-05-30T00:00:00Z" }),
  ];
  const s = summarize(rows, p, NOW);
  assert.equal(s.total_shots, 4); // 3 known + 1 unknown counted in total but not buckets? -> total counts inRange (4)
  // Note: total counts ALL in-range rows including unknown category; bucket excludes unknown.
  const totalKnown = s.by_category.reduce((n, c) => n + c.count, 0);
  assert.equal(totalKnown, 3);
  assert.equal(s.by_category[0].category, "receipt");
  assert.equal(s.by_category[0].count, 2);
  assert.equal(Math.round(s.by_category[0].avg_confidence * 100), 90);
});

test("summarize: top_shots sorted by confidence desc, capped at 5", () => {
  const p = makePeriod(30, NOW);
  const rows: DigestRow[] = Array.from({ length: 10 }, (_, i) =>
    row({
      id: `r${i}`,
      filename: `f${i}.png`,
      confidence: i / 10,
      primary_category: "receipt",
      created_at: "2026-05-20T00:00:00Z",
    }),
  );
  const s = summarize(rows, p, NOW);
  assert.equal(s.top_shots.length, 5);
  assert.equal(s.top_shots[0].id, "r9");
  assert.ok(s.top_shots[0].confidence >= s.top_shots[4].confidence);
});

test("summarize: per_day buckets align to UTC day", () => {
  const p = makePeriod(3, NOW); // since=2026-05-29, until=2026-06-01
  const rows: DigestRow[] = [
    row({ created_at: "2026-05-30T01:00:00Z" }),
    row({ created_at: "2026-05-30T23:00:00Z" }),
    row({ created_at: "2026-05-31T05:00:00Z" }),
  ];
  const s = summarize(rows, p, NOW);
  const totals = Object.fromEntries(s.per_day.map((d) => [d.date, d.count]));
  assert.equal(totals["2026-05-30"], 2);
  assert.equal(totals["2026-05-31"], 1);
});

test("renderDigestText: empty window message has link to demo", () => {
  const p = makePeriod(7, NOW);
  const s = summarize([], p, NOW);
  const txt = renderDigestText(s, "https://app.example.com");
  assert.match(txt, /No classifications/);
  assert.match(txt, /https:\/\/app\.example\.com\/demo/);
});

test("renderDigestText: lists category counts and top shots", () => {
  const p = makePeriod(7, NOW);
  const rows: DigestRow[] = [
    row({ id: "top", filename: "great.png", confidence: 0.99, created_at: "2026-05-30T00:00:00Z" }),
  ];
  const s = summarize(rows, p, NOW);
  const txt = renderDigestText(s, "https://x");
  assert.match(txt, /Total shots: 1/);
  assert.match(txt, /receipt/i);
  assert.match(txt, /great\.png/);
  assert.match(txt, /https:\/\/x\/shots\/top/);
});

test("renderDigestHTML: escapes user-supplied filename", () => {
  const p = makePeriod(7, NOW);
  const rows: DigestRow[] = [
    row({ id: "x", filename: "<script>alert(1)</script>.png", confidence: 0.9, created_at: "2026-05-30T00:00:00Z" }),
  ];
  const s = summarize(rows, p, NOW);
  const html = renderDigestHTML(s, "https://x");
  assert.ok(!html.includes("<script>alert(1)</script>"));
  assert.match(html, /&lt;script&gt;/);
});

test("renderEml: contains MIME headers and both parts", () => {
  const eml = renderEml({
    to: "a@b.com",
    from: "noreply@shotclassify.local",
    subject: "Hi",
    text: "hello",
    html: "<b>hello</b>",
  });
  assert.match(eml, /^From: noreply@shotclassify\.local/m);
  assert.match(eml, /^To: a@b\.com/m);
  assert.match(eml, /^Subject: Hi/m);
  assert.match(eml, /multipart\/alternative/);
  assert.match(eml, /text\/plain/);
  assert.match(eml, /text\/html/);
  assert.match(eml, /hello/);
});
