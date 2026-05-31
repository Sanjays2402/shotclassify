import { ImageResponse } from "next/og";
import { fetchShareRecord } from "@/lib/share";
import { LONG, type Category } from "@/lib/categories";
import {
  ogTierColor,
  ogFmtFilename,
  ogTopThree,
  ogBarWidthPct,
} from "@/lib/og-share";

// Dynamic Open Graph image for public share pages at /r/<id>.
// Rendered server-side by Next 15 / Vercel OG. Linked automatically into
// <meta property="og:image"> and <meta name="twitter:image"> by Next.

export const runtime = "nodejs";
export const contentType = "image/png";
export const size = { width: 1200, height: 630 };
export const alt = "ShotClassify result";

type Params = { params: Promise<{ id: string }> };

const BG = "#0b0d10";
const FG = "#f4f4f5";
const MUTED = "#9ca3af";
const ACCENT = "#a3e635";

export default async function Image({ params }: Params) {
  const { id } = await params;
  const rec = await fetchShareRecord(id);

  // Render a clean "not found" card rather than failing the metadata fetch.
  if (!rec) {
    return new ImageResponse(
      (
        <div
          style={{
            width: "100%",
            height: "100%",
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            alignItems: "center",
            background: BG,
            color: FG,
            fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
          }}
        >
          <div style={{ fontSize: 56, fontWeight: 700 }}>Result not found</div>
          <div style={{ fontSize: 28, color: MUTED, marginTop: 16 }}>
            ShotClassify
          </div>
        </div>
      ),
      { ...size },
    );
  }

  const label = LONG[rec.primary_category as Category] ?? rec.primary_category;
  const confPct = `${(rec.confidence * 100).toFixed(1)}%`;
  const tier = ogTierColor(rec.confidence);
  const top = ogTopThree(rec.classification?.confidences);
  const filename = ogFmtFilename(rec.filename);
  const corrected = rec.user_corrected_to
    ? LONG[rec.user_corrected_to as Category] ?? rec.user_corrected_to
    : null;

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          background: BG,
          color: FG,
          padding: 64,
          fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <div
              style={{
                width: 44,
                height: 44,
                borderRadius: 12,
                background: ACCENT,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "#0b0d10",
                fontSize: 28,
                fontWeight: 800,
              }}
            >
              S
            </div>
            <div style={{ fontSize: 28, fontWeight: 600, letterSpacing: -0.5 }}>
              ShotClassify
            </div>
          </div>
          <div style={{ fontSize: 22, color: MUTED }}>{filename}</div>
        </div>

        {/* Main result */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            marginTop: 72,
            gap: 14,
          }}
        >
          <div style={{ fontSize: 28, color: MUTED }}>Primary category</div>
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: 28,
              flexWrap: "wrap",
            }}
          >
            <div
              style={{
                fontSize: 96,
                fontWeight: 800,
                letterSpacing: -2,
                lineHeight: 1,
              }}
            >
              {label}
            </div>
            <div
              style={{
                fontSize: 64,
                fontWeight: 700,
                color: tier,
                lineHeight: 1,
              }}
            >
              {confPct}
            </div>
          </div>
          {corrected && (
            <div style={{ fontSize: 24, color: MUTED, marginTop: 4 }}>
              User corrected to {corrected}
            </div>
          )}
        </div>

        {/* Top-3 bars */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 14,
            marginTop: 48,
          }}
        >
          {top.map((c) => {
            const lbl = LONG[c.category as Category] ?? c.category;
            const w = ogBarWidthPct(c.score);
            return (
              <div
                key={c.category}
                style={{ display: "flex", alignItems: "center", gap: 20 }}
              >
                <div
                  style={{
                    width: 220,
                    fontSize: 24,
                    color: MUTED,
                  }}
                >
                  {lbl}
                </div>
                <div
                  style={{
                    flex: 1,
                    height: 18,
                    background: "#1f2226",
                    borderRadius: 9,
                    display: "flex",
                  }}
                >
                  <div
                    style={{
                      width: `${w}%`,
                      height: "100%",
                      background: ogTierColor(c.score),
                      borderRadius: 9,
                    }}
                  />
                </div>
                <div
                  style={{
                    width: 90,
                    textAlign: "right",
                    fontSize: 22,
                    color: FG,
                  }}
                >
                  {(c.score * 100).toFixed(1)}%
                </div>
              </div>
            );
          })}
        </div>

        {/* Footer spacer */}
        <div style={{ flex: 1 }} />

        {/* Footer */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            fontSize: 22,
            color: MUTED,
            borderTop: "1px solid #1f2226",
            paddingTop: 20,
          }}
        >
          <div>shotclassify · screenshot classifier</div>
          <div>/r/{id.slice(0, 12)}</div>
        </div>
      </div>
    ),
    { ...size },
  );
}
