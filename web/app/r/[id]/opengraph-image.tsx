import { ImageResponse } from "next/og";
import { fetchShareRecord } from "@/lib/share";
import { CATEGORIES, LONG, SHORT, type Category } from "@/lib/categories";

export const runtime = "nodejs";
export const alt = "ShotClassify result";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

// Palette mirrors the broadcast theme tokens in globals.css so the share card
// looks like a still frame pulled straight from the app.
const COLORS = {
  chalk: "#f5f1e8",
  felt: "#0b3d2e",
  feltRail: "#082a20",
  ink: "#101010",
  rule: "#d8d2c1",
  amber: "#f3a712",
  confHigh: "#1f8f4c",
  confMid: "#d68910",
  confLow: "#b03a2e",
};

function confColor(score: number): string {
  if (score >= 0.8) return COLORS.confHigh;
  if (score >= 0.55) return COLORS.confMid;
  return COLORS.confLow;
}

function truncate(s: string, n: number): string {
  if (!s) return "";
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

type Params = { params: Promise<{ id: string }> };

export default async function OgImage({ params }: Params) {
  const { id } = await params;
  const rec = await fetchShareRecord(id);

  if (!rec) {
    return new ImageResponse(
      (
        <div
          style={{
            width: "100%",
            height: "100%",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            background: COLORS.chalk,
            color: COLORS.ink,
            fontFamily: "sans-serif",
          }}
        >
          <div style={{ fontSize: 36, opacity: 0.6, letterSpacing: 2 }}>
            SHOTCLASSIFY
          </div>
          <div style={{ fontSize: 64, fontWeight: 700, marginTop: 20 }}>
            Result not found
          </div>
        </div>
      ),
      { ...size },
    );
  }

  const cat = (rec.primary_category as Category) ?? "other";
  const label = LONG[cat] ?? rec.primary_category;
  const short = SHORT[cat] ?? rec.primary_category.toUpperCase();
  const confPct = (rec.confidence * 100).toFixed(1) + "%";
  const cColor = confColor(rec.confidence);

  const dist =
    rec.classification?.confidences ??
    CATEGORIES.map((c) => ({
      category: c,
      score: c === cat ? rec.confidence : (1 - rec.confidence) / (CATEGORIES.length - 1),
    }));
  const top = [...dist].sort((a, b) => b.score - a.score).slice(0, 4);

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          background: COLORS.chalk,
          color: COLORS.ink,
          fontFamily: "sans-serif",
          padding: 56,
          position: "relative",
        }}
      >
        {/* Top bar: brand + ID */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            paddingBottom: 20,
            borderBottom: `2px solid ${COLORS.rule}`,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div
              style={{
                width: 18,
                height: 18,
                borderRadius: 9999,
                background: COLORS.felt,
                boxShadow: `inset 0 0 0 3px ${COLORS.chalk}, 0 0 0 2px ${COLORS.feltRail}`,
              }}
            />
            <div
              style={{
                fontSize: 28,
                fontWeight: 700,
                letterSpacing: 2,
              }}
            >
              SHOTCLASSIFY
            </div>
          </div>
          <div
            style={{
              fontSize: 20,
              fontFamily: "monospace",
              color: "#666",
              letterSpacing: 1,
            }}
          >
            /r/{id.slice(0, 12)}
          </div>
        </div>

        {/* Main: category + confidence */}
        <div
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            gap: 48,
            marginTop: 56,
          }}
        >
          {/* Category badge */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              background: COLORS.felt,
              color: COLORS.chalk,
              width: 280,
              height: 280,
              borderRadius: 24,
              boxShadow: `inset 0 0 0 6px ${COLORS.feltRail}`,
            }}
          >
            <div style={{ fontSize: 18, letterSpacing: 3, opacity: 0.7 }}>
              PRIMARY
            </div>
            <div
              style={{
                fontSize: 56,
                fontWeight: 800,
                marginTop: 12,
                letterSpacing: 1,
              }}
            >
              {short}
            </div>
          </div>

          {/* Label + confidence */}
          <div style={{ display: "flex", flexDirection: "column", flex: 1 }}>
            <div style={{ fontSize: 26, color: "#666", letterSpacing: 1 }}>
              CLASSIFIED AS
            </div>
            <div
              style={{
                fontSize: 76,
                fontWeight: 800,
                lineHeight: 1.05,
                marginTop: 6,
              }}
            >
              {label}
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "baseline",
                gap: 18,
                marginTop: 26,
              }}
            >
              <div
                style={{
                  fontSize: 92,
                  fontWeight: 800,
                  color: cColor,
                  fontFamily: "monospace",
                  lineHeight: 1,
                }}
              >
                {confPct}
              </div>
              <div style={{ fontSize: 22, color: "#666", letterSpacing: 2 }}>
                CONFIDENCE
              </div>
            </div>
          </div>
        </div>

        {/* Distribution bars */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 10,
            marginTop: 44,
          }}
        >
          {top.map((d) => {
            const w = Math.max(0.02, d.score) * 100;
            const isTop = d.category === cat;
            return (
              <div
                key={d.category}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 14,
                  fontSize: 18,
                }}
              >
                <div
                  style={{
                    width: 160,
                    fontFamily: "monospace",
                    letterSpacing: 1,
                    color: isTop ? COLORS.ink : "#888",
                    fontWeight: isTop ? 700 : 500,
                  }}
                >
                  {SHORT[d.category as Category] ?? d.category.toUpperCase()}
                </div>
                <div
                  style={{
                    display: "flex",
                    flex: 1,
                    height: 18,
                    background: "#e6e0d0",
                    borderRadius: 4,
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      width: `${w}%`,
                      background: isTop ? cColor : "#b8b0a0",
                    }}
                  />
                </div>
                <div
                  style={{
                    width: 90,
                    textAlign: "right",
                    fontFamily: "monospace",
                    color: isTop ? COLORS.ink : "#888",
                    fontWeight: isTop ? 700 : 500,
                  }}
                >
                  {(d.score * 100).toFixed(1)}%
                </div>
              </div>
            );
          })}
        </div>

        {/* Footer */}
        <div
          style={{
            position: "absolute",
            bottom: 32,
            left: 56,
            right: 56,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            fontSize: 18,
            color: "#666",
            paddingTop: 16,
            borderTop: `1px solid ${COLORS.rule}`,
          }}
        >
          <div
            style={{
              fontFamily: "monospace",
              maxWidth: 720,
              overflow: "hidden",
              whiteSpace: "nowrap",
              textOverflow: "ellipsis",
            }}
          >
            {truncate(rec.filename || "shot", 60)}
          </div>
          <div style={{ display: "flex", gap: 18, alignItems: "center" }}>
            {rec.elapsed_ms ? (
              <div style={{ fontFamily: "monospace" }}>
                {rec.elapsed_ms < 1000
                  ? `${rec.elapsed_ms} ms`
                  : `${(rec.elapsed_ms / 1000).toFixed(2)} s`}
              </div>
            ) : null}
            <div style={{ letterSpacing: 2 }}>shotclassify.app</div>
          </div>
        </div>
      </div>
    ),
    { ...size },
  );
}
