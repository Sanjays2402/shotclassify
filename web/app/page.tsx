"use client";

import { useCallback, useRef, useState } from "react";
import Dropzone from "@/components/Dropzone";
import ResultCard from "@/components/ResultCard";
import EmptyState from "@/components/EmptyState";

type Result = any;

export default function HomePage() {
  const [results, setResults] = useState<Result[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const onFiles = useCallback(async (files: File[]) => {
    if (!files.length) return;
    setBusy(true);
    setError(null);
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const settled = await Promise.allSettled(
        files.map(async (f) => {
          const fd = new FormData();
          fd.append("file", f);
          const res = await fetch("/api/classify", {
            method: "POST",
            body: fd,
            signal: ctrl.signal,
          });
          if (!res.ok) throw new Error(await res.text());
          return res.json();
        })
      );
      const ok = settled
        .filter((s): s is PromiseFulfilledResult<any> => s.status === "fulfilled")
        .map((s) => s.value);
      const failed = settled.filter((s) => s.status === "rejected");
      if (failed.length) setError(`${failed.length} of ${files.length} failed`);
      setResults((cur) => [...ok, ...cur]);
    } catch (e: any) {
      setError(e?.message ?? "Upload failed.");
    } finally {
      setBusy(false);
    }
  }, []);

  return (
    <div className="flex flex-col gap-6">
      <Dropzone onFiles={onFiles} busy={busy} />
      {error && (
        <div className="glass p-3 text-sm text-red-500">{error}</div>
      )}
      {results.length === 0 && !busy ? (
        <EmptyState />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {results.map((r) => (
            <ResultCard key={r.id} result={r} />
          ))}
        </div>
      )}
    </div>
  );
}
