import Link from "next/link";

export default function NotFound() {
  return (
    <div className="panel p-8 flex flex-col gap-3 items-start">
      <div className="eyebrow">404 · shared result not found</div>
      <h1 className="h-display text-[22px]">No record on the books.</h1>
      <p className="text-[13px] opacity-70 max-w-[52ch]">
        This share link points to a result that was deleted, expired, or never
        existed. Classify a new screenshot to get your own shareable link.
      </p>
      <Link
        href="/upload"
        className="num text-[11px] px-3 py-1.5 rounded-sm"
        style={{ background: "var(--color-ink)", color: "var(--color-chalk)" }}
      >
        Classify a screenshot →
      </Link>
    </div>
  );
}
