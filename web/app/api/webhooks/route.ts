import { NextRequest, NextResponse } from "next/server";
import {
  listWebhooks,
  createWebhook,
  listDeliveries,
} from "@/lib/webhooks";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const includeDeliveries = url.searchParams.get("deliveries") === "1";
  const hooks = await listWebhooks();
  const safe = hooks.map((h) => ({
    ...h,
    // Never re-leak the secret on list. Show prefix only.
    secret: undefined,
    secret_prefix: h.secret.slice(0, 12),
  }));
  if (!includeDeliveries) {
    return NextResponse.json({ webhooks: safe });
  }
  const deliveries = await listDeliveries(undefined, 50);
  return NextResponse.json({ webhooks: safe, deliveries });
}

export async function POST(req: NextRequest) {
  let body: any = {};
  try {
    body = await req.json();
  } catch {
    return NextResponse.json(
      { error: { code: "invalid_json", message: "Body must be JSON." } },
      { status: 400 },
    );
  }
  try {
    const hook = await createWebhook({
      url: body?.url,
      description: body?.description,
      events: Array.isArray(body?.events) ? body.events : undefined,
    });
    // Secret returned once at creation.
    return NextResponse.json({ webhook: hook }, { status: 201 });
  } catch (err: any) {
    return NextResponse.json(
      {
        error: {
          code: "invalid_webhook",
          message: err?.message || "Could not create webhook.",
        },
      },
      { status: 400 },
    );
  }
}
