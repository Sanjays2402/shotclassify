import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { fetchShareRecord } from "@/lib/share";
import { Chip } from "@/components/Chip";
import { ConfBar } from "@/components/ConfBar";
import ShareActions from "@/components/ShareActions";
import {
  CATEGORIES,
  LONG,
  SHORT,
  confColor,
  pct,
  shortId,
  type Category,
} from "@/lib/categories";

// Public share page. No auth, no cookies, server-rendered.
// URL shape: /r/<shot-id>

type Params = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { id } = await params;
  const rec = await fetchShareRecord(id);
  if (!rec) {
    return {
      title: "ShotClassify · result not found",
      robots: { index: false },
    };
  }
  const label = LONG[rec.primary_category as Category] ?? rec.primary_category;
  const conf = `${(rec.confidence * 100).toFixed(1)}%`;
  const title = `${label} · ${conf} · ShotClassify`;
  const desc = `Classified ${rec.filename} as ${label} with ${conf} confidence.`;
  const site = (process.env.NEXT_PUBLIC_SITE_URL || "").replace(/\/+$/, "");
  const canonical = site ? `${site}/r/${id}` : `/r/${id}`;
  const oembedHref = `${site}/api/oembed?url=${encodeURIComponent(canonical)}&format=json`;
  return {
    title,
    description: desc,
    openGraph: {
      title,
      description: desc,
      type: "article",
    },
    twitter: {
      card: "summary_large_image",
      title,
      description: desc,
    },
    alternates: {
      types: {
        "application/json+oembed": oembedHref,
      },
    },
  };
}

function fmt(iso: string) {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default async function PublicSharePage({ params }: Params) {
  const { id } = await params;
  const rec = await fetchShareRecord(id);

  if (!rec) {
    notFound();
  }

  const cat = (rec.primary_category as Category) ?? "other";
  const dist =
    rec.classification?.confidences ??
    CATEGORIES.map((c) => ({
      category: c,
      score: c === cat ? rec.confidence : (1 - rec.confidence) / (CATEGORIES.length - 1),
    }));
  const sortedDist = [...dist].sort((a, b) => b.score - a.score);
  const ocrText = rec.ocr?.text ?? rec.ocr_text ?? "";

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center justify-between gap-3 text-[12px] flex-wrap">
        <div className="flex items-center gap-3">
          <Link href="/" className="eyebrow hover:underline">
            ShotClassify
          </Link>
          <span className="opacity-40">/</span>
          <span className="eyebrow">shared result</span>
          <span className="opacity-40">/</span>
          <span className="num">{shortId(rec.id)}</span>
        </div>
        <ShareActions id={rec.id} />
      </div>

      <header className="panel p-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="eyebrow">The call</div>
          <div className="flex items-center gap-3 mt-1">
            <Chip cat={cat} size="lg" />
            <span
              className="num text-[28px]"
              style={{ color: confColor(rec.confidence) }}
            >
              {pct(rec.confidence, 1)}
            </span>
          </div>
          <h1 className="h-display text-[22px] mt-3 truncate max-w-[60ch]">
            {rec.filename}
          </h1>
          <div className="num text-[11px] opacity-70 mt-1">
            {fmt(rec.created_at)} · {rec.source ?? "api"}
          </div>
        </div>
        {rec.user_corrected_to && (
          <div className="text-right">
            <div className="eyebrow">Corrected to</div>
            <Chip cat={rec.user_corrected_to as Category} />
          </div>
        )}
      </header>

      <section className="grid lg:grid-cols-[1.4fr_1fr] gap-5">
        <div className="panel p-5">
          <div className="flex items-center justify-between mb-3">
            <span className="eyebrow">Confidence distribution</span>
            <span className="num text-[11px] opacity-60">
              {CATEGORIES.length} classes
            </span>
          </div>
          <ul className="flex flex-col gap-1.5">
            {sortedDist.map((d) => (
              <li
                key={d.category}
                className="grid grid-cols-[110px_1fr_64px] items-center gap-3"
              >
                <Chip cat={d.category as Category} />
                <div
                  style={{
                    ["--bar" as any]: `var(--color-cat-${d.category.split("_")[0]})`,
                  }}
                >
                  <ConfBar score={+(d.score * 100).toFixed(2)} />
                </div>
                <span className="num text-[12px] text-right">
                  {pct(d.score, 2)}
                </span>
              </li>
            ))}
          </ul>
        </div>

        <div className="flex flex-col gap-5">
          <div className="panel p-5">
            <div className="eyebrow mb-2">OCR transcript</div>
            <pre className="text-[12px] whitespace-pre-wrap leading-snug max-h-[260px] overflow-auto">
{ocrText || "(no OCR text on record)"}
            </pre>
          </div>

          <div className="panel-dark p-5">
            <div className="eyebrow mb-2" style={{ color: "var(--color-chalk)" }}>
              Want your own?
            </div>
            <p className="text-[12px] opacity-90 leading-relaxed mb-3">
              Classify your own screenshots with confidence scores, OCR, and
              field extraction.
            </p>
            <Link
              href="/upload"
              className="inline-block num text-[11px] px-3 py-1.5 rounded-sm"
              style={{
                background: "var(--color-chalk)",
                color: "var(--color-ink)",
              }}
            >
              Try ShotClassify →
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
