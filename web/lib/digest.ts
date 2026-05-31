// Activity digest aggregator.
//
// Pure functions: take a list of recent history rows and produce a
// structured summary plus plain-text + HTML renderings suitable for an
// email or an in-app preview. No I/O here so it can be unit-tested
// under plain `tsx --test` with no fixtures on disk.

import {
  CATEGORIES,
  LONG,
  type Category,
} from "./categories";

export type DigestRow = {
  id: string;
  filename?: string | null;
  primary_category: string;
  confidence: number;
  created_at: string;
  source?: string | null;
};

export type DigestPeriod = {
  days: number;
  since: string; // ISO
  until: string; // ISO
};

export type CategoryCount = {
  category: Category;
  label: string;
  count: number;
  avg_confidence: number;
};

export type TopShot = {
  id: string;
  filename: string;
  category: Category;
  confidence: number;
  created_at: string;
};

export type DigestSummary = {
  period: DigestPeriod;
  generated_at: string;
  total_shots: number;
  avg_confidence: number; // 0..1
  by_category: CategoryCount[]; // sorted desc by count
  top_shots: TopShot[];        // up to 5 highest-confidence
  per_day: { date: string; count: number }[]; // length = period.days
  empty: boolean;
};

function isCategory(v: string): v is Category {
  return (CATEGORIES as readonly string[]).includes(v);
}

function fmtDay(d: Date): string {
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function makePeriod(days: number, now: Date = new Date()): DigestPeriod {
  const clamped = Math.max(1, Math.min(90, Math.floor(days)));
  const until = new Date(now);
  const since = new Date(now);
  since.setUTCDate(since.getUTCDate() - clamped);
  return {
    days: clamped,
    since: since.toISOString(),
    until: until.toISOString(),
  };
}

export function summarize(
  rows: DigestRow[],
  period: DigestPeriod,
  now: Date = new Date(),
): DigestSummary {
  const sinceMs = Date.parse(period.since);
  const untilMs = Date.parse(period.until);
  const inRange = rows.filter((r) => {
    const t = Date.parse(r.created_at);
    return Number.isFinite(t) && t >= sinceMs && t <= untilMs;
  });

  const buckets = new Map<Category, { count: number; conf_sum: number }>();
  for (const r of inRange) {
    if (!isCategory(r.primary_category)) continue;
    const cur = buckets.get(r.primary_category) ?? { count: 0, conf_sum: 0 };
    cur.count += 1;
    cur.conf_sum += Number.isFinite(r.confidence) ? r.confidence : 0;
    buckets.set(r.primary_category, cur);
  }
  const by_category: CategoryCount[] = [...buckets.entries()]
    .map(([category, v]) => ({
      category,
      label: LONG[category],
      count: v.count,
      avg_confidence: v.count ? v.conf_sum / v.count : 0,
    }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));

  const top_shots: TopShot[] = inRange
    .filter((r) => isCategory(r.primary_category))
    .sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0))
    .slice(0, 5)
    .map((r) => ({
      id: r.id,
      filename: r.filename || r.id,
      category: r.primary_category as Category,
      confidence: r.confidence,
      created_at: r.created_at,
    }));

  // per_day buckets aligned to UTC day, oldest first.
  const per_day: { date: string; count: number }[] = [];
  const startOfDay = new Date(period.since);
  startOfDay.setUTCHours(0, 0, 0, 0);
  for (let i = 0; i < period.days; i++) {
    const d = new Date(startOfDay);
    d.setUTCDate(d.getUTCDate() + i);
    per_day.push({ date: fmtDay(d), count: 0 });
  }
  const dayIndex = new Map(per_day.map((d, i) => [d.date, i]));
  for (const r of inRange) {
    const d = new Date(r.created_at);
    if (Number.isNaN(d.getTime())) continue;
    const key = fmtDay(d);
    const idx = dayIndex.get(key);
    if (idx != null) per_day[idx].count += 1;
  }

  const total = inRange.length;
  const conf_sum = inRange.reduce(
    (s, r) => s + (Number.isFinite(r.confidence) ? r.confidence : 0),
    0,
  );
  return {
    period,
    generated_at: now.toISOString(),
    total_shots: total,
    avg_confidence: total ? conf_sum / total : 0,
    by_category,
    top_shots,
    per_day,
    empty: total === 0,
  };
}

function pct(n: number): string {
  return `${Math.round(n * 100)}%`;
}

export function renderDigestText(s: DigestSummary, appUrl: string): string {
  const lines: string[] = [];
  const since = s.period.since.slice(0, 10);
  const until = s.period.until.slice(0, 10);
  lines.push(`ShotClassify activity, ${since} to ${until}`);
  lines.push("");
  if (s.empty) {
    lines.push("No classifications in this window. Run one at " + appUrl + "/demo");
    return lines.join("\n");
  }
  lines.push(`Total shots: ${s.total_shots}`);
  lines.push(`Average confidence: ${pct(s.avg_confidence)}`);
  lines.push("");
  lines.push("By category:");
  for (const c of s.by_category) {
    lines.push(`  ${c.label.padEnd(14)} ${String(c.count).padStart(4)}  avg ${pct(c.avg_confidence)}`);
  }
  if (s.top_shots.length) {
    lines.push("");
    lines.push("Top confidence:");
    for (const t of s.top_shots) {
      lines.push(`  ${pct(t.confidence)}  ${t.category.padEnd(8)} ${t.filename}`);
      lines.push(`         ${appUrl}/shots/${t.id}`);
    }
  }
  lines.push("");
  lines.push(`View full history: ${appUrl}/shots`);
  return lines.join("\n");
}

function esc(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function renderDigestHTML(s: DigestSummary, appUrl: string): string {
  const since = s.period.since.slice(0, 10);
  const until = s.period.until.slice(0, 10);
  if (s.empty) {
    return `<!doctype html><meta charset="utf-8"><div style="font:14px system-ui;padding:24px">
<h2 style="margin:0 0 8px">ShotClassify activity</h2>
<p style="color:#666;margin:0 0 16px">${esc(since)} to ${esc(until)}</p>
<p>No classifications in this window. <a href="${esc(appUrl)}/demo">Run one</a>.</p>
</div>`;
  }
  const catRows = s.by_category
    .map(
      (c) => `<tr>
<td style="padding:6px 12px 6px 0">${esc(c.label)}</td>
<td style="padding:6px 12px;text-align:right;font-variant-numeric:tabular-nums">${c.count}</td>
<td style="padding:6px 0;text-align:right;color:#666">${pct(c.avg_confidence)}</td>
</tr>`,
    )
    .join("");
  const topRows = s.top_shots
    .map(
      (t) => `<li style="margin:4px 0">
<a href="${esc(appUrl)}/shots/${esc(t.id)}" style="color:#111;text-decoration:none">
<strong>${pct(t.confidence)}</strong>
<span style="color:#888;margin:0 6px">${esc(t.category)}</span>
${esc(t.filename)}
</a>
</li>`,
    )
    .join("");
  const maxCount = Math.max(1, ...s.per_day.map((d) => d.count));
  const spark = s.per_day
    .map((d) => {
      const h = Math.max(2, Math.round((d.count / maxCount) * 32));
      return `<span title="${esc(d.date)}: ${d.count}" style="display:inline-block;width:8px;height:${h}px;background:#111;margin-right:2px;vertical-align:bottom"></span>`;
    })
    .join("");
  return `<!doctype html><meta charset="utf-8"><div style="font:14px/1.5 system-ui,Segoe UI,Helvetica,Arial;color:#111;padding:24px;max-width:560px">
<h2 style="margin:0 0 4px;font-size:18px">ShotClassify activity</h2>
<p style="color:#666;margin:0 0 16px">${esc(since)} to ${esc(until)}</p>
<div style="display:flex;gap:24px;margin:0 0 16px">
<div><div style="color:#888;font-size:12px">Total shots</div><div style="font-size:22px;font-weight:600">${s.total_shots}</div></div>
<div><div style="color:#888;font-size:12px">Avg confidence</div><div style="font-size:22px;font-weight:600">${pct(s.avg_confidence)}</div></div>
</div>
<div style="margin:0 0 20px">${spark}</div>
<h3 style="margin:16px 0 6px;font-size:14px">By category</h3>
<table style="border-collapse:collapse;width:100%;font-size:13px">${catRows}</table>
<h3 style="margin:20px 0 6px;font-size:14px">Top confidence</h3>
<ul style="padding-left:18px;margin:0">${topRows}</ul>
<p style="margin:20px 0 0;font-size:12px;color:#666">
<a href="${esc(appUrl)}/shots" style="color:#666">View full history</a>
</p>
</div>`;
}

export function renderEml(opts: {
  to: string;
  from: string;
  subject: string;
  text: string;
  html: string;
}): string {
  const boundary = `=_shotclassify_${Date.now().toString(36)}`;
  const headers = [
    `From: ${opts.from}`,
    `To: ${opts.to}`,
    `Subject: ${opts.subject}`,
    `Date: ${new Date().toUTCString()}`,
    `MIME-Version: 1.0`,
    `Content-Type: multipart/alternative; boundary="${boundary}"`,
  ].join("\r\n");
  const body = [
    ``,
    `--${boundary}`,
    `Content-Type: text/plain; charset=utf-8`,
    `Content-Transfer-Encoding: 8bit`,
    ``,
    opts.text,
    `--${boundary}`,
    `Content-Type: text/html; charset=utf-8`,
    `Content-Transfer-Encoding: 8bit`,
    ``,
    opts.html,
    `--${boundary}--`,
    ``,
  ].join("\r\n");
  return headers + "\r\n" + body;
}
