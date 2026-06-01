"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import {
  ClipboardText,
  Shield,
  CheckCircle,
  XCircle,
  Clock,
  Warning,
  ArrowsClockwise,
  DownloadSimple,
  Prohibit,
  Plus,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type Role = "admin" | "operator" | "viewer";
type Decision = "pending" | "keep" | "revoke";

type ReviewSummary = {
  id: string;
  tenant_id: string;
  title: string;
  status: "open" | "applied" | "cancelled";
  created_at: string;
  created_by: string;
  due_at: string | null;
  applied_at: string | null;
  applied_by: string | null;
  item_count: number;
  pending_count: number;
  keep_count: number;
  revoke_count: number;
};

type ReviewItem = {
  id: string;
  review_id: string;
  principal: string;
  snapshot_role: Role;
  decision: Decision;
  decided_by: string | null;
  decided_at: string | null;
  note: string | null;
  revoked_at: string | null;
};

type ApiError = Error & { status?: number };

const STATUS_BADGE: Record<ReviewSummary["status"], string> = {
  open: "bg-amber-50 text-amber-700 ring-amber-200",
  applied: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  cancelled: "bg-slate-50 text-slate-600 ring-slate-200",
};

const DECISION_BADGE: Record<Decision, string> = {
  pending: "bg-slate-50 text-slate-600 ring-slate-200",
  keep: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  revoke: "bg-rose-50 text-rose-700 ring-rose-200",
};

const ROLE_BADGE: Record<Role, string> = {
  admin: "bg-amber-50 text-amber-700 ring-amber-200",
  operator: "bg-blue-50 text-blue-700 ring-blue-200",
  viewer: "bg-slate-50 text-slate-700 ring-slate-200",
};

function badge(klass: string) {
  return `inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${klass}`;
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

async function jsonFetch(url: string, init: RequestInit): Promise<unknown> {
  const r = await fetch(url, { credentials: "same-origin", ...init });
  if (!r.ok) {
    let text = "";
    try {
      text = await r.text();
    } catch {
      /* ignore */
    }
    const err = new Error(text || `${r.status} ${r.statusText}`) as ApiError;
    err.status = r.status;
    throw err;
  }
  if (r.status === 204) return null;
  return r.json();
}

export default function AccessReviewsPage() {
  const list = useSWR<{ reviews: ReviewSummary[]; open_in_progress: boolean }>(
    "/api/settings/security/access-reviews",
    fetcher,
  );

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reviews = list.data?.reviews ?? [];
  const openInProgress = list.data?.open_in_progress ?? false;

  const effectiveSelected = useMemo(() => {
    if (selectedId && reviews.find((r) => r.id === selectedId)) return selectedId;
    return reviews[0]?.id ?? null;
  }, [selectedId, reviews]);

  const detailUrl = effectiveSelected
    ? `/api/settings/security/access-reviews/${effectiveSelected}`
    : null;
  const detail = useSWR<{ review: ReviewSummary; items: ReviewItem[] }>(
    detailUrl,
    fetcher,
  );

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!title.trim()) {
      setError("Give the review a title so the audit trail is searchable.");
      return;
    }
    setBusy(true);
    try {
      const body = JSON.stringify({ title: title.trim() });
      const created = (await jsonFetch(
        "/api/settings/security/access-reviews",
        { method: "POST", headers: { "content-type": "application/json" }, body },
      )) as { review: ReviewSummary };
      setTitle("");
      setCreating(false);
      setSelectedId(created.review.id);
      await Promise.all([list.mutate(), detail.mutate?.()]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function setDecision(item: ReviewItem, decision: Decision) {
    if (!detail.data) return;
    setError(null);
    try {
      await jsonFetch(
        `/api/settings/security/access-reviews/${item.review_id}/items/${item.id}`,
        {
          method: "PUT",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ decision }),
        },
      );
      await detail.mutate();
      await list.mutate();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function applyReview(dryRun: boolean) {
    if (!detail.data) return;
    setError(null);
    setBusy(true);
    try {
      const qs = dryRun ? "?dry_run=true" : "";
      const result = (await jsonFetch(
        `/api/settings/security/access-reviews/${detail.data.review.id}/apply${qs}`,
        { method: "POST" },
      )) as Record<string, unknown>;
      if (dryRun) {
        const revoke = (result.would_revoke as string[]) ?? [];
        const blocker = result.blocker as string | null;
        if (blocker) {
          setError(
            `Apply is blocked: revoking ${blocker} would leave the workspace with no admin.`,
          );
        } else {
          setError(
            revoke.length === 0
              ? "Dry run: nothing would change."
              : `Dry run: would revoke ${revoke.length} member${revoke.length === 1 ? "" : "s"}.`,
          );
        }
      }
      await Promise.all([list.mutate(), detail.mutate()]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function cancelReview() {
    if (!detail.data) return;
    setError(null);
    setBusy(true);
    try {
      await jsonFetch(
        `/api/settings/security/access-reviews/${detail.data.review.id}/cancel`,
        { method: "POST" },
      );
      await Promise.all([list.mutate(), detail.mutate()]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const current = detail.data?.review;
  const items = detail.data?.items ?? [];
  const allDecided = items.length > 0 && items.every((i) => i.decision !== "pending");
  const isOpen = current?.status === "open";

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      <header className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight text-slate-900">
            <Shield weight="duotone" className="size-7 text-slate-700" aria-hidden />
            Access reviews
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-600">
            Periodically re-certify that every workspace member still needs their role.
            Required by SOC2 CC6.3 and ISO 27001 A.9.2.5. Each review snapshots the
            current roster, captures a keep or revoke decision per member, and seals
            the result as immutable audit evidence.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setError(null);
            setCreating((v) => !v);
          }}
          disabled={openInProgress && !creating}
          className="inline-flex items-center gap-2 self-start rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          <Plus weight="bold" className="size-4" aria-hidden />
          {openInProgress ? "Review in progress" : "Open a review"}
        </button>
      </header>

      {creating ? (
        <form
          onSubmit={onCreate}
          className="mb-6 rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
        >
          <label className="block text-sm font-medium text-slate-700" htmlFor="title">
            Review title
          </label>
          <input
            id="title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="2026 Q2 access review"
            className="mt-2 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            autoFocus
            disabled={busy}
          />
          <p className="mt-2 text-xs text-slate-500">
            Opens a campaign and snapshots every active member into a decision list.
            One open review per workspace at a time.
          </p>
          <div className="mt-3 flex gap-2">
            <button
              type="submit"
              disabled={busy}
              className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:bg-slate-300"
            >
              {busy ? "Opening" : "Open review"}
            </button>
            <button
              type="button"
              onClick={() => setCreating(false)}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700"
              disabled={busy}
            >
              Cancel
            </button>
          </div>
        </form>
      ) : null}

      {error ? (
        <div
          role="alert"
          className="mb-4 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
        >
          <Warning weight="duotone" className="mt-0.5 size-4 flex-none" aria-hidden />
          <span className="break-words">{error}</span>
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
        <aside aria-label="Review history">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            History
          </h2>
          {list.isLoading ? (
            <ul className="space-y-2">
              {[0, 1, 2].map((i) => (
                <li
                  key={i}
                  className="h-16 animate-pulse rounded-md border border-slate-200 bg-slate-50"
                />
              ))}
            </ul>
          ) : list.error ? (
            <p className="text-sm text-rose-700">Could not load reviews.</p>
          ) : reviews.length === 0 ? (
            <div className="rounded-md border border-dashed border-slate-300 p-4 text-sm text-slate-600">
              No reviews yet. Open the first one to start your audit trail.
            </div>
          ) : (
            <ul className="space-y-1">
              {reviews.map((r) => {
                const active = r.id === effectiveSelected;
                return (
                  <li key={r.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(r.id)}
                      className={`w-full rounded-md border px-3 py-2 text-left text-sm transition focus:outline-none focus:ring-2 focus:ring-slate-400 ${active ? "border-slate-900 bg-slate-900 text-white" : "border-slate-200 bg-white hover:border-slate-300"}`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate font-medium">{r.title}</span>
                        <span
                          className={badge(STATUS_BADGE[r.status]) + (active ? " ring-0" : "")}
                        >
                          {r.status}
                        </span>
                      </div>
                      <div
                        className={`mt-1 text-xs ${active ? "text-slate-300" : "text-slate-500"}`}
                      >
                        {fmtDate(r.created_at)} · {r.item_count} member
                        {r.item_count === 1 ? "" : "s"}
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </aside>

        <section aria-label="Review detail">
          {!effectiveSelected ? (
            <div className="rounded-lg border border-dashed border-slate-300 p-8 text-center">
              <ClipboardText
                weight="duotone"
                className="mx-auto size-10 text-slate-400"
                aria-hidden
              />
              <p className="mt-2 text-sm text-slate-600">
                Open your first access review to certify the current roster.
              </p>
            </div>
          ) : detail.isLoading || !current ? (
            <div className="space-y-3">
              {[0, 1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="h-14 animate-pulse rounded-md border border-slate-200 bg-slate-50"
                />
              ))}
            </div>
          ) : detail.error ? (
            <p className="text-sm text-rose-700">Could not load this review.</p>
          ) : (
            <>
              <div className="mb-4 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="truncate text-lg font-semibold text-slate-900">
                      {current.title}
                    </h2>
                    <p className="mt-1 text-xs text-slate-500">
                      Opened {fmtDate(current.created_at)} by {current.created_by}
                      {current.applied_at
                        ? ` · applied ${fmtDate(current.applied_at)} by ${current.applied_by}`
                        : ""}
                    </p>
                  </div>
                  <span className={badge(STATUS_BADGE[current.status])}>
                    {current.status}
                  </span>
                </div>
                <dl className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
                  <Stat label="Members" value={current.item_count} />
                  <Stat label="Pending" value={current.pending_count} tone="slate" />
                  <Stat label="Keep" value={current.keep_count} tone="emerald" />
                  <Stat label="Revoke" value={current.revoke_count} tone="rose" />
                </dl>
                <div className="mt-4 flex flex-wrap gap-2">
                  <a
                    href={`/api/settings/security/access-reviews/${current.id}?format=csv`}
                    className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
                  >
                    <DownloadSimple weight="duotone" className="size-4" aria-hidden />
                    Export CSV
                  </a>
                  {isOpen ? (
                    <>
                      <button
                        type="button"
                        onClick={() => applyReview(true)}
                        disabled={busy}
                        className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                      >
                        <ArrowsClockwise weight="duotone" className="size-4" aria-hidden />
                        Preview apply
                      </button>
                      <button
                        type="button"
                        onClick={() => applyReview(false)}
                        disabled={busy || !allDecided}
                        title={allDecided ? "" : "Decide every pending row first"}
                        className="inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
                      >
                        <CheckCircle weight="duotone" className="size-4" aria-hidden />
                        Apply revocations
                      </button>
                      <button
                        type="button"
                        onClick={cancelReview}
                        disabled={busy}
                        className="inline-flex items-center gap-1.5 rounded-md border border-rose-200 bg-white px-3 py-1.5 text-sm text-rose-700 hover:bg-rose-50 disabled:opacity-50"
                      >
                        <Prohibit weight="duotone" className="size-4" aria-hidden />
                        Cancel review
                      </button>
                    </>
                  ) : null}
                </div>
              </div>

              <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
                <table className="w-full text-left text-sm">
                  <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th scope="col" className="px-4 py-2">
                        Member
                      </th>
                      <th scope="col" className="px-4 py-2">
                        Role at review
                      </th>
                      <th scope="col" className="px-4 py-2">
                        Decision
                      </th>
                      <th scope="col" className="px-4 py-2 text-right">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {items.length === 0 ? (
                      <tr>
                        <td colSpan={4} className="px-4 py-6 text-center text-slate-500">
                          No members in this review.
                        </td>
                      </tr>
                    ) : (
                      items.map((item) => (
                        <tr key={item.id}>
                          <td className="px-4 py-2 font-medium text-slate-900">
                            <div className="truncate">{item.principal}</div>
                            {item.decided_by ? (
                              <div className="text-xs text-slate-500">
                                <Clock
                                  weight="duotone"
                                  className="mr-1 inline size-3"
                                  aria-hidden
                                />
                                {item.decided_by} · {fmtDate(item.decided_at)}
                              </div>
                            ) : null}
                          </td>
                          <td className="px-4 py-2">
                            <span className={badge(ROLE_BADGE[item.snapshot_role])}>
                              {item.snapshot_role}
                            </span>
                          </td>
                          <td className="px-4 py-2">
                            <span className={badge(DECISION_BADGE[item.decision])}>
                              {item.decision}
                            </span>
                            {item.revoked_at ? (
                              <span className="ml-2 text-xs text-rose-700">
                                revoked {fmtDate(item.revoked_at)}
                              </span>
                            ) : null}
                          </td>
                          <td className="px-4 py-2 text-right">
                            {isOpen ? (
                              <div className="inline-flex gap-1">
                                <button
                                  type="button"
                                  onClick={() => setDecision(item, "keep")}
                                  className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium transition ${item.decision === "keep" ? "border-emerald-300 bg-emerald-50 text-emerald-700" : "border-slate-200 bg-white text-slate-700 hover:border-emerald-300 hover:text-emerald-700"}`}
                                  aria-label={`Mark ${item.principal} as keep`}
                                >
                                  <CheckCircle weight="duotone" className="size-3.5" aria-hidden />
                                  Keep
                                </button>
                                <button
                                  type="button"
                                  onClick={() => setDecision(item, "revoke")}
                                  className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium transition ${item.decision === "revoke" ? "border-rose-300 bg-rose-50 text-rose-700" : "border-slate-200 bg-white text-slate-700 hover:border-rose-300 hover:text-rose-700"}`}
                                  aria-label={`Mark ${item.principal} as revoke`}
                                >
                                  <XCircle weight="duotone" className="size-3.5" aria-hidden />
                                  Revoke
                                </button>
                              </div>
                            ) : (
                              <span className="text-xs text-slate-400">sealed</span>
                            )}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "slate" | "emerald" | "rose";
}) {
  const toneClass =
    tone === "emerald"
      ? "text-emerald-700"
      : tone === "rose"
        ? "text-rose-700"
        : "text-slate-900";
  return (
    <div className="rounded-md bg-slate-50 px-3 py-2">
      <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className={`mt-0.5 text-lg font-semibold ${toneClass}`}>{value}</dd>
    </div>
  );
}
