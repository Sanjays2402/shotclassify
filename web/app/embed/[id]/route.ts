// Chrome-less embeddable result card returned as raw HTML.
// Implemented as a route handler so it bypasses the root layout
// (header, ticker, footer) and renders cleanly inside an iframe on
// third-party sites like Notion, Medium, Discourse, or a personal blog.
//
// URL shape:    /embed/<shot-id>
// Headers:      X-Frame-Options is intentionally omitted; CSP frame-ancestors
//               is set to '*' so any origin can embed.
// Caching:      public, s-maxage=300, stale-while-revalidate=86400

import { NextResponse } from "next/server";
import { fetchShareRecord } from "@/lib/share";
import { renderEmbedHtml } from "@/lib/embed";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ id: string }> };

export async function GET(_req: Request, ctx: Ctx): Promise<Response> {
  const { id } = await ctx.params;
  if (!id || !/^[a-zA-Z0-9_-]{1,64}$/.test(id)) {
    return new NextResponse(notFoundHtml("Invalid id"), {
      status: 400,
      headers: htmlHeaders(),
    });
  }
  const rec = await fetchShareRecord(id);
  if (!rec) {
    return new NextResponse(notFoundHtml("Result not found"), {
      status: 404,
      headers: htmlHeaders(),
    });
  }
  const html = renderEmbedHtml(rec);
  return new NextResponse(html, { status: 200, headers: htmlHeaders() });
}

function htmlHeaders(): HeadersInit {
  return {
    "content-type": "text/html; charset=utf-8",
    "cache-control": "public, s-maxage=300, stale-while-revalidate=86400",
    "content-security-policy": "frame-ancestors *",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
  };
}

function notFoundHtml(msg: string): string {
  const safe = msg.replace(/[<>&]/g, (c) =>
    c === "<" ? "&lt;" : c === ">" ? "&gt;" : "&amp;",
  );
  return `<!doctype html><html><head><meta charset="utf-8"><title>ShotClassify</title></head><body style="margin:0;padding:24px;font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;color:#525252;background:#fafaf7"><div style="border:1px solid #e5e5e0;border-radius:8px;padding:16px;background:#fff;max-width:560px;margin:0 auto;font-size:13px">${safe}</div></body></html>`;
}
