import { NextRequest, NextResponse } from "next/server";
import {
  deleteKey,
  getKey,
  renameKey,
  setKeyScopes,
  dailyUsageSeries,
} from "@/lib/keystore";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function strip(key: Awaited<ReturnType<typeof getKey>>) {
  if (!key) return null;
  const { hash, ...safe } = key;
  return safe;
}

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  if (!id) {
    return NextResponse.json({ error: "missing id" }, { status: 400 });
  }
  const key = await getKey(id);
  if (!key) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  const url = new URL(req.url);
  const days = Math.max(
    7,
    Math.min(180, Number.parseInt(url.searchParams.get("days") || "30", 10) || 30),
  );
  return NextResponse.json({
    key: strip(key),
    usage: {
      window_days: days,
      series: dailyUsageSeries(key, days),
      total: Object.values(key.daily_usage ?? {}).reduce(
        (a, b) => a + (b ?? 0),
        0,
      ),
    },
  });
}

export async function PATCH(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  if (!id) {
    return NextResponse.json({ error: "missing id" }, { status: 400 });
  }
  let body: any = {};
  try {
    body = await req.json();
  } catch {
    return NextResponse.json(
      { error: { code: "invalid_json", message: "Body must be JSON." } },
      { status: 400 },
    );
  }
  let updated = await getKey(id);
  if (!updated) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  if (typeof body?.name === "string") {
    const renamed = await renameKey(id, body.name);
    if (!renamed) {
      return NextResponse.json(
        {
          error: {
            code: "invalid_name",
            message: "Name must be 1 to 80 characters.",
          },
        },
        { status: 400 },
      );
    }
    updated = renamed;
  }
  if (Array.isArray(body?.scopes)) {
    const scoped = await setKeyScopes(id, body.scopes);
    if (scoped) updated = scoped;
  }
  return NextResponse.json({ key: strip(updated) });
}

export async function DELETE(
  _req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  if (!id) {
    return NextResponse.json({ error: "missing id" }, { status: 400 });
  }
  const ok = await deleteKey(id);
  if (!ok) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  return NextResponse.json({ ok: true });
}
