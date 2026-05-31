import { NextRequest, NextResponse } from "next/server";
import {
  deleteWebhook,
  getWebhook,
  setActive,
  testFire,
  listDeliveries,
} from "@/lib/webhooks";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const hook = await getWebhook(id);
  if (!hook) {
    return NextResponse.json(
      { error: { code: "not_found", message: "Webhook not found." } },
      { status: 404 },
    );
  }
  const deliveries = await listDeliveries(id, 50);
  return NextResponse.json({
    webhook: { ...hook, secret: undefined, secret_prefix: hook.secret.slice(0, 12) },
    deliveries,
  });
}

export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const ok = await deleteWebhook(id);
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
    const hook = await getWebhook(id);
    if (!hook) {
      return NextResponse.json(
        { error: { code: "not_found", message: "Webhook not found." } },
        { status: 404 },
      );
    }
    const delivery = await testFire(hook);
    return NextResponse.json({ delivery });
  }
  if (typeof body?.active === "boolean") {
    const updated = await setActive(id, body.active);
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
    { error: { code: "no_op", message: "Provide 'active' or action='test'." } },
    { status: 400 },
  );
}
