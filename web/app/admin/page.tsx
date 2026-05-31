"use client";

// Workspace admin console. Single read-only landing page for owners and
// admins that aggregates the operational state of the workspace and links
// out to each management surface. Backend (FastAPI) enforces the admin
// role; this UI shows a clean denied state for lower roles instead of
// pretending to work.

import Link from "next/link";
import useSWR from "swr";
import {
  Users,
  Key,
  ShieldCheck,
  ListMagnifyingGlass,
  EnvelopeSimple,
  ChartLineUp,
  Pulse,
  Lock,
  ShieldWarning,
  ArrowSquareOut,
  WebhooksLogo,
  Gavel,
  Scales,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type Overview = {
  tenant_id: string;
  members: {
    total: number;
    by_role: Record<string, number>;
    list: Array<{ principal: string; role: string; created_at: string }>;
  };
  invitations: {
    pending: number;
    list: Array<{ id: string; email: string; role: string; created_at: string }>;
  };
  sessions: { active: number; total: number };
  api_keys: {
    active: number;
    list: Array<{
      id: string;
      name: string;
      scopes: string[];
      last_used_at: string | null;
      created_at: string;
    }>;
  };
  audit: {
    recent: Array<{
      ts: string;
      principal: string | null;
      method: string;
      path: string;
      status: number;
    }>;
  };
  classifications: { total: number };
};

function StatCard({
  icon,
  label,
  value,
  href,
  sub,
}: {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  href: string;
  sub?: string;
}) {
  return (
    <Link
      href={href}
      className="block rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950 p-4 hover:border-neutral-400 dark:hover:border-neutral-600 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
    >
      <div className="flex items-center justify-between mb-2">
        <div className="text-neutral-500 dark:text-neutral-400">{icon}</div>
        <ArrowSquareOut
          size={14}
          className="text-neutral-400 dark:text-neutral-600"
          weight="duotone"
        />
      </div>
      <div className="text-sm text-neutral-500 dark:text-neutral-400">
        {label}
      </div>
      <div className="text-2xl font-semibold tabular-nums text-neutral-900 dark:text-neutral-100">
        {value}
      </div>
      {sub ? (
        <div className="text-xs text-neutral-500 dark:text-neutral-400 mt-1">
          {sub}
        </div>
      ) : null}
    </Link>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950 overflow-hidden">
      <header className="px-4 py-3 border-b border-neutral-200 dark:border-neutral-800 text-sm font-medium text-neutral-700 dark:text-neutral-300">
        {title}
      </header>
      <div className="text-sm">{children}</div>
    </section>
  );
}

function fmt(ts: string | null | undefined): string {
  if (!ts) return "never";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

export default function AdminConsolePage() {
  const { data, error, isLoading } = useSWR<Overview>(
    "/api/admin/overview",
    fetcher,
    { refreshInterval: 30_000 },
  );

  if (isLoading) {
    return (
      <div className="mx-auto max-w-6xl p-4 md:p-8">
        <header className="mb-6">
          <h1 className="text-2xl font-semibold">Admin console</h1>
          <p className="text-sm text-neutral-500 dark:text-neutral-400">
            Loading workspace state.
          </p>
        </header>
        <div className="grid gap-3 grid-cols-2 md:grid-cols-3 lg:grid-cols-6 mb-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className="h-24 rounded-lg border border-neutral-200 dark:border-neutral-800 bg-neutral-100 dark:bg-neutral-900 animate-pulse"
            />
          ))}
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="h-64 rounded-lg border border-neutral-200 dark:border-neutral-800 bg-neutral-100 dark:bg-neutral-900 animate-pulse" />
          <div className="h-64 rounded-lg border border-neutral-200 dark:border-neutral-800 bg-neutral-100 dark:bg-neutral-900 animate-pulse" />
        </div>
      </div>
    );
  }

  if (error) {
    const status = (error as { status?: number }).status;
    const denied = status === 401 || status === 403;
    return (
      <div className="mx-auto max-w-2xl p-4 md:p-8">
        <header className="mb-4">
          <h1 className="text-2xl font-semibold">Admin console</h1>
        </header>
        <div className="rounded-lg border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 p-4 flex gap-3 items-start">
          <Lock
            size={20}
            weight="duotone"
            className="text-amber-700 dark:text-amber-400 shrink-0 mt-0.5"
          />
          <div className="text-sm">
            <div className="font-medium text-amber-900 dark:text-amber-200">
              {denied ? "Admin role required" : "Could not load overview"}
            </div>
            <div className="text-amber-800 dark:text-amber-300/80 mt-1">
              {denied
                ? "Ask a workspace owner to grant you the admin role, or sign in with an admin API key."
                : "The API returned an unexpected error. Check the request log and try again."}
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const roles = Object.entries(data.members.by_role).sort();

  return (
    <div className="mx-auto max-w-6xl p-4 md:p-8 space-y-6">
      <header>
        <div className="flex items-center gap-3 mb-1">
          <ShieldCheck
            size={22}
            weight="duotone"
            className="text-neutral-700 dark:text-neutral-300"
          />
          <h1 className="text-2xl font-semibold">Admin console</h1>
        </div>
        <p className="text-sm text-neutral-500 dark:text-neutral-400">
          Workspace{" "}
          <span className="font-mono text-neutral-700 dark:text-neutral-300">
            {data.tenant_id}
          </span>
        </p>
      </header>

      <div className="grid gap-3 grid-cols-2 md:grid-cols-3 lg:grid-cols-6">
        <StatCard
          icon={<Users size={18} weight="duotone" />}
          label="Members"
          value={data.members.total}
          href="/settings/members"
          sub={roles.map(([r, n]) => `${n} ${r}`).join(", ") || undefined}
        />
        <StatCard
          icon={<EnvelopeSimple size={18} weight="duotone" />}
          label="Invitations"
          value={data.invitations.pending}
          href="/settings/members"
          sub="pending"
        />
        <StatCard
          icon={<ShieldCheck size={18} weight="duotone" />}
          label="Sessions"
          value={data.sessions.active}
          href="/settings/sessions"
          sub={`${data.sessions.total} total`}
        />
        <StatCard
          icon={<Key size={18} weight="duotone" />}
          label="API keys"
          value={data.api_keys.active}
          href="/keys"
          sub="active"
        />
        <StatCard
          icon={<ChartLineUp size={18} weight="duotone" />}
          label="Classifications"
          value={data.classifications.total.toLocaleString()}
          href="/usage"
        />
        <StatCard
          icon={<ListMagnifyingGlass size={18} weight="duotone" />}
          label="Audit events"
          value={data.audit.recent.length}
          href="/settings/audit"
          sub="recent"
        />
        <StatCard
          icon={<WebhooksLogo size={18} weight="duotone" />}
          label="Webhooks"
          value="Manage"
          href="/admin/api-webhooks"
          sub="signed deliveries"
        />
        <StatCard
          icon={<Gavel size={18} weight="duotone" />}
          label="Legal holds"
          value="Manage"
          href="/admin/legal-holds"
          sub="freeze deletes"
        />
        <StatCard
          icon={<Scales size={18} weight="duotone" />}
          label="Legal agreements"
          value="Review"
          href="/admin/legal"
          sub="TOS, DPA, AUP"
        />
        <StatCard
          icon={<Pulse size={18} weight="duotone" />}
          label="Observability"
          value="Probes"
          href="/admin/observability"
          sub="healthz, readyz, metrics"
        />
        <StatCard
          icon={<ShieldWarning size={18} weight="duotone" />}
          label="Auth lockouts"
          value="Review"
          href="/admin/lockouts"
          sub="brute-force defense"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Recent audit events">
          {data.audit.recent.length === 0 ? (
            <div className="p-4 text-neutral-500 dark:text-neutral-400">
              No audit events recorded yet.
            </div>
          ) : (
            <ul className="divide-y divide-neutral-200 dark:divide-neutral-800">
              {data.audit.recent.map((row, i) => (
                <li
                  key={i}
                  className="px-4 py-2 flex items-center gap-3 text-xs"
                >
                  <span className="text-neutral-500 dark:text-neutral-400 tabular-nums w-40 shrink-0">
                    {fmt(row.ts)}
                  </span>
                  <span className="font-mono w-14 text-neutral-700 dark:text-neutral-300">
                    {row.method}
                  </span>
                  <span className="font-mono flex-1 truncate text-neutral-700 dark:text-neutral-300">
                    {row.path}
                  </span>
                  <span
                    className={
                      row.status >= 400
                        ? "text-red-600 dark:text-red-400 tabular-nums"
                        : "text-emerald-700 dark:text-emerald-400 tabular-nums"
                    }
                  >
                    {row.status}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Members">
          {data.members.list.length === 0 ? (
            <div className="p-4 text-neutral-500 dark:text-neutral-400">
              No members yet. Invite teammates from{" "}
              <Link
                href="/settings/members"
                className="underline underline-offset-2"
              >
                Members
              </Link>
              .
            </div>
          ) : (
            <ul className="divide-y divide-neutral-200 dark:divide-neutral-800">
              {data.members.list.map((m) => (
                <li
                  key={m.principal}
                  className="px-4 py-2 flex items-center gap-3 text-sm"
                >
                  <span className="font-mono flex-1 truncate text-neutral-800 dark:text-neutral-200">
                    {m.principal}
                  </span>
                  <span className="text-xs rounded px-2 py-0.5 border border-neutral-200 dark:border-neutral-800 text-neutral-600 dark:text-neutral-400">
                    {m.role}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="API keys">
          {data.api_keys.list.length === 0 ? (
            <div className="p-4 text-neutral-500 dark:text-neutral-400">
              No active keys. Create one from{" "}
              <Link href="/keys" className="underline underline-offset-2">
                API keys
              </Link>
              .
            </div>
          ) : (
            <ul className="divide-y divide-neutral-200 dark:divide-neutral-800">
              {data.api_keys.list.map((k) => (
                <li
                  key={k.id}
                  className="px-4 py-2 flex flex-col gap-1 text-sm"
                >
                  <div className="flex items-center gap-2">
                    <span className="truncate font-medium text-neutral-800 dark:text-neutral-200">
                      {k.name || k.id}
                    </span>
                    <span className="text-xs text-neutral-500 dark:text-neutral-400 ml-auto tabular-nums">
                      last used {fmt(k.last_used_at)}
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {k.scopes.map((s) => (
                      <span
                        key={s}
                        className="text-[10px] rounded px-1.5 py-0.5 bg-neutral-100 dark:bg-neutral-900 text-neutral-600 dark:text-neutral-400 font-mono"
                      >
                        {s}
                      </span>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Pending invitations">
          {data.invitations.list.length === 0 ? (
            <div className="p-4 text-neutral-500 dark:text-neutral-400">
              No pending invitations.
            </div>
          ) : (
            <ul className="divide-y divide-neutral-200 dark:divide-neutral-800">
              {data.invitations.list.map((inv) => (
                <li
                  key={inv.id}
                  className="px-4 py-2 flex items-center gap-3 text-sm"
                >
                  <span className="flex-1 truncate text-neutral-800 dark:text-neutral-200">
                    {inv.email}
                  </span>
                  <span className="text-xs text-neutral-500 dark:text-neutral-400">
                    {inv.role}
                  </span>
                  <span className="text-xs text-neutral-500 dark:text-neutral-400 tabular-nums">
                    {fmt(inv.created_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
    </div>
  );
}
