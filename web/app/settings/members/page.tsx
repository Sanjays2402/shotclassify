"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import {
  Users,
  EnvelopeSimple,
  Trash,
  Plus,
  Copy,
  CheckCircle,
  Warning,
  Shield,
  Clock,
  XCircle,
  Seat,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type Role = "admin" | "operator" | "viewer";

type Member = {
  id: string;
  principal: string;
  role: Role;
  created_at: string;
};

type Invitation = {
  id: string;
  email: string;
  role: Role;
  status: "pending" | "accepted" | "expired" | "revoked";
  created_at: string;
  expires_at: string;
};

type ApiError = Error & { status?: number };

const ROLES: Role[] = ["admin", "operator", "viewer"];

function roleBadge(role: Role) {
  const tone: Record<Role, string> = {
    admin: "bg-amber-50 text-amber-700 ring-amber-200",
    operator: "bg-blue-50 text-blue-700 ring-blue-200",
    viewer: "bg-slate-50 text-slate-700 ring-slate-200",
  };
  return `inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${tone[role]}`;
}

function statusBadge(status: Invitation["status"]) {
  const tone: Record<Invitation["status"], string> = {
    pending: "bg-amber-50 text-amber-700 ring-amber-200",
    accepted: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    expired: "bg-slate-50 text-slate-500 ring-slate-200",
    revoked: "bg-rose-50 text-rose-700 ring-rose-200",
  };
  return `inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${tone[status]}`;
}

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function MembersSettingsPage() {
  const members = useSWR<{ members: Member[]; tenant_id: string }>(
    "/api/workspace/members",
    fetcher,
    { revalidateOnFocus: false },
  );
  const invites = useSWR<{ invitations: Invitation[] }>(
    "/api/workspace/invitations",
    fetcher,
    { revalidateOnFocus: false },
  );
  const seats = useSWR<{
    tenant_id: string;
    seat_limit: number | null;
    seats_in_use: { members: number; pending_invitations: number; total: number };
    seats_available: number | null;
  }>("/api/workspace/seats", fetcher, { revalidateOnFocus: false });
  const [seatDraft, setSeatDraft] = useState<string>("");
  const [seatBusy, setSeatBusy] = useState(false);

  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("operator");
  const [otp, setOtp] = useState("");
  const [ttlDays, setTtlDays] = useState(7);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; msg: string } | null>(
    null,
  );
  const [issuedToken, setIssuedToken] = useState<string | null>(null);

  const memberError = members.error as ApiError | undefined;
  const forbidden = memberError?.status === 403;
  const unauth = memberError?.status === 401;

  const adminCount = useMemo(
    () => (members.data?.members ?? []).filter((m) => m.role === "admin").length,
    [members.data],
  );

  const invite = async () => {
    setBusy(true);
    setFlash(null);
    setIssuedToken(null);
    try {
      const res = await fetch("/api/workspace/invitations", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          ...(otp ? { "x-mfa-otp": otp } : {}),
        },
        body: JSON.stringify({ email: email.trim(), role, ttl_days: ttlDays }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(body?.detail || `${res.status} ${res.statusText}`);
      }
      setIssuedToken(body.token as string);
      setEmail("");
      setOtp("");
      setFlash({ kind: "ok", msg: `Invited ${body.email}. Share the token below once.` });
      invites.mutate();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setFlash({ kind: "err", msg });
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (id: string) => {
    if (!confirm("Revoke this invitation? The token will stop working.")) return;
    const res = await fetch(`/api/workspace/invitations/${encodeURIComponent(id)}`, {
      method: "DELETE",
      headers: otp ? { "x-mfa-otp": otp } : undefined,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      setFlash({ kind: "err", msg: text || `${res.status} ${res.statusText}` });
      return;
    }
    invites.mutate();
  };

  const changeRole = async (principal: string, nextRole: Role) => {
    const res = await fetch(
      `/api/workspace/members/${encodeURIComponent(principal)}`,
      {
        method: "PUT",
        headers: {
          "content-type": "application/json",
          ...(otp ? { "x-mfa-otp": otp } : {}),
        },
        body: JSON.stringify({ role: nextRole }),
      },
    );
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      setFlash({ kind: "err", msg: body?.detail || `${res.status} ${res.statusText}` });
      return;
    }
    members.mutate();
  };

  const removeMember = async (principal: string) => {
    if (!confirm(`Remove ${principal} from the workspace?`)) return;
    const res = await fetch(
      `/api/workspace/members/${encodeURIComponent(principal)}`,
      {
        method: "DELETE",
        headers: otp ? { "x-mfa-otp": otp } : undefined,
      },
    );
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      setFlash({ kind: "err", msg: body?.detail || `${res.status} ${res.statusText}` });
      return;
    }
    members.mutate();
  };

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-8 sm:px-6 sm:py-12">
      <header className="mb-8 flex items-start gap-3">
        <Users size={28} weight="duotone" className="mt-1 text-slate-700" />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            Workspace members
          </h1>
          <p className="mt-1 text-sm text-slate-600">
            Invite teammates, assign roles, and revoke access. Role changes and
            invitations are audit logged and require MFA step-up.
          </p>
        </div>
      </header>

      {unauth && (
        <div className="mb-6 rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          Sign in to manage workspace members.
        </div>
      )}
      {forbidden && (
        <div className="mb-6 rounded-md border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">
          You need the admin role on this workspace to manage members.
        </div>
      )}

      {!unauth && !forbidden && (
        <>
          <SeatPanel
            data={seats.data}
            loading={!seats.data && !seats.error}
            draft={seatDraft}
            setDraft={setSeatDraft}
            busy={seatBusy}
            otp={otp}
            onSave={async (next) => {
              setSeatBusy(true);
              setFlash(null);
              try {
                const res = await fetch("/api/workspace/seats", {
                  method: "PUT",
                  headers: {
                    "content-type": "application/json",
                    ...(otp ? { "x-mfa-otp": otp } : {}),
                  },
                  body: JSON.stringify({ seat_limit: next }),
                });
                const body = await res.json().catch(() => ({}));
                if (!res.ok) {
                  throw new Error(
                    typeof body?.detail === "string"
                      ? body.detail
                      : `${res.status} ${res.statusText}`,
                  );
                }
                setSeatDraft("");
                setFlash({
                  kind: "ok",
                  msg:
                    next === null
                      ? "Seat limit removed. Workspace is now unlimited."
                      : `Seat limit set to ${next}.`,
                });
                seats.mutate();
              } catch (err: unknown) {
                const msg = err instanceof Error ? err.message : String(err);
                setFlash({ kind: "err", msg });
              } finally {
                setSeatBusy(false);
              }
            }}
          />
          <section className="mb-8 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="mb-1 flex items-center gap-2 text-base font-semibold text-slate-900">
              <EnvelopeSimple size={20} weight="duotone" className="text-slate-700" />
              Invite a teammate
            </h2>
            <p className="mb-4 text-sm text-slate-600">
              Send a one-time invite token. The recipient signs in and accepts it.
            </p>
            <div className="grid gap-3 sm:grid-cols-[1fr_140px_120px_auto]">
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="alice@company.com"
                className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
              />
              <select
                value={role}
                onChange={(e) => setRole(e.target.value as Role)}
                className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
              <input
                type="number"
                min={1}
                max={90}
                value={ttlDays}
                onChange={(e) => setTtlDays(Math.max(1, Math.min(90, Number(e.target.value) || 7)))}
                title="Days until the invitation expires"
                className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
              />
              <button
                onClick={invite}
                disabled={busy || !email.includes("@")}
                className="inline-flex items-center justify-center gap-1 rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
              >
                <Plus size={16} weight="bold" />
                Invite
              </button>
            </div>
            <div className="mt-3 flex items-center gap-2 text-xs text-slate-500">
              <Shield size={14} weight="duotone" />
              <span>MFA step-up code (TOTP) if your account requires it:</span>
              <input
                value={otp}
                onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))}
                placeholder="123456"
                inputMode="numeric"
                className="w-24 rounded border border-slate-300 px-2 py-1 text-xs font-mono"
              />
            </div>
            {flash && (
              <div
                className={`mt-4 flex items-start gap-2 rounded-md p-3 text-sm ${
                  flash.kind === "ok"
                    ? "bg-emerald-50 text-emerald-900"
                    : "bg-rose-50 text-rose-900"
                }`}
              >
                {flash.kind === "ok" ? (
                  <CheckCircle size={16} weight="duotone" className="mt-0.5" />
                ) : (
                  <Warning size={16} weight="duotone" className="mt-0.5" />
                )}
                <span className="break-words">{flash.msg}</span>
              </div>
            )}
            {issuedToken && (
              <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs">
                <div className="mb-1 font-medium text-amber-900">
                  One-time invite token (shown once):
                </div>
                <div className="flex items-center gap-2">
                  <code className="flex-1 break-all rounded bg-white px-2 py-1 font-mono text-[11px] text-amber-900 ring-1 ring-amber-200">
                    {issuedToken}
                  </code>
                  <button
                    onClick={() => {
                      navigator.clipboard?.writeText(issuedToken).catch(() => {});
                    }}
                    className="inline-flex items-center gap-1 rounded-md bg-amber-200 px-2 py-1 text-xs font-medium text-amber-900 hover:bg-amber-300"
                  >
                    <Copy size={12} weight="bold" />
                    Copy
                  </button>
                </div>
              </div>
            )}
          </section>

          <section className="mb-8 rounded-lg border border-slate-200 bg-white shadow-sm">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
              <h2 className="text-base font-semibold text-slate-900">Members</h2>
              <span className="text-xs text-slate-500">
                {members.data?.members?.length ?? 0} total, {adminCount} admin
              </span>
            </div>
            {members.isLoading && (
              <div className="p-5">
                <div className="h-4 w-1/3 animate-pulse rounded bg-slate-200" />
                <div className="mt-3 h-4 w-1/2 animate-pulse rounded bg-slate-200" />
              </div>
            )}
            {!members.isLoading && (members.data?.members?.length ?? 0) === 0 && (
              <div className="px-5 py-10 text-center text-sm text-slate-500">
                No members yet. Invite someone above to get started.
              </div>
            )}
            {!members.isLoading && (members.data?.members?.length ?? 0) > 0 && (
              <ul className="divide-y divide-slate-100">
                {(members.data?.members ?? []).map((m) => (
                  <li
                    key={m.id}
                    className="flex flex-col gap-2 px-5 py-3 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-slate-900">
                        {m.principal}
                      </div>
                      <div className="text-xs text-slate-500">
                        added {fmtDate(m.created_at)}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={roleBadge(m.role)}>{m.role}</span>
                      <select
                        value={m.role}
                        onChange={(e) => changeRole(m.principal, e.target.value as Role)}
                        aria-label={`Change role for ${m.principal}`}
                        className="rounded-md border border-slate-300 px-2 py-1 text-xs"
                      >
                        {ROLES.map((r) => (
                          <option key={r} value={r}>
                            {r}
                          </option>
                        ))}
                      </select>
                      <button
                        onClick={() => removeMember(m.principal)}
                        aria-label={`Remove ${m.principal}`}
                        className="inline-flex items-center justify-center rounded-md p-1.5 text-slate-500 hover:bg-rose-50 hover:text-rose-700"
                      >
                        <Trash size={16} weight="duotone" />
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="rounded-lg border border-slate-200 bg-white shadow-sm">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
              <h2 className="text-base font-semibold text-slate-900">
                Pending invitations
              </h2>
            </div>
            {invites.isLoading && (
              <div className="p-5">
                <div className="h-4 w-1/3 animate-pulse rounded bg-slate-200" />
              </div>
            )}
            {!invites.isLoading && (invites.data?.invitations?.length ?? 0) === 0 && (
              <div className="px-5 py-10 text-center text-sm text-slate-500">
                No pending invitations.
              </div>
            )}
            {!invites.isLoading && (invites.data?.invitations?.length ?? 0) > 0 && (
              <ul className="divide-y divide-slate-100">
                {(invites.data?.invitations ?? []).map((inv) => (
                  <li
                    key={inv.id}
                    className="flex flex-col gap-2 px-5 py-3 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-slate-900">
                        {inv.email}
                      </div>
                      <div className="flex items-center gap-2 text-xs text-slate-500">
                        <Clock size={12} weight="duotone" />
                        expires {fmtDate(inv.expires_at)}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={roleBadge(inv.role)}>{inv.role}</span>
                      <span className={statusBadge(inv.status)}>{inv.status}</span>
                      <button
                        onClick={() => revoke(inv.id)}
                        aria-label={`Revoke invitation for ${inv.email}`}
                        className="inline-flex items-center justify-center rounded-md p-1.5 text-slate-500 hover:bg-rose-50 hover:text-rose-700"
                      >
                        <XCircle size={16} weight="duotone" />
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}

type SeatSummary = {
  tenant_id: string;
  seat_limit: number | null;
  seats_in_use: { members: number; pending_invitations: number; total: number };
  seats_available: number | null;
};

function SeatPanel({
  data,
  loading,
  draft,
  setDraft,
  busy,
  otp,
  onSave,
}: {
  data: SeatSummary | undefined;
  loading: boolean;
  draft: string;
  setDraft: (v: string) => void;
  busy: boolean;
  otp: string;
  onSave: (next: number | null) => Promise<void>;
}) {
  const limit = data?.seat_limit ?? null;
  const total = data?.seats_in_use.total ?? 0;
  const available = data?.seats_available ?? null;
  const atCap = limit !== null && total >= limit;
  const nearCap =
    limit !== null && !atCap && total >= Math.max(1, Math.floor(limit * 0.8));

  const pct = limit && limit > 0 ? Math.min(100, Math.round((total / limit) * 100)) : 0;
  const barTone = atCap
    ? "bg-rose-500"
    : nearCap
      ? "bg-amber-500"
      : "bg-emerald-500";

  const parsed = draft.trim() === "" ? null : Number(draft);
  const draftValid =
    draft.trim() === "" || (Number.isInteger(parsed) && (parsed as number) >= 1);

  return (
    <section className="mb-8 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="flex items-start gap-2">
          <Seat size={20} weight="duotone" className="mt-0.5 text-slate-700" />
          <div>
            <h2 className="text-base font-semibold text-slate-900">Seats</h2>
            <p className="mt-0.5 text-xs text-slate-500">
              A seat is one active member or one pending invitation. Lower the
              cap to block new seats without removing anyone.
            </p>
          </div>
        </div>
        {limit !== null && (
          <span
            className={
              atCap
                ? "inline-flex items-center rounded-md bg-rose-50 px-2 py-0.5 text-xs font-medium text-rose-700 ring-1 ring-inset ring-rose-200"
                : nearCap
                  ? "inline-flex items-center rounded-md bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700 ring-1 ring-inset ring-amber-200"
                  : "inline-flex items-center rounded-md bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700 ring-1 ring-inset ring-emerald-200"
            }
          >
            {atCap ? "At cap" : nearCap ? "Near cap" : "Healthy"}
          </span>
        )}
      </div>

      {loading ? (
        <div className="h-16 animate-pulse rounded-md bg-slate-100" />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
            <Stat label="In use" value={String(total)} />
            <Stat
              label="Members"
              value={String(data?.seats_in_use.members ?? 0)}
            />
            <Stat
              label="Pending"
              value={String(data?.seats_in_use.pending_invitations ?? 0)}
            />
            <Stat
              label="Available"
              value={limit === null ? "Unlimited" : String(available ?? 0)}
            />
          </div>

          {limit !== null && (
            <div className="mt-4">
              <div className="mb-1 flex items-center justify-between text-xs text-slate-500">
                <span>
                  {total} of {limit} used
                </span>
                <span>{pct}%</span>
              </div>
              <div
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={limit}
                aria-valuenow={total}
                className="h-2 w-full overflow-hidden rounded-full bg-slate-100"
              >
                <div
                  className={`h-full ${barTone}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          )}

          <div className="mt-5 flex flex-col gap-2 sm:flex-row sm:items-end">
            <label className="flex-1">
              <span className="mb-1 block text-xs font-medium text-slate-700">
                Seat limit
              </span>
              <input
                type="number"
                inputMode="numeric"
                min={1}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder={limit === null ? "Unlimited" : String(limit)}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
              />
              {!draftValid && (
                <span className="mt-1 block text-xs text-rose-600">
                  Enter a whole number greater than zero, or leave blank for
                  unlimited.
                </span>
              )}
            </label>
            <button
              type="button"
              disabled={busy || !draftValid || draft.trim() === ""}
              onClick={() => onSave(parsed as number)}
              className="inline-flex items-center justify-center rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
            >
              {busy ? "Saving" : "Save limit"}
            </button>
            <button
              type="button"
              disabled={busy || limit === null}
              onClick={() => onSave(null)}
              className="inline-flex items-center justify-center rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              Remove cap
            </button>
          </div>
          {!otp && (
            <p className="mt-2 text-xs text-slate-500">
              Saving requires an MFA code. Add yours in the invite section
              below before changing the cap.
            </p>
          )}
        </>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="mt-0.5 text-lg font-semibold text-slate-900">{value}</div>
    </div>
  );
}
