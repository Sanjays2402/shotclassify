import { NextRequest, NextResponse } from "next/server";
import {
  deleteWebhook,
  getWebhook,
  setActive,
  testFire,
  listDeliveriesPage,
  listDeliveryEvents,
  redeliver,
} from "@/lib/webhooks";
import { DEFAULT_WORKSPACE_ID } from "@/lib/keystore";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const hook = await getWebhook(id, DEFAULT_WORKSPACE_ID);
  if (!hook) {
    return NextResponse.json(
      { error: { code: "not_found", message: "Webhook not found." } },
      { status: 404 },
    );
  }
  const sp = req.nextUrl.searchParams;
  const statusParam = sp.get("status");
  const eventParam = sp.get("event");
  const offset = Number.parseInt(sp.get("offset") || "0", 10) || 0;
  const limit = Number.parseInt(sp.get("limit") || "50", 10) || 50;
  const status =
    statusParam === "success" || statusParam === "failed" || statusParam === "pending"
      ? statusParam
      : undefined;
  const event = eventParam && eventParam.length > 0 ? eventParam : undefined;
  const page = await listDeliveriesPage(id, DEFAULT_WORKSPACE_ID, { status, event, offset, limit });
  const events = await listDeliveryEvents(id, DEFAULT_WORKSPACE_ID);
  return NextResponse.json({
    webhook: { ...hook, secret: undefined, secret_prefix: hook.secret.slice(0, 12) },
    deliveries: page.deliveries,
    total: page.total,
    offset: page.offset,
    limit: page.limit,
    has_more: page.has_more,
    events,
  });
}

export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const ok = await deleteWebhook(id, DEFAULT_WORKSPACE_ID);
  if (!ok) {
    return NextResponse.json(
      { error: { code: "not_found", message: "Webhook not found." } },
      { status: 404 },
    );
  }
  return NextResponse.json({ ok: true });
}

export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  let body: any = {};
  try {
    body = await req.json();
  } catch {
    return NextResponse.json(
      { error: { code: "invalid_json", message: "Body must be JSON." } },
      { status: 400 },
    );
  }
  if (body?.action === "test") {
    const hook = await getWebhook(id, DEFAULT_WORKSPACE_ID);
    if (!hook) {
      return NextResponse.json(
        { error: { code: "not_found", message: "Webhook not found." } },
        { status: 404 },
      );
    }
    const delivery = await testFire(hook);
    return NextResponse.json({ delivery });
  }
  if (body?.action === "redeliver") {
    const deliveryId = typeof body?.delivery_id === "string" ? body.delivery_id : "";
    if (!deliveryId) {
      return NextResponse.json(
        { error: { code: "invalid_input", message: "delivery_id is required." } },
        { status: 400 },
      );
    }
    const result = await redeliver(deliveryId, DEFAULT_WORKSPACE_ID);
    if ("error" in result) {
      return NextResponse.json(
        { error: { code: result.error, message: result.error === "delivery_not_found" ? "Delivery not found." : "Webhook no longer exists." } },
        { status: 404 },
      );
    }
    // Ensure the redelivered delivery belongs to this webhook.
    if (result.delivery.webhook_id !== id) {
      return NextResponse.json(
        { error: { code: "mismatch", message: "Delivery does not belong to this webhook." } },
        { status: 400 },
      );
    }
    return NextResponse.json({ delivery: result.delivery });
  }
  if (typeof body?.active === "boolean") {
    const updated = await setActive(id, body.active, DEFAULT_WORKSPACE_ID);
    if (!updated) {
      return NextResponse.json(
        { error: { code: "not_found", message: "Webhook not found." } },
        { status: 404 },
      );
    }
    return NextResponse.json({
      webhook: { ...updated, secret: undefined, secret_prefix: updated.secret.slice(0, 12) },
    });
  }
  return NextResponse.json(
    { error: { code: "no_op", message: "Provide 'active', action='test', or action='redeliver'." } },
    { status: 400 },
  );
}
