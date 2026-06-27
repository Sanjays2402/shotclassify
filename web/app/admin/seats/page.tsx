"use client";

// Per-seat usage breakdown for the workspace owner. Pairs the seat
// inventory (from memberships) with classification volume this calendar
// month so owners can answer: how many seats am I paying for, who is
// actually using the product, and which seats are dormant. Backed by
// /v1/admin/seats/usage, which enforces the admin role and tenant
// scoping on the FastAPI side; non-admins see a denied state instead of
// fabricated data.

import Link from "next/link";
import useSWR from "swr";
import {
  Users,
  Gauge,
  Lock,
  ChartBar,
  UserMinus,
  ArrowSquareOut,
  Warning,
  Clock,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";
import { EmptyState } from "@/components/EmptyState";

type SeatRow = {
  principal: string;
  role: string | null;
  member_since: string | null;
  usage_current_period: number;
  last_activity_at: string | null;
};

type SeatsUsage = {
  tenant_id: string;
  period: { start: string; granularity: string };
  seats: {
    limit: number | null;
    in_use: { total: number; [role: string]: number };
    active_this_period: number;
    dormant_this_period: number;
  };
  totals: {
    classifications: number;
    members: number;
    orphan_principals: number;
  };
  members: SeatRow[];
  orphans: SeatRow[];
};

function fmtTs(ts: string | null): string {
  if (!ts) return "Never";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function fmtMonth(ts: string): string {
  try {
    return new Date(ts).toLocaleDateString(undefined, {
      month: "long",
      year: "numeric",
    });
  } catch {
    return ts;
  }
}

function Stat({
  icon: Icon,
  label,
  value,
  sub,
}: {
  icon: React.ComponentType<any>;
  label: string;
  value: string | number;
  sub?: string;
}) {
  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950 p-4">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-neutral-500 dark:text-neutral-400">
        <Icon size={14} weight="duotone" />
        <span>{label}</span>
      </div>
      <div className="mt-2 text-2xl font-semibold tabular-nums">{value}</div>
      {sub ? (
        <div className="mt-0.5 text-xs text-neutral-500 dark:text-neutral-400">{sub}</div>
      ) : null}
    </div>
  );
}

function RoleBadge({ role }: { role: string | null }) {
  if (!role) {
    return (
      <span className="inline-flex items-center rounded border border-amber-300/60 bg-amber-50 dark:bg-amber-950/30 px-1.5 py-0.5 text-[11px] font-medium text-amber-700 dark:text-amber-300">
        former
      </span>
    );
  }
  const tone =
    role === "owner"
      ? "border-violet-300/60 bg-violet-50 dark:bg-violet-950/30 text-violet-700 dark:text-violet-300"
      : role === "admin"
        ? "border-blue-300/60 bg-blue-50 dark:bg-blue-950/30 text-blue-700 dark:text-blue-300"
        : role === "member"
          ? "border-emerald-300/60 bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300"
          : "border-neutral-300/60 bg-neutral-50 dark:bg-neutral-900 text-neutral-600 dark:text-neutral-400";
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] font-medium ${tone}`}
    >
      {role}
    </span>
  );
}

function UsageBar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div
      className="h-1.5 w-24 overflow-hidden rounded bg-neutral-200 dark:bg-neutral-800"
      aria-label={`${value} of ${max} max`}
      role="progressbar"
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={max || 1}
    >
      <div
        className="h-full bg-neutral-900 dark:bg-neutral-100"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export default function SeatsUsagePage() {
  const { data, error, isLoading } = useSWR<SeatsUsage>(
    "/api/admin/seats/usage",
    fetcher,
    { refreshInterval: 60_000 },
  );

  if (isLoading) {
    return (
      <div className="mx-auto max-w-6xl p-4 md:p-8">
        <header className="mb-6">
          <h1 className="text-2xl font-semibold">Seat usage</h1>
          <p className="text-sm text-neutral-500 dark:text-neutral-400">
            Loading per-seat usage for this workspace.
          </p>
        </header>
        <div className="grid gap-3 grid-cols-2 md:grid-cols-4 mb-6">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="h-24 rounded-lg border border-neutral-200 dark:border-neutral-800 bg-neutral-100 dark:bg-neutral-900 animate-pulse"
            />
          ))}
        </div>
        <div className="h-64 rounded-lg border border-neutral-200 dark:border-neutral-800 bg-neutral-100 dark:bg-neutral-900 animate-pulse" />
      </div>
    );
  }

  if (error) {
    const status = (error as { status?: number }).status;
    const denied = status === 401 || status === 403;
    return (
      <div className="mx-auto max-w-2xl p-4 md:p-8">
        <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950 p-6">
          <div className="flex items-start gap-3">
            <Lock size={20} weight="duotone" className="mt-0.5 text-neutral-500" />
            <div>
              <h1 className="text-lg font-semibold">
                {denied ? "Admin access required" : "Could not load seat usage"}
              </h1>
              <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
                {denied
                  ? "Only workspace owners and admins can view billing-by-seat. Ask an owner for an upgraded role, or sign in with an admin key."
                  : "The API returned an error. Try again, or check the API service logs for the matching request id."}
              </p>
              <div className="mt-4 flex gap-2">
                <Link
                  href="/admin"
                  className="inline-flex items-center gap-1 rounded border border-neutral-300 dark:border-neutral-700 px-3 py-1.5 text-sm hover:bg-neutral-100 dark:hover:bg-neutral-900"
                >
                  Back to admin console
                </Link>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const { seats, totals, members, orphans, period } = data;
  const limit = seats.limit;
  const inUseTotal = seats.in_use?.total ?? members.length;
  const overLimit = limit != null && inUseTotal > limit;
  const topUsage = Math.max(
    1,
    ...members.map((m) => m.usage_current_period),
    ...orphans.map((m) => m.usage_current_period),
  );
  const empty = members.length === 0 && orphans.length === 0;

  return (
    <div className="mx-auto max-w-6xl p-4 md:p-8">
      <header className="mb-6 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-neutral-500 dark:text-neutral-400">
            <Link href="/admin" className="hover:underline">
              Admin
            </Link>
            <span>/</span>
            <span>Seats</span>
          </div>
          <h1 className="mt-1 text-2xl font-semibold">Seat usage</h1>
          <p className="text-sm text-neutral-500 dark:text-neutral-400">
            Per-seat activity for {fmtMonth(period.start)}. Refreshes every minute.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            href="/settings/members"
            className="inline-flex items-center gap-1 rounded border border-neutral-300 dark:border-neutral-700 px-3 py-1.5 text-sm hover:bg-neutral-100 dark:hover:bg-neutral-900"
          >
            <Users size={14} weight="duotone" />
            Manage members
            <ArrowSquareOut size={12} weight="duotone" />
          </Link>
          <Link
            href="/v1/usage"
            className="inline-flex items-center gap-1 rounded border border-neutral-300 dark:border-neutral-700 px-3 py-1.5 text-sm hover:bg-neutral-100 dark:hover:bg-neutral-900"
          >
            <ChartBar size={14} weight="duotone" />
            My usage
          </Link>
        </div>
      </header>

      {overLimit ? (
        <div className="mb-4 flex items-start gap-2 rounded-lg border border-amber-300/60 bg-amber-50 dark:bg-amber-950/30 p-3 text-sm text-amber-800 dark:text-amber-200">
          <Warning size={16} weight="duotone" className="mt-0.5" />
          <div>
            Workspace is over its seat limit ({inUseTotal} in use, limit {limit}).
            New invitations will be rejected until you remove members or raise the
            limit.
          </div>
        </div>
      ) : null}

      <div className="grid gap-3 grid-cols-2 md:grid-cols-4 mb-6">
        <Stat
          icon={Users}
          label="Seats in use"
          value={inUseTotal}
          sub={limit != null ? `of ${limit} purchased` : "no seat cap set"}
        />
        <Stat
          icon={Gauge}
          label="Active this period"
          value={seats.active_this_period}
          sub={`${seats.dormant_this_period} dormant`}
        />
        <Stat
          icon={ChartBar}
          label="Classifications"
          value={totals.classifications.toLocaleString()}
          sub="current calendar month"
        />
        <Stat
          icon={UserMinus}
          label="Former principals"
          value={totals.orphan_principals}
          sub="usage from removed members"
        />
      </div>

      <section className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950 overflow-hidden">
        <header className="flex items-center justify-between gap-2 border-b border-neutral-200 dark:border-neutral-800 px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold">Members</h2>
            <p className="text-xs text-neutral-500 dark:text-neutral-400">
              Billable seats sorted by usage this period.
            </p>
          </div>
        </header>
        {empty ? (
          <EmptyState
            variant="bare"
            icon={<Users size={22} weight="duotone" />}
            eyebrow="No seats"
            title="No members yet"
            body="No members in this workspace yet. Invite teammates to start tracking per-seat usage."
            primary={{
              label: "Invite teammates",
              href: "/settings/members",
              kind: "cue",
            }}
            data-testid="seats-empty"
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-neutral-50 dark:bg-neutral-900/60 text-xs uppercase tracking-wide text-neutral-500 dark:text-neutral-400">
                <tr>
                  <th className="px-4 py-2 text-left font-medium">Principal</th>
                  <th className="px-4 py-2 text-left font-medium">Role</th>
                  <th className="px-4 py-2 text-right font-medium">Usage</th>
                  <th className="px-4 py-2 text-left font-medium">Last activity</th>
                </tr>
              </thead>
              <tbody>
                {members.map((m) => (
                  <tr
                    key={`m-${m.principal}`}
                    className="border-t border-neutral-100 dark:border-neutral-900"
                  >
                    <td className="px-4 py-2 font-mono text-[12px] break-all">
                      {m.principal}
                    </td>
                    <td className="px-4 py-2">
                      <RoleBadge role={m.role} />
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      <div className="flex items-center justify-end gap-2">
                        <UsageBar value={m.usage_current_period} max={topUsage} />
                        <span className="w-10 text-right">
                          {m.usage_current_period.toLocaleString()}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-2 text-neutral-600 dark:text-neutral-400">
                      <div className="flex items-center gap-1.5">
                        <Clock size={12} weight="duotone" />
                        {fmtTs(m.last_activity_at)}
                      </div>
                    </td>
                  </tr>
                ))}
                {orphans.map((m) => (
                  <tr
                    key={`o-${m.principal}`}
                    className="border-t border-neutral-100 dark:border-neutral-900 bg-neutral-50/60 dark:bg-neutral-900/40"
                  >
                    <td className="px-4 py-2 font-mono text-[12px] break-all">
                      {m.principal}
                    </td>
                    <td className="px-4 py-2">
                      <RoleBadge role={null} />
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      <div className="flex items-center justify-end gap-2">
                        <UsageBar value={m.usage_current_period} max={topUsage} />
                        <span className="w-10 text-right">
                          {m.usage_current_period.toLocaleString()}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-2 text-neutral-600 dark:text-neutral-400">
                      <div className="flex items-center gap-1.5">
                        <Clock size={12} weight="duotone" />
                        {fmtTs(m.last_activity_at)}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <p className="mt-4 text-xs text-neutral-500 dark:text-neutral-400">
        Tenant {data.tenant_id}. Period start {fmtTs(period.start)} ({period.granularity}).
      </p>
    </div>
  );
}
