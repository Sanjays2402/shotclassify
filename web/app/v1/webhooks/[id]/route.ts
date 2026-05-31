// GET    /v1/webhooks/[id] — fetch a webhook subscription
// DELETE /v1/webhooks/[id] — remove a subscription
import { NextRequest, NextResponse } from "next/server";
import { authenticate, v1Error } from "@/lib/v1auth";
import { deleteWebhook, getWebhook, type Webhook } from "@/lib/webhooks";
import { workspaceOf } from "@/lib/keystore";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function publicView(hook: Webhook) {
  const { secret, ...rest } = hook;
  return { ...rest, secret_prefix: secret.slice(0, 12) };
}

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const auth = await authenticate(req, "read");
  if (auth instanceof NextResponse) return auth;

  const { id } = await ctx.params;
  if (!id) return v1Error(400, "invalid_id", "Missing webhook id.");

  const hook = await getWebhook(id, workspaceOf(auth.key));
  if (!hook) {
    return v1Error(404, "not_found", `No webhook with id '${id}'.`);
  }
  return NextResponse.json({ webhook: publicView(hook) });
}

export async function DELETE(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const auth = await authenticate(req, "admin");
  if (auth instanceof NextResponse) return auth;

  const { id } = await ctx.params;
  if (!id) return v1Error(400, "invalid_id", "Missing webhook id.");

  const ok = await deleteWebhook(id, workspaceOf(auth.key));
  if (!ok) {
    return v1Error(404, "not_found", `No webhook with id '${id}'.`);
  }
  return NextResponse.json({ deleted: id });
}
