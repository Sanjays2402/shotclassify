"use client";

import { useState } from "react";
import useSWR from "swr";
import {
  UserCircle,
  SignIn,
  SignOut,
  Download,
  Trash,
  Database,
  ShieldCheck,
  Warning,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";
import { QuotaMeter } from "@/components/QuotaMeter";

type Me = {
  principal: string;
  tenant_id: string | null;
  exported_at: string;
  counts: { classifications: number; audit_log: number };
};

const API_BASE =
  process.env.NEXT_PUBLIC_SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";

export default function AccountPage() {
  const { data, error, isLoading, mutate } = useSWR<Me>(
    "/api/me",
    fetcher,
    { revalidateOnFocus: false },
  );

  const [confirmText, setConfirmText] = useState("");
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<{
    kind: "ok" | "err";
    msg: string;
  } | null>(null);

  const unauth =
    error && (error as Error & { status?: number }).status === 401;

  const onDelete = async () => {
    if (confirmText !== "erase") return;
    setBusy(true);
    setFlash(null);
    try {
      const res = await fetch("/api/me?confirm=erase", { method: "DELETE" });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || `${res.status} ${res.statusText}`);
      }
      const body = (await res.json()) as {
        deleted?: { classifications: number; audit_log: number };
      };
      const c = body.deleted?.classifications ?? 0;
      const a = body.deleted?.audit_log ?? 0;
      setFlash({
        kind: "ok",
        msg: `Erased ${c} classifications and ${a} audit rows.`,
      });
      setConfirmText("");
      mutate();
    } catch (e) {
      setFlash({
        kind: "err",
        msg: e instanceof Error ? e.message : "Delete failed.",
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-6 max-w-3xl">
      <header>
        <div className="eyebrow">Locker room</div>
        <h1 className="h-display text-[34px]">ACCOUNT</h1>
        <p className="text-[13px] opacity-70 mt-1">
          Your principal, what we store under it, and how to get it back or
          delete it.
        </p>
      </header>

      {/* Quota meter */}
      <QuotaMeter />

      {/* Identity panel */}
      <section className="panel p-5 flex flex-col gap-4">
        <div className="flex items-start gap-3">
          <UserCircle size={32} weight="duotone" className="opacity-80" />
          <div className="flex-1 min-w-0">
            <div className="eyebrow">Signed in as</div>
            {isLoading ? (
              <div
                className="h-5 w-40 rounded-sm mt-1 animate-pulse"
                style={{ background: "var(--color-rule)" }}
                aria-label="Loading principal"
              />
            ) : unauth ? (
              <div className="text-[15px] mt-0.5">Not signed in</div>
            ) : error ? (
              <div className="text-[15px] mt-0.5 text-red-700">
                Could not reach the API.
              </div>
            ) : (
              <>
                <div className="text-[16px] mt-0.5 font-medium num">
                  {data?.principal}
                </div>
                {data?.tenant_id && (
                  <div className="text-[12px] opacity-70 num mt-0.5">
                    tenant: {data.tenant_id}
                  </div>
                )}
              </>
            )}
          </div>
          <div className="flex items-center gap-2">
            {unauth ? (
              <a
                className="btn btn-primary"
                href={`${API_BASE}/auth/login`}
                rel="noopener"
              >
                <SignIn size={14} weight="duotone" /> Sign in with GitHub
              </a>
            ) : (
              <form action={`${API_BASE}/auth/logout`} method="post">
                <button className="btn btn-ghost" type="submit">
                  <SignOut size={14} weight="duotone" /> Sign out
                </button>
              </form>
            )}
          </div>
        </div>

        {!unauth && !error && (
          <div className="grid grid-cols-2 gap-3 pt-3 border-t" style={{ borderColor: "var(--color-rule)" }}>
            <Stat
              icon={<Database size={16} weight="duotone" />}
              label="Classifications"
              value={isLoading ? null : data?.counts.classifications ?? 0}
            />
            <Stat
              icon={<ShieldCheck size={16} weight="duotone" />}
              label="Audit entries"
              value={isLoading ? null : data?.counts.audit_log ?? 0}
            />
          </div>
        )}
      </section>

      {/* Export */}
      <section className="panel p-5 flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <Download size={18} weight="duotone" />
          <h2 className="h-display text-[18px]">EXPORT MY DATA</h2>
        </div>
        <p className="text-[13px] opacity-75">
          Download every classification and audit row stored under your
          principal as a single JSON file. Includes OCR text, route decisions,
          and full extracted blobs.
        </p>
        <div>
          <a
            className="btn btn-primary"
            href="/api/me/export"
            aria-disabled={!!unauth}
            onClick={(e) => {
              if (unauth) e.preventDefault();
            }}
          >
            <Download size={14} weight="duotone" /> Download JSON
          </a>
        </div>
      </section>

      {/* Danger zone */}
      <section
        className="panel p-5 flex flex-col gap-3"
        style={{ borderColor: "rgba(190, 30, 30, 0.45)" }}
      >
        <div className="flex items-center gap-2">
          <Warning size={18} weight="duotone" color="rgb(176, 30, 30)" />
          <h2 className="h-display text-[18px]" style={{ color: "rgb(176, 30, 30)" }}>
            DANGER ZONE
          </h2>
        </div>
        <p className="text-[13px] opacity-80">
          Permanently delete every classification and audit row stored under
          your principal. The stored screenshot blobs are unlinked too. This
          cannot be undone. Type{" "}
          <span className="num font-semibold">erase</span> to confirm.
        </p>
        <div className="flex items-center gap-2 flex-wrap">
          <input
            className="text-[13px] px-3 py-1.5 rounded-sm border bg-white"
            style={{ borderColor: "var(--color-rule)", minWidth: 180 }}
            placeholder="Type erase"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            aria-label="Type erase to confirm deletion"
            disabled={busy || !!unauth}
          />
          <button
            className="btn"
            style={{
              background: "rgb(176, 30, 30)",
              color: "white",
              borderColor: "rgb(120, 20, 20)",
              opacity: confirmText === "erase" && !busy && !unauth ? 1 : 0.5,
              cursor:
                confirmText === "erase" && !busy && !unauth
                  ? "pointer"
                  : "not-allowed",
            }}
            disabled={confirmText !== "erase" || busy || !!unauth}
            onClick={onDelete}
          >
            <Trash size={14} weight="duotone" />{" "}
            {busy ? "Erasing…" : "Erase everything"}
          </button>
        </div>
        {flash && (
          <div
            role="status"
            className="text-[13px] mt-1"
            style={{
              color: flash.kind === "ok" ? "rgb(20, 110, 60)" : "rgb(176, 30, 30)",
            }}
          >
            {flash.msg}
          </div>
        )}
      </section>
    </div>
  );
}

function Stat({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: number | null;
}) {
  return (
    <div className="flex items-center gap-3">
      <div className="opacity-80">{icon}</div>
      <div className="flex-1">
        <div className="eyebrow">{label}</div>
        {value === null ? (
          <div
            className="h-5 w-16 rounded-sm mt-1 animate-pulse"
            style={{ background: "var(--color-rule)" }}
            aria-label={`Loading ${label}`}
          />
        ) : (
          <div className="num text-[20px] font-semibold">
            {value.toLocaleString()}
          </div>
        )}
      </div>
    </div>
  );
}
