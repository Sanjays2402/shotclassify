"use client";

import { useState } from "react";
import {
  Database,
  DownloadSimple,
  FileZip,
  Shield,
  Trash,
  Warning,
  CheckCircle,
  Lock,
  Eye,
} from "@phosphor-icons/react/dist/ssr";

type DryRunResult = {
  dry_run: true;
  tenant_id: string;
  would_delete: {
    classifications: number;
    audit_log: number;
    saved_views: number;
  };
  preserved: string[];
};

type DeleteResult = {
  tenant_id: string;
  deleted: { classifications: number; audit_log: number; saved_views: number };
  preserved: string[];
};

type Flash = { kind: "ok" | "err"; msg: string };

function readMfaOtp(): string | null {
  if (typeof window === "undefined") return null;
  const otp = window.prompt(
    "Enter your 6 digit MFA code to authorize this action.",
  );
  if (!otp) return null;
  const cleaned = otp.trim();
  if (!/^\d{6}$/.test(cleaned)) {
    window.alert("MFA code must be 6 digits.");
    return null;
  }
  return cleaned;
}

export default function WorkspaceDataPage() {
  const [busy, setBusy] = useState<"export" | "dry" | "erase" | null>(null);
  const [flash, setFlash] = useState<Flash | null>(null);
  const [preview, setPreview] = useState<DryRunResult | null>(null);
  const [result, setResult] = useState<DeleteResult | null>(null);
  const [confirmText, setConfirmText] = useState("");

  const runExport = async () => {
    setBusy("export");
    setFlash(null);
    try {
      const otp = readMfaOtp();
      const headers: Record<string, string> = {};
      if (otp) headers["x-mfa-otp"] = otp;
      const r = await fetch("/api/workspace/data", {
        method: "GET",
        headers,
        credentials: "same-origin",
      });
      if (!r.ok) {
        const text = await r.text().catch(() => "");
        throw Object.assign(new Error(text || `${r.status}`), {
          status: r.status,
        });
      }
      const blob = await r.blob();
      const disposition = r.headers.get("content-disposition") || "";
      const match = disposition.match(/filename="([^"]+)"/);
      const filename = match ? match[1] : "shotclassify-workspace.zip";
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setFlash({ kind: "ok", msg: "Export downloaded." });
    } catch (e) {
      const err = e as Error & { status?: number };
      setFlash({
        kind: "err",
        msg:
          err.status === 403
            ? "You need workspace owner or admin to export."
            : err.status === 401
              ? "Sign in to continue."
              : err.message || "Export failed.",
      });
    } finally {
      setBusy(null);
    }
  };

  const runDryRun = async () => {
    setBusy("dry");
    setFlash(null);
    setPreview(null);
    setResult(null);
    try {
      const otp = readMfaOtp();
      const headers: Record<string, string> = {};
      if (otp) headers["x-mfa-otp"] = otp;
      const r = await fetch("/api/workspace/data?dry_run=true", {
        method: "DELETE",
        headers,
        credentials: "same-origin",
      });
      const data = await r.json();
      if (!r.ok) {
        throw new Error(data?.detail || `${r.status}`);
      }
      setPreview(data as DryRunResult);
    } catch (e) {
      setFlash({ kind: "err", msg: (e as Error).message || "Preview failed." });
    } finally {
      setBusy(null);
    }
  };

  const runErase = async () => {
    if (!preview) return;
    if (confirmText !== "ERASE") {
      setFlash({ kind: "err", msg: "Type ERASE in the confirm field to proceed." });
      return;
    }
    setBusy("erase");
    setFlash(null);
    try {
      const otp = readMfaOtp();
      const headers: Record<string, string> = {};
      if (otp) headers["x-mfa-otp"] = otp;
      const r = await fetch("/api/workspace/data?confirm=erase", {
        method: "DELETE",
        headers,
        credentials: "same-origin",
      });
      const data = await r.json();
      if (!r.ok) {
        throw new Error(data?.detail || `${r.status}`);
      }
      setResult(data as DeleteResult);
      setPreview(null);
      setConfirmText("");
      setFlash({ kind: "ok", msg: "Workspace data erased." });
    } catch (e) {
      setFlash({ kind: "err", msg: (e as Error).message || "Erase failed." });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-8 sm:px-6 sm:py-12">
      <header className="mb-8 flex items-start gap-3">
        <Database
          weight="duotone"
          className="mt-1 h-7 w-7 shrink-0 text-zinc-700 dark:text-zinc-200"
          aria-hidden
        />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
            Workspace data
          </h1>
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
            Export everything stored for this workspace, or permanently
            erase it. Admin role and MFA step up are required.
          </p>
        </div>
      </header>

      {flash ? (
        <div
          role="status"
          className={`mb-6 flex items-start gap-2 rounded-md border px-3 py-2 text-sm ${
            flash.kind === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900/50 dark:bg-emerald-950/40 dark:text-emerald-200"
              : "border-rose-200 bg-rose-50 text-rose-900 dark:border-rose-900/50 dark:bg-rose-950/40 dark:text-rose-200"
          }`}
        >
          {flash.kind === "ok" ? (
            <CheckCircle weight="duotone" className="h-4 w-4 shrink-0" aria-hidden />
          ) : (
            <Warning weight="duotone" className="h-4 w-4 shrink-0" aria-hidden />
          )}
          <span>{flash.msg}</span>
        </div>
      ) : null}

      <section className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
        <div className="flex items-start gap-3">
          <FileZip
            weight="duotone"
            className="mt-1 h-5 w-5 text-zinc-600 dark:text-zinc-300"
            aria-hidden
          />
          <div className="flex-1">
            <h2 className="text-base font-medium text-zinc-900 dark:text-zinc-100">
              Export workspace
            </h2>
            <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
              Downloads a ZIP with classifications, audit log, saved views,
              members, API key metadata, and workspace settings.
            </p>
          </div>
          <button
            type="button"
            onClick={runExport}
            disabled={busy !== null}
            className="inline-flex items-center gap-1.5 rounded-md bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white shadow-sm transition hover:bg-zinc-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white"
          >
            <DownloadSimple weight="duotone" className="h-4 w-4" aria-hidden />
            {busy === "export" ? "Preparing..." : "Download ZIP"}
          </button>
        </div>
      </section>

      <section className="mt-6 rounded-lg border border-rose-200 bg-rose-50/40 p-5 shadow-sm dark:border-rose-900/50 dark:bg-rose-950/20">
        <div className="flex items-start gap-3">
          <Shield
            weight="duotone"
            className="mt-1 h-5 w-5 text-rose-600 dark:text-rose-300"
            aria-hidden
          />
          <div className="flex-1">
            <h2 className="text-base font-medium text-rose-900 dark:text-rose-100">
              Erase workspace data
            </h2>
            <p className="mt-1 text-sm text-rose-800/80 dark:text-rose-200/80">
              Removes every classification, saved view, audit row, and
              stored image blob for this workspace. Memberships, API keys,
              SSO, and IP allowlist are kept so you can still sign in.
              This cannot be undone.
            </p>
          </div>
        </div>

        <div className="mt-4 flex flex-col gap-3 sm:flex-row">
          <button
            type="button"
            onClick={runDryRun}
            disabled={busy !== null}
            className="inline-flex items-center justify-center gap-1.5 rounded-md border border-rose-300 bg-white px-3 py-1.5 text-sm font-medium text-rose-700 shadow-sm transition hover:bg-rose-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-600 disabled:cursor-not-allowed disabled:opacity-60 dark:border-rose-800 dark:bg-zinc-950 dark:text-rose-200 dark:hover:bg-rose-950/40"
          >
            <Eye weight="duotone" className="h-4 w-4" aria-hidden />
            {busy === "dry" ? "Counting..." : "Preview deletion"}
          </button>
        </div>

        {preview ? (
          <div className="mt-4 rounded-md border border-rose-200 bg-white p-4 text-sm dark:border-rose-900/50 dark:bg-zinc-950">
            <p className="font-medium text-zinc-900 dark:text-zinc-100">
              About to delete from{" "}
              <span className="font-mono">{preview.tenant_id}</span>
            </p>
            <ul className="mt-2 grid grid-cols-1 gap-1 text-zinc-700 dark:text-zinc-300 sm:grid-cols-3">
              <li>
                <span className="tabular-nums font-semibold">
                  {preview.would_delete.classifications.toLocaleString()}
                </span>{" "}
                classifications
              </li>
              <li>
                <span className="tabular-nums font-semibold">
                  {preview.would_delete.audit_log.toLocaleString()}
                </span>{" "}
                audit rows
              </li>
              <li>
                <span className="tabular-nums font-semibold">
                  {preview.would_delete.saved_views.toLocaleString()}
                </span>{" "}
                saved views
              </li>
            </ul>
            <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-400">
              Preserved: {preview.preserved.join(", ")}.
            </p>

            <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center">
              <label
                htmlFor="confirm-erase"
                className="text-sm text-zinc-700 dark:text-zinc-300"
              >
                Type{" "}
                <span className="font-mono font-semibold text-rose-700 dark:text-rose-300">
                  ERASE
                </span>{" "}
                to confirm:
              </label>
              <input
                id="confirm-erase"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                className="w-full rounded-md border border-zinc-300 bg-white px-2 py-1 font-mono text-sm focus:border-rose-500 focus:outline-none focus:ring-2 focus:ring-rose-200 dark:border-zinc-700 dark:bg-zinc-900 sm:w-40"
                placeholder="ERASE"
                autoComplete="off"
                spellCheck={false}
              />
              <button
                type="button"
                onClick={runErase}
                disabled={busy !== null || confirmText !== "ERASE"}
                className="inline-flex items-center justify-center gap-1.5 rounded-md bg-rose-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm transition hover:bg-rose-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-600 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Trash weight="duotone" className="h-4 w-4" aria-hidden />
                {busy === "erase" ? "Erasing..." : "Erase permanently"}
              </button>
            </div>
          </div>
        ) : null}

        {result ? (
          <div className="mt-4 rounded-md border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900 dark:border-emerald-900/50 dark:bg-emerald-950/40 dark:text-emerald-200">
            <p className="font-medium">
              Erased from{" "}
              <span className="font-mono">{result.tenant_id}</span>
            </p>
            <ul className="mt-2 grid grid-cols-1 gap-1 sm:grid-cols-3">
              <li>
                <span className="tabular-nums font-semibold">
                  {result.deleted.classifications.toLocaleString()}
                </span>{" "}
                classifications
              </li>
              <li>
                <span className="tabular-nums font-semibold">
                  {result.deleted.audit_log.toLocaleString()}
                </span>{" "}
                audit rows
              </li>
              <li>
                <span className="tabular-nums font-semibold">
                  {result.deleted.saved_views.toLocaleString()}
                </span>{" "}
                saved views
              </li>
            </ul>
          </div>
        ) : null}
      </section>

      <footer className="mt-8 flex items-start gap-2 text-xs text-zinc-500 dark:text-zinc-500">
        <Lock weight="duotone" className="mt-0.5 h-3.5 w-3.5" aria-hidden />
        <p>
          Every call to this page is recorded in the workspace audit log
          with your principal, IP, and timestamp.
        </p>
      </footer>
    </div>
  );
}
