// Prometheus exposition endpoint. Text format v0.0.4. Scraping is the only
// supported caller. Public by design: a Prometheus server inside the cluster
// pulls this without an Authorization header. If you need to lock it down,
// gate at the ingress (NetworkPolicy + ServiceMonitor selector) which is what
// the existing Helm chart already does.
import { metrics, resolveRequestId } from "@/lib/metrics";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: Request): Promise<Response> {
  const rid = resolveRequestId(req.headers);
  const body = metrics.render();
  return new Response(body, {
    status: 200,
    headers: {
      "content-type": "text/plain; version=0.0.4; charset=utf-8",
      "cache-control": "no-store",
      "x-request-id": rid,
    },
  });
}
