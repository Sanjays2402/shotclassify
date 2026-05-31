"use client";

import { useCallback, useState } from "react";
import { Link as LinkIcon, Check } from "@phosphor-icons/react/dist/ssr";

// Copy-link button for public share pages and shot detail pages.
// Uses navigator.clipboard with a graceful fallback.
export default function ShareActions({ id }: { id: string }) {
  const [copied, setCopied] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const onCopy = useCallback(async () => {
    setErr(null);
    const url =
      typeof window !== "undefined"
        ? `${window.location.origin}/r/${id}`
        : `/r/${id}`;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(url);
      } else {
        const ta = document.createElement("textarea");
        ta.value = url;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch (e: any) {
      setErr("Copy failed. Long-press the link instead.");
    }
  }, [id]);

  return (
    <div className="flex items-center gap-2">
      <a
        href={`/r/${id}`}
        className="num text-[11px] opacity-60 hover:opacity-100"
        title="Open public share page"
      >
        /r/{id.slice(0, 8)}
      </a>
      <button
        onClick={onCopy}
        aria-label="Copy share link"
        className="num text-[11px] inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-sm border focus:outline-none focus-visible:ring-2"
        style={{
          borderColor: "var(--color-rule)",
          background: copied ? "var(--color-ink)" : "transparent",
          color: copied ? "var(--color-chalk)" : "inherit",
        }}
      >
        {copied ? (
          <>
            <Check size={14} weight="duotone" /> Copied
          </>
        ) : (
          <>
            <LinkIcon size={14} weight="duotone" /> Copy share link
          </>
        )}
      </button>
      {err && (
        <span role="alert" className="text-[11px] opacity-70">
          {err}
        </span>
      )}
    </div>
  );
}
