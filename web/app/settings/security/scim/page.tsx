"use client";

// SCIM 2.0 provisioning settings. Lets a workspace admin turn the SCIM
// data plane on, mint and rotate the bearer token an external IdP will
// use, and pick the default role the IdP will hand out to provisioned
// users. The plaintext token is shown exactly once at rotation time and
// must be copied into the IdP application config; we only ever store
// the SHA-256 on the server.

import { useEffect, useState } from "react";
import useSWR from "swr";
import {
  PlugsConnected,
  Key,
  ArrowsClockwise,
  Trash,
  Warning,
  CheckCircle,
  Copy,
  ShieldCheck,
  Clock,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type ScimConfig = {
  tenant_id: string;
  enabled: boolean;
  token_last_four: string | null;
  token_rotated_at: string | null;
  default_role: string;
  has_token: boolean;
};

type RotateResponse = {
  token: string;
  token_display_once: boolean;
  config: ScimConfig;
};

type ApiError = Error & { status?: number };

const ROLE_OPTIONS: { value: string; label: string; help: string }[] = [
  {
    value: "viewer",
    label: "Viewer",
    help: "Read-only. Safe default for a broad org rollout.",
  },
  {
    value: "operator",
    label: "Operator",
    help: "Can run classifications. Pick this only if the IdP group is curated.",
  },
];

function shortDate(iso: string | null): string {
  if (!iso) return "Never";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function ScimSettingsPage() {
  const { data, error, isLoading, mutate } = useSWR<ScimConfig>(
    "/api/settings/security/scim",
    fetcher,
    { revalidateOnFocus: false },
  );

  const [busy, setBusy] = useState<string | null>(null);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);
  const [freshToken, setFreshToken] = useState<string | null>(null);
  const [mfa, setMfa] = useState("");
  const [defaultRole, setDefaultRole] = useState<string>("viewer");

  useEffect(() => {
    if (data?.default_role) setDefaultRole(data.default_role);
  }, [data]);

  const status = error as ApiError | undefined;
  const unauth = status?.status === 401;
  const forbidden = status?.status === 403;

  function ok(msg: string) {
    setFlash({ kind: "ok", msg });
    setTimeout(() => setFlash(null), 4000);
  }
  function bad(msg: string) {
    setFlash({ kind: "err", msg });
    setTimeout(() => setFlash(null), 7000);
  }

  async function callJson(
    url: string,
    init: RequestInit,
  ): Promise<{ ok: boolean; status: number; body: unknown }> {
    const headers = new Headers(init.headers ?? {});
    if (mfa) headers.set("x-mfa-otp", mfa);
    const r = await fetch(url, { ...init, headers });
    let body: unknown = null;
    try {
      body = await r.json();
    } catch {
      body = null;
    }
    return { ok: r.ok, status: r.status, body };
  }

  async function setEnabled(next: boolean) {
    setBusy("enabled");
    const r = await callJson("/api/settings/security/scim/enabled", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ enabled: next }),
    });
    setBusy(null);
    if (!r.ok) {
      const detail = (r.body as { detail?: string })?.detail ?? `HTTP ${r.status}`;
      bad(`Could not update SCIM: ${detail}`);
      return;
    }
    ok(next ? "SCIM provisioning enabled." : "SCIM provisioning disabled.");
    mutate();
  }

  async function rotate() {
    if (data?.has_token && !confirm("Rotating invalidates the current SCIM token. Continue?")) return;
    setBusy("rotate");
    const r = await callJson("/api/settings/security/scim/token", { method: "POST" });
    setBusy(null);
    if (!r.ok) {
      const detail = (r.body as { detail?: string })?.detail ?? `HTTP ${r.status}`;
      bad(`Rotation failed: ${detail}`);
      return;
    }
    const body = r.body as RotateResponse;
    setFreshToken(body.token);
    ok("New SCIM token minted. Copy it now, it will not be shown again.");
    mutate();
  }

  async function revoke() {
    if (!confirm("Revoke the current SCIM token? The IdP will start failing immediately.")) return;
    setBusy("revoke");
    const r = await callJson("/api/settings/security/scim/token", { method: "DELETE" });
    setBusy(null);
    if (!r.ok) {
      const detail = (r.body as { detail?: string })?.detail ?? `HTTP ${r.status}`;
      bad(`Revoke failed: ${detail}`);
      return;
    }
    setFreshToken(null);
    ok("SCIM token revoked.");
    mutate();
  }

  async function saveDefaultRole() {
    setBusy("role");
    const r = await callJson("/api/settings/security/scim/default-role", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ role: defaultRole }),
    });
    setBusy(null);
    if (!r.ok) {
      const detail = (r.body as { detail?: string })?.detail ?? `HTTP ${r.status}`;
      bad(`Could not save default role: ${detail}`);
      return;
    }
    ok("Default role updated.");
    mutate();
  }

  async function copyToken() {
    if (!freshToken) return;
    try {
      await navigator.clipboard.writeText(freshToken);
      ok("Token copied to clipboard.");
    } catch {
      bad("Clipboard blocked. Select and copy manually.");
    }
  }

  if (unauth) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10">
        <Banner
          kind="err"
          icon={<Warning weight="duotone" className="size-5" />}
          title="Sign in required"
          body="You need to sign in to view SCIM settings."
        />
      </main>
    );
  }

  if (forbidden) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10">
        <Banner
          kind="err"
          icon={<ShieldCheck weight="duotone" className="size-5" />}
          title="Admin role required"
          body="SCIM provisioning is a workspace admin setting. Ask your workspace owner to grant the admin role."
        />
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl px-4 py-8 sm:py-10">
      <header className="mb-8 flex items-start gap-3">
        <span className="rounded-lg bg-zinc-100 p-2 dark:bg-zinc-900">
          <PlugsConnected weight="duotone" className="size-6 text-zinc-700 dark:text-zinc-300" />
        </span>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">SCIM provisioning</h1>
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
            Connect Okta, Azure AD, Google Workspace, or any SCIM 2.0 identity provider to auto
            provision and de provision workspace members. Tenant scoped, hash indexed, with a kill
            switch.
          </p>
        </div>
      </header>

      {flash && (
        <div className="mb-4">
          <Banner
            kind={flash.kind}
            icon={
              flash.kind === "ok" ? (
                <CheckCircle weight="duotone" className="size-5" />
              ) : (
                <Warning weight="duotone" className="size-5" />
              )
            }
            title={flash.kind === "ok" ? "Done" : "Something went wrong"}
            body={flash.msg}
          />
        </div>
      )}

      {isLoading && <SkeletonCard />}

      {data && (
        <div className="space-y-6">
          {/* Enable toggle */}
          <section className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-sm font-medium">Provisioning endpoint</h2>
                <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                  When on, your IdP can call <code className="rounded bg-zinc-100 px-1 py-0.5 text-xs dark:bg-zinc-900">/scim/v2/Users</code>{" "}
                  with a workspace scoped bearer. When off, every SCIM request returns 401 even if a
                  stale token is still on the row.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setEnabled(!data.enabled)}
                disabled={busy === "enabled"}
                className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none focus:ring-2 focus:ring-zinc-500 focus:ring-offset-2 disabled:opacity-50 ${
                  data.enabled ? "bg-emerald-600" : "bg-zinc-300 dark:bg-zinc-700"
                }`}
                aria-pressed={data.enabled}
                aria-label="Toggle SCIM provisioning"
              >
                <span
                  className={`pointer-events-none inline-block size-5 transform rounded-full bg-white shadow ring-0 transition ${
                    data.enabled ? "translate-x-5" : "translate-x-0"
                  }`}
                />
              </button>
            </div>
          </section>

          {/* Token */}
          <section className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
            <div className="flex items-center justify-between gap-3">
              <h2 className="flex items-center gap-2 text-sm font-medium">
                <Key weight="duotone" className="size-4" /> Bearer token
              </h2>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={revoke}
                  disabled={busy !== null || !data.has_token}
                  className="inline-flex items-center gap-1.5 rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-40 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800"
                >
                  <Trash weight="duotone" className="size-3.5" /> Revoke
                </button>
                <button
                  type="button"
                  onClick={rotate}
                  disabled={busy !== null}
                  className="inline-flex items-center gap-1.5 rounded-md bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-800 disabled:opacity-50 dark:bg-white dark:text-zinc-900 dark:hover:bg-zinc-200"
                >
                  <ArrowsClockwise weight="duotone" className="size-3.5" />
                  {data.has_token ? "Rotate" : "Generate"}
                </button>
              </div>
            </div>

            <dl className="mt-4 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-xs uppercase tracking-wide text-zinc-500">Status</dt>
                <dd className="mt-1">
                  {data.has_token ? (
                    <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                      <CheckCircle weight="duotone" className="size-4" /> Active
                    </span>
                  ) : (
                    <span className="text-zinc-500">No token</span>
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-zinc-500">Last four</dt>
                <dd className="mt-1 font-mono text-xs">
                  {data.token_last_four ? `…${data.token_last_four}` : "—"}
                </dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="flex items-center gap-1 text-xs uppercase tracking-wide text-zinc-500">
                  <Clock weight="duotone" className="size-3.5" /> Rotated
                </dt>
                <dd className="mt-1 text-zinc-700 dark:text-zinc-300">
                  {shortDate(data.token_rotated_at)}
                </dd>
              </div>
            </dl>

            {freshToken && (
              <div className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-700/60 dark:bg-amber-950/30">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-medium text-amber-900 dark:text-amber-200">
                    Copy this token now. It will not be shown again.
                  </p>
                  <button
                    type="button"
                    onClick={copyToken}
                    className="inline-flex items-center gap-1.5 rounded-md border border-amber-400 bg-white px-2 py-1 text-xs font-medium text-amber-900 hover:bg-amber-100 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200 dark:hover:bg-amber-900/40"
                  >
                    <Copy weight="duotone" className="size-3.5" /> Copy
                  </button>
                </div>
                <pre className="mt-2 overflow-x-auto rounded bg-zinc-900 px-3 py-2 font-mono text-[11px] text-zinc-100">
                  {freshToken}
                </pre>
              </div>
            )}
          </section>

          {/* Default role */}
          <section className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
            <h2 className="text-sm font-medium">Default role for SCIM-created users</h2>
            <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
              Workspace admin cannot be assigned from SCIM. Promote admins from the members page
              with MFA step up.
            </p>
            <div className="mt-3 space-y-2">
              {ROLE_OPTIONS.map((opt) => (
                <label
                  key={opt.value}
                  className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 text-sm transition ${
                    defaultRole === opt.value
                      ? "border-zinc-900 bg-zinc-50 dark:border-zinc-300 dark:bg-zinc-900"
                      : "border-zinc-200 hover:border-zinc-300 dark:border-zinc-800 dark:hover:border-zinc-700"
                  }`}
                >
                  <input
                    type="radio"
                    name="default-role"
                    value={opt.value}
                    checked={defaultRole === opt.value}
                    onChange={() => setDefaultRole(opt.value)}
                    className="mt-0.5 accent-zinc-900 dark:accent-zinc-200"
                  />
                  <div>
                    <div className="font-medium">{opt.label}</div>
                    <div className="text-xs text-zinc-500">{opt.help}</div>
                  </div>
                </label>
              ))}
            </div>
            <div className="mt-3 flex justify-end">
              <button
                type="button"
                onClick={saveDefaultRole}
                disabled={busy === "role" || defaultRole === data.default_role}
                className="inline-flex items-center gap-1.5 rounded-md bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-800 disabled:opacity-40 dark:bg-white dark:text-zinc-900 dark:hover:bg-zinc-200"
              >
                Save default role
              </button>
            </div>
          </section>

          {/* MFA helper */}
          <section className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
            <h2 className="text-sm font-medium">MFA step up</h2>
            <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
              Rotating the token, toggling SCIM, or changing the default role requires a fresh TOTP
              code if your session is older than the step up window.
            </p>
            <input
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="123456"
              value={mfa}
              onChange={(e) => setMfa(e.target.value.replace(/[^0-9]/g, "").slice(0, 6))}
              className="mt-3 w-32 rounded-md border border-zinc-300 bg-white px-3 py-1.5 font-mono text-sm tracking-widest focus:border-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
              aria-label="TOTP code"
            />
          </section>

          {/* How to wire it up */}
          <section className="rounded-xl border border-zinc-200 bg-white p-5 text-sm dark:border-zinc-800 dark:bg-zinc-950">
            <h2 className="text-sm font-medium">Wire it into your IdP</h2>
            <ul className="mt-2 space-y-1.5 text-zinc-600 dark:text-zinc-400">
              <li>
                <span className="text-zinc-500">Base URL</span>{" "}
                <code className="rounded bg-zinc-100 px-1 py-0.5 text-xs dark:bg-zinc-900">
                  https://your-host/scim/v2
                </code>
              </li>
              <li>
                <span className="text-zinc-500">Authentication</span> OAuth bearer token (the value
                shown once on rotate)
              </li>
              <li>
                <span className="text-zinc-500">Supported</span> Users, filter by{" "}
                <code className="rounded bg-zinc-100 px-1 py-0.5 text-xs dark:bg-zinc-900">
                  userName eq
                </code>
                , PUT, PATCH, DELETE
              </li>
              <li>
                <span className="text-zinc-500">Sanity check</span>{" "}
                <code className="rounded bg-zinc-100 px-1 py-0.5 text-xs dark:bg-zinc-900">
                  curl -H &quot;Authorization: Bearer …&quot; https://your-host/scim/v2/ServiceProviderConfig
                </code>
              </li>
            </ul>
          </section>
        </div>
      )}
    </main>
  );
}

function Banner({
  kind,
  icon,
  title,
  body,
}: {
  kind: "ok" | "err";
  icon: React.ReactNode;
  title: string;
  body: string;
}) {
  const cls =
    kind === "ok"
      ? "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-700/60 dark:bg-emerald-950/30 dark:text-emerald-200"
      : "border-rose-300 bg-rose-50 text-rose-900 dark:border-rose-700/60 dark:bg-rose-950/30 dark:text-rose-200";
  return (
    <div className={`flex items-start gap-2 rounded-lg border p-3 text-sm ${cls}`}>
      <span className="mt-0.5">{icon}</span>
      <div>
        <div className="font-medium">{title}</div>
        <div className="text-xs opacity-90">{body}</div>
      </div>
    </div>
  );
}

function SkeletonCard() {
  return (
    <div className="space-y-4">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-28 animate-pulse rounded-xl border border-zinc-200 bg-zinc-100/60 dark:border-zinc-800 dark:bg-zinc-900/40"
        />
      ))}
    </div>
  );
}
