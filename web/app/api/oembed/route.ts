// oEmbed provider endpoint for ShotClassify result share pages.
//
// Spec: https://oembed.com/  (rich type)
// Discovery: /r/<id> pages include a <link rel="alternate"
//   type="application/json+oembed" href="/api/oembed?url=...">
//
// Consumers (Notion, Discourse, Medium, custom) call this with the
// canonical /r/<id> URL and receive a JSON document pointing to
// /embed/<id>, which serves a chrome-less HTML card.

import { NextResponse } from "next/server";
import { fetchShareRecord } from "@/lib/share";
import { LONG, pct, type Category } from "@/lib/categories";

export const dynamic = "force-dynamic";

const DEFAULT_WIDTH = 560;
const DEFAULT_HEIGHT = 280;
const MAX_WIDTH = 1024;
const MIN_WIDTH = 280;

function siteBaseFromRequest(req: Request): string {
  const env = process.env.NEXT_PUBLIC_SITE_URL?.trim();
  if (env) return env.replace(/\/+$/, "");
  try {
    const u = new URL(req.url);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "";
  }
}

function parseShotIdFromUrl(target: string, siteBase: string): string | null {
  let u: URL;
  try {
    u = new URL(target);
  } catch {
    return null;
  }
  // Loose host match: only accept same-host (or any host if siteBase empty
  // during local dev) to avoid being an open redirect/discovery proxy.
  if (siteBase) {
    try {
      const expected = new URL(siteBase);
      if (u.host !== expected.host) return null;
    } catch {
      // fall through
    }
  }
  const m = u.pathname.match(/^\/r\/([a-zA-Z0-9_-]{1,64})\/?$/);
  return m ? m[1] : null;
}

function clampWidth(raw: string | null): number {
  const n = raw ? Math.floor(Number(raw)) : DEFAULT_WIDTH;
  if (!Number.isFinite(n) || n <= 0) return DEFAULT_WIDTH;
  return Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, n));
}

export async function GET(req: Request) {
  const url = new URL(req.url);
  const target = url.searchParams.get("url");
  const format = (url.searchParams.get("format") ?? "json").toLowerCase();
  const maxwidth = clampWidth(url.searchParams.get("maxwidth"));
  const height = DEFAULT_HEIGHT;

  if (format !== "json") {
    return NextResponse.json(
      { error: "unsupported_format", supported: ["json"] },
      { status: 501 },
    );
  }
  if (!target) {
    return NextResponse.json(
      { error: "missing_url" },
      { status: 400 },
    );
  }

  const siteBase = siteBaseFromRequest(req);
  const id = parseShotIdFromUrl(target, siteBase);
  if (!id) {
    return NextResponse.json(
      { error: "not_a_share_url" },
      { status: 404 },
    );
  }
  const rec = await fetchShareRecord(id);
  if (!rec) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }

  const cat = (rec.primary_category as Category) ?? "other";
  const label = LONG[cat] ?? cat;
  const title = `${label} · ${pct(rec.confidence, 1)} · ShotClassify`;
  const embedUrl = `${siteBase}/embed/${encodeURIComponent(rec.id)}`;
  const safeMaxWidth = maxwidth;
  const html = `<iframe src="${embedUrl}" width="${safeMaxWidth}" height="${height}" frameborder="0" loading="lazy" allowtransparency="true" referrerpolicy="no-referrer" title="${escapeAttr(title)}" style="border:0;max-width:100%"></iframe>`;

  return NextResponse.json(
    {
      version: "1.0",
      type: "rich",
      provider_name: "ShotClassify",
      provider_url: siteBase || "https://shotclassify.app",
      title,
      author_name: "ShotClassify",
      author_url: siteBase ? `${siteBase}/r/${rec.id}` : undefined,
      html,
      width: safeMaxWidth,
      height,
      cache_age: 300,
    },
    {
      status: 200,
      headers: {
        "cache-control": "public, s-maxage=300, stale-while-revalidate=86400",
        "access-control-allow-origin": "*",
      },
    },
  );
}

function escapeAttr(s: string): string {
  return s.replace(/[<>&"']/g, (c) => {
    if (c === "<") return "&lt;";
    if (c === ">") return "&gt;";
    if (c === "&") return "&amp;";
    if (c === '"') return "&quot;";
    return "&#39;";
  });
}
