"use client";

import { useState } from "react";
import useSWR from "swr";
import {
  ShieldCheck,
  ShieldWarning,
  Key,
  CheckCircle,
  Warning,
  ArrowsClockwise,
  Trash,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type Status = {
  enrolled: boolean;
  confirmed: boolean;
  created_at: string | null;
  confirmed_at: string | null;
  last_used_at: string | null;
  session_verified_at: string | null;
  principal: string;
};

type Enrollment = {
  secret: string;
  otpauth_uri: string;
  issuer: string;
  account: string;
};

function formatDate(s: string | null): string {
  if (!s) return "Never";
  try {
    return new Date(s).toLocaleString();
  } catch {
    return s;
  }
}

function QrFallback({ uri }: { uri: string }) {
  // Render a Google Charts QR. Loads only when the secret is shown.
  const src = `https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=${encodeURIComponent(uri)}`;
  return (
    <img
      src={src}
      alt="Scan with your authenticator app"
      width={180}
      height={180}
      className="rounded-md border border-white/10 bg-white p-1"
    />
  );
}

export default function MfaPage() {
  const { data, error, isLoading, mutate } = useSWR<Status>(
    "/api/mfa/status",
    fetcher,
    { revalidateOnFocus: false },
  );
  const [enrollment, setEnrollment] = useState<Enrollment | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; msg: string } | null>(
    null,
  );

  async function startEnroll() {
    setBusy(true);
    setFlash(null);
    try {
      const r = await fetch("/api/mfa/setup", { method: "POST" });
      const body = await r.json();
      if (!r.ok) throw new Error(body?.detail || `${r.status}`);
      setEnrollment(body);
    } catch (e) {
      setFlash({ kind: "err", msg: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function verifyEnrollment() {
    if (!code.trim()) return;
    setBusy(true);
    setFlash(null);
    try {
      const r = await fetch("/api/mfa/verify", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ code: code.trim() }),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body?.detail || `${r.status}`);
      setEnrollment(null);
      setCode("");
      setFlash({ kind: "ok", msg: "Second factor confirmed." });
      mutate();
    } catch (e) {
      setFlash({ kind: "err", msg: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function challenge() {
    if (!code.trim()) return;
    setBusy(true);
    setFlash(null);
    try {
      const r = await fetch("/api/mfa/challenge", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ code: code.trim() }),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body?.detail || `${r.status}`);
      setCode("");
      setFlash({ kind: "ok", msg: "Session step-up confirmed." });
      mutate();
    } catch (e) {
      setFlash({ kind: "err", msg: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function disable() {
    if (!code.trim()) {
      setFlash({
        kind: "err",
        msg: "Enter a current code to confirm removal.",
      });
      return;
    }
    if (!confirm("Remove the second factor for this account?")) return;
    setBusy(true);
    setFlash(null);
    try {
      const r = await fetch("/api/mfa/disable", {
        method: "DELETE",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ code: code.trim() }),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body?.detail || `${r.status}`);
      setCode("");
      setFlash({ kind: "ok", msg: "Second factor removed." });
      mutate();
    } catch (e) {
      setFlash({ kind: "err", msg: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6">
      <header className="mb-6 flex items-start gap-3">
        <div className="rounded-lg bg-white/5 p-2 ring-1 ring-white/10">
          <ShieldCheck size={28} weight="duotone" className="text-emerald-300" />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            Two-factor authentication
          </h1>
          <p className="mt-1 text-sm text-white/60">
            Required for destructive admin actions. Use any TOTP authenticator
            (1Password, Authy, Google Authenticator, Yubico Authenticator).
          </p>
        </div>
      </header>

      {flash && (
        <div
          role="status"
          className={`mb-4 flex items-center gap-2 rounded-md px-3 py-2 text-sm ring-1 ${
            flash.kind === "ok"
              ? "bg-emerald-500/10 text-emerald-200 ring-emerald-400/20"
              : "bg-rose-500/10 text-rose-200 ring-rose-400/20"
          }`}
        >
          {flash.kind === "ok" ? (
            <CheckCircle size={16} weight="duotone" />
          ) : (
            <Warning size={16} weight="duotone" />
          )}
          <span>{flash.msg}</span>
        </div>
      )}

      {isLoading && (
        <div className="space-y-3">
          <div className="h-20 animate-pulse rounded-lg bg-white/5" />
          <div className="h-32 animate-pulse rounded-lg bg-white/5" />
        </div>
      )}

      {error && !isLoading && (
        <div className="rounded-lg bg-rose-500/10 p-4 text-sm text-rose-200 ring-1 ring-rose-400/20">
          Could not load MFA status. Sign in and try again.
        </div>
      )}

      {data && (
        <div className="space-y-6">
          <section className="rounded-xl bg-white/5 p-5 ring-1 ring-white/10">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                {data.confirmed ? (
                  <ShieldCheck
                    size={24}
                    weight="duotone"
                    className="text-emerald-300"
                  />
                ) : (
                  <ShieldWarning
                    size={24}
                    weight="duotone"
                    className="text-amber-300"
                  />
                )}
                <div>
                  <div className="text-sm font-medium">
                    {data.confirmed
                      ? "Second factor active"
                      : "Second factor not enrolled"}
                  </div>
                  <div className="text-xs text-white/50">
                    Account {data.principal}
                  </div>
                </div>
              </div>
              <div className="text-right text-xs text-white/50">
                <div>Confirmed: {formatDate(data.confirmed_at)}</div>
                <div>Last used: {formatDate(data.last_used_at)}</div>
                <div>
                  Session verified: {formatDate(data.session_verified_at)}
                </div>
              </div>
            </div>
          </section>

          {!data.confirmed && !enrollment && (
            <section className="rounded-xl bg-white/5 p-5 ring-1 ring-white/10">
              <h2 className="text-sm font-semibold">Enroll an authenticator</h2>
              <p className="mt-1 text-sm text-white/60">
                Generates a TOTP secret, then asks for a current code to
                confirm.
              </p>
              <button
                type="button"
                onClick={startEnroll}
                disabled={busy}
                className="mt-3 inline-flex items-center gap-2 rounded-md bg-emerald-500/20 px-3 py-2 text-sm text-emerald-100 ring-1 ring-emerald-400/30 transition hover:bg-emerald-500/30 disabled:opacity-50"
              >
                <Key size={16} weight="duotone" /> Start enrollment
              </button>
            </section>
          )}

          {enrollment && (
            <section className="rounded-xl bg-white/5 p-5 ring-1 ring-white/10">
              <h2 className="text-sm font-semibold">Scan and confirm</h2>
              <div className="mt-4 flex flex-col gap-4 sm:flex-row sm:items-start">
                <QrFallback uri={enrollment.otpauth_uri} />
                <div className="flex-1 space-y-3 text-sm">
                  <div>
                    <div className="text-xs uppercase tracking-wide text-white/40">
                      Manual entry secret
                    </div>
                    <code className="mt-1 block break-all rounded bg-black/40 px-2 py-1 font-mono text-xs">
                      {enrollment.secret}
                    </code>
                  </div>
                  <div>
                    <label htmlFor="code-enroll" className="text-xs uppercase tracking-wide text-white/40">
                      Code from app
                    </label>
                    <input
                      id="code-enroll"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      maxLength={10}
                      value={code}
                      onChange={(e) => setCode(e.target.value.replace(/\s+/g, ""))}
                      className="mt-1 w-32 rounded-md bg-black/40 px-3 py-2 font-mono text-base tracking-widest ring-1 ring-white/10 focus:outline-none focus:ring-emerald-400/40"
                      placeholder="123456"
                    />
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={verifyEnrollment}
                      disabled={busy || code.length < 6}
                      className="inline-flex items-center gap-2 rounded-md bg-emerald-500/20 px-3 py-2 text-sm text-emerald-100 ring-1 ring-emerald-400/30 transition hover:bg-emerald-500/30 disabled:opacity-50"
                    >
                      <CheckCircle size={16} weight="duotone" /> Confirm
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setEnrollment(null);
                        setCode("");
                      }}
                      className="rounded-md px-3 py-2 text-sm text-white/60 hover:text-white"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              </div>
            </section>
          )}

          {data.confirmed && (
            <section className="rounded-xl bg-white/5 p-5 ring-1 ring-white/10">
              <h2 className="text-sm font-semibold">Step-up or remove</h2>
              <p className="mt-1 text-sm text-white/60">
                Re-enter a code to stamp this session for the next 15 minutes,
                or to confirm removal of the second factor.
              </p>
              <div className="mt-4 flex flex-wrap items-end gap-3">
                <div>
                  <label htmlFor="code-stepup" className="text-xs uppercase tracking-wide text-white/40">
                    Current code
                  </label>
                  <input
                    id="code-stepup"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={10}
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\s+/g, ""))}
                    className="mt-1 w-32 rounded-md bg-black/40 px-3 py-2 font-mono text-base tracking-widest ring-1 ring-white/10 focus:outline-none focus:ring-emerald-400/40"
                    placeholder="123456"
                  />
                </div>
                <button
                  type="button"
                  onClick={challenge}
                  disabled={busy || code.length < 6}
                  className="inline-flex items-center gap-2 rounded-md bg-white/10 px-3 py-2 text-sm ring-1 ring-white/15 transition hover:bg-white/15 disabled:opacity-50"
                >
                  <ArrowsClockwise size={16} weight="duotone" /> Step up session
                </button>
                <button
                  type="button"
                  onClick={disable}
                  disabled={busy || code.length < 6}
                  className="inline-flex items-center gap-2 rounded-md bg-rose-500/15 px-3 py-2 text-sm text-rose-100 ring-1 ring-rose-400/30 transition hover:bg-rose-500/25 disabled:opacity-50"
                >
                  <Trash size={16} weight="duotone" /> Remove second factor
                </button>
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
