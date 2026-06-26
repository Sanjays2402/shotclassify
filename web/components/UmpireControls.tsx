"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { useSWRConfig } from "swr";
import {
  ArrowsClockwise,
  CheckCircle,
  Flag,
  Warning,
} from "@phosphor-icons/react/dist/ssr";
import { Chip } from "@/components/Chip";
import { CATEGORIES, LONG, type Category } from "@/lib/categories";
import { ENDPOINTS } from "@/lib/api";

type Props = {
  id: string;
  primary: Category;
  corrected?: Category | null;
  /** Disable everything (sample / non-persisted shot). */
  disabled?: boolean;
  /** Rendered inside a CollapsibleSection (F77): drop the panel chrome +
   * the redundant "Umpire room" header since the section already labels it. */
  embedded?: boolean;
};

type Status =
  | { kind: "idle" }
  | { kind: "ok"; msg: string }
  | { kind: "err"; msg: string };

export function UmpireControls({ id, primary, corrected, disabled, embedded }: Props) {
  const router = useRouter();
  const { mutate } = useSWRConfig();
  const [pending, startTransition] = useTransition();
  const [busy, setBusy] = useState<"correct" | "reclassify" | null>(null);
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [pick, setPick] = useState<Category>(corrected ?? primary);

  const refresh = () => {
    mutate(ENDPOINTS.historyItem(id));
    mutate(
      (key) => typeof key === "string" && key.startsWith("/api/history"),
      undefined,
      { revalidate: true }
    );
    startTransition(() => router.refresh());
  };

  const onCorrect = async () => {
    if (disabled || busy) return;
    setBusy("correct");
    setStatus({ kind: "idle" });
    try {
      const fd = new FormData();
      fd.append("category", pick);
      const r = await fetch(`/api/shots/${encodeURIComponent(id)}/correct`, {
        method: "POST",
        body: fd,
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t || `${r.status}`);
      }
      setStatus({ kind: "ok", msg: `Called it ${LONG[pick]}. Logged for calibration.` });
      refresh();
    } catch (e: any) {
      setStatus({ kind: "err", msg: e?.message || "Correction failed." });
    } finally {
      setBusy(null);
    }
  };

  const onReclassify = async () => {
    if (disabled || busy) return;
    setBusy("reclassify");
    setStatus({ kind: "idle" });
    try {
      const r = await fetch(`/api/shots/${encodeURIComponent(id)}/reclassify`, {
        method: "POST",
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t || `${r.status}`);
      }
      const data = await r.json().catch(() => null);
      const next = data?.classification?.primary as Category | undefined;
      setStatus({
        kind: "ok",
        msg: next
          ? `Replay called ${LONG[next]}.`
          : "Replay complete.",
      });
      refresh();
    } catch (e: any) {
      setStatus({ kind: "err", msg: e?.message || "Reclassification failed." });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className={embedded ? "" : "panel p-5"}>
      {embedded ? (
        corrected ? (
          <div className="flex items-center justify-end mb-3">
            <span className="num text-[10px] opacity-60">
              on file: {LONG[corrected]}
            </span>
          </div>
        ) : null
      ) : (
        <div className="flex items-center justify-between mb-3">
          <span className="eyebrow inline-flex items-center gap-1.5">
            <Flag size={14} weight="duotone" /> Umpire room
          </span>
          {corrected && (
            <span className="num text-[10px] opacity-60">
              on file: {LONG[corrected]}
            </span>
          )}
        </div>
      )}

      <p className="text-[12px] opacity-75 leading-snug mb-3">
        Disagree with the call? Mark the true class to feed calibration, or rerun the
        pipeline on the saved frame.
      </p>

      <label className="block">
        <span className="eyebrow text-[10px]">True class</span>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {CATEGORIES.map((c) => {
            const active = c === pick;
            return (
              <button
                key={c}
                type="button"
                onClick={() => setPick(c)}
                disabled={disabled || !!busy}
                aria-pressed={active}
                className="transition-opacity"
                style={{
                  opacity: active ? 1 : 0.55,
                  outline: active ? "2px solid var(--color-ink)" : "none",
                  outlineOffset: 2,
                  borderRadius: 3,
                  cursor: disabled ? "not-allowed" : "pointer",
                }}
              >
                <Chip cat={c} />
              </button>
            );
          })}
        </div>
      </label>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onCorrect}
          disabled={disabled || !!busy || pick === corrected}
          className="btn btn-cue inline-flex items-center gap-1.5"
        >
          <CheckCircle size={14} weight="duotone" />
          {busy === "correct" ? "Logging…" : "Make the call"}
        </button>
        <button
          type="button"
          onClick={onReclassify}
          disabled={disabled || !!busy}
          className="btn inline-flex items-center gap-1.5"
          style={{
            background: "transparent",
            borderColor: "rgba(11,15,12,0.25)",
          }}
        >
          <ArrowsClockwise size={14} weight="duotone" />
          {busy === "reclassify" ? "Running replay…" : "Rerun the pitch"}
        </button>
      </div>

      {disabled && (
        <div className="mt-3 text-[11px] opacity-60">
          Sample shot. Upload a real frame to enable corrections.
        </div>
      )}

      {status.kind === "ok" && (
        <div
          role="status"
          className="mt-3 text-[12px] inline-flex items-center gap-1.5"
          style={{ color: "var(--color-cue)" }}
        >
          <CheckCircle size={14} weight="duotone" /> {status.msg}
        </div>
      )}
      {status.kind === "err" && (
        <div
          role="alert"
          className="mt-3 text-[12px] inline-flex items-center gap-1.5"
          style={{ color: "var(--color-foul, #b91c1c)" }}
        >
          <Warning size={14} weight="duotone" /> {status.msg}
        </div>
      )}
      {pending && (
        <div className="mt-2 text-[10px] num opacity-50">Refreshing box score…</div>
      )}
    </div>
  );
}
