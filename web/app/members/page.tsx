"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  UsersThree,
  Plus,
  Copy,
  Check,
  Trash,
  Warning,
  Envelope,
  ShieldCheck,
} from "@phosphor-icons/react/dist/ssr";

type Role = "admin" | "operator" | "viewer";

type Member = {
  id: string;
  email: string;
  role: Role;
  invited_by: string | null;
  created_at: string;
  updated_at: string;
};

type InvitationView = {
  id: string;
  email: string;
  role: Role;
  invited_by: string | null;
  created_at: string;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
  status: "pending" | "expired" | "revoked" | "accepted";
};

const ROLE_OPTIONS: { value: Role; label: string; help: string }[] = [
  { value: "admin", label: "Admin", help: "Full access including team and API keys" },
  { value: "operator", label: "Operator", help: "Read and write classifications" },
  { value: "viewer", label: "Viewer", help: "Read-only access" },
];

function fmtDate(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function MembersPage() {
  const [members, setMembers] = useState<Member[]>([]);
  const [invites, setInvites] = useState<InvitationView[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<Role>("operator");
  const [inviting, setInviting] = useState(false);
  const [revealed, setRevealed] = useState<{ email: string; token: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [savingRole, setSavingRole] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const [mr, ir] = await Promise.all([
        fetch("/api/members", { cache: "no-store" }),
        fetch("/api/invitations", { cache: "no-store" }),
      ]);
      if (!mr.ok) throw new Error(`members: ${mr.status}`);
      if (!ir.ok) throw new Error(`invitations: ${ir.status}`);
      const mj = await mr.json();
      const ij = await ir.json();
      setMembers(Array.isArray(mj.members) ? mj.members : []);
      setInvites(Array.isArray(ij.invitations) ? ij.invitations : []);
    } catch (e: any) {
      setErr(e?.message || "Failed to load team.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const onInvite = useCallback(async () => {
    const email = inviteEmail.trim();
    if (!email || !email.includes("@")) {
      setErr("Enter a valid email address.");
      return;
    }
    setInviting(true);
    setErr(null);
    try {
      const r = await fetch("/api/invitations", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, role: inviteRole, ttl_days: 7 }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j?.detail || `${r.status}`);
      setRevealed({ email: j.email, token: j.token });
      setInviteEmail("");
      await load();
    } catch (e: any) {
      setErr(e?.message || "Failed to send invitation.");
    } finally {
      setInviting(false);
    }
  }, [inviteEmail, inviteRole, load]);

  const onChangeRole = useCallback(
    async (email: string, role: Role) => {
      setSavingRole(email);
      setErr(null);
      try {
        const r = await fetch(`/api/members/${encodeURIComponent(email)}`, {
          method: "PUT",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ role }),
        });
        const j = await r.json();
        if (!r.ok) throw new Error(j?.detail || `${r.status}`);
        await load();
      } catch (e: any) {
        setErr(e?.message || "Could not update role.");
      } finally {
        setSavingRole(null);
      }
    },
    [load],
  );

  const onRemove = useCallback(
    async (email: string) => {
      if (!confirm(`Remove ${email} from the workspace?`)) return;
      setRemoving(email);
      setErr(null);
      try {
        const r = await fetch(`/api/members/${encodeURIComponent(email)}`, {
          method: "DELETE",
        });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(j?.detail || `${r.status}`);
        await load();
      } catch (e: any) {
        setErr(e?.message || "Could not remove member.");
      } finally {
        setRemoving(null);
      }
    },
    [load],
  );

  const onRevokeInvite = useCallback(
    async (id: string) => {
      setRevoking(id);
      setErr(null);
      try {
        const r = await fetch(`/api/invitations/${encodeURIComponent(id)}`, {
          method: "DELETE",
        });
        if (!r.ok) throw new Error(`${r.status}`);
        await load();
      } catch (e: any) {
        setErr(e?.message || "Could not revoke invitation.");
      } finally {
        setRevoking(null);
      }
    },
    [load],
  );

  const copyToken = useCallback(async () => {
    if (!revealed) return;
    try {
      await navigator.clipboard.writeText(revealed.token);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore */
    }
  }, [revealed]);

  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const inviteLink = useMemo(
    () => (revealed ? `${origin}/members?accept=${encodeURIComponent(revealed.token)}` : ""),
    [origin, revealed],
  );

  const adminCount = members.filter((m) => m.role === "admin").length;

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="eyebrow flex items-center gap-1.5">
            <UsersThree size={12} weight="duotone" />
            <span>Workspace</span>
          </div>
          <h1 className="h-display text-[28px] mt-1 tracking-tight">Team</h1>
          <p
            className="text-[13px] mt-1"
            style={{ color: "var(--color-ink-mute)" }}
          >
            Invite teammates and assign roles. Admins manage the team, billing,
            and API keys.
          </p>
        </div>
        <div
          className="text-[12px] flex items-center gap-1.5"
          style={{ color: "var(--color-ink-mute)" }}
        >
          <ShieldCheck size={14} weight="duotone" />
          {adminCount} admin{adminCount === 1 ? "" : "s"} active
        </div>
      </header>

      {err && (
        <div
          className="flex items-start gap-2 rounded-md border px-3 py-2 text-[13px]"
          style={{
            borderColor: "var(--color-rule)",
            background: "var(--color-chalk)",
          }}
          role="alert"
        >
          <Warning size={16} weight="duotone" />
          <span>{err}</span>
        </div>
      )}

      {/* Invite */}
      <section
        className="rounded-md border p-4 sm:p-5"
        style={{
          borderColor: "var(--color-rule)",
          background: "var(--color-chalk)",
        }}
        aria-labelledby="invite-heading"
      >
        <h2 id="invite-heading" className="eyebrow mb-3">
          Invite a teammate
        </h2>
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[220px]">
            <label htmlFor="invite-email" className="eyebrow block mb-1">
              Email
            </label>
            <input
              id="invite-email"
              type="email"
              autoComplete="email"
              placeholder="teammate@company.com"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              maxLength={255}
              className="w-full rounded-md border px-3 py-2 text-[13px] bg-white outline-none focus:ring-2"
              style={{ borderColor: "var(--color-rule)" }}
            />
          </div>
          <div className="min-w-[180px]">
            <label htmlFor="invite-role" className="eyebrow block mb-1">
              Role
            </label>
            <select
              id="invite-role"
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value as Role)}
              className="w-full rounded-md border px-3 py-2 text-[13px] bg-white outline-none focus:ring-2"
              style={{ borderColor: "var(--color-rule)" }}
            >
              {ROLE_OPTIONS.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            onClick={onInvite}
            disabled={inviting || !inviteEmail.trim()}
            className="inline-flex items-center gap-1.5 rounded-md border px-3 py-2 text-[13px] font-medium bg-white hover:bg-[color:var(--color-chalk)] disabled:opacity-50"
            style={{ borderColor: "var(--color-rule)" }}
          >
            <Plus size={14} weight="duotone" />
            {inviting ? "Sending..." : "Send invite"}
          </button>
        </div>
      </section>

      {revealed && (
        <section
          className="rounded-md border p-4 sm:p-5 space-y-3"
          style={{
            borderColor: "var(--color-rule)",
            background: "#fffaf0",
          }}
          aria-live="polite"
        >
          <div className="flex items-center gap-2 text-[13px] font-medium">
            <Envelope size={16} weight="duotone" />
            <span>Invitation link for {revealed.email}</span>
          </div>
          <p
            className="text-[12px]"
            style={{ color: "var(--color-ink-mute)" }}
          >
            Copy this link now. It is shown once. Anyone with the link can
            join the workspace as a {inviteRole}.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <code
              className="flex-1 min-w-[260px] rounded-md border px-3 py-2 text-[12px] font-mono break-all bg-white"
              style={{ borderColor: "var(--color-rule)" }}
            >
              {inviteLink}
            </code>
            <button
              type="button"
              onClick={copyToken}
              className="inline-flex items-center gap-1.5 rounded-md border px-3 py-2 text-[12px] bg-white"
              style={{ borderColor: "var(--color-rule)" }}
            >
              {copied ? <Check size={14} weight="duotone" /> : <Copy size={14} weight="duotone" />}
              {copied ? "Copied" : "Copy link"}
            </button>
            <button
              type="button"
              onClick={() => setRevealed(null)}
              className="text-[12px] underline"
              style={{ color: "var(--color-ink-mute)" }}
            >
              Dismiss
            </button>
          </div>
        </section>
      )}

      {/* Members */}
      <section aria-labelledby="members-heading" className="space-y-3">
        <h2 id="members-heading" className="eyebrow">
          Members
        </h2>
        {loading ? (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-12 rounded-md border animate-pulse"
                style={{
                  borderColor: "var(--color-rule)",
                  background: "var(--color-chalk)",
                }}
              />
            ))}
          </div>
        ) : members.length === 0 ? (
          <div
            className="rounded-md border p-6 text-center text-[13px]"
            style={{
              borderColor: "var(--color-rule)",
              color: "var(--color-ink-mute)",
            }}
          >
            No members yet. Invite the first teammate above.
          </div>
        ) : (
          <ul className="divide-y rounded-md border" style={{ borderColor: "var(--color-rule)" }}>
            {members.map((m) => {
              const isLastAdmin = m.role === "admin" && adminCount === 1;
              return (
                <li
                  key={m.id}
                  className="flex flex-wrap items-center gap-3 px-3 py-2.5 sm:px-4 sm:py-3"
                >
                  <div className="flex-1 min-w-[180px]">
                    <div className="text-[13px] font-medium break-all">{m.email}</div>
                    <div
                      className="text-[11px]"
                      style={{ color: "var(--color-ink-mute)" }}
                    >
                      Added {fmtDate(m.created_at)}
                    </div>
                  </div>
                  <select
                    aria-label={`Role for ${m.email}`}
                    value={m.role}
                    disabled={savingRole === m.email}
                    onChange={(e) => onChangeRole(m.email, e.target.value as Role)}
                    className="rounded-md border px-2 py-1.5 text-[12px] bg-white disabled:opacity-50"
                    style={{ borderColor: "var(--color-rule)" }}
                  >
                    {ROLE_OPTIONS.map((r) => (
                      <option key={r.value} value={r.value}>
                        {r.label}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => onRemove(m.email)}
                    disabled={removing === m.email || isLastAdmin}
                    title={isLastAdmin ? "Cannot remove the last admin" : "Remove member"}
                    className="inline-flex items-center gap-1 rounded-md border px-2 py-1.5 text-[12px] bg-white disabled:opacity-50"
                    style={{ borderColor: "var(--color-rule)" }}
                  >
                    <Trash size={12} weight="duotone" />
                    {removing === m.email ? "Removing..." : "Remove"}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {/* Pending invitations */}
      <section aria-labelledby="invites-heading" className="space-y-3">
        <h2 id="invites-heading" className="eyebrow">
          Pending invitations
        </h2>
        {loading ? null : invites.length === 0 ? (
          <div
            className="rounded-md border p-6 text-center text-[13px]"
            style={{
              borderColor: "var(--color-rule)",
              color: "var(--color-ink-mute)",
            }}
          >
            No pending invitations.
          </div>
        ) : (
          <ul className="divide-y rounded-md border" style={{ borderColor: "var(--color-rule)" }}>
            {invites.map((inv) => (
              <li
                key={inv.id}
                className="flex flex-wrap items-center gap-3 px-3 py-2.5 sm:px-4 sm:py-3"
              >
                <div className="flex-1 min-w-[180px]">
                  <div className="text-[13px] font-medium break-all">{inv.email}</div>
                  <div
                    className="text-[11px]"
                    style={{ color: "var(--color-ink-mute)" }}
                  >
                    {inv.role} - expires {fmtDate(inv.expires_at)}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => onRevokeInvite(inv.id)}
                  disabled={revoking === inv.id}
                  className="inline-flex items-center gap-1 rounded-md border px-2 py-1.5 text-[12px] bg-white disabled:opacity-50"
                  style={{ borderColor: "var(--color-rule)" }}
                >
                  <Trash size={12} weight="duotone" />
                  {revoking === inv.id ? "Revoking..." : "Revoke"}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
