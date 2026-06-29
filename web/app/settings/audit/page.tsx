"use client";

import { useCallback, useMemo, useState, Fragment } from "react";
import useSWR from "swr";
import {
  ClipboardText,
  MagnifyingGlass,
  Download,
  Warning,
  ArrowsClockwise,
  Shield,
  CheckCircle,
  ShieldCheck,
  ShieldWarning,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";
import { shortDateTime } from "@/lib/date-format";

type AuditEvent = {
  id: string;
  created_at: string | null;
  principal: string;
  method: string;
  path: string;
  status_code: number;
  request_id: string | null;
  client_ip: string | null;
  user_agent: string | null;
  elapsed_ms: number;
  target_id: string | null;
  tenant_id: string | null;
  extra: Record<string, unknown>;
};

type ApiError = Error & { status?: number };

const LIMITS = [50, 100, 250, 500, 1000] as const;

function statusTone(code: number): string {
  if (code >= 500) return "bg-rose-50 text-rose-700 ring-rose-200";
  if (code >= 400) return "bg-amber-50 text-amber-800 ring-amber-200";
  if (code >= 300) return "bg-sky-50 text-sky-700 ring-sky-200";
  return "bg-emerald-50 text-emerald-700 ring-emerald-200";
}

function methodTone(m: string): string {
  const u = (m || "").toUpperCase();
  if (u === "DELETE") return "text-rose-700";
  if (u === "POST") return "text-emerald-700";
  if (u === "PUT" || u === "PATCH") return "text-amber-700";
  return "text-slate-700";
}

function relTime(iso: string | null): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return "";
  const diff = Date.now() - t;
  const s = Math.round(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h}h ago`;
  return shortDateTime(iso);
}

export default function AuditLogPage() {
  const [principal, setPrincipal] = useState("");
  const [pathPrefix, setPathPrefix] = useState("");
  const [limit, setLimit] = useState<number>(100);
  const [expanded, setExpanded] = useState<string | null>(null);

  const qs = useMemo(() => {
    const p = new URLSearchParams();
    p.set("limit", String(limit));
    if (principal.trim()) p.set("principal", principal.trim());
    if (pathPrefix.trim()) p.set("path_prefix", pathPrefix.trim());
    return p.toString();
  }, [principal, pathPrefix, limit]);

  const { data, error, isLoading, mutate } = useSWR<AuditEvent[]>(
    `/api/audit?${qs}`,
    fetcher,
    { revalidateOnFocus: false, keepPreviousData: true },
  );

  const err = error as ApiError | undefined;
  const forbidden = err?.status === 401 || err?.status === 403;
  const events = Array.isArray(data) ? data : [];

  type VerifyResult = {
    ok: boolean;
    checked: number;
    tenant_id: string | null;
    broken_at: string | null;
    reason: string | null;
    tip_hash: string | null;
  };
  const [exportOpen, setExportOpen] = useState(false);
  const [exportFormat, setExportFormat] = useState<"jsonl" | "csv">("jsonl");
  const [exportSince, setExportSince] = useState("");
  const [exportUntil, setExportUntil] = useState("");
  const [exporting, setExporting] = useState(false);
  const [exportErr, setExportErr] = useState<string | null>(null);
  const [exportInfo, setExportInfo] = useState<string | null>(null);

  const runExport = useCallback(async () => {
    setExporting(true);
    setExportErr(null);
    setExportInfo(null);
    try {
      const body: Record<string, unknown> = { format: exportFormat };
      if (exportSince) body.since = new Date(exportSince).toISOString();
      if (exportUntil) body.until = new Date(exportUntil).toISOString();
      if (principal.trim()) body.principal = principal.trim();
      if (pathPrefix.trim()) body.path_prefix = pathPrefix.trim();
      const r = await fetch("/api/audit/export", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t || `HTTP ${r.status}`);
      }
      const blob = await r.blob();
      const cd = r.headers.get("content-disposition") || "";
      const m = /filename="([^"]+)"/.exec(cd);
      const fname =
        m?.[1] ||
        `shotclassify-audit-${new Date().toISOString().slice(0, 10)}.${exportFormat}`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = fname;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      const manifest = r.headers.get("x-audit-manifest");
      if (manifest) {
        try {
          const parsed = JSON.parse(manifest) as {
            tip_hash: string | null;
            chain_ok: boolean;
          };
          const tip = parsed.tip_hash ? `${parsed.tip_hash.slice(0, 12)}\u2026` : "(empty)";
          setExportInfo(
            `Saved ${fname}. Chain ${parsed.chain_ok ? "verified" : "broken"}. Tip ${tip}.`,
          );
        } catch {
          setExportInfo(`Saved ${fname}.`);
        }
      } else {
        setExportInfo(`Saved ${fname}.`);
      }
    } catch (e) {
      setExportErr(e instanceof Error ? e.message : String(e));
    } finally {
      setExporting(false);
    }
  }, [exportFormat, exportSince, exportUntil, principal, pathPrefix]);

  const [verify, setVerify] = useState<VerifyResult | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [verifyErr, setVerifyErr] = useState<string | null>(null);
  const runVerify = useCallback(async () => {
    setVerifying(true);
    setVerifyErr(null);
    try {
      const r = await fetch("/api/audit/verify", { cache: "no-store" });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t || `HTTP ${r.status}`);
      }
      setVerify((await r.json()) as VerifyResult);
    } catch (e) {
      setVerifyErr(e instanceof Error ? e.message : String(e));
    } finally {
      setVerifying(false);
    }
  }, []);

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      <header className="mb-6 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-slate-900">
            <ClipboardText size={22} weight="duotone" aria-hidden />
            <h1 className="text-2xl font-semibold tracking-tight">Audit log</h1>
          </div>
          <p className="mt-1 text-sm text-slate-600">
            Every authenticated mutation, scoped to this workspace. Admin only.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => mutate()}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
            aria-label="Refresh audit log"
          >
            <ArrowsClockwise size={16} weight="duotone" aria-hidden />
            Refresh
          </button>
          <button
            type="button"
            onClick={() => setExportOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-900 bg-slate-900 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
          >
            <Download size={16} weight="duotone" aria-hidden />
            Export
          </button>
        </div>
      </header>

      <section
        aria-label="Tamper-evident chain"
        className="mb-4 flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm sm:flex-row sm:items-center sm:justify-between"
      >
        <div className="flex items-start gap-3">
          {verify?.ok === false ? (
            <ShieldWarning size={22} weight="duotone" className="mt-0.5 text-rose-600" aria-hidden />
          ) : verify?.ok ? (
            <ShieldCheck size={22} weight="duotone" className="mt-0.5 text-emerald-600" aria-hidden />
          ) : (
            <Shield size={22} weight="duotone" className="mt-0.5 text-slate-500" aria-hidden />
          )}
          <div className="min-w-0">
            <p className="text-sm font-medium text-slate-900">
              Tamper-evident hash chain
            </p>
            {verify?.ok === false ? (
              <p className="text-xs text-rose-700">
                Chain broken at <span className="font-mono">{verify.broken_at}</span>. {verify.reason}
              </p>
            ) : verify?.ok ? (
              <p className="text-xs text-slate-600">
                Verified {verify.checked} rows. Tip{" "}
                <span className="font-mono" title={verify.tip_hash ?? ""}>
                  {verify.tip_hash ? `${verify.tip_hash.slice(0, 12)}\u2026` : "(empty)"}
                </span>
              </p>
            ) : verifyErr ? (
              <p className="text-xs text-rose-700 break-all">{verifyErr}</p>
            ) : (
              <p className="text-xs text-slate-600">
                Each row is SHA-256 linked to the previous row. Verify to detect any tampering or out-of-band edits.
              </p>
            )}
          </div>
        </div>
        <button
          type="button"
          onClick={runVerify}
          disabled={verifying}
          className="inline-flex shrink-0 items-center gap-1.5 self-start rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 disabled:cursor-not-allowed disabled:opacity-60 sm:self-auto"
          aria-label="Verify audit hash chain"
        >
          <ShieldCheck size={16} weight="duotone" aria-hidden />
          {verifying ? "Verifying\u2026" : "Verify chain"}
        </button>
      </section>

      <section
        aria-label="Filters"
        className="mb-4 grid grid-cols-1 gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm sm:grid-cols-12"
      >
        <label className="sm:col-span-5">
          <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">
            Principal
          </span>
          <div className="relative">
            <MagnifyingGlass
              size={16}
              weight="duotone"
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400"
              aria-hidden
            />
            <input
              type="text"
              value={principal}
              onChange={(e) => setPrincipal(e.target.value)}
              placeholder="user@example.com or api-key"
              className="w-full rounded-md border border-slate-200 bg-white py-1.5 pl-8 pr-3 text-sm text-slate-900 placeholder:text-slate-400 focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200"
            />
          </div>
        </label>
        <label className="sm:col-span-5">
          <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">
            Path prefix
          </span>
          <input
            type="text"
            value={pathPrefix}
            onChange={(e) => setPathPrefix(e.target.value)}
            placeholder="/v1/history"
            className="w-full rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-900 placeholder:text-slate-400 focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200"
          />
        </label>
        <label className="sm:col-span-2">
          <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">
            Limit
          </span>
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-sm text-slate-900 focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200"
          >
            {LIMITS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      </section>

      {forbidden ? (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-amber-900"
        >
          <Shield size={20} weight="duotone" aria-hidden />
          <div className="text-sm">
            <p className="font-medium">Admin role required.</p>
            <p className="mt-1 text-amber-800">
              The audit log is restricted to workspace admins. Ask an owner to grant you the admin role.
            </p>
          </div>
        </div>
      ) : err ? (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-lg border border-rose-200 bg-rose-50 p-4 text-rose-900"
        >
          <Warning size={20} weight="duotone" aria-hidden />
          <div className="text-sm">
            <p className="font-medium">Could not load audit events.</p>
            <p className="mt-1 break-all text-rose-800">{err.message}</p>
          </div>
        </div>
      ) : isLoading ? (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
          <ul className="divide-y divide-slate-100">
            {Array.from({ length: 8 }).map((_, i) => (
              <li key={i} className="flex animate-pulse items-center gap-4 px-4 py-3">
                <div className="h-4 w-24 rounded bg-slate-100" />
                <div className="h-4 w-16 rounded bg-slate-100" />
                <div className="h-4 flex-1 rounded bg-slate-100" />
                <div className="h-4 w-12 rounded bg-slate-100" />
              </li>
            ))}
          </ul>
        </div>
      ) : events.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-300 bg-white px-6 py-16 text-center">
          <CheckCircle size={28} weight="duotone" className="text-slate-400" aria-hidden />
          <p className="text-sm font-medium text-slate-900">No audit events match.</p>
          <p className="text-sm text-slate-500">
            Adjust the filters or trigger a mutation to populate the log.
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
          {/* Mobile cards */}
          <ul className="divide-y divide-slate-100 sm:hidden">
            {events.map((e) => (
              <li key={e.id} className="px-4 py-3">
                <div className="flex items-center justify-between gap-2">
                  <span className={`text-xs font-semibold ${methodTone(e.method)}`}>
                    {e.method.toUpperCase()}
                  </span>
                  <span
                    className={`rounded px-1.5 py-0.5 text-xs font-medium ring-1 ${statusTone(e.status_code)}`}
                  >
                    {e.status_code}
                  </span>
                </div>
                <div className="mt-1 truncate font-mono text-sm text-slate-900">{e.path}</div>
                <div className="mt-1 flex items-center justify-between text-xs text-slate-500">
                  <span className="truncate">{e.principal}</span>
                  <span>{relTime(e.created_at)}</span>
                </div>
              </li>
            ))}
          </ul>
          {/* Desktop table */}
          <table className="hidden w-full text-sm sm:table">
            <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2.5">When</th>
                <th className="px-4 py-2.5">Principal</th>
                <th className="px-4 py-2.5">Method</th>
                <th className="px-4 py-2.5">Path</th>
                <th className="px-4 py-2.5">Status</th>
                <th className="px-4 py-2.5">IP</th>
                <th className="px-4 py-2.5 text-right">ms</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {events.map((e) => {
                const open = expanded === e.id;
                return (
                  <Fragment key={e.id}>
                    <tr
                      className="cursor-pointer hover:bg-slate-50"
                      onClick={() => setExpanded(open ? null : e.id)}
                    >
                      <td className="whitespace-nowrap px-4 py-2 text-slate-600" title={e.created_at ?? ""}>
                        {relTime(e.created_at)}
                      </td>
                      <td className="px-4 py-2 text-slate-900">{e.principal}</td>
                      <td className={`px-4 py-2 font-mono text-xs font-semibold ${methodTone(e.method)}`}>
                        {e.method.toUpperCase()}
                      </td>
                      <td className="max-w-[28rem] truncate px-4 py-2 font-mono text-xs text-slate-700">
                        {e.path}
                      </td>
                      <td className="px-4 py-2">
                        <span className={`rounded px-1.5 py-0.5 text-xs font-medium ring-1 ${statusTone(e.status_code)}`}>
                          {e.status_code}
                        </span>
                      </td>
                      <td className="px-4 py-2 font-mono text-xs text-slate-600">{e.client_ip ?? ""}</td>
                      <td className="px-4 py-2 text-right tabular-nums text-slate-600">{e.elapsed_ms}</td>
                    </tr>
                    {open && (
                      <tr key={`${e.id}-d`} className="bg-slate-50/60">
                        <td colSpan={7} className="px-4 py-3">
                          <dl className="grid grid-cols-1 gap-2 text-xs text-slate-700 md:grid-cols-2">
                            <div>
                              <dt className="font-semibold text-slate-500">Request ID</dt>
                              <dd className="font-mono">{e.request_id ?? "(none)"}</dd>
                            </div>
                            <div>
                              <dt className="font-semibold text-slate-500">Tenant</dt>
                              <dd className="font-mono">{e.tenant_id ?? "(global)"}</dd>
                            </div>
                            <div>
                              <dt className="font-semibold text-slate-500">Target</dt>
                              <dd className="font-mono">{e.target_id ?? "(none)"}</dd>
                            </div>
                            <div>
                              <dt className="font-semibold text-slate-500">User agent</dt>
                              <dd className="truncate font-mono" title={e.user_agent ?? ""}>
                                {e.user_agent ?? "(none)"}
                              </dd>
                            </div>
                            {e.extra && Object.keys(e.extra).length > 0 && (
                              <div className="md:col-span-2">
                                <dt className="font-semibold text-slate-500">Extra</dt>
                                <dd>
                                  <pre className="mt-1 overflow-x-auto rounded bg-white p-2 font-mono text-[11px] text-slate-700 ring-1 ring-slate-200">
                                    {JSON.stringify(e.extra, null, 2)}
                                  </pre>
                                </dd>
                              </div>
                            )}
                          </dl>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-4 text-xs text-slate-500">
        Showing the most recent {events.length} of up to {limit} events. Filters apply server side. Exports respect the same filters and ship with a signed manifest.
      </p>

      {exportOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Export audit log"
          className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/40 px-4 py-6 sm:items-center"
          onKeyDown={(e) => {
            if (e.key === "Escape") setExportOpen(false);
          }}
        >
          <div className="w-full max-w-lg rounded-lg border border-slate-200 bg-white p-5 shadow-xl">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-base font-semibold text-slate-900">Export audit log</h2>
              <button
                type="button"
                onClick={() => setExportOpen(false)}
                className="rounded-md px-2 py-1 text-xs text-slate-500 hover:bg-slate-100"
                aria-label="Close export dialog"
              >
                Close
              </button>
            </div>
            <p className="mb-4 text-xs text-slate-600">
              Streams the workspace audit trail for SIEM ingestion. The download is signed with the current hash chain tip so consumers can verify the file independently.
            </p>
            <div className="space-y-3">
              <div>
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Format</span>
                <div className="inline-flex rounded-md border border-slate-200 bg-slate-50 p-0.5">
                  {(["jsonl", "csv"] as const).map((f) => (
                    <button
                      key={f}
                      type="button"
                      onClick={() => setExportFormat(f)}
                      className={`rounded px-3 py-1 text-xs font-medium ${
                        exportFormat === f
                          ? "bg-white text-slate-900 shadow-sm ring-1 ring-slate-200"
                          : "text-slate-600 hover:text-slate-900"
                      }`}
                    >
                      {f === "jsonl" ? "JSON Lines" : "CSV"}
                    </button>
                  ))}
                </div>
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label>
                  <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Since</span>
                  <input
                    type="datetime-local"
                    value={exportSince}
                    onChange={(e) => setExportSince(e.target.value)}
                    className="w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-sm text-slate-900 focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200"
                  />
                </label>
                <label>
                  <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Until</span>
                  <input
                    type="datetime-local"
                    value={exportUntil}
                    onChange={(e) => setExportUntil(e.target.value)}
                    className="w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-sm text-slate-900 focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200"
                  />
                </label>
              </div>
              <p className="text-[11px] text-slate-500">
                Current principal and path filters are also applied. Leave date fields empty for the full history.
              </p>
              {exportErr && (
                <p role="alert" className="rounded-md bg-rose-50 px-3 py-2 text-xs text-rose-700 ring-1 ring-rose-200 break-all">
                  {exportErr}
                </p>
              )}
              {exportInfo && (
                <p className="rounded-md bg-emerald-50 px-3 py-2 text-xs text-emerald-800 ring-1 ring-emerald-200 break-all">
                  {exportInfo}
                </p>
              )}
            </div>
            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setExportOpen(false)}
                className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={runExport}
                disabled={exporting}
                className="inline-flex items-center gap-1.5 rounded-md border border-slate-900 bg-slate-900 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Download size={16} weight="duotone" aria-hidden />
                {exporting ? "Preparing\u2026" : "Download"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
