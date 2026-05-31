// Server-only HTML renderer for /embed/<id>. Plain string templating
// so it runs inside a route handler without React/JSX. Designed for
// iframe embeds on third-party sites: no external assets, inlined CSS,
// no JavaScript, no app chrome.

// Pure HTML renderer; safe to import from tests. The only callers in
// the app are server-side route handlers (see app/embed/[id]/route.ts
// and app/api/oembed/route.ts), so it never ships to the client bundle.
import type { ShareRecord } from "./share";
import {
  CATEGORIES,
  LONG,
  pct,
  shortId,
  type Category,
} from "./categories";

// Confidence color, inlined (the app uses CSS variables, but embeds
// must paint without site styles).
function confHex(score: number): string {
  if (score >= 0.85) return "#1f7a3a"; // high
  if (score >= 0.6) return "#b27a13"; // mid
  return "#a3242b"; // low
}

function escape(s: string): string {
  return s.replace(/[<>&"']/g, (c) => {
    if (c === "<") return "&lt;";
    if (c === ">") return "&gt;";
    if (c === "&") return "&amp;";
    if (c === '"') return "&quot;";
    return "&#39;";
  });
}

export function topDistribution(rec: ShareRecord, n = 4) {
  const cat = (rec.primary_category as Category) ?? "other";
  const raw =
    rec.classification?.confidences ??
    CATEGORIES.map((c) => ({
      category: c,
      score:
        c === cat
          ? rec.confidence
          : (1 - rec.confidence) / (CATEGORIES.length - 1),
    }));
  return [...raw].sort((a, b) => b.score - a.score).slice(0, n);
}

export function renderEmbedHtml(rec: ShareRecord): string {
  const cat = (rec.primary_category as Category) ?? "other";
  const primaryLabel = LONG[cat] ?? cat;
  const confPct = pct(rec.confidence, 1);
  const confColor = confHex(rec.confidence);
  const sid = shortId(rec.id);
  const filename = escape(rec.filename || "(no filename)");
  const top = topDistribution(rec, 4);

  const rows = top
    .map((d) => {
      const label = escape(LONG[d.category as Category] ?? d.category);
      const width = Math.max(2, Math.round(d.score * 100));
      const barColor = d.category === cat ? confColor : "#a3a3a3";
      return `<li style="display:grid;grid-template-columns:120px 1fr 48px;align-items:center;gap:8px;font-size:11px"><span style="color:#404040">${label}</span><div style="height:6px;background:#f0f0ea;border-radius:3px;overflow:hidden"><div style="width:${width}%;height:100%;background:${barColor}"></div></div><span style="font-variant-numeric:tabular-nums;text-align:right;color:#525252">${escape(pct(d.score, 1))}</span></li>`;
    })
    .join("");

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>ShotClassify result ${escape(sid)}</title>
<style>
  *,*::before,*::after{box-sizing:border-box}
  html,body{margin:0;padding:0;background:transparent;color:#171717;font-family:ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}
  a{color:inherit}
  .card{border:1px solid #e5e5e0;border-radius:8px;padding:14px 16px;background:#fff;max-width:560px;margin:8px auto;display:flex;flex-direction:column;gap:10px}
  .row-eyebrow{display:flex;align-items:center;justify-content:space-between;font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#737373}
  .row-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
  .row-head strong{font-size:18px;font-weight:600}
  .conf{font-variant-numeric:tabular-nums;font-size:22px}
  .filename{font-size:12px;color:#525252;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:4px}
  .footer-link{font-size:11px;color:#525252;text-decoration:none;border-top:1px solid #f0f0ea;padding-top:8px;display:flex;justify-content:space-between;align-items:center}
  .footer-link:hover{color:#171717}
  @media (prefers-color-scheme: dark){
    html,body{color:#e5e5e0}
    .card{background:#161614;border-color:#2a2a26}
    .row-eyebrow,.filename,.footer-link{color:#a3a3a3}
    .row-head strong{color:#fafaf7}
    ul li span:first-child{color:#d4d4d4}
    .footer-link{border-color:#2a2a26}
  }
</style>
</head>
<body>
<div class="card" role="article" aria-label="ShotClassify result">
  <div class="row-eyebrow"><span>ShotClassify</span><span style="font-variant-numeric:tabular-nums">${escape(sid)}</span></div>
  <div class="row-head">
    <strong>${escape(primaryLabel)}</strong>
    <span class="conf" style="color:${confColor}">${escape(confPct)}</span>
  </div>
  <div class="filename" title="${filename}">${filename}</div>
  <ul>${rows}</ul>
  <a class="footer-link" href="/r/${escape(rec.id)}" target="_top" rel="noopener">
    <span>View full result on ShotClassify</span><span aria-hidden>&rarr;</span>
  </a>
</div>
</body>
</html>`;
}
