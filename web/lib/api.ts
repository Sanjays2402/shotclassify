// SWR fetcher + endpoint paths.
// All browser requests go through the Next.js route handlers under /api/*,
// which proxy to the FastAPI service.
export const fetcher = async (url: string) => {
  const r = await fetch(url, { credentials: "same-origin" });
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    const err = new Error(text || `${r.status} ${r.statusText}`) as Error & {
      status?: number;
    };
    err.status = r.status;
    throw err;
  }
  return r.json();
};

export const fetcherWithMeta = async (url: string) => {
  const r = await fetch(url, { credentials: "same-origin" });
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    const err = new Error(text || `${r.status} ${r.statusText}`) as Error & {
      status?: number;
    };
    err.status = r.status;
    throw err;
  }
  const data = await r.json();
  const total = Number(r.headers.get("x-total-count") ?? "");
  const offset = Number(r.headers.get("x-offset") ?? "");
  const limit = Number(r.headers.get("x-limit") ?? "");
  return {
    data,
    total: Number.isFinite(total) ? total : undefined,
    offset: Number.isFinite(offset) ? offset : undefined,
    limit: Number.isFinite(limit) ? limit : undefined,
  } as { data: any; total?: number; offset?: number; limit?: number };
};

export const ENDPOINTS = {
  history: (params?: {
    limit?: number;
    category?: string;
    q?: string;
    offset?: number;
    since?: string;
    until?: string;
    min_conf?: number;
    max_conf?: number;
    sort?: "new" | "old" | "conf_asc" | "conf_desc";
  }) => {
    const sp = new URLSearchParams();
    if (params?.limit) sp.set("limit", String(params.limit));
    if (params?.offset) sp.set("offset", String(params.offset));
    if (params?.category) sp.set("category", params.category);
    if (params?.q) sp.set("q", params.q);
    if (params?.since) sp.set("since", params.since);
    if (params?.until) sp.set("until", params.until);
    if (params?.min_conf != null) sp.set("min_conf", String(params.min_conf));
    if (params?.max_conf != null) sp.set("max_conf", String(params.max_conf));
    if (params?.sort) sp.set("sort", params.sort);
    const qs = sp.toString();
    return `/api/history${qs ? `?${qs}` : ""}`;
  },
  historyItem: (id: string) => `/api/shots/${encodeURIComponent(id)}`,
  stats: "/api/stats",
  aggregate: (hours: number = 24) => `/api/aggregate?hours=${hours}`,
  classify: "/api/classify",
  historyExport: (params?: {
    format?: "csv" | "json";
    limit?: number;
    category?: string;
    q?: string;
  }) => {
    const sp = new URLSearchParams();
    sp.set("format", params?.format ?? "csv");
    if (params?.limit) sp.set("limit", String(params.limit));
    if (params?.category) sp.set("category", params.category);
    if (params?.q) sp.set("q", params.q);
    return `/api/history/export?${sp.toString()}`;
  },
};
