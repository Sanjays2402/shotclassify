// In-process Prometheus metrics collector. Deliberately tiny and dependency-free
// so it works in the Next.js node runtime without pulling prom-client. Counters
// and a fixed-bucket histogram are enough for HTTP request observability and a
// readiness probe. Process-wide state is intentional: scraping happens against
// a single Next process, and Helm runs N pods that Prometheus aggregates.

export type LabelValues = Record<string, string>;

type CounterSeries = { labels: LabelValues; value: number };
type HistogramSeries = {
  labels: LabelValues;
  buckets: number[]; // upper bounds, in seconds
  counts: number[]; // cumulative-by-bucket counts, same length as buckets
  sum: number;
  count: number;
};

const DEFAULT_BUCKETS_SECONDS = [
  0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10,
];

function labelKey(labels: LabelValues): string {
  const keys = Object.keys(labels).sort();
  return keys.map((k) => `${k}=${labels[k]}`).join("|");
}

function escapeLabelValue(v: string): string {
  return v.replace(/\\/g, "\\\\").replace(/\n/g, "\\n").replace(/"/g, '\\"');
}

function renderLabels(labels: LabelValues): string {
  const keys = Object.keys(labels).sort();
  if (keys.length === 0) return "";
  const parts = keys.map((k) => `${k}="${escapeLabelValue(labels[k])}"`);
  return `{${parts.join(",")}}`;
}

class Counter {
  readonly name: string;
  readonly help: string;
  private series = new Map<string, CounterSeries>();

  constructor(name: string, help: string) {
    this.name = name;
    this.help = help;
  }

  inc(labels: LabelValues = {}, by = 1): void {
    const key = labelKey(labels);
    const existing = this.series.get(key);
    if (existing) {
      existing.value += by;
    } else {
      this.series.set(key, { labels: { ...labels }, value: by });
    }
  }

  render(): string {
    const lines: string[] = [
      `# HELP ${this.name} ${this.help}`,
      `# TYPE ${this.name} counter`,
    ];
    for (const s of this.series.values()) {
      lines.push(`${this.name}${renderLabels(s.labels)} ${s.value}`);
    }
    return lines.join("\n");
  }

  reset(): void {
    this.series.clear();
  }
}

class Histogram {
  readonly name: string;
  readonly help: string;
  readonly buckets: number[];
  private series = new Map<string, HistogramSeries>();

  constructor(name: string, help: string, buckets = DEFAULT_BUCKETS_SECONDS) {
    this.name = name;
    this.help = help;
    this.buckets = buckets;
  }

  observe(labels: LabelValues, value: number): void {
    const key = labelKey(labels);
    let s = this.series.get(key);
    if (!s) {
      s = {
        labels: { ...labels },
        buckets: this.buckets.slice(),
        counts: new Array(this.buckets.length).fill(0),
        sum: 0,
        count: 0,
      };
      this.series.set(key, s);
    }
    s.sum += value;
    s.count += 1;
    for (let i = 0; i < s.buckets.length; i++) {
      if (value <= s.buckets[i]) s.counts[i] += 1;
    }
  }

  render(): string {
    const lines: string[] = [
      `# HELP ${this.name} ${this.help}`,
      `# TYPE ${this.name} histogram`,
    ];
    for (const s of this.series.values()) {
      for (let i = 0; i < s.buckets.length; i++) {
        const labels = { ...s.labels, le: String(s.buckets[i]) };
        lines.push(`${this.name}_bucket${renderLabels(labels)} ${s.counts[i]}`);
      }
      const inf = { ...s.labels, le: "+Inf" };
      lines.push(`${this.name}_bucket${renderLabels(inf)} ${s.count}`);
      lines.push(`${this.name}_sum${renderLabels(s.labels)} ${s.sum}`);
      lines.push(`${this.name}_count${renderLabels(s.labels)} ${s.count}`);
    }
    return lines.join("\n");
  }

  reset(): void {
    this.series.clear();
  }
}

// Singleton registry survives between requests inside a single Next worker.
class Registry {
  readonly httpRequests: Counter;
  readonly httpErrors: Counter;
  readonly httpDuration: Histogram;
  readonly processStartedAt: number;

  constructor() {
    this.httpRequests = new Counter(
      "shotclassify_http_requests_total",
      "Total HTTP requests handled by the /v1 API surface, labeled by route, method, and status class.",
    );
    this.httpErrors = new Counter(
      "shotclassify_http_errors_total",
      "Total HTTP responses with status >= 500.",
    );
    this.httpDuration = new Histogram(
      "shotclassify_http_request_duration_seconds",
      "End-to-end request duration in seconds for /v1 endpoints.",
    );
    this.processStartedAt = Date.now();
  }

  render(): string {
    const uptime = (Date.now() - this.processStartedAt) / 1000;
    const parts = [
      this.httpRequests.render(),
      this.httpErrors.render(),
      this.httpDuration.render(),
      "# HELP shotclassify_process_uptime_seconds Process uptime in seconds.",
      "# TYPE shotclassify_process_uptime_seconds gauge",
      `shotclassify_process_uptime_seconds ${uptime}`,
    ];
    return parts.join("\n") + "\n";
  }

  resetForTests(): void {
    this.httpRequests.reset();
    this.httpErrors.reset();
    this.httpDuration.reset();
  }
}

const g = globalThis as { __shotclassify_metrics__?: Registry };
if (!g.__shotclassify_metrics__) {
  g.__shotclassify_metrics__ = new Registry();
}
export const metrics: Registry = g.__shotclassify_metrics__;

/**
 * Record a finished HTTP request. `route` should be the templated path
 * (e.g. `/v1/shots/:id`), not the raw URL, so cardinality stays bounded.
 */
export function recordHttp(
  route: string,
  method: string,
  status: number,
  durationMs: number,
): void {
  const statusClass = `${Math.floor(status / 100)}xx`;
  metrics.httpRequests.inc({ route, method, status: statusClass }, 1);
  metrics.httpDuration.observe({ route, method }, durationMs / 1000);
  if (status >= 500) {
    metrics.httpErrors.inc({ route, method, status: String(status) }, 1);
  }
}

/**
 * Resolve or mint a request ID. Honors common upstream propagation headers so
 * traces survive a hop through nginx / a CDN.
 */
export function resolveRequestId(headers: Headers): string {
  const candidate =
    headers.get("x-request-id") ||
    headers.get("x-correlation-id") ||
    headers.get("traceparent");
  if (candidate && /^[A-Za-z0-9._-]{1,128}$/.test(candidate)) return candidate;
  // 16 random bytes hex; node crypto via Web Crypto for cross-runtime safety.
  const buf = new Uint8Array(16);
  crypto.getRandomValues(buf);
  let out = "";
  for (let i = 0; i < buf.length; i++) {
    out += buf[i].toString(16).padStart(2, "0");
  }
  return out;
}

// Re-exported only so tests can introspect the classes.
export const __testing__ = { Counter, Histogram, DEFAULT_BUCKETS_SECONDS };
