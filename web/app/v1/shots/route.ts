// GET /v1/shots — list shots for an API-key holder.
// Authenticated via 'Authorization: Bearer sk_live_...'.
// Forwards filter query string to upstream FastAPI /v1/history.
import { NextRequest, NextResponse } from "next/server";
import {
  authenticate,
  keyHeaders,
  proxyUpstream,
  v1Error,
} from "@/lib/v1auth";
import { filterShotListQuery } from "@/lib/v1-core";
import { withObservability } from "@/lib/observability";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const FORWARD_HEADERS = ["x-total-count", "x-offset", "x-limit"];

async function getHandler(req: NextRequest): Promise<Response> {
  const auth = await authenticate(req);
  if (auth instanceof NextResponse) return auth;

  const url = new URL(req.url);
  const filtered = filterShotListQuery(url.searchParams);
  if (!filtered.ok) {
    return v1Error(400, filtered.code, filtered.message);
  }
  const out = filtered.params;

  let upstream: Response;
  try {
    const qs = out.toString();
    upstream = await proxyUpstream(
      `/v1/history${qs ? `?${qs}` : ""}`,
    );
  } catch (err: any) {
    return v1Error(
      502,
      "upstream_unreachable",
      `Could not reach classifier service: ${err?.message || "unknown"}`,
    );
  }

  const body = await upstream.text();
  const headers: Record<string, string> = {
    "content-type":
      upstream.headers.get("content-type") ?? "application/json",
    ...keyHeaders(auth.key, auth.rateHeaders),
  };
  for (const h of FORWARD_HEADERS) {
    const v = upstream.headers.get(h);
    if (v) headers[h] = v;
  }
  return new NextResponse(body, { status: upstream.status, headers });
}

export const GET = withObservability("/v1/shots", getHandler);
