import { confColor } from "@/lib/categories";

export function ConfBar({ score }: { score: number }) {
  const w = Math.max(0, Math.min(1, score)) * 100;
  return (
    <div className="conf-bar" aria-label={`Confidence ${(score * 100).toFixed(1)}%`}>
      <span style={{ width: `${w}%`, background: confColor(score) }} />
    </div>
  );
}
