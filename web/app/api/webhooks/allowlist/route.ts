// Admin-facing endpoint to read/update the hostname allowlist used by the
// webhook SSRF guard. Matches the trust posture of the rest of /api/webhooks
// (dashboard session, not a programmatic API key).
import { NextRequest, NextResponse } from "next/server";
import {
  readWebhookAllowlist,
  writeWebhookAllowlist,
} from "@/lib/webhook-allowlist";
import { DEFAULT_WORKSPACE_ID } from "@/lib/keystore";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const hostnames = await readWebhookAllowlist(DEFAULT_WORKSPACE_ID);
  return NextResponse.json({ hostnames });
}

export async function PUT(req: NextRequest) {
  let body: any = null;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json(
      { error: { code: "invalid_json", message: "Body must be JSON." } },
      { status: 400 },
    );
  }
  const input = Array.isArray(body?.hostnames) ? body.hostnames : null;
  if (input === null) {
    return NextResponse.json(
      {
        error: {
          code: "invalid_input",
          message: "Field 'hostnames' must be an array of strings.",
        },
      },
      { status: 400 },
    );
  }
  const accepted = await writeWebhookAllowlist(input, DEFAULT_WORKSPACE_ID);
  const rejected = input.filter(
    (v: unknown) => typeof v === "string" && !accepted.includes(v.trim().toLowerCase()),
  );
  return NextResponse.json({ hostnames: accepted, rejected });
}
