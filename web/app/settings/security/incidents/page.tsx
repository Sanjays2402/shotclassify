"use client";

// Security incidents settings. Two halves on one page so a procurement
// reviewer can see both the public incident history this vendor will
// publish to and the notification contacts this workspace has wired up
// to receive them.
//
// Admin role + MFA step-up are required server-side for mutations; this
// page leans on the same session cookie the rest of the app uses and
// surfaces 401/403 inline rather than redirecting.

import { useMemo, useState } from "react";
import useSWR, { mutate } from "swr";
import {
  Bell,
  EnvelopeSimple,
  Plug,
  Plus,
  ShieldCheck,
  Trash,
  Warning,
  CheckCircle,
  Clock,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type Incident = {
  id: string;
  published_at: string;
  severity: "low" | "medium" | "high" | "critical";
  status: string;
  title: string;
  summary: string;
  affected_components: string[];
  advisory_url: string | null;
};

type IncidentList = {
  items: Incident[];
  count: number;
  valid_severities: string[];
  valid_statuses: string[];
};

type Subscription = {
  id: string;
  channel: "email" | "webhook";
  endpoint: string;
  severity_min: "low" | "medium" | "high" | "critical";
  active: boolean;
  label: string | null;
  created_by: string;
  created_at: string;
  last_notified_at: string | null;
  last_incident_id: string | null;
};

type SubscriptionList = {
  tenant_id: string;
  items: Subscription[];
  count: number;
  valid_channels: string[];
  valid_severities: string[];
};

type ApiError = Error & { status?: number };

const SEVERITY_BADGE: Record<string, string> = {
  low: "bg-slate-100 text-slate-700 ring-slate-200",
  medium: "bg-amber-50 text-amber-800 ring-amber-200",
  high: "bg-orange-50 text-orange-800 ring-orange-200",
  critical: "bg-red-50 text-red-800 ring-red-200",
};

const STATUS_BADGE: Record<string, string> = {
  investigating: "bg-amber-50 text-amber-800 ring-amber-200",
  identified: "bg-orange-50 text-orange-800 ring-orange-200",
  monitoring: "bg-sky-50 text-sky-800 ring-sky-200",
  resolved: "bg-emerald-50 text-emerald-800 ring-emerald-200",
};

function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded-md bg-slate-100 ${className}`}
      aria-hidden
    />
  );
}

export default function IncidentsSettingsPage() {
  const {
    data: incidents,
    error: incidentsErr,
    isLoading: incidentsLoading,
  } = useSWR<IncidentList, ApiError>("/api/trust/incidents", fetcher);

  const {
    data: subs,
    error: subsErr,
    isLoading: subsLoading,
  } = useSWR<SubscriptionList, ApiError>(
    "/api/incident-subscriptions",
    fetcher,
  );

  const [channel, setChannel] = useState<"email" | "webhook">("email");
  const [endpoint, setEndpoint] = useState("");
  const [severityMin, setSeverityMin] = useState<
    "low" | "medium" | "high" | "critical"
  >("low");
  const [label, setLabel] = useState("");
  const [submitErr, setSubmitErr] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const subsList = useMemo(() => subs?.items ?? [], [subs]);
  const subsForbidden = subsErr?.status === 401 || subsErr?.status === 403;

  async function addSubscription(e: React.FormEvent) {
    e.preventDefault();
    setSubmitErr(null);
    if (!endpoint.trim()) {
      setSubmitErr("Endpoint is required.");
      return;
    }
    setSubmitting(true);
    try {
      const r = await fetch("/api/incident-subscriptions", {
        method: "POST",
        credentials: "same-origin",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          channel,
          endpoint: endpoint.trim(),
          severity_min: severityMin,
          label: label.trim() || undefined,
        }),
      });
      if (!r.ok) {
        const text = await r.text().catch(() => "");
        setSubmitErr(text || `${r.status} ${r.statusText}`);
        return;
      }
      setEndpoint("");
      setLabel("");
      await mutate("/api/incident-subscriptions");
    } finally {
      setSubmitting(false);
    }
  }

  async function toggleActive(sub: Subscription) {
    await fetch(`/api/incident-subscriptions/${sub.id}`, {
      method: "PATCH",
      credentials: "same-origin",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ active: !sub.active }),
    });
    await mutate("/api/incident-subscriptions");
  }

  async function removeSubscription(sub: Subscription) {
    if (
      !confirm(
        `Remove ${sub.channel} notification to ${sub.endpoint}? This cannot be undone.`,
      )
    ) {
      return;
    }
    await fetch(`/api/incident-subscriptions/${sub.id}`, {
      method: "DELETE",
      credentials: "same-origin",
    });
    await mutate("/api/incident-subscriptions");
  }

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-8 sm:px-6">
      <header className="mb-6">
        <div className="flex items-center gap-2 text-slate-900">
          <ShieldCheck
            size={26}
            weight="duotone"
            className="text-slate-600"
            aria-hidden
          />
          <h1 className="text-xl font-semibold">Security incidents</h1>
        </div>
        <p className="mt-1 text-sm text-slate-600">
          The public incident history we publish, plus the contacts in this
          workspace we notify when new incidents are posted.
        </p>
      </header>

      <section
        aria-labelledby="incidents-history"
        className="mb-8 rounded-lg border border-slate-200 bg-white shadow-sm"
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <h2
            id="incidents-history"
            className="text-sm font-medium text-slate-900"
          >
            Published incidents
          </h2>
          <a
            href="/api/trust/incidents"
            className="text-xs font-medium text-slate-600 hover:text-slate-900"
          >
            JSON feed
          </a>
        </div>
        {incidentsLoading && (
          <div className="space-y-3 p-4">
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
          </div>
        )}
        {incidentsErr && (
          <div className="flex items-center gap-2 p-4 text-sm text-red-700">
            <Warning size={18} weight="duotone" aria-hidden />
            Could not load incidents: {incidentsErr.message}
          </div>
        )}
        {incidents && incidents.items.length === 0 && (
          <div className="flex items-center gap-2 p-6 text-sm text-slate-600">
            <CheckCircle
              size={20}
              weight="duotone"
              className="text-emerald-600"
              aria-hidden
            />
            No incidents have been published.
          </div>
        )}
        {incidents && incidents.items.length > 0 && (
          <ul className="divide-y divide-slate-100">
            {incidents.items.map((i) => (
              <li key={i.id} className="p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs text-slate-500">
                    {i.id}
                  </span>
                  <span
                    className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${
                      SEVERITY_BADGE[i.severity] ?? SEVERITY_BADGE.low
                    }`}
                  >
                    {i.severity}
                  </span>
                  <span
                    className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${
                      STATUS_BADGE[i.status] ?? "bg-slate-100 text-slate-700"
                    }`}
                  >
                    {i.status}
                  </span>
                  <span className="ml-auto inline-flex items-center gap-1 text-xs text-slate-500">
                    <Clock size={14} weight="duotone" aria-hidden />
                    {fmtDate(i.published_at)}
                  </span>
                </div>
                <p className="mt-2 text-sm font-medium text-slate-900">
                  {i.title}
                </p>
                <p className="mt-1 text-sm text-slate-600">{i.summary}</p>
                {i.affected_components.length > 0 && (
                  <p className="mt-2 text-xs text-slate-500">
                    Affected:{" "}
                    {i.affected_components.map((c) => (
                      <span
                        key={c}
                        className="mr-1 inline-flex items-center rounded bg-slate-100 px-1.5 py-0.5 font-mono"
                      >
                        {c}
                      </span>
                    ))}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section
        aria-labelledby="incident-subs"
        className="rounded-lg border border-slate-200 bg-white shadow-sm"
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <h2 id="incident-subs" className="text-sm font-medium text-slate-900">
            Notification contacts
          </h2>
          <span className="text-xs text-slate-500">
            Admin role and MFA required to change.
          </span>
        </div>

        {subsForbidden && (
          <div className="flex items-center gap-2 p-4 text-sm text-amber-800">
            <Warning size={18} weight="duotone" aria-hidden />
            You need the admin role and a recent MFA step-up to manage
            notification contacts.
          </div>
        )}

        {!subsForbidden && subsLoading && (
          <div className="space-y-3 p-4">
            <Skeleton className="h-12" />
            <Skeleton className="h-12" />
          </div>
        )}

        {!subsForbidden && subs && (
          <>
            {subs.items.length === 0 ? (
              <div className="flex items-center gap-2 p-6 text-sm text-slate-600">
                <Bell size={20} weight="duotone" aria-hidden />
                No contacts yet. Add an email or webhook below.
              </div>
            ) : (
              <ul className="divide-y divide-slate-100">
                {subsList.map((s) => (
                  <li
                    key={s.id}
                    className="flex flex-col gap-2 p-4 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 text-sm text-slate-900">
                        {s.channel === "email" ? (
                          <EnvelopeSimple
                            size={18}
                            weight="duotone"
                            className="text-slate-500"
                            aria-hidden
                          />
                        ) : (
                          <Plug
                            size={18}
                            weight="duotone"
                            className="text-slate-500"
                            aria-hidden
                          />
                        )}
                        <span className="truncate font-mono text-sm">
                          {s.endpoint}
                        </span>
                        {!s.active && (
                          <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 ring-1 ring-inset ring-slate-200">
                            paused
                          </span>
                        )}
                      </div>
                      <p className="mt-1 text-xs text-slate-500">
                        Severity{" "}
                        <span
                          className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${
                            SEVERITY_BADGE[s.severity_min]
                          }`}
                        >
                          {s.severity_min}+
                        </span>{" "}
                        - added by {s.created_by} on {fmtDate(s.created_at)}
                        {s.label ? ` - ${s.label}` : ""}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <button
                        type="button"
                        onClick={() => toggleActive(s)}
                        className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
                      >
                        {s.active ? "Pause" : "Resume"}
                      </button>
                      <button
                        type="button"
                        onClick={() => removeSubscription(s)}
                        className="inline-flex items-center gap-1 rounded-md border border-red-200 bg-white px-2.5 py-1.5 text-xs font-medium text-red-700 shadow-sm hover:bg-red-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400"
                        aria-label={`Remove ${s.endpoint}`}
                      >
                        <Trash size={14} weight="duotone" aria-hidden />
                        Remove
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}

            <form
              onSubmit={addSubscription}
              className="border-t border-slate-200 p-4"
            >
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-12">
                <label className="sm:col-span-3">
                  <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">
                    Channel
                  </span>
                  <select
                    value={channel}
                    onChange={(e) =>
                      setChannel(e.target.value as "email" | "webhook")
                    }
                    className="w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-sm text-slate-900 focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200"
                  >
                    <option value="email">Email</option>
                    <option value="webhook">Webhook</option>
                  </select>
                </label>
                <label className="sm:col-span-5">
                  <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">
                    {channel === "email" ? "Email address" : "Webhook URL"}
                  </span>
                  <input
                    type={channel === "email" ? "email" : "url"}
                    required
                    value={endpoint}
                    onChange={(e) => setEndpoint(e.target.value)}
                    placeholder={
                      channel === "email"
                        ? "security@acme.example"
                        : "https://hooks.acme.example/security"
                    }
                    className="w-full rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-900 placeholder:text-slate-400 focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200"
                  />
                </label>
                <label className="sm:col-span-2">
                  <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">
                    Min severity
                  </span>
                  <select
                    value={severityMin}
                    onChange={(e) =>
                      setSeverityMin(
                        e.target.value as
                          | "low"
                          | "medium"
                          | "high"
                          | "critical",
                      )
                    }
                    className="w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-sm text-slate-900 focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200"
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                    <option value="critical">Critical</option>
                  </select>
                </label>
                <label className="sm:col-span-2">
                  <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">
                    Label
                  </span>
                  <input
                    type="text"
                    value={label}
                    onChange={(e) => setLabel(e.target.value)}
                    placeholder="Optional"
                    className="w-full rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-900 placeholder:text-slate-400 focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200"
                  />
                </label>
              </div>
              {submitErr && (
                <p className="mt-3 flex items-center gap-2 text-sm text-red-700">
                  <Warning size={16} weight="duotone" aria-hidden />
                  {submitErr}
                </p>
              )}
              <div className="mt-3 flex items-center justify-end">
                <button
                  type="submit"
                  disabled={submitting}
                  className="inline-flex items-center gap-1.5 rounded-md border border-slate-900 bg-slate-900 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <Plus size={16} weight="duotone" aria-hidden />
                  {submitting ? "Adding..." : "Add contact"}
                </button>
              </div>
            </form>
          </>
        )}
      </section>
    </main>
  );
}
