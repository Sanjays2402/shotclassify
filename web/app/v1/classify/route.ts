// Public programmatic endpoint. Authenticates with a user-generated
// sk_live_* token via Authorization: Bearer ..., then proxies the
// multipart form-data body to the upstream FastAPI /v1/classify.
import { NextRequest, NextResponse } from "next/server";
import { verifyAndTouch } from "@/lib/keystore";
import { dispatchEvent } from "@/lib/webhooks";
import { notifyClassifyCompleted } from "@/lib/notifications";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";
const UPSTREAM_KEY = process.env.SHOTCLASSIFY_API_KEY || "";

function extractToken(req: NextRequest): string | null {
  const auth = req.headers.get("authorization") || "";
  const m = auth.match(/^Bearer\s+(\S+)$/i);
  if (m) return m[1];
  const xk = req.headers.get("x-api-key");
  if (xk) return xk;
  return null;
}

function errorResponse(status: number, code: string, message: string) {
  return NextResponse.json(
    { error: { code, message } },
    { status, headers: { "content-type": "application/json" } },
  );
}

export async function POST(req: NextRequest) {
  const token = extractToken(req);
  if (!token) {
    return errorResponse(
      401,
      "missing_credentials",
      "Provide an API key via 'Authorization: Bearer sk_live_...'",
    );
  }
  const key = await verifyAndTouch(token);
  if (!key) {
    return errorResponse(401, "invalid_key", "API key is invalid or revoked.");
  }

  // Validate body: must be multipart/form-data with a 'file' field.
  const ctype = req.headers.get("content-type") || "";
  if (!ctype.toLowerCase().includes("multipart/form-data")) {
    return errorResponse(
      400,
      "invalid_content_type",
      "Expected multipart/form-data with a 'file' field.",
    );
  }
  let fd: FormData;
  try {
    fd = await req.formData();
  } catch {
    return errorResponse(400, "invalid_body", "Could not parse multipart body.");
  }
  const file = fd.get("file");
  if (!(file instanceof Blob)) {
    return errorResponse(400, "missing_file", "Field 'file' is required.");
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${API}/v1/classify`, {
      method: "POST",
      headers: UPSTREAM_KEY ? { "x-api-key": UPSTREAM_KEY } : {},
      body: fd,
    });
  } catch (err: any) {
    return errorResponse(
      502,
      "upstream_unreachable",
      `Could not reach classifier service: ${err?.message || "unknown"}`,
    );
  }

  const body = await upstream.text();
  if (upstream.ok) {
    try {
      const parsed = JSON.parse(body);
      dispatchEvent("classify.completed", {
        event: "classify.completed",
        delivered_at: new Date().toISOString(),
        source: "/v1/classify",
        api_key_id: key.id,
        result: parsed,
      }).catch(() => {});
      notifyClassifyCompleted(parsed).catch(() => {});
    } catch {
      /* non-json upstream, skip */
    }
  }
  return new NextResponse(body, {
    status: upstream.status,
    headers: {
      "content-type":
        upstream.headers.get("content-type") ?? "application/json",
      "x-api-key-id": key.id,
      "x-api-key-usage": String(key.usage_count),
    },
  });
}

export async function GET() {
  return NextResponse.json({
    name: "shotclassify",
    version: "v1",
    endpoint: "POST /v1/classify",
    auth: "Authorization: Bearer sk_live_...",
    body: "multipart/form-data; field 'file' = image",
  });
}
