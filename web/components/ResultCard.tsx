"use client";

import { useState } from "react";
import {
  Receipt,
  Code,
  Bug,
  Chat,
  Image as ImageIcon,
  FileText,
  Chart,
  Frame,
  Question,
  CheckCircle,
} from "@/components/icons";

const ICONS: Record<string, any> = {
  receipt: Receipt,
  code_snippet: Code,
  error_stacktrace: Bug,
  chat_screenshot: Chat,
  meme: ImageIcon,
  document: FileText,
  ui_mockup: Frame,
  chart: Chart,
  other: Question,
};

export default function ResultCard({ result }: { result: any }) {
  const [showOcr, setShowOcr] = useState(false);
  const cat = result?.classification?.primary ?? "other";
  const Icon = ICONS[cat] ?? Question;
  const conf =
    result?.classification?.confidences?.find((c: any) => c.category === cat)?.score ?? 0;
  const fields = result?.extracted ?? {};
  const route = result?.route ?? {};

  return (
    <article className="glass p-4 flex flex-col gap-3">
      <header className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className="cat-badge">
            <Icon className="w-3.5 h-3.5" />
            {cat}
          </span>
          <span className="text-xs opacity-60 truncate">{result.filename}</span>
        </div>
        <span className="text-xs opacity-70">{(conf * 100).toFixed(0)}%</span>
      </header>

      <ExtractedView category={cat} fields={fields} />

      <footer className="flex items-center justify-between text-xs">
        <div className="flex items-center gap-2 opacity-80">
          <CheckCircle className="w-3.5 h-3.5" />
          <span>
            {route.action} · {route.dry_run ? "dry-run" : route.executed ? "executed" : "skipped"}
          </span>
        </div>
        <button
          className="underline opacity-70 hover:opacity-100"
          onClick={() => setShowOcr((v) => !v)}
        >
          {showOcr ? "hide" : "show"} OCR
        </button>
      </footer>

      {showOcr && (
        <pre className="glass p-3 text-[11px] whitespace-pre-wrap max-h-56 overflow-auto">
          {result?.ocr?.text || "(empty)"}
        </pre>
      )}
    </article>
  );
}

function ExtractedView({ category, fields }: { category: string; fields: any }) {
  if (category === "receipt" && fields.receipt) {
    const r = fields.receipt;
    return (
      <div className="grid grid-cols-2 gap-2 text-sm">
        <Field label="Vendor" value={r.vendor} />
        <Field label="Date" value={r.date} />
        <Field label="Total" value={r.total ? `${r.total} ${r.currency ?? ""}` : null} />
        <Field label="Tax" value={r.tax} />
        {r.items?.length ? (
          <div className="col-span-2 text-xs opacity-80">
            {r.items.slice(0, 6).map((it: any, i: number) => (
              <div key={i} className="flex justify-between border-b border-white/5 py-0.5">
                <span>{it.description}</span>
                <span>{it.price}</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    );
  }
  if (category === "code_snippet" && fields.code) {
    return (
      <div className="text-sm">
        <Field label="Language" value={fields.code.language} />
        <pre className="glass mt-2 p-3 text-[11px] whitespace-pre-wrap max-h-64 overflow-auto">
          {fields.code.code}
        </pre>
      </div>
    );
  }
  if (category === "error_stacktrace" && fields.error) {
    const e = fields.error;
    return (
      <div className="grid grid-cols-2 gap-2 text-sm">
        <Field label="Framework" value={e.framework} />
        <Field label="Exception" value={e.exception} />
        <Field label="File" value={e.file ? `${e.file}:${e.line ?? "?"}` : null} />
        <Field label="Likely cause" value={e.likely_cause} />
        {e.message && (
          <div className="col-span-2 text-xs opacity-80 truncate">{e.message}</div>
        )}
      </div>
    );
  }
  if (category === "chat_screenshot" && fields.chat) {
    return (
      <div className="text-sm">
        <Field label="Platform" value={fields.chat.platform} />
        <Field label="People" value={(fields.chat.participants || []).join(", ")} />
      </div>
    );
  }
  return (
    <div className="text-xs opacity-70">
      Structured fields not produced for this category.
    </div>
  );
}

function Field({ label, value }: { label: string; value: any }) {
  return (
    <div>
      <div className="text-[10px] uppercase opacity-50 tracking-wider">{label}</div>
      <div className="text-sm">{value ?? <span className="opacity-50">—</span>}</div>
    </div>
  );
}
