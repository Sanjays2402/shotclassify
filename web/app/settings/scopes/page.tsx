"use client";

import useSWR from "swr";
import {
  Key,
  ShieldCheck,
  Eye,
  PencilSimple,
  Crown,
  Warning,
  Info,
  IdentificationCard,
  Clock,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type Scope = {
  id: string;
  title: string;
  description: string;
  mutating: boolean;
  roles: string[];
  unknown?: boolean;
};

type CatalogResponse = { version: number; scopes: Scope[] };

type Credential = {
  type: string;
  id?: string;
  label?: string;
  tenant_id?: string | null;
  created_at?: string | null;
  last_used_at?: string | null;
  expires_at?: string | null;
  revoked_at?: string | null;
};

type IntrospectResponse =
  | { active: false }
  | {
      active: true;
      principal: string;
      tenant_id: string | null;
      role: string | null;
      scopes: string[];
      scope_details: Scope[];
      credential: Credential;
      request_id?: string;
      checked_at: string;
    };

type ApiError = Error & { status?: number };

function fmt(ts?: string | null) {
  if (!ts) return "never";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function ScopeIcon({ mutating, unknown }: { mutating: boolean; unknown?: boolean }) {
  if (unknown) return <Warning weight="duotone" className="h-4 w-4 text-amber-500" />;
  if (mutating) return <PencilSimple weight="duotone" className="h-4 w-4 text-violet-500" />;
  return <Eye weight="duotone" className="h-4 w-4 text-emerald-500" />;
}

export default function ScopesPage() {
  const catalog = useSWR<CatalogResponse>("/api/scopes", fetcher, {
    revalidateOnFocus: false,
  });
  const introspect = useSWR<IntrospectResponse>("/api/auth/introspect", fetcher, {
    revalidateOnFocus: false,
  });

  const catError = catalog.error as ApiError | undefined;
  const introError = introspect.error as ApiError | undefined;

  const isUnauth = catError?.status === 401 || introError?.status === 401;

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-10 sm:px-6 lg:px-8">
      <header className="mb-8 flex items-start gap-3">
        <div className="rounded-xl bg-zinc-100 p-2.5 dark:bg-zinc-900">
          <ShieldCheck weight="duotone" className="h-6 w-6 text-zinc-700 dark:text-zinc-200" />
        </div>
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
            API scopes
          </h1>
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
            Every permission your API keys and sessions can hold, what each one grants, and what your current credential can do right now.
          </p>
        </div>
      </header>

      {isUnauth && (
        <div className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200">
          Sign in to see the scope catalog and your active credential.
        </div>
      )}

      <section className="mb-10">
        <h2 className="mb-3 flex items-center gap-2 text-sm font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
          <IdentificationCard weight="duotone" className="h-4 w-4" />
          Your credential
        </h2>
        {introspect.isLoading ? (
          <div className="h-28 animate-pulse rounded-xl border border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900/50" />
        ) : introspect.data && "active" in introspect.data && introspect.data.active ? (
          <div className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Principal" value={introspect.data.principal} />
              <Field label="Tenant" value={introspect.data.tenant_id ?? "unscoped"} />
              <Field
                label="Role"
                value={
                  <span className="inline-flex items-center gap-1.5">
                    {introspect.data.role === "admin" ? (
                      <Crown weight="duotone" className="h-4 w-4 text-amber-500" />
                    ) : null}
                    {introspect.data.role ?? "none"}
                  </span>
                }
              />
              <Field label="Credential type" value={introspect.data.credential.type} />
              {introspect.data.credential.label && (
                <Field label="Key label" value={introspect.data.credential.label} />
              )}
              {introspect.data.credential.id && (
                <Field label="Key id" mono value={introspect.data.credential.id} />
              )}
              {introspect.data.credential.last_used_at !== undefined && (
                <Field
                  label="Last used"
                  value={
                    <span className="inline-flex items-center gap-1.5">
                      <Clock weight="duotone" className="h-4 w-4 text-zinc-400" />
                      {fmt(introspect.data.credential.last_used_at)}
                    </span>
                  }
                />
              )}
              {introspect.data.credential.expires_at !== undefined && (
                <Field label="Expires" value={fmt(introspect.data.credential.expires_at)} />
              )}
            </div>
            <div className="mt-5 border-t border-zinc-100 pt-4 dark:border-zinc-900">
              <div className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                Active scopes
              </div>
              {introspect.data.scope_details.length === 0 ? (
                <p className="text-sm text-zinc-500 dark:text-zinc-400">
                  No scopes attached. This credential has the implicit role&apos;s defaults only.
                </p>
              ) : (
                <ul className="flex flex-wrap gap-2">
                  {introspect.data.scope_details.map((s) => (
                    <li
                      key={s.id}
                      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs ${
                        s.unknown
                          ? "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/40 dark:text-amber-200"
                          : "border-zinc-200 bg-zinc-50 text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200"
                      }`}
                    >
                      <ScopeIcon mutating={s.mutating} unknown={s.unknown} />
                      <span className="font-mono">{s.id}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-zinc-300 p-6 text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
            No active credential detected.
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-3 flex items-center gap-2 text-sm font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
          <Key weight="duotone" className="h-4 w-4" />
          Scope catalog
        </h2>
        {catalog.isLoading ? (
          <div className="space-y-2">
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-16 animate-pulse rounded-lg border border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900/50"
              />
            ))}
          </div>
        ) : catalog.data ? (
          <ul className="divide-y divide-zinc-100 overflow-hidden rounded-xl border border-zinc-200 bg-white dark:divide-zinc-900 dark:border-zinc-800 dark:bg-zinc-950">
            {catalog.data.scopes.map((s) => (
              <li key={s.id} className="flex flex-col gap-2 p-4 sm:flex-row sm:items-start sm:gap-4">
                <div className="flex shrink-0 items-center gap-2 sm:w-56">
                  <ScopeIcon mutating={s.mutating} />
                  <code className="rounded bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-800 dark:bg-zinc-900 dark:text-zinc-200">
                    {s.id}
                  </code>
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                    {s.title}
                  </div>
                  <p className="mt-0.5 text-sm text-zinc-600 dark:text-zinc-400">
                    {s.description}
                  </p>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
                    <span className="inline-flex items-center gap-1 rounded-full bg-zinc-100 px-2 py-0.5 dark:bg-zinc-900">
                      {s.mutating ? "mutating" : "read only"}
                    </span>
                    {s.roles.length > 0 ? (
                      <span className="inline-flex items-center gap-1">
                        <span className="text-zinc-400">included in</span>
                        {s.roles.map((r) => (
                          <span
                            key={r}
                            className="rounded-full border border-zinc-200 px-2 py-0.5 dark:border-zinc-800"
                          >
                            {r}
                          </span>
                        ))}
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-zinc-400">
                        <Info weight="duotone" className="h-3.5 w-3.5" />
                        service accounts only
                      </span>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            Catalog unavailable.
          </p>
        )}
      </section>
    </main>
  );
}

function Field({
  label,
  value,
  mono,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div>
      <div className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        {label}
      </div>
      <div
        className={`mt-1 text-sm text-zinc-900 dark:text-zinc-100 ${
          mono ? "font-mono" : ""
        }`}
      >
        {value}
      </div>
    </div>
  );
}
