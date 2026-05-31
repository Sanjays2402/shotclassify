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

export const ENDPOINTS = {
  history: (params?: { limit?: number; category?: string; q?: string }) => {
    const sp = new URLSearchParams();
    if (params?.limit) sp.set("limit", String(params.limit));
    if (params?.category) sp.set("category", params.category);
    if (params?.q) sp.set("q", params.q);
    const qs = sp.toString();
    return `/api/history${qs ? `?${qs}` : ""}`;
  },
  historyItem: (id: string) => `/api/shots/${encodeURIComponent(id)}`,
  stats: "/api/stats",
  aggregate: (hours: number = 24) => `/api/aggregate?hours=${hours}`,
  classify: "/api/classify",
};
