"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

const CATS = [
  "receipt",
  "code_snippet",
  "error_stacktrace",
  "chat_screenshot",
  "meme",
  "document",
  "ui_mockup",
  "chart",
  "other",
];

export default function ReviewPage() {
  const { id } = useParams<{ id: string }>();
  const [rec, setRec] = useState<any>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetch(`/api/proxy/v1/history/${id}`).then((r) => r.json()).then(setRec);
  }, [id]);

  async function correct(cat: string) {
    setSaving(true);
    const fd = new FormData();
    fd.append("category", cat);
    await fetch(`/api/proxy/v1/classify/${id}/correct`, { method: "POST", body: fd });
    setSaving(false);
    const fresh = await fetch(`/api/proxy/v1/history/${id}`).then((r) => r.json());
    setRec(fresh);
  }

  if (!rec) return <div className="opacity-60 text-sm">loading…</div>;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <section className="glass p-4">
        <h1 className="text-lg font-semibold">{rec.filename}</h1>
        <div className="text-xs opacity-70 mt-1">
          {rec.primary_category} · {(rec.confidence * 100).toFixed(0)}%
          {rec.user_corrected_to && ` · user said ${rec.user_corrected_to}`}
        </div>
        <pre className="mt-3 text-[11px] glass p-3 max-h-[480px] overflow-auto whitespace-pre-wrap">
          {JSON.stringify(rec.extracted, null, 2)}
        </pre>
      </section>

      <section className="glass p-4 flex flex-col gap-3">
        <h2 className="font-medium">Re-classify</h2>
        <p className="text-xs opacity-70">
          Pick the correct category. Stored as labeled data for future fine-tunes.
        </p>
        <div className="flex flex-wrap gap-2">
          {CATS.map((c) => (
            <button
              key={c}
              disabled={saving}
              onClick={() => correct(c)}
              className={`cat-badge cursor-pointer disabled:opacity-50 ${
                rec.user_corrected_to === c ? "ring-2 ring-indigo-400" : ""
              }`}
            >
              {c}
            </button>
          ))}
        </div>

        <h3 className="font-medium mt-4">OCR</h3>
        <pre className="text-[11px] glass p-3 max-h-72 overflow-auto whitespace-pre-wrap">
          {rec.ocr_text || "(empty)"}
        </pre>
      </section>
    </div>
  );
}
