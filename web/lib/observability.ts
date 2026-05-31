// Wrap a Next route handler so every response carries an x-request-id and the
// request is recorded into the Prometheus registry. Use the templated route
// (e.g. `/v1/shots/:id`) to keep label cardinality bounded.
import { NextRequest, NextResponse } from "next/server";
import { recordHttp, resolveRequestId } from "@/lib/metrics";

type Handler<P> = (
  req: NextRequest,
  ctx: P,
) => Promise<Response> | Response;

export function withObservability<P>(
  route: string,
  handler: Handler<P>,
): Handler<P> {
  return async (req: NextRequest, ctx: P) => {
    const start = performance.now();
    const rid = resolveRequestId(req.headers);
    let res: Response;
    let status = 500;
    try {
      const out = await handler(req, ctx);
      res = out;
      status = out.status;
    } catch (err) {
      const message = err instanceof Error ? err.message : "internal_error";
      res = NextResponse.json(
        { error: { code: "internal_error", message } },
        { status: 500 },
      );
      status = 500;
    } finally {
      const dur = performance.now() - start;
      recordHttp(route, req.method, status, dur);
    }
    // Mutating headers on the returned Response is safe and avoids cloning.
    res.headers.set("x-request-id", rid);
    return res;
  };
}
