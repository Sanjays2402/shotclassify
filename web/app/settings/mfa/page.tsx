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
  Lifebuoy,
  DownloadSimple,
  CopySimple,
  LockKey,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type RecoveryCodes = {
  total: number;
  remaining: number;
  generated_at: string | null;
  last_used_at: string | null;
};

type Status = {
  enrolled: boolean;
  confirmed: boolean;
  created_at: string | null;
  confirmed_at: string | null;
  last_used_at: string | null;
  session_verified_at: string | null;
  principal: string;
  recovery_codes?: RecoveryCodes;
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
  const [issuedCodes, setIssuedCodes] = useState<string[] | null>(null);
  const [recoveryCode, setRecoveryCode] = useState("");
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

  async function regenerateRecovery() {
    if (
      !confirm(
        "Generate a new set of 10 recovery codes? The previous codes will stop working.",
      )
    )
      return;
    setBusy(true);
    setFlash(null);
    try {
      const r = await fetch("/api/mfa/recovery-codes", { method: "POST" });
      const body = await r.json();
      if (!r.ok) throw new Error(body?.detail || `${r.status}`);
      setIssuedCodes(body.codes as string[]);
      setFlash({
        kind: "ok",
        msg: "Recovery codes generated. Save them now; they will not be shown again.",
      });
      mutate();
    } catch (e) {
      setFlash({ kind: "err", msg: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function redeemRecovery() {
    if (!recoveryCode.trim()) return;
    setBusy(true);
    setFlash(null);
    try {
      const r = await fetch("/api/mfa/recovery", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ code: recoveryCode.trim() }),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body?.detail || `${r.status}`);
      setRecoveryCode("");
      setFlash({
        kind: "ok",
        msg: `Recovery code accepted. ${body.remaining} remaining. Rotate from a secure device when you can.`,
      });
      mutate();
    } catch (e) {
      setFlash({ kind: "err", msg: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function copyCodes() {
    if (!issuedCodes) return;
    try {
      await navigator.clipboard.writeText(issuedCodes.join("\n"));
      setFlash({ kind: "ok", msg: "Recovery codes copied to clipboard." });
    } catch {
      setFlash({ kind: "err", msg: "Clipboard unavailable; copy them manually." });
    }
  }

  function downloadCodes() {
    if (!issuedCodes) return;
    const stamp = new Date().toISOString().slice(0, 10);
    const header = `# ShotClassify recovery codes\n# Account: ${data?.principal ?? ""}\n# Generated: ${new Date().toISOString()}\n# Each code works exactly once.\n\n`;
    const blob = new Blob([header + issuedCodes.join("\n") + "\n"], {
      type: "text/plain;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `shotclassify-recovery-${stamp}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
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

          {data.confirmed && (
            <section
              aria-labelledby="recovery-heading"
              className="rounded-xl bg-white/5 p-5 ring-1 ring-white/10"
            >
              <div className="flex items-start gap-3">
                <div className="rounded-md bg-amber-500/10 p-2 ring-1 ring-amber-400/20">
                  <Lifebuoy
                    size={20}
                    weight="duotone"
                    className="text-amber-300"
                  />
                </div>
                <div className="flex-1">
                  <h2 id="recovery-heading" className="text-sm font-semibold">
                    Recovery codes
                  </h2>
                  <p className="mt-1 text-sm text-white/60">
                    Single-use backup codes that satisfy step-up when your
                    authenticator app is unavailable. Store them somewhere
                    your password manager can reach from another device.
                  </p>
                  <dl className="mt-3 grid grid-cols-2 gap-3 text-xs text-white/60 sm:grid-cols-4">
                    <div>
                      <dt className="uppercase tracking-wide text-white/40">
                        Active
                      </dt>
                      <dd className="mt-0.5 font-mono text-sm text-white">
                        {data.recovery_codes?.remaining ?? 0}
                      </dd>
                    </div>
                    <div>
                      <dt className="uppercase tracking-wide text-white/40">
                        Issued
                      </dt>
                      <dd className="mt-0.5 font-mono text-sm text-white">
                        {data.recovery_codes?.total ?? 0}
                      </dd>
                    </div>
                    <div>
                      <dt className="uppercase tracking-wide text-white/40">
                        Generated
                      </dt>
                      <dd className="mt-0.5 text-sm">
                        {formatDate(
                          data.recovery_codes?.generated_at ?? null,
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt className="uppercase tracking-wide text-white/40">
                        Last used
                      </dt>
                      <dd className="mt-0.5 text-sm">
                        {formatDate(
                          data.recovery_codes?.last_used_at ?? null,
                        )}
                      </dd>
                    </div>
                  </dl>

                  {(data.recovery_codes?.remaining ?? 0) > 0 &&
                    (data.recovery_codes?.remaining ?? 0) <= 2 &&
                    !issuedCodes && (
                      <p
                        role="alert"
                        className="mt-3 flex items-center gap-2 rounded-md bg-amber-500/10 px-3 py-2 text-xs text-amber-200 ring-1 ring-amber-400/20"
                      >
                        <Warning size={14} weight="duotone" />
                        Only {data.recovery_codes?.remaining} recovery code
                        {(data.recovery_codes?.remaining ?? 0) === 1
                          ? ""
                          : "s"}{" "}
                        left. Regenerate a fresh batch soon.
                      </p>
                    )}

                  {!issuedCodes && (
                    <div className="mt-4 flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        onClick={regenerateRecovery}
                        disabled={busy || !data.session_verified_at}
                        title={
                          data.session_verified_at
                            ? ""
                            : "Step up your session above first."
                        }
                        className="inline-flex items-center gap-2 rounded-md bg-amber-500/15 px-3 py-2 text-sm text-amber-100 ring-1 ring-amber-400/30 transition hover:bg-amber-500/25 disabled:opacity-50"
                      >
                        <ArrowsClockwise size={16} weight="duotone" />
                        {data.recovery_codes?.total
                          ? "Regenerate recovery codes"
                          : "Generate recovery codes"}
                      </button>
                      {!data.session_verified_at && (
                        <span className="text-xs text-white/50">
                          Step up your session first to confirm intent.
                        </span>
                      )}
                    </div>
                  )}

                  {issuedCodes && (
                    <div className="mt-4 rounded-lg bg-black/40 p-4 ring-1 ring-amber-400/30">
                      <div className="flex items-center gap-2 text-xs text-amber-200">
                        <LockKey size={14} weight="duotone" />
                        Shown once. Copy or download before leaving this page.
                      </div>
                      <ul className="mt-3 grid grid-cols-1 gap-2 font-mono text-sm text-white sm:grid-cols-2">
                        {issuedCodes.map((c) => (
                          <li
                            key={c}
                            className="rounded bg-white/5 px-2 py-1 tracking-widest ring-1 ring-white/10"
                          >
                            {c}
                          </li>
                        ))}
                      </ul>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={copyCodes}
                          className="inline-flex items-center gap-2 rounded-md bg-white/10 px-3 py-2 text-sm ring-1 ring-white/15 transition hover:bg-white/15"
                        >
                          <CopySimple size={16} weight="duotone" /> Copy all
                        </button>
                        <button
                          type="button"
                          onClick={downloadCodes}
                          className="inline-flex items-center gap-2 rounded-md bg-white/10 px-3 py-2 text-sm ring-1 ring-white/15 transition hover:bg-white/15"
                        >
                          <DownloadSimple size={16} weight="duotone" /> Download .txt
                        </button>
                        <button
                          type="button"
                          onClick={() => setIssuedCodes(null)}
                          className="rounded-md px-3 py-2 text-sm text-white/60 hover:text-white"
                        >
                          I have saved them
                        </button>
                      </div>
                    </div>
                  )}

                  <div className="mt-5 border-t border-white/10 pt-4">
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-white/40">
                      Use a recovery code
                    </h3>
                    <p className="mt-1 text-xs text-white/50">
                      Step up this session if your authenticator is
                      unavailable. Each code works once.
                    </p>
                    <div className="mt-2 flex flex-wrap items-end gap-2">
                      <label htmlFor="recovery-input" className="sr-only">
                        Recovery code
                      </label>
                      <input
                        id="recovery-input"
                        autoComplete="off"
                        spellCheck={false}
                        maxLength={32}
                        value={recoveryCode}
                        onChange={(e) => setRecoveryCode(e.target.value)}
                        placeholder="abcd-efgh"
                        className="w-44 rounded-md bg-black/40 px-3 py-2 font-mono text-sm tracking-widest ring-1 ring-white/10 focus:outline-none focus:ring-amber-400/40"
                      />
                      <button
                        type="button"
                        onClick={redeemRecovery}
                        disabled={busy || recoveryCode.trim().length < 4}
                        className="inline-flex items-center gap-2 rounded-md bg-amber-500/15 px-3 py-2 text-sm text-amber-100 ring-1 ring-amber-400/30 transition hover:bg-amber-500/25 disabled:opacity-50"
                      >
                        <Lifebuoy size={16} weight="duotone" /> Redeem code
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
