"use client";

// Per-tenant webhook auto-disable threshold (circuit breaker). When the
// number of consecutive failed deliveries on a single subscription reaches
// the configured threshold, the dispatcher pauses the subscription. The
// signing secret and delivery history survive so an operator can resume
// once the downstream receiver is healthy again.

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import {
  ShieldCheck,
  CircleNotch,
  Warning,
  CheckCircle,
  Lock,
  Lightning,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type Policy = {
  tenant_id: string;
  threshold: number | null;
  min_threshold: number;
  max_threshold: number;
};

type ApiError = Error & { status?: number };

export default function WebhookAutoDisablePage() {
  const { data, error, isLoading, mutate } = useSWR<Policy>(
    "/api/settings/security/webhook-autodisable",
    fetcher,
    { revalidateOnFocus: false },
  );

  const [enabled, setEnabled] = useState(false);
  const [value, setValue] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<
    { kind: "ok" | "err"; msg: string } | null
  >(null);

  useEffect(() => {
    if (!data) return;
    if (data.threshold === null) {
      setEnabled(false);
      setValue("");
    } else {
      setEnabled(true);
      setValue(String(data.threshold));
    }
  }, [data?.threshold]);

  const status = error as ApiError | undefined;
  const unauth = status?.status === 401;
  const forbidden = status?.status === 403;

  const min = data?.min_threshold ?? 2;
  const max = data?.max_threshold ?? 10000;

  const parsed = useMemo(() => {
    if (!enabled) return null;
    const n = Number(value);
    if (!Number.isInteger(n)) return NaN;
    return n;
  }, [enabled, value]);

  const inputInvalid =
    enabled &&
    (Number.isNaN(parsed) ||
      (typeof parsed === "number" &&
        (parsed < min || parsed > max)));

  const dirty = useMemo(() => {
    if (!data) return false;
    if (!enabled) return data.threshold !== null;
    if (typeof parsed !== "number" || Number.isNaN(parsed)) return false;
    return parsed !== data.threshold;
  }, [data?.threshold, enabled, parsed]);

  async function save() {
    if (inputInvalid) return;
    setBusy(true);
    setFlash(null);
    try {
      const body = enabled
        ? { threshold: parsed }
        : { threshold: null };
      const res = await fetch("/api/settings/security/webhook-autodisable", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          payload.detail ?? payload.error ?? `HTTP ${res.status}`,
        );
      }
      await mutate();
      setFlash({
        kind: "ok",
        msg: enabled
          ? "Circuit breaker saved. Subscriptions will pause after the configured number of consecutive failures."
          : "Circuit breaker cleared. Failing subscriptions will keep retrying.",
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setFlash({ kind: "err", msg });
    } finally {
      setBusy(false);
    }
  }

  function revert() {
    if (!data) return;
    if (data.threshold === null) {
      setEnabled(false);
      setValue("");
    } else {
      setEnabled(true);
      setValue(String(data.threshold));
    }
    setFlash(null);
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-8 sm:py-10">
      <header className="mb-6 flex items-start gap-3">
        <ShieldCheck size={28} weight="duotone" className="mt-1 shrink-0" />
        <div>
          <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
            Webhook circuit breaker
          </h1>
          <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            Pause a webhook subscription automatically after this many
            consecutive failed deliveries. Pausing preserves the signing
            secret and the delivery history so you can resume the
            subscription once the receiver is healthy. A successful delivery
            resets the counter.
          </p>
        </div>
      </header>

      {unauth && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          <div className="flex items-center gap-2">
            <Lock size={16} weight="duotone" />
            <span>Sign in to manage security settings.</span>
          </div>
        </div>
      )}

      {forbidden && (
        <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          <div className="flex items-center gap-2">
            <Warning size={16} weight="duotone" />
            <span>
              You need the admin role to view or change the webhook circuit
              breaker.
            </span>
          </div>
        </div>
      )}

      {!unauth && !forbidden && (
        <section className="rounded-xl border border-neutral-200 bg-white p-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-950 sm:p-6">
          {isLoading && !data ? (
            <div className="space-y-3" aria-busy="true" aria-live="polite">
              <div className="h-10 w-full animate-pulse rounded-md bg-neutral-200 dark:bg-neutral-800" />
              <div className="h-10 w-2/3 animate-pulse rounded-md bg-neutral-200 dark:bg-neutral-800" />
            </div>
          ) : status && !unauth && !forbidden ? (
            <div className="flex items-center gap-2 text-sm text-red-700 dark:text-red-300">
              <Warning size={16} weight="duotone" />
              <span>Could not load policy: {status.message}</span>
            </div>
          ) : (
            <div className="space-y-5">
              <label className="flex items-start gap-3 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
                <input
                  type="checkbox"
                  className="mt-1 size-4 cursor-pointer accent-neutral-900 dark:accent-neutral-100"
                  checked={enabled}
                  onChange={(e) => {
                    setEnabled(e.target.checked);
                    if (e.target.checked && !value) setValue("5");
                  }}
                  aria-label="Enable webhook circuit breaker"
                />
                <div className="flex-1">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <Lightning size={16} weight="duotone" />
                    Enable circuit breaker
                  </div>
                  <p className="mt-1 text-xs text-neutral-600 dark:text-neutral-400">
                    When off, failing subscriptions keep retrying with
                    exponential backoff and only stop when an operator
                    pauses or revokes them by hand.
                  </p>
                </div>
              </label>

              <div className="space-y-2">
                <label
                  className="block text-sm font-medium"
                  htmlFor="threshold"
                >
                  Consecutive failures before pausing
                </label>
                <input
                  id="threshold"
                  type="number"
                  inputMode="numeric"
                  min={min}
                  max={max}
                  step={1}
                  disabled={!enabled}
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  className="block w-full max-w-xs rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm tabular-nums shadow-sm outline-none focus:border-neutral-500 disabled:opacity-50 dark:border-neutral-700 dark:bg-neutral-900"
                  aria-invalid={inputInvalid || undefined}
                  aria-describedby="threshold-help"
                />
                <p
                  id="threshold-help"
                  className="text-xs text-neutral-500 dark:text-neutral-400"
                >
                  Between {min.toLocaleString()} and {max.toLocaleString()}.
                  A typical value is 5 to 20: low enough to protect a flaky
                  receiver, high enough to ride out a brief outage.
                </p>
                {inputInvalid && (
                  <p
                    className="flex items-center gap-1 text-xs text-red-700 dark:text-red-300"
                    role="alert"
                  >
                    <Warning size={14} weight="duotone" />
                    Enter a whole number between {min} and {max}.
                  </p>
                )}
              </div>

              {flash && (
                <div
                  role="status"
                  className={
                    flash.kind === "ok"
                      ? "flex items-start gap-2 rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200"
                      : "flex items-start gap-2 rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
                  }
                >
                  {flash.kind === "ok" ? (
                    <CheckCircle
                      size={16}
                      weight="duotone"
                      className="mt-0.5 shrink-0"
                    />
                  ) : (
                    <Warning
                      size={16}
                      weight="duotone"
                      className="mt-0.5 shrink-0"
                    />
                  )}
                  <span>{flash.msg}</span>
                </div>
              )}

              <div className="flex flex-wrap items-center gap-2 pt-2">
                <button
                  type="button"
                  onClick={save}
                  disabled={busy || !dirty || inputInvalid}
                  className="inline-flex items-center gap-2 rounded-md bg-neutral-900 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-white"
                >
                  {busy ? (
                    <CircleNotch size={14} weight="duotone" className="animate-spin" />
                  ) : (
                    <ShieldCheck size={14} weight="duotone" />
                  )}
                  Save policy
                </button>
                <button
                  type="button"
                  onClick={revert}
                  disabled={busy || !dirty}
                  className="inline-flex items-center gap-2 rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm font-medium text-neutral-800 hover:bg-neutral-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-200 dark:hover:bg-neutral-800"
                >
                  Revert
                </button>
                <span className="ml-auto text-xs text-neutral-500 dark:text-neutral-400">
                  Current:{" "}
                  {data?.threshold === null
                    ? "no policy"
                    : `pause after ${data?.threshold} consecutive failures`}
                </span>
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
