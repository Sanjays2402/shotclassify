"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  GithubLogo,
  SignIn,
  CheckCircle,
  Warning,
  Key,
  ShieldCheck,
} from "@phosphor-icons/react/dist/ssr";

type Who = { principal: string | null; error?: string };

const API_BASE =
  process.env.NEXT_PUBLIC_SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";

export default function SignInPage() {
  const [who, setWho] = useState<Who | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/auth/whoami", { credentials: "include" })
      .then(async (r) => {
        const j = (await r.json()) as Who;
        if (!cancelled) {
          setWho(j);
          if (j.error) setError("Backend unreachable. Start the API on :7441.");
        }
      })
      .catch(() => {
        if (!cancelled) setError("Network error while checking session.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function signOut() {
    setLoading(true);
    await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
    setWho({ principal: null });
    setLoading(false);
  }

  const loginHref = `${API_BASE}/auth/login`;
  const signedIn = !!who?.principal;

  return (
    <div className="max-w-xl mx-auto py-8">
      <div className="mb-6">
        <div className="eyebrow mb-2">Account</div>
        <h1 className="h-display text-[28px] tracking-tight">Sign in</h1>
        <p className="text-[13px] mt-2 opacity-70">
          Sign in to save your shots, view history across devices, manage API
          keys and webhooks, and track your usage quota.
        </p>
      </div>

      <div
        className="border rounded-lg p-5"
        style={{
          borderColor: "var(--color-rule)",
          background: "var(--color-chalk)",
        }}
      >
        {loading ? (
          <SkeletonCard />
        ) : signedIn ? (
          <SignedInCard principal={who!.principal!} onSignOut={signOut} />
        ) : (
          <SignedOutCard loginHref={loginHref} error={error} />
        )}
      </div>

      <div className="mt-6 grid gap-3 text-[12px] opacity-80">
        <Row icon={<Key size={16} weight="duotone" />} label="Use an API key">
          Prefer headless? Generate a key on{" "}
          <Link className="underline" href="/keys">
            /keys
          </Link>{" "}
          and pass it as <code className="kbd">X-API-Key</code>.
        </Row>
        <Row
          icon={<ShieldCheck size={16} weight="duotone" />}
          label="Sessions persist"
        >
          Sign-in sets an <code className="kbd">sc_session</code> cookie valid
          for 30 days. Sign out from this page to revoke it on this device.
        </Row>
      </div>
    </div>
  );
}

function SignedOutCard({
  loginHref,
  error,
}: {
  loginHref: string;
  error: string | null;
}) {
  const [ssoEnabled, setSsoEnabled] = useState(false);
  const [email, setEmail] = useState("");
  useEffect(() => {
    fetch("/api/sso-config")
      .then((r) => r.json())
      .then((j) => setSsoEnabled(!!j?.enabled))
      .catch(() => setSsoEnabled(false));
  }, []);
  const ssoHref = email.trim()
    ? `${API_BASE}/auth/sso/login?email=${encodeURIComponent(email.trim())}`
    : `${API_BASE}/auth/sso/login`;
  return (
    <div className="flex flex-col gap-4">
      <p className="text-[14px]">You are not signed in.</p>
      {ssoEnabled ? (
        <div className="flex flex-col gap-2 rounded-md border p-3" style={{ borderColor: "var(--color-rule)" }}>
          <label htmlFor="sso-email" className="text-[12px] font-medium">
            Work email (optional)
          </label>
          <input
            id="sso-email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@acme.com"
            className="rounded-md border px-3 py-2 text-[13px] outline-none focus:ring-2 focus:ring-emerald-500/20"
            style={{ borderColor: "var(--color-rule)" }}
          />
          <a
            href={ssoHref}
            className="inline-flex items-center justify-center gap-2 rounded-md px-4 py-2.5 text-[14px] font-medium border"
            style={{ background: "var(--color-felt)", color: "white" }}
          >
            <ShieldCheck size={18} weight="duotone" />
            Continue with SSO
          </a>
          <p className="text-[11px] opacity-60">
            Routes you to your workspace identity provider (Google Workspace,
            Okta, Azure AD). If your workspace requires SSO, sign in here.
          </p>
        </div>
      ) : null}
      <a
        href={loginHref}
        className="inline-flex items-center justify-center gap-2 rounded-md px-4 py-2.5 text-[14px] font-medium border transition-colors"
        style={{
          background: ssoEnabled ? "transparent" : "var(--color-felt)",
          color: ssoEnabled ? "inherit" : "white",
          borderColor: "var(--color-felt-rail, var(--color-felt))",
        }}
      >
        <GithubLogo size={18} weight="duotone" />
        Continue with GitHub
      </a>
      {error ? (
        <div className="flex items-start gap-2 text-[12px] text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">
          <Warning size={14} weight="duotone" className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      ) : null}
      <p className="text-[11px] opacity-60">
        If OAuth is not configured on the server you will see an
        &ldquo;OAuth not configured&rdquo; notice. Set{" "}
        <code className="kbd">AUTH_OAUTH_CLIENT_ID</code> /{" "}
        <code className="kbd">AUTH_OAUTH_CLIENT_SECRET</code> on the API and
        retry.
      </p>
    </div>
  );
}

function SignedInCard({
  principal,
  onSignOut,
}: {
  principal: string;
  onSignOut: () => void;
}) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <div
          aria-hidden
          className="w-10 h-10 rounded-full flex items-center justify-center text-[14px] font-semibold"
          style={{ background: "var(--color-felt)", color: "white" }}
        >
          {principal.slice(0, 2).toUpperCase()}
        </div>
        <div>
          <div className="text-[14px] font-medium flex items-center gap-1.5">
            {principal}
            <CheckCircle
              size={14}
              weight="duotone"
              className="text-emerald-600"
            />
          </div>
          <div className="text-[11px] opacity-60">Signed in via GitHub</div>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Link
          href="/shots"
          className="text-[13px] underline underline-offset-2"
        >
          Your shots
        </Link>
        <span className="opacity-40">·</span>
        <Link href="/usage" className="text-[13px] underline underline-offset-2">
          Usage
        </Link>
        <span className="opacity-40">·</span>
        <Link
          href="/account"
          className="text-[13px] underline underline-offset-2"
        >
          Account
        </Link>
      </div>
      <button
        onClick={onSignOut}
        className="inline-flex items-center gap-2 self-start rounded-md px-3 py-2 text-[13px] font-medium border bg-white hover:bg-gray-50 transition-colors"
        style={{ borderColor: "var(--color-rule)" }}
      >
        <SignIn size={16} weight="duotone" className="rotate-180" />
        Sign out
      </button>
    </div>
  );
}

function SkeletonCard() {
  return (
    <div className="animate-pulse flex flex-col gap-3" aria-busy="true">
      <div className="h-4 w-32 bg-gray-200 rounded" />
      <div className="h-10 w-48 bg-gray-200 rounded" />
      <div className="h-3 w-64 bg-gray-200 rounded" />
    </div>
  );
}

function Row({
  icon,
  label,
  children,
}: {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-2">
      <span className="mt-0.5 shrink-0">{icon}</span>
      <div>
        <span className="font-medium">{label}.</span> {children}
      </div>
    </div>
  );
}
