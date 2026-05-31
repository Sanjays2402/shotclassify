import { ImageResponse } from "next/og";
import { fetchShareRecord } from "@/lib/share";
import { LONG, SHORT } from "@/lib/categories";

export const runtime = "nodejs";
export const alt = "ShotClassify shared result";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

// Static category color map (mirrors --color-cat-* vars).
const CAT_COLORS: Record<string, string> = {
  receipt: "#0e5c3a",
  code_snippet: "#1d3b8a",
  error_stacktrace: "#a8261c",
  chat_screenshot: "#7b2d8e",
  meme: "#d97706",
  document: "#374151",
  ui_mockup: "#0891b2",
  chart: "#16a34a",
  other: "#525252",
};

export default async function OG({ params }: { params: { id: string } }) {
  const rec = await fetchShareRecord(params.id);

  if (!rec) {
    return new ImageResponse(
      (
        <div
          style={{
            width: "100%",
            height: "100%",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "#f6f3ec",
            color: "#0b0f0c",
            fontSize: 48,
            fontFamily: "sans-serif",
          }}
        >
          ShotClassify · result not found
        </div>
      ),
      size
    );
  }

  const cat = rec.primary_category;
  const color = CAT_COLORS[cat.split("_")[0]] ?? CAT_COLORS[cat] ?? "#0e5c3a";
  const label = LONG[cat as keyof typeof LONG] ?? cat;
  const short = SHORT[cat as keyof typeof SHORT] ?? cat.toUpperCase();
  const conf = `${(rec.confidence * 100).toFixed(1)}%`;

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          background: "#f6f3ec",
          color: "#0b0f0c",
          fontFamily: "sans-serif",
          padding: 64,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            fontSize: 22,
            letterSpacing: 2,
            textTransform: "uppercase",
            opacity: 0.7,
          }}
        >
          <span>ShotClassify</span>
          <span>shared result</span>
        </div>

        <div
          style={{
            display: "flex",
            flexDirection: "column",
            marginTop: 60,
            gap: 24,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 24,
            }}
          >
            <div
              style={{
                background: color,
                color: "#fff",
                padding: "12px 24px",
                fontSize: 36,
                fontWeight: 700,
                letterSpacing: 2,
                borderRadius: 4,
                display: "flex",
              }}
            >
              {short}
            </div>
            <div
              style={{
                fontSize: 96,
                fontWeight: 700,
                color,
                fontVariantNumeric: "tabular-nums",
                display: "flex",
              }}
            >
              {conf}
            </div>
          </div>

          <div
            style={{
              fontSize: 44,
              fontWeight: 600,
              maxWidth: 1000,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              display: "flex",
            }}
          >
            {rec.filename}
          </div>

          <div style={{ fontSize: 26, opacity: 0.7, display: "flex" }}>
            Classified as {label}
          </div>
        </div>

        <div
          style={{
            marginTop: "auto",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-end",
            fontSize: 20,
            opacity: 0.6,
          }}
        >
          <span>shotclassify · screenshot intelligence</span>
          <span style={{ fontVariantNumeric: "tabular-nums" }}>
            #{rec.id.slice(0, 8)}
          </span>
        </div>
      </div>
    ),
    size
  );
}
