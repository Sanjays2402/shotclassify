// GET /v1/shots/[id] — fetch a single shot for an API-key holder.
import { NextRequest, NextResponse } from "next/server";
import {
  authenticate,
  keyHeaders,
  proxyUpstream,
  v1Error,
} from "@/lib/v1auth";
import { isValidShotId } from "@/lib/v1-core";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const auth = await authenticate(req);
  if (auth instanceof NextResponse) return auth;

  const { id } = await ctx.params;
  if (!id || !isValidShotId(id)) {
    return v1Error(400, "invalid_id", "Shot id is missing or malformed.");
  }

  let upstream: Response;
  try {
    upstream = await proxyUpstream(`/v1/history/${encodeURIComponent(id)}`);
  } catch (err: any) {
    return v1Error(
      502,
      "upstream_unreachable",
      `Could not reach classifier service: ${err?.message || "unknown"}`,
    );
  }

  if (upstream.status === 404) {
    return v1Error(404, "not_found", `No shot with id '${id}'.`);
  }
  const body = await upstream.text();
  return new NextResponse(body, {
    status: upstream.status,
    headers: {
      "content-type":
        upstream.headers.get("content-type") ?? "application/json",
      ...keyHeaders(auth.key),
    },
  });
}
