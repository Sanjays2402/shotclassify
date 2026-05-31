// Admin API for per-workspace rate-limit configuration.
//
// Auth: requires an sk_live_* API key with the 'admin' scope. The key's
// workspace is the workspace being inspected or mutated; cross-tenant reads
// or writes are impossible because we derive the workspace from the bearer
// key rather than trusting a path or header.
//
// GET  /api/ratelimit  -> current config + live usage snapshot
// PUT  /api/ratelimit  -> { plan?: "free"|"pro"|"team"|"custom",
//                           limits?: Partial<Limits> }
import { NextRequest, NextResponse } from "next/server";
import { authenticate, rateSnapshot } from "@/lib/v1auth";
import { workspaceOf } from "@/lib/keystore";
import {
  getWorkspaceConfig,
  setWorkspaceConfig,
  PLAN_DEFAULTS,
} from "@/lib/ratelimit";
import { withObservability } from "@/lib/observability";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function getHandler(req: NextRequest): Promise<Response> {
  const auth = await authenticate(req, "admin");
  if (auth instanceof NextResponse) return auth;
  const ws = workspaceOf(auth.key);
  const cfg = await getWorkspaceConfig(ws);
  return NextResponse.json(
    {
      workspace_id: ws,
      plan: cfg.plan,
      limits: cfg.limits,
      used: rateSnapshot(auth.key),
      plan_defaults: PLAN_DEFAULTS,
    },
    { headers: { "cache-control": "no-store" } },
  );
}

async function putHandler(req: NextRequest): Promise<Response> {
  const auth = await authenticate(req, "admin");
  if (auth instanceof NextResponse) return auth;

  let payload: unknown;
  try {
    payload = await req.json();
  } catch {
    return NextResponse.json(
      { error: { code: "invalid_body", message: "Body must be JSON." } },
      { status: 400 },
    );
  }
  const o = (payload ?? {}) as Record<string, unknown>;
  const plan = o.plan;
  if (plan !== undefined && plan !== "free" && plan !== "pro" && plan !== "team" && plan !== "custom") {
    return NextResponse.json(
      { error: { code: "invalid_plan", message: "plan must be free, pro, team, or custom." } },
      { status: 400 },
    );
  }
  const limits = o.limits;
  if (limits !== undefined && (limits === null || typeof limits !== "object")) {
    return NextResponse.json(
      { error: { code: "invalid_limits", message: "limits must be an object." } },
      { status: 400 },
    );
  }
  const cfg = await setWorkspaceConfig(workspaceOf(auth.key), {
    plan: plan as "free" | "pro" | "team" | "custom" | undefined,
    limits: (limits ?? undefined) as Record<string, number> | undefined,
  });
  return NextResponse.json({ ok: true, config: cfg });
}

export const GET = withObservability("/api/ratelimit", getHandler);
export const PUT = withObservability("/api/ratelimit", putHandler);
