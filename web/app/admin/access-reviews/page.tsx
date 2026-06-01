"use client";

// Quarterly access review campaigns (SOC2 CC6.3 / ISO 27001 A.9.2.5).
// Workspace owners open a campaign, the system snapshots every active
// member, the owner marks each one keep or revoke, then Apply removes
// the revoked memberships in a single transaction and seals the review
// so the trail is immutable compliance evidence.
//
// Tenant scoping and the last-admin guard are enforced server-side; the
// UI only renders what /v1/access-reviews returns. Apply offers a
// dry-run preview first so the owner can see exactly which members will
// be removed before pulling the trigger.

import Link from "next/link";
import { useCallback, useState } from "react";
import useSWR, { mutate as globalMutate } from "swr";
import {
  ShieldCheck,
  Lock,
  Warning,
  CheckCircle,
  XCircle,
  Plus,
  Download,
  ArrowLeft,
  CircleNotch,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type Review = {
  id: string;
  tenant_id: string;
  title: string;
  status: "open" | "applied" | "cancelled";
  created_at: string;
  created_by: string;
  due_at: string | null;
  closed_at: string | null;
  closed_by: string | null;
  applied_at: string | null;
  applied_by: string | null;
  item_count: number;
  pending_count: number;
  keep_count: number;
  revoke_count: number;
};

type Item = {
  id: string;
  review_id: string;
  principal: string;
  snapshot_role: string;
  decision: "pending" | "keep" | "revoke";
  decided_by: string | null;
  decided_at: string | null;
  note: string | null;
  revoked_at: string | null;
};

type ListResponse = {
  tenant_id: string;
  reviews: Review[];
  open_in_progress: boolean;
};

type DetailResponse = { review: Review; items: Item[] };

type Preview = {
  dry_run: true;
  review_id: string;
  would_revoke: string[];
  would_keep: string[];
  still_pending: string[];
  blocker: string | null;
};

function fmtTs(ts: string | null): string {
  if (!ts) return "";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function StatusPill({ status }: { status: Review["status"] }) {
  const tone =
    status === "open"
      ? "border-amber-300/60 bg-amber-50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-300"
      : status === "applied"
        ? "border-emerald-300/60 bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300"
        : "border-neutral-300/60 bg-neutral-50 dark:bg-neutral-900 text-neutral-600 dark:text-neutral-400";
  return (
    <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] font-medium ${tone}`}>
      {status}
    </span>
  );
}

function DecisionPill({ decision }: { decision: Item["decision"] }) {
  const tone =
    decision === "keep"
      ? "border-emerald-300/60 bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300"
      : decision === "revoke"
        ? "border-rose-300/60 bg-rose-50 dark:bg-rose-950/30 text-rose-700 dark:text-rose-300"
        : "border-neutral-300/60 bg-neutral-50 dark:bg-neutral-900 text-neutral-600 dark:text-neutral-400";
  return (
    <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] font-medium ${tone}`}>
      {decision}
    </span>
  );
}

function ErrorBox({ status, message }: { status?: number; message: string }) {
  const denied = status === 401 || status === 403;
  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950 p-6">
      <div className="flex items-start gap-3">
        <Lock size={20} weight="duotone" className="mt-0.5 text-neutral-500" />
        <div>
          <h1 className="text-lg font-semibold">
            {denied ? "Admin access required" : "Could not load access reviews"}
          </h1>
          <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            {denied
              ? "Only workspace owners and admins can run access reviews. Ask an owner for an upgraded role, or sign in with an admin key."
              : message}
          </p>
        </div>
      </div>
    </div>
  );
}

function OpenReviewForm({ onCreated, disabled }: { onCreated: () => void; disabled: boolean }) {
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch("/api/admin/access-reviews", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title: title.trim() }),
      });
      if (!r.ok) {
        const body = await r.text();
        setErr(body || `HTTP ${r.status}`);
        return;
      }
      setTitle("");
      onCreated();
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-2 md:flex-row md:items-center">
      <label htmlFor="ar-title" className="sr-only">Campaign title</label>
      <input
        id="ar-title"
        type="text"
        required
        maxLength={255}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="2026 Q2 access review"
        className="flex-1 rounded border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-950 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-neutral-400"
        disabled={busy || disabled}
      />
      <button
        type="submit"
        disabled={busy || disabled || !title.trim()}
        className="inline-flex items-center gap-1.5 rounded bg-neutral-900 dark:bg-neutral-100 px-3 py-1.5 text-sm font-medium text-white dark:text-neutral-900 disabled:opacity-50"
      >
        {busy
          ? <CircleNotch size={14} weight="duotone" className="animate-spin" />
          : <Plus size={14} weight="duotone" />}
        Open review
      </button>
      {err ? <span className="text-xs text-rose-600 dark:text-rose-400">{err}</span> : null}
      {disabled && !err ? (
        <span className="text-xs text-neutral-500 dark:text-neutral-400">
          Close the in-progress review before opening another.
        </span>
      ) : null}
    </form>
  );
}

function ItemRow({
  item, reviewId, readOnly, onChanged,
}: { item: Item; reviewId: string; readOnly: boolean; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const decide = async (decision: Item["decision"]) => {
    if (busy || readOnly) return;
    setBusy(true);
    try {
      const r = await fetch(`/api/admin/access-reviews/${reviewId}/items/${item.id}`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ decision }),
      });
      if (r.ok) onChanged();
    } finally { setBusy(false); }
  };
  return (
    <tr className="border-t border-neutral-100 dark:border-neutral-900">
      <td className="px-4 py-2 font-mono text-[12px] break-all">{item.principal}</td>
      <td className="px-4 py-2 text-neutral-600 dark:text-neutral-400">{item.snapshot_role}</td>
      <td className="px-4 py-2"><DecisionPill decision={item.decision} /></td>
      <td className="px-4 py-2">
        {readOnly ? (
          <span className="text-xs text-neutral-500 dark:text-neutral-400">
            {item.decided_at ? fmtTs(item.decided_at) : "sealed"}
          </span>
        ) : (
          <div className="flex gap-1.5">
            <button type="button" onClick={() => decide("keep")} disabled={busy}
              aria-pressed={item.decision === "keep"}
              className="inline-flex items-center gap-1 rounded border border-emerald-300/60 bg-emerald-50 dark:bg-emerald-950/30 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:text-emerald-300 hover:bg-emerald-100 dark:hover:bg-emerald-900/40 disabled:opacity-50">
              <CheckCircle size={12} weight="duotone" /> Keep
            </button>
            <button type="button" onClick={() => decide("revoke")} disabled={busy}
              aria-pressed={item.decision === "revoke"}
              className="inline-flex items-center gap-1 rounded border border-rose-300/60 bg-rose-50 dark:bg-rose-950/30 px-2 py-0.5 text-[11px] font-medium text-rose-700 dark:text-rose-300 hover:bg-rose-100 dark:hover:bg-rose-900/40 disabled:opacity-50">
              <XCircle size={12} weight="duotone" /> Revoke
            </button>
          </div>
        )}
      </td>
    </tr>
  );
}

function ReviewDetail({ reviewId, onBack }: { reviewId: string; onBack: () => void }) {
  const key = `/api/admin/access-reviews/${reviewId}`;
  const { data, error, isLoading, mutate } = useSWR<DetailResponse>(key, fetcher);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [applyBusy, setApplyBusy] = useState(false);
  const [applyErr, setApplyErr] = useState<string | null>(null);

  const refresh = useCallback(() => {
    mutate();
    globalMutate("/api/admin/access-reviews");
  }, [mutate]);

  const runPreview = async () => {
    setApplyErr(null);
    const r = await fetch(`/api/admin/access-reviews/${reviewId}/apply?dry_run=true`, { method: "POST" });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) { setApplyErr(typeof body === "string" ? body : JSON.stringify(body)); return; }
    setPreview(body as Preview);
  };

  const confirmApply = async () => {
    if (!preview) return;
    setApplyBusy(true);
    setApplyErr(null);
    try {
      const r = await fetch(`/api/admin/access-reviews/${reviewId}/apply`, { method: "POST" });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        const detail = (body as { detail?: unknown }).detail;
        setApplyErr(
          typeof detail === "string"
            ? detail
            : (detail as { message?: string } | undefined)?.message || JSON.stringify(body),
        );
        return;
      }
      setPreview(null);
      refresh();
    } finally { setApplyBusy(false); }
  };

  const cancelReview = async () => {
    if (!confirm("Cancel this review? Decisions made so far will be discarded.")) return;
    const r = await fetch(`/api/admin/access-reviews/${reviewId}/cancel`, { method: "POST" });
    if (r.ok) refresh();
  };

  if (isLoading) {
    return (
      <div className="space-y-3">
        <div className="h-8 w-64 rounded bg-neutral-100 dark:bg-neutral-900 animate-pulse" />
        <div className="h-64 rounded-lg border border-neutral-200 dark:border-neutral-800 bg-neutral-100 dark:bg-neutral-900 animate-pulse" />
      </div>
    );
  }
  if (error || !data) {
    const status = (error as { status?: number } | undefined)?.status;
    return <ErrorBox status={status} message="Review not found or no access." />;
  }
  const { review, items } = data;
  const readOnly = review.status !== "open";

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div>
          <button type="button" onClick={onBack}
            className="mb-1 inline-flex items-center gap-1 text-xs text-neutral-500 dark:text-neutral-400 hover:underline">
            <ArrowLeft size={12} weight="duotone" /> All reviews
          </button>
          <h2 className="text-xl font-semibold">{review.title}</h2>
          <p className="text-sm text-neutral-500 dark:text-neutral-400">
            Opened {fmtTs(review.created_at)} by {review.created_by}
            {review.applied_at ? ` · Applied ${fmtTs(review.applied_at)} by ${review.applied_by}` : null}
            {review.closed_at && !review.applied_at ? ` · Cancelled ${fmtTs(review.closed_at)}` : null}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <StatusPill status={review.status} />
          <a href={`/api/admin/access-reviews/${reviewId}/export.csv`}
            className="inline-flex items-center gap-1 rounded border border-neutral-300 dark:border-neutral-700 px-2.5 py-1 text-xs hover:bg-neutral-100 dark:hover:bg-neutral-900">
            <Download size={12} weight="duotone" /> Export CSV
          </a>
          {review.status === "open" ? (
            <button type="button" onClick={cancelReview}
              className="inline-flex items-center gap-1 rounded border border-neutral-300 dark:border-neutral-700 px-2.5 py-1 text-xs hover:bg-neutral-100 dark:hover:bg-neutral-900">
              Cancel review
            </button>
          ) : null}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-center text-xs">
        <div className="rounded border border-neutral-200 dark:border-neutral-800 p-2">
          <div className="text-neutral-500 dark:text-neutral-400">Members</div>
          <div className="mt-0.5 text-lg font-semibold tabular-nums">{review.item_count}</div>
        </div>
        <div className="rounded border border-neutral-200 dark:border-neutral-800 p-2">
          <div className="text-neutral-500 dark:text-neutral-400">Pending</div>
          <div className="mt-0.5 text-lg font-semibold tabular-nums">{review.pending_count}</div>
        </div>
        <div className="rounded border border-emerald-300/60 bg-emerald-50/40 dark:bg-emerald-950/20 p-2">
          <div className="text-emerald-700 dark:text-emerald-300">Keep</div>
          <div className="mt-0.5 text-lg font-semibold tabular-nums">{review.keep_count}</div>
        </div>
        <div className="rounded border border-rose-300/60 bg-rose-50/40 dark:bg-rose-950/20 p-2">
          <div className="text-rose-700 dark:text-rose-300">Revoke</div>
          <div className="mt-0.5 text-lg font-semibold tabular-nums">{review.revoke_count}</div>
        </div>
      </div>

      <section className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-neutral-50 dark:bg-neutral-900/60 text-xs uppercase tracking-wide text-neutral-500 dark:text-neutral-400">
              <tr>
                <th className="px-4 py-2 text-left font-medium">Principal</th>
                <th className="px-4 py-2 text-left font-medium">Snapshot role</th>
                <th className="px-4 py-2 text-left font-medium">Decision</th>
                <th className="px-4 py-2 text-left font-medium">{readOnly ? "Decided" : "Action"}</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? (
                <tr><td colSpan={4} className="px-4 py-8 text-center text-sm text-neutral-500 dark:text-neutral-400">
                  No members snapshotted in this review.
                </td></tr>
              ) : items.map((item) => (
                <ItemRow key={item.id} item={item} reviewId={reviewId} readOnly={readOnly} onChanged={refresh} />
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {review.status === "open" ? (
        <section className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950 p-4">
          <h3 className="text-sm font-semibold">Apply decisions</h3>
          <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            Preview which members will be removed, then confirm to seal the review. Apply only revokes members
            explicitly marked revoke; pending and keep stay on the roster.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" onClick={runPreview}
              className="inline-flex items-center gap-1.5 rounded border border-neutral-300 dark:border-neutral-700 px-3 py-1.5 text-sm hover:bg-neutral-100 dark:hover:bg-neutral-900">
              <ShieldCheck size={14} weight="duotone" /> Preview apply
            </button>
            {preview ? (
              <button type="button" onClick={confirmApply}
                disabled={applyBusy || preview.blocker !== null}
                className="inline-flex items-center gap-1.5 rounded bg-rose-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-rose-700 disabled:opacity-50">
                {applyBusy
                  ? <CircleNotch size={14} weight="duotone" className="animate-spin" />
                  : <CheckCircle size={14} weight="duotone" />}
                Confirm apply ({preview.would_revoke.length} revoke)
              </button>
            ) : null}
          </div>
          {applyErr ? (
            <div className="mt-3 flex items-start gap-2 rounded border border-rose-300/60 bg-rose-50 dark:bg-rose-950/30 p-2 text-xs text-rose-700 dark:text-rose-300">
              <Warning size={14} weight="duotone" className="mt-0.5" />
              <span className="break-all">{applyErr}</span>
            </div>
          ) : null}
          {preview ? (
            <div className="mt-3 space-y-2 text-xs">
              {preview.blocker ? (
                <div className="flex items-start gap-2 rounded border border-rose-300/60 bg-rose-50 dark:bg-rose-950/30 p-2 text-rose-700 dark:text-rose-300">
                  <Warning size={14} weight="duotone" className="mt-0.5" />
                  <span>
                    Cannot apply: revoking {preview.blocker} would leave the workspace with no admin. Mark at
                    least one admin as keep.
                  </span>
                </div>
              ) : null}
              {preview.still_pending.length > 0 ? (
                <div className="rounded border border-amber-300/60 bg-amber-50 dark:bg-amber-950/30 p-2 text-amber-800 dark:text-amber-200">
                  {preview.still_pending.length} member(s) still pending: <span className="font-mono">{preview.still_pending.join(", ")}</span>
                </div>
              ) : null}
              <div className="grid gap-2 md:grid-cols-2">
                <div className="rounded border border-rose-300/60 bg-rose-50/40 dark:bg-rose-950/20 p-2">
                  <div className="font-semibold text-rose-700 dark:text-rose-300">Will revoke ({preview.would_revoke.length})</div>
                  <ul className="mt-1 space-y-0.5 font-mono">
                    {preview.would_revoke.map((p) => <li key={p} className="break-all">{p}</li>)}
                    {preview.would_revoke.length === 0 ? <li className="text-neutral-500 dark:text-neutral-400 font-sans">None.</li> : null}
                  </ul>
                </div>
                <div className="rounded border border-emerald-300/60 bg-emerald-50/40 dark:bg-emerald-950/20 p-2">
                  <div className="font-semibold text-emerald-700 dark:text-emerald-300">Will keep ({preview.would_keep.length})</div>
                  <ul className="mt-1 space-y-0.5 font-mono">
                    {preview.would_keep.map((p) => <li key={p} className="break-all">{p}</li>)}
                    {preview.would_keep.length === 0 ? <li className="text-neutral-500 dark:text-neutral-400 font-sans">None.</li> : null}
                  </ul>
                </div>
              </div>
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

export default function AccessReviewsPage() {
  const { data, error, isLoading, mutate } = useSWR<ListResponse>(
    "/api/admin/access-reviews",
    fetcher,
  );
  const [selected, setSelected] = useState<string | null>(null);

  return (
    <div className="mx-auto max-w-6xl p-4 md:p-8">
      <header className="mb-6">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-neutral-500 dark:text-neutral-400">
          <Link href="/admin" className="hover:underline">Admin</Link>
          <span>/</span>
          <span>Access reviews</span>
        </div>
        <h1 className="mt-1 text-2xl font-semibold flex items-center gap-2">
          <ShieldCheck size={22} weight="duotone" /> Access reviews
        </h1>
        <p className="text-sm text-neutral-500 dark:text-neutral-400">
          Periodic re-certification of who has access to this workspace. Required by SOC2 CC6.3 and ISO 27001 A.9.2.5.
        </p>
      </header>

      {isLoading ? (
        <div className="space-y-3">
          <div className="h-10 rounded bg-neutral-100 dark:bg-neutral-900 animate-pulse" />
          <div className="h-64 rounded-lg border border-neutral-200 dark:border-neutral-800 bg-neutral-100 dark:bg-neutral-900 animate-pulse" />
        </div>
      ) : error || !data ? (
        <ErrorBox
          status={(error as { status?: number } | undefined)?.status}
          message="The API returned an error. Try again, or check the API service logs for the matching request id."
        />
      ) : selected ? (
        <ReviewDetail reviewId={selected} onBack={() => { setSelected(null); mutate(); }} />
      ) : (
        <div className="space-y-6">
          <section className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950 p-4">
            <h2 className="text-sm font-semibold">Open a new review</h2>
            <p className="mt-1 mb-3 text-xs text-neutral-500 dark:text-neutral-400">
              Snapshots every active member of {data.tenant_id} into a fresh campaign. Only one open campaign per workspace at a time.
            </p>
            <OpenReviewForm
              onCreated={() => mutate()}
              disabled={data.open_in_progress}
            />
          </section>

          <section className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950 overflow-hidden">
            <header className="flex items-center justify-between border-b border-neutral-200 dark:border-neutral-800 px-4 py-3">
              <div>
                <h2 className="text-sm font-semibold">Campaigns</h2>
                <p className="text-xs text-neutral-500 dark:text-neutral-400">
                  All access reviews scoped to this workspace.
                </p>
              </div>
            </header>
            {data.reviews.length === 0 ? (
              <div className="p-8 text-center text-sm text-neutral-500 dark:text-neutral-400">
                No access reviews yet. Open the first one above to start the audit trail.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-neutral-50 dark:bg-neutral-900/60 text-xs uppercase tracking-wide text-neutral-500 dark:text-neutral-400">
                    <tr>
                      <th className="px-4 py-2 text-left font-medium">Title</th>
                      <th className="px-4 py-2 text-left font-medium">Status</th>
                      <th className="px-4 py-2 text-right font-medium">Members</th>
                      <th className="px-4 py-2 text-right font-medium">Pending</th>
                      <th className="px-4 py-2 text-left font-medium">Opened</th>
                      <th className="px-4 py-2 text-left font-medium">Sealed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.reviews.map((r) => (
                      <tr key={r.id}
                        className="border-t border-neutral-100 dark:border-neutral-900 hover:bg-neutral-50 dark:hover:bg-neutral-900/40 cursor-pointer"
                        onClick={() => setSelected(r.id)}
                        tabIndex={0}
                        onKeyDown={(e) => { if (e.key === "Enter") setSelected(r.id); }}
                        role="button"
                        aria-label={`Open review ${r.title}`}
                      >
                        <td className="px-4 py-2 font-medium">{r.title}</td>
                        <td className="px-4 py-2"><StatusPill status={r.status} /></td>
                        <td className="px-4 py-2 text-right tabular-nums">{r.item_count}</td>
                        <td className="px-4 py-2 text-right tabular-nums">{r.pending_count}</td>
                        <td className="px-4 py-2 text-neutral-600 dark:text-neutral-400">{fmtTs(r.created_at)}</td>
                        <td className="px-4 py-2 text-neutral-600 dark:text-neutral-400">
                          {r.applied_at ? fmtTs(r.applied_at) : r.closed_at ? fmtTs(r.closed_at) : ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
